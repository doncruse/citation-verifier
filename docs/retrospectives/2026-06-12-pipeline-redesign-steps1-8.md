# Retrospective: proposition-verifier pipeline redesign, Steps 1-8

**Dates:** 2026-06-11 → 2026-06-12 (branch `pipeline-redesign`)
**Design:** `docs/plans/2026-06-11-proposition-verifier-pipeline-design.md` (Tier 3 #11, folding in Tier 2 #7)
**Step plans:** `docs/plans/2026-06-11-prop-pipeline-step{1..8}-*.md` (each carries its own execution notes)

## What the redesign set out to fix (design §1)

`/verify-brief` worked but was ~400 lines of SKILL prose orchestrating CLI
steps, subagents, and session judgment: nondeterministic extraction,
assessment results re-entering claims.csv through throwaway scripts,
non-resumable runs, nothing A/B-testable, every run babysat live. The tool
was also misnamed — its true input is (citation, proposition) pairs.

## What landed, step by step

1. **Offline harness** — executor protocol (`Job`/`Verdict`/JSONL serde),
   `RecordedExecutor` replay, three frozen corpora (withers/payne/wainwright)
   with ground truth + cassettes, two-axis `derive_color`, offline scoring
   reproducing both committed baselines (Withers 12/19; A/B 56/61 — the plan's
   54/61 corrected against the authoritative ledger).
2. **Pipeline skeleton** — `proposition_pipeline.py` with `verify`/`merge`
   verbs, the `matched_name` batch-path bug fixed at the source
   (`VerificationResult.matched_case_name` accessor), slug-token opinion
   linkage, `brief_pipeline` kept as a `sys.modules` alias.
3. **Quote floors** — ≥2-word span extraction + the **banded** `quote_floor`
   (FABRICATED always; CLOSE only <0.75; [0.75, 0.85) is transcription
   noise). Withers 12/19 → 14/19 with zero new green over-flags. The
   unbanded floor breached the green guardrail in testing — the band was
   the fix, and it mattered again at Step 8 (below).
4. **assess / apply-assessments** — versioned `assess_v1.md` (byte-pinned to
   the cassettes), `AgentToolExecutor` jobs mode, floor-enforced apply.
5. **AgentSDKExecutor + extract** — headless SDK transport (env strip, full
   drain, auth stop), live smoke green with cross-transport agreement;
   `extract` verb + `extract_v1.md`.
6. **crosscheck + triage** — matched-court persistence (client → download
   stash → accessors → vr CSV), TOA/body diff, court check, best-effort
   pincite flags (flags only, never colors); deterministic `triage_track`
   + prescreen wiring (default OFF).
7. **Report lanes + SKILL stub + A/B re-point** — `report_lane()` resolving
   the v1-schema tension (CITE_UNCONFIRMED = amber Check Cite, never Red;
   Gray = full unlocatable set; floor-enforced `assessment` authoritative),
   §6.5 flag chips on cards including greens, `run_report` closing the
   `full` chain; thin `/proposition-verifier` SKILL (~40 lines, zero
   criteria); harness moved to `tools/` on the executor + frozen-workdir
   contract.
8. **assess-v2 + acceptance** — this retro's subject; details below.

## Step 8: assess-v2 and the acceptance runs

**User-ruled decisions (2026-06-12):** two-axis + report-block verdict
schema; per-opinion packing only (documented deviation from §6.8's
multi-opinion caps); Haiku fast-track routing deferred past acceptance;
full live scope (re-record + acceptance + prescreen A/B).

**What v2 is:** one packed job per opinion; claim blocks carry `cited_for`
(judge-this instruction, §6.3), brief sentence, quoted strings,
matched-passage hints ≥0.65 sim, and `prescreen_hint` (§6.7); the agent
returns a per-claim `verdicts` array with `support` + four report-block
fields and never outputs a color — `apply-assessments` derives it via
`derive_color(cl_status, support, floor-effective quote axis)`.

**Re-record:** 90 verdicts (29+27+34), all-Opus, appended to the same
cassette files (one file, two versions, keyed by claim_id +
prompt_version). The v1 baselines remain replayable and pinned.

### §8 acceptance scorecard (assess-v2, offline replay of the re-record)

| target | result | verdict |
|---|---|---|
| Withers yellows ≥15/19 | **16/19** (11 exact; v1: 14/19, 8 exact) | PASS |
| Withers reds 3/3 | **3/3** | PASS |
| Withers green over-flags ≤2/12 | **4/12** | **MISS** |
| A/B ≥85% | **55/61 = 90%** (payne 23/27, wainwright 32/34) | PASS |
| No new lenient-direction errors | lenient set shrank to {payne-03} (payne-58 fixed) | PASS |

**The yellows story.** v2 caught withers-05, -09, -12, -38, -44 — including
**withers-12**, which Step 3 had classified as *not mechanically catchable*
(its proposition paraphrases without quotation marks). The brief-sentence +
cited_for context in the v2 claim block is what caught it. One previously
caught yellow (-33) flipped to Green; remaining misses (-32, -33, -49) are
the author-hedged judgment band.

**The green over-flag miss.** All four over-flags are agent "partial"
judgments: withers-01 and -26 were over-flagged by v1 too (v1 sat exactly
at the ≤2 allowance with these two); the two new ones are -20
(VERIFIED_PARTIAL name_unverified, "See, e.g." cite) and -30
(cite_not_on_record WL-gap green) — both author-hedged/edge greens. The
pattern: v2's stricter partial-vs-unsupported guidance buys +2 yellows
caught at the cost of +2 stricter calls on hedged greens. All four errors
are in the strict direction (the safe direction for a citation checker).
Per the step plan's stop rule, no prompt tuning was done; disposition is
the user's call (accept the tradeoff and amend the §8 guardrail, or queue
a v3 calibration item).

### Live findings fixed during the runs (each with a pinned test)

1. **SDK plain-Exception crash** — the SDK's message stream can raise a
   plain `Exception` ("Claude Code returned an error result: ...") on
   transient API blips, bypassing the `ClaudeSDKError` handler and killing
   a 90-job batch on job 1. `AgentSDKExecutor` now records any non-auth
   exception as a per-job failure and continues; the resume key re-runs
   stragglers (it did: 3 wainwright jobs failed transiently, the batch
   completed, one rerun finished them).
2. **The Withers pincite flag (9.6) was a false positive** — Missouri v.
   Jenkins n.10 exists, but CL marks it `<footnotemark>10</footnotemark>`
   and the tag-strip made it invisible to the footnote-existence check.
   `_read_clean_opinion` now rewrites footnotemarks to `n.N` before
   stripping; Withers crosscheck shows 0 pincite flags.
3. **derive_color double-floored the §6.4 noise band** — supported+CLOSE
   in [0.75, 0.85) (quote_floor deliberately unset) was yellowed by the
   raw quote axis, re-flagging withers-21 (the exact green the Step 3 band
   was calibrated to protect). The quote axis passed to `derive_color` is
   now the floor-effective verdict.

### Prescreen ON/OFF A/B (§6.7 default decision)

(filled when the opus-v2-hints arm completes)

## Open items (not blocking; tracked)

- **Green over-flag guardrail disposition** — user decision (above).
- **Haiku fast-track routing** (`assess` honoring `triage_track`) — user-
  deferred past acceptance; A/B against the v2 baseline as a cost play.
- **claims.csv consumer contract + export option** — scratch/TODO.md
  Priority 2 (custom reports from pipeline outputs without the report verb).
- **report row-4 switch to derive_color** — now possible since v2 fills
  `support`; report_lane documents the hand-off.
- **Web app onto verify_batch()** (§6.10) — out of scope, separate PR.
- Corpus candidates: kettering, brooks, maxwell (§7).
- Check-cite live acceptance pass (`-m live_api` + fake/real re-record on
  this token machine) — pre-dates this redesign, still owed (design §11).

## Process notes

- Measure-first paid off twice: the Withers measurement defined the targets,
  and the frozen-corpus replay made every step's effect visible offline in
  seconds (812 tests, no network).
- The cassette policy worked exactly as designed at the re-record: v1 stayed
  byte-pinned and replayable; v2 appended alongside it; structural tests
  enforce dual coverage.
- TDD caught real bugs at every step (the step plans' execution notes log
  them); the three live findings above each landed with a regression test
  the same hour they were found.
- All four §8-relevant design decisions that arose mid-stream went to the
  user before code (the Step 8 decision log) — same pattern as the design's
  §13 sign-off table.
