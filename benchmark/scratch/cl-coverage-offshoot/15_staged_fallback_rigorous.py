"""
Step 4c: staged fallback redux — RIGOROUS edition.

The 2026-05-15 eyeball check on the previous staged fallback
(14_staged_fallback.py) showed name-only scoring at threshold 0.5
admits clear false positives:

  Cnty. of Sacramento v. Lewis (523 U.S.) -> Decker v. Cnty of Sacramento  ← wrong case
  Hubbard (650 F.2d)                      -> Hubbard v. Hubbard            ← LLM dropped name; any Hubbard matches
  Preston v. Smith (2023 WL ...)          -> Taylor v. Aspy, Preston ...   ← Preston is a co-defendant
  Iglesias v. City of Hialeah             -> DIPIETRO v. CITY OF HIALEAH   ← totally different plaintiff
  Frankling Inc. v. BA CE Services        -> just "v."                     ← garbage match

The verifier's actual search-fallback path uses multi-factor scoring
(name + court + date + docket) plus a court-mismatch guard that forces
NOT_FOUND when a reporter cite is provided but the matched cluster's
court doesn't match the cited court. My custom name-only scoring
dropped all of that.

Fix: rebuild staged fallback using:
- parse_citation() to get a proper ParsedCitation
- verifier._process_results() to get multi-factor-scored candidates
- verifier._build_fallback_result() to apply thresholds + court guards
  exactly as the production verifier does (LIKELY_REAL >= 0.85,
  POSSIBLE_MATCH >= 0.40 with cite-corroboration requirement).

Stage A = opinion search candidates only.
Stage B = RECAP search candidates only.
Hit per stage = _build_fallback_result returns non-NOT_FOUND.

The court-mismatch guard means: when we have a reporter cite like
"22 F.4th 450" and the matched cluster's court ≠ 5th Cir, the result
is forced to NOT_FOUND. That catches the Iglesias / Terry Black's
type errors automatically.

Outputs:
  staged_fallback_rigorous_per_row.csv
  staged_fallback_rigorous_summary.md
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
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parse_citation  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

HERE = Path(__file__).parent
COVERAGE_CSV = HERE / "coverage_per_citation.csv"
OUT_CSV = HERE / "staged_fallback_rigorous_per_row.csv"
OUT_SUMMARY_MD = HERE / "staged_fallback_rigorous_summary.md"

TARGET_TIERS = ("SCOTUS", "Circuit", "State_COLR", "State_IAC", "Federal_District")


def build_full_citation_str(row: dict[str, str]) -> str:
    """Same format as step 4 — give the parser as much signal as we have."""
    case = (row.get("cited_case_name") or "").strip()
    cite = (row.get("citation_string") or "").strip()
    year = (row.get("year") or "").strip()
    hint = (row.get("court_hint") or "").strip()
    # Build a parenthetical for the parser: (Court Year)
    paren_parts = []
    if hint:
        paren_parts.append(hint)
    if year:
        paren_parts.append(year)
    if paren_parts:
        return f"{case}, {cite} ({' '.join(paren_parts)})" if case else f"{cite} ({' '.join(paren_parts)})"
    if case:
        return f"{case}, {cite}"
    return cite


async def run_stage_a(
    verifier: CitationVerifier,
    async_client: AsyncCourtListenerClient,
    citation_text: str,
    parsed: Any,
) -> tuple[Any, list[Any], str | None]:
    """Stage A: opinion search only. Returns (result, candidates, court_id)."""
    court_id, filed_after, filed_before = verifier._build_search_params(parsed)

    candidates = []
    if parsed.case_name:
        try:
            results = await async_client.search_opinions(
                q=parsed.case_name,
                court=court_id,
                filed_after=filed_after,
                filed_before=filed_before,
            )
            candidates = verifier._process_results(results, parsed)
            # Retry without court filter if no candidates (mirrors the
            # production fallback's behavior)
            if not candidates and court_id:
                results = await async_client.search_opinions(
                    q=parsed.case_name,
                    filed_after=filed_after,
                    filed_before=filed_before,
                )
                candidates = verifier._process_results(results, parsed)
        except Exception:
            pass

    result = verifier._build_fallback_result(citation_text, parsed, candidates, court_id)
    return result, candidates, court_id


async def run_stage_b(
    verifier: CitationVerifier,
    async_client: AsyncCourtListenerClient,
    citation_text: str,
    parsed: Any,
) -> tuple[Any, list[Any], str | None]:
    """Stage B: RECAP search only. Returns (result, candidates, court_id)."""
    court_id, _, _ = verifier._build_search_params(parsed)
    candidates = []

    # RECAP search by docket number (if we have one)
    if parsed.docket_number:
        try:
            results = await async_client.search_recap(docket_number=parsed.docket_number)
            cited_dn = verifier._normalize_docket_number(parsed.docket_number)
            results = [
                r for r in results
                if verifier._normalize_docket_number(
                    r.get("docketNumber") or r.get("docket_number") or ""
                ) == cited_dn
            ]
            recap_candidates = await verifier._process_recap_results_async(
                async_client, results, parsed
            )
            candidates.extend(recap_candidates)
        except Exception:
            pass

    # RECAP search by case name
    if parsed.case_name:
        try:
            results = await async_client.search_recap(q=parsed.case_name, court=court_id)
            recap_candidates = await verifier._process_recap_results_async(
                async_client, results, parsed
            )
            candidates.extend(recap_candidates)
        except Exception:
            pass

    result = verifier._build_fallback_result(citation_text, parsed, candidates, court_id)
    return result, candidates, court_id


def status_to_outcome(status_value: str) -> str:
    """Map the verifier's status to a stage rescue flag."""
    if status_value in ("VERIFIED", "LIKELY_REAL", "POSSIBLE_MATCH"):
        return "rescued"
    return "not_rescued"


async def main() -> int:
    all_rows = list(csv.DictReader(COVERAGE_CSV.open(encoding="utf-8")))
    nf_rows = [r for r in all_rows if r["lookup_status"] == "NOT_FOUND"]
    print(f"Loaded {len(nf_rows)} NOT_FOUND rows from coverage_per_citation.csv")

    verifier = CitationVerifier()
    out_rows: list[dict[str, Any]] = []

    t0 = time.monotonic()
    async with AsyncCourtListenerClient() as async_client:
        for i, r in enumerate(nf_rows, 1):
            citation_text = build_full_citation_str(r)
            try:
                parsed = parse_citation(citation_text)
            except Exception as e:
                print(f"  [{i:>2}/{len(nf_rows)}] PARSE_ERROR  {e}")
                out_rows.append({
                    **r,
                    "full_citation": citation_text,
                    "parse_error": str(e)[:200],
                    "stage_a_status": "PARSE_ERROR",
                    "stage_a_score": "",
                    "stage_a_matched_name": "",
                    "stage_a_matched_court": "",
                    "stage_a_matched_date": "",
                    "stage_a_url": "",
                    "stage_a_diag": "",
                    "stage_b_run": "no",
                    "stage_b_status": "",
                    "stage_b_score": "",
                    "stage_b_matched_name": "",
                    "stage_b_matched_court": "",
                    "stage_b_matched_date": "",
                    "stage_b_url": "",
                    "stage_b_diag": "",
                    "final_outcome": "parse_error",
                })
                continue

            # Stage A
            result_a, candidates_a, court_a = await run_stage_a(
                verifier, async_client, citation_text, parsed
            )
            a_status = result_a.status.value
            a_outcome = status_to_outcome(a_status)

            stage_b_run = a_outcome == "not_rescued"
            result_b = None
            if stage_b_run:
                result_b, _, _ = await run_stage_b(verifier, async_client, citation_text, parsed)
                b_status = result_b.status.value
                b_outcome = status_to_outcome(b_status)
            else:
                b_status = ""
                b_outcome = ""

            if a_outcome == "rescued":
                final = "rescued_by_opinion_search"
            elif b_outcome == "rescued":
                final = "rescued_by_recap"
            else:
                final = "still_not_found"

            tag = {
                "rescued_by_opinion_search": "A",
                "rescued_by_recap": "B",
                "still_not_found": "-",
                "parse_error": "?",
            }[final]

            print(f"  [{i:>2}/{len(nf_rows)}] {tag}  {r['cited_tier']:<16} "
                  f"{(r['cited_case_name'] or '')[:35]:<35}  "
                  f"cite={r['citation_string'][:25]:<25}  "
                  f"A={a_status}({result_a.confidence:.2f})"
                  + (f"  B={b_status}({result_b.confidence:.2f})" if result_b else ""))

            out_rows.append({
                **r,
                "full_citation": citation_text,
                "parse_error": "",
                "stage_a_status": a_status,
                "stage_a_score": f"{result_a.confidence:.3f}",
                "stage_a_matched_name": result_a.matched_case_name or "",
                "stage_a_matched_court": result_a.matched_court or "",
                "stage_a_matched_date": result_a.matched_date or "",
                "stage_a_url": result_a.matched_url or "",
                "stage_a_diag": "; ".join(d.message for d in (result_a.diagnostics or []))[:300],
                "stage_b_run": "yes" if stage_b_run else "no",
                "stage_b_status": b_status,
                "stage_b_score": f"{result_b.confidence:.3f}" if result_b else "",
                "stage_b_matched_name": result_b.matched_case_name if result_b else "",
                "stage_b_matched_court": result_b.matched_court if result_b else "",
                "stage_b_matched_date": result_b.matched_date if result_b else "",
                "stage_b_url": result_b.matched_url if result_b else "",
                "stage_b_diag": ("; ".join(d.message for d in (result_b.diagnostics or [])) if result_b else "")[:300],
                "final_outcome": final,
            })

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
    per_tier_orig = Counter()
    for r in all_rows:
        if r["cited_tier"] in TARGET_TIERS:
            per_tier_orig[r["cited_tier"]] += 1
    per_tier_nf_orig = Counter()
    per_tier_a = Counter()
    per_tier_b = Counter()
    per_tier_still = Counter()
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

    print("\n=== STAGED COVERAGE (RIGOROUS) ===")
    print(f"  {'tier':<16} {'n':>4} {'cite_lkup':>10} {'+opn':>6} {'+recap':>8} {'still':>6} {'cov_after_A':>14} {'cov_after_B':>14}")
    summary_rows = []
    for t in TARGET_TIERS:
        n = per_tier_orig[t]
        in_cl_baseline = n - per_tier_nf_orig[t]
        plus_a = per_tier_a[t]
        plus_b = per_tier_b[t]
        still = per_tier_still[t]
        cov_after_a = in_cl_baseline + plus_a
        cov_after_b = cov_after_a + plus_b
        print(f"  {t:<16} {n:>4} {in_cl_baseline:>10} {plus_a:>+6} {plus_b:>+8} {still:>6} "
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

    total = sum(s["n"] for s in summary_rows)
    base = sum(s["citation_lookup_in_cl"] for s in summary_rows)
    a_total = sum(s["rescued_by_opinion_search"] for s in summary_rows)
    b_total = sum(s["rescued_by_recap"] for s in summary_rows)
    still_total = sum(s["still_not_found"] for s in summary_rows)

    lines = [
        "# Step 4c — staged fallback (rigorous, multi-factor scoring)",
        "",
        "Uses the verifier's `_process_results` (multi-factor name+court+date+docket scoring) ",
        "and `_build_fallback_result` (which applies the LIKELY_REAL/POSSIBLE_MATCH thresholds ",
        "PLUS a court-mismatch guard that forces NOT_FOUND when a reporter cite's court doesn't ",
        "match the best candidate's court).",
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
        "## Overall",
        "",
        f"- citation_lookup baseline: {base}/{total} = {100*base/total:.1f}%",
        f"- after opinion search:     {base+a_total}/{total} = {100*(base+a_total)/total:.1f}%",
        f"- after RECAP search:       {base+a_total+b_total}/{total} = {100*(base+a_total+b_total)/total:.1f}%",
        f"",
    ]
    OUT_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_SUMMARY_MD.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
