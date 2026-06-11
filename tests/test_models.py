"""Unit tests for the v0.3 schema types in models.py."""
from __future__ import annotations

import pytest

from citation_verifier.models import (
    BatchVerificationResult,
    FinalIds,
    GateFailure,
    GateName,
    GateSpec,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)


class TestStatusEnum:
    def test_has_expected_states(self):
        assert {s.value for s in Status} == {
            "VERIFIED",
            "VERIFIED_PARTIAL",
            "VERIFIED_VIA_RECAP",
            "VERIFIED_DOCKET_ONLY",
            "WRONG_CASE",
            "CITE_UNCONFIRMED",   # Check Cite design (2026-06-11)
            "NOT_FOUND",
            "VERIFICATION_INCOMPLETE",
            "INSUFFICIENT_DATA",
        }


class TestVerificationResult:
    def test_minimal_construction(self):
        result = VerificationResult(
            citation_as_written="Foo v. Bar, 1 U.S. 1 (2020)",
            parsed_citation=None,
            status=Status.NOT_FOUND,
            final_ids=FinalIds(
                cluster_id=None, opinion_id=None, docket_id=None,
                recap_document_id=None, absolute_url=None, text_source=None,
            ),
            resolution_path=[],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 0},
            cache_hit=False,
        )
        assert result.status == Status.NOT_FOUND
        assert result.headline_confidence is None

    def test_headline_confidence_walks_path_in_reverse(self):
        """Per design §2.5: returns confidence of the last `resolved`-or-
        `partial` entry, scanning from the tail."""
        result = VerificationResult(
            citation_as_written="x",
            parsed_citation=None,
            status=Status.VERIFIED,
            final_ids=FinalIds(None, None, None, None, None, None),
            resolution_path=[
                ResolutionPathEntry(
                    stage=StageName.citation_lookup,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.no_match,
                    confidence=None, notes=None, elapsed_ms=10,
                ),
                ResolutionPathEntry(
                    stage=StageName.opinion_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.resolved,
                    confidence=0.78, notes=None, elapsed_ms=120,
                ),
            ],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 130},
            cache_hit=False,
        )
        assert result.headline_confidence == 0.78

    def test_headline_confidence_skips_non_resolved_entries(self):
        result = VerificationResult(
            citation_as_written="x",
            parsed_citation=None,
            status=Status.NOT_FOUND,
            final_ids=FinalIds(None, None, None, None, None, None),
            resolution_path=[
                ResolutionPathEntry(
                    stage=StageName.opinion_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.partial,
                    confidence=0.55, notes=None, elapsed_ms=120,
                ),
                ResolutionPathEntry(
                    stage=StageName.recap_document_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.errored,
                    confidence=None, notes="rate limited", elapsed_ms=300,
                ),
            ],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 420},
            cache_hit=False,
        )
        # Reverse walk: errored is skipped, partial wins.
        assert result.headline_confidence == 0.55


class TestWarningAndGate:
    def test_warning_construction(self):
        w = Warning(
            category=WarningCategory.cl_display_name_data_bug,
            message="CL display name differs from real caption",
            details={"cl_name": "Ricky Koch v. Tote, Incorporated"},
        )
        assert w.category == WarningCategory.cl_display_name_data_bug

    def test_gate_failure_construction(self):
        gf = GateFailure(
            gate=GateName.no_not_found,
            reason="status is NOT_FOUND",
            details=None,
        )
        assert gf.gate == GateName.no_not_found


class TestBatchVerificationResult:
    def test_grouped_by_status_shape(self):
        batch = BatchVerificationResult(
            total=0, by_status={}, errors=[], elapsed_ms=0,
        )
        assert batch.total == 0


def test_warning_category_has_cl_duplicate_clusters():
    """Per Phase 3 plan Task 2 (maintainer Q3 pre-decision): CL has
    multiple clusters for the same case; caption_investigation emits
    this warning instead of privileging one canonical cluster ID."""
    from citation_verifier.models import WarningCategory
    assert WarningCategory.cl_duplicate_clusters.value == "cl_duplicate_clusters"


def test_warning_category_has_wrong_page_number():
    """Per Phase 3 plan Task 2 (maintainer Q2 pre-decision): name
    resolves to a known case at a different reporter location than
    cited. Fires during caption_investigation."""
    from citation_verifier.models import WarningCategory
    assert WarningCategory.wrong_page_number.value == "wrong_page_number"
