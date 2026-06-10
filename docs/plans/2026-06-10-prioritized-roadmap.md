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
