"""Tests for HTML opinion text retrieval."""
import pytest
from unittest.mock import patch, MagicMock
from citation_verifier.client import CourtListenerClient


class TestPreferHtml:
    """get_opinion_text_with_metadata with prefer_html=True."""

    def _mock_cluster(self, sub_opinion_id="123", case_name="Test v. Case",
                      plain_text="", html_with_citations="", html=""):
        """Build mock responses for cluster -> opinion chain."""
        cluster_resp = MagicMock()
        cluster_resp.json.return_value = {
            "sub_opinions": [f"https://www.courtlistener.com/api/rest/v4/opinions/{sub_opinion_id}/"],
            "case_name": case_name,
            "citations": [],
            "date_filed": "2020-01-01",
            "docket_number": "1:20-cv-00001",
        }
        opinion_resp = MagicMock()
        opinion_resp.json.return_value = {
            "plain_text": plain_text,
            "html_with_citations": html_with_citations,
            "html": html,
        }
        return [cluster_resp, opinion_resp]

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_prefer_html_returns_html_when_available(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text version",
            html_with_citations='<p>HTML with <a href="/opinion/456/">cited case</a></p>',
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert "<a href" in result["text"]
        assert result["format"] == "html"

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_prefer_html_falls_back_to_plain_text(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text only",
            html_with_citations="",
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert result["text"] == "Plain text only"
        assert result["format"] == "text"

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_default_prefer_html_false_returns_plain_text(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text version",
            html_with_citations='<p>HTML version</p>',
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
        )
        assert result is not None
        assert "<p>" not in result["text"]
        assert result["format"] == "text"


class TestPdfFallback:
    """Download PDF when no text or HTML available."""

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_returns_pdf_bytes_when_no_text(self, mock_req):
        cluster_resp = MagicMock()
        cluster_resp.json.return_value = {
            "sub_opinions": ["https://www.courtlistener.com/api/rest/v4/opinions/123/"],
            "case_name": "Test v. Case",
            "citations": [],
            "date_filed": "2020-01-01",
            "docket_number": "1:20-cv-00001",
            "filepath_pdf_with_extracted_text": "recap/gov.uscourts.test/test.pdf",
        }
        opinion_resp = MagicMock()
        opinion_resp.json.return_value = {
            "plain_text": "",
            "html_with_citations": "",
            "html": "",
        }
        pdf_resp = MagicMock()
        pdf_resp.content = b"%PDF-1.4 fake pdf content"
        pdf_resp.status_code = 200
        mock_req.side_effect = [cluster_resp, opinion_resp, pdf_resp]

        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert result["format"] == "pdf"
        assert result["pdf_bytes"] == b"%PDF-1.4 fake pdf content"
