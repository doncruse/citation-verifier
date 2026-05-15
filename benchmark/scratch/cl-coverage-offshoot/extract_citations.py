"""
LLM-based citation extractor for CL-resident opinions, via `claude -p`.

Uses Claude Code's headless mode (`claude -p --output-format json --model sonnet`)
to extract every citation in an opinion as written, along with the parenthetical
(if any), sentence context, and basic metadata. Pipes the prompt via stdin
(Windows arg-length cap) and runs from a hermetic temp dir to avoid CLAUDE.md
bleed-in (matches the pattern in `pilot_a/score.py` and
`runners/truncation_experiment.py`).

Goal: bypass eyecite's paren-attribution bug, smart-quote contamination, and
truncated-case-name issues from the 158-row re-verify (step 2). Capture
citations as the citing court wrote them, no resolution attempted.

Design tradeoffs vs SDK (documented for the eventual writeup):
- No `temperature=0` control. CLI runs at temp=1.0. Measured ~13% within-model
  variance on the assessor task; extraction variance is unknown but likely lower.
- No `output_config.format` schema enforcement. We instruct the model to emit a
  fenced JSON block, then regex-parse it. Failures are recovered or dropped.
- No fine-grained token-cost tracking; `total_cost_usd` from the CLI wrapper is
  the only signal.

Failure modes & mitigations:
1. Citation hallucination → post-validate citation_string substring in source.
2. JSON parse failure → drop the result, count it, optionally re-try once.
3. Coverage gaps → cross-check vs eyecite if needed (later).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MODEL = "haiku"  # CLI alias; resolves to claude-haiku-4-5
# Was "sonnet" but sonnet via claude -p hangs indefinitely on opinions over
# ~27K chars (Knick 46K, Lemcke 79K, Ram 40K all hit subprocess timeout).
# Stripping output volume (removing sentence_context) didn't fix it. Switching
# to haiku to see if smaller-per-call overhead clears the cliff. Quality on
# parenthetical attribution may be lower but extraction is mostly pattern
# matching — should be acceptable for coverage measurement.
# 600s default for the real run. The 2026-05-14 A/B test
# (ab_results.csv) found the hang cliff is closer to 24K chars than
# LIMITATIONS.md's 27-30K estimate — a 24,720-char opinion timed out
# at 240s on BOTH sonnet and haiku. 600s gives slow-but-completable
# extractions room to finish without burning excessive wall time on
# truly-hung opinions in the 24K-25K char band.
TIMEOUT_S = 600

# One temp dir per process (matches `truncation_experiment.py:_HERMETIC_DIR`).
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="extract_citations_"))

EXTRACTION_PROMPT = """You are extracting every legal citation that appears in a judicial opinion.

For each citation in the opinion, capture these eight fields:

1. **citation_string** — the reporter citation as written (e.g. "576 U.S. 644", "947 F.3d 240", "2018 WL 301424"). Verbatim — preserve the exact characters, including punctuation. If a citation has multiple parallel reporter cites (e.g. "326 U.S. 310, 66 S.Ct. 154"), capture each parallel cite as a separate entry sharing the other fields.

2. **cited_case_name** — the case name as written immediately before this citation (e.g. "Obergefell v. Hodges"). Include "In re" / "Ex parte" prefixes. Drop trailing punctuation. If a short-form cite or "id." is used, populate with whatever case name is most recently in scope. Use null only if no case name can be determined.

3. **year** — the year as a 4-digit integer if shown in parentheses with the citation, or null if not present.

4. **month** — the month as a 1-12 integer if a full date is shown in the citation parenthetical (e.g. "(N.D. Cal. Jan. 8, 2014)" → 1; "(June 23, 2019)" → 6). Null if only year is shown.

5. **day** — the day of month as a 1-31 integer if a full date is shown (e.g. "Jan. 8, 2014" → 8). Null if only year/month is shown.

6. **court_hint** — the court as you understand it from the citation pattern or surrounding text. Use court_hint values like "U.S. Supreme Court", "1st Cir.", "9th Cir.", "Cal. Supreme Court", "Cal. Ct. App.", "N.Y. Ct. App.", "S.D.N.Y.", etc. Null if unknown.

7. **docket_number** — the docket / case number when it appears with the citation (e.g. "No. 1:18-cv-00236", "Case No. 23-cv-02041", "B225051", "20-1234"). Capture the number itself with its prefix if any (e.g. "1:18-cv-00236"). Null if not shown. This is especially important for unpublished district court opinions (WL/LEXIS cites) — the docket number is often a more reliable identifier than the case name (which may change due to Rule 25(d) substitutions, anonymized SSA captions like "John S. v. Bisignano", or John/Jane Doe captions later identified).

8. **parenthetical** — the parenthetical text following the citation, if any, with the surrounding parentheses removed. EXCLUDE the court-and-date parenthetical (e.g. "(N.D. Cal. Jan. 8, 2014)") — those facts go in court_hint/year/month/day fields. Only capture editorial parentheticals describing what the cited case holds or stands for. E.g. for `Obergefell v. Hodges, 576 U.S. 644 (2015) (holding that same-sex couples may marry)`, parenthetical is "holding that same-sex couples may marry". Null if no editorial parenthetical.

Rules:
- Capture EVERY citation, including string cites and short-form cites like "id." or "supra".
- Do NOT capture statutes, regulations, or constitutional provisions — only case citations.
- Do NOT invent citations not in the source text. If you can't find the citation string in the text, omit it.
- Preserve citation_string verbatim — do not "fix" typos, abbreviations, or spelling.
- If a citation has no parenthetical, set parenthetical to null — do NOT fabricate one.
- The opinion may have its own internal heading/preamble — extract citations from the body, not from any "Citations" or "Table of Authorities" section.

OUTPUT FORMAT:
Return ONLY a JSON object inside a fenced ```json code block, in this exact shape:

```json
{
  "citations": [
    {
      "citation_string": "<verbatim cite>",
      "cited_case_name": "<case name or null>",
      "year": <int or null>,
      "month": <1-12 int or null>,
      "day": <1-31 int or null>,
      "court_hint": "<court or null>",
      "docket_number": "<docket no. or null>",
      "parenthetical": "<text or null>"
    }
  ]
}
```

No preamble, no explanation outside the fenced block. The JSON must parse with standard json.loads.

=== OPINION TEXT ===
{opinion_text}
=== END OPINION TEXT ===

Now produce the JSON output.
"""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_from_response(text: str) -> dict | None:
    """Find and parse the citations JSON in a free-form response.

    Tries (in order):
    1. fenced ```json ... ``` block
    2. fenced ``` ... ``` block
    3. first balanced JSON object containing "citations"
    """
    m = _JSON_BLOCK_RE.search(text or "")
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: locate the first { that contains "citations" and balance braces
    idx = (text or "").find('"citations"')
    if idx < 0:
        return None
    start = (text or "").rfind("{", 0, idx)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_citations(
    opinion_text: str,
    *,
    model: str = MODEL,
    timeout_s: int = TIMEOUT_S,
) -> dict[str, Any]:
    """Run citation extraction via `claude -p` on a single opinion.

    Returns:
        {
            "citations": list[dict],
            "elapsed_s": float,
            "cost_usd": float,
            "raw_response_chars": int,
            "error": str | None,
        }
    """
    prompt = EXTRACTION_PROMPT.replace("{opinion_text}", opinion_text)

    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=str(_HERMETIC_DIR),
        )
    except subprocess.TimeoutExpired:
        return {
            "citations": [],
            "elapsed_s": float(timeout_s),
            "cost_usd": 0.0,
            "raw_response_chars": 0,
            "error": "TIMEOUT",
        }
    elapsed = time.time() - start

    # Outer JSON envelope from `--output-format json`
    try:
        payload = json.loads(proc.stdout.strip())
        response = (payload.get("result") or "").strip()
        cost = float(payload.get("total_cost_usd") or 0.0)
    except json.JSONDecodeError:
        return {
            "citations": [],
            "elapsed_s": round(elapsed, 1),
            "cost_usd": 0.0,
            "raw_response_chars": len(proc.stdout or ""),
            "error": f"OUTER_JSON_DECODE_ERROR; stdout[:300]={proc.stdout[:300]!r}",
        }

    inner = _extract_json_from_response(response)
    if not inner or "citations" not in inner:
        return {
            "citations": [],
            "elapsed_s": round(elapsed, 1),
            "cost_usd": cost,
            "raw_response_chars": len(response),
            "error": f"INNER_JSON_NOT_FOUND; response[:300]={response[:300]!r}",
        }

    citations = inner.get("citations") or []
    if not isinstance(citations, list):
        return {
            "citations": [],
            "elapsed_s": round(elapsed, 1),
            "cost_usd": cost,
            "raw_response_chars": len(response),
            "error": f"citations field not a list: {type(citations).__name__}",
        }

    return {
        "citations": citations,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": round(cost, 6),
        "raw_response_chars": len(response),
        "error": None,
    }


def validate_citations(
    citations: list[dict],
    opinion_text: str,
) -> tuple[list[dict], list[dict]]:
    """Split extracted citations into (valid, hallucinated).

    A citation is "valid" if its `citation_string` appears verbatim in the
    opinion text. Hallucinated entries are returned separately for inspection.
    """
    valid = []
    halluc = []
    for c in citations:
        if not isinstance(c, dict):
            halluc.append({"_raw": c, "_reason": "not_a_dict"})
            continue
        cite_str = (c.get("citation_string") or "").strip()
        if cite_str and cite_str in opinion_text:
            valid.append(c)
        else:
            halluc.append(c)
    return valid, halluc


if __name__ == "__main__":
    # Synthetic smoke test — exercises every field in the schema:
    #   - published reporter cite with year only (Anderson, Celotex)
    #   - unpublished WL cite with full date + docket number (Gilliard)
    #   - SSA-style anonymized caption that would fail name-match alone
    #     but is rescuable via docket_number (John S. v. Bisignano)
    sample = (
        "The Supreme Court has held that there is no genuine dispute of material fact when the evidence is so one-sided "
        "that one party must prevail as a matter of law. Anderson v. Liberty Lobby, Inc., 477 U.S. 242, 252 (1986). "
        "See also Celotex Corp. v. Catrett, 477 U.S. 317 (1986) (clarifying summary judgment burdens). "
        "The district court applied the same standard. Gilliard v. McWilliams, 2019 WL 3304707, at *3 "
        "(D.D.C. July 23, 2019), No. 1:18-cv-01506. Cf. John S. v. Bisignano, 2025 WL 1505405 "
        "(N.D. Ill. May 27, 2025), No. 1:23-cv-02041."
    )
    out = extract_citations(sample)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    valid, halluc = validate_citations(out["citations"], sample)
    print(f"\nvalid: {len(valid)}, hallucinated: {len(halluc)}")
    valid, halluc = validate_citations(out["citations"], sample)
    print(f"\nvalid: {len(valid)}, hallucinated: {len(halluc)}")
