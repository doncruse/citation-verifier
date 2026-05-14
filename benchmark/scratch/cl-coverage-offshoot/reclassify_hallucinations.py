"""
Re-classify pilot "hallucinations" with a normalizing validator that handles
PDF artifacts the strict substring check misses:

- collapse runs of whitespace (PDF line breaks split citations)
- normalize smart quotes / apostrophes to straight
- normalize em-dash / en-dash to ASCII hyphen
- normalize non-breaking spaces

After normalization, "real" hallucinations are citations whose normalized
form still doesn't appear in the normalized source. Whitespace/punctuation
mismatches go to a third bucket: `near_miss`.

Reads the pilot_extractions/*.json files written by 03_pilot_extraction.py.
Does not re-run the extractor. Writes:
- reclassified_summary.csv: one row per opinion with refined counts
- reclassified_hallucinations.md: list of truly NOT_IN_SOURCE citations
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
EXTRACTIONS_DIR = HERE / "pilot_extractions"
OPINIONS_DIR = HERE / "pilot_opinions"


_SMART_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
})


def normalize(s: str) -> str:
    """Aggressive normalization for substring matching."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_SMART_QUOTE_MAP)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def classify(citation: str, opinion_text: str) -> str:
    """Return 'valid' / 'near_miss' / 'not_in_source'."""
    cite = (citation or "").strip()
    if not cite:
        return "not_in_source"
    if cite in opinion_text:
        return "valid"
    cn = normalize(cite)
    on = normalize(opinion_text)
    if cn in on:
        return "near_miss"
    return "not_in_source"


def main():
    out_rows = []
    not_in_source_examples = []

    for f in sorted(EXTRACTIONS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        case = data.get("case_name") or ""
        tier = data.get("tier_label") or ""
        valid = data.get("citations_valid") or []
        halluc = data.get("citations_hallucinated") or []
        all_returned = valid + halluc
        if not all_returned:
            out_rows.append({
                "tier": tier, "cluster_id": f.stem, "case": case,
                "n_returned": 0, "n_valid": 0, "n_near_miss": 0, "n_not_in_source": 0,
            })
            continue

        op_file = OPINIONS_DIR / f"{f.stem}.txt"
        op_text = op_file.read_text(encoding="utf-8") if op_file.exists() else ""

        counts = {"valid": 0, "near_miss": 0, "not_in_source": 0}
        for c in all_returned:
            kind = classify(c.get("citation_string", ""), op_text)
            counts[kind] += 1
            if kind == "not_in_source":
                not_in_source_examples.append({
                    "tier": tier,
                    "cluster_id": f.stem,
                    "case": case,
                    "citation_string": c.get("citation_string"),
                    "cited_case_name": c.get("cited_case_name"),
                    "year": c.get("year"),
                    "sentence_context": (c.get("sentence_context") or "")[:200],
                })

        out_rows.append({
            "tier": tier, "cluster_id": f.stem, "case": case[:50],
            "n_returned": len(all_returned),
            "n_valid": counts["valid"],
            "n_near_miss": counts["near_miss"],
            "n_not_in_source": counts["not_in_source"],
        })

    # Write summary
    with open(HERE / "reclassified_summary.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    # Print table
    print(f"{'tier':<15} {'cluster':<10} {'case':<50} {'returned':>9} {'valid':>6} {'near':>5} {'NOT':>4}")
    print("-" * 105)
    total_returned = total_valid = total_near = total_not = 0
    for r in out_rows:
        print(f"{r['tier']:<15} {r['cluster_id']:<10} {r['case']:<50} {r['n_returned']:>9} {r['n_valid']:>6} {r['n_near_miss']:>5} {r['n_not_in_source']:>4}")
        total_returned += r["n_returned"]
        total_valid += r["n_valid"]
        total_near += r["n_near_miss"]
        total_not += r["n_not_in_source"]
    print("-" * 105)
    print(f"{'TOTAL':<15} {'':<10} {'':<50} {total_returned:>9} {total_valid:>6} {total_near:>5} {total_not:>4}")
    if total_returned > 0:
        true_halluc = 100 * total_not / total_returned
        near_miss = 100 * total_near / total_returned
        print()
        print(f"True hallucination rate (citation not in source even after normalization): {true_halluc:.1f}%")
        print(f"Near-miss rate (PDF/encoding artifacts):                                   {near_miss:.1f}%")

    # Save not-in-source examples for inspection
    md = ["# True hallucinations (not in normalized source)", ""]
    if not not_in_source_examples:
        md.append("None.")
    else:
        for ex in not_in_source_examples:
            md.append(f"### {ex['tier']} / cluster {ex['cluster_id']} ({ex['case'][:40]})")
            md.append(f"- citation: `{ex['citation_string']}`")
            md.append(f"- case_name: `{ex['cited_case_name']}`")
            md.append(f"- year: {ex['year']}")
            md.append(f"- sentence: {ex['sentence_context']}")
            md.append("")
    (HERE / "reclassified_hallucinations.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
