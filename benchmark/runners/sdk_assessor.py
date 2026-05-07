"""SDK-based assessor helper. Use this for v1.3 and any "serious" run.

The CLI path (`pilot_a/score.py:call_assessor`, `truncation_experiment.py:
call_assessor_stdin`) shells out to `claude -p`, which doesn't expose a
temperature flag — those calls run at the API default of temperature=1.0.
That's fine for plausibility checks but bad for evaluation: high-temp
sampling produces measurable run-to-run variance on borderline verdicts.
The 2026-05-07 Sonnet@FT spin-off measured ~13% within-model verdict flips
on identical inputs (`docs/retrospectives/2026-05-07-sonnet-at-ft-on-22-flipped.md`).

This module is the canonical SDK path: temperature=0, direct Anthropic SDK,
same prompt as the CLI helpers. Returns the same dict shape so callers can
swap CLI for SDK without changing their downstream code.

Existing CLI helpers stay in place for legacy / sealed-v1 reproducibility:
  - `pilot_a/score.py:call_assessor` (v1 scoring, sealed)
  - `truncation_experiment.py:call_assessor_stdin` (v1 truncation experiment, sealed)

Anything new — v1.3 model runs, gold-pair scoring at FT, sonnet-on-200,
calibration-pilot work — should call `call_assessor_sdk` from this module.

Requires `ANTHROPIC_API_KEY` in `.env` or environment.

Note on determinism: temperature=0 reduces sampling variance but is **not**
fully deterministic. Anthropic's infrastructure has batching / numerical-
precision nondeterminism that survives temperature=0. Expect some residual
flip rate on identical inputs (anecdotally ~1-3%, well below CLI's ~13%).
Budget for drift sampling on long runs.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load .env so ANTHROPIC_API_KEY is available. override=True needed on
# Windows because the var may exist as "" in the system environment.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

import anthropic  # noqa: E402

# Single source of truth for the prompt: pilot_a/score.py defines it,
# everything else imports from there. Identical to calibrate_assessor.py's
# inlined copy as of 2026-05-07 (verified by string equality).
sys.path.insert(0, str(PROJECT_ROOT))
from benchmark.pilot_a.score import ASSESSMENT_PROMPT  # noqa: E402

# Model IDs and pricing (USD per million tokens, May 2026). Update with
# the latest Anthropic pricing as model versions advance.
MODEL_SPECS: dict[str, dict[str, Any]] = {
    "sonnet": {
        "model_id": "claude-sonnet-4-6",
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
    },
    "opus": {
        "model_id": "claude-opus-4-7",
        "input_per_mtok": 15.0,
        "output_per_mtok": 75.0,
    },
    "haiku": {
        "model_id": "claude-haiku-4-5-20251001",
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
    },
}

# Same regex pilot_a/score.py and calibrate_assessor.py use.
_VERDICT_RE = re.compile(r"\{[^{}]*assessment[^{}]*\}", re.DOTALL)


def _parse_verdict(text: str) -> tuple[str | None, str]:
    """Extract (assessment, rationale) from the model's JSON response.
    Falls back to bare-color detection if JSON parse fails.
    """
    m = _VERDICT_RE.search(text or "")
    if m:
        try:
            j = json.loads(m.group(0))
            return j.get("assessment"), j.get("rationale", "")
        except json.JSONDecodeError:
            pass
    for color in ("Red", "Yellow", "Green"):
        if color in (text or ""):
            return color, (text or "")[:200]
    return None, (text or "")[:200]


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing from environment / .env. "
            "Add it to .env at repo root."
        )
    return anthropic.Anthropic()


def call_assessor_sdk(
    proposition: str,
    case_name_citation: str,
    opinion_text: str,
    *,
    model: str = "sonnet",
    max_tokens: int = 512,
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """Call the substance assessor via Anthropic SDK at temperature=0.

    Returns a dict with the same shape as the CLI helpers
    (`pilot_a/score.py:call_assessor`, `truncation_experiment.py:
    call_assessor_stdin`):

        {
            "assessment": "Green" | "Yellow" | "Red" | None,
            "rationale": str,
            "elapsed_s": float,
            "cost_usd": float,
        }

    Drop-in for callers that previously used the CLI helpers, with two
    notable differences callers should be aware of:
      - temperature=0 (vs CLI's default 1.0)
      - direct API call (vs subprocess), so no Windows arg-length limit
        and no CLAUDE.md context bleed-in
    """
    if model not in MODEL_SPECS:
        raise ValueError(f"Unknown model {model!r}. Choose from {list(MODEL_SPECS)}.")
    spec = MODEL_SPECS[model]
    cli = client if client is not None else _client()

    prompt = ASSESSMENT_PROMPT.format(
        proposition=proposition,
        case_name_citation=case_name_citation,
        opinion_text=opinion_text or "(opinion text unavailable)",
    )

    start = time.time()
    try:
        resp = cli.messages.create(
            model=spec["model_id"],
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return {
            "assessment": None,
            "rationale": f"API_ERROR: {exc!r}",
            "elapsed_s": round(time.time() - start, 1),
            "cost_usd": 0.0,
        }
    elapsed = time.time() - start

    text = ""
    if resp.content:
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text += block.text

    assessment, rationale = _parse_verdict(text)

    in_tok = getattr(resp.usage, "input_tokens", 0) or 0
    out_tok = getattr(resp.usage, "output_tokens", 0) or 0
    cost = (
        in_tok * spec["input_per_mtok"] / 1_000_000
        + out_tok * spec["output_per_mtok"] / 1_000_000
    )

    return {
        "assessment": assessment,
        "rationale": rationale,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": round(cost, 6),
    }


if __name__ == "__main__":
    # Self-check: tiny smoke test, prints result.
    out = call_assessor_sdk(
        proposition="The Court held that summary judgment is appropriate when there is no genuine dispute as to any material fact.",
        case_name_citation="Anderson v. Liberty Lobby, Inc., 477 U.S. 242 (1986)",
        opinion_text=(
            "We hold that the standard for summary judgment under Rule 56 mirrors "
            "the standard for a directed verdict: the inquiry is whether the evidence "
            "presents a sufficient disagreement to require submission to a jury or "
            "whether it is so one-sided that one party must prevail as a matter of law."
        ),
        model="sonnet",
    )
    print(json.dumps(out, indent=2))
