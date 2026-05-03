"""Tests for the `citation-verifier --json` single-verify output mode.

These tests pin the canonical JSON schema documented in
docs/plans/benchmark-spinout-prep.md (Task 2). The schema must
match the verify-batch CSV column set so downstream tools can
shell out to either form interchangeably.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from citation_verifier.__main__ import main
from citation_verifier.models import (
    Diagnostic,
    VerificationResult,
    VerificationStatus,
)


_REQUIRED_KEYS = {
    "citation",
    "status",
    "matched_cluster_id",
    "matched_url",
    "matched_case_name",
    "matched_court_id",
    "matched_date_filed",
    "confidence",
    "diagnostics",
}

# Bonus debug fields kept from the pre-spin-out JSON shape; they aren't
# part of the verify-batch CSV contract but stay available in --json
# so single-citation debugging doesn't lose information.
_BONUS_KEYS = {
    "candidates",
    "error",
}


def _verified_result() -> VerificationResult:
    return VerificationResult(
        input_citation="Obergefell v. Hodges, 576 U.S. 644 (2015)",
        status=VerificationStatus.VERIFIED,
        confidence=1.0,
        matched_case_name="Obergefell v. Hodges",
        matched_url="https://www.courtlistener.com/opinion/2812209/obergefell-v-hodges/",
        matched_cluster_id=2812209,
        matched_court="scotus",
        matched_date="2015-06-26",
        diagnostics=[],
    )


def _not_found_result() -> VerificationResult:
    return VerificationResult(
        input_citation="Made-Up Case, 999 F.99 1 (2099)",
        status=VerificationStatus.NOT_FOUND,
        confidence=0.0,
        diagnostics=[Diagnostic("info", "No match in citation lookup")],
    )


def _run_main_capture(argv: list[str], canned: list[VerificationResult]) -> str:
    """Run main(argv) with CitationVerifier patched and return captured stdout."""

    async def fake_verify_batch(citations, **kwargs):
        return canned

    buf = io.StringIO()
    with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
        instance = MockVerifier.return_value
        instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
        # The single-citation path uses verifier.verify (sync). Mock that too.
        instance.verify = MagicMock(
            return_value=canned[0] if canned else None
        )
        with patch("citation_verifier.__main__.VerificationCache") as MockCache:
            cache_instance = MockCache.return_value
            cache_instance.get = MagicMock(return_value=None)
            cache_instance.put = MagicMock(return_value=None)
            with redirect_stdout(buf):
                rc = main(argv)
    assert rc in (0, 1)  # 1 if any NOT_FOUND, 0 otherwise
    return buf.getvalue()


class TestSingleCitationJsonMode:
    def test_single_verified_emits_canonical_schema(self):
        out = _run_main_capture(
            ["--json", "--no-cache", "Obergefell v. Hodges, 576 U.S. 644 (2015)"],
            [_verified_result()],
        )
        # Stdout must contain exactly one valid JSON object on its own line.
        non_empty = [ln for ln in out.splitlines() if ln.strip()]
        assert len(non_empty) == 1, f"expected one JSON line, got: {out!r}"
        obj = json.loads(non_empty[0])

        assert _REQUIRED_KEYS.issubset(obj.keys())
        assert _BONUS_KEYS.issubset(obj.keys())
        assert obj["citation"] == "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        assert obj["status"] == "VERIFIED"
        assert obj["matched_cluster_id"] == 2812209
        assert obj["matched_url"].startswith("https://www.courtlistener.com/")
        assert obj["matched_case_name"] == "Obergefell v. Hodges"
        assert obj["matched_court_id"] == "scotus"
        assert obj["matched_date_filed"] == "2015-06-26"
        assert obj["confidence"] == 1.0
        assert obj["diagnostics"] == []
        # Bonus debug fields exposed for single-citation runs.
        assert obj["candidates"] == []
        assert obj["error"] is None

    def test_single_not_found_emits_nulls_and_diagnostics(self):
        out = _run_main_capture(
            ["--json", "--no-cache", "Made-Up Case, 999 F.99 1 (2099)"],
            [_not_found_result()],
        )
        non_empty = [ln for ln in out.splitlines() if ln.strip()]
        assert len(non_empty) == 1
        obj = json.loads(non_empty[0])

        assert _REQUIRED_KEYS.issubset(obj.keys())
        assert _BONUS_KEYS.issubset(obj.keys())
        assert obj["status"] == "NOT_FOUND"
        assert obj["matched_cluster_id"] is None
        assert obj["matched_url"] is None
        assert obj["matched_case_name"] is None
        assert obj["matched_court_id"] is None
        assert obj["matched_date_filed"] is None
        assert obj["confidence"] == 0.0
        assert obj["diagnostics"] == [
            {"category": "info", "message": "No match in citation lookup"}
        ]
        # Bonus debug fields stay available even on misses.
        assert obj["candidates"] == []
        assert obj["error"] is None


class TestMultiCitationJsonMode:
    def test_multi_emits_one_json_per_line(self):
        out = _run_main_capture(
            [
                "--json",
                "--no-cache",
                "Obergefell v. Hodges, 576 U.S. 644 (2015)",
                "Made-Up Case, 999 F.99 1 (2099)",
            ],
            [_verified_result(), _not_found_result()],
        )
        non_empty = [ln for ln in out.splitlines() if ln.strip()]
        assert len(non_empty) == 2

        first = json.loads(non_empty[0])
        second = json.loads(non_empty[1])
        assert first["status"] == "VERIFIED"
        assert second["status"] == "NOT_FOUND"
        assert _REQUIRED_KEYS.issubset(first.keys())
        assert _REQUIRED_KEYS.issubset(second.keys())

    def test_progress_messages_go_to_stderr_in_json_mode(self, capfd):
        # Two-citation path triggers the "Verifying N/M..." progress callback.
        # In json mode it must go to stderr to keep stdout pure JSON.
        async def fake_verify_batch(citations, **kwargs):
            cb = kwargs.get("progress_callback")
            if cb:
                cb(1, len(citations))
                cb(len(citations), len(citations))
            return [_verified_result(), _not_found_result()]

        with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
            instance = MockVerifier.return_value
            instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
            with patch("citation_verifier.__main__.VerificationCache") as MockCache:
                cache_instance = MockCache.return_value
                cache_instance.get = MagicMock(return_value=None)
                cache_instance.put = MagicMock(return_value=None)
                rc = main([
                    "--json",
                    "--no-cache",
                    "Obergefell v. Hodges, 576 U.S. 644 (2015)",
                    "Made-Up Case, 999 F.99 1 (2099)",
                ])

        captured = capfd.readouterr()
        # stdout should parse as NDJSON (no progress messages)
        non_empty = [ln for ln in captured.out.splitlines() if ln.strip()]
        for ln in non_empty:
            json.loads(ln)  # raises if any non-JSON sneaks in
        # stderr should contain the progress text
        assert "Verifying" in captured.err
