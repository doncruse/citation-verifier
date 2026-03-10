"""Tests for the brief verification pipeline."""
import asyncio
import csv
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from citation_verifier.brief_pipeline import merge_claims, MergeStats, _normalize_quote_text
from citation_verifier.models import VerificationResult, VerificationStatus, Diagnostic


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
    return VerificationResult(
        input_citation="test",
        status=status,
        confidence=1.0 if status == VerificationStatus.VERIFIED else 0.0,
        matched_url=url,
        matched_case_name=case_name,
        matched_cluster_id=123 if url else None,
        diagnostics=[],
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
            _make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Case A"),
            _make_result(VerificationStatus.VERIFIED, "https://cl/opinion/2/", "Case B"),
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
    def test_wave1_identifies_misses(self, mock_verifier_cls, mock_client_cls, tmp_path):
        from citation_verifier.brief_pipeline import wave1_verify_and_download, Wave1Result

        citations = ["Found, 100 U.S. 1 (2000)", "Missing, 200 U.S. 2 (2001)"]

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            _make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Found"),
            _make_result(VerificationStatus.NOT_FOUND),
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
            _make_result(VerificationStatus.LIKELY_REAL, "https://cl/opinion/10/", "Miss One"),
            _make_result(VerificationStatus.NOT_FOUND),
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
            _make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Case A"),
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
