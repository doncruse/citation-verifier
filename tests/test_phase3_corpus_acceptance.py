"""Phase 3 acceptance: run the verifier against tests/data/refactor_corpus.json
and assert each fixture's expected outcome.

This file hits the live CourtListener API (where mock_spec is null) and
deselects from the standard suite via the live_api mark.

VERIFICATION_INCOMPLETE fixtures are skipped here — Phase 4 wires the
mock_spec harness in production logic.
"""
from __future__ import annotations

import os

import pytest

from citation_verifier.verifier import CitationVerifier
from tests.data.refactor_corpus_loader import load_corpus

pytestmark = pytest.mark.live_api


@pytest.fixture(scope="module")
def verifier():
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set — live API tests skipped")
    return CitationVerifier()


_, _ALL_FIXTURES = load_corpus()
_RUNNABLE = [
    fx for fx in _ALL_FIXTURES
    if fx.expected_status != "VERIFICATION_INCOMPLETE"
]


@pytest.fixture(scope="module")
def results(verifier):
    """Run each runnable fixture once and cache the result by fixture id."""
    out: dict[str, object] = {}
    for fx in _RUNNABLE:
        out[fx.id] = verifier.verify(fx.citation)
    return out


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
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


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
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


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
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
