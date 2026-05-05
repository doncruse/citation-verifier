"""Join citation_court from _raw_pool.json into _all_cl_misses.csv.

Adds a `citation_court` column (the cited opinion's jurisdiction, as
extracted by eyecite during pool mining) right after `citing_court`.
"""

import csv
import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "releases" / "v1"
POOL_PATH = BENCH / "_raw_pool.json"
IN_CSV = BENCH / "_all_cl_misses.csv"
OUT_CSV = BENCH / "_all_cl_misses_with_citation_court.csv"


def main() -> None:
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    idx: dict[tuple[str, str, str], str] = {}
    for items in pool.values():
        for it in items:
            key = (str(it["citing_cluster_id"]), it["citation_text"], it["case_name"])
            idx[key] = it.get("court") or ""

    with open(IN_CSV, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        in_fields = list(rows[0].keys()) if rows else []

    insert_at = in_fields.index("citing_court") + 1
    out_fields = in_fields[:insert_at] + ["citation_court"] + in_fields[insert_at:]

    hits = unmatched = no_court = 0
    for row in rows:
        key = (row["citing_cluster_id"], row["cite"], row["case_name"])
        if key in idx:
            hits += 1
            row["citation_court"] = idx[key]
            if not idx[key]:
                no_court += 1
        else:
            unmatched += 1
            row["citation_court"] = ""

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUT_CSV.relative_to(BENCH.parent)}")
    print(f"  rows: {len(rows)}")
    print(f"  joined: {hits}  (with citation_court populated: {hits - no_court})")
    print(f"  pool key not found: {unmatched}")
    print(f"  joined but no court in pool: {no_court}")


if __name__ == "__main__":
    main()
