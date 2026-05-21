"""Tests for the `citation-verifier --json` single-verify output mode.

These tests pin the canonical JSON schema documented in
docs/plans/benchmark-spinout-prep.md (Task 2). The schema must
match the verify-batch CSV column set so downstream tools can
shell out to either form interchangeably.

Migrated to the v0.3 schema (Phase 1, Task 5). ``_make_result``
builds the v0.3 shape directly; the JSON serializer in
``__main__._result_to_json_dict`` translates back to the legacy
external schema for shell consumers.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from citation_verifier.__main__ import main
from citation_verifier.models import (
    FinalIds,
    ParsedCitation,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
)


_REQUIRED_KEYS = {
    "citation",
    "status",
    "matched_cluster_id",
    "matched_docket_id",
    "matched_url",
    "matched_case_name",
    "matched_court_id",
    "matched_date_filed",
    "confidence",
    "diagnostics",
}

# Bonus debug fields kept from the pre-spin-out JSON shape; they aren't
# part of the verify-batch CSV contract but stay available in --json
# so single-citation debugging doesn't lose information. Phase 1
# doesn't track candidates or a structured error channel anymore, so
# the keys exist but are always [] / None.
_BONUS_KEYS = {
    "candidates",
    "error",
}


def _make_result(
    *,
    citation: str,
    status: Status,
    confidence: float | None,
    case_name: str | None = None,
    cluster_id: int | None = None,
    docket_id: int | None = None,
    absolute_url: str | None = None,
    court: str | None = None,
    year: int | None = None,
) -> VerificationResult:
    """Build a v0.3 VerificationResult.

    When ``status`` is a verified-class status (or any time we have a case
    name to surface), the resolution_path entry carries it via
    ``raw_response_summary["case_name"]`` — mirroring verifier._build_result.
    """
    path: list[ResolutionPathEntry] = []
    if status != Status.NOT_FOUND or case_name is not None:
        path.append(
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={},
                raw_response_summary=({"case_name": case_name} if case_name else {}),
                verdict=(
                    StageVerdict.resolved
                    if status != Status.NOT_FOUND
                    else StageVerdict.no_match
                ),
                confidence=confidence,
                notes=None,
                elapsed_ms=0,
            )
        )

    parsed = ParsedCitation(raw_text=citation, court=court, year=year)

    return VerificationResult(
        citation_as_written=citation,
        parsed_citation=parsed,
        status=status,
        final_ids=FinalIds(
            cluster_id=cluster_id,
            opinion_id=None,
            docket_id=docket_id,
            recap_document_id=None,
            absolute_url=absolute_url,
            text_source=None,
        ),
        resolution_path=path,
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


def _verified_result() -> VerificationResult:
    return _make_result(
        citation="Obergefell v. Hodges, 576 U.S. 644 (2015)",
        status=Status.VERIFIED,
        confidence=1.0,
        case_name="Obergefell v. Hodges",
        cluster_id=2812209,
        absolute_url="https://www.courtlistener.com/opinion/2812209/obergefell-v-hodges/",
        court="scotus",
        year=2015,
    )


def _not_found_result() -> VerificationResult:
    """Phase 1 NOT_FOUND: no resolution_path entry, no matched fields.

    The legacy "No match in citation lookup" diagnostic moved into the
    resolving-stage's notes when a NOT_FOUND stage entry is emitted.
    For a bare NOT_FOUND we have no stage entry and therefore no
    diagnostics — matching what verifier.py now produces.
    """
    return _make_result(
        citation="Made-Up Case, 999 F.99 1 (2099)",
        status=Status.NOT_FOUND,
        confidence=0.0,
        # No year/court — the canonical schema lets matched_court_id
        # and matched_date_filed be None for a true miss.
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
        # v0.3 dropped the structured matched_date; the JSON shim falls
        # back to the parsed-citation year. The legacy field was a full
        # ISO date — here we get the year only.
        assert obj["matched_date_filed"] == "2015"
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
        # Phase 1 NOT_FOUND no longer carries the legacy "No match in
        # citation lookup" Diagnostic; the verifier emits an empty
        # warnings list. Diagnostics serialize to []. The downstream
        # contract still gets a key, just with no entries.
        assert obj["diagnostics"] == []
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
