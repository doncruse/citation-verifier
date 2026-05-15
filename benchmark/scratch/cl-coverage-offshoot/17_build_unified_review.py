"""
Build a single unified review CSV with all 250 sample rows annotated
with the judgment made at every phase of the analysis pipeline:

  Phase identity   — tier, citing case, cited case, citation, etc.
  Phase 4          — strict citation_lookup status
  Phase 4c         — rigorous staged fallback (opinion / RECAP)
  Phase 5          — audited verdict on each rescue

Final classification per row:
  - in_cl_via_citation_lookup  Phase 4 returned VERIFIED/LIKELY_REAL/POSSIBLE_MATCH
  - in_cl_via_opinion_rescue   Phase 4 was NOT_FOUND; Phase 4c Stage A
                               rescued; Phase 5 audit confirmed TRUE
  - in_cl_via_recap_rescue     Phase 4 was NOT_FOUND; Phase 4c Stage B
                               rescued; Phase 5 audit confirmed TRUE
  - rescue_was_false_positive  Phase 4 was NOT_FOUND; Phase 4c rescued
                               but Phase 5 audit said LIKELY_FALSE
  - not_in_cl                  Phase 4c didn't rescue at all
  - extraction_artifact        LLM dropped cited_case_name; can't audit
                               (subset of "not_in_cl")

Output: unified_review.csv (UTF-8, plain CSV — Excel-compatible).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
SAMPLE_CSV = HERE / "final_200.csv"                          # 250-row sample
STEP4_CSV = HERE / "coverage_per_citation.csv"               # citation_lookup status
STEP4C_CSV = HERE / "staged_fallback_rigorous_per_row.csv"   # rigorous fallback
STEP5_CSV = HERE / "audit_per_row.csv"                       # audit verdicts
OUT_CSV = HERE / "unified_review.csv"


def load_index(path: Path, key_fn) -> dict[Any, dict[str, str]]:
    """Load a CSV into a dict keyed by `key_fn(row)`."""
    out: dict[Any, dict[str, str]] = {}
    if not path.exists():
        return out
    for r in csv.DictReader(path.open(encoding="utf-8")):
        out[key_fn(r)] = r
    return out


def main() -> int:
    # Key on (citing_cluster, citation_string) — unique per row across the pipeline
    def key(r: dict[str, str]) -> tuple[str, str]:
        return (r.get("citing_cluster", ""), r.get("citation_string", ""))

    sample = list(csv.DictReader(SAMPLE_CSV.open(encoding="utf-8")))
    step4 = load_index(STEP4_CSV, key)
    step4c = load_index(STEP4C_CSV, key)
    step5 = load_index(STEP5_CSV, key)

    print(f"Loaded sample: {len(sample)}, step4: {len(step4)}, "
          f"step4c: {len(step4c)}, step5: {len(step5)}")

    out_rows = []
    for r in sample:
        k = key(r)
        s4 = step4.get(k, {})
        s4c = step4c.get(k, {})
        s5 = step5.get(k, {})

        cited_tier = r["cited_tier"]
        cited_case = r.get("cited_case_name") or ""

        # Phase 4 — strict citation_lookup
        p4_status = s4.get("lookup_status", "")
        p4_in_cl = s4.get("in_cl", "")
        p4_matched_name = s4.get("lookup_matched_name", "")
        p4_diag = s4.get("lookup_diagnostics", "")

        # Phase 4c — rigorous fallback (only NOT_FOUND rows went through this)
        p4c_outcome = s4c.get("final_outcome", "")
        p4c_stage_a_status = s4c.get("stage_a_status", "")
        p4c_stage_a_score = s4c.get("stage_a_score", "")
        p4c_stage_a_match = s4c.get("stage_a_matched_name", "")
        p4c_stage_a_url = s4c.get("stage_a_url", "")
        p4c_stage_b_status = s4c.get("stage_b_status", "")
        p4c_stage_b_score = s4c.get("stage_b_score", "")
        p4c_stage_b_match = s4c.get("stage_b_matched_name", "")
        p4c_stage_b_url = s4c.get("stage_b_url", "")

        # Phase 5 — audit (only rescues went through this)
        p5_verdict = s5.get("verdict", "")
        p5_reason = s5.get("reason", "")
        p5_test_cite = s5.get("test_cite_match", "")
        p5_test_parties = s5.get("test_parties", "")
        p5_test_court_id = s5.get("test_court_id", "")
        p5_test_date = s5.get("test_date", "")
        p5_cluster_citations = s5.get("matched_cluster_citations", "")

        # FINAL CLASSIFICATION
        if p4_in_cl == "yes":
            # Step 4 already had it in CL via citation_lookup
            final_status = "in_cl_via_citation_lookup"
            final_reason = f"citation_lookup returned {p4_status}"
        elif not cited_case.strip():
            final_status = "extraction_artifact_no_name"
            final_reason = "LLM dropped cited_case_name — can't verify"
        elif p4c_outcome == "still_not_found":
            final_status = "not_in_cl"
            final_reason = "rigorous fallback found no credible match"
        elif p4c_outcome == "parse_error":
            final_status = "extraction_artifact_unparseable"
            final_reason = "couldn't parse citation_string"
        elif p4c_outcome == "rescued_by_opinion_search":
            if p5_verdict == "VERIFIED_TRUE":
                final_status = "in_cl_via_opinion_rescue"
                final_reason = f"audit confirmed: {p5_reason}"
            elif p5_verdict == "LIKELY_FALSE":
                final_status = "rescue_was_false_positive"
                final_reason = f"audit overturned: {p5_reason}"
            else:
                final_status = f"audit_{p5_verdict.lower()}"
                final_reason = p5_reason
        elif p4c_outcome == "rescued_by_recap":
            if p5_verdict == "VERIFIED_TRUE":
                final_status = "in_cl_via_recap_rescue"
                final_reason = f"audit confirmed: {p5_reason}"
            elif p5_verdict == "LIKELY_FALSE":
                final_status = "rescue_was_false_positive"
                final_reason = f"audit overturned: {p5_reason}"
            else:
                final_status = f"audit_{p5_verdict.lower()}"
                final_reason = p5_reason
        else:
            final_status = "unknown"
            final_reason = f"unexpected pipeline state: p4={p4_status} p4c={p4c_outcome}"

        # Pull a few helpful identity columns
        citing_case = r.get("citing_case_name", "")
        citing_court = r.get("citing_court_id", "")
        citing_cluster = r.get("citing_cluster", "")
        citing_level = r.get("citing_level", "")

        out_rows.append({
            # ----- identity -----
            "cited_tier": cited_tier,
            "cited_case_name": cited_case,
            "citation_string": r.get("citation_string", ""),
            "cited_year": r.get("year", ""),
            "cited_court_hint": r.get("court_hint", ""),
            "parenthetical": (r.get("parenthetical") or "")[:200],
            # ----- citing context -----
            "citing_case_name": citing_case[:80],
            "citing_court_id": citing_court,
            "citing_level": citing_level,
            "citing_cluster": citing_cluster,
            # ----- final classification (the headline column) -----
            "FINAL_STATUS": final_status,
            "FINAL_REASON": final_reason,
            # ----- phase 4: strict citation_lookup -----
            "p4_status": p4_status,
            "p4_in_cl": p4_in_cl,
            "p4_matched_name": p4_matched_name,
            "p4_diag": p4_diag[:200],
            # ----- phase 4c: rigorous staged fallback -----
            "p4c_outcome": p4c_outcome,
            "p4c_stage_a_status": p4c_stage_a_status,
            "p4c_stage_a_score": p4c_stage_a_score,
            "p4c_stage_a_match": p4c_stage_a_match[:80],
            "p4c_stage_a_url": p4c_stage_a_url,
            "p4c_stage_b_status": p4c_stage_b_status,
            "p4c_stage_b_score": p4c_stage_b_score,
            "p4c_stage_b_match": p4c_stage_b_match[:80],
            "p4c_stage_b_url": p4c_stage_b_url,
            # ----- phase 5: audit verdict -----
            "p5_verdict": p5_verdict,
            "p5_reason": p5_reason,
            "p5_test_cite_in_cluster": p5_test_cite,
            "p5_test_parties": p5_test_parties,
            "p5_test_court_id_match": p5_test_court_id,
            "p5_test_date_close": p5_test_date,
            "p5_matched_cluster_citations": p5_cluster_citations[:200],
        })

    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUT_CSV.name} ({len(out_rows)} rows)")

    # Summary by FINAL_STATUS
    from collections import Counter
    summary = Counter(r["FINAL_STATUS"] for r in out_rows)
    print("\n=== FINAL_STATUS distribution ===")
    for s, n in summary.most_common():
        print(f"  {s:<32} {n:>4}  ({100*n/len(out_rows):.1f}%)")

    # Per-tier x final_status
    print("\n=== Per-tier x final_status ===")
    by_tier_status: dict[tuple[str, str], int] = Counter()
    for r in out_rows:
        by_tier_status[(r["cited_tier"], r["FINAL_STATUS"])] += 1
    tiers = ("SCOTUS", "Circuit", "State_COLR", "State_IAC", "Federal_District")
    statuses = (
        "in_cl_via_citation_lookup",
        "in_cl_via_opinion_rescue",
        "in_cl_via_recap_rescue",
        "rescue_was_false_positive",
        "not_in_cl",
        "extraction_artifact_no_name",
        "extraction_artifact_unparseable",
    )
    print(f"  {'tier':<16}  " + " ".join(f"{s[:16]:>16}" for s in statuses))
    for t in tiers:
        cells = [f"{by_tier_status.get((t, s), 0):>16}" for s in statuses]
        print(f"  {t:<16}  " + " ".join(cells))

    return 0


if __name__ == "__main__":
    sys.exit(main())
