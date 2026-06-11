# Consumer Surface Manifest (v0.3)

This file enumerates every consumer of `VerificationResult` and the
`Status` enum, what each one reads, and what statuses each one expects.
**Run through this list before merging any change to `models.py`** —
schema changes that touch the status taxonomy or `final_ids` shape
need to update every entry below.

**Last full audit:** Phase 5 (2026-05-24). Maintainer: see CHANGELOG.md.

**v0.3.3 (2026-06-11) — `Status.CITE_UNCONFIRMED` added (Tier 1 Step 3 "Check Cite").**
Every consumer below was swept in the same change (see CHANGELOG v0.3.3). Notable
handling: `brief_pipeline._DOWNLOADABLE_STATUSES` **includes** CITE_UNCONFIRMED (it
carries the winning stage's `final_ids`, so the matched text is download-eligible —
unlike WRONG_CASE/NOT_FOUND); the web frontends render an amber "Check Cite" badge
(get/index tooltip is warning-aware — a `cite_contradicted` warning surfaces CL's
actual `record_citations`); `get.html` deep-search retry does **not** retry it
(resolved-ish); `__main__.py` `_STATUS_LABELS` → `[!] CHECK CITE` (exit code 0, like
WRONG_CASE — the pre-existing WRONG_CASE-exits-0 gap is unchanged/out of scope).
New warnings `cite_contradicted` / `cite_not_on_record` and gate `no_cite_unconfirmed`.
Coverage enforced by `test_frontend_status_coverage.py` + `test_models.py`.

## How to use this file

1. Before changing `Status`, `FinalIds`, `WarningCategory`, or
   `VerificationResult` fields, read this file end-to-end.
2. For each consumer row, decide whether it needs to be updated.
3. After landing the schema change, update each row's "Last verified"
   column to the phase / commit that re-checked it.
4. If you add a NEW consumer, add a row here in the same commit.

## Core library (verified Phase 5; v0.3 shape is canonical here)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `src/citation_verifier/models.py` | Defines the schema | N/A (source of truth) | Phase 4 |
| `src/citation_verifier/verifier.py` | Constructs `VerificationResult` via `_finalize_result` | Emits every `Status` value | Phase 4 |
| `src/citation_verifier/brief_pipeline.py` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence` | `_DOWNLOADABLE_STATUSES` + `_STATUS_BADGE_FALLBACK` cover every status | Phase 4 Task 8 |
| `src/citation_verifier/cache.py` | Full schema (round-trips) | Catches `ValueError` on unknown status enum value → safe cache-miss fallback | Phase 4 |
| `src/citation_verifier/__main__.py` (`main`, single-citation CLI) | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status` | Exit code: 0/1/2 by Status (Phase 5 Task 8) | Phase 5 Task 8 |
| `src/citation_verifier/__main__.py` (`audit_misses_main`) | `result.status` | Retries `NOT_FOUND` + `VERIFICATION_INCOMPLETE` in pass 2 (Phase 5 Task 7) | Phase 5 Task 7 |
| `src/citation_verifier/__main__.py` (`verify_brief_main`) | `_DOWNLOADABLE_STATUSES` via brief_pipeline | Covered by brief_pipeline's status mapping | Phase 4 |
| `src/citation_verifier/__main__.py` (`verify_batch_main`) | `result.final_ids`, `result.warnings`, `result.headline_confidence` | Emits every status to output CSV | Phase 4 |

## Web app (verified Phase 5; integration tests in `tests/test_web_app.py`)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `web/app.py` `/api/verify` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status`. Serializes via `_result_to_dict`. Per-citation `verify_async` (BYOK token preserved). | Emits every v0.3 status value; ERROR sentinel for catch-all | Phase 5 Task 2 |
| `web/app.py` `/api/qc/run-batch` | Same as above; per-citation `verify_async` after Phase 5 Task 2 (audit row C1 fix) | Same | Phase 5 Task 2 |
| `web/app.py` `/api/qc/runs` | Reads JSON sidecar metadata only | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/qc/run/{filename}` | Enriches sidecar rows with CSV state; sidecar dicts carry whatever status they had at write time (v0.2 or v0.3) | N/A (passthrough) | Phase 5 (smoke) |
| `web/app.py` `/api/qc/save` | None (writes `qc_status` field only) | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/qc/opinion-text` | None | N/A. **Known issue:** uses outdated text fallback chain (missing `html_lawbox`/`html_columbia`/`xml_harvard`); see `client._extract_opinion_text` for canonical chain. Pre-existing bug; not v0.3-related. | Phase 5 noted; deferred |
| `web/app.py` `/api/flag-for-flp` | None (writes user-supplied dict) | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/download-{pdfs,texts,htmls}` | None (operates on URLs) | N/A | Phase 5 (smoke) |
| `web/app.py` `_BlockQCMiddleware` (MODE=public) | URL prefix only | N/A (schema-orthogonal) | Phase 5 (smoke) |
| `web/static/get.html` `statusBadges` | `data.status` from SSE result events | Every v0.3 status has a `case` block (test in `tests/test_frontend_status_coverage.py`) | Phase 5 Task 3 |
| `web/static/get.html` deep-search retry | `data.status` | Retries `NOT_FOUND`, `ERROR`, `VERIFICATION_INCOMPLETE` | Phase 5 Task 5 |
| `web/static/index.html` `statusLabel/badgeClass/statusBadges` | Same as get.html | Same | Phase 5 Task 3 |
| `web/static/qc.html` `statusLabel/badgeClass` | Same | Same | Phase 5 Task 3 |
| `web/static/qc.html` filter chips | `data-filter` attribute on chip spans | Chips cover every v0.3 status + legacy LIKELY_REAL/POSSIBLE_MATCH for old sidecars | Phase 5 Task 4 |

## Iterative workflow scripts (verified Phase 5)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `tests/verify_from_csv.py` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status` | "needs QC" highlights NOT_FOUND/WRONG_CASE/INCOMPLETE/POSSIBLE_MATCH (Phase 5 Task 6) | Phase 5 Task 6 |
| `tests/verify_sample_citations.py` | `result.final_ids.absolute_url`, `result.final_ids.cluster_id`, `result.warnings`, `result.headline_confidence` | Results dict built from `Status` enum (Phase 5 Task 9) | Phase 5 Task 9 |
| `tests/extract_citations_batch.py` | None (PDF extraction, pre-verify) | N/A | n/a |
| `tests/extract_hallucination_citations.py` | None | N/A | n/a |

## Test files (verified Phase 5; the test suite IS the consumer here)

| File | What it reads | Coverage notes |
|---|---|---|
| `tests/test_verifier.py` | Full schema | 101 unit tests; covers every status path |
| `tests/test_async_verifier.py` | Full schema | 29 sync/async parity tests |
| `tests/test_brief_pipeline.py` | brief_pipeline status mapping | Covers DOWNLOADABLE_STATUSES + badge fallback |
| `tests/test_resolution_path.py` | resolution_path entries | Covers verdict types |
| `tests/test_phase3_corpus_acceptance.py` | Full schema (live API + mock) | 141 live + 5 mock fixtures pin expected statuses |
| `tests/test_false_negatives.py` | Full schema (live API) | 7 known-real citations |
| `tests/test_web_app.py` | API JSON shape | **NEW Phase 5 Task 1** — regression-pattern tests |
| `tests/test_frontend_status_coverage.py` | Static JS coverage | **NEW Phase 5 Task 3** — every Status enum value has a JS case |
| `tests/test_cli_audit_misses.py` | `audit_misses_main` retry logic | Covers Phase 5 Task 7 |
| `tests/test_cli_verify_json.py` `TestExitCodes` | `main` exit code mapping | Covers Phase 5 Task 8 |
| `tests/test_cli_verify_batch.py` | `verify_batch_main` CSV output | Pinned to v0.3 column set |

## Known v0.2 dust (deliberately NOT updated; not in active code paths)

| File | What | Reason kept | Action needed |
|---|---|---|---|
| `scratch/casedev/test_waterfall.py` | `result.matched_url`, `LIKELY_REAL`, `POSSIBLE_MATCH` | One-off case.dev API exploration script from 2026-03 (per `scratch/casedev/README.md`); not run since | None — exploration archive |
| `scratch/casedev/waterfall_batch_50.py` | Same | Same | None |
| Old JSON sidecars under `tests/data/results/` (gitignored) | v0.2-status fields | Backward-compat handled by frontend JS + cache `ValueError` swallow | None |
| Master CSV pre-v0.3 rows with `v_status=LIKELY_REAL` / `POSSIBLE_MATCH` | Same | `verify_from_csv.py` reads both via `__main__._read_status_from_csv` mapping | None |

## Known issues (deferred to Phase 6+)

| Issue | Where | Why deferred | Impact |
|---|---|---|---|
| `/api/qc/opinion-text` text fallback chain missing `html_lawbox`/`html_columbia`/`html_anon_2020`/`xml_harvard` | `web/app.py:1131-1212` | Pre-existing bug (predates v0.3); QC opinion-text peek panel underserves state opinions where `plain_text` is empty. | State opinions render as "no opinion text available" in the QC peek panel even when `html_lawbox` populates. Fix: replace inline regex chain with a call to `client._extract_opinion_text` or `get_opinion_text_with_metadata`. |
| `_STATUS_DISPLAY` dict appears to be dead code | `web/app.py:45-53` | Single reference (its own definition); intended for a templated-response feature that wasn't wired. | Harmless; just clutter. Can be removed in a small cleanup PR. |

## Adding a new consumer

When you write code that consumes `VerificationResult` or `Status`:

1. Add a row to the appropriate table above in the same commit.
2. Declare which fields you read and what statuses you handle.
3. Add an integration or static test to one of:
   - `tests/test_web_app.py` for web-app endpoints
   - `tests/test_frontend_status_coverage.py` for HTML/JS coverage
   - `tests/test_cli_*.py` for CLI scripts
   - `tests/test_<your_module>.py` for new library modules
4. If you handle status in a `match` / `switch` / dict, write a test
   that asserts every `Status` enum member appears as a case. The
   pattern in `tests/test_frontend_status_coverage.py` is the model.
