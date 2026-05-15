"""
Step 4 of the real run: CL coverage lookup on the 200-row stratified
sample.

Per REAL_RUN_DESIGN.md step 4: `verify_batch(quick_only=True)`. The
`quick_only=True` flag is essential — it limits the lookup to CL's
citation-lookup API and skips the search-fallback + RECAP fallback
passes. Without quick_only we'd be measuring "is this case findable
in CL by any method", not "does CL have this reporter cite indexed".

Statuses recorded per row:
- VERIFIED      : citation-lookup hit; cited_case_name matches CL's
                  case name → confidently in CL.
- LIKELY_REAL   : citation-lookup hit with high confidence; name match
                  not strict → still in CL.
- POSSIBLE_MATCH: citation-lookup hit, but cluster's case_name differs
                  from the cited_case_name we extracted → reporter cite
                  resolved, but to a different case than the brief
                  named. Counts as in-CL for coverage but is a quality
                  signal.
- NOT_FOUND     : citation-lookup returned nothing. Either a real CL
                  gap or an extraction artifact (e.g. LLM mis-parsed
                  the cite). Step 5 (audit) distinguishes the two.

Outputs:
  coverage_per_citation.csv  one row per cited citation
  coverage_per_tier.csv      per-tier rollup
  coverage_summary.md        narrative
"""
from __future__ import annotations

import asyncio
import csv
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)
sys.path.insert(0, str(ROOT / "src"))

from citation_verifier.verifier import CitationVerifier  # noqa: E402

HERE = Path(__file__).parent
SAMPLE_CSV = HERE / "final_200.csv"
OUT_PER_CITATION = HERE / "coverage_per_citation.csv"
OUT_PER_TIER = HERE / "coverage_per_tier.csv"
OUT_SUMMARY_MD = HERE / "coverage_summary.md"

TARGET_TIERS = ("SCOTUS", "Circuit", "State_COLR", "State_IAC", "Federal_District")


def build_full_citation_str(row: dict) -> str:
    """Build a 'CaseName, citation (year)' string for the verifier."""
    case = (row.get("cited_case_name") or "").strip()
    cite = (row.get("citation_string") or "").strip()
    year = (row.get("year") or "").strip()
    if case and year:
        return f"{case}, {cite} ({year})"
    if case:
        return f"{case}, {cite}"
    if year:
        return f"{cite} ({year})"
    return cite


async def main() -> int:
    rows = list(csv.DictReader(SAMPLE_CSV.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} sample rows from {SAMPLE_CSV.name}")

    citation_strings = [build_full_citation_str(r) for r in rows]

    verifier = CitationVerifier()
    print(f"Running verify_batch(quick_only=True) on {len(citation_strings)} citations...")

    start = time.monotonic()

    def progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            elapsed = time.monotonic() - start
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"  {done}/{total}  elapsed={elapsed:.1f}s  rate={rate:.2f}/s  eta={eta:.0f}s",
                  flush=True)

    results = await verifier.verify_batch(
        citation_strings,
        progress_callback=progress,
        quick_only=True,
    )
    elapsed_total = time.monotonic() - start
    print(f"\nDone in {elapsed_total:.1f}s ({elapsed_total/60:.1f} min)")

    # Combine
    out_rows = []
    for r, res in zip(rows, results):
        diag_msgs = "; ".join(d.message for d in (res.diagnostics or []))[:400]
        out_rows.append({
            **r,
            "lookup_status": res.status.value,
            "in_cl": "yes" if res.status.value != "NOT_FOUND" else "no",
            "lookup_confidence": f"{res.confidence:.3f}",
            "lookup_matched_name": res.matched_case_name or "",
            "lookup_matched_url": res.matched_url or "",
            "lookup_diagnostics": diag_msgs,
        })

    # Per-citation CSV
    fields = list(out_rows[0].keys())
    with OUT_PER_CITATION.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUT_PER_CITATION.name}")

    # Per-tier rollup
    per_tier: dict[str, Counter] = {t: Counter() for t in TARGET_TIERS}
    for r in out_rows:
        t = r["cited_tier"]
        if t not in per_tier:
            continue
        per_tier[t]["total"] += 1
        per_tier[t][r["lookup_status"]] += 1
        if r["in_cl"] == "yes":
            per_tier[t]["in_cl"] += 1

    tier_rows = []
    for t in TARGET_TIERS:
        c = per_tier[t]
        total = c.get("total", 0)
        in_cl = c.get("in_cl", 0)
        miss = total - in_cl
        tier_rows.append({
            "tier": t,
            "n": total,
            "VERIFIED": c.get("VERIFIED", 0),
            "LIKELY_REAL": c.get("LIKELY_REAL", 0),
            "POSSIBLE_MATCH": c.get("POSSIBLE_MATCH", 0),
            "NOT_FOUND": c.get("NOT_FOUND", 0),
            "in_cl": in_cl,
            "miss_rate_pct": f"{100*miss/total:.1f}" if total else "—",
        })
    with OUT_PER_TIER.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tier_rows[0].keys()))
        w.writeheader()
        w.writerows(tier_rows)
    print(f"wrote {OUT_PER_TIER.name}")

    # Overall
    overall = Counter()
    for r in out_rows:
        overall["total"] += 1
        overall[r["lookup_status"]] += 1
        if r["in_cl"] == "yes":
            overall["in_cl"] += 1

    # Narrative
    lines = [
        "# Step 4 — coverage results (pre-audit)",
        "",
        f"- Sample size: {overall['total']}",
        f"- In CL (any status != NOT_FOUND): {overall['in_cl']}",
        f"- NOT_FOUND (real gap OR extraction artifact): "
        f"{overall.get('NOT_FOUND', 0)} ({100*overall.get('NOT_FOUND', 0)/max(overall['total'],1):.1f}%)",
        "",
        "**NOT_FOUND is an upper bound on the true CL gap rate.** Step 5",
        "audits each NOT_FOUND row to split real gaps from extraction noise",
        "(LLM-mis-parsed cites, slip-opinion patterns, etc.). Final per-tier",
        "coverage rate = (n - real_gaps) / n, computed after audit.",
        "",
        "## Status breakdown — overall",
        "",
        "| status | n | % |",
        "|---|---|---|",
    ]
    for s in ("VERIFIED", "LIKELY_REAL", "POSSIBLE_MATCH", "NOT_FOUND"):
        n = overall.get(s, 0)
        pct = 100 * n / overall["total"] if overall["total"] else 0
        lines.append(f"| {s} | {n} | {pct:.1f}% |")

    lines += [
        "",
        "## Per-tier coverage (pre-audit)",
        "",
        "| tier | n | VERIFIED | LIKELY_REAL | POSSIBLE_MATCH | NOT_FOUND | in_cl | NOT_FOUND % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in tier_rows:
        lines.append(
            f"| {r['tier']} | {r['n']} | {r['VERIFIED']} | {r['LIKELY_REAL']} | "
            f"{r['POSSIBLE_MATCH']} | {r['NOT_FOUND']} | {r['in_cl']} | {r['miss_rate_pct']}% |"
        )

    lines += [
        "",
        "## Methodology notes",
        "",
        "- `verify_batch(quick_only=True)`: CL citation-lookup API only. No",
        "  search/RECAP fallback. We measure 'reporter cite indexed in CL',",
        "  not 'findable by any method'.",
        "- Cited tier assigned pre-lookup from reporter pattern + court_hint",
        "  (Bluebook 10.4 parenthetical) — no CL data, no measurement bias.",
        "- POSSIBLE_MATCH = citation found but case_name mismatch. Counts",
        "  as in-CL for coverage but is a separate signal worth flagging.",
        "",
    ]
    OUT_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_SUMMARY_MD.name}")

    # Stdout summary
    print()
    print("=== COVERAGE (PRE-AUDIT) ===")
    for r in tier_rows:
        print(f"  {r['tier']:<12} n={r['n']}  VER={r['VERIFIED']:>3}  "
              f"LR={r['LIKELY_REAL']:>3}  PM={r['POSSIBLE_MATCH']:>3}  "
              f"NF={r['NOT_FOUND']:>3}  in_cl={r['in_cl']:>3}  miss={r['miss_rate_pct']}%")
    print(f"  {'OVERALL':<12} n={overall['total']}  in_cl={overall['in_cl']}  "
          f"NF={overall.get('NOT_FOUND',0)} ({100*overall.get('NOT_FOUND',0)/max(overall['total'],1):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
