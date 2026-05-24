"""Tests for HTML report generation."""
import pytest
from citation_verifier.report_template import generate_report_html


@pytest.fixture
def sample_report_data():
    """Minimal report data for testing."""
    return {
        "title": "Test Brief",
        "case_name": "Smith v. Jones",
        "case_number": "No. 1:24-CV-00001 (S.D. Ohio)",
        "filed_date": "January 1, 2026",
        "report_date": "April 15, 2026",
        "findings": [
            {
                "id": "finding-1",
                "page": "3",
                "case_name": "Tompkins v. Cyr",
                "citation": "202 F.3d 770, 787 (5th Cir. 2000)",
                "cl_url": "https://www.courtlistener.com/opinion/19782/tompkins-v-cyr/",
                "severity": "red",
                "badge_label": "Not supported by cited case",
                "brief_block": "Courts hold that prior settlement evidence is irrelevant.",
                "opinion_block": "This case is about anti-abortion protesters.",
                "explanation": "Complete subject matter mismatch.",
            },
        ],
        "verified": [
            {
                "page": "6",
                "case_name": "King v. Illinois Cent. R.R.",
                "citation": "337 F.3d 550, 556 (5th Cir. 2003)",
                "cl_url": "https://www.courtlistener.com/opinion/8437633/",
                "proposition": "Spoliation requires bad faith.",
                "badge_label": "Supported",
                "supporting_language": "An adverse inference is predicated on bad conduct.",
            },
        ],
        "unable_to_verify": [
            {
                "id": "finding-uv-1",
                "page": "7",
                "case_name": "Menges v. Cliffs Drilling Co.",
                "citation": "2000 WL 765082 (E.D. La. 2000)",
                "brief_text": "Plaintiff did not have a duty to delay surgery.",
                "explanation": "WestLaw-only citation, not in CourtListener.",
            },
        ],
        "retrieved_opinions": [
            {"case_name": "Tompkins v. Cyr", "citation": "202 F.3d 770", "cluster_id": "19782"},
            {"case_name": "King v. Illinois Cent. R.R.", "citation": "337 F.3d 550", "cluster_id": "8437633"},
        ],
        "unavailable_opinions": [
            {"case_name": "Menges v. Cliffs Drilling Co.", "citation": "2000 WL 765082", "reason": "WestLaw-only"},
        ],
    }


class TestReportGeneration:
    def test_returns_valid_html(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_case_metadata(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Smith v. Jones" in html
        assert "No. 1:24-CV-00001" in html

    def test_contains_red_finding(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Tompkins v. Cyr" in html
        assert "Not supported by cited case" in html
        assert "anti-abortion protesters" in html

    def test_contains_verified_section(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "King v. Illinois Cent. R.R." in html
        assert "Spoliation requires bad faith" in html

    def test_contains_unable_to_verify(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Menges v. Cliffs Drilling Co." in html
        assert "Unable to verify" in html

    def test_contains_methodology(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Methodology" in html
        assert "retrieved from CourtListener" in html
        assert "not available on CourtListener" in html

    def test_dashboard_counts(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        # Should have counts for findings, verified, unable
        assert "Serious issues" in html or "serious issue" in html.lower()

    def test_expand_collapse_controls(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "expandAll" in html
        assert "collapseAll" in html

    def test_empty_findings(self, sample_report_data):
        """Report with no issues should show all-clear banner."""
        sample_report_data["findings"] = []
        html = generate_report_html(sample_report_data)
        assert "No serious issues found" in html
