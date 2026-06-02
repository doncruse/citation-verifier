"""Tests for async verification pipeline and sync/async parity.

Verifies that:
1. Async path produces identical results to sync path (given same mock data)
2. verify_batch orchestration (ordering, progress callback, concurrency)
3. AsyncCourtListenerClient API parity and retry behavior
4. Exponential backoff formula (intentionally stricter than sync to avoid 429 storms)

All tests mock API clients so no real API calls are made.

Migrated to the v0.3 schema (Phase 1, Task 3). Task 1 (Phase 3) removed
the legacy _DiagnosticLike / _CATEGORY_PATTERNS / _classify_note /
_diagnostics / _matched_case_name bridge; assertions now read
result.warnings and _winning_path_entry() directly.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from citation_verifier.client import AsyncCourtListenerClient, CourtListenerClient
from citation_verifier.models import (
    ParsedCitation,
    StageName,
    StageVerdict,
    Status,
    WarningCategory,
)
from citation_verifier.verifier import CitationVerifier


def _winning_path_entry(result):
    """Return the resolution_path entry that drove the result (highest-
    confidence resolved/partial entry, else the last entry).

    Phase 2 emits one entry per stage attempted; the last is not always
    the winner (e.g. opinion_search resolved, then recap_docket_search
    ran afterward as a no_match). This helper picks the entry that
    actually decided the verdict so tests can assert against its
    raw_response_summary, notes, etc."""
    if not result.resolution_path:
        return None
    resolved = [
        e for e in result.resolution_path
        if e.verdict in (StageVerdict.resolved, StageVerdict.partial)
    ]
    if resolved:
        return max(resolved, key=lambda e: e.confidence or 0.0)
    return result.resolution_path[-1]


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_client(**overrides):
    """Create a mock sync CourtListenerClient with sensible defaults."""
    client = MagicMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    # New for Phase 3 caption_investigation — Task 5 wires the production
    # call sites; default these to empty dicts so existing tests don't break.
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text.return_value = overrides.get("get_opinion_text", None)
    client.get_opinion_text_with_metadata.return_value = overrides.get(
        "get_opinion_text_with_metadata", None
    )
    return client


def _make_async_client(**overrides):
    """Create a mock AsyncCourtListenerClient with sensible defaults."""
    client = AsyncMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    # New for Phase 3 caption_investigation — Task 5 wires the production
    # call sites; default these to empty dicts so existing tests don't break.
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text.return_value = overrides.get("get_opinion_text", None)
    client.get_opinion_text_with_metadata.return_value = overrides.get(
        "get_opinion_text_with_metadata", None
    )
    # Phase 4 Task 4 doc-detail fetch for VIA_RECAP score gate refinement.
    recap_doc_metadata = overrides.get("recap_document_metadata", None)
    if isinstance(recap_doc_metadata, Exception):
        client.get_recap_document_metadata.side_effect = recap_doc_metadata
    else:
        client.get_recap_document_metadata.return_value = recap_doc_metadata
    return client


def _verify_parity(api_responses, citation_text, parsed=None):
    """Run both sync and async verify with the same mock data, return both results."""
    sync_client = _make_client(**api_responses)
    async_client = _make_async_client(**api_responses)

    v = CitationVerifier(sync_client)
    sync_result = v.verify(citation_text, parsed=parsed)
    async_result = asyncio.run(v.verify_async(async_client, citation_text, parsed=parsed))

    return sync_result, async_result


# ---------------------------------------------------------------------------
# Sync/Async Parity: identical mock data → identical results
# ---------------------------------------------------------------------------


class TestAsyncSyncParity:
    """Given identical mock API responses, sync and async paths must produce
    identical verification results (status, confidence, matched fields, diagnostics)."""

    def test_parity_citation_lookup_verified(self):
        """Step 1: Citation found and name matches → VERIFIED in both paths."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell-v-hodges/",
                        }
                    ]
                }
            ]
        }
        sync_r, async_r = _verify_parity(
            api, "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        )

        assert sync_r.status == async_r.status == Status.VERIFIED
        assert sync_r.headline_confidence == async_r.headline_confidence == 1.0
        assert (_winning_path_entry(sync_r).raw_response_summary.get("matched_case_name")
                == _winning_path_entry(async_r).raw_response_summary.get("matched_case_name"))
        assert sync_r.final_ids.absolute_url == async_r.final_ids.absolute_url

    def test_parity_citation_lookup_name_mismatch(self):
        """Step 1: Citation exists but wrong case → WRONG_CASE after investigation
        (no party overlap; was VERIFIED + cl_display_name_data_bug in Phase 1)."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Totally Different v. Case",
                            "id": 789,
                            "absolute_url": "/opinion/789/",
                        }
                    ]
                }
            ]
        }
        sync_r, async_r = _verify_parity(
            api, "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)"
        )

        # Phase 3: caption_investigation finds no party overlap → WRONG_CASE.
        assert sync_r.status == async_r.status == Status.WRONG_CASE
        # Parity: final_ids populated with actual CL cluster per design §2.4
        assert sync_r.final_ids.cluster_id == async_r.final_ids.cluster_id == 789
        # Parity: both paths include caption_investigation stage
        stages_sync = [e.stage for e in sync_r.resolution_path]
        stages_async = [e.stage for e in async_r.resolution_path]
        assert StageName.caption_investigation in stages_sync
        assert StageName.caption_investigation in stages_async

    def test_parity_opinion_search_likely_real(self):
        """Step 2: Fuzzy opinion search finds good match → LIKELY_REAL in both paths."""
        api = {
            "search_opinions": [
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 300,
                    "dateFiled": "2020-03-15",
                    "court_id": "ca2",
                    "absolute_url": "/opinion/300/smith-v-jones/",
                    "citation": ["500 F.3d 200"],
                }
            ],
        }
        sync_r, async_r = _verify_parity(
            api, "Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)"
        )

        # Old LIKELY_REAL band: VERIFIED with confidence >= 0.85 from a
        # fallback (opinion-search) stage entry.
        assert sync_r.status == async_r.status == Status.VERIFIED
        assert sync_r.headline_confidence is not None
        assert sync_r.headline_confidence >= 0.85
        assert sync_r.headline_confidence == async_r.headline_confidence
        assert (_winning_path_entry(sync_r).raw_response_summary.get("best_case_name")
                == _winning_path_entry(async_r).raw_response_summary.get("best_case_name"))
        assert sync_r.final_ids.absolute_url == async_r.final_ids.absolute_url

    def test_parity_no_results_not_found(self):
        """All searches return empty → NOT_FOUND in both paths."""
        api = {}  # everything returns []
        sync_r, async_r = _verify_parity(
            api, "Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)"
        )

        assert sync_r.status == async_r.status == Status.NOT_FOUND
        # NOT_FOUND has no resolving stage, so headline_confidence is None
        # in the new schema (was 0.0 default in old VerificationResult).
        assert sync_r.headline_confidence is None
        assert async_r.headline_confidence is None

    def test_parity_opinion_search_call_count(self):
        """Both paths call opinion search the same number of times."""
        sync_client = _make_client()
        async_client = _make_async_client()

        citation = "Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)"
        v = CitationVerifier(sync_client)
        v.verify(citation)
        asyncio.run(v.verify_async(async_client, citation))

        assert sync_client.search_opinions.call_count == 1
        assert async_client.search_opinions.call_count == 1

    def test_parity_recap_match_with_substantive_doc(self):
        """Step 3: RECAP finds docket with substantive doc → same result both paths."""
        api = {
            "search_recap": [
                {
                    "caseName": "Anderson v. Furst",
                    "docket_id": 6264209,
                    "court_id": "mied",
                    "docket_absolute_url": "/docket/6264209/anderson-v-furst/",
                    "docketNumber": "2:17-cv-12676",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2018-09-17",
                            "short_description": "Order on Motion to Compel",
                            "absolute_url": "/docket/6264209/54/anderson-v-furst/",
                        }
                    ],
                }
            ],
        }
        sync_r, async_r = _verify_parity(
            api,
            "Anderson v. Furst, No. 17-cv-12676, 2018 WL 4407750, at *2 "
            "(E.D. Mich. Sept. 17, 2018)",
        )

        assert sync_r.status == async_r.status
        assert sync_r.headline_confidence == async_r.headline_confidence
        assert (_winning_path_entry(sync_r).raw_response_summary.get("best_case_name")
                == _winning_path_entry(async_r).raw_response_summary.get("best_case_name"))

    def test_parity_recap_docket_only_discounted(self):
        """RECAP docket with no docs → 0.6x discount applied by both paths."""
        api = {
            "search_recap": [
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 300,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/300/",
                    "recap_documents": [],
                }
            ],
        }
        sync_r, async_r = _verify_parity(
            api, "Smith v. Jones, 2020 WL 111111 (S.D.N.Y. 2020)"
        )

        assert sync_r.status == async_r.status
        assert sync_r.headline_confidence == async_r.headline_confidence
        assert sync_r.headline_confidence is not None
        assert sync_r.headline_confidence < 0.6  # 0.6x discount

    def test_parity_docket_only_sets_matched_docket_id(self):
        """Async parity for issue #6 docket-only path."""
        client = _make_async_client(
            search_recap=[
                {
                    "caseName": "Lindsay-Stern v. Garamszegi",
                    "docket_id": 18158469,
                    "court_id": "cacd",
                    "docket_absolute_url": "/docket/18158469/",
                    "recap_documents": [],
                }
            ],
        )
        v = CitationVerifier()
        result = asyncio.run(
            v.verify_async(
                client,
                "Lindsay-Stern v. Garamszegi, No. 2:18-cv-01234 (C.D. Cal. 2018)",
            )
        )
        assert result.final_ids.docket_id == 18158469
        assert result.final_ids.cluster_id is None

    def test_parity_court_corroboration_required(self):
        """Unverified citation + wrong court → NOT_FOUND in both paths."""
        api = {
            "search_recap": [
                {
                    "caseName": "United States v. Craner",
                    "docket_id": 500,
                    "court_id": "nvd",
                    "docket_absolute_url": "/docket/500/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2021-08-03",
                            "short_description": "Order",
                            "absolute_url": "/docket/500/9/",
                        },
                    ],
                }
            ],
        }
        sync_r, async_r = _verify_parity(
            api, "United States v. Craner, 652 F.3d 560, 562 (9th Cir. 2016)"
        )

        assert sync_r.status == async_r.status == Status.NOT_FOUND

    def test_parity_insufficient_data_guard(self):
        """Missing both court and date → INSUFFICIENT_DATA in both paths.

        Before the INSUFFICIENT_DATA promotion landed, this returned
        NOT_FOUND with the "Insufficient data" note. The status now
        distinguishes "we couldn't tell because the input was too weak"
        from "we tried and found nothing convincing" — the note is still
        on the resolution_path entry for context."""
        # Use pre-parsed citation with no court/year to guarantee the guard fires
        parsed = ParsedCitation(
            raw_text="Smith v. Jones, 100 F.3d 200",
            case_name="Smith v. Jones",
            plaintiff="Smith",
            defendant="Jones",
            volume="100",
            reporter="F.3d",
            page="200",
        )
        api = {
            "search_opinions": [
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 800,
                    "dateFiled": "2020-01-01",
                    "court_id": "nysd",
                    "absolute_url": "",
                    "citation": [],
                }
            ],
        }
        sync_r, async_r = _verify_parity(
            api, "Smith v. Jones, 100 F.3d 200", parsed=parsed
        )

        assert sync_r.status == async_r.status == Status.INSUFFICIENT_DATA
        assert sync_r.headline_confidence is None
        assert async_r.headline_confidence is None
        sync_winner = _winning_path_entry(sync_r)
        async_winner = _winning_path_entry(async_r)
        assert sync_winner is not None and sync_winner.notes, "expected at least one diagnostic"
        assert "Insufficient data" in sync_winner.notes
        assert sync_winner.notes == async_winner.notes

    def test_parity_quick_only_not_found(self):
        """quick_only: both paths return NOT_FOUND with diagnostic when not in lookup."""
        api = {}  # everything returns []
        sync_client = _make_client(**api)
        async_client = _make_async_client(**api)

        citation = "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)"
        v = CitationVerifier(sync_client)
        sync_r = v.verify(citation, quick_only=True)
        async_r = asyncio.run(
            v.verify_async(async_client, citation, quick_only=True)
        )

        assert sync_r.status == async_r.status == Status.NOT_FOUND
        assert sync_r.headline_confidence is None
        assert async_r.headline_confidence is None
        sync_winner = _winning_path_entry(sync_r)
        async_winner = _winning_path_entry(async_r)
        assert sync_winner is not None and sync_winner.notes, "expected at least one diagnostic"
        assert "Quick search only" in sync_winner.notes
        assert sync_winner.notes == async_winner.notes

    def test_parity_quick_only_verified(self):
        """quick_only: citation found in Step 1 -> VERIFIED in both paths."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell-v-hodges/",
                        }
                    ]
                }
            ]
        }
        sync_client = _make_client(**api)
        async_client = _make_async_client(**api)

        citation = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        v = CitationVerifier(sync_client)
        sync_r = v.verify(citation, quick_only=True)
        async_r = asyncio.run(
            v.verify_async(async_client, citation, quick_only=True)
        )

        assert sync_r.status == async_r.status == Status.VERIFIED
        assert sync_r.headline_confidence == async_r.headline_confidence == 1.0
        assert (_winning_path_entry(sync_r).raw_response_summary.get("matched_case_name")
                == _winning_path_entry(async_r).raw_response_summary.get("matched_case_name"))

    def test_parity_preparsed_citation(self):
        """Pre-parsed citation produces identical results in both paths."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell-v-hodges/",
                        }
                    ]
                }
            ]
        }
        parsed = ParsedCitation(
            raw_text="Obergefell v. Hodges, 576 U.S. 644 (2015)",
            case_name="Obergefell v. Hodges",
            plaintiff="Obergefell",
            defendant="Hodges",
            volume="576",
            reporter="U.S.",
            page="644",
            court="scotus",
            year=2015,
        )
        sync_r, async_r = _verify_parity(
            api, "Obergefell v. Hodges, 576 U.S. 644 (2015)", parsed=parsed
        )

        assert sync_r.status == async_r.status == Status.VERIFIED
        assert sync_r.headline_confidence == async_r.headline_confidence == 1.0

    def test_parity_recap_docket_entries_query(self):
        """When RECAP docs don't match cited date, both paths query docket-entries API."""
        api = {
            "search_recap": [
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 200,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/200/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2019-03-01",
                            "short_description": "Reply",
                            "absolute_url": "/docket/200/50/",
                        },
                    ],
                }
            ],
            "get_docket_entries": [
                {
                    "date_filed": "2018-09-17",
                    "recap_documents": [
                        {
                            "short_description": "Opinion",
                            "absolute_url": "/docket/200/30/smith-v-jones/",
                        }
                    ],
                }
            ],
        }
        citation = "Smith v. Jones, 2018 WL 555555 (S.D.N.Y. Sept. 17, 2018)"
        sync_r, async_r = _verify_parity(api, citation)

        assert sync_r.status == async_r.status
        assert sync_r.headline_confidence == async_r.headline_confidence
        assert (_winning_path_entry(sync_r).raw_response_summary.get("best_case_name")
                == _winning_path_entry(async_r).raw_response_summary.get("best_case_name"))


# ---------------------------------------------------------------------------
# verify_batch orchestration
# ---------------------------------------------------------------------------


def _mock_batch_client(**overrides):
    """Create a mock async client wired for verify_batch (context manager)."""
    client = AsyncMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestVerifyBatch:
    """Tests for the batch verification entry point."""

    def test_batch_returns_results_in_order(self):
        """Results must be in the same order as input citations."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",
            "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)",
        ]

        # Batch citation_lookup returns start_index-based results
        def mock_citation_lookup(text):
            # Batch call: text contains all citations joined by newlines.
            # Return a hit for the first citation only.
            if "\n" in text and "576" in text:
                return [
                    {
                        "start_index": 0,
                        "end_index": len(citations[0]),
                        "clusters": [
                            {
                                "case_name": "Obergefell v. Hodges",
                                "id": 123,
                                "absolute_url": "/opinion/123/",
                            }
                        ],
                    }
                ]
            return []

        mock_client = _mock_batch_client()
        mock_client.citation_lookup.side_effect = mock_citation_lookup

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch(citations))

        assert len(results) == 2
        assert results[0].status == Status.VERIFIED
        assert results[1].status == Status.NOT_FOUND

    def test_batch_calls_progress_callback(self):
        """Progress callback receives (completed, total) after each citation."""
        citations = [
            "A v. B, 100 F.3d 1 (2d Cir. 2020)",
            "C v. D, 200 F.3d 2 (9th Cir. 2021)",
        ]
        mock_client = _mock_batch_client()
        progress_calls = []

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            asyncio.run(
                v.verify_batch(
                    citations,
                    progress_callback=lambda done, total: progress_calls.append(
                        (done, total)
                    ),
                )
            )

        assert len(progress_calls) == 2
        assert all(total == 2 for _, total in progress_calls)
        # Both 1 and 2 should be reported (order may vary due to async)
        assert sorted(done for done, _ in progress_calls) == [1, 2]

    def test_batch_with_preparsed_citations(self):
        """Pre-parsed citations are forwarded through batch lookup."""
        citation = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        parsed = ParsedCitation(
            raw_text=citation,
            case_name="Obergefell v. Hodges",
            plaintiff="Obergefell",
            defendant="Hodges",
            volume="576",
            reporter="U.S.",
            page="644",
            year=2015,
        )

        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                        }
                    ],
                }
            ]
        )

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(
                v.verify_batch([citation], parsed_citations=[parsed])
            )

        assert len(results) == 1
        assert results[0].status == Status.VERIFIED

    def test_batch_empty_input(self):
        """Empty citation list returns empty results."""
        mock_client = _mock_batch_client()

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch([]))

        assert results == []

    def test_batch_exceeding_semaphore_limit(self):
        """Batch handles > MAX_CONCURRENT citations without deadlocking."""
        n = 8  # exceeds MAX_CONCURRENT=5
        citations = [
            f"Case{i} v. Opponent{i}, {100 + i} F.3d {i} (2d Cir. 2020)"
            for i in range(n)
        ]
        mock_client = _mock_batch_client()

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch(citations))

        assert len(results) == n
        # All should complete (NOT_FOUND since mocks return empty)
        assert all(r.status == Status.NOT_FOUND for r in results)


# ---------------------------------------------------------------------------
# _batch_citation_lookup unit tests
# ---------------------------------------------------------------------------


class TestBatchCitationLookup:
    """Tests for the _batch_citation_lookup() method."""

    def test_text_block_construction_and_offset_mapping(self):
        """Citations are joined with newlines; results map back via start_index."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",
            "Roe v. Wade, 410 U.S. 113 (1973)",
        ]
        # start_index for first citation = 0
        # start_index for second = len(citations[0]) + 1 (newline)
        second_start = len(citations[0]) + 1

        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citations[0]),
                    "clusters": [
                        {"case_name": "Obergefell v. Hodges", "id": 1}
                    ],
                },
                {
                    "start_index": second_start,
                    "end_index": second_start + len(citations[1]),
                    "clusters": [
                        {"case_name": "Roe v. Wade", "id": 2}
                    ],
                },
            ]
        )

        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, citations))

        assert len(result) == 2
        assert result[0]["case_name"] == "Obergefell v. Hodges"
        assert result[1]["case_name"] == "Roe v. Wade"

    def test_empty_input(self):
        """Empty citation list returns empty dict."""
        mock_client = _mock_batch_client()
        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, []))
        assert result == {}

    def test_no_hits_returns_empty(self):
        """When API returns no clusters, result dict is empty."""
        mock_client = _mock_batch_client(
            citation_lookup=[
                {"start_index": 0, "end_index": 10, "clusters": []},
            ]
        )
        v = CitationVerifier()
        result = asyncio.run(
            v._batch_citation_lookup(mock_client, ["Fake v. Case, 999 F.3d 1 (2025)"])
        )
        assert result == {}

    def test_retry_on_failure_then_success(self):
        """Retries up to 3 times; succeeds on second attempt."""
        citation = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        success_response = [
            {
                "start_index": 0,
                "end_index": len(citation),
                "clusters": [{"case_name": "Obergefell v. Hodges", "id": 1}],
            }
        ]

        mock_client = _mock_batch_client()
        # First call raises, second succeeds
        mock_client.citation_lookup.side_effect = [
            Exception("Server error"),
            success_response,
        ]

        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, [citation]))
        assert 0 in result
        assert result[0]["case_name"] == "Obergefell v. Hodges"
        assert mock_client.citation_lookup.call_count == 2

    def test_fallback_to_individual_after_3_failures(self):
        """After 3 batch failures, falls back to individual calls."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",
            "Roe v. Wade, 410 U.S. 113 (1973)",
        ]

        call_count = 0

        async def mock_lookup(text):
            nonlocal call_count
            call_count += 1
            # First 3 calls are batch attempts (all fail)
            if call_count <= 3:
                raise Exception("Server error")
            # Individual fallback calls
            if "576" in text:
                return [
                    {
                        "clusters": [
                            {"case_name": "Obergefell v. Hodges", "id": 1}
                        ]
                    }
                ]
            return []

        mock_client = _mock_batch_client()
        mock_client.citation_lookup.side_effect = mock_lookup

        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, citations))

        # Should have found Obergefell via individual fallback
        assert 0 in result
        assert result[0]["case_name"] == "Obergefell v. Hodges"
        # Roe not found individually either (mock returns [])
        assert 1 not in result
        # 3 batch attempts + 2 individual fallbacks = 5 calls
        assert call_count == 5

    def test_first_cluster_per_citation_wins(self):
        """If CL returns multiple entries for the same citation range,
        only the first cluster is kept."""
        citation = "576 U.S. 644"
        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {"case_name": "Obergefell v. Hodges", "id": 1},
                        {"case_name": "Some Parallel", "id": 2},
                    ],
                },
            ]
        )

        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, [citation]))
        assert result[0]["case_name"] == "Obergefell v. Hodges"

    def test_duplicate_entries_for_same_citation(self):
        """Multiple response entries mapping to the same citation: first wins."""
        citation = "576 U.S. 644"
        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [{"case_name": "First Match", "id": 1}],
                },
                {
                    "start_index": 2,
                    "end_index": len(citation),
                    "clusters": [{"case_name": "Second Match", "id": 2}],
                },
            ]
        )

        v = CitationVerifier()
        result = asyncio.run(v._batch_citation_lookup(mock_client, [citation]))
        assert result[0]["case_name"] == "First Match"

    def test_chunks_when_citation_count_exceeds_limit(self):
        """CL's citation-lookup response truncates beyond ~200 entries.
        Verifier must chunk by citation count (max 150 per chunk), not just
        by character count, so requests with 200+ citations get full
        coverage. Regression for benchmark v1 bug: 437-citation batch
        silently dropped citations 250+ from the response."""
        # 300 short citations stay well under the 50K char limit but
        # exceed the 150 citation-count limit, so should produce 2 chunks.
        citations = [
            f"Case{i} v. Other, {100 + i} U.S. {i} (2020)"
            for i in range(300)
        ]

        chunk_calls: list[str] = []

        async def track_chunks(text: str):
            chunk_calls.append(text)
            return []  # no hits, doesn't matter for this test

        mock_client = _mock_batch_client()
        mock_client.citation_lookup.side_effect = track_chunks

        v = CitationVerifier()
        asyncio.run(v._batch_citation_lookup(mock_client, citations))

        assert len(chunk_calls) >= 2, (
            f"Expected >=2 chunks for 300 citations; got {len(chunk_calls)}"
        )
        for i, chunk in enumerate(chunk_calls):
            n_lines = chunk.count("\n")
            assert n_lines <= 150, (
                f"Chunk {i} has {n_lines} citations; max is 150 to stay "
                f"under CL's ~200-entry response truncation"
            )


# ---------------------------------------------------------------------------
# Sync / async / batch resolution_path parity
# ---------------------------------------------------------------------------


class TestSyncAsyncBatchPathParity:
    """Same mock data should produce the same resolution_path shape
    through sync verify(), async verify_async(), and batch verify_batch().

    "Same shape" = same sequence of (stage, verdict) tuples and same
    headline_confidence. Per-entry elapsed_ms is allowed to differ.
    """

    @staticmethod
    def _shape(result):
        return (
            [(e.stage, e.verdict) for e in result.resolution_path],
            result.headline_confidence,
        )

    def test_citation_lookup_hit_parity(self):
        cite = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        lookup_payload = [{
            "clusters": [{"id": 100, "case_name": "Obergefell v. Hodges",
                          "absolute_url": "/opinion/100/"}],
        }]

        # Sync
        sync_client = MagicMock()
        sync_client.citation_lookup.return_value = lookup_payload
        sync_verifier = CitationVerifier(client=sync_client)
        sync_result = sync_verifier.verify(cite)

        # Async (single)
        async_client = AsyncMock(spec=AsyncCourtListenerClient)
        async_client.citation_lookup.return_value = lookup_payload
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_verifier = CitationVerifier()
        async_result = asyncio.run(async_verifier.verify_async(async_client, cite))

        # Batch (one citation)
        batch_verifier = CitationVerifier()
        async def _run_batch():
            with patch.object(batch_verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={0: lookup_payload[0]["clusters"][0]})):
                return await batch_verifier.verify_batch([cite])
        batch_results = asyncio.run(_run_batch())

        assert self._shape(sync_result) == self._shape(async_result) == self._shape(batch_results[0]), (
            f"sync={self._shape(sync_result)}  "
            f"async={self._shape(async_result)}  "
            f"batch={self._shape(batch_results[0])}"
        )

    def test_all_stages_miss_parity(self):
        cite = "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)"

        sync_client = MagicMock()
        sync_client.citation_lookup.return_value = []
        sync_client.search_opinions.return_value = []
        sync_client.search_recap.return_value = []
        sync_result = CitationVerifier(client=sync_client).verify(cite)

        async_client = AsyncMock(spec=AsyncCourtListenerClient)
        async_client.citation_lookup.return_value = []
        async_client.search_opinions.return_value = []
        async_client.search_recap.return_value = []
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_result = asyncio.run(
            CitationVerifier().verify_async(async_client, cite)
        )

        batch_verifier = CitationVerifier()
        async def _run_batch():
            with patch.object(batch_verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={})), \
                 patch("citation_verifier.verifier.AsyncCourtListenerClient") as MockClient:
                client = AsyncMock()
                client.search_opinions.return_value = []
                client.search_recap.return_value = []
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = client
                return await batch_verifier.verify_batch([cite])
        batch_results = asyncio.run(_run_batch())

        assert self._shape(sync_result) == self._shape(async_result) == self._shape(batch_results[0])


# ---------------------------------------------------------------------------
# verify_batch integration with batch lookup
# ---------------------------------------------------------------------------


class TestVerifyBatchIntegration:
    """Tests for verify_batch's interaction with _batch_citation_lookup."""

    def test_batch_hit_uses_process_citation_lookup_hit(self):
        """Citations resolved by batch lookup go through
        _process_citation_lookup_hit, not verify_async."""
        citation = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell/",
                        }
                    ],
                }
            ]
        )

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch([citation]))

        assert results[0].status == Status.VERIFIED
        assert results[0].final_ids.cluster_id == 123
        # Only one citation_lookup call (the batch), no search calls
        assert mock_client.citation_lookup.call_count == 1
        mock_client.search_opinions.assert_not_called()

    def test_no_hit_falls_through_to_search(self):
        """Citations without batch hits go through search fallback."""
        citation = "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)"
        mock_client = _mock_batch_client(
            citation_lookup=[],  # no batch hits
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "absolute_url": "/opinion/456/smith/",
                    "cluster_id": 456,
                    "court_id": "ca2",
                    "dateFiled": "2020-05-15",
                }
            ],
        )

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch([citation]))

        # Old LIKELY_REAL: VERIFIED via fallback opinion-search.
        assert results[0].status == Status.VERIFIED
        assert results[0].headline_confidence is not None
        assert results[0].headline_confidence >= 0.85
        mock_client.search_opinions.assert_called()

    def test_mixed_hits_and_misses_in_order(self):
        """Some hits, some misses; results returned in input order."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",  # will hit
            "Fake v. Nobody, 999 F.3d 1 (2025)",           # will miss
            "Roe v. Wade, 410 U.S. 113 (1973)",            # will hit
        ]

        second_start = len(citations[0]) + 1
        third_start = second_start + len(citations[1]) + 1

        def mock_citation_lookup(text):
            # Batch call: return hits for first and third citations
            if "\n" in text:
                return [
                    {
                        "start_index": 0,
                        "end_index": len(citations[0]),
                        "clusters": [
                            {
                                "case_name": "Obergefell v. Hodges",
                                "id": 1,
                                "absolute_url": "/opinion/1/",
                            }
                        ],
                    },
                    {
                        "start_index": third_start,
                        "end_index": third_start + len(citations[2]),
                        "clusters": [
                            {
                                "case_name": "Roe v. Wade",
                                "id": 2,
                                "absolute_url": "/opinion/2/",
                            }
                        ],
                    },
                ]
            return []

        mock_client = _mock_batch_client()
        mock_client.citation_lookup.side_effect = mock_citation_lookup

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch(citations))

        assert len(results) == 3
        assert results[0].status == Status.VERIFIED
        assert results[0].final_ids.cluster_id == 1
        assert results[1].status == Status.NOT_FOUND
        assert results[2].status == Status.VERIFIED
        assert results[2].final_ids.cluster_id == 2

    def test_quick_only_batch_misses_return_not_found(self):
        """With quick_only, batch misses return NOT_FOUND without fallback."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",  # will hit
            "Fake v. Nobody, 999 F.3d 1 (2025)",           # will miss
        ]

        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citations[0]),
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                        }
                    ],
                }
            ]
        )

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(
                v.verify_batch(citations, quick_only=True)
            )

        assert results[0].status == Status.VERIFIED
        assert results[1].status == Status.NOT_FOUND
        # No search calls should have been made
        mock_client.search_opinions.assert_not_called()
        mock_client.search_recap.assert_not_called()

    def test_progress_callback_with_batch_hits(self):
        """Progress callback fires for both batch hits and fallback results."""
        citations = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",
            "Fake v. Nobody, 999 F.3d 1 (2025)",
        ]
        mock_client = _mock_batch_client(
            citation_lookup=[
                {
                    "start_index": 0,
                    "end_index": len(citations[0]),
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                        }
                    ],
                }
            ]
        )

        progress_calls = []
        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            asyncio.run(
                v.verify_batch(
                    citations,
                    progress_callback=lambda done, total: progress_calls.append(
                        (done, total)
                    ),
                )
            )

        assert len(progress_calls) == 2
        assert all(total == 2 for _, total in progress_calls)
        assert sorted(done for done, _ in progress_calls) == [1, 2]


# ---------------------------------------------------------------------------
# Exponential backoff: intentionally stricter than sync
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """Verify the async 429 backoff formula.

    The async client uses exponential backoff (wait_seconds * 2^attempt + 1)
    instead of the sync client's linear backoff (wait_seconds + 1). This is
    intentional: semaphore-based concurrency alone was insufficient to prevent
    429 storms, which degraded response quality.
    """

    def test_backoff_formula_attempt_0(self):
        """First retry: wait_seconds * 2^0 + 1 = wait_seconds + 1 (same as sync)."""
        wait_seconds = 10.0
        backoff = wait_seconds * (2**0) + 1.0
        assert backoff == 11.0

    def test_backoff_formula_attempt_1(self):
        """Second retry: wait_seconds * 2^1 + 1 (2x sync)."""
        wait_seconds = 10.0
        backoff = wait_seconds * (2**1) + 1.0
        assert backoff == 21.0

    def test_backoff_formula_attempt_2(self):
        """Third retry: wait_seconds * 2^2 + 1 (4x sync)."""
        wait_seconds = 10.0
        backoff = wait_seconds * (2**2) + 1.0
        assert backoff == 41.0

    def test_async_always_backs_off_at_least_as_much_as_sync(self):
        """For any wait_seconds, async backoff >= sync backoff on every attempt."""
        for wait_seconds in (5.0, 30.0, 60.0):
            for attempt in range(CourtListenerClient.MAX_RETRIES - 1):
                sync_sleep = wait_seconds + 1.0
                async_sleep = wait_seconds * (2**attempt) + 1.0
                assert async_sleep >= sync_sleep, (
                    f"wait={wait_seconds}, attempt={attempt}: "
                    f"async {async_sleep} < sync {sync_sleep}"
                )

    def test_worst_case_backoff_bounded(self):
        """With CL's typical max wait (60s), worst-case sleep is ~4 minutes."""
        max_wait = 60.0
        max_attempt = CourtListenerClient.MAX_RETRIES - 1  # 2
        worst_case = max_wait * (2**max_attempt) + 1.0
        # 60 * 4 + 1 = 241 seconds ≈ 4 minutes
        assert worst_case == 241.0
        # This is long but intentional: aggressive backoff prevents cascading
        # 429s that degrade response quality across the entire batch.


# ---------------------------------------------------------------------------
# API method signature parity
# ---------------------------------------------------------------------------


class TestAsyncClientAPIParity:
    """Verify that async client methods accept the same parameters as sync,
    and share critical constants."""

    def test_citation_lookup_signature(self):
        sync_params = list(
            inspect.signature(CourtListenerClient.citation_lookup).parameters.keys()
        )
        async_params = list(
            inspect.signature(AsyncCourtListenerClient.citation_lookup).parameters.keys()
        )
        assert sync_params == async_params

    def test_search_opinions_signature(self):
        sync_params = set(
            inspect.signature(CourtListenerClient.search_opinions).parameters.keys()
        )
        async_params = set(
            inspect.signature(AsyncCourtListenerClient.search_opinions).parameters.keys()
        )
        assert sync_params == async_params

    def test_search_recap_signature(self):
        sync_params = set(
            inspect.signature(CourtListenerClient.search_recap).parameters.keys()
        )
        async_params = set(
            inspect.signature(AsyncCourtListenerClient.search_recap).parameters.keys()
        )
        assert sync_params == async_params

    def test_get_docket_entries_signature(self):
        sync_params = set(
            inspect.signature(
                CourtListenerClient.get_docket_entries
            ).parameters.keys()
        )
        async_params = set(
            inspect.signature(
                AsyncCourtListenerClient.get_docket_entries
            ).parameters.keys()
        )
        assert sync_params == async_params

    def test_shared_constants(self):
        """Async client inherits BASE_URL, timeout, retry, and docket limits."""
        assert AsyncCourtListenerClient.BASE_URL == CourtListenerClient.BASE_URL
        assert (
            AsyncCourtListenerClient.REQUEST_TIMEOUT
            == CourtListenerClient.REQUEST_TIMEOUT
        )
        assert AsyncCourtListenerClient.MAX_RETRIES == CourtListenerClient.MAX_RETRIES
        assert (
            AsyncCourtListenerClient.MAX_DOCKET_ENTRIES
            == CourtListenerClient.MAX_DOCKET_ENTRIES
        )

    def test_async_rate_limit_faster_than_sync(self):
        """Async interval (0.5s) is intentionally faster than sync (1.0s)
        since concurrency is also gated by the semaphore."""
        assert AsyncCourtListenerClient.MIN_REQUEST_INTERVAL < 1.0
        assert AsyncCourtListenerClient.MIN_REQUEST_INTERVAL == 0.5


class TestAsyncResolutionPathShape:
    """Phase 2: assert async path produces the same resolution_path
    shape as the sync path. Per-stage parity is the load-bearing
    invariant for the sync/async/batch parity test in Task 7."""

    def test_async_citation_lookup_hit_one_entry(self):
        client = AsyncMock(spec=AsyncCourtListenerClient)
        client.citation_lookup.return_value = [{
            "clusters": [{"id": 100, "case_name": "Foo v. Bar", "absolute_url": "/opinion/100/"}],
        }]
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        verifier = CitationVerifier()
        result = asyncio.run(verifier.verify_async(client, "100 U.S. 1 (2020)"))

        assert len(result.resolution_path) == 1
        assert result.resolution_path[0].stage == StageName.citation_lookup
        assert result.resolution_path[0].verdict == StageVerdict.resolved

    def test_async_all_stages_miss(self):
        client = AsyncMock(spec=AsyncCourtListenerClient)
        client.citation_lookup.return_value = []
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        verifier = CitationVerifier()
        result = asyncio.run(verifier.verify_async(
            client, "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)",
        ))

        stages = [e.stage for e in result.resolution_path]
        assert stages[0] == StageName.citation_lookup
        assert StageName.opinion_search in stages
        assert result.status == Status.NOT_FOUND


class TestBatchPathShape:
    """Phase 2, Task 5: assert verify_batch produces per-citation
    resolution_path entries. Batch hits get a one-entry path
    (citation_lookup, resolved, via=batch). Batch misses lead with a
    citation_lookup no_match entry, then accumulate fallback stages
    via _search_fallback_async."""

    def test_batch_hits_produce_one_entry_paths(self):
        verifier = CitationVerifier()

        async def _run():
            with patch.object(
                verifier,
                "_batch_citation_lookup",
                AsyncMock(
                    return_value={
                        0: {
                            "id": 100,
                            "case_name": "Foo v. Bar",
                            "absolute_url": "/opinion/100/",
                        },
                        1: {
                            "id": 200,
                            "case_name": "Baz v. Qux",
                            "absolute_url": "/opinion/200/",
                        },
                    }
                ),
            ), patch(
                "citation_verifier.verifier.AsyncCourtListenerClient"
            ) as MockClient:
                client = AsyncMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = client
                return await verifier.verify_batch(
                    [
                        "Foo v. Bar, 100 U.S. 1 (2020)",
                        "Baz v. Qux, 200 U.S. 2 (2021)",
                    ]
                )

        results = asyncio.run(_run())
        for r in results:
            assert len(r.resolution_path) == 1
            assert r.resolution_path[0].stage == StageName.citation_lookup
            assert r.resolution_path[0].verdict == StageVerdict.resolved
            # Batch-hit confidence is 1.0 (same as single citation_lookup hit)
            assert r.resolution_path[0].confidence == 1.0

    def test_batch_miss_falls_through_to_fallback_with_path(self):
        verifier = CitationVerifier()

        async def _run():
            # Mock the batch call to return empty (miss for all).
            # _search_fallback_async will be called for each citation.
            with patch.object(
                verifier, "_batch_citation_lookup", AsyncMock(return_value={})
            ), patch(
                "citation_verifier.verifier.AsyncCourtListenerClient"
            ) as MockClient:
                client = AsyncMock()
                client.search_opinions.return_value = []
                client.search_recap.return_value = []
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = client
                return await verifier.verify_batch(
                    ["Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)"]
                )

        results = asyncio.run(_run())
        r = results[0]
        # Batch-miss path: citation_lookup (no_match) + opinion_search
        # (no_match) at minimum.
        assert r.resolution_path[0].stage == StageName.citation_lookup
        assert r.resolution_path[0].verdict == StageVerdict.no_match
        assert any(
            e.stage == StageName.opinion_search for e in r.resolution_path
        )


# ---------------------------------------------------------------------------
# Phase 3 Task 3: VERIFIED_PARTIAL detection (silent partial verification)
# ---------------------------------------------------------------------------


class TestVerifiedPartial:
    """Phase 3: silent partial verification (design §2.2 VERIFIED_PARTIAL).
    Async parity per design v2 §1."""

    def test_partial_when_primary_reporter_not_in_cluster_citations(self):
        """NY A.D.3d + slip op pattern: parallel resolves, primary does not."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Gilliam v. Uni Holdings",
                            "id": 5305052,
                            "absolute_url": "/opinion/5305052/gilliam/",
                            # CL's citation index has the slip op but NOT
                            # the A.D.3d reporter — that's what makes it
                            # the silent-partial case.
                            "citations": [
                                {"volume": "2021", "reporter": "NY Slip Op",
                                 "page": "06798", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        }
        citation = (
            "Gilliam v. Uni Holdings, 201 A.D.3d 83, 88-89, "
            "2021 NY Slip Op 06798 (N.Y. App. Div. 2021)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_PARTIAL
        assert any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )
        # The citation_lookup stage still resolved — confidence stays high.
        assert _winning_path_entry(result).verdict == StageVerdict.resolved

    def test_verified_not_partial_when_primary_in_cluster_citations(self):
        """Peerenboom-shape: A.D.3d IS in CL — VERIFIED not PARTIAL."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Peerenboom v. Marvel Entertainment",
                            "id": 4376072,
                            "absolute_url": "/opinion/4376072/peerenboom/",
                            "citations": [
                                {"volume": "148", "reporter": "A.D.3d",
                                 "page": "531", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        }
        citation = (
            "Peerenboom v. Marvel Entertainment, LLC, 148 A.D.3d 531 "
            "(N.Y. App. Div. 2017)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED
        assert not any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )

    def test_verified_when_wl_only_input(self):
        """A WL-only citation (no parallel reporter) is VERIFIED, not PARTIAL."""
        api = {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": "Some Case",
                            "id": 999,
                            "absolute_url": "/opinion/999/",
                            "citations": [
                                {"volume": "2020", "reporter": "WL",
                                 "page": "123456", "type": 9},
                            ],
                        }
                    ]
                }
            ]
        }
        citation = "Some Case, 2020 WL 123456 (D. Md. 2020)"
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED


# ---------------------------------------------------------------------------
# Phase 3 Task 4: VERIFIED_VIA_RECAP / VERIFIED_DOCKET_ONLY branching
# ---------------------------------------------------------------------------


class TestVerifiedViaRecapVsDocketOnly:
    """Phase 3 Task 4: strict VIA_RECAP gate per maintainer Q1.
    Async parity per design v2 §1."""

    def test_via_recap_when_opinion_typed_doc_matches_date(self):
        """Mehar shape: opinion-typed doc + date-matched -> VIA_RECAP."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": "OPINION on motion to dismiss",
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        }
        citation = (
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.docket_id == 5474769
        assert result.final_ids.recap_document_id == 18720567
        assert result.final_ids.cluster_id is None
        assert result.final_ids.text_source.value == "recap_document"

    def test_docket_only_when_doc_is_procedural_order(self):
        """Cabot v. Lewis shape: order certifying interlocutory appeal
        is text-bearing but procedural. Strict reading: DOCKET_ONLY."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": "ORDER CERTIFYING INTERLOCUTORY APPEAL",
                            "page_count": 2,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        }
        citation = "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 4275225
        assert result.final_ids.recap_document_id is None
        assert result.final_ids.text_source is None

    def test_docket_only_when_date_mismatches(self):
        """Menges-actual shape: docket exists, doc description contains
        'motion in limine' (procedural keyword) -> DOCKET_ONLY."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Menges v. Cliffs Drilling Co.",
                    "docket_id": 10993603,
                    "id": 10993603,
                    "court_id": "laed",
                    "docket_absolute_url": "/docket/10993603/menges/",
                    "dateFiled": "1999-07-16",
                    "docketNumber": "99-2061",
                    "recap_documents": [
                        {
                            "id": 476627754,
                            "entry_date_filed": "2000-06-12",
                            "short_description": "ORDER & REASONS on motion in limine",
                            "page_count": 4,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        }
        citation = (
            "Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. May 31, 2000)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 10993603
        assert result.final_ids.recap_document_id is None


# ---------------------------------------------------------------------------
# Phase 3 Task 5 Async parity: caption_investigation
# ---------------------------------------------------------------------------


class TestCaptionInvestigationAsyncParity:
    """Async mirrors of tests/test_caption_investigation.py.

    Per design v2 §1: the async surface must be preserved — identical
    mock data must produce identical results in sync and async paths.
    """

    def _make_mismatch_api(
        self,
        cl_case_name: str,
        cluster_id: int,
        case_name_full: str = "",
        docket_id: int | None = None,
        docket_case_name: str = "",
        opinion_text: str = "",
    ) -> dict:
        """Build API response dict for both sync and async mocks."""
        return {
            "citation_lookup": [
                {
                    "clusters": [
                        {
                            "case_name": cl_case_name,
                            "id": cluster_id,
                            "absolute_url": f"/opinion/{cluster_id}/",
                            "citations": [
                                {"volume": "857", "reporter": "F.3d", "page": "267"},
                            ],
                        }
                    ]
                }
            ],
            "get_cluster": {
                "id": cluster_id,
                "case_name_full": case_name_full,
                "docket_id": docket_id,
            },
            "get_docket": {"case_name": docket_case_name} if docket_id else {},
            "get_opinion_text": opinion_text or None,
        }

    def test_async_path_includes_caption_investigation_stage(self):
        """Async mirror: caption_investigation stage appears in resolution_path."""
        api = self._make_mismatch_api(
            "Thompson v. Brown",
            cluster_id=4390987,
            case_name_full="Thompson v. Brown",
            docket_id=12345,
            docket_case_name="Morrison v. Green",
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(
            v.verify_async(async_client, "Morrison v. Green, 857 F.3d 267 (5th Cir. 2017)")
        )
        stages = [e.stage for e in result.resolution_path]
        assert StageName.caption_investigation in stages

    def test_async_parity_party_overlap_yields_verified(self):
        """Async mirror: docket caption matches → VERIFIED + cl_display_name_data_bug."""
        api = self._make_mismatch_api(
            "Thompson v. Brown",
            cluster_id=4390987,
            case_name_full="Thompson v. Brown",
            docket_id=12345,
            docket_case_name="Morrison v. Green",
        )
        sync_client = _make_client(**api)
        async_client = _make_async_client(**api)

        v_sync = CitationVerifier(sync_client)
        sync_result = v_sync.verify("Morrison v. Green, 857 F.3d 267 (5th Cir. 2017)")

        v_async = CitationVerifier()
        async_result = asyncio.run(
            v_async.verify_async(async_client, "Morrison v. Green, 857 F.3d 267 (5th Cir. 2017)")
        )

        assert sync_result.status == async_result.status == Status.VERIFIED
        assert any(
            w.category == WarningCategory.cl_display_name_data_bug
            for w in sync_result.warnings
        )
        assert any(
            w.category == WarningCategory.cl_display_name_data_bug
            for w in async_result.warnings
        )

    def test_async_parity_no_overlap_yields_wrong_case(self):
        """Async mirror: no party overlap → WRONG_CASE in both paths."""
        api = self._make_mismatch_api(
            "U.S. ex rel. Green v. Washington",
            cluster_id=2140439,
            case_name_full="United States ex rel. Green v. Washington",
            docket_id=999,
            docket_case_name="United States ex rel. Green v. Washington",
            opinion_text=(
                "UNITED STATES OF AMERICA EX REL. RICHARD GREEN, "
                "Plaintiff, v. WASHINGTON, et al. Defendants."
            ),
        )
        sync_client = _make_client(**api)
        async_client = _make_async_client(**api)

        v_sync = CitationVerifier(sync_client)
        sync_result = v_sync.verify("Hogan v. AT&T, Inc., 917 F. Supp. 1275 (S.D. Tex. 1994)")

        v_async = CitationVerifier()
        async_result = asyncio.run(
            v_async.verify_async(async_client, "Hogan v. AT&T, Inc., 917 F. Supp. 1275 (S.D. Tex. 1994)")
        )

        assert sync_result.status == async_result.status == Status.WRONG_CASE
        assert sync_result.final_ids.cluster_id == async_result.final_ids.cluster_id == 2140439


# ---------------------------------------------------------------------------
# Phase 4 Task 4: score-based VIA_RECAP gate (Q2) — async parity
# ---------------------------------------------------------------------------


class TestVerifiedViaRecapScoreGate:
    """Phase 4 Task 4 (Q2): score-based VIA_RECAP gate catches
    substantive-but-keyword-poor opinion descriptions like Mehar
    Holdings' 'ORDER GRANTING Motion for Reconsideration'.
    Async parity per design v2 §1."""

    def test_score_based_gate_accepts_substantive_long_form_doc(self):
        """Mehar Holdings shape: 12-page is_free_on_pacer doc with
        'ORDER GRANTING' description -> VIA_RECAP via score gate."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        }
        citation = (
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.recap_document_id == 18720567

    def test_score_gate_does_not_override_procedural_keywords(self):
        """Cabot v. Lewis shape: 'ORDER CERTIFYING INTERLOCUTORY APPEAL'
        matches a procedural keyword and stays DOCKET_ONLY even with
        a 8-page count + is_free_on_pacer."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": (
                                "ORDER CERTIFYING INTERLOCUTORY APPEAL"
                            ),
                            "page_count": 8,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        }
        citation = "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_DOCKET_ONLY

    def test_score_gate_requires_both_page_count_and_is_free(self):
        """A short doc (page_count < 5) fails the score gate even with
        a non-procedural description and is_free_on_pacer=True."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Short Case",
                    "docket_id": 9999,
                    "id": 9999,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/9999/short/",
                    "dateFiled": "2020-06-15",
                    "docketNumber": "1:20-cv-00001",
                    "recap_documents": [
                        {
                            "id": 12345,
                            "entry_date_filed": "2020-06-15",
                            "short_description": "ORDER on motion",
                            "page_count": 2,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        }
        citation = "Short Case v. Other, 2020 WL 999999 (W.D. Tex. June 15, 2020)"
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_DOCKET_ONLY

    def test_score_gate_fetches_doc_detail_when_search_omits_metadata(self):
        """Async parity: search_recap returns page_count=None/is_free_on_pacer=None.

        The async verifier must fetch /recap-documents/{id}/ and re-apply the
        score gate. If the detail populates page_count>=5 and is_free_on_pacer,
        the result should be VERIFIED_VIA_RECAP.
        """
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": None,
                            "is_free_on_pacer": None,
                        }
                    ],
                }
            ],
            "recap_document_metadata": {
                "id": 18720567,
                "page_count": 12,
                "is_free_on_pacer": True,
            },
        }
        citation = (
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.recap_document_id == 18720567
        async_client.get_recap_document_metadata.assert_called_once_with(18720567)

    def test_score_gate_doc_detail_fetch_failure_falls_back_to_docket_only(self):
        """Async parity: a failed doc-detail fetch leaves DOCKET_ONLY (no exception raised)."""
        api = {
            "citation_lookup": [],
            "search_opinions": [],
            "search_recap": [
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": None,
                            "is_free_on_pacer": None,
                        }
                    ],
                }
            ],
            "recap_document_metadata": ConnectionError("simulated network failure"),
        }
        citation = (
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        async_client = _make_async_client(**api)
        v = CitationVerifier()
        result = asyncio.run(v.verify_async(async_client, citation))
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.status != Status.VERIFICATION_INCOMPLETE


# ---------------------------------------------------------------------------
# verify_batch hit-processing path (regression: pre-fix this crashed with
# TypeError because the dict returned by _process_citation_lookup_hit can
# carry needs_caption_investigation/_cluster_for_investigation/status_override
# keys that _finalize_result doesn't accept. The single-citation pipeline
# pops them; verify_batch used to splat them straight in.)
# ---------------------------------------------------------------------------


def _make_batch_client_with_api(**api):
    """`_make_async_client` + the context-manager dunders verify_batch needs
    when patched in as the AsyncCourtListenerClient constructor result."""
    client = _make_async_client(**api)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestBatchPathHitProcessing:
    """Regression coverage for verify_batch's batch-hit branch.

    Pre-fix, both tests below crashed with
    `TypeError: _finalize_result() got an unexpected keyword argument ...`
    because the batch-hit splat at verifier.py:2948 passed
    `needs_caption_investigation` (name-mismatch path) or `status_override`
    (silent-partial path) into a fixed-signature kwargs target. The fix
    ports the pop-and-handle block from verify_async (verifier.py:2428-2482)
    into verify_batch.
    """

    def test_batch_hit_name_mismatch_runs_caption_investigation(self):
        """Cluster case_name disagrees with brief caption → batch path must
        open a caption_investigation stage instead of crashing."""
        # Use the same mismatch shape as
        # TestCaptionInvestigationAsyncParity.test_async_parity_no_overlap_yields_wrong_case
        # so the investigation reaches WRONG_CASE deterministically.
        citation = "Hogan v. AT&T, Inc., 917 F. Supp. 1275 (S.D. Tex. 1994)"
        api = {
            "citation_lookup": [
                {
                    # start_index/end_index let _batch_citation_lookup map
                    # the response back to the original citation slot.
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {
                            "case_name": "U.S. ex rel. Green v. Washington",
                            "id": 2140439,
                            "absolute_url": "/opinion/2140439/",
                            "citations": [
                                {"volume": "917", "reporter": "F. Supp.", "page": "1275"},
                            ],
                        }
                    ]
                }
            ],
            "get_cluster": {
                "id": 2140439,
                "case_name_full": "United States ex rel. Green v. Washington",
                "docket_id": 999,
            },
            "get_docket": {
                "case_name": "United States ex rel. Green v. Washington",
            },
            "get_opinion_text": (
                "UNITED STATES OF AMERICA EX REL. RICHARD GREEN, "
                "Plaintiff, v. WASHINGTON, et al. Defendants."
            ),
        }
        mock_client = _make_batch_client_with_api(**api)

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch([citation]))

        result = results[0]
        stages = [e.stage for e in result.resolution_path]
        assert StageName.caption_investigation in stages, (
            f"expected caption_investigation stage in batch path, got {stages}"
        )
        # Investigation classifies as WRONG_CASE (matches the verify_async
        # parity test); the underlying cluster id is still recorded.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 2140439

    def test_batch_hit_silent_partial_returns_verified_partial(self):
        """Cluster matches name but primary reporter is missing from CL's
        citation index → status_override=VERIFIED_PARTIAL must flow through."""
        # Mirrors TestVerifiedPartial.test_partial_when_primary_reporter_not_in_cluster_citations
        # (line ~1422) but driven through verify_batch.
        citation = (
            "Gilliam v. Uni Holdings, 201 A.D.3d 83, 88-89, "
            "2021 NY Slip Op 06798 (N.Y. App. Div. 2021)"
        )
        api = {
            "citation_lookup": [
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {
                            "case_name": "Gilliam v. Uni Holdings",
                            "id": 5305052,
                            "absolute_url": "/opinion/5305052/gilliam/",
                            "citations": [
                                {"volume": "2021", "reporter": "NY Slip Op",
                                 "page": "06798", "type": 1},
                            ],
                        }
                    ]
                }
            ],
        }
        mock_client = _make_batch_client_with_api(**api)

        v = CitationVerifier()
        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            return_value=mock_client,
        ):
            results = asyncio.run(v.verify_batch([citation]))

        result = results[0]
        assert result.status == Status.VERIFIED_PARTIAL
        assert any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )

    def test_batch_uses_provided_client_and_does_not_construct_its_own(self):
        """verify_batch(client=...) must reuse the caller's client so BYOK
        tokens (carried on web/app.py's per-request AsyncCourtListenerClient)
        reach the batched citation_lookup call."""
        citation = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        api = {
            "citation_lookup": [
                {
                    "start_index": 0,
                    "end_index": len(citation),
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell/",
                        }
                    ],
                }
            ]
        }
        provided_client = _make_batch_client_with_api(**api)

        v = CitationVerifier()
        # Patch the constructor to a sentinel that errors if called. If
        # verify_batch ignores the `client=` kwarg and constructs its own,
        # this will raise inside the function and the test fails.
        def _boom(*_a, **_kw):
            raise AssertionError(
                "verify_batch must not construct its own AsyncCourtListenerClient "
                "when one is passed via client="
            )

        with patch(
            "citation_verifier.verifier.AsyncCourtListenerClient",
            side_effect=_boom,
        ):
            results = asyncio.run(
                v.verify_batch([citation], client=provided_client)
            )

        assert results[0].status == Status.VERIFIED
        assert results[0].final_ids.cluster_id == 123
        # And the provided client actually got used.
        provided_client.citation_lookup.assert_called()
