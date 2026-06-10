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

## Lever 1 — IMPLEMENTED (2026-06-09)

RECAP hard-gate parity landed. New `_recap_result_gated()` helper, wired
into both `_process_recap_results` (sync) and `_process_recap_results_async`,
applies before the docket-entries fetch:

- **Name-token gate** — reuses `_name_tokens`; rejects a docket sharing no
  distinctive token with the cited caption (mirrors `_process_results`).
- **One-sided temporal gate** — rejects only when
  `filing_year - parsed.year > _TEMPORAL_GATE_YEARS` (cite predates filing),
  never the reverse. Reads the result's `dateFiled` (the docket *filing*
  date, confirmed live).
- **PACER-era floor** (`_RECAP_PACER_ERA_FLOOR = 1990`) — added during
  implementation when In re Hudson turned out to resolve, on live data, to a
  *null-`dateFiled`* appellate docket (number `16-6270`) that the date-diff
  check can't evaluate. RECAP is electronic PACER data that doesn't predate
  ~1990, so a pre-1990 cite reaching the RECAP fallback can't be a real
  docket match. Corpus's oldest real RECAP cite is 2006 → ample margin.

**Results (live):**
- False positives **11 → 3**. All 7 zero-overlap RECAP matches + In re
  Hudson now NOT_FOUND. Remaining 3 are exactly the Lever 2/3 cases
  (Johnson v. Mitchell, Thompson v. Best → Lever 2; Lopez → Lever 3), now
  marked `xfail` in `known_fake_citations.json` so they xpass-alert when
  fixed.
- False negatives **14/14 held** — no real cite over-gated; Oracle (date-gap
  guard), Marlite, and Moore all still resolve.
- Unit coverage: `TestRecapHardGates` (5 mocked tests, TDD). Full mocked
  suite 263 passed.

Tests: `tests/test_verifier.py::TestRecapHardGates`. Code:
`verifier.py::_recap_result_gated` + the two call sites.

**Next: Lever 2** (symmetric party-mismatch penalty in `_score_match`).

## Lever 2 — IMPLEMENTED (2026-06-09)

Symmetric party-mismatch handling in `_score_match`, in three parts (each
discovered by following the live evidence):

1. **Name-similarity penalty** (`_PARTY_MISMATCH_NAME_FACTOR = 0.25`) — when
   `_party_overlap_ok` is False (candidate matches only one cited party, the
   other absent), the name contribution is discounted. Reuses the existing,
   calibrated `_party_overlap_ok`. Killed the opinion-search FPs
   (Johnson → Scudder v. Mitchell; Thompson → Thompson v. Thompson).
2. **No-corroboration cap** — the penalty alone was insufficient: these fakes
   are crafted to name a plausible real court + year, so a *different* wrong
   case in that court/year scores ~0.40 on court+date regardless of name
   (Johnson then matched a 2020 S.D. Ohio doc, Laile v. Mitchell, at 0.43).
   So when party overlap fails AND neither the reporter/WL cite NOR the
   docket number is positively confirmed, cap the score below threshold. A
   cite-match or docket-match is the escape hatch protecting
   cl_display_name_data_bug cases (a real record whose CL caption lists a
   different party).
3. **Docket-normalizer fix** — adding the docket-match escape surfaced that
   `_normalize_docket_number` stripped only ONE trailing judge token, so
   paired District+Magistrate initials ("1:13-CV-1483 AWI SAB") never matched
   "1:13-cv-01483". Changed to strip all trailing judge tokens. This both
   restores the Elkins display-name fixture and is a real normalizer
   improvement.

**Results (live):** false negatives **14/14 held**. False positives stay at
**3**, but the *failure mode converged*: Lever 2 eliminated every
party-mismatch / surname-inflation match, and the 3 remaining FPs are now a
single coherent class — name-plausible records (a real "Johnson v. Mitchell"
docket; "Thompson v. **Best** Buy", where cited "Best" substring-matches;
Lopez's real BofA docket) where only the **cited docket#/reporter cite
contradicts**. That is exactly Lever 3. Scores also dropped (Johnson
0.50→0.42, Thompson 0.625→0.425). Count unchanged but the verdict is closer to
the threshold and the remaining work is unified.

Unit coverage: `TestPartyMismatchPenalty` (5 mocked tests, TDD — penalty,
cap, cite-escape, docket-escape via the Elkins fixture, control). Full mocked
suite 268 passed. The 3 FPs are `xfail` in the corpus with Lever-3 reasons.

Tests: `tests/test_verifier.py::TestPartyMismatchPenalty`. Code:
`verifier.py::_score_match` (party penalty + no-corroboration cap) and
`_normalize_docket_number`.

**Next: Lever 3** (docket#/reporter-cite contradiction penalty) — now the
sole remaining false-positive class: Lopez (0.85), Johnson (0.42),
Thompson (0.425).
