"""
Step 4b: staged fallback test on the 43 NOT_FOUND rows.

User requested 2026-05-15: run NOT_FOUNDs through fallback A
(opinion search) first, then through fallback B (RECAP) for any that
A didn't rescue. Gives a stepped view of how much each fallback
contributes to CL coverage:

  citation_lookup only  -> baseline (already computed in step 4)
  + opinion search      -> stage A rescues
  + RECAP search        -> stage B rescues

For each row we score returned results with the verifier's
CaseNameMatcher (4-factor similarity, ≥0.5 = "credible match"
threshold the verifier itself uses).

The methodological framing for the writeup:
  - citation_lookup coverage    = "indexed by reporter cite"
  - + opinion search            = "indexed OR findable by name search"
  - + RECAP search              = "indexed OR findable in CL anywhere"
                                  (RECAP = PACER docket data, federal only)

Outputs:
  staged_fallback_per_row.csv   per-NOT_FOUND row with stage outcomes
  staged_fallback_summary.md    narrative + per-tier rescue counts
"""
from __future__ import annotations

import asyncio
import csv
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)
sys.path.insert(0, str(ROOT / "src"))

from citation_verifier.client import AsyncCourtListenerClient  # noqa: E402
from citation_verifier.name_matcher import CaseNameMatcher  # noqa: E402

HERE = Path(__file__).parent
COVERAGE_CSV = HERE / "coverage_per_citation.csv"
OUT_CSV = HERE / "staged_fallback_per_row.csv"
OUT_SUMMARY_MD = HERE / "staged_fallback_summary.md"

TARGET_TIERS = ("SCOTUS", "Circuit", "State_COLR", "State_IAC")
SCORE_THRESHOLD = 0.5  # matches the verifier's credible-match cutoff


def year_window(year_str: str) -> tuple[str | None, str | None]:
    """Build a +/- 1 year window (matches the verifier's behavior)."""
    if not year_str:
        return None, None
    try:
        y = int(year_str)
    except (ValueError, TypeError):
        return None, None
    return f"{y-1}-01-01", f"{y+1}-12-31"


def score_results(
    results: list[dict[str, Any]],
    cited_name: str,
    matcher: CaseNameMatcher,
) -> tuple[float, dict[str, Any] | None]:
    """Return (best_score, best_result) for results vs cited_name."""
    if not results or not cited_name:
        return 0.0, None
    best_score = 0.0
    best = None
    for r in results:
        name = r.get("caseName") or r.get("case_name") or ""
        if not name:
            continue
        s = matcher.calculate_similarity(cited_name, name)
        if s > best_score:
            best_score = s
            best = r
    return best_score, best


async def run_stage_opinion(
    client: AsyncCourtListenerClient,
    row: dict[str, str],
    matcher: CaseNameMatcher,
) -> tuple[bool, float, str, str]:
    """Stage A: opinion search. Returns (hit, score, matched_name, url)."""
    case_name = row.get("cited_case_name") or ""
    if not case_name.strip():
        return False, 0.0, "", ""
    filed_after, filed_before = year_window(row.get("year") or "")
    try:
        results = await client.search_opinions(
            q=case_name,
            filed_after=filed_after,
            filed_before=filed_before,
        )
    except Exception:
        results = []
    score, best = score_results(results, case_name, matcher)
    if score < SCORE_THRESHOLD and not results:
        # Retry without year window (the verifier does similar widening)
        try:
            results = await client.search_opinions(q=case_name)
        except Exception:
            results = []
        score, best = score_results(results, case_name, matcher)

    if best and score >= SCORE_THRESHOLD:
        matched_name = best.get("caseName") or best.get("case_name") or ""
        url = best.get("absolute_url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.courtlistener.com{url}"
        return True, score, matched_name, url
    return False, score, "", ""


async def run_stage_recap(
    client: AsyncCourtListenerClient,
    row: dict[str, str],
    matcher: CaseNameMatcher,
) -> tuple[bool, float, str, str]:
    """Stage B: RECAP search by case name. RECAP = federal PACER docket
    data; runs for all rows even though we expect state hits to be
    rare, for transparency. Returns (hit, score, matched_name, url)."""
    case_name = row.get("cited_case_name") or ""
    if not case_name.strip():
        return False, 0.0, "", ""
    try:
        results = await client.search_recap(q=case_name)
    except Exception:
        results = []
    score, best = score_results(results, case_name, matcher)
    if best and score >= SCORE_THRESHOLD:
        matched_name = best.get("caseName") or best.get("case_name") or ""
        url = (best.get("docket_absolute_url")
               or best.get("absolute_url") or "")
        if url and not url.startswith("http"):
            url = f"https://www.courtlistener.com{url}"
        return True, score, matched_name, url
    return False, score, "", ""


async def main() -> int:
    all_rows = list(csv.DictReader(COVERAGE_CSV.open(encoding="utf-8")))
    nf_rows = [r for r in all_rows if r["lookup_status"] == "NOT_FOUND"]
    print(f"Loaded {len(nf_rows)} NOT_FOUND rows from coverage_per_citation.csv")

    matcher = CaseNameMatcher()
    out_rows: list[dict[str, Any]] = []

    t0 = time.monotonic()
    async with AsyncCourtListenerClient() as client:
        for i, r in enumerate(nf_rows, 1):
            hit_a, score_a, name_a, url_a = await run_stage_opinion(client, r, matcher)
            if hit_a:
                stage_b_run = False
                hit_b, score_b, name_b, url_b = False, 0.0, "", ""
                final = "rescued_by_opinion_search"
            else:
                hit_b, score_b, name_b, url_b = await run_stage_recap(client, r, matcher)
                stage_b_run = True
                final = "rescued_by_recap" if hit_b else "still_not_found"

            out = {
                **r,
                "stage_a_hit": "yes" if hit_a else "no",
                "stage_a_score": f"{score_a:.3f}",
                "stage_a_matched_name": name_a,
                "stage_a_url": url_a,
                "stage_b_run": "yes" if stage_b_run else "no",
                "stage_b_hit": "yes" if hit_b else "no",
                "stage_b_score": f"{score_b:.3f}" if stage_b_run else "",
                "stage_b_matched_name": name_b,
                "stage_b_url": url_b,
                "final_outcome": final,
            }
            out_rows.append(out)

            tag = {
                "rescued_by_opinion_search": "A",
                "rescued_by_recap": "B",
                "still_not_found": "-",
            }[final]
            print(f"  [{i:>2}/{len(nf_rows)}] {tag}  {r['cited_tier']:<12} "
                  f"{(r['cited_case_name'] or '')[:40]:<40}  cite={r['citation_string'][:30]:<30}"
                  + (f"  A.score={score_a:.2f}" if hit_a or not stage_b_run else "")
                  + (f"  B.score={score_b:.2f}" if stage_b_run else ""))

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # CSV
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUT_CSV.name}")

    # Per-tier rollup
    per_tier_orig = Counter()  # original total per tier (from all 200)
    for r in all_rows:
        if r["cited_tier"] in TARGET_TIERS:
            per_tier_orig[r["cited_tier"]] += 1

    per_tier_nf_orig = Counter()  # NOT_FOUND from step 4 per tier
    per_tier_a = Counter()        # rescued by stage A
    per_tier_b = Counter()        # rescued by stage B
    per_tier_still = Counter()    # still missing
    for r in out_rows:
        t = r["cited_tier"]
        if t not in TARGET_TIERS:
            continue
        per_tier_nf_orig[t] += 1
        if r["final_outcome"] == "rescued_by_opinion_search":
            per_tier_a[t] += 1
        elif r["final_outcome"] == "rescued_by_recap":
            per_tier_b[t] += 1
        else:
            per_tier_still[t] += 1

    # Coverage rates by tier
    print("\n=== STAGED COVERAGE ===")
    print(f"  {'tier':<12} {'n':>4} {'cite_lkup':>10} {'+opn':>6} {'+recap':>8} {'still':>6} {'cov_after_A':>12} {'cov_after_B':>12}")
    summary_rows = []
    for t in TARGET_TIERS:
        n = per_tier_orig[t]
        in_cl_baseline = n - per_tier_nf_orig[t]
        plus_a = per_tier_a[t]
        plus_b = per_tier_b[t]
        still = per_tier_still[t]
        cov_after_a = in_cl_baseline + plus_a
        cov_after_b = cov_after_a + plus_b
        print(f"  {t:<12} {n:>4} {in_cl_baseline:>10} {plus_a:>+6} {plus_b:>+8} {still:>6} "
              f"{cov_after_a}/{n}={100*cov_after_a/n:>5.1f}%  "
              f"{cov_after_b}/{n}={100*cov_after_b/n:>5.1f}%")
        summary_rows.append({
            "tier": t,
            "n": n,
            "citation_lookup_in_cl": in_cl_baseline,
            "rescued_by_opinion_search": plus_a,
            "rescued_by_recap": plus_b,
            "still_not_found": still,
            "in_cl_after_opn": cov_after_a,
            "in_cl_after_recap": cov_after_b,
            "pct_after_opn": f"{100*cov_after_a/n:.1f}",
            "pct_after_recap": f"{100*cov_after_b/n:.1f}",
        })

    # Narrative
    total = sum(s["n"] for s in summary_rows)
    base = sum(s["citation_lookup_in_cl"] for s in summary_rows)
    a_total = sum(s["rescued_by_opinion_search"] for s in summary_rows)
    b_total = sum(s["rescued_by_recap"] for s in summary_rows)
    still_total = sum(s["still_not_found"] for s in summary_rows)

    lines = [
        "# Step 4b — staged fallback rescue",
        "",
        f"- NOT_FOUND rows from step 4 baseline: {len(nf_rows)}",
        f"- Stage A (opinion search) rescued: {a_total}",
        f"- Stage B (RECAP search) rescued: {b_total}",
        f"- Still NOT_FOUND after both fallbacks: {still_total}",
        "",
        "## Coverage progression by tier",
        "",
        "| tier | n | citation_lookup | + opinion search | + RECAP | still NOT_FOUND | cov_after_opn | cov_after_recap |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in summary_rows:
        lines.append(
            f"| {s['tier']} | {s['n']} | {s['citation_lookup_in_cl']} | "
            f"+{s['rescued_by_opinion_search']} | +{s['rescued_by_recap']} | "
            f"{s['still_not_found']} | {s['in_cl_after_opn']}/{s['n']} = "
            f"{s['pct_after_opn']}% | {s['in_cl_after_recap']}/{s['n']} = "
            f"{s['pct_after_recap']}% |"
        )

    lines += [
        "",
        f"## Overall",
        f"",
        f"- citation_lookup baseline: {base}/{total} = {100*base/total:.1f}%",
        f"- after opinion search:     {base+a_total}/{total} = {100*(base+a_total)/total:.1f}%",
        f"- after RECAP search:       {base+a_total+b_total}/{total} = {100*(base+a_total+b_total)/total:.1f}%",
        f"",
        "## Methodology",
        "",
        f"- Score threshold for 'credible match': {SCORE_THRESHOLD} (matches the verifier's internal cutoff)",
        f"- CaseNameMatcher: 4-factor weighted similarity (sequence / Jaccard / substring / key-words)",
        f"- Stage A queries: search_opinions(q=cited_case_name, filed_after=year-1, filed_before=year+1); falls back to no year window if empty",
        f"- Stage B queries: search_recap(q=cited_case_name); RECAP = PACER docket data, primarily federal",
        f"- Still NOT_FOUND rows after both stages are the strongest candidates for real CL gaps; step 5 audit still recommended.",
        "",
    ]
    OUT_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_SUMMARY_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
