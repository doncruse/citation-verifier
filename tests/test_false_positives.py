"""False-positive regression suite: known-fake citations we must reject.

Counterpart to test_false_negatives.py. The corpus in
tests/data/known_fake_citations.json holds citations confirmed fake either
by a court (sanctions orders identifying the fabricated cite) or by manual
QC review (scratch/QC_TRIAGE.md, Feb 2026). A fake citation must never
come back with a VERIFIED-family status — that is the product's central
promise.

The live tests (marked live_api, deselected by default per pyproject
addopts) hit the real CourtListener API and require COURTLISTENER_API_TOKEN.
The schema tests run in the standard mocked suite.

Several v0.2 results recorded in the corpus (`prior_result`) were
false positives at the time (POSSIBLE_MATCH 0.4-0.65). Running this suite
under v0.3 is the measurement step from
docs/plans/2026-06-10-prioritized-roadmap.md Tier 1 Step 1: it shows which
of those the v0.3 taxonomy/scoring already fixed and which still need the
scoring gates in Tier 1 Step 2.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from citation_verifier import CitationVerifier
from citation_verifier.models import Status

_DATA_DIR = Path(__file__).parent / "data"
_KNOWN_FAKE_FILE = _DATA_DIR / "known_fake_citations.json"

# A fake citation may legitimately resolve to any of these: NOT_FOUND (no
# match), WRONG_CASE (the cite exists but belongs to a different case —
# the ideal outcome for wrong_name_real_citation entries), or
# INSUFFICIENT_DATA (parse too weak to verify). It must never come back
# VERIFIED-family.
_VERIFIED_FAMILY = {
    Status.VERIFIED,
    Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP,
    Status.VERIFIED_DOCKET_ONLY,
}

_VALID_CATEGORIES = {
    "hallucinated_case",
    "wrong_name_real_citation",
    "wrong_court",
    "wrong_page_number",
    "future_date",
    "invalid_reporter",
    "out_of_range_page",
}


def load_known_fake_citations():
    if not _KNOWN_FAKE_FILE.exists():
        return []
    with open(_KNOWN_FAKE_FILE, encoding="utf-8") as f:
        return json.load(f)


_CORPUS = load_known_fake_citations()


# ---------------------------------------------------------------------------
# Schema validation — runs in the default (mocked) suite
# ---------------------------------------------------------------------------


def test_corpus_is_nonempty():
    assert len(_CORPUS) >= 19


def test_corpus_entries_have_required_fields():
    for entry in _CORPUS:
        assert entry.get("citation"), f"entry missing citation: {entry}"
        assert entry.get("category") in _VALID_CATEGORIES, (
            f"invalid category {entry.get('category')!r} "
            f"for {entry['citation'][:60]}"
        )
        assert entry.get("expected_status") == "NOT_FOUND", (
            f"expected_status must be NOT_FOUND (the assertion itself allows "
            f"WRONG_CASE/INSUFFICIENT_DATA): {entry['citation'][:60]}"
        )
        assert entry.get("notes"), f"entry missing notes: {entry['citation'][:60]}"


def test_corpus_citations_unique():
    citations = [e["citation"] for e in _CORPUS]
    assert len(set(citations)) == len(citations)


# ---------------------------------------------------------------------------
# Live verification — requires COURTLISTENER_API_TOKEN, marked live_api
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def verifier():
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set — live API tests skipped")
    return CitationVerifier()


@pytest.fixture(scope="module")
def results(verifier):
    """Verify each corpus entry once, cached across the parametrized tests."""
    return {e["citation"]: verifier.verify(e["citation"]) for e in _CORPUS}


@pytest.mark.live_api
@pytest.mark.parametrize(
    "entry", _CORPUS, ids=lambda e: e.get("citation", "")[:60]
)
def test_known_fake_citation_rejected(entry, results):
    """A confirmed-fake citation must not verify.

    If a test fails:
    1. Check the matched URL in the failure output — is the verifier
       matching an unrelated case on surname/score inflation? That is the
       Tier 1 Step 2 scoring-gate work.
    2. Re-confirm the citation is actually fake (CL data changes; a case
       could have been added). If it turned real, move the entry to
       known_real_citations.json.
    """
    xfail_reason = entry.get("xfail_reason")
    if xfail_reason:
        pytest.xfail(xfail_reason)

    result = results[entry["citation"]]

    if result.status is Status.VERIFICATION_INCOMPLETE:
        pytest.skip(
            "VERIFICATION_INCOMPLETE — transient API failure, rerun to "
            "get a real verdict"
        )

    matched_url = result.final_ids.absolute_url
    prior = entry.get("prior_result", {})
    assert result.status not in _VERIFIED_FAMILY, (
        f"FALSE POSITIVE [{entry['category']}]: {entry['citation']}\n"
        f"  Got: {result.status.value} "
        f"(confidence {result.headline_confidence})\n"
        f"  Matched: {matched_url}\n"
        f"  Prior ({prior.get('engine', '?')}): {prior.get('status')} "
        f"@ {prior.get('confidence')}\n"
        f"  Notes: {entry.get('notes', '')}\n"
        f"  Warnings: {[w.category.value for w in result.warnings]}"
    )
