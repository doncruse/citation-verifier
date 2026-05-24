"""Phase 3 acceptance: run the verifier against tests/data/refactor_corpus.json
and assert each fixture's expected outcome.

Live-API tests hit the real CourtListener API (where mock_spec is null) and
deselect from the standard suite via the live_api mark.

Phase 4 Task 3: VERIFICATION_INCOMPLETE fixtures now run on a separate
mock-driven test function using MockSpecPatcher — no API token required.
"""
from __future__ import annotations

import os

import pytest

from citation_verifier.verifier import CitationVerifier
from tests.data.refactor_corpus_loader import load_corpus

_, _ALL_FIXTURES = load_corpus()

_ALL_FIXTURES_BY_RUNNABILITY = {
    "live": [fx for fx in _ALL_FIXTURES
             if fx.expected_status != "VERIFICATION_INCOMPLETE"],
    "mock": [fx for fx in _ALL_FIXTURES
             if fx.expected_status == "VERIFICATION_INCOMPLETE"],
}
_LIVE_RUNNABLE = _ALL_FIXTURES_BY_RUNNABILITY["live"]
_MOCK_RUNNABLE = _ALL_FIXTURES_BY_RUNNABILITY["mock"]


@pytest.fixture(scope="module")
def verifier():
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set — live API tests skipped")
    return CitationVerifier()


@pytest.fixture(scope="module")
def results(verifier):
    """Run each live-runnable fixture once and cache the result by fixture id."""
    out: dict[str, object] = {}
    for fx in _LIVE_RUNNABLE:
        out[fx.id] = verifier.verify(fx.citation)
    return out


@pytest.mark.live_api
@pytest.mark.parametrize("fx", _LIVE_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_status(fx, results):
    result = results[fx.id]
    assert result.status.value == fx.expected_status, (
        f"{fx.id}: expected {fx.expected_status}, got {result.status.value}\n"
        f"  Citation: {fx.citation}\n"
        f"  Rationale: {fx.rationale[:200]}\n"
        f"  Resolution path: "
        f"{[(e.stage.value, e.verdict.value) for e in result.resolution_path]}\n"
        f"  Warnings: {[w.category.value for w in result.warnings]}"
    )


@pytest.mark.live_api
@pytest.mark.parametrize("fx", _LIVE_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_final_ids(fx, results):
    """Pinned ID checks. Only asserts non-null pinned fields; null in
    the fixture means 'unconstrained.'"""
    result = results[fx.id]
    for key, pinned in fx.expected_final_ids.items():
        if pinned is None:
            continue
        if key == "text_source":
            actual = (
                result.final_ids.text_source.value
                if result.final_ids.text_source else None
            )
        else:
            actual = getattr(result.final_ids, key, None)
        assert actual == pinned, (
            f"{fx.id}: final_ids.{key} expected {pinned}, got {actual}"
        )


@pytest.mark.live_api
@pytest.mark.parametrize("fx", _LIVE_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_warnings_subset(fx, results):
    """expected_warnings_subset uses subset semantics — Phase 3 may
    emit other categories without breaking the fixture, as long as
    the required ones are present."""
    result = results[fx.id]
    actual = {w.category.value for w in result.warnings}
    expected = set(fx.expected_warnings_subset)
    missing = expected - actual
    assert not missing, (
        f"{fx.id}: missing required warnings {missing}; got {actual}"
    )


@pytest.mark.parametrize("fx", _MOCK_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_incomplete_status_via_mock(fx, monkeypatch):
    """Phase 4 Task 3: INCOMPLETE fixtures consume the corpus mock_spec
    via the MockSpecPatcher. Does not require COURTLISTENER_API_TOKEN."""
    from tests.mock_spec_harness import MockSpecPatcher
    from citation_verifier.client import CourtListenerClient
    from citation_verifier.models import Status
    from citation_verifier.verifier import CitationVerifier

    assert fx.mock_spec is not None, (
        f"{fx.id}: VERIFICATION_INCOMPLETE fixture must have mock_spec"
    )
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-not-used")
    client = CourtListenerClient(api_token="test-token-not-used")
    v = CitationVerifier(client)
    with MockSpecPatcher(client, spec=fx.mock_spec):
        result = v.verify(fx.citation)
    assert result.status == Status.VERIFICATION_INCOMPLETE, (
        f"{fx.id}: expected VERIFICATION_INCOMPLETE, got {result.status.value}\n"
        f"  Mock spec: {fx.mock_spec}\n"
        f"  Resolution path: "
        f"{[(e.stage.value, e.verdict.value) for e in result.resolution_path]}"
    )
    # Final IDs must all be null on INCOMPLETE (Task 2 enforces this).
    assert result.final_ids.cluster_id is None
    assert result.final_ids.docket_id is None
    assert result.final_ids.recap_document_id is None
