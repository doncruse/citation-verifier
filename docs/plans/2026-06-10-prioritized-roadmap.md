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

> **Status (2026-06-11):** Steps 1, 2, **3 (Check Cite)**, and the RECAP-leak
> half of 4 are **done** — fake corpus 0/19, published reals 203/204,
> fallback reals guarded, Charlotin fake FPs 67→33 with 34 reclassified
> "Check Cite", all replayable offline. Remaining: the cross-state
> opinion-match half of Step 4 (Graves), Step 5 (web app onto
> `verify_batch()`). See the Status log and the "Follow-ups discovered during
> execution" section below.

1. ✅ **DONE — Expand the fake-citation regression corpus, then measure.** Convert the QC-confirmed hallucinations and wrong-document matches from `scratch/QC_TRIAGE.md` into `tests/data/known_fake_citations.json` entries (8 → ~25) with categories per `tests/data/README.md`. Add a parametrized live-API test (`test_false_positives.py`, marked like `test_false_negatives.py`) asserting each scores below threshold / returns NOT_FOUND. **Run it before tuning anything** — it tells us which QC items v0.3 already fixed and which still fail.
2. ✅ **DONE — False-positive scoring fixes.** Became four levers, not the three originally guessed (the measurement reshaped the plan — the dominant fix was RECAP hard-gate *parity*, not the per-factor penalties first imagined):
   - Lever 1: port name-token + one-sided temporal hard-gates to the RECAP path + PACER-era floor (In re Hudson).
   - Lever 2: symmetric party-mismatch penalty + no-corroboration cap (Thompson→Thompson, Johnson→Scudder/Laile).
   - Lever 3: docket-number contradiction cap + bare-docket parse (Lopez, Johnson). *Reporter-cite contradiction arm was removed after the benchmark replay caught it causing the Muldrow false negative — see follow-ups.*
   - The per-factor scoring was NOT extracted into helpers (the fixes didn't require it; `_score_match` grew but stayed coherent).
3. ✅ **DONE — "Check Cite" status** (new `CITE_UNCONFIRMED`). A fallback name-search win whose cited reporter/WL location is contradicted by CL's same-reporter-family records (`cite_contradicted`) or backed by no text at all — a bare RECAP docket (`cite_not_on_record`) — demotes from VERIFIED-family to `CITE_UNCONFIRMED` (UI "Check Cite"). Post-threshold classification, no scoring changes (the Muldrow constraint). **Charlotin: found 67→33, 34 Check Cite, zero new found; benchmark 203/204 unchanged; fallback 0 reals lost + Viken FN fixed; 600 offline passed.** Design `docs/plans/2026-06-11-check-cite-design.md`; retro `docs/retrospectives/2026-06-11-check-cite-cite-unconfirmed.md`. Same change ruled on the Lever-2 FNs (Sundown/Viken — see Status log).
4. **State-court leaks:**
   - ✅ **DONE — RECAP leak** despite `is_federal_court()` gate (Oddi-Sampson `ind`, Reinlasoder `mont`, Keaau P.3d, Thompson `indctapp`). One shared root cause: the guard keyed off the federal-only `court_id` (None for state courts). Fixed via `_is_state_court_citation()` (court OR regional-reporter signal). Only Thompson was in the live corpus; the others are covered by the shared fix + a 7-case unit matrix — see follow-up "pin the other reproducers."
   - ⬜ **TODO — Cross-state opinion match** (Graves v. State, Ind. cite matched another state's Graves v. State at 0.70) — different mechanism (opinion-search state disqualification, not RECAP gating); not addressed.
5. ⬜ **TODO — Web app back onto `verify_batch()`** — the bug it was working around is fixed (e391209); restore the batched-lookup API savings in `/api/verify` and `/api/qc/run-batch`.

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

## Current automated coverage (2026-06-10)

The accuracy work is now guarded by three corpora, all replayable **offline**
in seconds via the cassette harness (`tests/cassette_client.py`):

| Corpus | What it guards | Size / result | Mode |
|---|---|---|---|
| `known_fake_citations.json` (`test_false_positives.py`) | fakes must not verify | **0/19** false positives | live (`-m live_api`) |
| `known_real_citations.json` (`test_false_negatives.py`) | curated real cites resolve; incl. RECAP/WL + date-gap guard | **14/14** | live |
| `benchmark_*` (`test_benchmark_regression.py`) | real published cases still found (citation-lookup path) | **203/204** | offline replay |
| `fallback_*` (`test_fallback_regression.py`) | real cases that resolve via opinion-search/RECAP | **32/32** guarded, 100% via fallback stages | offline replay |

Re-record the cassettes periodically (live) to catch CourtListener drift;
`--from-cassette` re-derives verdicts offline after an interpretation change.

## Follow-ups discovered during execution (not in the original plan)

These surfaced while doing Tier 1 Steps 1–4 and the test-harness work. None
block anything; roughly highest-value first.

1. **Parallel-citation robustness (S. Ct. vs U.S.).** Muldrow exposed that a
   recent SCOTUS case cited by its `S. Ct.` reporter misses citation-lookup
   (CL indexes the `U.S.` parallel cite) and only resolves because
   opinion-search clears threshold by a hair. We fixed the cap regression,
   but the underlying path is threshold-fragile. Consider parallel-reporter
   normalization or a name+court lookup for recent SCOTUS so these resolve
   robustly instead of by a 0.01 margin.
2. **Triage the 18 fallback NOT_FOUNDs** (`fallback_baseline.json`). Split
   genuine CL coverage gaps (the coverage memo already named several: Rose
   Way, Wilson, Iglesias, Terry Black's, etc.) from any real fallback
   false-negatives we should fix. The memo's Step 5 audit is a head start.
3. **Pin the other RECAP-leak reproducers as live regressions** —
   Oddi-Sampson (`ind`), Reinlasoder (`mont`), Keaau (P.3d). Fixed by the
   shared Step-4 root cause and a unit matrix, but not end-to-end in the live
   corpus. Need their citation strings (QC_TRIAGE / coverage CSV) to add them
   to `known_fake_citations.json` or a state-leak corpus.
4. **Charlotin fake-mining pipeline** — ✅ **candidate corpus built
   (2026-06-10)**; live measurement run pending. Both original blockers
   dissolved: (a) the CSV was manually downloaded to
   `scratch/Charlotin-hallucination_cases.csv`; (b) extraction did NOT need
   the linked rulings — the `Hallucination Items` field quotes fabricated
   citations verbatim. `tests/build_charlotin_corpus.py` (offline, 10 unit
   tests) mined **547 unique court-confirmed fakes** →
   `tests/data/charlotin_corpus.json` (29x the 19-entry fake corpus). Pilot
   adjudication via the CL MCP: 30/30 genuinely fake (16 not in CL, 14
   resolve to a different case — the Step 3 "Check Cite" pattern). **Next:**
   `python tests/record_benchmark_cassette.py --corpus-name charlotin` on a
   token-equipped machine; `found (resolved)` = false positives to triage.
   Details: `docs/retrospectives/2026-06-10-charlotin-fake-mining.md`.
5. **Threshold/constant calibration.** Several fixes use hand-tuned constants:
   `_VERIFIED_SCORE_THRESHOLD = 0.40`, `_PARTY_MISMATCH_NAME_FACTOR = 0.25`,
   `_RECAP_PACER_ERA_FLOOR = 1990`, the cap value (`threshold − 0.01`). Muldrow
   showed 0.01 margins decide outcomes. A larger labeled set (esp. from #4)
   could validate or tune these rather than leaving them eyeballed.
6. **Harness maintenance / extension.** (a) Periodically re-record cassettes
   for CL drift. (b) Optionally extend record/replay to the fake + curated-real
   corpora so the *entire* accuracy suite runs offline (and becomes CI-able
   without a token). (c) The `benchmark_baseline.json` predates the
   `winning_stage` field — regenerate (`--from-cassette`) for consistency if
   we want path-migration guarding there too.
7. **Bare-docket parser coverage.** `_BARE_DOCKET_PATTERN` only handles the
   federal `N:NN-cv-N` form. State/other docket formats seen in the coverage
   data (`B225051`, `2024 IL App (4th) 230931`) aren't extracted — only matters
   if a future docket-contradiction case needs them. Low priority.

## Status log

- **2026-06-11 (Tier 1 Step 3 — Check Cite / `CITE_UNCONFIRMED` — DONE):**
  New seventh status for the last big FP class: a fallback name-search win
  whose cited reporter/WL location is **contradicted** by CL's
  *same-reporter-family* records (`cite_contradicted`), or backed by **no
  text at all** — a bare RECAP docket (`cite_not_on_record`), demotes from
  VERIFIED-family to `CITE_UNCONFIRMED` (UI "Check Cite"). Post-threshold
  classification; **no scoring changes** (the Muldrow constraint). The
  same-family witness rule (N.E.2d ≡ N.E.3d; U.S. ≠ S. Ct.) is load-bearing:
  it catches the fakes (they fabricate an address in the family CL uses for
  that court) while sparing real cases CL indexes under only one parallel
  reporter (the So.3d/Ala.App. case the user raised → kept VERIFIED +
  warning, the reporter-gap compensation) and makes Muldrow fall out for
  free. RECAP VIA_RECAP gate-passers keep status + warning (Oracle/Abbott
  accepted cost); bare dockets demote. **Charlotin replay: found 67→33
  (12.7%→6.5%), 34 Check Cite, ZERO rejected→found; benchmark 203/204
  unchanged; fallback 0 reals lost; 600 offline passed.** Also ruled on the
  **Lever-2 FNs**: refine via levers (a)+(b), reject (c). (a) split into
  (a1) cite-corroboration-skips-penalty (narrowed to cite-only — docket
  numbers aren't unique) + (a2) placeholder-party waiver (narrowed to
  defendant-position only). Both narrowings were forced by the
  zero-new-found guard catching `Lee→MOTE` and `Doe v. Northrop→Barker`.
  **Viken FN fixed** (live: VERIFIED 0.58 → Viken Detection v. Bradshaw).
  **Sundown still NOT_FOUND** — lever (b) fixed the docket-junk parse bug but
  two independent out-of-scope causes remain (CL search returns 0 for the
  full punctuated query; the real cluster has empty citations + a 14-party
  caption); fixture stays red per the scope guard, logged as a follow-up.
  Design `docs/plans/2026-06-11-check-cite-design.md`; retro
  `docs/retrospectives/2026-06-11-check-cite-cite-unconfirmed.md`. **Needs
  token machine:** the full 19-min `-m live_api` acceptance pass + fake/real
  corpora live re-record to confirm no live-only drift (offline guards cover
  the regression surface meanwhile).

- **2026-06-11 (live mop-up + NY state-RECAP leak fix — FP settles at 66):**
  Token-machine recorder rerun resolved 36/40 INCOMPLETEs → found went
  59 → 69. Triage: 9 of the 10 new finds are the Step-3 class made
  *visible* by the Bug-1 parser fixes (names now parse → fallback runs →
  real same-name case matches the fake cite) — the honest Bug-1
  accounting. The 10th was a **new NY state-RECAP leak** (Kaszovitz, 202
  AD3d 421 → federal SDNY docket): the `A.D.`/`N.Y.S.`/`Misc.` reporter
  families were missing from `state_reporter_map.py`, so the Step-4
  state gate had no reporter signal. Fixed (A.D. → nyappdiv with safe
  inference; N.Y.S./Misc. multi-entry gate-only); matrix rows added;
  offline suite 531 passed. Post-fix replay: **66/511 found, zero new**.
  6 NY entries flipped INCOMPLETE (court-filtered searches not in
  cassette) — one more recorder resume run settles them.

- **2026-06-11 (Charlotin bugs 1–3 fixed + corpus hygiene — FP 122 → 59):**
  Follow-up session executed the triage plan, all offline/TDD. **(1)
  Corpus hygiene:** builder gained the retro's safe contrast markers
  (+ appear-to-match, likely-intended from the B/C sweep) and a
  per-entry `_ADJUDICATED` table; corpus 547 → **511** (35 dropped —
  15 poisoned A, 10+1 mislabels incl. Manfer found post-fix, 6 B/C-sweep
  poisonings incl. Norg/Curtis, 1 junk extraction; Holden/Bolin
  relabeled `charlotin_real_case_wrong_pincite`/`_wrong_court` as future
  targets). **(2) Bug 1:** parser now names NY v-without-period,
  truncated "of X v Y", paren-led, Marriage-of/Estate-of + Cal. "(year)
  cite", and surname-only forms (`tests/test_parser_name_forms.py`);
  nameless lookup hits return **VERIFIED_PARTIAL + new `name_unverified`
  warning** (policy at `_process_citation_lookup_hit`, shared
  sync/async/batch). **(3) Bugs 2+3:** shared `_GENERIC_NAME_TOKENS`
  guard in `_party_overlap_ok` + `_names_match_citation_lookup`;
  all-generic/short surnames escalate to caption_investigation; acronym
  bridge (FDIC ↔ Federal Deposit Insurance) added after the benchmark
  replay caught the one regression. **Replay recompute: found 122 → 59
  (57 fakes + 2 relabeled reals), zero rejected→found regressions;
  benchmark 203/204, fallback 32/32, offline suite 527 passed.** The 57
  remaining fake FPs ≈ 11% are: 54 Step-3 "Check Cite" class (next
  session's design doc) + 3 nameless-but-flagged VERIFIED_PARTIALs.
  **Needs token machine:** charlotin recorder rerun (40 INCOMPLETE: 23
  old transients + 17 CassetteMiss from new fallback calls) and one
  `-m live_api` pass to confirm no live drift. Details in the charlotin
  retro "Fix session" section.

- **2026-06-11 (Charlotin live run + triage — three verifier bugs found):**
  Live recording done (547 fakes, cassette 81MB committed f142dc9):
  **393 rejected (210 WRONG_CASE + 183 NOT_FOUND), 122 false positives.**
  Full offline triage in the charlotin retro +
  `scratch/charlotin_fp_triage.csv` +
  `scratch/charlotin_bucketA_adjudication.csv`. Findings, in priority
  order: **(1) Bug 1 — parser drops case_name** on NY/Cal/paren-led/
  surname-only forms and verifier.py:253 then skips the name check →
  blind VERIFIED@1.0 on any cluster the cite resolves to (20+ FPs, the
  single biggest mechanism; needs parser fix + a policy decision for
  nameless lookup hits). **(2) Step 3 "Check Cite" now has ~60 motivating
  cases** (bucket B 33 opinion-search + most of bucket C 34 RECAP —
  real/common name, fabricated cite). **(3) Bugs 2+3 — generic-token
  party overlap** in caption_investigation and
  `_names_match_citation_lookup` ("United States"/"State"/"St."/"Inc."
  alone establish overlap; 8 FPs; fix with a shared generic-token
  guard). **(4) Corpus hygiene:** 15 poisoned + 12 mislabeled entries to
  drop/recategorize (lists + new contrast markers in the retro); B/C not
  yet swept. All bugs reproduce offline from the cassette — fixes are
  TDD-able without a token. 24 INCOMPLETE entries: rerun the recorder
  (it resumes and retries transients).

- **2026-06-10 (Charlotin candidate corpus — follow-up #4 unblocked):** The
  manually-downloaded CSV (`scratch/Charlotin-hallucination_cases.csv`, 1,598
  rulings / 1,115 USA) turned out to quote fabricated citations **verbatim**
  in `Hallucination Items` — no linked-ruling processing needed for the first
  pass. Built `tests/build_charlotin_corpus.py` (TDD, 10 tests): eyecite
  span extraction with quote/em-dash repairs, contrast-marker flagging (49
  REAL contrast cases excluded — e.g. "identified only an unrelated Jackson
  v. Lew" — the main poisoning risk), dedup. **Output:
  `tests/data/charlotin_corpus.json`, 547 unique court-confirmed fakes**
  (29x scale-up). Pilot adjudication via CL MCP `analyze_citations`: 30/30
  genuinely fake — 16 not in CL, 14 resolve to a *different* case (≈50%
  are the wrong-case hybrids Step 3 "Check Cite" targets, so this corpus is
  Step 3's test bed). Offline suite 459 passed. **Pending (needs token):**
  `python tests/record_benchmark_cassette.py --corpus-name charlotin` —
  for a fake corpus, `found` = false positives; triage every resolved
  candidate (our FP vs. corpus mislabel) before promoting assertions.
  Retro: `docs/retrospectives/2026-06-10-charlotin-fake-mining.md`.
- **2026-06-10:** Plan written. Started Tier 1 Step 1 (fake-citation corpus expansion). Live-API runs must happen on a machine with `COURTLISTENER_API_TOKEN` (remote dev container has no token).
- **2026-06-10 (later):** Tier 1 Step 1 corpus work done: `known_fake_citations.json` 8 → 19 entries (QC_TRIAGE promotions), new `tests/test_false_positives.py` (live tests + schema tests). **Measurement run pending:** `pytest tests/test_false_positives.py -m live_api -v` on a token-equipped machine tells us which v0.2 false positives v0.3 already fixed → that decides Step 2 scope. Side fixes while in there: `test_web_app.py` QC run-batch test no longer writes stub NOT_FOUNDs into the real master CSV (tmp-copy isolation — the Phase 5 retro "CSV side-effect"); `test_false_negatives.py` and the two API-hitting classes in `test_cl_api_issues.py` now carry the `live_api` mark, so a tokenless `pytest` run is green (413 passed / 0 failed). Also verified tokenless/403 behavior is already correct: stages error → `VERIFICATION_INCOMPLETE`, not bogus `NOT_FOUND`.
- **2026-06-10 (fallback regression corpus):** Closed the coverage-gap caveat from the benchmark harness. Built a 51-citation **fallback** corpus from the May-2026 FLP coverage study's lookup misses (`coverage_per_citation.csv`, `lookup_status=NOT_FOUND` — real cases that bypass citation-lookup). `tests/build_fallback_corpus.py` reconstructs full cites; recorded via the harness (`--corpus-name fallback`). **32/51 resolve, 100% via fallback stages (23 opinion_search, 9 recap_docket_search, 0 citation_lookup)** — so it actually exercises the RECAP/opinion-search scoring Levers 1-3 + Step 4 changed. `tests/test_fallback_regression.py` (offline ~3s) guards no-new-FN, no-silent-path-migration, and that the corpus keeps hitting fallback. 18 NOT_FOUND are real CL gaps the memo catalogued. Full offline suite 449 passed. Details in `docs/retrospectives/2026-06-10-benchmark-replay-harness.md`.
- **2026-06-10 (benchmark replay harness + Muldrow regression fix):** Built a record/replay test harness (`tests/cassette_client.py`) that caches CourtListener responses at the client seam so interpretation-logic changes regress offline. Mined 204 real citations from the spun-off benchmark gold DB (`tests/data/benchmark_real_citations.json`), recorded a cassette + baseline, and added an offline regression test (`test_benchmark_regression.py`) — the full 204-case run replays in ~2s vs ~10min live. **Bigger-test result: 202/204 real cases resolved**, surfacing **1 genuine false negative that was ours**: `Muldrow v. City of St. Louis, 144 S. Ct. 967` was capped to 0.39 by Lever 3's reporter-cite-contradiction arm because CL lists the parallel `601 U.S. 346` cite. Fixed by dropping the reporter/WL arm from the cap (keeping the reliable docket-number arm) — the cite arm was never load-bearing for any FP. After fix: **203/204 reals resolved, fake corpus still 0/19**, full mocked suite 446 passed. Caveat: this corpus resolves almost entirely at citation-lookup, so it guards real-case finding, not the RECAP fallback scoring (the 19 fakes + 14 WL-heavy reals cover that). Details: `docs/retrospectives/2026-06-10-benchmark-replay-harness.md`. **Fake-mining from Damien Charlotin's hallucination DB (~1,598 cases) is the next lever for FP scale — blocked on access (site/CSV return 403 to automated fetch; needs a manual download).**
- **2026-06-10 (Step 4 RECAP-leak half landed — corpus now FP 0/19):** Root-caused the state-court RECAP leak (Thompson): the guard `is_state_court = court_id and not is_federal_court(court_id)` keyed off the federal-only `court_id`, which is `None` for state courts, so RECAP ran; the single-state reporter-inference fallback missed multi-state reporters like N.E.2d. Fix: `_is_state_court_citation(parsed, court_id)` (used by both sync + async guards) flags state when the effective court (`court_id or parsed.court`) is non-federal OR the reporter is regional (`get_states_for_reporter` non-empty). **Live: FP 1→0, FN 14/14 held.** Coverage: Thompson integration repro + 7-case classification matrix (ind/mont/P.3d flagged; F.3d/WL/U.S. not); full mocked suite 284 passed. **Not done:** the other RECAP-leak reproducers (Oddi-Sampson/Reinlasoder/Keaau) are covered by the shared fix + unit matrix but aren't in the live corpus; the **cross-state opinion-match** half of Step 4 (Graves v. State) is a different mechanism (opinion-search state disqualification) and remains open. **Corpus now: FP 0/19, FN 14/14.**
- **2026-06-10 (Lever 3 landed — Tier 1 Step 2 DONE):** Inspecting the 3 residual FPs showed they weren't one class. (1) **Contradiction cap**: extended the Lever 2 no-corroboration cap so the strong-negative trigger is `party_mismatch OR docket_contradicted OR cite_contradicted` (cited value present on both sides but differing — gated present-and-differing, never absent; escape on a positive docket/cite match). (2) **Bare-docket parser fix** (`_BARE_DOCKET_PATTERN`): extract `2:20-cv-1882`-style numbers without a `No.` prefix, so Johnson's cited docket# is available to contradict. **Live: FP 3 → 1, FN 14/14 held.** Lopez (docket# 14-cv vs 10-cv) and Johnson (20-cv vs 02-cv) now NOT_FOUND. The lone remaining FP, **Thompson v. Best**, is a **state-court RECAP leak** (cited `indctapp`, RECAP shouldn't run) — handed to Step 4, no scoring lever can reach it. `TestContradictionCap` (3) + `test_parser_bare_docket.py` (3); full mocked suite 283 passed. **Net Step 2: FP 11→1, FN held 14/14.** Next: **Step 4** (state-court leaks), with Thompson now the motivating case alongside Oddi-Sampson/Reinlasoder/Keaau/Graves.
- **2026-06-09 (Lever 2 landed):** Symmetric party-mismatch handling in `_score_match` (TDD). Three parts, each surfaced by live evidence: (1) name-similarity penalty (`_PARTY_MISMATCH_NAME_FACTOR=0.25`) via the existing `_party_overlap_ok` — kills the opinion-search FPs (Johnson→Scudder, Thompson→Thompson-v-Thompson); (2) a no-corroboration **cap** — penalty alone was insufficient because these fakes name a plausible court+year, so a different wrong case scores ~0.40 on court+date alone (Johnson→Laile v. Mitchell 0.43); cap below threshold when party overlap fails AND neither cite nor docket# corroborates, with cite/docket match as the escape hatch for cl_display_name_data_bug cases; (3) `_normalize_docket_number` fix to strip paired District+Magistrate judge initials ("1:13-CV-1483 AWI SAB"). **Live: FN 14/14 held; FP stays 3 but the failure mode converged** — all party-mismatch matches eliminated, the 3 residual FPs are now a single class (name-plausible record, contradicting docket#/cite) = exactly Lever 3 (Lopez 0.85, Johnson 0.42, Thompson 0.425). 5 mocked tests in `TestPartyMismatchPenalty`; full mocked suite 268 passed; 3 corpus entries xfail with Lever-3 reasons. **Next: Lever 3** (docket#/reporter-cite contradiction penalty) — the sole remaining FP class.
- **2026-06-09 (Lever 1 landed):** RECAP hard-gate parity implemented (TDD). New `_recap_result_gated()` wired into both sync + async RECAP processing: name-token gate + **one-sided** temporal gate (reject cite-before-filing only) + a `_RECAP_PACER_ERA_FLOOR = 1990` (added when In re Hudson turned out to resolve to a null-`dateFiled` appellate docket the date-diff can't evaluate; RECAP=PACER data doesn't predate ~1990). Live results: **FP 11 → 3, FN 14/14 held.** The 3 remaining FPs are the Lever 2/3 cases (Johnson, Thompson → Lever 2; Lopez → Lever 3), now `xfail` in the corpus so they xpass-alert when fixed. 5 mocked tests in `TestRecapHardGates`; full mocked suite 263 passed. Details in the measurement retro. **Next: Lever 2.**
- **2026-06-09 (FN corpus widened, pre-Lever-1):** Before touching scoring, widened the false-negative guardrail `known_real_citations.json` **5 → 14** (sourced from QC-approved CSV rows + the spun-off `case-law-proposition-benchmark` gold_db, each re-verified live under v0.3). New coverage: 4 state-court reals (Mass N.E.2d, Mont. P.3d, D.C. A.2d, + generic-gov defendant), old SCOTUS (1833), common-prefix plaintiff, and **both RECAP sub-paths**. The critical add is `recap_long_running_date_gap` = **Oracle v. Google, 2016 WL 3181206** (docket filed 2010, cited 2016, VIA_RECAP) — the guard that fails any symmetric ±5yr RECAP temporal gate. Added `expected_docket_id` support to `test_false_negatives.py` so RECAP entries pin the docket, not just "not NOT_FOUND." All 16 live tests green (7m15s). This closes the "5-case corpus too thin" gap flagged in the measurement retro; Lever 1 now has a real two-direction harness.
- **2026-06-10 (measurement done):** Ran both live suites. **False positives: 8/19 fixed, 11/19 still verify. False negatives: 5/5 real cites still VERIFIED (no regression).** Full triage: `docs/retrospectives/2026-06-10-tier1-step1-measurement.md`; raw dump `scratch/fp_triage_result.json`. v0.3's big win is the `WRONG_CASE` status (5 of the 8 fixes are `wrong_name_real_citation` now correctly resolving-but-mismatched). **Key finding that reshapes Step 2:** 9 of 11 remaining FPs are `VERIFIED_DOCKET_ONLY` from the RECAP path — and the RECAP path (`_process_recap_results` sync + async) lacks the temporal + name-token **hard-gates** the opinion-search path already has. Reordered Step 2: **(1)** port those two gates to the RECAP path — reuses tested code, kills 7 zero-overlap matches + In re Hudson's 1812-vs-2018 (the "hard date gate," which belongs at the candidate level reading docket `dateFiled`, NOT inside `_score_match` where the docket-only path feeds it an empty date); **(2)** symmetric both-sides party-mismatch penalty in `_score_match` (Johnson→Scudder, Thompson→Thompson — 2 opinion-search FPs); **(3)** docket#/WL *contradiction* penalty for Lopez (the lone 0.85 FP) — do last, guard the false-negative corpus. One regression flagged: South Pointe Wholesale was NOT_FOUND in v0.2, now a RECAP FP — Lever 1 fixes it. Re-run both suites after each lever.
