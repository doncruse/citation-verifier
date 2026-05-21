"""Tests for the `verify-batch` CLI subcommand.

CitationVerifier.verify_batch is mocked so no real API calls are made.
Tests focus on CLI plumbing: argument parsing, CSV reading,
output column structure, status formatting, and diagnostics
serialization.

Migrated to the v0.3 schema (Phase 1, Task 5). The v0.3
VerificationResult drops top-level matched_court/matched_date; the CSV
writer in __main__ falls back to the parsed citation's court/year for
the matched_court_id and matched_date_filed columns. The asserts in
this file have been relaxed to that shape.
"""

from __future__ import annotations

import csv
import json
import sys
from unittest.mock import AsyncMock, patch

import pytest

from citation_verifier.__main__ import verify_batch_main
from citation_verifier.models import (
    FinalIds,
    ParsedCitation,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
    Warning as ResultWarning,
    WarningCategory,
)


_OUTPUT_COLUMNS = [
    "citation",
    "status",
    "matched_cluster_id",
    "matched_docket_id",
    "matched_url",
    "matched_case_name",
    "matched_court_id",
    "matched_date_filed",
    "confidence",
    "diagnostics_json",
]


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
    warnings: list[ResultWarning] | None = None,
    stage_notes: str | None = None,
) -> VerificationResult:
    """v0.3 VerificationResult fixture.

    Mirrors the production verifier._build_result shape: when the result
    is verified-class (or has a case_name to surface), a single
    resolution_path entry holds confidence + case_name. Stage notes go
    into ``ResolutionPathEntry.notes``.
    """
    path: list[ResolutionPathEntry] = []
    if status != Status.NOT_FOUND or case_name is not None or stage_notes:
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
                notes=stage_notes,
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
        warnings=warnings or [],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


def _verified(citation: str) -> VerificationResult:
    return _make_result(
        citation=citation,
        status=Status.VERIFIED,
        confidence=1.0,
        case_name="Obergefell v. Hodges",
        cluster_id=2812209,
        absolute_url="https://www.courtlistener.com/opinion/2812209/obergefell-v-hodges/",
        court="scotus",
        year=2015,
    )


def _not_found(citation: str) -> VerificationResult:
    # The old fixture attached a Diagnostic("info", "No match in citation lookup").
    # In v0.3 that prose lives in ResolutionPathEntry.notes; the CSV writer
    # appends it under category "info" to mirror the legacy diagnostics_json
    # output.
    return _make_result(
        citation=citation,
        status=Status.NOT_FOUND,
        confidence=0.0,
        stage_notes="No match in citation lookup",
    )


def _build_input_csv(tmp_path, rows: list[dict], fieldnames: list[str]) -> "Path":
    path = tmp_path / "input.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _run_with_canned_results(argv: list[str], canned: list[VerificationResult]):
    """Patch CitationVerifier so verify_batch returns canned results."""
    captured: dict = {}

    async def fake_verify_batch(citations, **kwargs):
        captured["citations"] = list(citations)
        captured["kwargs"] = kwargs
        return canned

    with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
        instance = MockVerifier.return_value
        instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
        rc = verify_batch_main(argv)
    return rc, captured


class TestVerifyBatchCLI:
    def test_basic_10_row_input_produces_csv_with_expected_columns(self, tmp_path):
        # Build 10-row input: 5 known-real + 5 known-fake
        real = [
            "Obergefell v. Hodges, 576 U.S. 644 (2015)",
            "Brown v. Board of Education, 347 U.S. 483 (1954)",
            "Marbury v. Madison, 5 U.S. 137 (1803)",
            "Roe v. Wade, 410 U.S. 113 (1973)",
            "Miranda v. Arizona, 384 U.S. 436 (1966)",
        ]
        fake = [
            "Smith v. Jones, 999 F.99 99999 (2099)",
            "Doe v. Roe, 1 ZZZ 1 (1900)",
            "Hallucinated v. Citation, 100 X.Y.Z 200 (2025)",
            "Made-Up Case, 50 Fake.3d 1 (1999)",
            "Fictional v. Real, 200 NotReal 300 (2024)",
        ]
        all_cites = real + fake

        in_rows = [{"id": str(i + 1), "citation": c} for i, c in enumerate(all_cites)]
        in_path = _build_input_csv(tmp_path, in_rows, ["id", "citation"])
        out_path = tmp_path / "verified.csv"

        canned = [_verified(c) for c in real] + [_not_found(c) for c in fake]

        rc, captured = _run_with_canned_results(
            [
                str(in_path),
                "--column", "citation",
                "--output", str(out_path),
            ],
            canned,
        )

        assert rc == 0
        assert out_path.exists()

        with out_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == _OUTPUT_COLUMNS
            out_rows = list(reader)

        assert len(out_rows) == 10
        assert captured["citations"] == all_cites

        # First 5 are VERIFIED with full match metadata
        for i, cite in enumerate(real):
            row = out_rows[i]
            assert row["citation"] == cite
            assert row["status"] == "VERIFIED"
            assert row["matched_cluster_id"] == "2812209"
            assert row["matched_url"].startswith("https://www.courtlistener.com/")
            assert row["matched_case_name"] == "Obergefell v. Hodges"
            assert row["matched_court_id"] == "scotus"
            # v0.3 dropped the structured matched_date; the writer falls
            # back to the parsed-citation year (string).
            assert row["matched_date_filed"] == "2015"
            assert row["confidence"] == "1.0"
            assert row["diagnostics_json"] == "[]"

        # Last 5 are NOT_FOUND with stage-notes serialized as a synthetic
        # info-category diagnostic (legacy compat).
        for i, cite in enumerate(fake):
            row = out_rows[5 + i]
            assert row["citation"] == cite
            assert row["status"] == "NOT_FOUND"
            assert row["matched_cluster_id"] == ""
            assert row["matched_url"] == ""
            assert row["matched_case_name"] == ""
            # No court/year on the parsed citation for our fake inputs.
            assert row["matched_court_id"] == ""
            assert row["matched_date_filed"] == ""
            assert row["confidence"] == "0.0"
            diags = json.loads(row["diagnostics_json"])
            assert diags == [{"category": "info", "message": "No match in citation lookup"}]

    def test_quick_only_flag_passed_through(self, tmp_path):
        in_path = _build_input_csv(
            tmp_path,
            [{"citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)"}],
            ["citation"],
        )
        out_path = tmp_path / "out.csv"

        canned = [_verified("Obergefell v. Hodges, 576 U.S. 644 (2015)")]
        rc, captured = _run_with_canned_results(
            [
                str(in_path),
                "--column", "citation",
                "--output", str(out_path),
                "--quick-only",
            ],
            canned,
        )

        assert rc == 0
        assert captured["kwargs"].get("quick_only") is True

    def test_no_quick_only_default_false(self, tmp_path):
        in_path = _build_input_csv(
            tmp_path,
            [{"citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)"}],
            ["citation"],
        )
        out_path = tmp_path / "out.csv"

        canned = [_verified("Obergefell v. Hodges, 576 U.S. 644 (2015)")]
        rc, captured = _run_with_canned_results(
            [
                str(in_path),
                "--column", "citation",
                "--output", str(out_path),
            ],
            canned,
        )

        assert rc == 0
        # Either absent or explicitly False is fine.
        assert captured["kwargs"].get("quick_only", False) is False

    def test_optional_metadata_columns_build_parsed_citations(self, tmp_path):
        in_path = _build_input_csv(
            tmp_path,
            [
                {
                    "citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)",
                    "case_name": "Obergefell v. Hodges",
                    "court": "scotus",
                    "year": "2015",
                },
            ],
            ["citation", "case_name", "court", "year"],
        )
        out_path = tmp_path / "out.csv"

        canned = [_verified("Obergefell v. Hodges, 576 U.S. 644 (2015)")]
        rc, captured = _run_with_canned_results(
            [
                str(in_path),
                "--column", "citation",
                "--name-column", "case_name",
                "--court-column", "court",
                "--year-column", "year",
                "--output", str(out_path),
            ],
            canned,
        )

        assert rc == 0
        parsed = captured["kwargs"].get("parsed_citations")
        assert parsed is not None
        assert len(parsed) == 1
        assert parsed[0] is not None
        assert parsed[0].case_name == "Obergefell v. Hodges"
        assert parsed[0].court == "scotus"
        assert parsed[0].year == 2015
        assert parsed[0].raw_text == "Obergefell v. Hodges, 576 U.S. 644 (2015)"

    def test_missing_input_column_errors(self, tmp_path):
        in_path = _build_input_csv(
            tmp_path,
            [{"foo": "bar"}],
            ["foo"],
        )
        out_path = tmp_path / "out.csv"

        canned: list[VerificationResult] = []
        rc, _ = _run_with_canned_results(
            [
                str(in_path),
                "--column", "citation",
                "--output", str(out_path),
            ],
            canned,
        )
        assert rc != 0

    def test_csv_includes_matched_docket_id_column(self):
        from citation_verifier.__main__ import _VERIFY_BATCH_OUTPUT_COLUMNS, _result_to_row

        assert "matched_docket_id" in _VERIFY_BATCH_OUTPUT_COLUMNS

        result = _make_result(
            citation="Lindsay-Stern v. Garamszegi",
            # POSSIBLE_MATCH is not a v0.3 status. The closest v0.3 cousin
            # for a docket-only resolution is VERIFIED_DOCKET_ONLY; the
            # original test only cared that docket_id serialized and
            # cluster_id was blank, so we use that here.
            status=Status.VERIFIED_DOCKET_ONLY,
            confidence=0.5,
            docket_id=18158469,
            cluster_id=None,
        )
        row = _result_to_row(result)
        assert row["matched_docket_id"] == "18158469"
        assert row["matched_cluster_id"] == ""

    def test_dispatch_via_main_module(self, tmp_path, monkeypatch):
        """Confirm `python -m citation_verifier verify-batch ...` is wired up."""
        in_path = _build_input_csv(
            tmp_path,
            [{"citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)"}],
            ["citation"],
        )
        out_path = tmp_path / "out.csv"

        canned = [_verified("Obergefell v. Hodges, 576 U.S. 644 (2015)")]

        async def fake_verify_batch(citations, **kwargs):
            return canned

        # Simulate the dispatcher in `if __name__ == "__main__"` by importing
        # the module and calling the dispatch path.
        from citation_verifier import __main__ as cli_main

        argv = [
            "citation-verifier",
            "verify-batch",
            str(in_path),
            "--column", "citation",
            "--output", str(out_path),
        ]
        monkeypatch.setattr(sys, "argv", argv)

        with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
            instance = MockVerifier.return_value
            instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
            # Manually invoke the dispatch logic that lives under
            # `if __name__ == "__main__"` so we do not actually spawn a process.
            assert sys.argv[1] == "verify-batch"
            rc = cli_main.verify_batch_main(sys.argv[2:])

        assert rc == 0
        assert out_path.exists()
