"""Phase 4 Task 1 — unit tests for the MockSpecPatcher.

These tests verify the patcher's URL-routing and exception-injection
behavior against a toy CitationVerifier setup. They do NOT touch the
live CL API.
"""
from __future__ import annotations

import json

import pytest
import requests

from citation_verifier.client import CourtListenerClient
from citation_verifier.models import StageName, StageVerdict
from citation_verifier.verifier import CitationVerifier
from tests.mock_spec_harness import MockSpecPatcher, _STAGE_URL_PATTERNS


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
