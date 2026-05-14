"""
Step 1: extract SCOTUS + Circuit dedup rows from v1's raw pool.

Tier classification uses the eyecite-derived `court` field on each pool row,
classified via gold_db.lookup_court.

Output: v1_scotus_circuit.csv with one row per unique (citing_cluster_id,
citation_text, parenthetical) tuple where the cited tier is
(federal, colr) [SCOTUS] or (federal, iac) [Circuit].
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from citation_verifier.gold_db import lookup_court  # noqa: E402

HERE = Path(__file__).parent
RAW_POOL = ROOT / "benchmark" / "releases" / "v1" / "_raw_pool.json"
OUT = HERE / "v1_scotus_circuit.csv"

TARGET_TIERS = {("federal", "colr"), ("federal", "iac")}


def main():
    with open(RAW_POOL, encoding="utf-8") as f:
        pool = json.load(f)

    seen = set()
    out_rows = []
    for source_court, rows in pool.items():
        for r in rows:
            key = (r["citing_cluster_id"], r["citation_text"], r.get("parenthetical", ""))
            if key in seen:
                continue
            seen.add(key)
            court = r.get("court") or ""
            sl = lookup_court(court) if court else None
            if not sl:
                continue
            if sl not in TARGET_TIERS:
                continue
            out_rows.append({
                "source_court": source_court,
                "system": sl[0],
                "level": sl[1],
                "tier_label": "SCOTUS" if sl == ("federal", "colr") else "Circuit",
                "cited_court_id": court,
                "cited_case_name": r.get("case_name") or "",
                "cited_year": r.get("year") or "",
                "citation_text": r["citation_text"],
                "parenthetical": r.get("parenthetical") or "",
                "citing_cluster_id": r["citing_cluster_id"],
                "citing_case": r.get("citing_case") or "",
                "citing_date": r.get("citing_date") or "",
                "citing_court": r.get("citing_court") or "",
                "v1_v_status": r.get("v_status") or "",
                "v1_v_url": r.get("v_url") or "",
                "v1_v_matched_name": r.get("v_matched_name") or "",
            })

    fieldnames = list(out_rows[0].keys())
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    from collections import Counter
    by_tier = Counter((r["system"], r["level"]) for r in out_rows)
    by_tier_x_status = Counter((r["tier_label"], r["v1_v_status"]) for r in out_rows)

    print(f"wrote {len(out_rows)} rows to {OUT.relative_to(ROOT)}")
    print()
    print("By tier:")
    for k, n in by_tier.most_common():
        print(f"  {k}: {n}")
    print()
    print("By tier x v1 v_status:")
    for (tier, status), n in sorted(by_tier_x_status.items()):
        print(f"  {tier:>8} {status:>14}: {n}")


if __name__ == "__main__":
    main()
