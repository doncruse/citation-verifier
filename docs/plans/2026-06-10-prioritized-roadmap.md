# Prioritized Roadmap — June 2026

**Date:** 2026-06-10
**Purpose:** Sequencing document across the three workstreams (core verifier accuracy, /verify-brief product, FLP contributions). This does NOT replace the backlogs — `scratch/TODO.md`, `scratch/ROADMAP.md`, and `scratch/QC_TRIAGE.md` remain the source of truth for individual items. This doc decides what order to pull from them.

**Context:** v0.3 refactor (phases 1–5) merged 2026-05-24. The schema, status taxonomy (incl. `WRONG_CASE`, `VERIFICATION_INCOMPLETE`, `INSUFFICIENT_DATA`), warnings system, and the 52-fixture `tests/data/refactor_corpus.json` acceptance corpus are all in place. The dominant remaining product risk is **false positives**: QC_TRIAGE has ~10 confirmed hallucinations scoring 0.4–0.7 (POSSIBLE_MATCH) and wrong-document matches at 0.85–0.9, all field-found in Feb 2026. For a hallucination-catching tool, a hallucination scored "possible match" is the worst failure mode.

## Already addressed (verified 2026-06-10)

Items that recent commits resolved — checked against the working tree before writing this plan:

- ✅ `verify_batch()` hit-finalize kwargs bug + injectable `client=` (e391209, 2026-06-02). TODO/manifest "Phase 6+ open questions" #1 and #5 are done. *Remaining follow-up: point the web app's `/api/verify` and `/api/qc/run-batch` back at `verify_batch()` to restore batched citation lookup.*
- ✅ `INSUFFICIENT_DATA` weak-parse short-circuit (f7c9203) — TODO Priority 1 "skip verification entirely" item.
- ✅ "Motion for ... Opinion" VIA_RECAP false-positive gate (3975905) — TODO Priority 1 Phase 3 Task 4 item.
- ✅ Slip-opinion placeholder stripping (`_SLIP_OPINION_JUNK`) landed earlier — Johnson v. Dunn may now resolve; needs a rerun to confirm.

**Unknown:** how many of the Feb 2026 QC_TRIAGE false positives are already fixed by v0.3 scoring/classification changes. Tier 1 Step 1 answers this empirically before any tuning.

## Tier 1 — Make the verdict trustworthy

The core mission. Everything here compounds; do in order.

1. **Expand the fake-citation regression corpus, then measure.** Convert the QC-confirmed hallucinations and wrong-document matches from `scratch/QC_TRIAGE.md` into `tests/data/known_fake_citations.json` entries (8 → ~25) with categories per `tests/data/README.md`. Add a parametrized live-API test (`test_false_positives.py`, marked like `test_false_negatives.py`) asserting each scores below threshold / returns NOT_FOUND. **Run it before tuning anything** — it tells us which QC items v0.3 already fixed and which still fail.
2. **False-positive scoring fixes**, driven by whatever Step 1 shows still failing. Known candidates from TODO Priority 1:
   - Hard date-mismatch gate (In re Hudson: 1812 vs 2018 scored 0.50)
   - Defendant-mismatch penalty (Thompson v. Best → Thompson v. Thompson, 0.62)
   - Docket-number-mismatch penalty (Lopez 0.65, Johnson v. Mitchell 0.58)
   - While in `_score_match()` (currently 935 lines, `verifier.py:2148–3082`): opportunistically extract the per-factor scoring into testable helpers. Not a standalone refactor — only as needed for these fixes.
3. **"Check Cite" status** (TODO Priority 1 "Citation mismatch detection"). Case found by name via opinion search but cited volume/page doesn't match any of the case's citations → currently shows VERIFIED. This is the exact signature of `wrong_page_number` / hybrid hallucinations (Butler Motors, Gallagher v. Wilton). Likely a new warning category + status or `VERIFIED_PARTIAL` reuse — design against the v0.3 taxonomy, don't bolt on.
4. **State-court leaks:**
   - RECAP leak despite `is_federal_court()` gate (Oddi-Sampson `ind`, Reinlasoder `mont`, Keaau P.3d) — TODO says gate should work; needs a debugging session, possibly one shared root cause.
   - Cross-state opinion match (Graves v. State, Ind. cite matched other state's Graves v. State at 0.70) — state mismatch should disqualify.
5. **Web app back onto `verify_batch()`** — the bug it was working around is fixed (e391209); restore the batched-lookup API savings in `/api/verify` and `/api/qc/run-batch`.

## Tier 2 — Cheap wins on existing investments (slot in anytime)

6. **Post the ready FLP drafts** (`scratch/drafts/`): cl-6963 comment is marked "post when ready"; contribution #1 (abbreviation synonyms) needs only its submission checklist. 5 of 11 contributions are submitted; keep momentum. (FLP's docket-entry classifier #6689 is also the long-term fix for our bankruptcy problem — keep monitoring.)
7. **Ship the Haiku prescreen** for /verify-brief assessment — marked "ready to ship" in ROADMAP with test data (76% exact, 3% one-step false upgrades, ~15x cheaper). Sitting since March.
8. **QC opinion-text fallback chain** (`web/app.py` `/api/qc/opinion-text`): replace inline regex with `client.get_opinion_text_with_metadata()` / the canonical `_extract_opinion_text` chain. Known bug (Phase 5 retro open question #2); state opinions render blank in the QC peek panel today.
9. **Minimal CI**: GitHub Actions running the mocked suite (`pytest tests/test_verifier.py tests/test_async_verifier.py ...` — everything not live_api) + `ruff check`. No mypy yet. Multi-machine workflow makes this high-value insurance. Include the dev-tooling cleanup only if trivial (move `ab_test_runner.py`, `build_review_page.py`, `extract_citations_batch.py` out of `tests/` into `tools/`).
10. **Small cleanups** (batch into any PR touching the area): `_STATUS_DISPLAY` dead dict (`web/app.py`), `__import__('datetime')` at `web/app.py:1068`, convert the 3 permanently-skipped tests in `test_cl_api_issues.py` to `xfail` so upstream fixes become visible.

## Tier 3 — One deliberate architecture decision

11. **verify-brief pipeline → scripts** (`claude -p` headless, per TODO "Pipeline architecture"). The biggest fork in the road: reproducible, resumable, A/B-testable runs. The A/B infrastructure (`tests/ab_test_runner.py`, 61 ground-truth cases) is already built. Write the design doc first; fold in the open /verify-brief items so they're decided once, not piecemeal:
    - Proposition scoping (argument vs. citation scope — TODO option a/b/c)
    - Fabricated-quote check as separate assessment criterion
    - TOA-vs-body cross-check (Layer 1, deterministic)
    - Assessment-to-CSV workflow (`--update-assessments` CLI)
    - Subagent batching limits + external-tool prohibition
12. **Semantic search fallback (Citegeist)** for stubborn NOT_FOUNDs (Cohen, Hayes, Rocha, Terwillinger). Do after Tier 1 — better scoring changes which cases still need it. First rerun the `investigate` items; some may already pass.

## Tier 4 — Explicitly parked

- Bankruptcy docket ranking (wait on FLP #6689 classifier; revisit if it stalls)
- `candidates: list[CandidateMatch]` schema addition (per Phase 4 disposition: wait for grounded callers — MCP server / diagnostic runner)
- Client-side BYOK hybrid architecture (ROADMAP) — do the quick wins (sessionStorage, CSP) if touching the frontend
- eyecite upstream PR — current "hold until we've used the fork more" stance stands, but **plaintiff truncation is the dominant false-negative pattern**; promote to Tier 2 once Tier 1 lands
- Statute/rule verification (scope expansion)
- Packaging for third-party tools
- Playwright browser tests for the web frontend

## Status log

- **2026-06-10:** Plan written. Started Tier 1 Step 1 (fake-citation corpus expansion). Live-API runs must happen on a machine with `COURTLISTENER_API_TOKEN` (remote dev container has no token).
- **2026-06-10 (later):** Tier 1 Step 1 corpus work done: `known_fake_citations.json` 8 → 19 entries (QC_TRIAGE promotions), new `tests/test_false_positives.py` (live tests + schema tests). **Measurement run pending:** `pytest tests/test_false_positives.py -m live_api -v` on a token-equipped machine tells us which v0.2 false positives v0.3 already fixed → that decides Step 2 scope. Side fixes while in there: `test_web_app.py` QC run-batch test no longer writes stub NOT_FOUNDs into the real master CSV (tmp-copy isolation — the Phase 5 retro "CSV side-effect"); `test_false_negatives.py` and the two API-hitting classes in `test_cl_api_issues.py` now carry the `live_api` mark, so a tokenless `pytest` run is green (413 passed / 0 failed). Also verified tokenless/403 behavior is already correct: stages error → `VERIFICATION_INCOMPLETE`, not bogus `NOT_FOUND`.
- **2026-06-10 (Lever 3 landed — Tier 1 Step 2 DONE):** Inspecting the 3 residual FPs showed they weren't one class. (1) **Contradiction cap**: extended the Lever 2 no-corroboration cap so the strong-negative trigger is `party_mismatch OR docket_contradicted OR cite_contradicted` (cited value present on both sides but differing — gated present-and-differing, never absent; escape on a positive docket/cite match). (2) **Bare-docket parser fix** (`_BARE_DOCKET_PATTERN`): extract `2:20-cv-1882`-style numbers without a `No.` prefix, so Johnson's cited docket# is available to contradict. **Live: FP 3 → 1, FN 14/14 held.** Lopez (docket# 14-cv vs 10-cv) and Johnson (20-cv vs 02-cv) now NOT_FOUND. The lone remaining FP, **Thompson v. Best**, is a **state-court RECAP leak** (cited `indctapp`, RECAP shouldn't run) — handed to Step 4, no scoring lever can reach it. `TestContradictionCap` (3) + `test_parser_bare_docket.py` (3); full mocked suite 283 passed. **Net Step 2: FP 11→1, FN held 14/14.** Next: **Step 4** (state-court leaks), with Thompson now the motivating case alongside Oddi-Sampson/Reinlasoder/Keaau/Graves.
- **2026-06-09 (Lever 2 landed):** Symmetric party-mismatch handling in `_score_match` (TDD). Three parts, each surfaced by live evidence: (1) name-similarity penalty (`_PARTY_MISMATCH_NAME_FACTOR=0.25`) via the existing `_party_overlap_ok` — kills the opinion-search FPs (Johnson→Scudder, Thompson→Thompson-v-Thompson); (2) a no-corroboration **cap** — penalty alone was insufficient because these fakes name a plausible court+year, so a different wrong case scores ~0.40 on court+date alone (Johnson→Laile v. Mitchell 0.43); cap below threshold when party overlap fails AND neither cite nor docket# corroborates, with cite/docket match as the escape hatch for cl_display_name_data_bug cases; (3) `_normalize_docket_number` fix to strip paired District+Magistrate judge initials ("1:13-CV-1483 AWI SAB"). **Live: FN 14/14 held; FP stays 3 but the failure mode converged** — all party-mismatch matches eliminated, the 3 residual FPs are now a single class (name-plausible record, contradicting docket#/cite) = exactly Lever 3 (Lopez 0.85, Johnson 0.42, Thompson 0.425). 5 mocked tests in `TestPartyMismatchPenalty`; full mocked suite 268 passed; 3 corpus entries xfail with Lever-3 reasons. **Next: Lever 3** (docket#/reporter-cite contradiction penalty) — the sole remaining FP class.
- **2026-06-09 (Lever 1 landed):** RECAP hard-gate parity implemented (TDD). New `_recap_result_gated()` wired into both sync + async RECAP processing: name-token gate + **one-sided** temporal gate (reject cite-before-filing only) + a `_RECAP_PACER_ERA_FLOOR = 1990` (added when In re Hudson turned out to resolve to a null-`dateFiled` appellate docket the date-diff can't evaluate; RECAP=PACER data doesn't predate ~1990). Live results: **FP 11 → 3, FN 14/14 held.** The 3 remaining FPs are the Lever 2/3 cases (Johnson, Thompson → Lever 2; Lopez → Lever 3), now `xfail` in the corpus so they xpass-alert when fixed. 5 mocked tests in `TestRecapHardGates`; full mocked suite 263 passed. Details in the measurement retro. **Next: Lever 2.**
- **2026-06-09 (FN corpus widened, pre-Lever-1):** Before touching scoring, widened the false-negative guardrail `known_real_citations.json` **5 → 14** (sourced from QC-approved CSV rows + the spun-off `case-law-proposition-benchmark` gold_db, each re-verified live under v0.3). New coverage: 4 state-court reals (Mass N.E.2d, Mont. P.3d, D.C. A.2d, + generic-gov defendant), old SCOTUS (1833), common-prefix plaintiff, and **both RECAP sub-paths**. The critical add is `recap_long_running_date_gap` = **Oracle v. Google, 2016 WL 3181206** (docket filed 2010, cited 2016, VIA_RECAP) — the guard that fails any symmetric ±5yr RECAP temporal gate. Added `expected_docket_id` support to `test_false_negatives.py` so RECAP entries pin the docket, not just "not NOT_FOUND." All 16 live tests green (7m15s). This closes the "5-case corpus too thin" gap flagged in the measurement retro; Lever 1 now has a real two-direction harness.
- **2026-06-10 (measurement done):** Ran both live suites. **False positives: 8/19 fixed, 11/19 still verify. False negatives: 5/5 real cites still VERIFIED (no regression).** Full triage: `docs/retrospectives/2026-06-10-tier1-step1-measurement.md`; raw dump `scratch/fp_triage_result.json`. v0.3's big win is the `WRONG_CASE` status (5 of the 8 fixes are `wrong_name_real_citation` now correctly resolving-but-mismatched). **Key finding that reshapes Step 2:** 9 of 11 remaining FPs are `VERIFIED_DOCKET_ONLY` from the RECAP path — and the RECAP path (`_process_recap_results` sync + async) lacks the temporal + name-token **hard-gates** the opinion-search path already has. Reordered Step 2: **(1)** port those two gates to the RECAP path — reuses tested code, kills 7 zero-overlap matches + In re Hudson's 1812-vs-2018 (the "hard date gate," which belongs at the candidate level reading docket `dateFiled`, NOT inside `_score_match` where the docket-only path feeds it an empty date); **(2)** symmetric both-sides party-mismatch penalty in `_score_match` (Johnson→Scudder, Thompson→Thompson — 2 opinion-search FPs); **(3)** docket#/WL *contradiction* penalty for Lopez (the lone 0.85 FP) — do last, guard the false-negative corpus. One regression flagged: South Pointe Wholesale was NOT_FOUND in v0.2, now a RECAP FP — Lever 1 fixes it. Re-run both suites after each lever.
