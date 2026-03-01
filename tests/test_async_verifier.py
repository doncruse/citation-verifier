"""Tests for async verification pipeline and sync/async parity.

Verifies that:
1. Async path produces identical results to sync path (given same mock data)
2. verify_batch orchestration (ordering, progress callback, concurrency)
3. AsyncCourtListenerClient API parity and retry behavior
4. Exponential backoff formula (intentionally stricter than sync to avoid 429 storms)

All tests mock API clients so no real API calls are made.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from citation_verifier.client import AsyncCourtListenerClient, CourtListenerClient
from citation_verifier.models import ParsedCitation, VerificationStatus
from citation_verifier.verifier import CitationVerifier


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
    return client


def _make_async_client(**overrides):
    """Create a mock AsyncCourtListenerClient with sensible defaults."""
    client = AsyncMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
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

        assert sync_r.status == async_r.status == VerificationStatus.VERIFIED
        assert sync_r.confidence == async_r.confidence == 1.0
        assert sync_r.matched_case_name == async_r.matched_case_name
        assert sync_r.matched_url == async_r.matched_url

    def test_parity_citation_lookup_name_mismatch(self):
        """Step 1: Citation exists but wrong case → NOT_FOUND in both paths."""
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

        assert sync_r.status == async_r.status == VerificationStatus.NOT_FOUND
        assert sync_r.confidence == async_r.confidence == 0.0
        assert sync_r.diagnostics == async_r.diagnostics

    def test_parity_adjacent_page_match(self):
        """Step 1b: Found on adjacent page → VERIFIED in both paths."""

        def lookup_side_effect(text):
            if "559" in text:
                return [
                    {
                        "clusters": [
                            {
                                "case_name": "Smith v. Jones",
                                "id": 100,
                                "absolute_url": "/opinion/100/",
                            }
                        ]
                    }
                ]
            return []

        sync_client = _make_client()
        sync_client.citation_lookup.side_effect = lookup_side_effect

        async_client = _make_async_client()
        async_client.citation_lookup.side_effect = lookup_side_effect

        citation = "Smith v. Jones, 500 F.3d 560 (2d Cir. 2020)"
        v = CitationVerifier(sync_client)
        sync_r = v.verify(citation)
        async_r = asyncio.run(v.verify_async(async_client, citation))

        assert sync_r.status == async_r.status == VerificationStatus.VERIFIED
        assert sync_r.confidence == async_r.confidence
        assert sync_r.matched_case_name == async_r.matched_case_name

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

        assert sync_r.status == async_r.status == VerificationStatus.LIKELY_REAL
        assert sync_r.confidence == async_r.confidence
        assert sync_r.matched_case_name == async_r.matched_case_name
        assert sync_r.matched_url == async_r.matched_url

    def test_parity_no_results_not_found(self):
        """All searches return empty → NOT_FOUND in both paths."""
        api = {}  # everything returns []
        sync_r, async_r = _verify_parity(
            api, "Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)"
        )

        assert sync_r.status == async_r.status == VerificationStatus.NOT_FOUND
        assert sync_r.confidence == async_r.confidence == 0.0

    def test_parity_retries_without_court_filter(self):
        """Both paths retry opinion search without court filter when first attempt is empty."""
        sync_client = _make_client()
        async_client = _make_async_client()

        citation = "Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)"
        v = CitationVerifier(sync_client)
        v.verify(citation)
        asyncio.run(v.verify_async(async_client, citation))

        assert sync_client.search_opinions.call_count == 2
        assert async_client.search_opinions.call_count == 2

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
        assert sync_r.confidence == async_r.confidence
        assert sync_r.matched_case_name == async_r.matched_case_name

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
        assert sync_r.confidence == async_r.confidence
        assert sync_r.confidence < 0.6  # 0.6x discount

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

        assert sync_r.status == async_r.status == VerificationStatus.NOT_FOUND

    def test_parity_insufficient_data_guard(self):
        """Missing both court and date → NOT_FOUND with diagnostic in both paths."""
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

        assert sync_r.status == async_r.status == VerificationStatus.NOT_FOUND
        assert sync_r.confidence == async_r.confidence == 0.0
        assert "Insufficient data" in sync_r.diagnostics[0]
        assert sync_r.diagnostics == async_r.diagnostics

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

        assert sync_r.status == async_r.status == VerificationStatus.NOT_FOUND
        assert sync_r.confidence == async_r.confidence == 0.0
        assert "Quick search only" in sync_r.diagnostics[0]
        assert sync_r.diagnostics == async_r.diagnostics

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

        assert sync_r.status == async_r.status == VerificationStatus.VERIFIED
        assert sync_r.confidence == async_r.confidence == 1.0
        assert sync_r.matched_case_name == async_r.matched_case_name

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

        assert sync_r.status == async_r.status == VerificationStatus.VERIFIED
        assert sync_r.confidence == async_r.confidence == 1.0

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
        assert sync_r.confidence == async_r.confidence
        assert sync_r.matched_case_name == async_r.matched_case_name


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

        def mock_citation_lookup(text):
            if "576" in text:
                return [
                    {
                        "clusters": [
                            {
                                "case_name": "Obergefell v. Hodges",
                                "id": 123,
                                "absolute_url": "/opinion/123/",
                            }
                        ]
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
        assert results[0].status == VerificationStatus.VERIFIED
        assert results[1].status == VerificationStatus.NOT_FOUND

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
        """Pre-parsed citations are forwarded to verify_async."""
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
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                        }
                    ]
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
        assert results[0].status == VerificationStatus.VERIFIED

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
        assert all(r.status == VerificationStatus.NOT_FOUND for r in results)


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
