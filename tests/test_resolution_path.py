"""Unit tests for ResolutionPathBuilder (Phase 2)."""
from __future__ import annotations

import time

import pytest

from citation_verifier.models import StageName, StageVerdict
from citation_verifier.resolution_path import ResolutionPathBuilder


class TestResolutionPathBuilderBasic:
    def test_empty_builder_has_no_entries(self):
        b = ResolutionPathBuilder()
        assert b.entries() == []

    def test_resolved_stage_appends_entry(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup, query={"text": "x"}) as t:
            t.resolved(
                confidence=1.0,
                raw_response_summary={"matched_cluster_id": 42, "matched_case_name": "Foo v. Bar", "clusters_returned": 1},
            )
        entries = b.entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.stage == StageName.citation_lookup
        assert e.verdict == StageVerdict.resolved
        assert e.confidence == 1.0
        assert e.query == {"text": "x"}
        assert e.raw_response_summary["matched_cluster_id"] == 42
        assert e.elapsed_ms >= 0

    def test_no_match_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.no_match(raw_response_summary={"clusters_returned": 0})
        e = b.entries()[0]
        assert e.verdict == StageVerdict.no_match
        assert e.confidence is None

    def test_partial_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.opinion_search) as t:
            t.partial(confidence=0.55, notes="primary reporter unverified")
        e = b.entries()[0]
        assert e.verdict == StageVerdict.partial
        assert e.confidence == 0.55
        assert e.notes == "primary reporter unverified"

    def test_errored_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.errored(error_type="HTTPError", notes="429 rate-limited")
        e = b.entries()[0]
        assert e.verdict == StageVerdict.errored
        assert e.confidence is None
        assert e.raw_response_summary == {"error_type": "HTTPError"}
        assert e.notes == "429 rate-limited"


class TestResolutionPathBuilderOrdering:
    def test_multiple_stages_recorded_in_order(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.no_match(raw_response_summary={"clusters_returned": 0})
        with b.stage(StageName.opinion_search) as t:
            t.resolved(
                confidence=0.78,
                raw_response_summary={
                    "candidate_count": 3, "best_score": 0.78,
                    "best_case_name": "Foo v. Bar", "best_cluster_id": 100,
                },
            )
        entries = b.entries()
        assert [e.stage for e in entries] == [
            StageName.citation_lookup, StageName.opinion_search,
        ]
        assert [e.verdict for e in entries] == [
            StageVerdict.no_match, StageVerdict.resolved,
        ]


class TestResolutionPathBuilderTiming:
    def test_elapsed_ms_records_block_duration(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.opinion_search) as t:
            time.sleep(0.02)
            t.no_match(raw_response_summary={"candidate_count": 0})
        e = b.entries()[0]
        assert e.elapsed_ms >= 15   # generous lower bound for 20ms sleep


class TestResolutionPathBuilderExceptionPropagation:
    def test_exception_inside_block_still_records_entry(self):
        """If the caller doesn't catch and convert, the builder still
        appends an entry (the finally runs) and the exception propagates.
        Verifier code is expected to catch + token.errored() instead, but
        defensive behavior should not silently drop entries either way."""
        b = ResolutionPathBuilder()
        with pytest.raises(RuntimeError):
            with b.stage(StageName.citation_lookup) as t:
                raise RuntimeError("boom")
        entries = b.entries()
        assert len(entries) == 1
        # Default verdict when caller never set one — for debuggability,
        # this should be a clear indicator that something went wrong.
        assert entries[0].verdict == StageVerdict.errored
        assert entries[0].notes is not None and "RuntimeError" in entries[0].notes
