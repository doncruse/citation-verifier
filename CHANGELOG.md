# Changelog

All notable schema-level changes to citation-verifier. Per design v2 §2.6 / §5: additions to closed-set enums are minor-version changes, removals are major.

## v0.3.2 — 2026-05-27

### Schema (models.py)

- **New `Status.INSUFFICIENT_DATA`** in the "Unresolved" group. Additive minor-version change per design v2 §2.6. Distinguishes "the parser couldn't extract enough metadata to anchor a confident verification" from `NOT_FOUND` ("we tried everything we have and found nothing convincing"). Carries no `final_ids` — promotion nulls cluster_id, docket_id, recap_document_id, absolute_url, and text_source, mirroring the `VERIFICATION_INCOMPLETE` design §2.8 pattern.

### Behavior

- **NOT_FOUND → INSUFFICIENT_DATA promotion in `_finalize_result`**: when the final status would be `NOT_FOUND` AND `parsed_citation.court is None` AND `parsed_citation.year is None`, the verifier promotes to `INSUFFICIENT_DATA`. Runs after the existing INCOMPLETE promotion, so `VERIFICATION_INCOMPLETE` (CL infra failure — rerun) still wins when both conditions apply. The pre-existing `_search_fallback` short-circuit (which already skipped opinion_search and RECAP when court+year are both missing) is preserved; this change only relabels the terminal status. The "Insufficient data to verify..." note remains on the synthetic opinion_search resolution_path entry.
- **Single-citation CLI exit codes** (`__main__.py`): new exit code `3` for `INSUFFICIENT_DATA`. Priority in a mixed batch via `max()`: `3 (INSUFFICIENT_DATA) > 2 (INCOMPLETE) > 1 (NOT_FOUND) > 0`. Rationale: "we couldn't tell because the input was too weak" outranks the other failure modes because retry / hallucination analysis are moot until the parse is fixed.

### Consumer surface

- **Frontend coverage** (`web/static/{get,index,qc}.html`): added `case 'INSUFFICIENT_DATA':` blocks to every Status switch (badgeClass, statusLabel, statusBadges per page). Badge style mirrors `POSSIBLE_MATCH` / `VERIFIED_DOCKET_ONLY` warning treatment. The Phase 5 `test_every_status_has_case_in_every_switch` test enforces coverage.
- **QC filter chip** (`qc.html`): new `data-filter='INSUFFICIENT_DATA'` chip in the default-active set alongside `NOT_FOUND` / `WRONG_CASE` / `VERIFICATION_INCOMPLETE` / `POSSIBLE_MATCH`. Active-state chip styling matches INCOMPLETE (`#856404`).
- **Deep-search retry exclusion** (`get.html`): `INSUFFICIENT_DATA` is intentionally NOT included in the `quickNotFoundIndices` retry trigger. The retry escalates the lookup — it cannot fix a parser failure. Same reasoning excludes it from `audit-misses`'s full-pipeline retry pass.
- **`brief_pipeline._STATUS_BADGE_FALLBACK`**: new mapping for the report-finding fallback label ("Insufficient data — citation lacks court and year") for legacy claims.csv runs without an agent-authored badge_label.
- **`tests/verify_from_csv.py`**: post-run "NEEDS QC" highlight now includes `INSUFFICIENT_DATA` alongside `NOT_FOUND`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`, and `POSSIBLE_MATCH`.

### Testing

- New `TestInsufficientData` class in `test_verifier.py` (5 tests): main promotion, final_ids nulling, court-set blocking, year-set blocking, lookup-success blocking.
- `test_async_verifier.py::test_parity_insufficient_data_guard` updated from `Status.NOT_FOUND` to `Status.INSUFFICIENT_DATA`.
- `test_models.py::TestStatusEnum::test_has_six_states` renamed to `test_has_expected_states` and updated to include the new enum value.
- 2 new CLI exit-code tests in `test_cli_verify_json.py::TestExitCodes`: `test_insufficient_data_exits_three` and `test_insufficient_data_beats_other_failures`.

## v0.3.1 — 2026-05-23

### Schema (models.py)

- **New `VerificationResult.syllabus` property**: walks `resolution_path` in reverse looking for a `citation_lookup` entry with `verdict=resolved`/`partial`, and returns the joined `syllabus` + `nature_of_suit` strings from its `raw_response_summary` (joined with `"; "` per the pre-refactor convention). Returns `None` when no citation_lookup entry exists or neither metadata field is populated. Additive, no removed surfaces. Mirrors `headline_confidence`'s walk-the-path accessor pattern (design §2.5).

### Behavior

- **`raw_response_summary` for `citation_lookup` entries now carries `syllabus` and `nature_of_suit`** keys when the CL cluster response includes them (omitted when absent to avoid storing empty strings). Per design §2.5, `raw_response_summary` is free-form per stage; this is an addition to the citation_lookup stage's documented shape, not a contract break.
- **`brief_pipeline._write_verification_csv` re-populates the `syllabus` CSV column** via `result.syllabus`. The column had been blank since the Phase 1 schema migration (which deferred the question to "Phase 3 re-evaluates whether to add to FinalIds"); restored here as Phase 1 retro Q5 / Path A (raw_response_summary + accessor rather than top-level field, since syllabus is per-stage metadata not a verifier-side ID).
- **Verify-brief skill's syllabus-based topic-mismatch triage works again**: `SKILL.md` Phase 1d's "Syllabus check" print path and Phase 2a's "Syllabus vs. proposition topic mismatch" full-Opus trigger now receive data. SKILL.md prose was already correct; only the upstream data plumbing was missing.

### Roadmap cleanup

- Removed `scratch/ROADMAP.md` entry "Fabricated quote detection (separate criterion)" — audit confirmed all three claims are realized (quote_check_worst produces FABRICATED status; SKILL.md Phase 2a triage uses it as a full-Opus trigger; Phase 2c assessment matrix treats FABRICATED as its own axis with dedicated badge labels).

## v0.3.0 — 2026-05-24

### Migrating from v0.2 to v0.3

Most upgrades touch only two surfaces:

**1. `VerificationResult` field renames** (top-level fields collapsed under `final_ids`):

| v0.2 | v0.3 |
|------|------|
| `result.matched_url` | `result.final_ids.absolute_url` |
| `result.matched_cluster_id` | `result.final_ids.cluster_id` |
| `result.matched_docket_id` | `result.final_ids.docket_id` |
| `result.confidence` | `result.headline_confidence` |
| `result.diagnostics` | `result.warnings` |

`matched_court`, `matched_date`, `matched_description` were dropped from `VerificationResult` (they were not consistently populated). Use `result.parsed_citation.court` and `result.parsed_citation.year` for the *cited* values, or read the CL cluster directly via `final_ids.cluster_id`.

**2. `Status` taxonomy** (`LIKELY_REAL` and `POSSIBLE_MATCH` removed):

| v0.2 status | What to do in v0.3 |
|---|---|
| `LIKELY_REAL` | No longer emitted. Treat as `VERIFIED`. |
| `POSSIBLE_MATCH` | No longer emitted. Caption-divergence cases now produce `VERIFIED` + a warning, or `WRONG_CASE`. |

**New v0.3 statuses to handle:**
- `VERIFIED_PARTIAL` — parallel cite resolved, primary didn't (e.g. NY A.D.3d + slip op)
- `VERIFIED_VIA_RECAP` — matched a specific RECAP document (federal PACER)
- `VERIFIED_DOCKET_ONLY` — docket found, specific cited opinion not pinned
- `WRONG_CASE` — reporter cite resolves to a different case (caption divergence + party-overlap fails)
- `VERIFICATION_INCOMPLETE` — CL infrastructure failure (5xx / timeout); rerun

**Code patterns that change:**

```python
# v0.2: "any verified-class" check
if result.status in (Status.VERIFIED, Status.LIKELY_REAL):
    ...

# v0.3: covers all five verified-class statuses
if result.status.value.startswith("VERIFIED"):
    ...

# v0.3: RECAP vs opinion-cluster discriminator
if result.final_ids.docket_id and not result.final_ids.cluster_id:
    # RECAP match (no opinion cluster)
```

**Diagnostic messages** (legacy `result.diagnostics`) are now structured `Warning` objects on `result.warnings`. Both have `.category` and `.message`; the v0.3 categories are a closed enum (see `WarningCategory`). To get a flat string list:
```python
diagnostic_strs = [w.message for w in result.warnings]
```

**CLI exit codes** (single-citation `python -m citation_verifier`):
- `0` — all verified (unchanged)
- `1` — at least one `NOT_FOUND` (unchanged)
- `2` — at least one `VERIFICATION_INCOMPLETE` (NEW). Wins over `NOT_FOUND` when both appear — if any verification didn't complete, the `NOT_FOUND` signal isn't fully trustworthy either.

**Cache and disk artifacts** (no action needed):
- `.citation_cache.json` from v0.2 — safe to keep. The cache catches `ValueError` on unknown status and falls through to re-verify.
- Old JSON sidecars under `tests/data/results/` — read correctly by the QC page (frontend keeps legacy `LIKELY_REAL`/`POSSIBLE_MATCH` cases for historical data).

**Consumer surface checklist:** `docs/consumer-surface-manifest.md` enumerates every consumer in this repo and what fields each one reads. Use it as a model when auditing your own codebase for the v0.3 upgrade.

### Schema (models.py)

- **New `Status` taxonomy**: six states (VERIFIED, VERIFIED_PARTIAL, VERIFIED_VIA_RECAP, VERIFIED_DOCKET_ONLY, WRONG_CASE, NOT_FOUND, VERIFICATION_INCOMPLETE) replacing the legacy four (VERIFIED, LIKELY_REAL, POSSIBLE_MATCH, NOT_FOUND). LIKELY_REAL and POSSIBLE_MATCH collapsed into VERIFIED with per-stage confidence on resolution_path. See design v2 §2.2.
- **New `VerificationResult` shape**: `final_ids`, `resolution_path`, `warnings`, `gates_failed`, `timing`, `cache_hit` are mandatory. The top-level `confidence`, `matched_*`, and `diagnostics` fields are removed. Headline confidence is now a property derived from resolution_path. See design v2 §2.1.
- **New `WarningCategory` (closed set)**: silent_partial_verification, cl_display_name_data_bug, court_mismatch_noted, date_close_not_exact, name_formatting_noise, unparseable_citation, extraction_contamination_detected. Added Phases 1–2.
- **Phase 3 WarningCategory additions** (this entry): `cl_duplicate_clusters`, `wrong_page_number`. Both are facts the verifier observed during caption_investigation; neither is editorialization. See design v2 §2.6 amendment note.
- **ParsedCitation**: added `ecf_document_number: str | None` (Phase 1).

### Behavior

- Phase 3: `caption_investigation` stage now runs automatically when citation_lookup hits at a different case_name than the brief cited. Outcomes: VERIFIED + cl_display_name_data_bug (CL metadata stale), VERIFIED + name_formatting_noise (cosmetic divergence), VERIFIED + cl_duplicate_clusters (CL has multiple clusters for the case), VERIFIED + wrong_page_number (same case, different page), or WRONG_CASE (party-overlap fails). See verifier.py.
- Phase 3: `VERIFIED_PARTIAL` is produced when a parallel cite resolves but the primary reporter does not (e.g. NY A.D.3d + slip op pattern).
- Phase 3: `VERIFIED_VIA_RECAP` requires a RECAPDocument that is the cited opinion (date match within ±2 weeks of cited date, opinion-typed description, no procedural-order keywords). Otherwise `VERIFIED_DOCKET_ONLY`.
- Phase 3: `WRONG_CASE` is produced by caption_investigation's party-overlap check (at least one plaintiff and one defendant token must match after normalization; otherwise WRONG_CASE).

### Phase 4 behavior

- **VERIFICATION_INCOMPLETE production wiring** (design §2.8 internal gate): `_finalize_result` now promotes `NOT_FOUND` to `VERIFICATION_INCOMPLETE` when any stage in `resolution_path` has `verdict=errored` and no stage has `resolved`/`partial`. Resolved-stage-trumps-errored asymmetry honors the rule "fail-closed only at the boundary of verifier integrity" (design §1.5). On promotion, all `final_ids` are nulled so consumers cannot mistake an INCOMPLETE result for a partial verification.
- **Opinion-typing gate refinement** (Phase 3 retro Q2): VIA_RECAP now accepts substantive-but-keyword-poor opinion descriptions ("ORDER GRANTING Motion for X") via a score-based gate (`page_count >= 5 AND is_free_on_pacer AND no procedural keywords`). The verifier fetches `/recap-documents/{id}/` detail when `search_recap` omits the metadata. Mehar Holdings restored to VIA_RECAP.
- **X v. United States caption_investigation gap** (Phase 3 retro Q3): `_names_match_citation_lookup` now detects generic-government-defendant patterns (`v. United States`, `v. State`, `v. Commonwealth`, `v. People`). Koch named exemplar recovers its `cl_display_name_data_bug` warning.
- **Brief pipeline status-aware badges** (Phase 3 retro carry-forward): `brief_pipeline.py` now consults a `_STATUS_BADGE_FALLBACK` map when the agent-authored `badge_label` is absent. WRONG_CASE, VERIFIED_PARTIAL, VERIFIED_VIA_RECAP, VERIFIED_DOCKET_ONLY, VERIFICATION_INCOMPLETE get distinguishable labels. The agent-authored path is unchanged.

### Phase 5 behavior (consumer compatibility sweep)

- **Web app `/api/qc/run-batch` regression fix** (audit row C1): the QC batch endpoint previously called `_search_fallback_async(client, cite, parsed)` with the v0.2 3-arg signature, raising TypeError on every miss. Routed through per-citation `verify_async()` for consistency with `/api/verify`'s addendum fix. Same code path as CLI + unit tests; schema changes can no longer silently break it.
- **Single-citation CLI exit codes** (audit row C7): now distinguishes `NOT_FOUND` (exit 1) from `VERIFICATION_INCOMPLETE` (exit 2). When a batch contains both, INCOMPLETE wins — if any verification didn't complete, the NOT_FOUND signal is itself not fully trustworthy.
- **`audit-misses` CLI** (audit row C6): retries `VERIFICATION_INCOMPLETE` quick-results in the full pass alongside `NOT_FOUND` (design §2.8: INCOMPLETE is exactly the case the full pipeline's fallback was built for).
- **`tests/verify_sample_citations.py`** (audit row C2): migrated to v0.3 schema (was crashing on every successful verify due to `result.matched_url` / `result.diagnostics` AttributeErrors). Results dict now built from `Status` enum so future additions auto-bucket.
- **`tests/verify_from_csv.py`** (audit row C5): post-run "NEEDS QC" highlight now includes `WRONG_CASE` and `VERIFICATION_INCOMPLETE` alongside `NOT_FOUND` and `POSSIBLE_MATCH`.
- **Frontend coverage** (audit row C3, C4, plus addendum sweep): every `Status` enum value has a `case` block in each of `web/static/{get,index,qc}.html`'s JS switches (test in `tests/test_frontend_status_coverage.py`). QC page filter chips cover all v0.3 statuses; default-active set is `NOT_FOUND` + `WRONG_CASE` + `VERIFICATION_INCOMPLETE` + `POSSIBLE_MATCH`. Deep-search retry includes `VERIFICATION_INCOMPLETE`.
- **Web app integration test infrastructure** lands as `tests/test_web_app.py`. Regression-pattern coverage of `/api/verify`, `/api/qc/run-batch`, `/api/qc/runs`, `/api/qc/save`, `/api/flag-for-flp`, `/api/download-pdfs`, `/api/health`, and the public-mode middleware. Stubs `AsyncCourtListenerClient` at both module boundaries (web.app and verifier).
- **`docs/consumer-surface-manifest.md`** enumerates every consumer of `VerificationResult` and `Status` — checklist artifact for future schema changes. Includes "Known issues" section tracking `verify_batch()`'s deferred `needs_caption_investigation` bug and client-injection gap.

### Testing infrastructure

- **`MockSpecPatcher` / `AsyncMockSpecPatcher`** in `tests/mock_spec_harness.py`: reusable test harness that wraps `client._request_with_retry` (sync + async) to inject stage-targeted API failures per a corpus `mock_spec` dict. URL/params-based stage classification; clean no-match stubs for non-target stages. Used by `tests/test_phase3_corpus_acceptance.py::test_corpus_fixture_incomplete_status_via_mock` to drive the 5 VERIFICATION_INCOMPLETE corpus fixtures without a CL token.
- **Phase 5 additions**: `tests/test_web_app.py` (14 tests, FastAPI TestClient + stubbed CL client), `tests/test_frontend_status_coverage.py` (5 tests, static JS switch-body checks with brace-balanced extraction), plus per-task unit tests in `test_cli_audit_misses.py` and `test_cli_verify_json.py`. Test count: 362 → 386.

### Cross-repo consumers

- The benchmark project (`~/Projects/case-law-proposition-benchmark`) pins `citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.2.0` and is unblocked to upgrade to `v0.3.0`. See design v2 §5 "tag-pin staging."
