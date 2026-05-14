"""
Focused test of option (1) — does dropping sentence_context from the prompt
let claude -p complete on Knick (46K chars)?

If yes: re-run all 3 timed-out opinions with the new prompt.
If no: the cliff isn't about output size; try option (3) with API key.

Outputs:
- pilot_extractions/4631843.json    : new extraction (overwrites prior TIMEOUT)
- Stdout: timestamped progress
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv(usecwd=False), override=True)

HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OPINIONS_DIR = HERE / "pilot_opinions"
EXTRACTIONS_DIR = HERE / "pilot_extractions"

sys.path.insert(0, str(HERE))
from extract_citations import extract_citations  # noqa: E402

KNICK_CLUSTER = 4631843


_SMART_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
})


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_SMART_QUOTE_MAP)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def classify(citation: str, opinion_text: str) -> str:
    cite = (citation or "").strip()
    if not cite:
        return "empty"
    if cite in opinion_text:
        return "appears_in_source"
    if normalize(cite) in normalize(opinion_text):
        return "near_miss_after_normalize"
    return "not_in_source"


def log(t0: float, msg: str) -> None:
    elapsed = time.time() - t0
    print(f"[{elapsed:6.1f}s] {msg}", flush=True)


def main():
    t0 = time.time()
    op_file = OPINIONS_DIR / f"{KNICK_CLUSTER}.txt"
    if not op_file.exists():
        log(t0, f"ERROR: opinion file missing: {op_file}")
        return
    op_text = op_file.read_text(encoding="utf-8")
    log(t0, f"Knick cluster={KNICK_CLUSTER}  chars={len(op_text):,}")
    log(t0, f"running extractor with stripped prompt (no sentence_context)...")

    result = extract_citations(op_text)
    log(t0, f"extractor returned after {result['elapsed_s']}s  cost=${result['cost_usd']:.4f}")
    if result.get("error"):
        log(t0, f"ERROR: {result['error'][:200]}")
    else:
        log(t0, f"raw response chars: {result['raw_response_chars']:,}")

    citations = result.get("citations", [])
    buckets = {"appears_in_source": [], "near_miss_after_normalize": [], "not_in_source": []}
    for c in citations:
        if not isinstance(c, dict):
            continue
        cls = classify(c.get("citation_string", ""), op_text)
        if cls in buckets:
            c["_classification"] = cls
            buckets[cls].append(c)
    log(t0, f"returned={len(citations)}  appears={len(buckets['appears_in_source'])}  near_miss={len(buckets['near_miss_after_normalize'])}  not_in_source={len(buckets['not_in_source'])}")

    # Save
    ex_file = EXTRACTIONS_DIR / f"{KNICK_CLUSTER}.json"
    ex_file.write_text(json.dumps({
        "tier_label": "SCOTUS",
        "seed_cite": "588 U.S. 180",
        "cluster_id": KNICK_CLUSTER,
        "case_name": "Knick v. Township of Scott",
        "court_id": "scotus",
        "char_count": len(op_text),
        "elapsed_s": result["elapsed_s"],
        "cost_usd": result["cost_usd"],
        "raw_response_chars": result["raw_response_chars"],
        "error": result["error"],
        "citations_appears_in_source": buckets["appears_in_source"],
        "citations_near_miss_after_normalize": buckets["near_miss_after_normalize"],
        "citations_not_in_source": buckets["not_in_source"],
        "citations_all": citations,
        "_prompt_variant": "stripped_no_sentence_context",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log(t0, f"wrote {ex_file.name}")
    log(t0, f"DONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
