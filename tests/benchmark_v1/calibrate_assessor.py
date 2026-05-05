"""Calibration study: can Sonnet 4.6 or Haiku 4.5 reproduce v1's Opus
verdicts well enough to replace Opus as the substance assessor?

Acceptance bar (from `docs/plans/benchmark-roadmap.md` v1.2):
    overall agreement >= 90% AND Red agreement >= 85%

Reads:
- `benchmark/releases/v1/results.csv` (v1 cells; `supports` column = Opus verdict)
- `benchmark/releases/v1/dataset.csv` (used for `canonical_dataset_ids()` dedup)
- `benchmark/releases/v1/citing_opinion_cache/<cluster_id>.txt` (cached opinion text)

Writes:
- `benchmark/releases/v1/calibration_results.csv` (per-row, resume-safe — append-only)

Run from repo root, with `ANTHROPIC_API_KEY` in `.env`:

    venv/Scripts/python.exe tests/benchmark_v1/calibrate_assessor.py \\
        [--models sonnet,haiku]  (default: both)
        [--dry-run]              (cost estimate only)
        [--limit N]              (smoke-test first N cells per model)

Aggregation (confusion matrices, kappa, decision) lives in a separate
script (`calibrate_assessor_report.py`) so re-running the report doesn't
require re-running the API calls.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env so ANTHROPIC_API_KEY is available. override=True is needed
# on Windows because the key may exist as an empty string in the system
# environment, and dotenv won't replace pre-set vars by default.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass  # python-dotenv is in deps, but tolerate absence in case of editable install drift

# canonical_dataset_ids() lives in scorecard.py — reuse the same dedup rule v1 uses.
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "benchmark_v1"))
from scorecard import canonical_dataset_ids  # noqa: E402

import anthropic  # noqa: E402

BENCH = PROJECT_ROOT / "benchmark" / "releases" / "v1"
RESULTS_CSV = BENCH / "results.csv"
# v1's score.py used pilot_a's cache for CITED opinion text. The
# benchmark/releases/v1/citing_opinion_cache directory holds CITING-court opinions
# used during dataset mining — different artifact, do not confuse.
OPINION_CACHE = PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache"
OUT_CSV = BENCH / "calibration_results.csv"

# Same truncation v1's Opus calls used. Keeps the comparison apples-to-apples.
MAX_OPINION_CHARS = 20000

# Direct API model IDs and pricing (USD per million tokens, as of May 2026).
MODEL_SPECS = {
    "sonnet": {
        "model_id": "claude-sonnet-4-6",
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
    },
    "haiku": {
        "model_id": "claude-haiku-4-5-20251001",
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
    },
}

ASSESSMENT_PROMPT = """You are a legal-research auditor. You will be given:
  1. A legal proposition (the claim being made).
  2. A case name + citation that someone offered in support.
  3. An excerpt from the cited case's opinion text.

Your job: decide whether the cited case substantively supports the proposition.

Score:
  - Green: case directly and accurately supports the proposition.
  - Yellow: partially relevant; support is weaker than represented, or the
    proposition slightly overstates what the case held.
  - Red: case does not support the proposition; case addresses a completely
    different topic; or no on-point passage exists in the excerpt.

Respond with ONLY a single-line JSON object. No prose, no markdown.
Format: {{"assessment": "Green|Yellow|Red", "rationale": "one short sentence"}}

PROPOSITION:
{proposition}

CITED CASE:
{case_name_citation}

OPINION TEXT (excerpt, may be truncated):
{opinion_text}
"""

OUT_FIELDS = [
    "id",
    "model_under_test",  # which v1 model produced model_response (sonnet/opus/gpt-5)
    "candidate_model",   # which assessor we're calibrating (sonnet/haiku)
    "opus_verdict",
    "candidate_verdict",
    "candidate_rationale",
    "agree",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "elapsed_s",
    "error",
]


def load_candidate_cells() -> list[dict]:
    """v1 cells filtered to (a) deduped canonical examples and (b) cells
    where Opus's assessor fired (`supports` column populated)."""
    keep_ids = canonical_dataset_ids()
    rows = list(csv.DictReader(RESULTS_CSV.open(encoding="utf-8")))
    cells = []
    for r in rows:
        if r.get("id") not in keep_ids:
            continue
        if not r.get("supports"):
            continue
        cells.append(r)
    return cells


def load_existing_calibration() -> set[tuple[str, str, str]]:
    """(id, model_under_test, candidate_model) triples already in the output.

    The cell key is (id, model_under_test) because each v1 example has
    up to three cells (one per model under test) with different
    model_responses → different assessor input. Within a candidate-model
    run, those cells must be scored independently.
    """
    if not OUT_CSV.exists():
        return set()
    seen = set()
    with OUT_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            seen.add((r["id"], r.get("model_under_test", ""), r["candidate_model"]))
    return seen


def fetch_cached_opinion(cluster_id: str) -> str:
    """Read cached opinion text. v1 builds this cache during scoring;
    we should not be re-hitting CourtListener here."""
    if not cluster_id:
        return ""
    p = OPINION_CACHE / f"{cluster_id}.txt"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[:MAX_OPINION_CHARS]


_VERDICT_RE = re.compile(r"\{[^{}]*assessment[^{}]*\}", re.DOTALL)


def parse_verdict(text: str) -> tuple[str | None, str]:
    """Extract (assessment, rationale) from the model's response."""
    m = _VERDICT_RE.search(text or "")
    if m:
        try:
            j = json.loads(m.group(0))
            return j.get("assessment"), j.get("rationale", "")
        except json.JSONDecodeError:
            pass
    # Fallback: look for a bare color keyword.
    for color in ("Red", "Yellow", "Green"):
        if color in (text or ""):
            return color, (text or "")[:200]
    return None, (text or "")[:200]


def call_candidate_assessor(
    client: anthropic.Anthropic,
    model_id: str,
    prompt: str,
) -> dict:
    """One API call. Returns text/usage or an error stub on exception."""
    start = time.time()
    try:
        resp = client.messages.create(
            model=model_id,
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return {
            "text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "elapsed_s": round(time.time() - start, 2),
            "error": str(exc)[:500],
        }
    blocks = resp.content or []
    text = "".join(b.text for b in blocks if getattr(b, "type", None) == "text")
    return {
        "text": text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "elapsed_s": round(time.time() - start, 2),
        "error": "",
    }


def cost_for(spec: dict, in_tok: int, out_tok: int) -> float:
    return (
        in_tok / 1_000_000 * spec["input_per_mtok"]
        + out_tok / 1_000_000 * spec["output_per_mtok"]
    )


def estimate_cost(cells: list[dict], specs: dict) -> str:
    # Use the median-from-v1 estimate (8500 input, 400 output per call).
    est_in, est_out = 8500, 400
    lines = []
    for name, spec in specs.items():
        per_call = cost_for(spec, est_in, est_out)
        total = per_call * len(cells)
        lines.append(
            f"  {name} ({spec['model_id']}): {len(cells)} calls "
            f"~ ${total:.2f} ({per_call:.4f}/call)"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--models",
        default="sonnet,haiku",
        help="Comma-separated subset of {sonnet, haiku} (default: both)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Cost estimate only")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap to first N cells per model (for smoke-test)",
    )
    args = ap.parse_args()

    requested = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in requested if m not in MODEL_SPECS]
    if unknown:
        print(f"Error: unknown model(s) {unknown}. Choose from: {list(MODEL_SPECS)}",
              file=sys.stderr)
        return 1

    cells = load_candidate_cells()
    print(f"Candidate cells (deduped, assessor fired): {len(cells)}")
    if args.limit:
        cells = cells[: args.limit]
        print(f"--limit {args.limit}: capping to {len(cells)} per model")

    specs = {m: MODEL_SPECS[m] for m in requested}
    print("Cost estimate:")
    print(estimate_cost(cells, specs))

    if args.dry_run:
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY missing from environment / .env",
              file=sys.stderr)
        return 1

    client = anthropic.Anthropic()
    seen = load_existing_calibration()
    print(f"Already in {OUT_CSV.name}: {len(seen)} (id, model) pairs — will skip")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists()
    with OUT_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()

        for model_name in requested:
            spec = MODEL_SPECS[model_name]
            todo = [
                c for c in cells
                if (c["id"], c.get("model", ""), model_name) not in seen
            ]
            print(f"\n=== {model_name} ({spec['model_id']}): {len(todo)} cells to run ===")
            running_cost = 0.0
            for i, cell in enumerate(todo, 1):
                opinion = fetch_cached_opinion(cell.get("matched_cluster_id", ""))
                cell_label = f"{cell['id']}/{cell.get('model','?')}"
                if not opinion:
                    # No cached text — skip and record (Opus had no_opinion too)
                    writer.writerow({
                        "id": cell["id"],
                        "model_under_test": cell.get("model", ""),
                        "candidate_model": model_name,
                        "opus_verdict": cell.get("supports", ""),
                        "candidate_verdict": "",
                        "candidate_rationale": "no cached opinion text",
                        "agree": "",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": 0,
                        "elapsed_s": 0,
                        "error": "no_opinion",
                    })
                    f.flush()
                    print(f"  [{i}/{len(todo)}] {cell_label:36} SKIP (no opinion)")
                    continue

                case_label = (
                    f"{cell.get('matched_cl_name') or cell.get('extracted_case_name') or ''}, "
                    f"{cell.get('extracted_citation') or ''}"
                ).strip(", ")
                prompt = ASSESSMENT_PROMPT.format(
                    proposition=cell.get("proposition", ""),
                    case_name_citation=case_label,
                    opinion_text=opinion,
                )

                result = call_candidate_assessor(client, spec["model_id"], prompt)
                verdict, rationale = parse_verdict(result["text"])
                opus = cell.get("supports", "")
                agree = "" if not verdict else ("Y" if verdict == opus else "N")
                cost = cost_for(spec, result["input_tokens"], result["output_tokens"])
                running_cost += cost

                writer.writerow({
                    "id": cell["id"],
                    "model_under_test": cell.get("model", ""),
                    "candidate_model": model_name,
                    "opus_verdict": opus,
                    "candidate_verdict": verdict or "",
                    "candidate_rationale": rationale[:400],
                    "agree": agree,
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                    "cost_usd": round(cost, 6),
                    "elapsed_s": result["elapsed_s"],
                    "error": result["error"],
                })
                f.flush()

                marker = "OK " if verdict else "??? "
                tail = f"err={result['error'][:40]}" if result["error"] else f"{result['elapsed_s']:.1f}s"
                print(
                    f"  [{i}/{len(todo)}] {cell_label:36} "
                    f"{marker} opus={opus:6} cand={verdict or '?':6} "
                    f"${running_cost:.3f} {tail}"
                )

    print(f"\nDone. Output: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
