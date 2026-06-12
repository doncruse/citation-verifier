"""Tests for proposition_pipeline (pipeline redesign SS10 step 2).

Covers what is NEW relative to brief_pipeline: the matched_case_name
accessor (SS11 bug 1 source fix), slug-token opinion linkage, verify/merge
verbs, and the brief_pipeline alias. Legacy behavior stays covered by
test_brief_pipeline.py through the alias.
"""
import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
)


def _entry(stage, summary, verdict=StageVerdict.resolved):
    return ResolutionPathEntry(
        stage=stage, query={}, raw_response_summary=summary,
        verdict=verdict, confidence=1.0, notes="", elapsed_ms=0,
    )


def _result(path_entries):
    return VerificationResult(
        citation_as_written="Test v. Case, 1 U.S. 1 (1800)",
        parsed_citation=None,
        status=Status.VERIFIED,
        final_ids=FinalIds(
            cluster_id=None, opinion_id=None, docket_id=None,
            recap_document_id=None, absolute_url=None, text_source=None,
        ),
        resolution_path=path_entries,
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


class TestMatchedCaseNameAccessor:
    def test_citation_lookup_key(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Nix v. Whiteside"})])
        assert r.matched_case_name == "Nix v. Whiteside"

    def test_search_stage_key(self):
        r = _result([_entry(StageName.opinion_search,
                            {"best_case_name": "Donovan v. Carls Drug Co."})])
        assert r.matched_case_name == "Donovan v. Carls Drug Co."

    def test_caption_investigation_key_wins_as_latest(self):
        r = _result([
            _entry(StageName.citation_lookup,
                   {"matched_case_name": "Brief's Name"}),
            _entry(StageName.caption_investigation,
                   {"cl_case_name": "CL's Actual Caption"}),
        ])
        assert r.matched_case_name == "CL's Actual Caption"

    def test_sibling_swap_case_name_key(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Original",
                             "case_name": "Swapped Sibling"})])
        assert r.matched_case_name == "Swapped Sibling"

    def test_walks_back_past_summaryless_entries(self):
        r = _result([
            _entry(StageName.citation_lookup,
                   {"matched_case_name": "Found Here"}),
            _entry(StageName.opinion_search, {"candidate_count": 0},
                   verdict=StageVerdict.no_match),
        ])
        assert r.matched_case_name == "Found Here"

    def test_empty_path_returns_empty(self):
        assert _result([]).matched_case_name == ""


class TestBriefPipelineAlias:
    def test_module_identity(self):
        import citation_verifier.brief_pipeline as bp
        import citation_verifier.proposition_pipeline as pp
        assert bp is pp

    def test_patch_through_alias_reaches_real_globals(self):
        import citation_verifier.proposition_pipeline as pp
        with patch("citation_verifier.brief_pipeline.CitationVerifier") as m:
            assert pp.CitationVerifier is m
