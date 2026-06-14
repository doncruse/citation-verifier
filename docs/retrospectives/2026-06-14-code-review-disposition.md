# Code-review disposition — PR #21 (proposition-verifier pipeline redesign)

**Date:** 2026-06-14
**Source:** independent code review (manual, separate session) of PR #21
(`pipeline-redesign` → `main`).
**Processed via** `superpowers:receiving-code-review` — each finding verified
against the code before acting; external findings treated skeptically.

| # | severity | finding | disposition |
|---|---|---|---|
| 1 | High | merge links opinions to NOT_FOUND/unmatched claims (false link) | **FIXED** |
| 2 | Medium | merge drops downstream columns on standalone rerun | **FIXED** |
| 3 | Medium | dashboard "Claims checked" undercounts multiply-cited unable cases | **FIXED** |
| 4 | Low | run_verify can ship incomplete results then no-op on rerun | **DEFERRED** (logged) |
| 5 | Low | dead code: `_find_opinion_file` | **FIXED** (removed) |
| 6 | Note | `_parse_json_object` first-`{`/last-`}` over-capture | **DEFERRED** (logged) |

## Fixed

**#1 (High) — the real one.** `merge_claims` called `_link_opinion_file`
for every claim with no located gate. For a NOT_FOUND/unmatched citation
(empty `cl_url` + `matched_name`), linkage fell through to the bare
cited-name token source and borrowed another located case's opinion at
Jaccard ≥ 0.25 — so a hallucinated `United States v. <fake>` linked to a
real `United States v. <X>` on `{united, states}` overlap, got assessed
against the wrong opinion, and could surface as verified instead of Gray
"unable to verify." Verified the trace through `_assessable` (no located
check) and `report_lane` (gray-lanes unlocatable only when `not
opinion_file`).
- **Fix:** gate the linkage call on `(url or matched_name)` — CL's
  located signal — rather than a VERIFIED-only allowlist. This keeps
  `POSSIBLE_MATCH`/`LIKELY_REAL` (which carry a real match; confirmed
  payne-02/15/23 have `cl_url`+`retrieved_case`) and drops NOT_FOUND /
  unmatched. The reviewer's twin concern in `predict_workdir` is the
  same root: both read `opinion_file`, so fixing the link at merge fixes
  both lanes.
- **Why not gate on `scoring.LOCATED`:** that set is VERIFIED-only and
  would have wrongly stripped legitimate POSSIBLE_MATCH/LIKELY_REAL links
  (3 real rows in the payne corpus). `(url or matched_name)` is the
  correct signal.
- Tests: `TestMergeLinkageGate` (NOT_FOUND + unmatched don't borrow;
  POSSIBLE_MATCH still links). Frozen corpora safe — only the withers
  reproduction re-runs merge and it has 0 non-located-with-opinion rows;
  regression baselines score committed CSVs and don't re-run merge.

**#2 (Medium).** merge projected rows onto a fixed `output_fields` +
`_PASSTHROUGH_FIELDS` schema, silently dropping later verbs' columns
(`quote_floor`, `crosscheck_flags`, `triage_track`, `prescreen_hint`,
`support`, `assessed_by`) on a standalone rerun — violating "every verb
independently runnable; resume = rerun the verb."
- **Fix:** build each output row from `dict(claim)` (preserves all
  existing columns) and overlay the merge-derived fields; `output_fields`
  now carries through any input column not in the canonical set. This
  subsumes `_PASSTHROUGH_FIELDS` (removed as now-dead). Also fixes the
  noted inconsistency (assessment survived but support didn't).
- Test: `TestMergeColumnPreservation`.

**#3 (Medium, display).** `total_checked = len(findings)+len(verified)+
len(unable)` counted unable *cards*, not claims; a case cited N times
counted as 1, disagreeing with `run_report`'s per-row `ReportStats`.
- **Fix:** `total_checked` now adds the sum of each unable card's
  `propositions`. Test: `TestDashboardClaimCount`.

**#5 (Low).** Removed dead `_find_opinion_file` (no caller/test; superseded
by `_link_opinion_file`) and the now-dead `_PASSTHROUGH_FIELDS` constant.

## Deferred (logged to scratch/TODO.md, not fixed now)

**#4 (Low) — run_verify partial-write window.** `wave1` writes
`verification_results.csv` before `wave2`; if `wave2` raised, the file
persists wave-1-only and `run_verify` no-ops on the next non-`--force`
run. **Deferred because:** the window is narrow (`verify_batch` swallows
network errors into `VERIFICATION_INCOMPLETE` rather than raising), and a
clean fix touches the live-API verify path, which the offline suite
can't exercise — fixing it blind risks more than the narrow bug. Logged
for when the live verify path is next worked (e.g., alongside the
MessagesAPIExecutor build).

**#6 (Note) — `_parse_json_object` over-capture.** First-`{`/last-`}`
slicing fails if a model appends prose containing braces after the JSON,
dropping the verdict to a recorded failure (claim stays pending).
**Deferred because:** it fails *safe* (no wrong data — the claim just
re-runs), it's the documented PoC parse rule, and the reviewer agreed
it's acceptable. Logged to revisit when `MessagesAPIExecutor` lands (a
stricter extraction — last balanced object or fenced-block-first — fits
that work).

## Not re-litigated (already accepted; reviewer correctly skipped)

`assess_v1.md` byte-pin, CLI-v2/library-v1 default split, Withers green
over-flags (4/12, user-adjudicated), and the four prior follow-ups
(A/B-harness gap crash, Batches not built, report-layout v2, kettering
stragglers). The reviewer's "what looks solid" section (derive_color/
report_lane split, floor consistency, CITE_UNCONFIRMED kept out of
`_SEVERITY_RANK`, executor §5.1 handling) matches our understanding.

**Suite after fixes: 820 passed, 2 skipped (offline).**
