"""One-shot backfill of v1 cases' court_id (and re-confirm year).

Per the v1.3 design (`docs/plans/2026-05-05-v1.3-design.md` §"v1 cohort
backfill"), v1's cases table has NULL court_id for all 127 cited cases,
which blocks any tier-stratified comparison between v1 and v1.3.

This script:
  1. Pulls every distinct cited_cluster_id from `citation_rows` where
     dataset_name='v1'.
  2. For each, fetches the cluster from CL, follows its docket URL to
     get the court_id, and reads year from the cluster's date_filed.
  3. Calls `GoldDB.upsert_case()` — which auto-derives `(system, level)`
     via `lookup_court()` — under run_id `v1-backfill-court-{date}`.

Idempotent: re-running on a populated DB updates only what's still NULL
(COALESCE semantics in upsert_case mean already-filled values stick).

Usage:
  venv/Scripts/python.exe benchmark/runners/backfill_v1_court_metadata.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.gold_db import GoldDB, lookup_court  # noqa: E402

GOLD_DB_PATH = PROJECT_ROOT / "benchmark" / "gold_db" / "gold.db"
DATASET = "v1"


def fetch_court_and_year(client: CourtListenerClient, cluster_id: int) -> tuple[str | None, int | None]:
    """Return (court_id, year) for a cluster_id, or (None, None) on failure."""
    try:
        cluster = client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{cluster_id}/",
        ).json()
    except Exception as exc:
        print(f"  cluster {cluster_id}: fetch error {exc}", file=sys.stderr)
        return None, None

    date_filed = cluster.get("date_filed", "") or ""
    year: int | None = None
    if len(date_filed) >= 4 and date_filed[:4].isdigit():
        year = int(date_filed[:4])

    docket_url = cluster.get("docket", "") or ""
    if not docket_url:
        return None, year

    try:
        docket = client._request_with_retry("GET", docket_url).json()
    except Exception as exc:
        print(f"  cluster {cluster_id}: docket fetch error {exc}", file=sys.stderr)
        return None, year

    court_url = docket.get("court", "") or ""
    if not court_url:
        return None, year
    court_id = court_url.rstrip("/").split("/")[-1]
    return court_id, year


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change, don't write to DB")
    args = ap.parse_args()

    db = GoldDB(GOLD_DB_PATH)
    rows = db.conn.execute(
        """
        SELECT DISTINCT cr.cited_cluster_id AS cluster_id,
               c.canonical_name, c.court_id, c.year, c.cite_string
        FROM citation_rows cr
        JOIN cases c ON cr.cited_cluster_id = c.cluster_id
        WHERE cr.dataset_name = ?
          AND cr.cited_cluster_id IS NOT NULL
          AND c.court_id IS NULL
        ORDER BY cr.cited_cluster_id
        """,
        (DATASET,),
    ).fetchall()
    todo = [dict(r) for r in rows]
    print(f"v1 cases needing court_id backfill: {len(todo)}")

    if args.dry_run:
        for r in todo[:5]:
            print(f"  [dry] cluster {r['cluster_id']}: {r['canonical_name']} (year={r['year']})")
        if len(todo) > 5:
            print(f"  ... and {len(todo) - 5} more")
        db.close()
        return

    if not todo:
        print("Nothing to backfill.")
        db.close()
        return

    run_id = f"v1-backfill-court-{datetime.date.today().isoformat()}"
    print(f"Run id: {run_id}")

    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 30

    n_filled = 0
    n_failed = 0
    n_already = 0
    failures: list[tuple[int, str]] = []
    for i, r in enumerate(todo, 1):
        cid = r["cluster_id"]
        court_id, year = fetch_court_and_year(client, cid)
        if not court_id:
            n_failed += 1
            failures.append((cid, r["canonical_name"]))
            print(f"[{i}/{len(todo)}] cluster {cid}: FAILED to resolve court", flush=True)
            continue

        # Don't overwrite year if already populated (COALESCE handles this)
        existing_year = r["year"]
        year_to_pass = year if existing_year is None else existing_year

        sys_, lvl_ = lookup_court(court_id)
        db.upsert_case(
            cluster_id=cid,
            canonical_name=r["canonical_name"] or "",
            court_id=court_id,
            year=year_to_pass,
            cite_string=r["cite_string"],
            run_id=run_id,
        )
        n_filled += 1
        if i % 20 == 0 or i == len(todo):
            print(f"[{i}/{len(todo)}] cluster {cid}: court={court_id} "
                  f"({sys_ or '?'}/{lvl_ or '?'}) year={year_to_pass}",
                  flush=True)

    print()
    print(f"Filled:        {n_filled}")
    print(f"Already-set:   {n_already}")
    print(f"Failed:        {n_failed}")
    if failures:
        print()
        print("Failures (cluster_id, name):")
        for cid, name in failures:
            print(f"  {cid}: {name}")

    db.close()


if __name__ == "__main__":
    main()
