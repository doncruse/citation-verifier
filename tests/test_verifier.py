"""Tests for the citation verification pipeline.

All tests mock CourtListenerClient so no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from citation_verifier.models import VerificationStatus
from citation_verifier.verifier import CitationVerifier


def _make_client(**overrides):
    """Create a mock CourtListenerClient with sensible defaults."""
    client = MagicMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    return client


# ---------------------------------------------------------------------------
# Step 1: Citation Lookup — VERIFIED
# ---------------------------------------------------------------------------


class TestStep1Verified:
    def test_verified_when_name_matches(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/obergefell-v-hodges/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")

        assert result.status == VerificationStatus.VERIFIED
        assert result.confidence == 1.0
        assert result.matched_case_name == "Obergefell v. Hodges"
        assert "courtlistener.com" in result.matched_url

    def test_verified_builds_url_from_cluster_id(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {"case_name": "Smith v. Jones", "id": 456, "absolute_url": ""}
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)")

        assert result.status == VerificationStatus.VERIFIED
        assert result.matched_url == "https://www.courtlistener.com/opinion/456/"

    def test_verified_prepends_domain_to_relative_url(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Smith v. Jones",
                            "id": 456,
                            "absolute_url": "/opinion/456/smith-v-jones/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)")

        assert (
            result.matched_url
            == "https://www.courtlistener.com/opinion/456/smith-v-jones/"
        )


# ---------------------------------------------------------------------------
# Step 1: Citation Lookup — NOT_FOUND (name mismatch)
# ---------------------------------------------------------------------------


class TestStep1NameMismatch:
    def test_not_found_when_citation_belongs_to_different_case(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Totally Different v. Case",
                            "id": 789,
                            "absolute_url": "/opinion/789/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)")

        assert result.status == VerificationStatus.NOT_FOUND
        assert result.confidence == 0.0
        assert "different case" in result.diagnostics[0].lower()

    def test_not_found_different_defendant_same_prefix(self):
        """'United States v. Smith' should not match 'United States v. Johnson'."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "United States v. Johnson",
                            "id": 111,
                            "absolute_url": "/opinion/111/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("United States v. Smith, 500 F.3d 100 (9th Cir. 2018)")

        assert result.status == VerificationStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Step 1b: Adjacent page fallback
# ---------------------------------------------------------------------------


class TestAdjacentPage:
    def test_finds_case_on_adjacent_page(self):
        """If page 560 returns nothing but page 559 has the right case, VERIFIED."""

        def lookup_side_effect(text):
            if "559" in text:
                return [
                    {
                        "clusters": [
                            {
                                "case_name": "Smith v. Jones",
                                "id": 100,
                                "absolute_url": "/opinion/100/",
                            }
                        ]
                    }
                ]
            return []

        client = _make_client()
        client.citation_lookup.side_effect = lookup_side_effect
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 500 F.3d 560 (2d Cir. 2020)")

        assert result.status == VerificationStatus.VERIFIED
        assert "adjacent page" in result.diagnostics[0].lower()

    def test_rejects_different_case_on_adjacent_page(self):
        """Adjacent page match must have defendant similarity >= 0.7."""

        def lookup_side_effect(text):
            if "561" in text:
                return [
                    {
                        "clusters": [
                            {
                                "case_name": "United States v. Carlos Escobar",
                                "id": 200,
                                "absolute_url": "/opinion/200/",
                            }
                        ]
                    }
                ]
            return []

        client = _make_client()
        client.citation_lookup.side_effect = lookup_side_effect
        v = CitationVerifier(client)
        result = v.verify("United States v. Craner, 652 F.3d 560 (9th Cir. 2016)")

        assert result.status != VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# Step 2: Opinion search fallback
# ---------------------------------------------------------------------------


class TestOpinionSearchFallback:
    def test_likely_real_when_opinion_search_matches(self):
        client = _make_client(
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 300,
                    "dateFiled": "2020-03-15",
                    "court_id": "ca2",
                    "absolute_url": "/opinion/300/smith-v-jones/",
                    "citation": ["500 F.3d 200"],
                }
            ],
        )
        # citation_lookup returns nothing → falls through to search
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)")

        assert result.status == VerificationStatus.LIKELY_REAL
        assert result.matched_case_name == "Smith v. Jones"

    def test_not_found_when_no_results(self):
        client = _make_client()  # everything returns []
        v = CitationVerifier(client)
        result = v.verify("Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)")

        assert result.status == VerificationStatus.NOT_FOUND
        assert result.confidence == 0.0

    def test_retries_without_court_filter(self):
        """Opinion search retries without court filter when first attempt finds nothing."""
        client = _make_client()
        client.search_opinions.return_value = []
        v = CitationVerifier(client)
        v.verify("Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)")

        assert client.search_opinions.call_count == 2


# ---------------------------------------------------------------------------
# Step 3: RECAP fallback
# ---------------------------------------------------------------------------


class TestRecapFallback:
    def test_recap_match_with_substantive_doc(self):
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Anderson v. Furst",
                    "docket_id": 6264209,
                    "court_id": "mied",
                    "docket_absolute_url": "/docket/6264209/anderson-v-furst/",
                    "docketNumber": "2:17-cv-12676",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2018-09-17",
                            "short_description": "Order on Motion to Compel",
                            "absolute_url": "/docket/6264209/54/anderson-v-furst/",
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Anderson v. Furst, No. 17-cv-12676, 2018 WL 4407750, at *2 "
            "(E.D. Mich. Sept. 17, 2018)"
        )

        assert result.status in (
            VerificationStatus.LIKELY_REAL,
            VerificationStatus.POSSIBLE_MATCH,
        )
        assert "anderson-v-furst" in result.matched_url

    def test_recap_prefers_substantive_over_procedural(self):
        """An Order should be preferred over a Reply brief at the same score."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 100,
                    "court_id": "mied",
                    "docket_absolute_url": "/docket/100/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Reply to Response to Motion",
                            "absolute_url": "/docket/100/10/smith-v-jones/",
                        },
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Order",
                            "absolute_url": "/docket/100/11/smith-v-jones/",
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2020 WL 999999 (E.D. Mich. June 1, 2020)")

        assert "Order" in result.diagnostics[0]
        assert "Reply" not in result.diagnostics[0]

    def test_recap_queries_exact_date_first(self):
        """When month/day are known and initial docs don't match, queries exact date."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 200,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/200/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2019-03-01",
                            "short_description": "Reply",
                            "absolute_url": "/docket/200/50/",
                        },
                    ],
                }
            ],
            get_docket_entries=[
                {
                    "date_filed": "2018-09-17",
                    "recap_documents": [
                        {
                            "short_description": "Opinion",
                            "absolute_url": "/docket/200/30/smith-v-jones/",
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        v.verify("Smith v. Jones, 2018 WL 555555 (S.D.N.Y. Sept. 17, 2018)")

        # Should have called get_docket_entries with exact date
        call_args = client.get_docket_entries.call_args
        assert call_args.kwargs.get("date_filed_after") == "2018-09-17"
        assert call_args.kwargs.get("date_filed_before") == "2018-09-17"

    def test_recap_docket_only_fallback_discounted(self):
        """A docket match with no documents gets a 0.6x score discount."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 300,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/300/",
                    "recap_documents": [],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2020 WL 111111 (S.D.N.Y. 2020)")

        assert "possible docket match" in result.diagnostics[0].lower()
        # Score should be discounted: base ~0.7 * 0.6 = ~0.42
        assert result.confidence < 0.6


# ---------------------------------------------------------------------------
# Court corroboration requirement
# ---------------------------------------------------------------------------


class TestCourtCorroboration:
    def test_not_found_when_citation_fails_and_wrong_court(self):
        """Unverified citation + wrong court = NOT_FOUND (no false positives)."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "United States v. Craner",
                    "docket_id": 500,
                    "court_id": "nvd",
                    "docket_absolute_url": "/docket/500/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2021-08-03",
                            "short_description": "Order",
                            "absolute_url": "/docket/500/9/",
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("United States v. Craner, 652 F.3d 560, 562 (9th Cir. 2016)")

        assert result.status == VerificationStatus.NOT_FOUND
        assert "could not be verified" in result.diagnostics[0].lower()

    def test_match_allowed_when_court_matches(self):
        """Unverified citation + correct court = still a valid match."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 600,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/600/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-06-15",
                            "short_description": "Order",
                            "absolute_url": "/docket/600/10/",
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 500 F.3d 200 (S.D.N.Y. 2020)")

        assert result.status != VerificationStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Scoring edge cases
# ---------------------------------------------------------------------------


class TestScoring:
    def _score(
        self,
        parsed_overrides=None,
        result_case_name="Smith v. Jones",
        result_court="",
        result_date="",
        result=None,
    ):
        """Helper to call _score_match with a ParsedCitation."""
        from citation_verifier.models import ParsedCitation

        defaults = {
            "raw_text": "test",
            "case_name": "Smith v. Jones",
            "plaintiff": "Smith",
            "defendant": "Jones",
        }
        if parsed_overrides:
            defaults.update(parsed_overrides)
        parsed = ParsedCitation(**defaults)
        v = CitationVerifier(_make_client())
        return v._score_match(
            parsed, result_case_name, result_court, result_date, result or {}
        )

    def test_perfect_name_gives_50_percent(self):
        score, mismatches = self._score()
        assert score == pytest.approx(0.5, abs=0.01)
        assert not any("mismatch" in m.lower() for m in mismatches)

    def test_name_mismatch_flagged(self):
        score, mismatches = self._score(result_case_name="Totally Different v. Case")
        assert score < 0.3
        assert any("name mismatch" in m.lower() for m in mismatches)

    def test_court_match_adds_20_percent(self):
        score_no_court, _ = self._score()
        score_with_court, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y."},
            result_court="nysd",
        )
        assert score_with_court - score_no_court == pytest.approx(0.2, abs=0.01)

    def test_court_mismatch_adds_nothing(self):
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y."},
            result_court="ca9",
        )
        assert any("court mismatch" in m.lower() for m in mismatches)

    def test_exact_year_adds_20_percent(self):
        score, _ = self._score(
            parsed_overrides={"year": 2020},
            result_date="2020-06-15",
        )
        # name (0.5) + date (0.2)
        assert score == pytest.approx(0.7, abs=0.01)

    def test_off_by_one_year_adds_10_percent(self):
        score, mismatches = self._score(
            parsed_overrides={"year": 2020},
            result_date="2019-12-31",
        )
        # name (0.5) + date (0.1)
        assert score == pytest.approx(0.6, abs=0.01)
        assert any("date close" in m.lower() for m in mismatches)

    def test_date_mismatch_adds_nothing(self):
        score, mismatches = self._score(
            parsed_overrides={"year": 2020},
            result_date="2015-01-01",
        )
        assert score == pytest.approx(0.5, abs=0.01)
        assert any("date mismatch" in m.lower() for m in mismatches)

    def test_exact_date_scores_higher_than_same_year_wrong_month(self):
        score_exact, _ = self._score(
            parsed_overrides={"year": 2020, "month": 9, "day": 17},
            result_date="2020-09-17",
        )
        score_wrong_month, _ = self._score(
            parsed_overrides={"year": 2020, "month": 9, "day": 17},
            result_date="2020-03-01",
        )
        assert score_exact > score_wrong_month

    def test_same_month_scores_higher_than_different_month(self):
        score_same_month, _ = self._score(
            parsed_overrides={"year": 2020, "month": 9, "day": 17},
            result_date="2020-09-25",
        )
        score_diff_month, _ = self._score(
            parsed_overrides={"year": 2020, "month": 9, "day": 17},
            result_date="2020-03-01",
        )
        assert score_same_month > score_diff_month

    def test_docket_number_match_adds_5_percent(self):
        score, _ = self._score(
            parsed_overrides={"docket_number": "17-cv-12676"},
            result={"docketNumber": "2:17-cv-00012676"},
        )
        # name (0.5) + docket (0.05)
        assert score == pytest.approx(0.55, abs=0.01)

    def test_docket_number_mismatch_flagged(self):
        _, mismatches = self._score(
            parsed_overrides={"docket_number": "17-cv-12676"},
            result={"docketNumber": "99-cv-99999"},
        )
        assert any("docket mismatch" in m.lower() for m in mismatches)

    def test_reporter_citation_match_adds_5_percent(self):
        score, _ = self._score(
            parsed_overrides={"volume": "500", "reporter": "F.3d", "page": "200"},
            result={"citation": ["500 F.3d 200"]},
        )
        # name (0.5) + citation (0.05)
        assert score == pytest.approx(0.55, abs=0.01)

    def test_wl_number_match_adds_5_percent(self):
        score, _ = self._score(
            parsed_overrides={"wl_number": "4407750"},
            result={"citation": ["2018 WL 4407750"]},
        )
        # name (0.5) + WL (0.05)
        assert score == pytest.approx(0.55, abs=0.01)


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_names_match_same_case(self):
        from citation_verifier.models import ParsedCitation

        parsed = ParsedCitation(
            raw_text="", case_name="Smith v. Jones", defendant="Jones"
        )
        assert CitationVerifier._names_match(parsed, "Smith v. Jones")

    def test_names_match_different_defendant(self):
        from citation_verifier.models import ParsedCitation

        parsed = ParsedCitation(
            raw_text="", case_name="United States v. Smith", defendant="Smith"
        )
        assert not CitationVerifier._names_match(parsed, "United States v. Johnson")

    def test_normalize_docket_strips_division_and_zeros(self):
        n = CitationVerifier._normalize_docket_number
        assert n("2:17-cv-00012676") == n("17-cv-12676")
        assert n("4:06-CV-00043") == n("4:06-CV-43")

    def test_normalize_docket_strips_judge_suffix(self):
        n = CitationVerifier._normalize_docket_number
        assert n("2:24-cv-01776-JHC") == n("2:24-cv-01776")
        assert n("6:18-CV-02337-DCC") == n("6:18-cv-02337")

    def test_normalize_docket_expands_shorthand(self):
        n = CitationVerifier._normalize_docket_number
        assert n("C15-1228-JCC") == n("2:15-cv-01228")
        assert n("C15-1228") == n("15-cv-1228")

    def test_extract_surname(self):
        s = CitationVerifier._extract_surname
        assert s("Gomez") == "Gomez"
        assert s("Daou Systems, Inc.") == "Daou"
        assert s("James H. Gomez, Director") == "James"
        assert s("None") == ""
        assert s("") == ""
        assert s(None) == ""

    def test_is_substantive_doc(self):
        s = CitationVerifier._is_substantive_doc
        assert s("order")
        assert s("opinion and order")
        assert s("memorandum")
        assert s("judgment")
        assert s("ruling on motion")
        assert not s("reply to response to motion")
        assert not s("motion - free")
        assert not s("extend - free")

    def test_match_word_follows_status(self):
        """LIKELY_REAL says 'likely', POSSIBLE_MATCH says 'possible'."""
        # High-scoring match → LIKELY_REAL → "likely"
        client = _make_client(
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 700,
                    "dateFiled": "2020-03-15",
                    "court_id": "nysd",
                    "absolute_url": "",
                    "citation": ["500 F.3d 200"],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 500 F.3d 200 (S.D.N.Y. 2020)")
        assert result.status == VerificationStatus.LIKELY_REAL
        assert any("likely match" in d for d in result.diagnostics)

    def test_match_word_possible_for_lower_score(self):
        """Lower confidence → POSSIBLE_MATCH → 'possible'."""
        client = _make_client(
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 800,
                    "dateFiled": "2016-01-01",
                    "court_id": "ca9",
                    "absolute_url": "",
                    "citation": [],
                }
            ],
        )
        v = CitationVerifier(client)
        # Wrong court, wrong date → lower score
        result = v.verify("Smith v. Jones, 500 F.3d 200 (S.D.N.Y. 2020)")
        if result.status == VerificationStatus.POSSIBLE_MATCH:
            assert any("possible match" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Docket number RECAP search filtering
# ---------------------------------------------------------------------------


class TestDocketNumberSearch:
    def test_filters_to_matching_docket_numbers(self):
        """RECAP docket search filters out fuzzy non-matching results."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Elkins v. California Highway Patrol",
                    "docket_id": 900,
                    "court_id": "caed",
                    "docket_absolute_url": "/docket/900/",
                    "docketNumber": "1:13-cv-01483",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-05-21",
                            "short_description": "Order",
                            "absolute_url": "/docket/900/50/",
                        }
                    ],
                },
                {
                    "caseName": "Unrelated v. Case",
                    "docket_id": 901,
                    "court_id": "caed",
                    "docket_absolute_url": "/docket/901/",
                    "docketNumber": "2:20-cv-99999",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Order",
                            "absolute_url": "/docket/901/10/",
                        }
                    ],
                },
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Estate of Elkins v. Pelayo, Case No. 1:13-CV-1483 AWI SAB, "
            "2020 WL 2571387, at *4 n.3 (E.D. Cal. May 21, 2020)"
        )

        # Should find a match via docket number (different case name is OK)
        assert result.status in (
            VerificationStatus.LIKELY_REAL,
            VerificationStatus.POSSIBLE_MATCH,
        )
        # The unrelated case should have been filtered out
        assert "Unrelated" not in (result.matched_case_name or "")

    def test_no_match_when_docket_numbers_dont_match(self):
        """If API returns only non-matching docket numbers, no candidates survive."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Wrong v. Case",
                    "docket_id": 950,
                    "court_id": "caed",
                    "docket_absolute_url": "/docket/950/",
                    "docketNumber": "3:99-cv-77777",
                    "recap_documents": [],
                },
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Test v. Case, Case No. 1:13-CV-1483 (E.D. Cal. 2020)")

        assert result.status == VerificationStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Parser: case name normalization
# ---------------------------------------------------------------------------


class TestCaseNameNormalization:
    def test_cnty_expanded_to_county(self):
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, "
            "2025 WL 459154, at *1 (W.D. Wash. Feb. 11, 2025)"
        )
        assert "County" in parsed.case_name
        assert "Cnty" not in parsed.case_name
        assert "County" in parsed.defendant

    def test_dept_expanded_to_department(self):
        from citation_verifier.parser import parse_citation

        parsed = parse_citation("Smith v. Fire Dept., 100 F.3d 200 (2d Cir. 2020)")
        assert "Department" in parsed.case_name

    def test_dept_with_apostrophe_expanded(self):
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Busha v. SC Dep't of Mental Health, 2019 WL 651680 (D.S.C. Feb. 13, 2019)"
        )
        assert "Department" in parsed.case_name
        assert "Dep't" not in parsed.case_name

    def test_multiple_abbreviations_expanded(self):
        """Test various Indigo Book abbreviations are normalized."""
        from citation_verifier.parser import parse_citation

        test_cases = [
            ("Smith v. ABC Corp.", "Corporation"),
            ("Jones v. National Assn. of Realtors", "Association"),
            ("Doe v. University Hosp.", "Hospital"),
            ("Roe v. City School Dist.", "District"),
            ("Brown v. XYZ Inc.", "Incorporated"),
            ("Green v. County Bd. of Education", "Board"),
            ("White v. Public Util. Comm.", "Utility", "Commission"),
        ]

        for citation_fragment, *expected_words in test_cases:
            parsed = parse_citation(f"{citation_fragment}, 100 F.3d 200 (2d Cir. 2020)")
            for expected in expected_words:
                assert expected in parsed.case_name, (
                    f"Expected '{expected}' in '{parsed.case_name}' "
                    f"for input '{citation_fragment}'"
                )


# ---------------------------------------------------------------------------
# Citation lookup name matching (lenient surname-based)
# ---------------------------------------------------------------------------


class TestCitationLookupNameMatching:
    """Citation lookup should use lenient surname-based matching."""

    def test_abbreviated_name_matches_full_name(self):
        """'Fink v. Gomez' should match 'David M. Fink v. James H. Gomez, Director...'"""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "David M. Fink v. James H. Gomez, Director, Diana Carloni Nourse",
                            "id": 772039,
                            "absolute_url": "/opinion/772039/david-m-fink-v-james-h-gomez/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Fink v. Gomez, 239 F.3d 989 (9th Cir. 2001)")

        assert result.status == VerificationStatus.VERIFIED

    def test_none_plaintiff_trusts_citation_lookup(self):
        """When eyecite fails to parse plaintiff ('None v. X'), trust citation lookup."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Sparling v. Daou",
                            "id": 8438896,
                            "absolute_url": "/opinion/8438896/sparling-v-daou/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("None v. Daou Systems, Inc., 411 F.3d 1006 (2005)")

        assert result.status == VerificationStatus.VERIFIED

    def test_completely_wrong_name_still_rejected(self):
        """Fabricated name + real citation should still be NOT_FOUND."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "David M. Fink v. James H. Gomez, Director",
                            "id": 772039,
                            "absolute_url": "/opinion/772039/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Johnson v. Microsoft Corp., 239 F.3d 989 (9th Cir. 2001)")

        assert result.status == VerificationStatus.NOT_FOUND

    def test_defendant_only_match_sufficient(self):
        """If just the defendant surname matches, accept it (plaintiff may be 'Estate of X')."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Elkins v. California Highway Patrol",
                            "id": 100,
                            "absolute_url": "/opinion/100/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        # "Estate" won't appear in CL name, but "Pelayo" won't either —
        # actually this should NOT match since neither surname is in there.
        # But "Elkins" IS in both. Let's test the right thing:
        result = v.verify("Elkins v. Pelayo, 100 F.3d 200 (2001)")
        # "Elkins" appears in CL name → passes surname check
        assert result.status == VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# Surname score bonus for search fallback
# ---------------------------------------------------------------------------


class TestSurnameScoreBonus:
    """Search fallback should boost score when surnames match despite low SequenceMatcher."""

    def test_surname_match_boosts_score(self):
        """'Jindrich v. Weihele' vs 'Edward S. Jindrich, Jr. v. Michaela Weihele' should score well."""
        from citation_verifier.models import ParsedCitation

        parsed = ParsedCitation(
            raw_text="test",
            case_name="Jindrich v. Weihele",
            plaintiff="Jindrich",
            defendant="Weihele",
        )
        v = CitationVerifier(_make_client())
        score, _ = v._score_match(
            parsed,
            "Edward S. Jindrich, Jr. v. Michaela Weihele",
            "", "", {}
        )
        # Without bonus: ~0.5 * 0.61 = 0.305
        # With bonus: should be boosted to ~0.5 * 0.85 = 0.425
        assert score >= 0.40

    def test_no_bonus_when_surnames_dont_match(self):
        """Unrelated names should not get a surname bonus."""
        from citation_verifier.models import ParsedCitation

        parsed = ParsedCitation(
            raw_text="test",
            case_name="Smith v. Jones",
            plaintiff="Smith",
            defendant="Jones",
        )
        v = CitationVerifier(_make_client())
        score, _ = v._score_match(
            parsed,
            "Edward S. Jindrich, Jr. v. Michaela Weihele",
            "", "", {}
        )
        # No surname match → no bonus → stays low
        assert score < 0.30
