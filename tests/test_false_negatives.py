"""Test suite for false negatives - real citations we should find.

This tracks regressions and validates fixes for known issues.
"""

import json
from pathlib import Path

import pytest

from citation_verifier import CitationVerifier
from citation_verifier.models import VerificationStatus


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

    verifier = CitationVerifier()
    result = verifier.verify(citation)

    # Should find the case (not NOT_FOUND)
    assert result.status != VerificationStatus.NOT_FOUND, (
        f"False negative for {category}: {citation}\n"
        f"Notes: {notes}\n"
        f"Expected cluster ID: {expected_cluster_id}\n"
        f"Diagnostics: {result.diagnostics}"
    )

    # If we have an expected cluster ID, verify it matches
    if expected_cluster_id:
        assert result.matched_cluster_id == expected_cluster_id, (
            f"Found a case but wrong cluster ID for: {citation}\n"
            f"Expected: {expected_cluster_id}\n"
            f"Got: {result.matched_cluster_id}\n"
            f"Matched case: {result.matched_case_name}\n"
            f"URL: {result.matched_url}"
        )

    # Print success info
    print(f"\n[OK] {category}: {result.status.value}")
    print(f"     Citation: {citation[:70]}...")
    print(f"     Matched: {result.matched_case_name}")
    print(f"     Confidence: {result.confidence:.0%}")
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
