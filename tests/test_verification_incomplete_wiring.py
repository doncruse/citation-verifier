"""Phase 4 Task 2 — VERIFICATION_INCOMPLETE production wiring per design §2.8.

The internal API-error gate: if any stage in resolution_path is
`errored` AND no stage has `resolved`/`partial`, status is
VERIFICATION_INCOMPLETE (not NOT_FOUND). When a stage IS resolved,
errors in later stages are tolerated and status stands.
"""
from __future__ import annotations

import asyncio

import pytest

from citation_verifier.client import (
    AsyncCourtListenerClient,
    CourtListenerClient,
)
from citation_verifier.models import StageName, StageVerdict, Status
from citation_verifier.verifier import CitationVerifier
from tests.mock_spec_harness import (
    AsyncMockSpecPatcher,
    MockSpecPatcher,
)


def _client(monkeypatch) -> CourtListenerClient:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test")
    return CourtListenerClient(api_token="test")


class TestSyncWiring:
    def test_http_500_on_citation_lookup_produces_verification_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup", "failure_mode": "http_500",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")
        assert result.status == Status.VERIFICATION_INCOMPLETE
        assert result.final_ids.cluster_id is None
        assert result.final_ids.docket_id is None
        # The path must record the errored stage; consumers depend on this.
        errored = [e for e in result.resolution_path
                   if e.verdict == StageVerdict.errored]
        assert any(e.stage == StageName.citation_lookup for e in errored)

    def test_connection_error_on_citation_lookup_produces_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup", "failure_mode": "connection_error",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Hanover Shoe, Inc. v. United Shoe, 392 U.S. 481 (1968)")
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_timeout_on_opinion_search_produces_incomplete(self, monkeypatch):
        """citation_lookup returns clean no_match; opinion_search times out.
        Per §2.8: cannot silently degrade to NOT_FOUND."""
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "opinion_search", "failure_mode": "timeout",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify(
                "Anderson v. Furst, No. 17-cv-12676, "
                "2018 WL 4407750 (E.D. Mich. Sept. 17, 2018)"
            )
        assert result.status == Status.VERIFICATION_INCOMPLETE
        stages_errored = [
            e.stage for e in result.resolution_path
            if e.verdict == StageVerdict.errored
        ]
        assert StageName.opinion_search in stages_errored

    def test_http_429_exhausted_produces_incomplete(self, monkeypatch):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup",
            "failure_mode": "http_429_no_retry_after",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Bossart v. King Cnty., 2025 WL 459154 "
                              "(W.D. Wash. Feb. 11, 2025)")
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_json_malformed_on_recap_docket_search_produces_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "recap_docket_search", "failure_mode": "json_malformed",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify(
                "Mehar Holdings, LLC v. Evanston Ins. Co., "
                "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
            )
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_clean_no_match_everywhere_still_produces_not_found(
        self, monkeypatch,
    ):
        """Sanity: with no errored stages, the existing NOT_FOUND path holds.
        Phase 4 must NOT promote clean negatives to INCOMPLETE."""
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        # Use the patcher with a fake target stage that no call matches;
        # the patcher then stubs every call to clean no-match.
        with MockSpecPatcher(client, spec={
            "stage": "caption_investigation",  # never reached for an unresolvable cite
            "failure_mode": "http_500",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Nonexistent v. Madeup, 999 F.3d 999 (5th Cir. 2099)")
        assert result.status == Status.NOT_FOUND


class TestAsyncWiring:
    def test_async_http_500_produces_verification_incomplete(self):
        async def go():
            async with AsyncCourtListenerClient(api_token="test") as async_client:
                v = CitationVerifier()
                async with AsyncMockSpecPatcher(async_client, spec={
                    "stage": "citation_lookup", "failure_mode": "http_500",
                    "attempt_idx": 0, "details": "",
                }):
                    return await v.verify_async(
                        async_client,
                        "Obergefell v. Hodges, 576 U.S. 644 (2015)",
                    )
        result = asyncio.run(go())
        assert result.status == Status.VERIFICATION_INCOMPLETE
