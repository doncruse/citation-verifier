"""Test suite for false negatives - real citations we should find.

This tracks regressions and validates fixes for known issues.
"""

import json
from pathlib import Path

import pytest

from citation_verifier import CitationVerifier
from citation_verifier.models import Status

# Every test here hits the real CourtListener API. Deselected from the
# default suite (pyproject addopts); run with: pytest -m live_api
pytestmark = pytest.mark.live_api


# Load test corpus
_DATA_DIR = Path(__file__).parent / "data"
_KNOWN_REAL_FILE = _DATA_DIR / "known_real_citations.json"


def load_known_real_citations():
    """Load the corpus of known-real citations."""
    if not _KNOWN_REAL_FILE.exists():
        return []
    with open(_KNOWN_REAL_FILE) as f:
        return json.load(f)


@pytest.mark.parametrize(
    "test_case",
    load_known_real_citations(),
    ids=lambda tc: tc.get("citation", "")[:60],
)
def test_known_real_citation(test_case):
    """Verify we find known-real cases.

    This test uses REAL API calls to CourtListener. It will be slow
    and requires an API token.

    If a test fails:
    1. Check if the citation is still valid (did CL data change?)
    2. Check if our parser/verifier regressed
    3. Update the test data if needed
    """
    citation = test_case["citation"]
    expected_cluster_id = test_case.get("expected_cluster_id")
    category = test_case.get("category", "unknown")
    notes = test_case.get("notes", "")

    xfail_reason = test_case.get("xfail_reason")
    if xfail_reason:
        pytest.xfail(xfail_reason)

    verifier = CitationVerifier()
    result = verifier.verify(citation)

    matched_case_name = (
        result.resolution_path[-1].raw_response_summary.get("case_name")
        if result.resolution_path else None
    )
    warnings_str = "; ".join(w.message for w in result.warnings)
    stage_notes = (
        result.resolution_path[-1].notes
        if result.resolution_path and result.resolution_path[-1].notes
        else ""
    )

    # Should find the case (not NOT_FOUND)
    assert result.status != Status.NOT_FOUND, (
        f"False negative for {category}: {citation}\n"
        f"Notes: {notes}\n"
        f"Expected cluster ID: {expected_cluster_id}\n"
        f"Warnings: {warnings_str}\n"
        f"Stage notes: {stage_notes}"
    )

    # If we have an expected cluster ID, verify it matches
    if expected_cluster_id:
        assert result.final_ids.cluster_id == expected_cluster_id, (
            f"Found a case but wrong cluster ID for: {citation}\n"
            f"Expected: {expected_cluster_id}\n"
            f"Got: {result.final_ids.cluster_id}\n"
            f"Matched case: {matched_case_name}\n"
            f"URL: {result.final_ids.absolute_url}"
        )

    # Print success info
    print(f"\n[OK] {category}: {result.status.value}")
    print(f"     Citation: {citation[:70]}...")
    print(f"     Matched: {matched_case_name}")
    conf = result.headline_confidence
    if conf is not None:
        print(f"     Confidence: {conf:.0%}")
    if notes:
        print(f"     Notes: {notes}")


def test_corpus_exists():
    """Verify the test corpus file exists and is valid JSON."""
    assert _KNOWN_REAL_FILE.exists(), (
        f"Test corpus not found: {_KNOWN_REAL_FILE}\n"
        "Create it with known-real citations for regression testing."
    )

    citations = load_known_real_citations()
    assert len(citations) > 0, "Test corpus is empty"

    # Validate structure
    for i, tc in enumerate(citations):
        assert "citation" in tc, f"Entry {i} missing 'citation' field"
        assert "category" in tc, f"Entry {i} missing 'category' field"
        # expected_cluster_id is optional (for cases we can't verify ID)


def test_categories_coverage():
    """Report coverage of different false negative categories."""
    citations = load_known_real_citations()
    categories = {}

    for tc in citations:
        cat = tc.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    print("\n" + "="*60)
    print("FALSE NEGATIVE TEST COVERAGE BY CATEGORY")
    print("="*60)
    for cat, count in sorted(categories.items()):
        print(f"  {cat:30s} {count:3d} test(s)")
    print("="*60)
    print(f"  {'TOTAL':30s} {len(citations):3d} test(s)")
    print("="*60)
