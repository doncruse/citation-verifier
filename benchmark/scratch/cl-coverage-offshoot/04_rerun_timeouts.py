"""
Re-run extraction on the 3 opinions that timed out in 03_pilot_extraction.py
with the bumped 900s timeout.

Inputs: opinion text files already saved under pilot_opinions/ from step 3.
Outputs: pilot_extractions/<cluster_id>.json (overwrites the prior timeout
markers).

Also re-applies the normalizing classifier (appears_in_source vs
near_miss_after_normalize vs not_in_source) on the saved citations so the
results are consistent across all 5 opinions for downstream analysis.
"""
from __future__ import annotations

import csv
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

# Map of cluster_id -> (tier_label, case_name) — read from prior summary
def load_targets():
    summary = HERE / "pilot_summary.csv"
    if not summary.exists():
        raise RuntimeError(f"missing {summary} — run 03_pilot_extraction.py first")
    targets = []
    for row in csv.DictReader(summary.open(encoding="utf-8")):
        if row.get("error") == "TIMEOUT":
            cluster_id = row["cluster_id"]
            op_file = OPINIONS_DIR / f"{cluster_id}.txt"
            if not op_file.exists():
                print(f"  warning: opinion file missing for {cluster_id}")
                continue
            targets.append({
                "tier_label": row["tier_label"],
                "cluster_id": cluster_id,
                "case_name": row["cited_case_name"],
                "court_id": row["cited_court_id"],
                "seed_cite": row["seed_cite"],
                "op_path": op_file,
                "char_count": int(row["char_count"]),
            })
    return targets


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


def main():
    targets = load_targets()
    print(f"re-running {len(targets)} timeouts with 900s timeout:")
    for t in targets:
        print(f"  - {t['tier_label']:<15} {t['cluster_id']:<10} {t['char_count']:>8,} chars  {t['case_name'][:40]}")

    overall_start = time.time()
    for t in targets:
        print(f"\n=== {t['tier_label']} — cluster {t['cluster_id']} ===")
        op_text = t["op_path"].read_text(encoding="utf-8")

        start = time.time()
        result = extract_citations(op_text)
        elapsed = time.time() - start
        print(f"  done in {elapsed:.1f}s, cost ${result['cost_usd']:.4f}")
        if result["error"]:
            print(f"  EXTRACT_ERROR: {result['error'][:200]}")

        # Classify each returned citation
        citations = result.get("citations", [])
        buckets = {"appears_in_source": [], "near_miss_after_normalize": [], "not_in_source": []}
        for c in citations:
            if not isinstance(c, dict):
                continue
            cls = classify(c.get("citation_string", ""), op_text)
            if cls in buckets:
                c["_classification"] = cls
                buckets[cls].append(c)
        print(f"  returned={len(citations)}  appears_in_source={len(buckets['appears_in_source'])}  near_miss={len(buckets['near_miss_after_normalize'])}  not_in_source={len(buckets['not_in_source'])}")

        # Save
        ex_file = EXTRACTIONS_DIR / f"{t['cluster_id']}.json"
        ex_file.write_text(json.dumps({
            "tier_label": t["tier_label"],
            "seed_cite": t["seed_cite"],
            "cluster_id": t["cluster_id"],
            "case_name": t["case_name"],
            "court_id": t["court_id"],
            "char_count": len(op_text),
            "elapsed_s": result["elapsed_s"],
            "cost_usd": result["cost_usd"],
            "raw_response_chars": result["raw_response_chars"],
            "error": result["error"],
            "citations_appears_in_source": buckets["appears_in_source"],
            "citations_near_miss_after_normalize": buckets["near_miss_after_normalize"],
            "citations_not_in_source": buckets["not_in_source"],
            "citations_all": citations,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {ex_file.name}")

    overall_elapsed = time.time() - overall_start
    print(f"\nDONE — total wall time {overall_elapsed:.0f}s ({overall_elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
