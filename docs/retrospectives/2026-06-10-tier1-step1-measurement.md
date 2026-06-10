# Tier 1 Step 1 — Fake-Citation Measurement Run

**Date:** 2026-06-10
**Code:** main @ 3ec7ad1 (v0.3)
**Command:** `pytest tests/test_false_positives.py -m live_api -v` (19 entries)
plus `pytest tests/test_false_negatives.py -m live_api -v` (5 real cites)
**Raw dump:** `scratch/fp_triage_result.json` (regenerate with `scratch/fp_triage_run.py`)

## Headline

- **False positives: 8 / 19 now rejected, 11 / 19 still verify** under v0.3.
- **False negatives: 5 / 5 real citations still VERIFIED** — no regression on the real-cite corpus from any change so far.

The test assertion (`test_false_positives.py:143`) only fails on a
VERIFIED-*family* status, so "11 failed" in pytest == "11 still false-positive."
`WRONG_CASE` and `NOT_FOUND` both pass.

## What v0.3 already fixed (8)

| Citation | v0.2 prior | v0.3 | Why it's fixed |
|---|---|---|---|
| Bloomberg L.P. v. Bd. of Govs. | (fabricated) | NOT_FOUND | — |
| Hogan v. AT&T | — | **WRONG_CASE** @1.0 | new taxonomy: cite resolves, name mismatches |
| Head v. Chicora Life Ctr. | — | NOT_FOUND | — |
| Shell Petroleum N.V. | — | **WRONG_CASE** @1.0 | new taxonomy |
| Butler Motors v. Benosky | — | NOT_FOUND | wrong page; cite doesn't resolve |
| TIG Ins. Co. v. Carter | — | **WRONG_CASE** @1.0 | new taxonomy |
| Gallagher v. Wilton | — | **WRONG_CASE** @1.0 | new taxonomy |
| Thompson v. Best, 118 N.E.3d | NOT_FOUND | **WRONG_CASE** @1.0 | improved: now positively identifies the conflicting case |

The big v0.3 win is the **`WRONG_CASE` status** for `wrong_name_real_citation`
entries — exactly the ideal outcome (the cite resolves, but to a different
case). 5 of the 8 passes are this pattern.

## What still verifies — the 11 false positives

| # | Citation | v0.3 status | conf | Matched (wrong) case | Path |
|---|---|---|---|---|---|
| 1 | Gibbs v. Wright (WL) | VERIFIED_DOCKET_ONLY | 0.43 | United States v. Draughn | RECAP |
| 2 | Lopez v. Bank of Am. (WL) | VERIFIED_DOCKET_ONLY | **0.85** | Lopez v. Bank of America NA | RECAP |
| 3 | Reed v. ZipRecruiter (WL) | VERIFIED_DOCKET_ONLY | 0.42 | Adzhikosyan v. AT&T | RECAP |
| 4 | In re Tenn. Dep't Homeland Sec. | VERIFIED_DOCKET_ONLY | 0.45 | Bledsoe v. TVA Board | RECAP |
| 5 | Johnson v. Mitchell (WL) | **VERIFIED** | 0.50 | Scudder v. Mitchell | opinion search |
| 6 | Thompson v. Best, 989 N.E.2d | **VERIFIED** | 0.625 | Thompson v. Thompson | opinion search |
| 7 | South Pointe Wholesale v. Vilardi | VERIFIED_DOCKET_ONLY | 0.42 | Thompson v. Martuscello | RECAP |
| 8 | Pointe Wholesale v. 5 Vilardi | VERIFIED_DOCKET_ONLY | 0.42 | Thompson v. Martuscello | RECAP |
| 9 | Mavy v. Comm'n SSA (9-digit WL) | VERIFIED_DOCKET_ONLY | 0.45 | Alley v. County of Pima | RECAP |
| 10 | Marion v. Hollis Cobb (WL) | VERIFIED_DOCKET_ONLY | 0.41 | Winer v. Mohammad | RECAP |
| 11 | In re Hudson, 11 U.S. 225 (1812) | VERIFIED_DOCKET_ONLY | 0.50 | In re Hudson (2018 bankruptcy) | RECAP |

**Regression to note:** South Pointe Wholesale (#7) was `NOT_FOUND` under v0.2
and is now a false positive — v0.3's RECAP path matches an unrelated docket
(Thompson v. Martuscello) the old engine rejected.

## Root cause — reshapes Step 2

**9 of 11 failures are `VERIFIED_DOCKET_ONLY` from the RECAP path; only 2 are
from opinion search.** The roadmap framed Step 2 as per-factor penalties inside
`_score_match`. The measurement says the dominant lever is elsewhere:

> The **opinion-search path** (`_process_results`, verifier.py:1096) applies two
> **hard-gates** before scoring — a temporal gate (`_TEMPORAL_GATE_YEARS = 5`,
> line 1116) and a name-token gate (≥1 shared ≥4-char distinctive token, line
> 1124). The **RECAP path** (`_process_recap_results`, line 1019, and its async
> twin `_process_recap_results_async`, line 2694) applies **neither.**

Every zero-party-overlap RECAP match (#1, 3, 4, 7, 8, 9, 10 — seven of them)
would be killed by the **name-token gate** that already exists and is already
tested on the opinion path. They share no distinctive token with the cited
caption (e.g. "South Pointe Wholesale v. Vilardi" → "Thompson v. Martuscello").

So Step 2 should be reordered:

### Lever 1 (biggest, cheapest): port the two hard-gates to the RECAP path
Both sync (`_process_recap_results`) and async (`_process_recap_results_async`).
Reuses existing, tested logic. Directly kills #1, #3, #4, #7, #8, #9, #10.

- **Name-token gate** → the 7 zero-overlap matches above.
- **Temporal gate** → **In re Hudson (#11)**. This is the roadmap's
  "hard date-mismatch gate (1812 vs 2018)." It does **not** belong inside
  `_score_match` as the roadmap suggested: the docket-only path
  (`_build_docket_only_candidate`, line 1252) calls `_score_match` with
  `result_date=""`, so the date branch is skipped and never sees the 2018.
  The 2018 lives on the docket's `dateFiled` in the search result. Gate it at
  the candidate level (like `_process_results` does), reading the docket
  `dateFiled` — **not** in `_score_match`.

  **⚠ Asymmetry required (caught in post-run review):** RECAP docket
  `dateFiled` is the *case filing date*, not the opinion date (see CLAUDE.md
  architecture note). A symmetric ±5-year gate like the opinion path's would
  wrongly reject real citations to opinions issued >5 years into a
  long-running case (cited year ≫ filing year is legitimate). The impossible
  direction is the other one: an opinion cannot predate its case's filing.
  So the RECAP gate must be **one-sided** — reject when
  `parsed.year < filing_year - tolerance` (In re Hudson: 1812 < 2018 ✓
  rejected), never when the cited year is *after* filing. The opinion-search
  path keeps its symmetric gate because cluster `dateFiled` there IS the
  decision date.

  **Guard now in place:** the false-negative corpus was widened 5 → 14
  (2026-06-09) specifically to cover this. `recap_long_running_date_gap`
  pins **Oracle Am. v. Google, 2016 WL 3181206** — docket filed 2010-08-12,
  cited opinion 2016, resolves `VERIFIED_VIA_RECAP` to docket 4177532. The
  test asserts the docket id (not just "not NOT_FOUND"), so a symmetric
  ±5yr RECAP gate would fail it. `test_false_negatives.py` gained
  `expected_docket_id` support for this. Lever 1 must keep both
  `test_false_positives.py` (In re Hudson rejected) and
  `test_false_negatives.py` (Oracle accepted) green.

### Lever 2: both-sides party-mismatch penalty in `_score_match`
For the 2 opinion-search FPs that pass the name-token gate on a *shared*
surname:
- **Johnson v. Mitchell → Scudder v. Mitchell** (defendant matches, plaintiff
  absent).
- **Thompson v. Best → Thompson v. Thompson** (plaintiff matches, defendant
  absent).

The roadmap called this a "defendant-mismatch penalty"; the data shows it must
be **symmetric** — penalize when the candidate matches one cited party strongly
but the *other* cited party is entirely absent from the candidate name. This is
the surname-inflation failure mode.

### Lever 3: docket-number / WL contradiction penalty
For **Lopez v. Bank of Am. (#2)** — the only high-confidence FP at **0.85**.
Name and court legitimately match a real Lopez/Bank of America docket; the
cited docket number, WL number, and date all belong to no real document. Today
a docket mismatch only forfeits its 5% weight (`_score_match`, line 2321); an
*active contradiction* (cited value present, found value present, they differ)
should subtract, not just withhold.
**Caution:** must not regress the false-negative corpus — real cites where CL
simply lacks the WL number currently get a "could not be confirmed" pass
(line 2359) and must stay passing. Penalize only on present-and-contradicting,
never on absent.

## Suggested Step 2 order

1. Lever 1 (RECAP hard-gate parity) — biggest win, lowest risk, reuses tested code. ~7 fixes.
2. Lever 2 (symmetric party penalty) — 2 fixes, guard the real-cite corpus.
3. Lever 3 (docket/WL contradiction penalty) — 1 fix (Lopez 0.85), the trickiest; do last and re-run false-negatives after.

Re-run **both** `test_false_positives.py` and `test_false_negatives.py`
(`-m live_api`) after each lever — they are the regression harness in both
directions.
