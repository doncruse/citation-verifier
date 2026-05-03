"""Tests for the `audit-misses` CLI subcommand.

The audit takes a CSV of (mostly) NOT_FOUND citations, re-runs the
full production fallback pipeline (citation-lookup with chunking →
opinion-search → RECAP for federal courts), and writes a passthrough
CSV with new ``fallback_*`` columns including a ``fallback_path``
attribution column.

CitationVerifier is mocked so no API calls happen. Path attribution
logic is what these tests pin down.
"""

from __future__ import annotations

import csv
from unittest.mock import AsyncMock, patch

import pytest

from citation_verifier.__main__ import audit_misses_main
from citation_verifier.models import (
    Diagnostic,
    VerificationResult,
    VerificationStatus,
)


_AUDIT_OUTPUT_COLUMNS_ADDED = [
    "fallback_status",
    "fallback_path",
    "fallback_confidence",
    "fallback_url",
    "fallback_matched_name",
    "fallback_court_id",
    "fallback_date_filed",
]


def _not_found(citation: str) -> VerificationResult:
    return VerificationResult(
        input_citation=citation,
        status=VerificationStatus.NOT_FOUND,
        confidence=0.0,
        diagnostics=[Diagnostic("info", "No match in citation lookup")],
    )


def _verified_via_lookup(citation: str, **kw) -> VerificationResult:
    return VerificationResult(
        input_citation=citation,
        status=VerificationStatus.VERIFIED,
        confidence=1.0,
        matched_case_name=kw.get("matched_case_name", "Found Case"),
        matched_url=kw.get("matched_url", "https://www.courtlistener.com/opinion/100/"),
        matched_cluster_id=kw.get("matched_cluster_id", 100),
        matched_court=kw.get("matched_court", "ca9"),
        matched_date=kw.get("matched_date", "1995-10-04"),
    )


def _verified_via_search(citation: str, **kw) -> VerificationResult:
    """Opinion-search hit: no `recap` diagnostic on the result."""
    return VerificationResult(
        input_citation=citation,
        status=VerificationStatus.LIKELY_REAL,
        confidence=0.85,
        matched_case_name=kw.get("matched_case_name", "Search Hit Case"),
        matched_url=kw.get("matched_url", "https://www.courtlistener.com/opinion/200/"),
        matched_cluster_id=kw.get("matched_cluster_id", 200),
        matched_court=kw.get("matched_court", "ca6"),
        matched_date=kw.get("matched_date", "2014-08-13"),
        diagnostics=[Diagnostic("info", "We identified a likely match.")],
    )


def _verified_via_recap(citation: str, **kw) -> VerificationResult:
    """RECAP hit: has at least one `recap` category diagnostic."""
    return VerificationResult(
        input_citation=citation,
        status=VerificationStatus.LIKELY_REAL,
        confidence=0.7,
        matched_case_name=kw.get("matched_case_name", "RECAP Docket"),
        matched_url=kw.get("matched_url", "https://www.courtlistener.com/docket/300/"),
        matched_cluster_id=kw.get("matched_cluster_id", 300),
        matched_court=kw.get("matched_court", "dcd"),
        matched_date=kw.get("matched_date", "2019-02-08"),
        diagnostics=[
            Diagnostic("recap", "Found in RECAP (not in opinions database)"),
            Diagnostic("info", "We identified a likely match."),
        ],
    )


def _build_input_csv(tmp_path, rows: list[dict], fieldnames: list[str]) -> "Path":
    path = tmp_path / "misses.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _patched_run(argv, quick_results, full_results):
    """Mock CitationVerifier.verify_batch to dispatch on quick_only."""
    captured: dict = {"calls": []}

    async def fake_verify_batch(citations, **kwargs):
        captured["calls"].append({
            "quick_only": kwargs.get("quick_only", False),
            "citations": list(citations),
        })
        if kwargs.get("quick_only"):
            return quick_results
        return full_results

    with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
        instance = MockVerifier.return_value
        instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
        rc = audit_misses_main(argv)
    return rc, captured


class TestAuditMissesCLI:
    def test_attributes_three_paths_correctly(self, tmp_path):
        rows = [
            {"cite": "67 F.3d 309", "case_name": "United States v. Asrar",
             "court": "ca9", "year": "1995"},
            {"cite": "763 F.3d 443", "case_name": "United States v. Fields",
             "court": "ca6", "year": "2014"},
            {"cite": "751 F. App'x 928", "case_name": "Slabon v. Berryhill",
             "court": "ca7", "year": "2019"},
            {"cite": "999 F.99 1", "case_name": "Made-Up Case",
             "court": "scotus", "year": "2099"},
        ]
        in_path = _build_input_csv(
            tmp_path, rows, ["cite", "case_name", "court", "year"]
        )
        out_path = tmp_path / "audited.csv"

        # Quick pass: row 0 is a citation-lookup recovery (chunking-fix style),
        # the other three miss in citation-lookup.
        quick_results = [
            _verified_via_lookup(rows[0]["cite"]),
            _not_found(rows[1]["cite"]),
            _not_found(rows[2]["cite"]),
            _not_found(rows[3]["cite"]),
        ]
        # Full pass on the three quick-misses: one opinion-search hit,
        # one RECAP hit, one truly no_match.
        full_results = [
            _verified_via_search(rows[1]["cite"]),
            _verified_via_recap(rows[2]["cite"]),
            _not_found(rows[3]["cite"]),
        ]

        rc, captured = _patched_run(
            [
                str(in_path),
                "--column", "cite",
                "--name-column", "case_name",
                "--court-column", "court",
                "--year-column", "year",
                "--output", str(out_path),
            ],
            quick_results,
            full_results,
        )

        assert rc == 0
        assert out_path.exists()

        # Quick was called on all 4; full was called only on the 3 quick-misses.
        assert len(captured["calls"]) == 2
        assert captured["calls"][0]["quick_only"] is True
        assert len(captured["calls"][0]["citations"]) == 4
        assert captured["calls"][1]["quick_only"] is False
        assert len(captured["calls"][1]["citations"]) == 3

        with out_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            out_rows = list(reader)
            fieldnames = reader.fieldnames

        # Input columns preserved, new columns appended.
        assert fieldnames[:4] == ["cite", "case_name", "court", "year"]
        for col in _AUDIT_OUTPUT_COLUMNS_ADDED:
            assert col in fieldnames
        assert len(out_rows) == 4

        # Row 0: citation-lookup recovery
        assert out_rows[0]["cite"] == rows[0]["cite"]
        assert out_rows[0]["fallback_path"] == "citation-lookup"
        assert out_rows[0]["fallback_status"] == "VERIFIED"
        assert out_rows[0]["fallback_url"].startswith("https://www.courtlistener.com/")

        # Row 1: opinion-search recovery
        assert out_rows[1]["fallback_path"] == "opinion-search"
        assert out_rows[1]["fallback_status"] == "LIKELY_REAL"
        assert out_rows[1]["fallback_court_id"] == "ca6"
        assert out_rows[1]["fallback_date_filed"] == "2014-08-13"

        # Row 2: RECAP recovery (has recap diagnostic)
        assert out_rows[2]["fallback_path"] == "RECAP"
        assert out_rows[2]["fallback_status"] == "LIKELY_REAL"
        assert out_rows[2]["fallback_url"] == "https://www.courtlistener.com/docket/300/"

        # Row 3: still NOT_FOUND
        assert out_rows[3]["fallback_path"] == "no_match"
        assert out_rows[3]["fallback_status"] == "NOT_FOUND"
        assert out_rows[3]["fallback_url"] == ""
        assert out_rows[3]["fallback_matched_name"] == ""

    def test_passes_metadata_to_verify_batch(self, tmp_path):
        """Audit should give verify_batch a parsed_citations list with the
        case_name / court / year that the input provides — that's what
        makes the search-fallback effective for misses.
        """
        rows = [
            {"cite": "763 F.3d 443", "case_name": "United States v. Fields",
             "court": "ca6", "year": "2014"},
        ]
        in_path = _build_input_csv(
            tmp_path, rows, ["cite", "case_name", "court", "year"]
        )
        out_path = tmp_path / "out.csv"

        captured = {}

        async def fake_verify_batch(citations, **kwargs):
            captured.setdefault("kwargs_per_call", []).append(kwargs)
            if kwargs.get("quick_only"):
                return [_not_found(rows[0]["cite"])]
            return [_verified_via_search(rows[0]["cite"])]

        with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
            instance = MockVerifier.return_value
            instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
            rc = audit_misses_main([
                str(in_path),
                "--column", "cite",
                "--name-column", "case_name",
                "--court-column", "court",
                "--year-column", "year",
                "--output", str(out_path),
            ])

        assert rc == 0
        # Both calls (quick + full) should have parsed_citations populated.
        for call_kwargs in captured["kwargs_per_call"]:
            parsed = call_kwargs.get("parsed_citations")
            assert parsed is not None
            assert len(parsed) >= 1
            assert parsed[0].case_name == "United States v. Fields"
            assert parsed[0].court == "ca6"
            assert parsed[0].year == 2014

    def test_skips_full_pass_when_all_resolved_via_quick(self, tmp_path):
        rows = [{"cite": "67 F.3d 309"}]
        in_path = _build_input_csv(tmp_path, rows, ["cite"])
        out_path = tmp_path / "out.csv"

        rc, captured = _patched_run(
            [
                str(in_path),
                "--column", "cite",
                "--output", str(out_path),
            ],
            [_verified_via_lookup(rows[0]["cite"])],
            # full pass would not be invoked; supply empty list
            [],
        )

        assert rc == 0
        # Only the quick call should have happened.
        assert len(captured["calls"]) == 1
        assert captured["calls"][0]["quick_only"] is True

        out_rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
        assert out_rows[0]["fallback_path"] == "citation-lookup"

    def test_dispatch_via_main_module(self, tmp_path, monkeypatch):
        import sys
        from citation_verifier import __main__ as cli_main

        rows = [{"cite": "999 F.99 1"}]
        in_path = _build_input_csv(tmp_path, rows, ["cite"])
        out_path = tmp_path / "out.csv"

        argv = [
            "citation-verifier",
            "audit-misses",
            str(in_path),
            "--column", "cite",
            "--output", str(out_path),
        ]
        monkeypatch.setattr(sys, "argv", argv)

        async def fake_verify_batch(citations, **kwargs):
            return [_not_found(rows[0]["cite"])]

        with patch("citation_verifier.__main__.CitationVerifier") as MockVerifier:
            instance = MockVerifier.return_value
            instance.verify_batch = AsyncMock(side_effect=fake_verify_batch)
            assert sys.argv[1] == "audit-misses"
            rc = cli_main.audit_misses_main(sys.argv[2:])

        assert rc == 0
        assert out_path.exists()
