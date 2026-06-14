# Shakedown retro: first cold end-to-end run — Kettering MTD

**Date:** 2026-06-13
**Run:** `/proposition-verifier` driven **cold** (fresh session, SKILL only,
no handoff) on the real Kettering Adventist Healthcare v. Collier 12(b)(6)
motion. Output: `matters/kettering-mtd/`. Branch `pipeline-redesign` @ 2764655.
**Grading:** done in the build session against
`scratch/kettering_shakedown_rubric.md`.
**Comparison target:** the old `/verify-brief` run in
`briefs/kettering-v-collier/` (+ its 2026-03-02 retro).

## Verdict: PASS on integration; ONE must-fix before merge.

The whole point of going cold was to find whether the redesign *actually
works end to end for a naive user* and to let rough edges surface as
failures. It did both.

## What worked (the validation we needed)

The full chain ran cold, start to finish, with no crashes and no manual
repair (`run.json`):

| verb | result |
|---|---|
| **extract** (LLM, **first ever live run**) | 36 proposition-claims, 20 body citations, 0 TOA |
| verify | 40 unique citations, 4 wave-1 misses → wave 2 |
| merge | 36 matched, 32 opinions linked |
| check-quotes / crosscheck / triage | 36 / 36 / (12 full · 20 fast · 4 skip) |
| **assess** (jobs-mode dispatch) | 32 done, 0 pending |
| apply-assessments | 32 applied, 0 invalid, 0 missing |
| report | 20 findings · 14 verified · 2 unable |

Two things that had **never** executed integrated both worked on the first
real try:
1. **The `extract` verb live** — and it recovered **20 body citations,
   exactly matching the old run's 20** (into 36 proposition-claim pairs,
   since one case cited for several propositions splits into rows). TOA=0
   is plausibly correct: an 11-page 12(b)(6) motion typically has no formal
   Table of Authorities. The citation set is topically coherent (Twombly /
   Iqbal pleading, Ohio civil-procedure cases, plus extortion/abuse-of-
   process authorities — Flatley v. Mauro, U.S. v. Jackson — consistent
   with claims against the attorney-defendant).
2. **The jobs-mode pend → dispatch → ingest arc, twice** (extract, then
   per-opinion assess). The cold session dispatched subagents, they
   appended verdict lines, the rerun ingested them: 32/32 clean, apply
   invalid=0. The transport-neutral executor contract held in the real
   interactive setting it was designed for.

This is the end-to-end validation the redesign never had. The machinery is
sound.

## MUST-FIX (the headline finding) — naive path silently ships assess-v1

`claims.csv`: **`support` filled 0/36; `assessed_by` = claude-opus-4-8/
assess-v1.** The cold session followed the SKILL, which says run
`full --document <path>` with no `--prompt-version` — so it got the
**v1 single-color** prompt, NOT the assess-v2 two-axis + report-block
output that all of Step 8 built. A real user would never know they missed
v2: the report renders (lanes via `report_lane`'s v1 path), it just has
the thinner v1 cards (rationale only — no `opinion_block`/`brief_block`,
no `support` axis).

This is exactly the gap the rubric predicted and the cold run was meant to
expose. **It gates the merge to main.** Fix options:
- **(a, recommended)** make the propositions CLI default `--prompt-version`
  to **assess-v2** (the product default), while leaving the library
  constant `DEFAULT_PROMPT_VERSION = "assess-v1"` untouched so the frozen-
  cassette regression tests (which pin v1 as the default replay version)
  stay green. Small, localized to `__main__`.
- **(b)** also/instead have the SKILL pass `--prompt-version assess-v2`.
- Either way: the SKILL should not be able to silently produce degraded
  output. Recommend (a) as the real fix, (b) as belt-and-suspenders.

**Consequence for everything downstream:** the `matters/kettering-mtd/`
report is a **v1** report — NOT representative of v2 card quality. Re-run
with v2 after the fix before judging report content or feeding the
report-layout-v2 discussion. (Assessment distribution under v1: 14 Green /
7 Yellow / 11 Red / 4 unassessed. The 11 Red is high; v1's blunter prompt
over-Reds vs v2's partial-vs-unsupported nuance — another reason the v2
re-run matters before reading too much into the colors.)

## Minor findings (not merge-blockers)

1. **Pincite false-positive class (2 flags, both Royal Truck v. Kraft).**
   Cite pinpoint **758** (an *F.3d* page); the matched opinion has only 3
   star markers `[3,4,7]` that are not F.3d pages. The check compared a
   pinpoint from one reporter against star markers from another and fired
   at the `>=3 markers` threshold. Same family as the footnotemark fix
   (the star-pagination check trusts markers it shouldn't). Flag-only, no
   color impact. **Tightening to consider:** require the cited reporter to
   match the star-pagination reporter, or require markers to bracket a
   plausible range near the pinpoint, or raise the marker threshold. Low
   priority — logged to TODO.
2. **2 WRONG_CASE (State v. Carter, State v. Milam), 2 NOT_FOUND (In re
   Protech Indus., 51 F.4th 714, 6th Cir. 2022).** These are the existing
   *verifier's* behavior, not new-pipeline bugs. Protech NOT_FOUND on a
   recent federal case fits the known parallel-cite/coverage gap (TODO
   Priority 2). Worth a human glance, not a blocker.
3. **Extract may be MORE accurate than the old stub-based list.** The new
   extract read the *real* document and produced "Surace v. Wuliger";
   the old citation list (built from a paste, never saved) had "Surace v.
   Willer." Can't confirm which is correct without re-reading the brief,
   but it's a sign the real-document path is working as intended, not a
   regression.

## Ship-readiness call

Integration is **validated** — the redesign does what it was built to do on
a real brief, cold. **One gate before merging `pipeline-redesign` to main:**
fix the assess-v2-default gap (option a), then re-run kettering with v2 to
confirm the richer cards render. After that, the merge is justified.

## Follow-ups → TODO

- [merge gate] ✅ **FIXED 2026-06-13** — the propositions CLI now defaults
  `--prompt-version` to assess-v2 (`__main__`: `args.prompt_version or
  pp.ASSESS_V2_PROMPT_VERSION`); library `DEFAULT_PROMPT_VERSION` stays
  v1 for the frozen-cassette tests. SKILL left unchanged (the CLI default
  carries it — config stays out of the thin SKILL). Tests:
  `test_assess_defaults_to_v2_prompt` / `_apply_` / `_explicit_v1_still_
  overrides`. 815 offline. v2 re-run of kettering pending below.
- [minor] Pincite check: cross-reporter / too-few-marker false positives
  (Royal Truck class) — tighten or document.
- [watch] Protech Indus. NOT_FOUND (recent-federal coverage gap).
- The `matters/kettering-mtd/` artifact is committed as the v1 baseline of
  this shakedown; the v2 re-run will sit beside it for comparison.

## RESUME POINTS (token pause 2026-06-13) — in-flight work, pick up here

1. **Kettering v2 re-run — DONE (30/32), validated.** v2 cards are rich
   (`support` 15 supported/8 partial/7 unsupported; `opinion_block` 22/36;
   `brief_block` 30/36; assessed_by opus/assess-v2). Distribution softened
   v1→v2: 11 Red→**9 Red**, 7→8 Yellow, 14→**15 Green** (partial-vs-
   unsupported nuance). Sample: Wilson v. Collins → "Case on unrelated
   subject", support=unsupported, opinion_block correctly empty, analysis
   leads with subject-matter framing — textbook v2. v1 preserved as
   `report-v1.html`/`claims-v1.csv` beside the v2 `report.html`/`claims.csv`.
   **2 opinions** hit the transient SDK error and stayed on v1 (the
   hardened path recorded + continued); optional cleanup = rerun
   `assess --executor sdk` (picks up the 2), then apply + report. The
   merge gate is fully cleared: CLI defaults to v2 AND a real run produces
   the rich cards.
   (Original resume note, if ever needed again:)
   ```
   venv/Scripts/python.exe -m citation_verifier verify-propositions matters/kettering-mtd assess --executor sdk   # resumes any not-yet-done opinions
   venv/Scripts/python.exe -m citation_verifier verify-propositions matters/kettering-mtd apply-assessments      # v2 default now
   venv/Scripts/python.exe -m citation_verifier verify-propositions matters/kettering-mtd report
   ```
   Then diff `report-v1.html` vs `report.html`: v2 cards should carry
   `support`, `badge_label`, and orange/green `brief_block`/`opinion_block`
   boxes the v1 cards lacked; expect the 11 v1 Reds to soften (v2
   partial-vs-unsupported nuance). Commit `matters/kettering-mtd/`.

2. **sonnet-v2 A/B (user-approved, NOT yet run).** Config `sonnet-v2`
   added to `tests/ab_test_configs.json`. Run it live (1 arm), then
   compare against the already-saved opus-v2 baseline:
   ```
   venv/Scripts/python.exe tools/ab_test_runner.py --config sonnet-v2 --corpus withers payne wainwright
   venv/Scripts/python.exe tools/ab_test_runner.py --compare \
     scratch/ab_runs/ab_opus-v2-nohints-baseline_20260612-235338.jsonl \
     tests/data/results/ab_sonnet-v2_<TIMESTAMP>.jsonl
   ```
   Decide whether Sonnet's cost saving justifies any accuracy delta;
   record in this retro + CLAUDE.md. (Prior: old v1 sonnet 53/61 vs opus
   54/61 — near-tie. v2 packs multiple claims per opinion, so watch
   whether Sonnet holds up on packed jobs.)

### sonnet-v2 model A/B — RESULT: Sonnet over-flags badly; stay on Opus

Ran `sonnet-v2` live (2026-06-13). **withers scored cleanly; payne/wainwright
did NOT** — the run hit transient SDK failures (6 payne jobs) leaving claims
without verdicts, and `score_workdir`'s RecordedExecutor raised
`RecordedVerdictMiss` on the first gap, crashing the harness before payne
scored. **Harness robustness bug** (logged to TODO): live A/B scoring must
tolerate missing verdicts (re-run to fill, or score only completed claims +
report the drop) instead of crashing on a gap.

withers comparison (the decisive signal — opus-v2 vs sonnet-v2):

| | yellows caught | yellows exact | greens over-flagged | reds |
|---|---|---|---|---|
| **opus-v2** | 16/19 | 11 | **4/12** | 3/3 |
| **sonnet-v2** | 16/19 | 9 | **9/12** | 3/3 |

Same yellow recall, but Sonnet achieves it by **over-flagging 9 of 12 true
greens** (vs Opus's 4) — withers-01/-26 went all the way to **Red**. Sonnet
is indiscriminately stricter: good recall, terrible precision. On a real
brief that's a flood of false concerns. The old v1 near-tie (sonnet 53/61
~ opus 54/61) does **NOT** carry to v2 — plausibly because v2 packs multiple
claims per opinion (harder context-tracking) and the two-axis support call
makes Sonnet default to partial/unsupported too readily.

**But assess-v1 with Sonnet IS viable** — the follow-up the user asked for
(2026-06-13). What broke Sonnet was v2's *structure* (packed multi-claim +
two-axis support derivation), not the judgment. On the simpler v1 single-
claim/single-color prompt Sonnet holds up:

| config | withers yellows | withers green over-flags | A/B internal | lenient errors |
|---|---|---|---|---|
| opus-v1 | 14/19 | 2/12 | 56/61 | 2 |
| **opus-v2** (default) | 16/19 | 4/12 | 55/61 | 1 |
| **sonnet-v1** | 16/19 | 5/12 | **55/61** | **0** |
| sonnet-v2 | 16/19 | 9/12 | (crashed) | — |

sonnet-v1 **matches opus-v2 on A/B accuracy (55/61)** and yellow recall
(16/19), reds 3/3, and has **zero lenient-direction errors** — every miss
is strict (green→yellow, yellow→red), the *safe* direction for a citation
checker. Its only weakness is 5/12 green over-flags (vs Opus 2-4), and 4 of
those are the same hedged-green cluster (-01/-20/-26/-30) the user already
adjudicated as defensible. So Sonnet-v1 trades a little green precision on
borderline cases for several-fold lower cost, with accuracy intact.

**What v2 actually bought** (the user's other question): re-scored Opus
v1→v2 is a near-wash on accuracy (yellows 14→16 but green over-flags 2→4,
A/B 56→55). v2's real value is the **report presentation** — the rich
`brief_block`/`opinion_block`/`finding_analysis` cards. v1 gives only a
color + one sentence.

### Model/cost decision menu (cost from 2026-06-13 measurement)

| option | quality | ~cost/run | note |
|---|---|---|---|
| Opus-v2 interactive (current) | best (rich cards) | ~$13 | premium |
| **Opus-v2 + Batches API** | **best, unchanged** | **~$6.50** | 50% off, just async — the clean win, zero quality loss; already Priority-0 |
| Sonnet-v1 | matching accuracy, **thin cards** | low single-$ | budget; safe-direction errors only |
| Hybrid: Sonnet-v1 bulk + Opus-v2 cards on findings | accuracy everywhere, rich cards where it matters | middle | best-of-both, more engineering (two-pass) |

**Recommendation:** the first lever is **Batches on Opus-v2** — halves cost
with no quality or accuracy loss (and it's the deadline work anyway).
Sonnet-v1 is now *proven* as a further cut if cost must go lower and thin
cards are acceptable; the hybrid is the eventual best-of-both. Model default
stays **Opus**; Sonnet-v1 is a documented, validated fallback. (Earlier note
about cheap-model-on-fast-track still applies as the hybrid's mechanism.)

3. **Then:** merge `pipeline-redesign` → main (decide squash vs merge-
   commit). Optional cleanup logged to TODO: resume `--force` guards on
   merge/check-quotes/crosscheck/triage to quiet the re-running middle
   verbs on `full` resumes (cosmetic).
