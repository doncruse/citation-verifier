"""Tests for the brief verification pipeline.

Migrated to the v0.3 schema (Phase 1, Task 4). The old top-level
``status``/``confidence``/``matched_*``/``diagnostics`` fields have been
replaced; ``_make_result`` now builds the v0.3 shape directly, and the
sibling-swap assertions read through ``final_ids`` and
``resolution_path[-1].notes``.
"""
import asyncio
import csv
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from citation_verifier.brief_pipeline import merge_claims, MergeStats, _normalize_quote_text, check_quotes, QuoteCheckStats
from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
)


@pytest.fixture
def workdir(tmp_path):
    """Set up a workdir with claims.csv and verification_results.csv."""
    # claims.csv — Phase 1 output
    claims = tmp_path / "claims.csv"
    claims.write_text(
        "page,proposition,cited_case\n"
        '21,"Courts defer to executive on security clearances.","Dep\'t of Navy v. Egan, 484 U.S. 518, 527 (1988)"\n'
        '22,"Same principle applies broadly.","Dep\'t of Navy v. Egan, 484 U.S. 518 (1988)"\n'
        '30,"Free speech applies.","Garcetti v. Ceballos, 547 U.S. 410 (2006)"\n'
        '35,"The Federalist No. 72","The Federalist No. 72"\n'
    )
    # verification_results.csv
    vr = tmp_path / "verification_results.csv"
    vr.write_text(
        "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
        '"Dep\'t of Navy v. Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,'
        'https://www.courtlistener.com/opinion/111990/egan/,'
        'Department of the Navy v. Egan,,\n'
        '"Garcetti v. Ceballos, 547 U.S. 410 (2006)",VERIFIED,1.0,'
        'https://www.courtlistener.com/opinion/145625/garcetti/,'
        'Garcetti v. Ceballos,,\n'
    )
    # opinions/
    opinions = tmp_path / "opinions"
    opinions.mkdir()
    (opinions / "Dept_of_Navy_v_Egan.txt").write_text("opinion text here")
    return tmp_path


class TestMergeClaims:
    def test_basic_merge(self, workdir):
        stats = merge_claims(workdir)
        assert stats.matched == 3  # 2 Egan rows + 1 Garcetti
        assert stats.unmatched == 1  # Federalist

        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        assert len(merged) == 4

        # Egan pinpoint row matched
        egan_row = merged[0]
        assert egan_row["cl_status"] == "VERIFIED"
        assert "egan" in egan_row["cl_url"].lower()
        assert egan_row["retrieved_case"] == "Department of the Navy v. Egan"

        # Non-case citation has empty verification fields
        fed_row = merged[3]
        assert fed_row["cl_status"] == ""

    def test_pinpoint_stripping(self, workdir):
        merge_claims(workdir)
        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        # Both Egan rows (with and without pinpoint) should match
        assert merged[0]["cl_url"] == merged[1]["cl_url"]

    def test_opinion_file_linked(self, workdir):
        stats = merge_claims(workdir)
        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        # Egan has opinion file, Garcetti doesn't (no file created in fixture)
        assert merged[0]["opinion_file"] != ""
        assert merged[2]["opinion_file"] == ""


# --- Helper for wave tests ---

def _make_result(status, url="", case_name=""):
    """Build a v0.3 VerificationResult for tests.

    When ``status`` is one of the VERIFIED_* statuses, emit a resolved
    resolution_path entry carrying ``case_name`` so brief_pipeline's CSV
    writer and download path can find it (mirrors verifier.py's
    ``_build_result`` shape).
    """
    is_verified = status in (
        Status.VERIFIED,
        Status.VERIFIED_PARTIAL,
        Status.VERIFIED_VIA_RECAP,
        Status.VERIFIED_DOCKET_ONLY,
    )
    cluster_id_match = None
    if url:
        import re as _re
        m = _re.search(r"/opinion/(\d+)/", url)
        if m:
            try:
                cluster_id_match = int(m.group(1))
            except ValueError:
                cluster_id_match = 123
        else:
            cluster_id_match = 123

    path = []
    if is_verified:
        path.append(
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={},
                raw_response_summary=(
                    {"case_name": case_name} if case_name else {}
                ),
                verdict=StageVerdict.resolved,
                confidence=1.0,
                notes=None,
                elapsed_ms=0,
            )
        )
    return VerificationResult(
        citation_as_written="test",
        parsed_citation=None,
        status=status,
        final_ids=FinalIds(
            cluster_id=cluster_id_match,
            opinion_id=None,
            docket_id=None,
            recap_document_id=None,
            absolute_url=url or None,
            text_source=None,
        ),
        resolution_path=path,
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


# --- Task 4: wave1 ---

class TestWave1:
    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave1_downloads_verified_cases(self, mock_verifier_cls, mock_client_cls, tmp_path):
        from citation_verifier.brief_pipeline import wave1_verify_and_download, Wave1Result

        citations = ["Case A, 100 U.S. 1 (2000)", "Case B, 200 U.S. 2 (2001)"]

        # verify_batch returns both as VERIFIED
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            _make_result(Status.VERIFIED, "https://cl/opinion/1/", "Case A"),
            _make_result(Status.VERIFIED, "https://cl/opinion/2/", "Case B"),
        ])

        # Client returns text for both
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(side_effect=[
            {"text": "Opinion A text", "case_name": "Case A", "format": "text",
             "citations": [], "court": "", "date_filed": "", "docket_number": ""},
            {"text": "Opinion B text", "case_name": "Case B", "format": "text",
             "citations": [], "court": "", "date_filed": "", "docket_number": ""},
        ])

        result = asyncio.run(wave1_verify_and_download(tmp_path, citations))

        assert isinstance(result, Wave1Result)
        assert len(result.miss_indices) == 0
        assert (tmp_path / "opinions").exists()
        assert result.download_stats["downloaded"] == 2

    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave1_swaps_short_order_for_substantive_sibling(
        self, mock_verifier_cls, mock_client_cls, tmp_path,
    ):
        """When the matched cluster is a short order (e.g. a vacatur order),
        the pipeline should swap to a sibling cluster on the same docket that
        carries the substantive merits opinion, and update matched_url in the
        result (so verification_results.csv reflects the swap).
        """
        from citation_verifier.brief_pipeline import wave1_verify_and_download

        citations = ["In re Hertz Corp., 2024 LEXIS 1 (2024)"]

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            _make_result(
                # Phase 1 collapses LIKELY_REAL/POSSIBLE_MATCH into VERIFIED.
                Status.VERIFIED,
                "https://www.courtlistener.com/opinion/10124964/hertz/",
                "In re Hertz",
            ),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.BASE_URL = "https://cl/api"

        short_order_text = "ORDER: the opinion is vacated. " * 20  # ~620 chars
        substantive_text = "PRECEDENTIAL opinion body. " * 200  # ~5400 chars

        # get_opinion_text_with_metadata: first returns short order (for the
        # original cluster), then substantive (for the sibling)
        mock_client.get_opinion_text_with_metadata = AsyncMock(side_effect=[
            {"text": short_order_text, "case_name": "In re Hertz",
             "format": "text", "citations": [], "court": "", "date_filed": "",
             "docket_number": ""},
            {"text": substantive_text, "case_name": "In re Hertz",
             "format": "text", "citations": [], "court": "", "date_filed": "",
             "docket_number": ""},
        ])
        # _request_with_retry: first returns the cluster (w/ docket), then
        # the list of clusters on that docket (original + one sibling)
        mock_client._request_with_retry = AsyncMock(side_effect=[
            {"docket": "https://cl/api/dockets/999/"},
            {"results": [
                {"id": 10124964, "absolute_url": "/opinion/10124964/hertz/"},
                {"id": 10265999, "absolute_url": "/opinion/10265999/hertz/"},
            ]},
        ])

        result = asyncio.run(wave1_verify_and_download(tmp_path, citations))

        assert result.download_stats["downloaded"] == 1
        # The swap should have updated final_ids.absolute_url and
        # final_ids.cluster_id.
        vr = result.results[0]
        assert "10265999" in (vr.final_ids.absolute_url or "")
        assert vr.final_ids.cluster_id == 10265999
        # And the swap note should be recorded in resolution_path[-1].notes
        # (Phase 1 uses the legacy diagnostic bridge for operational notes;
        # Phase 3 may add a sibling_swap WarningCategory).
        notes = vr.resolution_path[-1].notes or ""
        assert "swapped to sibling" in notes
        # verification_results.csv should also reflect the new URL
        vr_csv = (tmp_path / "verification_results.csv").read_text()
        assert "10265999" in vr_csv
        assert "10124964" not in vr_csv

    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave1_identifies_misses(self, mock_verifier_cls, mock_client_cls, tmp_path):
        from citation_verifier.brief_pipeline import wave1_verify_and_download, Wave1Result

        citations = ["Found, 100 U.S. 1 (2000)", "Missing, 200 U.S. 2 (2001)"]

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            _make_result(Status.VERIFIED, "https://cl/opinion/1/", "Found"),
            _make_result(Status.NOT_FOUND),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Opinion text", "case_name": "Found", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        result = asyncio.run(wave1_verify_and_download(tmp_path, citations))

        assert result.miss_indices == [1]
        assert result.download_stats["downloaded"] == 1


# --- Task 5: wave2 ---

class TestWave2:
    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave2_runs_fallback_for_misses(self, mock_verifier_cls, mock_client_cls, tmp_path):
        from citation_verifier.brief_pipeline import wave2_fallback_and_download, Wave2Result

        citations = ["Found, 100 U.S. 1 (2000)", "Miss1, 200 U.S. 2 (2001)", "Miss2, 300 U.S. 3 (2002)"]
        miss_indices = [1, 2]

        # verify_batch (full pipeline, not quick_only) resolves Miss1
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            # Phase 1 collapses LIKELY_REAL into VERIFIED.
            _make_result(Status.VERIFIED, "https://cl/opinion/10/", "Miss One"),
            _make_result(Status.NOT_FOUND),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Resolved opinion", "case_name": "Miss One", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        # Pre-existing verification_results.csv from wave1
        (tmp_path / "verification_results.csv").write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Found, 100 U.S. 1 (2000)",VERIFIED,1.0,https://cl/opinion/1/,Found,,\n'
        )
        (tmp_path / "opinions").mkdir(exist_ok=True)

        result = asyncio.run(wave2_fallback_and_download(tmp_path, citations, miss_indices))

        assert isinstance(result, Wave2Result)
        assert result.download_stats["downloaded"] == 1
        # verification_results.csv should now have 3 rows (1 from wave1 + 2 from wave2)
        vr = list(csv.DictReader((tmp_path / "verification_results.csv").open()))
        assert len(vr) == 3


# --- Task 6: full_pipeline ---

class TestFullPipeline:
    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_full_pipeline_runs_wave1_wave2_merge(self, mock_verifier_cls, mock_client_cls, tmp_path):
        """full_pipeline runs wave1 + wave2 + merge in sequence."""
        from citation_verifier.brief_pipeline import full_pipeline, PipelineResult

        # Set up claims.csv
        (tmp_path / "claims.csv").write_text(
            "page,proposition,cited_case\n"
            '1,"Some proposition.","Case A, 100 U.S. 1 (2000)"\n'
        )

        mock_verifier = mock_verifier_cls.return_value
        # wave1 (quick_only) finds it
        mock_verifier.verify_batch = AsyncMock(return_value=[
            _make_result(Status.VERIFIED, "https://cl/opinion/1/", "Case A"),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Opinion text", "case_name": "Case A", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        result = asyncio.run(full_pipeline(tmp_path, ["Case A, 100 U.S. 1 (2000)"]))

        assert isinstance(result, PipelineResult)
        # claims.csv should be merged
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["cl_status"] == "VERIFIED"


# --- Task 1: merge passthrough columns ---

class TestMergePassthroughColumns:
    def test_merge_preserves_quoted_text(self, tmp_path):
        """merge_claims passes through quoted_text column."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            'page,proposition,cited_case,quoted_text\n'
            '21,"Courts defer.","Egan, 484 U.S. 518 (1988)","[""defer to executive""]"\n'
            '30,"Free speech.","Garcetti, 547 U.S. 410 (2006)","[]"\n'
        )
        vr = tmp_path / "verification_results.csv"
        vr.write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,https://cl/1/,Egan,,\n'
            '"Garcetti, 547 U.S. 410 (2006)",VERIFIED,1.0,https://cl/2/,Garcetti,,\n'
        )
        (tmp_path / "opinions").mkdir()

        merge_claims(tmp_path)

        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quoted_text"] == '["defer to executive"]'
        assert merged[1]["quoted_text"] == "[]"

    def test_merge_preserves_quote_check(self, tmp_path):
        """merge_claims passes through quote_check and quote_check_worst."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            'page,proposition,cited_case,quoted_text,quote_check,quote_check_worst\n'
            '21,"Courts defer.","Egan, 484 U.S. 518 (1988)","[""defer""]",'
            '"[{""quote"": ""defer"", ""result"": ""VERBATIM"", ""similarity"": 0.95}]",VERBATIM\n'
        )
        vr = tmp_path / "verification_results.csv"
        vr.write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,https://cl/1/,Egan,,\n'
        )
        (tmp_path / "opinions").mkdir()

        merge_claims(tmp_path)

        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quote_check_worst"] == "VERBATIM"


# --- Task 2: _normalize_quote_text ---

class TestNormalizeQuoteText:
    def test_smart_quotes_to_straight(self):
        assert _normalize_quote_text("\u201cno desire\u201d") == '"no desire"'

    def test_collapses_whitespace(self):
        assert _normalize_quote_text("no   desire\n to") == "no desire to"

    def test_strips_bracketed_alterations(self):
        assert _normalize_quote_text("the [Defendant] must show") == "the must show"

    def test_strips_ellipses(self):
        assert _normalize_quote_text("first ... last") == "first last"
        assert _normalize_quote_text("first \u2026 last") == "first last"

    def test_initial_capital_bracket(self):
        """[T]he -> the (lowercase the revealed letter)."""
        assert _normalize_quote_text("[T]he court held") == "the court held"

    def test_combined(self):
        text = "\u201c[T]he court\u2019s [inherent] authority \u2026 extends\u201d"
        result = _normalize_quote_text(text)
        assert result == '"the court\'s authority extends"'


# --- Task 3: check_quotes ---

class TestCheckQuotes:
    def _setup_workdir(self, tmp_path, claims_text, opinion_text):
        """Helper: write claims.csv and an opinion file."""
        (tmp_path / "claims.csv").write_text(claims_text, encoding="utf-8")
        opinions = tmp_path / "opinions"
        opinions.mkdir(exist_ok=True)
        if opinion_text is not None:
            (opinions / "Test_Case.txt").write_text(opinion_text, encoding="utf-8")
        return tmp_path

    def test_verbatim_match(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""the court held that sanctions require bad faith""]",opinions/Test_Case.txt\n',
            "In this opinion, the court held that sanctions require bad faith under the statute.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open(encoding="utf-8")))
        checks = json.loads(merged[0]["quote_check"])
        assert len(checks) == 1
        assert checks[0]["result"] == "VERBATIM"
        assert checks[0]["similarity"] > 0.85
        assert merged[0]["quote_check_worst"] == "VERBATIM"

    def test_fabricated_quote(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""completely invented language not in the opinion at all""]",opinions/Test_Case.txt\n',
            "This opinion discusses sanctions under Rule 11 and the standard of review.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open(encoding="utf-8")))
        checks = json.loads(merged[0]["quote_check"])
        assert checks[0]["result"] == "FABRICATED"
        assert checks[0]["similarity"] < 0.6
        assert merged[0]["quote_check_worst"] == "FABRICATED"

    def test_no_quotes(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[]",opinions/Test_Case.txt\n',
            "Some opinion text.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open(encoding="utf-8")))
        assert merged[0]["quote_check"] == "[]"
        assert merged[0]["quote_check_worst"] == "NO_QUOTES"

    def test_no_opinion_file(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""some quote""]",""\n',
            None,
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open(encoding="utf-8")))
        assert merged[0]["quote_check"] == "[]"
        assert merged[0]["quote_check_worst"] == "NO_OPINION"

    def test_multiple_quotes_worst_wins(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)",'
            '"[""sanctions require bad faith"", ""totally fake quote here not in text""]",'
            'opinions/Test_Case.txt\n',
            "The court stated that sanctions require bad faith under the rule.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open(encoding="utf-8")))
        checks = json.loads(merged[0]["quote_check"])
        assert len(checks) == 2
        assert merged[0]["quote_check_worst"] == "FABRICATED"

    def test_stats_returned(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"P1","Test, 100 U.S. 1 (2000)","[""sanctions require bad faith""]",opinions/Test_Case.txt\n'
            '2,"P2","Test, 100 U.S. 1 (2000)","[]",opinions/Test_Case.txt\n',
            "The court held that sanctions require bad faith.",
        )
        stats = check_quotes(workdir)
        assert stats.total_claims == 2
        assert stats.checked == 1
        assert stats.no_quotes == 1


# --- metadata_check ---

from citation_verifier.brief_pipeline import metadata_check, MetadataCheckResult, generate_report


class TestMetadataCheck:
    def test_surfaces_syllabus_for_triage(self, tmp_path):
        """Syllabus data is included in output for LLM triage."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '3,"Prior settlement evidence is irrelevant.","Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",'
            'VERIFIED,"Tompkins v. Cyr",https://cl/1/,opinions/Tompkins.txt,"",'
            '"RICO; anti-abortion protesters; harassment; emotional distress"\n'
        )
        result = metadata_check(tmp_path)
        # Names match so no name_mismatch flag, but syllabus is surfaced
        assert result.name_mismatches == 0
        assert len(result.syllabus_items) == 1
        assert "RICO" in result.syllabus_items[0]["syllabus"]
        assert "settlement" in result.syllabus_items[0]["proposition"]

    def test_flags_name_mismatch(self, tmp_path):
        """When CL returns a different case name, flag it."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '3,"Some proposition.","State v. Carter, 100 So.3d 1 (La. 2020)",'
            'VERIFIED,"Stull v. Combustion Engineering",https://cl/1/,opinions/Stull.txt,'
            '"name: Name mismatch",""\n'
        )
        result = metadata_check(tmp_path)
        assert result.name_mismatches == 1
        assert "State v. Carter" in result.flagged_claims[0]["cited_case"]

    def test_flags_not_found(self, tmp_path):
        """NOT_FOUND citations are flagged for mandatory assessment."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '7,"Plaintiff has no duty.","Menges v. Cliffs, 2000 WL 765082 (E.D. La. 2000)",'
            'NOT_FOUND,"",,,,""\n'
        )
        result = metadata_check(tmp_path)
        assert result.not_found == 1

    def test_no_flags_on_clean_data(self, tmp_path):
        """Clean data with no syllabus produces no flags."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '6,"Bad faith required.","King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)",'
            'VERIFIED,"King v. Illinois Central Railroad",https://cl/1/,opinions/King.txt,"",""\n'
        )
        result = metadata_check(tmp_path)
        assert result.name_mismatches == 0
        assert result.not_found == 0
        assert len(result.flagged_claims) == 0
        assert len(result.syllabus_items) == 0


# --- generate_report ---


class TestGenerateReport:
    def test_generates_html_file(self, tmp_path):
        """generate_report reads claims.csv and produces report.html."""
        # Set up minimal claims.csv with assessment data
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,quote_check_worst,syllabus\n"
            '3,"Bad faith required.","King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)",'
            '"King v. Illinois Central Railroad","An adverse inference requires bad conduct.","Green",'
            '"https://cl/opinion/8437633/","VERIFIED","",opinions/King.txt,"[]","[]","NO_QUOTES",""\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "King.txt").write_text("opinion text")

        report_path = generate_report(
            tmp_path,
            title="Test Brief",
            case_name="Smith v. Jones",
            case_number="No. 1:24-CV-00001",
        )

        assert report_path.exists()
        html = report_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "Smith v. Jones" in html
        assert "King v. Ill" in html

    def test_agent_authored_blocks_preferred_over_fallback(self, tmp_path):
        """When the agent authors brief_block and opinion_block, the
        template renders those verbatim instead of the deterministic
        brief_sentence / matched_passage fallbacks."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,brief_block,opinion_block,"
            "finding_analysis,badge_label\n"
            '4,"Prop.","McMurtrey, 704 F.3d 502","McMurtrey","","Yellow",'
            '"https://cl/1/","VERIFIED","",opinions/McMurtrey.txt,'
            '"[""reasons to doubt the truth""]",'
            '"[{""quote"": ""reasons to doubt the truth"", ""result"": ""CLOSE"", '
            '""similarity"": 0.72, ""matched_passage"": ""obvious reasons to doubt the veracity""}]",'
            '"CLOSE","",'
            # brief_sentence (deterministic fallback, should NOT appear when brief_block wins)
            '"AGENT SHOULD OVERRIDE THIS sentence.",'
            # brief_block (agent authored)
            '"Reckless disregard is shown where the officer had reasons to doubt the truth. Cite: McMurtrey.",'
            # opinion_block (agent authored — different from matched_passage)
            '"The court spoke of doubting the veracity, not the truth.",'
            '"One-sentence agent analysis.","Reworded -- not a verbatim quote"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "McMurtrey.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # Agent-authored blocks appear
        assert "Reckless disregard is shown where the officer" in html
        assert "The court spoke of doubting the veracity" in html
        # Deterministic fallbacks must NOT appear when agent authored
        assert "AGENT SHOULD OVERRIDE THIS" not in html
        # matched_passage is not rendered when agent authored opinion_block
        assert "obvious reasons to doubt the veracity" not in html

    def test_empty_opinion_block_omits_the_box(self, tmp_path):
        """When the agent leaves opinion_block empty intentionally, the
        green box is omitted (no fallback rendering)."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,brief_block,opinion_block,"
            "finding_analysis,badge_label\n"
            '3,"Prop.","Case, 1 U.S. 1","Case","","Red",'
            '"https://cl/1/","VERIFIED","",opinions/Case.txt,'
            '"[]","[]","NO_QUOTES","","",'
            '"Brief says X.","",'
            '"The case is about Y, not X.","Not supported by cited case"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "Case.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # brief_block rendered
        assert "Brief says X." in html
        # No "Actual language in opinion" section when agent left it empty
        # AND there's no matched_passage fallback
        assert "Actual language in opinion" not in html

    def test_finding_analysis_is_rendered_as_prose(self, tmp_path):
        """finding_analysis is the agent's prose block. Paragraphs separated
        by blank lines render as <p> tags."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,finding_analysis,badge_label\n"
            '3,"Generic proposition.","Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",'
            '"Tompkins v. Cyr","","Red",'
            '"https://cl/opinion/19782/tompkins-v-cyr/","VERIFIED","",opinions/Tompkins.txt,'
            '"[]","[]","NO_QUOTES","",'
            '"Courts hold that prior settlement evidence is irrelevant. See Tompkins v. Cyr.",'
            '"Tompkins v. Cyr is a civil RICO case about anti-abortion protesters. '
            'The phrase \'consequential fact\' does not appear in the opinion.\n\n'
            "This looks like a fabricated attribution.\","
            '"Not supported by cited case"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "Tompkins.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # brief_sentence is rendered under "What the brief claims:"
        assert "prior settlement evidence is irrelevant" in html
        assert "What the brief claims" in html
        # finding_analysis appears with both paragraphs
        assert "anti-abortion protesters" in html
        assert "fabricated attribution" in html
        # Two paragraphs → rendered as two <p> tags inside .analysis
        assert '<div class="analysis">' in html
        assert html.count('<p>') >= 2

    def test_legacy_opinion_text_and_explanation_fallback(self, tmp_path):
        """Old schema (opinion_text + explanation) still renders when
        finding_analysis is absent — lets pre-existing briefs regenerate."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,opinion_text,explanation,badge_label\n"
            '3,"Prop.","Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",'
            '"Tompkins v. Cyr","","Red",'
            '"https://cl/opinion/19782/tompkins-v-cyr/","VERIFIED","",opinions/Tompkins.txt,'
            '"[]","[]","NO_QUOTES","",'
            '"This case is about anti-abortion protesters under RICO.",'
            '"Complete subject matter mismatch.",'
            '"Not supported by cited case"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "Tompkins.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # Both legacy fields appear, joined into the single analysis block
        assert "anti-abortion protesters" in html
        assert "Complete subject matter mismatch" in html

    def test_brief_sentence_bolds_quoted_strings(self, tmp_path):
        """When brief_sentence contains a quoted_string, the string is
        wrapped in <strong> so the reader sees what the brief attributed."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,finding_analysis,badge_label\n"
            '2,"Prop.","Case, 100 U.S. 1 (2000)","Case","","Red",'
            '"https://cl/1/","VERIFIED","",opinions/Case.txt,'
            '"[""obvious reasons to doubt""]","[]","FABRICATED","",'
            '"Reckless disregard means obvious reasons to doubt. Case, 100 U.S. 1.",'
            '"Agent analysis.","Quote not found in opinion"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "Case.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        assert "<strong>obvious reasons to doubt</strong>" in html

    def test_matched_passage_below_threshold_is_hidden(self, tmp_path):
        """Passages below the 0.65 similarity floor are junk; hide them."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,finding_analysis,badge_label\n"
            '3,"Prop.","Case, 100 U.S. 1","Case","","Red",'
            '"https://cl/1/","VERIFIED","",opinions/Case.txt,'
            '"[""fabricated quote""]",'
            '"[{""quote"": ""fabricated quote"", ""result"": ""FABRICATED"", '
            '""similarity"": 0.55, ""matched_passage"": ""adjust the lodestar upward""}]",'
            '"FABRICATED","","","Analysis.","Quote not found in opinion"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "Case.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # Junk passage must not appear
        assert "adjust the lodestar upward" not in html
        assert "Actual language in opinion" not in html

    def test_matched_passage_above_threshold_is_shown(self, tmp_path):
        """Passages at or above 0.65 similarity are shown."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,finding_analysis,badge_label\n"
            '4,"Prop.","McMurtrey, 704 F.3d 502","McMurtrey","","Yellow",'
            '"https://cl/1/","VERIFIED","",opinions/McMurtrey.txt,'
            '"[""reasons to doubt the truth""]",'
            '"[{""quote"": ""reasons to doubt the truth"", ""result"": ""CLOSE"", '
            '""similarity"": 0.72, ""matched_passage"": ""obvious reasons to doubt the veracity""}]",'
            '"CLOSE","","","Reworded.","Reworded -- not a verbatim quote"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "McMurtrey.txt").write_text("opinion text")

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        assert "obvious reasons to doubt the veracity" in html
        assert "Actual language in opinion" in html

    def test_unable_to_verify_groups_by_citation(self, tmp_path):
        """Same unavailable case cited for 3 propositions = one card, not
        three."""
        claims = tmp_path / "claims.csv"
        rows = []
        for page, prop in [(2, "Prop A"), (3, "Prop B"), (14, "Prop C")]:
            rows.append(
                f'{page},"{prop}","Holleman v. Zatecky, 951 F.2d 873 (7th Cir. 1991)",'
                f'"","","Red","","NOT_FOUND","","","[]","[]","NO_QUOTES","","","",""\n'
            )
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,"
            "quote_check_worst,syllabus,brief_sentence,finding_analysis,badge_label\n"
            + "".join(rows)
        )
        (tmp_path / "opinions").mkdir()

        report_path = generate_report(tmp_path, title="Test")
        html = report_path.read_text(encoding="utf-8")

        # Exactly one unable-to-verify card (one <details id="finding-uv-*">)
        assert html.count('id="finding-uv-') == 1
        # Badge appears once
        assert html.count('Unable to verify -- opinion text unavailable') == 1
        # All three propositions listed inside the card
        assert "Prop A" in html
        assert "Prop B" in html
        assert "Prop C" in html
        # Count suffix shows how many times cited
        assert "cited 3" in html

