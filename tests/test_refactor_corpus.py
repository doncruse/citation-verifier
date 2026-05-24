"""Phase 2.5 acceptance tests for the refactor corpus.

These tests do NOT call the verifier. They validate the corpus file's
schema, count fixtures per status, and verify the named exemplars from
design v2 §4 are present. Phase 3's tests run the verifier against
each fixture.
"""

from __future__ import annotations

import pytest

from tests.data.refactor_corpus_loader import (
    Fixture,
    _VALID_STAGES,
    _VALID_STATUSES,
    fixtures_by_status,
    load_corpus,
)


@pytest.fixture(scope="module")
def corpus():
    metadata, fixtures = load_corpus()
    return metadata, fixtures


def test_metadata_has_required_fields(corpus):
    metadata, _ = corpus
    assert metadata["schema_version"] == "1"
    assert metadata["description"]
    assert isinstance(metadata["selection_criteria"], list)
    assert len(metadata["selection_criteria"]) >= 4


def test_ids_are_unique(corpus):
    _, fixtures = corpus
    ids = [fx.id for fx in fixtures]
    assert len(ids) == len(set(ids)), "Duplicate fixture ids"


def test_status_values_are_valid(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        assert fx.expected_status in _VALID_STATUSES, fx.id


def test_resolving_stage_values_are_valid(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        if fx.expected_resolving_stage is not None:
            assert fx.expected_resolving_stage in _VALID_STAGES, fx.id


def test_unresolved_statuses_have_null_stage(corpus):
    """NOT_FOUND and VERIFICATION_INCOMPLETE don't resolve — stage must be null."""
    _, fixtures = corpus
    for fx in fixtures:
        if fx.expected_status in {"NOT_FOUND", "VERIFICATION_INCOMPLETE"}:
            assert fx.expected_resolving_stage is None, (
                f"{fx.id}: unresolved status must have null expected_resolving_stage"
            )


def test_final_ids_are_dict(corpus):
    """expected_final_ids must always be a dict (possibly with null values),
    never absent. Per design §2.1: every field present, nullable rather
    than absent."""
    _, fixtures = corpus
    required_keys = {
        "cluster_id",
        "opinion_id",
        "docket_id",
        "recap_document_id",
        "text_source",
    }
    for fx in fixtures:
        assert isinstance(fx.expected_final_ids, dict), fx.id
        assert required_keys.issubset(fx.expected_final_ids.keys()), (
            f"{fx.id}: expected_final_ids missing keys: "
            f"{required_keys - fx.expected_final_ids.keys()}"
        )


def test_text_source_values_are_valid(corpus):
    """text_source values must be from the closed set in design §2.4."""
    _, fixtures = corpus
    valid = {"opinion_plain_text", "opinion_html", "recap_document", None}
    for fx in fixtures:
        ts = fx.expected_final_ids["text_source"]
        assert ts in valid, f"{fx.id}: text_source={ts!r} not in {valid}"


def test_mock_spec_only_for_verification_incomplete(corpus):
    """mock_spec is populated only for VERIFICATION_INCOMPLETE fixtures."""
    _, fixtures = corpus
    valid_modes = {
        "http_500",
        "http_502",
        "http_503",
        "http_429_no_retry_after",
        "timeout",
        "connection_error",
        "json_malformed",
    }
    for fx in fixtures:
        if fx.expected_status == "VERIFICATION_INCOMPLETE":
            assert fx.mock_spec is not None, f"{fx.id}: mock_spec required"
            assert fx.mock_spec["stage"] in _VALID_STAGES, fx.id
            assert fx.mock_spec["failure_mode"] in valid_modes, fx.id
        else:
            assert fx.mock_spec is None, (
                f"{fx.id}: mock_spec only valid for VERIFICATION_INCOMPLETE"
            )


def test_rationale_and_source_nonempty(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        assert fx.rationale.strip(), fx.id
        assert fx.source.strip(), fx.id


# Per-status minimum fixture counts. Phase 2.5 set the default floor to 5.
# Phase 3 §0.3 demoted Darensburg (VIA_RECAP -> DOCKET_ONLY per Westlaw
# disambiguation finding), and Task 6.4b will reclassify Cabot + Hunter
# (VIA_RECAP -> DOCKET_ONLY per strict opinion-typed gate). The plan
# explicitly authorizes lowering this floor — see Task 6.4b: "accept that
# the corpus minimum drops to 3 and update the test_refactor_corpus.py
# minimum threshold." VIA_RECAP minimum lowered again in Phase 3 Task 6
# after live-API validation: of the 4 originally-pinned VIA_RECAP
# fixtures, all but Menges-actual were reclassified to DOCKET_ONLY under
# strict gating (recap_doc_not_opinion_typed for Cabot/Hunter per Q1;
# Mehar's "ORDER GRANTING Motion for Reconsideration" description
# matches no opinion keywords; Doe v. Lawrence's WL-only citation has
# no specific date to compare against doc filing date). The Phase 3
# §3.1 ruling documents this — the floor of 1 is intentional under
# strict Phase 3 logic. Phase 4 may loosen the strict gate and raise
# the floor back up.
_STATUS_MIN_FIXTURES = {s: 5 for s in _VALID_STATUSES}
_STATUS_MIN_FIXTURES["VERIFIED_VIA_RECAP"] = 1


@pytest.mark.parametrize("status", sorted(_VALID_STATUSES))
def test_minimum_fixtures_per_status(corpus, status):
    """Design §3 Phase 2.5 acceptance: each status has the per-status
    minimum number of fixtures. VIA_RECAP floor lowered to 3 per Phase 3
    §0.3 + Task 6.4b (Westlaw-disambiguation + strict opinion-typed gate
    reclassifications)."""
    _, fixtures = corpus
    grouped = fixtures_by_status(fixtures)
    minimum = _STATUS_MIN_FIXTURES[status]
    assert len(grouped[status]) >= minimum, (
        f"{status}: only {len(grouped[status])} fixtures (need >= {minimum})"
    )


@pytest.mark.parametrize(
    "exemplar_id, expected_status",
    [
        ("named-exemplar-koch", "VERIFIED"),
        ("named-exemplar-gilliam", "VERIFIED_PARTIAL"),
        # Phase 3 §0.3: VIA_RECAP named exemplar moved from
        # named-exemplar-menges (Darensburg substitution) to Mehar Holdings
        # after Westlaw lookup showed 2009 WL 2392094 actually maps to the
        # Aug 4 procedural costs-taxation order, not the July 7 opinion the
        # fixture originally pinned. See docs/notes/wl-disambiguation-limit.md.
        # Phase 3 Task 6 follow-up: Mehar was temporarily downgraded to
        # VERIFIED_DOCKET_ONLY because its description "ORDER GRANTING Motion
        # for Reconsideration" matched no opinion keyword under the strict
        # Phase 3 gate (see survey §3.1).
        # Phase 4 Task 4 (Q2): restored to VERIFIED_VIA_RECAP by the
        # score-based gate (page_count >= 5 AND is_free_on_pacer). Mehar's
        # 12-page free doc qualifies regardless of description wording.
        ("named-exemplar-mehar-holdings", "VERIFIED_VIA_RECAP"),
        ("named-exemplar-wrong-case", "WRONG_CASE"),
        ("named-exemplar-verification-incomplete", "VERIFICATION_INCOMPLETE"),
    ],
)
def test_named_exemplars_present(corpus, exemplar_id, expected_status):
    """Design §4 acceptance: the named exemplars are in the corpus."""
    _, fixtures = corpus
    by_id = {fx.id: fx for fx in fixtures}
    assert exemplar_id in by_id, f"Missing named exemplar: {exemplar_id}"
    assert by_id[exemplar_id].expected_status == expected_status
    assert by_id[exemplar_id].category == "named_exemplar"
