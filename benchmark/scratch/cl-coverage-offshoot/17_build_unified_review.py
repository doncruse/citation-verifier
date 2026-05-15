"""
Build a single unified review CSV with all 250 sample rows annotated
with the judgment made at every phase of the analysis pipeline:

  Phase identity   — tier, citing case, cited case, citation, etc.
  Phase 4          — strict citation_lookup status
  Phase 4c         — rigorous staged fallback (opinion / RECAP)
  Phase 5          — audited verdict on each rescue
  Phase 6          — short-form dedup + exclusion (this script)

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
  - duplicate_of_fuller_sibling  (Phase 6) Short-form citation that has
                               a fuller sibling in the same opinion for
                               the same case — the sibling is canonical.
                               Dropped from both numerator and denominator.
  - excluded_incomplete_citation  (Phase 6) Unresolvable short-form
                               (no fuller sibling in extraction). Excluded
                               from the denominator — not a measurable miss.

Output: unified_review.csv (UTF-8, plain CSV — Excel-compatible).
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# === Short-form citation detection (Phase 6) ===
# A "short form" is a pin-cite or stub that cannot be resolved to a unique
# opinion via CL's citation lookup alone, e.g.:
#   "594 U.S. at 442"        — pin cite, no start page
#   "523 U.S."               — volume+reporter, no page at all
#   "360 F. Supp. 2d"        — reporter stub with no page
#   "B225051"                — California internal docket number
#   "Id. at 741", "Jd. at 7" — Id./OCR-garbled short forms
_SHORT_FORM_PATTERNS = (
    re.compile(r"^\s*\d+\s+[A-Za-z][\w.\s()]*?\s+at\s", re.IGNORECASE),  # "N REPORTER at P"
    re.compile(r"^\s*\d+\s+[A-Za-z][\w.\s]*[A-Za-z.]\s*$"),               # "N REPORTER" stub (no page)
    re.compile(r"^\s*[A-Z]\d{6}\s*$"),                                    # California docket "B225051"
    re.compile(r"^\s*[IJij]d\.?\s+at\b", re.IGNORECASE),                  # "Id. at P" / OCR-garbled "Jd."
)


def is_short_form(cite: str) -> bool:
    """True iff the citation string is a short form/stub that can't be
    resolved to a unique opinion via citation_lookup."""
    s = (cite or "").strip()
    if not s:
        return False
    return any(p.match(s) for p in _SHORT_FORM_PATTERNS)


def _normalize_name(name: str) -> str:
    """Loose normalize for sibling matching: lowercase, strip punctuation,
    collapse whitespace. Used only to group short-forms with their fuller
    antecedents in the same citing opinion."""
    n = (name or "").lower().strip()
    n = re.sub(r"[.,]", "", n)
    n = re.sub(r"\s+", " ", n)
    return n


def find_fuller_siblings(
    sample_rows: list[dict[str, str]],
) -> dict[tuple[str, str], str]:
    """For each (citing_cluster, citation_string) row, return its
    dedup status:
      ""                 — not a short-form (no action)
      "duplicate"        — short-form WITH a fuller sibling in same opinion
      "excluded"         — short-form WITHOUT a fuller sibling (no name or
                           no antecedent extracted)
    """
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in sample_rows:
        k = (r.get("citing_cluster", ""), _normalize_name(r.get("cited_case_name", "")))
        groups[k].append(r)

    status: dict[tuple[str, str], str] = {}
    for r in sample_rows:
        cite = r.get("citation_string", "")
        row_key = (r.get("citing_cluster", ""), cite)
        if not is_short_form(cite):
            status[row_key] = ""
            continue
        name_key = _normalize_name(r.get("cited_case_name", ""))
        if not name_key:
            # No name to match against; can't find a fuller sibling
            status[row_key] = "excluded"
            continue
        sibs = groups.get((r.get("citing_cluster", ""), name_key), [])
        has_fuller = any(
            s is not r and not is_short_form(s.get("citation_string", ""))
            for s in sibs
        )
        status[row_key] = "duplicate" if has_fuller else "excluded"
    return status

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

    # Phase 6 — short-form dedup + exclusion
    short_form_status = find_fuller_siblings(sample)
    n_dup = sum(1 for v in short_form_status.values() if v == "duplicate")
    n_exc = sum(1 for v in short_form_status.values() if v == "excluded")
    print(f"Phase 6 short-form: {n_dup} duplicates of fuller siblings, "
          f"{n_exc} unresolvable (excluded from denominator)")

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
        dedup_status = short_form_status.get(k, "")

        # Phase 6 override: a short-form citation that has a fuller sibling
        # in the same opinion is a duplicate — drop it (the sibling is the
        # canonical row for this case in this opinion). Applies regardless
        # of the short-form's own Phase 4/4c/5 outcome.
        if dedup_status == "duplicate":
            final_status = "duplicate_of_fuller_sibling"
            final_reason = "short-form citation; fuller sibling exists in same opinion"
        # Phase 6 override: a short-form WITHOUT a fuller sibling is only
        # excluded if it wasn't a lucky citation_lookup hit. A lucky hit is
        # a real match and should stay in the numerator/denominator.
        elif dedup_status == "excluded" and p4_in_cl != "yes":
            final_status = "excluded_incomplete_citation"
            final_reason = "short-form citation; no antecedent in extraction — not measurable"
        elif p4_in_cl == "yes":
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
        "duplicate_of_fuller_sibling",
        "excluded_incomplete_citation",
        "extraction_artifact_no_name",
        "extraction_artifact_unparseable",
    )
    print(f"  {'tier':<16}  " + " ".join(f"{s[:16]:>16}" for s in statuses))
    for t in tiers:
        cells = [f"{by_tier_status.get((t, s), 0):>16}" for s in statuses]
        print(f"  {t:<16}  " + " ".join(cells))

    # Corrected coverage: numerator = any in_cl status; denominator = all
    # rows except the unmeasurable (duplicate/excluded/extraction_artifact).
    in_cl_statuses = {
        "in_cl_via_citation_lookup",
        "in_cl_via_opinion_rescue",
        "in_cl_via_recap_rescue",
    }
    unmeasurable_statuses = {
        "duplicate_of_fuller_sibling",
        "excluded_incomplete_citation",
        "extraction_artifact_no_name",
        "extraction_artifact_unparseable",
    }
    print("\n=== Corrected coverage (Phase 6 applied) ===")
    print(f"  {'tier':<16}  {'in_cl':>6} / {'denom':>5}  = {'pct':>6}   (excluded: dup/inc/art)")
    overall_in = overall_denom = overall_excluded = 0
    for t in tiers:
        in_n = sum(by_tier_status.get((t, s), 0) for s in in_cl_statuses)
        excluded_n = sum(by_tier_status.get((t, s), 0) for s in unmeasurable_statuses)
        denom = sum(by_tier_status.get((t, s), 0) for s in statuses) - excluded_n
        pct = 100.0 * in_n / denom if denom else 0.0
        print(f"  {t:<16}  {in_n:>6} / {denom:>5}  = {pct:>5.1f}%   (excluded: {excluded_n})")
        overall_in += in_n
        overall_denom += denom
        overall_excluded += excluded_n
    overall_pct = 100.0 * overall_in / overall_denom if overall_denom else 0.0
    print(f"  {'OVERALL':<16}  {overall_in:>6} / {overall_denom:>5}  = {overall_pct:>5.1f}%   (excluded: {overall_excluded})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
