"""Tests for CourtListenerClient.get_opinion_text() and get_opinion_text_with_metadata()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from citation_verifier.client import CourtListenerClient


class TestSyncGetOpinionText:
    """Tests for sync get_opinion_text() mirroring the async version."""

    def _make_client(self):
        return CourtListenerClient(api_token="test-token")

    def test_opinion_url_returns_plain_text(self):
        """Opinion URL -> cluster API -> sub_opinions -> opinion API -> plain_text."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Obergefell v. Hodges",
                "date_filed": "2015-06-26",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/123/"
                ],
                "citations": [
                    {"volume": "576", "reporter": "U.S.", "page": "644"}
                ],
                "docket": "https://www.courtlistener.com/api/rest/v4/dockets/999/",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "This is the opinion text.",
                "html_with_citations": "",
            }
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "docket_number": "14-556",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/scotus/",
            }
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "Supreme Court of the United States",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp, docket_resp, court_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/opinion/123/obergefell-v-hodges/"
            )
            assert result == "This is the opinion text."

    def test_opinion_url_falls_back_to_html(self):
        """Falls back to stripped html_with_citations when plain_text is empty."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Test Case",
                "date_filed": "2020-01-01",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/456/"
                ],
                "citations": [],
                "docket": "",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "",
                "html_with_citations": "<p>This is <b>HTML</b> content.</p>",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/opinion/456/test-case/"
            )
            assert result is not None
            assert "HTML" in result
            assert "<p>" not in result  # HTML tags stripped

    def test_returns_none_for_empty_url(self):
        client = self._make_client()
        assert client.get_opinion_text("") is None

    def test_returns_none_for_unrecognized_url(self):
        client = self._make_client()
        assert client.get_opinion_text("https://example.com/something") is None

    def test_with_metadata_returns_dict(self):
        """get_opinion_text_with_metadata returns full metadata dict."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Obergefell v. Hodges",
                "date_filed": "2015-06-26",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/123/"
                ],
                "citations": [
                    {"volume": "576", "reporter": "U.S.", "page": "644"}
                ],
                "docket": "https://www.courtlistener.com/api/rest/v4/dockets/999/",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "Opinion text here.",
            }
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "docket_number": "14-556",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/scotus/",
            }
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "Supreme Court of the United States",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp, docket_resp, court_resp]

            result = client.get_opinion_text_with_metadata(
                "https://www.courtlistener.com/opinion/123/obergefell-v-hodges/"
            )
            assert result is not None
            assert result["text"] == "Opinion text here."
            assert result["case_name"] == "Obergefell v. Hodges"
            assert result["court"] == "Supreme Court of the United States"
            assert result["date_filed"] == "2015-06-26"
            assert result["docket_number"] == "14-556"
            assert "576 U.S. 644" in result["citations"]

    def test_docket_url_returns_text(self):
        """RECAP docket URL -> docket-entries API -> recap-document -> plain_text."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            entry_resp = MagicMock()
            entry_resp.json.return_value = {
                "results": [
                    {
                        "recap_documents": [
                            {"id": 789}
                        ]
                    }
                ]
            }
            doc_resp = MagicMock()
            doc_resp.json.return_value = {
                "plain_text": "Full document text from RECAP.",
            }
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "case_name": "Smith v. Jones",
                "docket_number": "1:20-cv-01234",
                "date_filed": "2020-03-15",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/ohsd/",
            }
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "U.S. District Court for the Southern District of Ohio",
            }
            mock_req.side_effect = [entry_resp, doc_resp, docket_resp, court_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/docket/5555/42/smith-v-jones/"
            )
            assert result == "Full document text from RECAP."

    def test_returns_none_when_no_text_available(self):
        """Returns None when opinion has no plain_text and no HTML."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Empty Case",
                "date_filed": "2020-01-01",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/999/"
                ],
                "citations": [],
                "docket": "",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "",
                "html_with_citations": "",
                "html": "",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/opinion/999/empty-case/"
            )
            assert result is None
