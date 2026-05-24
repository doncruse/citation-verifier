"""Tests for the `audit-misses` CLI subcommand.

The audit takes a CSV of (mostly) NOT_FOUND citations, re-runs the
full production fallback pipeline (citation-lookup with chunking ->
opinion-search -> RECAP for federal courts), and writes a passthrough
CSV with new ``fallback_*`` columns including a ``fallback_path``
attribution column.

CitationVerifier is mocked so no API calls happen. Path attribution
logic is what these tests pin down.

Migrated to the v0.3 schema (Phase 1, Task 5). The legacy
"recap"-category Diagnostic is encoded in v0.3 via stage notes (the
audit's fallback-path classifier looks at ``resolution_path[-1].notes``
for a "recap" marker).
"""

from __future__ import annotations

import csv
from unittest.mock import AsyncMock, patch

import pytest

from citation_verifier.__main__ import audit_misses_main
from citation_verifier.models import (
    FinalIds,
    ParsedCitation,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
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
    stage_notes: str | None = None,
) -> VerificationResult:
    """Build a v0.3 VerificationResult.

    ``stage_notes`` is appended to the resolving-stage's ``notes`` field;
    the audit's RECAP-vs-opinion-search classifier reads it for the
    substring "recap".
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
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


def _not_found(citation: str) -> VerificationResult:
    return _make_result(
        citation=citation,
        status=Status.NOT_FOUND,
        confidence=0.0,
        stage_notes="No match in citation lookup",
    )


def _verified_via_lookup(citation: str, **kw) -> VerificationResult:
    """Citation-lookup recovery — verified-class with no RECAP marker."""
    return _make_result(
        citation=citation,
        status=Status.VERIFIED,
        confidence=1.0,
        case_name=kw.get("matched_case_name", "Found Case"),
        absolute_url=kw.get(
            "matched_url", "https://www.courtlistener.com/opinion/100/"
        ),
        cluster_id=kw.get("matched_cluster_id", 100),
        court=kw.get("matched_court", "ca9"),
        year=kw.get("matched_year", 1995),
    )


def _verified_via_search(citation: str, **kw) -> VerificationResult:
    """Opinion-search hit: no `recap` marker on the result.

    The old fixture used Status.LIKELY_REAL (dropped in v0.3). The audit's
    classifier only checks for verified-class status, so we use VERIFIED
    here — the test still pins ``fallback_status`` against the value, so
    we update the asserts below in lockstep.
    """
    return _make_result(
        citation=citation,
        status=Status.VERIFIED,
        confidence=0.85,
        case_name=kw.get("matched_case_name", "Search Hit Case"),
        absolute_url=kw.get(
            "matched_url", "https://www.courtlistener.com/opinion/200/"
        ),
        cluster_id=kw.get("matched_cluster_id", 200),
        court=kw.get("matched_court", "ca6"),
        year=kw.get("matched_year", 2014),
        stage_notes="We identified a likely match.",
    )


def _verified_via_recap(citation: str, **kw) -> VerificationResult:
    """RECAP hit: the resolving stage's notes mention RECAP."""
    return _make_result(
        citation=citation,
        status=Status.VERIFIED,
        confidence=0.7,
        case_name=kw.get("matched_case_name", "RECAP Docket"),
        absolute_url=kw.get(
            "matched_url", "https://www.courtlistener.com/docket/300/"
        ),
        cluster_id=kw.get("matched_cluster_id", 300),
        court=kw.get("matched_court", "dcd"),
        year=kw.get("matched_year", 2019),
        stage_notes="Found in RECAP (not in opinions database)",
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

        # Row 1: opinion-search recovery (v0.3 collapses LIKELY_REAL into VERIFIED)
        assert out_rows[1]["fallback_path"] == "opinion-search"
        assert out_rows[1]["fallback_status"] == "VERIFIED"
        assert out_rows[1]["fallback_court_id"] == "ca6"
        # v0.3 dropped matched_date; the writer falls back to parsed year.
        assert out_rows[1]["fallback_date_filed"] == "2014"

        # Row 2: RECAP recovery (resolving-stage notes mention recap)
        assert out_rows[2]["fallback_path"] == "RECAP"
        assert out_rows[2]["fallback_status"] == "VERIFIED"
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

    def test_retries_verification_incomplete_in_full_pass(self, tmp_path):
        """Phase 5 Task 7 (audit row C6): VERIFICATION_INCOMPLETE in the
        quick pass should be retried by the full pass, alongside NOT_FOUND.
        Per design §2.8, INCOMPLETE means the quick stage errored out
        (CL infra failure); the full pipeline's search-fallback may recover.
        """
        rows = [
            {"cite": "1 F.3d 1", "case_name": "Real v. Case",
             "court": "ca9", "year": "1995"},
            {"cite": "2 F.3d 2", "case_name": "Infra v. Failure",
             "court": "ca9", "year": "1995"},
            {"cite": "3 F.3d 3", "case_name": "Truly v. Missing",
             "court": "ca9", "year": "1995"},
        ]
        in_path = _build_input_csv(
            tmp_path, rows, ["cite", "case_name", "court", "year"]
        )
        out_path = tmp_path / "out.csv"

        # Quick pass: row 0 = VERIFIED (no retry needed),
        # row 1 = VERIFICATION_INCOMPLETE (must be retried),
        # row 2 = NOT_FOUND (must be retried).
        incomplete = _make_result(
            citation=rows[1]["cite"],
            status=Status.VERIFICATION_INCOMPLETE,
            confidence=None,
            stage_notes="HTTP 500 from citation lookup API",
        )
        quick_results = [
            _verified_via_lookup(rows[0]["cite"]),
            incomplete,
            _not_found(rows[2]["cite"]),
        ]
        # Full pass on the two retried rows: row 1 recovers via search,
        # row 2 stays NOT_FOUND.
        full_results = [
            _verified_via_search(rows[1]["cite"]),
            _not_found(rows[2]["cite"]),
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
        # Quick on all 3; full pass on the 2 retried (rows 1 and 2).
        assert len(captured["calls"]) == 2
        assert captured["calls"][1]["quick_only"] is False
        assert captured["calls"][1]["citations"] == [rows[1]["cite"], rows[2]["cite"]]

        out_rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
        # Row 1 (was INCOMPLETE in quick) now VERIFIED via search.
        assert out_rows[1]["fallback_status"] == "VERIFIED"
        assert out_rows[1]["fallback_path"] == "opinion-search"
