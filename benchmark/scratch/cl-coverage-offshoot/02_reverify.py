"""
Step 2: re-verify all 158 SCOTUS + Circuit dedup rows using the current
verifier (verify_batch), then compare new v_status to v1's stored v_status.

Goal: quantify how much of v1's ~8% Circuit miss-rate (and 0% SCOTUS) was
genuine "not in CL" vs verifier false negatives that newer verifier logic
recovers. Also produce a clean per-row VERIFIED / NOT_FOUND / POSSIBLE_MATCH
list for the offshoot.

Input:  v1_scotus_circuit.csv  (158 rows)
Output: reverify_results.csv   (same rows + new_v_status, new_v_url, etc.)
        reverify_summary.md    (narrative + diff stats)
"""

import asyncio
import csv
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from citation_verifier.verifier import CitationVerifier  # noqa: E402

HERE = Path(__file__).parent
INPUT = HERE / "v1_scotus_circuit.csv"
OUTPUT = HERE / "reverify_results.csv"
SUMMARY = HERE / "reverify_summary.md"


def build_citation_string(row: dict) -> str:
    """Build a full citation string the parser can handle."""
    case = (row.get("cited_case_name") or "").strip()
    cite = (row.get("citation_text") or "").strip()
    year = (row.get("cited_year") or "").strip()
    if case and year:
        return f"{case}, {cite} ({year})"
    if case:
        return f"{case}, {cite}"
    if year:
        return f"{cite} ({year})"
    return cite


async def main():
    rows = list(csv.DictReader(open(INPUT, encoding="utf-8")))
    print(f"loaded {len(rows)} rows from {INPUT.name}")

    citations = [build_citation_string(r) for r in rows]
    print(f"built {len(citations)} citation strings, e.g.:")
    for c in citations[:3]:
        print(f"  {c}")

    print("\nrunning verify_batch...")
    verifier = CitationVerifier()
    start = time.monotonic()

    def progress(done, total):
        if done % 25 == 0 or done == total:
            elapsed = time.monotonic() - start
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"  {done}/{total}  elapsed={elapsed:.0f}s  rate={rate:.2f}/s  eta={eta:.0f}s", flush=True)

    results = await verifier.verify_batch(citations, progress_callback=progress)
    elapsed = time.monotonic() - start
    print(f"done in {elapsed:.1f}s")

    # Combine input rows + new verification fields
    new_rows = []
    for r, res in zip(rows, results):
        new_rows.append({
            **r,
            "new_v_status": res.status.value,
            "new_v_confidence": f"{res.confidence:.3f}",
            "new_v_url": res.matched_url or "",
            "new_v_matched_name": res.matched_case_name or "",
            "new_v_diagnostics": "; ".join(d.message for d in (res.diagnostics or [])),
        })

    fieldnames = list(new_rows[0].keys())
    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(new_rows)
    print(f"wrote {len(new_rows)} rows to {OUTPUT.name}")

    # ----- diff stats -----
    summary_lines = ["# Step 2 — Re-verify summary", ""]
    summary_lines.append(f"- Input: `{INPUT.name}` ({len(rows)} rows; 26 SCOTUS + 132 Circuit)")
    summary_lines.append(f"- Verifier wall time: {elapsed:.1f}s")
    summary_lines.append("")

    # Old vs new global
    old_counter = Counter(r["v1_v_status"] for r in new_rows)
    new_counter = Counter(r["new_v_status"] for r in new_rows)
    summary_lines.append("## Status distribution: v1 verifier vs current verifier")
    summary_lines.append("")
    summary_lines.append("| status | v1 | current | delta |")
    summary_lines.append("|---|---|---|---|")
    statuses = sorted(set(old_counter) | set(new_counter))
    for s in statuses:
        o = old_counter.get(s, 0)
        n = new_counter.get(s, 0)
        d = n - o
        summary_lines.append(f"| {s} | {o} | {n} | {d:+d} |")
    summary_lines.append("")

    # Per-tier breakdown of NEW verdicts
    summary_lines.append("## Per-tier current-verifier results")
    summary_lines.append("")
    summary_lines.append("| tier | total | VERIFIED | NOT_FOUND | POSSIBLE_MATCH | miss_rate |")
    summary_lines.append("|---|---|---|---|---|---|")
    by_tier = {}
    for r in new_rows:
        by_tier.setdefault(r["tier_label"], []).append(r)
    for tier in ("SCOTUS", "Circuit"):
        tier_rows = by_tier.get(tier, [])
        c = Counter(r["new_v_status"] for r in tier_rows)
        total = len(tier_rows)
        miss = c.get("NOT_FOUND", 0) + c.get("POSSIBLE_MATCH", 0)
        rate = 100 * miss / total if total else 0
        summary_lines.append(
            f"| {tier} | {total} | {c.get('VERIFIED', 0)} | {c.get('NOT_FOUND', 0)} | {c.get('POSSIBLE_MATCH', 0)} | {rate:.1f}% |"
        )
    summary_lines.append("")

    # Status change matrix
    summary_lines.append("## Per-row status change (v1 → current)")
    summary_lines.append("")
    summary_lines.append("| v1 → current | n |")
    summary_lines.append("|---|---|")
    change_counter = Counter((r["v1_v_status"], r["new_v_status"]) for r in new_rows)
    for (o, n), cnt in sorted(change_counter.items(), key=lambda x: -x[1]):
        summary_lines.append(f"| {o} → {n} | {cnt} |")
    summary_lines.append("")

    # Disagreements: rows where v1 said NOT_FOUND or POSSIBLE_MATCH but current says VERIFIED
    recovered = [r for r in new_rows if r["v1_v_status"] in ("NOT_FOUND", "POSSIBLE_MATCH") and r["new_v_status"] == "VERIFIED"]
    regressed = [r for r in new_rows if r["v1_v_status"] == "VERIFIED" and r["new_v_status"] in ("NOT_FOUND", "POSSIBLE_MATCH")]
    summary_lines.append(f"## Recovered ({len(recovered)} rows: v1 NOT_FOUND/POSSIBLE_MATCH → current VERIFIED)")
    summary_lines.append("")
    for r in recovered:
        summary_lines.append(f"- `{r['citation_text']}` — {r['cited_case_name']} ({r['cited_year']}) — v1: {r['v1_v_status']}")
    summary_lines.append("")
    summary_lines.append(f"## Regressed ({len(regressed)} rows: v1 VERIFIED → current NOT_FOUND/POSSIBLE_MATCH)")
    summary_lines.append("")
    for r in regressed:
        summary_lines.append(f"- `{r['citation_text']}` — {r['cited_case_name']} ({r['cited_year']}) — current: {r['new_v_status']}  diag: {r['new_v_diagnostics'][:120]}")
    summary_lines.append("")

    # Still-missing list (current verifier says NOT_FOUND or POSSIBLE_MATCH)
    still_missing = [r for r in new_rows if r["new_v_status"] in ("NOT_FOUND", "POSSIBLE_MATCH")]
    summary_lines.append(f"## Still missing after re-verify ({len(still_missing)} rows)")
    summary_lines.append("")
    summary_lines.append("These are the rows that look like real candidate CL gaps for SCOTUS/Circuit — but each one still needs manual audit before being counted as a true miss (could be eyecite mis-extraction, format quirk, etc.).")
    summary_lines.append("")
    for r in still_missing:
        summary_lines.append(f"- [{r['tier_label']}] `{r['citation_text']}` — {r['cited_case_name']} ({r['cited_year']}) — {r['new_v_status']}  diag: {r['new_v_diagnostics'][:120]}")
    summary_lines.append("")

    SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"wrote {SUMMARY.name}")

    print("\n----- summary -----")
    print(f"Recovered (v1 miss → now verified): {len(recovered)}")
    print(f"Regressed (v1 verified → now miss): {len(regressed)}")
    print(f"Still missing in current verifier:  {len(still_missing)}")


if __name__ == "__main__":
    asyncio.run(main())
