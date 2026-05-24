# tests/test_cache_roundtrip.py
"""Phase 2: VerificationResult resolution_path survives the cache.

cache.py already serializes path entries (Phase 1 Task 2). Phase 2's
richer entries (multiple stages, raw_response_summary keys, errored
verdicts) need explicit round-trip coverage so future cache changes
don't silently drop them.
"""
from __future__ import annotations

import json
from pathlib import Path

from citation_verifier.cache import VerificationCache
from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)


def _make_multi_stage_result() -> VerificationResult:
    return VerificationResult(
        citation_as_written="Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
        parsed_citation=None,
        status=Status.VERIFIED,
        final_ids=FinalIds(
            cluster_id=200,
            opinion_id=None,
            docket_id=None,
            recap_document_id=None,
            absolute_url="https://www.courtlistener.com/opinion/200/",
            text_source=TextSource.opinion_plain_text,
        ),
        resolution_path=[
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={"text": "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)"},
                raw_response_summary={"clusters_returned": 0},
                verdict=StageVerdict.no_match,
                confidence=None,
                notes=None,
                elapsed_ms=42,
            ),
            ResolutionPathEntry(
                stage=StageName.opinion_search,
                query={"q": "Foo v. Bar", "court": "ca1", "filed_after": "2019-01-01", "filed_before": "2021-12-31"},
                raw_response_summary={
                    "candidate_count": 3, "best_score": 0.78,
                    "best_case_name": "Foo v. Bar", "best_cluster_id": 200,
                },
                verdict=StageVerdict.resolved,
                confidence=0.78,
                notes="Date close: cited 2020 vs filed 2020-06-15",
                elapsed_ms=180,
            ),
        ],
        warnings=[Warning(
            category=WarningCategory.date_close_not_exact,
            message="Date close: cited 2020 vs filed 2020-06-15",
            details=None,
        )],
        gates_failed=[],
        timing={"total_ms": 222},
        cache_hit=False,
    )


def test_resolution_path_survives_cache_round_trip(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache = VerificationCache(path=cache_path)
    original = _make_multi_stage_result()

    cache.put(original.citation_as_written, original)
    hydrated = cache.get(original.citation_as_written)

    assert hydrated is not None
    # Path length, stages, verdicts preserved
    assert len(hydrated.resolution_path) == 2
    assert [e.stage for e in hydrated.resolution_path] == [
        StageName.citation_lookup, StageName.opinion_search,
    ]
    assert [e.verdict for e in hydrated.resolution_path] == [
        StageVerdict.no_match, StageVerdict.resolved,
    ]
    # raw_response_summary keys and values preserved
    assert hydrated.resolution_path[1].raw_response_summary["best_score"] == 0.78
    assert hydrated.resolution_path[1].raw_response_summary["best_case_name"] == "Foo v. Bar"
    # confidence, notes, elapsed_ms preserved
    assert hydrated.resolution_path[1].confidence == 0.78
    assert hydrated.resolution_path[1].notes == "Date close: cited 2020 vs filed 2020-06-15"
    assert hydrated.resolution_path[1].elapsed_ms == 180
    # headline_confidence accessor still works after hydration
    assert hydrated.headline_confidence == 0.78


def test_errored_stage_survives_cache_round_trip(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache = VerificationCache(path=cache_path)
    original = VerificationResult(
        citation_as_written="x",
        parsed_citation=None,
        status=Status.NOT_FOUND,
        final_ids=FinalIds(None, None, None, None, None, None),
        resolution_path=[
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={"text": "x"},
                raw_response_summary={"error_type": "ConnectionError"},
                verdict=StageVerdict.errored,
                confidence=None,
                notes="ConnectionError: network down",
                elapsed_ms=100,
            ),
        ],
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )
    cache.put(original.citation_as_written, original)
    hydrated = cache.get(original.citation_as_written)
    assert hydrated is not None
    assert hydrated.resolution_path[0].verdict == StageVerdict.errored
    assert hydrated.resolution_path[0].raw_response_summary == {"error_type": "ConnectionError"}
    assert hydrated.resolution_path[0].notes == "ConnectionError: network down"
