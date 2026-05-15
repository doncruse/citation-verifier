"""One-off: replay scratch/citations_for_review.csv through the new
gates and report flips relative to the recorded v_status / qc_status.

This is NOT a regression test -- it's a manual calibration tool.

Run from the worktree root:
    PYTHONPATH=src venv/Scripts/python.exe scripts/recalibrate_against_qc.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from collections import Counter
from pathlib import Path

# Load .env explicitly. The client module's auto-load walks up from
# src/citation_verifier/client.py, which lands at the worktree root --
# but our .env only exists at the parent repo root. Load both, parent
# first, so the worktree (if it ever has one) wins.
from dotenv import load_dotenv

_THIS = Path(__file__).resolve()
_WORKTREE_ROOT = _THIS.parent.parent
# Walk up to find the citation-verifier repo root (it has .env)
for candidate in [
    _WORKTREE_ROOT / ".env",
    _WORKTREE_ROOT.parent.parent.parent / ".env",  # main repo root
]:
    if candidate.exists():
        load_dotenv(candidate)

from citation_verifier.verifier import CitationVerifier  # noqa: E402

CSV_PATH = _WORKTREE_ROOT / "scratch" / "citations_for_review.csv"


async def main() -> None:
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        raise SystemExit("Set COURTLISTENER_API_TOKEN in environment (or .env)")

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} rows from {CSV_PATH.name}")

    # The CSV's citation column is named `citation_text`, not `citation`.
    citations: list[str] = []
    indices: list[int] = []
    for i, r in enumerate(rows):
        cite = (r.get("citation_text") or "").strip()
        if cite:
            citations.append(cite)
            indices.append(i)
    print(f"Verifying {len(citations)} citations with non-empty citation_text")

    verifier = CitationVerifier()

    def _progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"  ... {done}/{total}", flush=True)

    results = await verifier.verify_batch(
        citations,
        progress_callback=_progress,
    )

    flips: list[tuple[str, str, str, str]] = []
    counter_old: Counter[str] = Counter()
    counter_new: Counter[str] = Counter()

    for idx_in_results, row_idx in enumerate(indices):
        row = rows[row_idx]
        result = results[idx_in_results]
        old = row.get("v_status") or "(empty)"
        new = result.status.value
        counter_old[old] += 1
        counter_new[new] += 1
        if old != new:
            flips.append(
                (
                    row.get("citation_text", ""),
                    old,
                    new,
                    row.get("qc_status", "") or "",
                )
            )

    print("\nDistribution (old -> new):")
    statuses = sorted(set(counter_old) | set(counter_new))
    print(f"  {'status':22s}  {'old':>5s}  ->  {'new':>5s}")
    for s in statuses:
        print(f"  {s:22s}  {counter_old.get(s, 0):5d}  ->  {counter_new.get(s, 0):5d}")

    print(f"\n{len(flips)} flips:")
    for cite, old, new, qc in flips[:50]:
        print(f"  [{qc:12s}] {old:18s} -> {new:18s}  {cite[:80]}")
    if len(flips) > 50:
        print(f"  ... and {len(flips) - 50} more")

    # Show ALL flips broken down by (old, new) pair for the report
    pair_counts: Counter[tuple[str, str]] = Counter()
    for _, old, new, _ in flips:
        pair_counts[(old, new)] += 1
    print("\nFlip transitions (old -> new, count):")
    for (old, new), n in sorted(pair_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {old:18s} -> {new:18s}  {n}")

    bad = [f for f in flips if f[3] == "approved" and f[2] == "NOT_FOUND"]
    if bad:
        print(f"\nREGRESSIONS: {len(bad)} qc-approved rows are now NOT_FOUND:")
        for cite, old, new, qc in bad:
            print(f"  [{old} -> NOT_FOUND]  {cite}")
    else:
        print("\nNo qc-approved -> NOT_FOUND regressions.")

    # Also surface any qc=approved row that flipped to ANY other status, for awareness
    other_qc_flips = [
        f for f in flips
        if f[3] == "approved" and f[2] != "NOT_FOUND"
    ]
    if other_qc_flips:
        print(f"\nOther qc-approved status changes ({len(other_qc_flips)}):")
        for cite, old, new, qc in other_qc_flips[:50]:
            print(f"  {old} -> {new}  {cite[:80]}")
        if len(other_qc_flips) > 50:
            print(f"  ... and {len(other_qc_flips) - 50} more")


if __name__ == "__main__":
    asyncio.run(main())
