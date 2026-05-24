"""Phase 4 Task 1 — unit tests for the MockSpecPatcher.

These tests verify the patcher's URL-routing and exception-injection
behavior against a toy CitationVerifier setup. They do NOT touch the
live CL API.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import requests

from citation_verifier.client import AsyncCourtListenerClient, CourtListenerClient
from citation_verifier.models import StageName, StageVerdict
from citation_verifier.verifier import CitationVerifier
from tests.mock_spec_harness import (
    AsyncMockSpecPatcher,
    MockSpecPatcher,
    _STAGE_URL_PATTERNS,
    _classify_url,
)


def _client(monkeypatch) -> CourtListenerClient:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-not-used")
    return CourtListenerClient(api_token="test-token-not-used")


class TestStageRouting:
    """The harness identifies stages by URL pattern. The patterns must
    match the URLs the client actually constructs."""

    def test_citation_lookup_endpoint_routes_to_citation_lookup(self):
        assert _STAGE_URL_PATTERNS["citation_lookup"].search(
            "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
        )

    def test_opinion_search_endpoint_routes_to_opinion_search(self):
        # search?type=o
        assert _STAGE_URL_PATTERNS["opinion_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=o&q=foo"
        )

    def test_recap_docket_search_routes_to_recap_docket_search(self):
        assert _STAGE_URL_PATTERNS["recap_docket_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=r&q=foo"
        )

    def test_recap_document_search_routes_to_recap_document_search(self):
        assert _STAGE_URL_PATTERNS["recap_document_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=rd&q=foo"
        )


class TestSyncFailureInjection:
    def test_http_500_on_citation_lookup_raises_http_error(self, monkeypatch):
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            with pytest.raises(requests.HTTPError):
                client.citation_lookup("Obergefell v. Hodges, 576 U.S. 644 (2015)")

    def test_connection_error_on_citation_lookup_raises_connection_error(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "connection_error",
                  "attempt_idx": 0, "details": ""},
        ):
            with pytest.raises(requests.ConnectionError):
                client.citation_lookup("Obergefell v. Hodges, 576 U.S. 644 (2015)")

    def test_timeout_on_opinion_search_returns_empty_for_citation_lookup(
        self, monkeypatch,
    ):
        """citation_lookup is stubbed to clean no-match; opinion_search times out."""
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "opinion_search", "failure_mode": "timeout",
                  "attempt_idx": 0, "details": ""},
        ):
            # citation_lookup is NOT the target — returns clean no-match.
            result = client.citation_lookup("Nonexistent Case, 999 F.3d 999 (2099)")
            assert result == []
            # opinion_search IS the target — raises Timeout.
            with pytest.raises(requests.Timeout):
                client.search_opinions(case_name="X")

    def test_non_target_stage_calls_return_clean_no_match(self, monkeypatch):
        """Calls to non-target stages get stubbed empty responses, NOT live
        API calls. This is what makes the harness CI-safe (no token needed)."""
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            # search_opinions is NOT the target -> empty list, no raise.
            assert client.search_opinions(case_name="X") == []
            assert client.search_recap(q='"X v. Y"') == []


class TestVerifierEndToEndUnderHarness:
    """The verifier driven by an instrumented client under the harness
    must record `verdict=errored` on the target stage's path entry."""

    def test_verify_http_500_records_errored_on_citation_lookup(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")
        entries = [e for e in result.resolution_path
                   if e.stage == StageName.citation_lookup]
        assert entries, "citation_lookup stage entry missing"
        assert entries[0].verdict == StageVerdict.errored
        # Phase 4 Task 2 will assert status==VERIFICATION_INCOMPLETE here;
        # this test only confirms the harness wired the error correctly.


class TestAttemptIdxIgnored:
    """C1 regression: attempt_idx > 0 must NOT delay firing.

    The harness wraps _request_with_retry (the OUTER retry boundary) which the
    verifier calls exactly once per stage per verify(). A gate of
    ``count == attempt_idx`` with attempt_idx=2 would never fire. The fix is
    to fire on the first matching-stage call regardless of attempt_idx.
    """

    def test_attempt_idx_ignored_fires_on_first_call(self, monkeypatch):
        """Spec with attempt_idx=2 must still raise on the very first call."""
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_429_no_retry_after",
                  "attempt_idx": 2, "details": ""},
        ):
            with pytest.raises(requests.HTTPError) as exc_info:
                client.citation_lookup("Bossart v. King Cnty., 2025 WL 459154")
        assert exc_info.value.response.status_code == 429


class TestClassifyUrlWithParams:
    """I3: _classify_url must route via params['type'] (the production path),
    not only the regex fallback that TestStageRouting covers."""

    def test_search_opinion_via_params(self):
        assert _classify_url(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"type": "o", "q": "foo"},
        ) == "opinion_search"

    def test_search_recap_docket_via_params(self):
        assert _classify_url(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"type": "r", "q": "foo"},
        ) == "recap_docket_search"

    def test_search_recap_document_via_params(self):
        assert _classify_url(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"type": "rd", "q": "foo"},
        ) == "recap_document_search"

    def test_citation_lookup_url_path_classified(self):
        assert _classify_url(
            "https://www.courtlistener.com/api/rest/v4/citation-lookup/",
            params=None,
        ) == "citation_lookup"

    def test_search_plain_docket_via_params(self):
        assert _classify_url(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"type": "d", "q": "foo"},
        ) == "plain_docket_search"


class TestAsyncFailureInjection:
    """I1: async harness mirrors sync failure injection.

    Uses asyncio.run() (matching the convention in test_async_verifier.py)
    rather than @pytest.mark.asyncio, since pytest-asyncio is not installed
    in this environment.
    """

    def test_async_http_500_on_citation_lookup_raises(self):
        async def _run():
            async with AsyncCourtListenerClient(api_token="test-token-not-used") as client:
                async with AsyncMockSpecPatcher(
                    client,
                    spec={"stage": "citation_lookup", "failure_mode": "http_500",
                          "attempt_idx": 0, "details": ""},
                ):
                    await client.citation_lookup(
                        "Obergefell v. Hodges, 576 U.S. 644 (2015)"
                    )

        with pytest.raises(requests.HTTPError):
            asyncio.run(_run())
