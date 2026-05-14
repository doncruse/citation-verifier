"""
Step 6: feed every model-extracted citation through CourtListener's
citation-lookup API (via verify_batch quick_only=True) and produce a
coverage table.

This is the actual coverage measurement: does CL resolve each cited
citation, or not? Interpretation:

- VERIFIED  : citation-lookup returned a cluster whose name matches the model's
              cited_case_name — in CL, name-confirmed
- LIKELY_REAL : citation-lookup returned a cluster with high confidence but the
              name match wasn't strict — in CL
- POSSIBLE_MATCH : citation-lookup returned a cluster, but the name differs —
              in CL, but cite resolves to a different case than the model named
              (a separate finding from a pure coverage perspective; still
              counts as "citation is in CL")
- NOT_FOUND : citation-lookup returned nothing — *either* a real CL gap *or*
              a model fabrication. Manual spot-check the cited_case_name to
              tell them apart.

We're NOT pre-filtering with the appears_in_source / near_miss flag — per the
earlier discussion, model cleanups (smart quotes, line breaks, pin-cite
canonicalization) are exactly what we want, not hallucinations.

Inputs: pilot_extractions/*.json (all 5 once timeouts retry completes)
Outputs:
- coverage_per_citation.csv: one row per (citing_opinion, cited_citation)
- coverage_per_opinion.csv: roll-up by citing opinion / tier
- coverage_summary.md: narrative
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv(usecwd=False), override=True)

HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
EXTRACTIONS_DIR = HERE / "pilot_extractions"

sys.path.insert(0, str(ROOT / "src"))
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUTPUT_PER_CITATION = HERE / "coverage_per_citation.csv"
OUTPUT_PER_OPINION = HERE / "coverage_per_opinion.csv"
OUTPUT_SUMMARY_MD = HERE / "coverage_summary.md"


def collect_citations():
    """Walk pilot_extractions/, yield rows ready for verify_batch."""
    rows = []
    for f in sorted(EXTRACTIONS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if not data.get("citations_all") and not data.get("citations_appears_in_source"):
            # Likely a timeout file still pending re-run
            continue
        tier_label = data.get("tier_label", "")
        cluster_id = data.get("cluster_id", "")
        citing_case_name = data.get("case_name") or data.get("cited_case_name") or ""
        citing_court_id = data.get("court_id") or data.get("cited_court_id") or ""
        all_cites = data.get("citations_all") or (
            (data.get("citations_appears_in_source") or [])
            + (data.get("citations_near_miss_after_normalize") or [])
            + (data.get("citations_not_in_source") or [])
        )
        for c in all_cites:
            if not isinstance(c, dict):
                continue
            cite_str = (c.get("citation_string") or "").strip()
            if not cite_str:
                continue
            rows.append({
                "citing_tier": tier_label,
                "citing_cluster": cluster_id,
                "citing_case": citing_case_name,
                "citing_court": citing_court_id,
                "citation_string": cite_str,
                "cited_case_name_model": (c.get("cited_case_name") or "").strip(),
                "year": c.get("year"),
                "court_hint": c.get("court_hint"),
                "parenthetical": c.get("parenthetical"),
                "sentence_context": (c.get("sentence_context") or "")[:300],
                "classification": c.get("_classification"),
            })
    return rows


def build_full_citation_str(row: dict) -> str:
    """Build a 'CaseName, citation (year)' string for the verifier."""
    case = row["cited_case_name_model"]
    cite = row["citation_string"]
    year = row.get("year")
    if case and year:
        return f"{case}, {cite} ({year})"
    if case:
        return f"{case}, {cite}"
    if year:
        return f"{cite} ({year})"
    return cite


async def main():
    rows = collect_citations()
    print(f"collected {len(rows)} citations across pilot extractions")
    if not rows:
        print("nothing to look up — wait for extractions to complete")
        return

    citations = [build_full_citation_str(r) for r in rows]
    verifier = CitationVerifier()
    print(f"running verify_batch(quick_only=True) on {len(citations)} citations...")

    start = time.monotonic()

    def progress(done, total):
        if done % 25 == 0 or done == total:
            elapsed = time.monotonic() - start
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"  {done}/{total}  elapsed={elapsed:.0f}s  rate={rate:.2f}/s  eta={eta:.0f}s", flush=True)

    results = await verifier.verify_batch(citations, progress_callback=progress, quick_only=True)
    print(f"done in {time.monotonic()-start:.1f}s")

    # Combine
    out_rows = []
    for r, res in zip(rows, results):
        out_rows.append({
            **r,
            "lookup_status": res.status.value,
            "in_cl": "yes" if res.status.value != "NOT_FOUND" else "no",
            "lookup_confidence": f"{res.confidence:.3f}",
            "lookup_matched_name": res.matched_case_name or "",
            "lookup_matched_url": res.matched_url or "",
            "lookup_diagnostics": "; ".join(d.message for d in (res.diagnostics or []))[:300],
        })

    # Write per-citation CSV
    fieldnames = list(out_rows[0].keys())
    with open(OUTPUT_PER_CITATION, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUTPUT_PER_CITATION.name}")

    # Roll up per opinion / tier
    per_opinion = {}
    for r in out_rows:
        key = (r["citing_tier"], r["citing_cluster"], r["citing_case"][:50])
        per_opinion.setdefault(key, Counter())
        per_opinion[key]["total"] += 1
        per_opinion[key][r["lookup_status"]] += 1
        per_opinion[key]["in_cl"] += 1 if r["in_cl"] == "yes" else 0

    op_rows = []
    for (tier, cluster, case), cnt in sorted(per_opinion.items()):
        op_rows.append({
            "citing_tier": tier,
            "citing_cluster": cluster,
            "citing_case": case,
            "total": cnt.get("total", 0),
            "in_cl": cnt.get("in_cl", 0),
            "miss_rate": f"{100*(cnt.get('total', 0) - cnt.get('in_cl', 0))/max(cnt.get('total', 1), 1):.1f}%",
            "VERIFIED": cnt.get("VERIFIED", 0),
            "LIKELY_REAL": cnt.get("LIKELY_REAL", 0),
            "POSSIBLE_MATCH": cnt.get("POSSIBLE_MATCH", 0),
            "NOT_FOUND": cnt.get("NOT_FOUND", 0),
        })
    fieldnames = list(op_rows[0].keys()) if op_rows else []
    with open(OUTPUT_PER_OPINION, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(op_rows)
    print(f"wrote {OUTPUT_PER_OPINION.name}")

    # Narrative
    overall = Counter()
    for r in out_rows:
        overall["total"] += 1
        overall[r["lookup_status"]] += 1
    miss = overall.get("NOT_FOUND", 0)
    miss_rate = 100 * miss / overall["total"] if overall["total"] else 0

    lines = ["# Pilot coverage results", ""]
    lines.append(f"- Citations looked up: {overall['total']}")
    lines.append(f"- In CL (any non-NOT_FOUND status): {overall['total'] - miss}")
    lines.append(f"- NOT_FOUND (real CL gap or fabrication — needs spot-check): {miss} ({miss_rate:.1f}%)")
    lines.append("")
    lines.append("## Per status breakdown")
    lines.append("")
    lines.append("| status | n | % |")
    lines.append("|---|---|---|")
    for s in ("VERIFIED", "LIKELY_REAL", "POSSIBLE_MATCH", "NOT_FOUND"):
        n = overall.get(s, 0)
        pct = 100 * n / overall["total"] if overall["total"] else 0
        lines.append(f"| {s} | {n} | {pct:.1f}% |")
    lines.append("")
    lines.append("## Per opinion")
    lines.append("")
    lines.append("| tier | cluster | case | total | in_cl | miss_rate |")
    lines.append("|---|---|---|---|---|---|")
    for r in op_rows:
        lines.append(f"| {r['citing_tier']} | {r['citing_cluster']} | {r['citing_case']} | {r['total']} | {r['in_cl']} | {r['miss_rate']} |")
    lines.append("")
    lines.append("## Next step")
    lines.append("")
    lines.append(f"Manually inspect the {miss} NOT_FOUND rows in `coverage_per_citation.csv` — for each, decide whether it's a real CL gap or a model fabrication. (Google the cited_case_name; if it's a real published case, count as CL gap.)")
    OUTPUT_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT_SUMMARY_MD.name}")
    print()
    print(f"=== SUMMARY ===")
    print(f"Citations: {overall['total']}  |  In CL: {overall['total']-miss}  |  Miss: {miss} ({miss_rate:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
