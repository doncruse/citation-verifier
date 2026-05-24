# Changelog

All notable schema-level changes to citation-verifier. Per design v2 §2.6 / §5: additions to closed-set enums are minor-version changes, removals are major.

## v0.3.0 — 2026-05-24

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

### Testing infrastructure

- **`MockSpecPatcher` / `AsyncMockSpecPatcher`** in `tests/mock_spec_harness.py`: reusable test harness that wraps `client._request_with_retry` (sync + async) to inject stage-targeted API failures per a corpus `mock_spec` dict. URL/params-based stage classification; clean no-match stubs for non-target stages. Used by `tests/test_phase3_corpus_acceptance.py::test_corpus_fixture_incomplete_status_via_mock` to drive the 5 VERIFICATION_INCOMPLETE corpus fixtures without a CL token.

### Cross-repo consumers

- The benchmark project (`~/Projects/case-law-proposition-benchmark`) pins `citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.2.0` and is unblocked to upgrade to `v0.3.0`. See design v2 §5 "tag-pin staging."
