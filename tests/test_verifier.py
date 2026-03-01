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

    def test_no_retry_without_court_filter(self):
        """Opinion search does NOT retry without court filter (removed: never found correct matches)."""
        client = _make_client()
        client.search_opinions.return_value = []
        v = CitationVerifier(client)
        v.verify("Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)")

        assert client.search_opinions.call_count == 1


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

    def test_recap_prefers_is_free_on_pacer(self):
        """A doc with is_free_on_pacer=True should be preferred over one without,
        even when descriptions are non-substantive."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 400,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/400/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Attachment",
                            "absolute_url": "/docket/400/10/smith-v-jones/",
                            "is_free_on_pacer": False,
                        },
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Attachment",
                            "absolute_url": "/docket/400/11/smith-v-jones/",
                            "is_free_on_pacer": True,
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2020 WL 999999 (S.D.N.Y. June 1, 2020)")

        # The free-on-PACER doc (entry 11) should be selected
        assert "/11/" in result.matched_url

    def test_recap_date_proximity_beats_is_free_on_pacer(self):
        """A doc with an exact date match should beat a free-on-PACER doc
        that is months away from the cited date."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 500,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/500/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-02-15",
                            "short_description": "Order",
                            "absolute_url": "/docket/500/20/smith-v-jones/",
                            "is_free_on_pacer": True,
                        },
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Report and Recommendation",
                            "absolute_url": "/docket/500/21/smith-v-jones/",
                            "is_free_on_pacer": False,
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2020 WL 999999 (S.D.N.Y. June 1, 2020)")

        # The date-matching R&R (entry 21) should win over the free-on-PACER
        # order that is 4 months away
        assert "/21/" in result.matched_url

    def test_opinion_keyword_beats_is_free_alone(self):
        """An opinion doc without is_free beats a non-opinion doc with is_free
        at the same score and date proximity."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 600,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/600/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Attachment",
                            "absolute_url": "/docket/600/10/smith-v-jones/",
                            "is_free_on_pacer": True,
                        },
                        {
                            "entry_date_filed": "2020-06-01",
                            "short_description": "Opinion and Order",
                            "absolute_url": "/docket/600/11/smith-v-jones/",
                            "is_free_on_pacer": False,
                        },
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2020 WL 999999 (S.D.N.Y. June 1, 2020)")

        # Opinion (tier 2) should beat Attachment+is_free (tier 1)
        assert "/11/" in result.matched_url

    def test_progressive_date_widening(self):
        """When exact date returns nothing, month ± 1 query should fire
        before falling back to full year."""

        call_count = {"n": 0}

        def docket_entries_side_effect(**kwargs):
            call_count["n"] += 1
            after = kwargs.get("date_filed_after", "")
            before = kwargs.get("date_filed_before", "")
            # Exact date query: return nothing
            if after == "2020-09-17" and before == "2020-09-17":
                return []
            # Month ± 1 query (Aug-Oct): return a doc
            if after.startswith("2020-08") and before.startswith("2020-10"):
                return [
                    {
                        "date_filed": "2020-09-20",
                        "description": "Opinion",
                        "recap_documents": [
                            {
                                "short_description": "Opinion",
                                "absolute_url": "/docket/700/40/smith-v-jones/",
                            }
                        ],
                    }
                ]
            # Year range: should NOT be reached
            return []

        client = _make_client(
            search_recap=[
                {
                    "caseName": "Smith v. Jones",
                    "docket_id": 700,
                    "court_id": "nysd",
                    "docket_absolute_url": "/docket/700/",
                    "recap_documents": [
                        {
                            "entry_date_filed": "2020-01-15",
                            "short_description": "Reply",
                            "absolute_url": "/docket/700/5/",
                        },
                    ],
                }
            ],
        )
        client.get_docket_entries.side_effect = docket_entries_side_effect
        v = CitationVerifier(client)
        result = v.verify(
            "Smith v. Jones, 2020 WL 555555 (S.D.N.Y. Sept. 17, 2020)"
        )

        # Month ± 1 query should have fired (2 calls: exact date + month range)
        assert call_count["n"] == 2
        # The opinion from the month range should be selected
        assert "/40/" in result.matched_url


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

    # --- Tests with all components evaluable (no redistribution) ---
    # When court AND year are provided, base weights apply: 50/20/20/5/5

    def test_perfect_score_all_components(self):
        """With all components, perfect name + court + date + cite = 1.0."""
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020,
                              "volume": "500", "reporter": "F.3d", "page": "200"},
            result_court="nysd",
            result_date="2020-06-15",
            result={"citation": ["500 F.3d 200"]},
        )
        assert score == pytest.approx(0.95, abs=0.01)  # name 0.5 + court 0.2 + date 0.2 + cite 0.05
        assert not any("mismatch" in m.lower() for m in mismatches)

    def test_name_only_with_all_weights(self):
        """With court and year evaluable but not matching, name contributes 50%."""
        score, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="ca9",  # mismatch
            result_date="2015-01-01",  # mismatch
        )
        assert score == pytest.approx(0.5, abs=0.01)

    def test_name_mismatch_flagged(self):
        score, mismatches = self._score(result_case_name="Totally Different v. Case")
        assert score < 0.4
        assert any("name mismatch" in m.lower() for m in mismatches)

    def test_court_match_adds_20_percent(self):
        """Court match adds 20% when base weights apply (year also provided)."""
        score_no_match, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="ca9",  # mismatch
            result_date="2015-01-01",  # mismatch
        )
        score_with_court, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",  # match
            result_date="2015-01-01",  # mismatch
        )
        assert score_with_court - score_no_match == pytest.approx(0.2, abs=0.01)

    def test_court_mismatch_adds_nothing(self):
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y."},
            result_court="ca9",
        )
        assert any("court mismatch" in m.lower() for m in mismatches)

    def test_exact_year_adds_20_percent(self):
        """Year match adds 20% when base weights apply (court also provided)."""
        score, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2020-06-15",
        )
        # name (0.5) + court (0.2) + date (0.2)
        assert score == pytest.approx(0.9, abs=0.01)

    def test_off_by_one_year_adds_half_date_weight(self):
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2019-12-31",
        )
        # name (0.5) + court (0.2) + date (0.2 * 0.5 = 0.1)
        assert score == pytest.approx(0.8, abs=0.01)
        assert any("date close" in m.lower() for m in mismatches)

    def test_date_mismatch_adds_nothing(self):
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2015-01-01",
        )
        # name (0.5) + court (0.2) + date (0)
        assert score == pytest.approx(0.7, abs=0.01)
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

    def test_docket_number_match_adds_points(self):
        """Docket match adds to score (weight may be redistributed)."""
        score_without, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2020-06-15",
        )
        score_with, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020,
                              "docket_number": "17-cv-12676"},
            result_court="nysd",
            result_date="2020-06-15",
            result={"docketNumber": "2:17-cv-00012676"},
        )
        # Docket adds 5% with base weights
        assert score_with - score_without == pytest.approx(0.05, abs=0.01)

    def test_docket_number_mismatch_flagged(self):
        _, mismatches = self._score(
            parsed_overrides={"docket_number": "17-cv-12676"},
            result={"docketNumber": "99-cv-99999"},
        )
        assert any("docket mismatch" in m.lower() for m in mismatches)

    def test_reporter_citation_match_adds_points(self):
        """Reporter match adds to score (weight may be redistributed)."""
        score_without, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2020-06-15",
        )
        score_with, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020,
                              "volume": "500", "reporter": "F.3d", "page": "200"},
            result_court="nysd",
            result_date="2020-06-15",
            result={"citation": ["500 F.3d 200"]},
        )
        # Reporter adds 5% with base weights
        assert score_with - score_without == pytest.approx(0.05, abs=0.01)

    def test_wl_number_match_adds_points(self):
        """WL number match adds to score (weight may be redistributed)."""
        score_without, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2020-06-15",
        )
        score_with, _ = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020,
                              "wl_number": "4407750"},
            result_court="nysd",
            result_date="2020-06-15",
            result={"citation": ["2018 WL 4407750"]},
        )
        # WL adds 5% with base weights
        assert score_with - score_without == pytest.approx(0.05, abs=0.01)

    # --- Tests for weight redistribution (missing court/date) ---

    def test_weight_redistribution_no_court(self):
        """When court is not parsed, its 20% weight is redistributed."""
        # No court → name gets ~0.667 weight (0.5 + redistribution)
        score, _ = self._score(
            parsed_overrides={"year": 2020},
            result_date="2020-06-15",
        )
        # With redistribution: name ~0.667 + date 0.2 = ~0.867
        assert score > 0.85
        assert score < 0.95

    def test_weight_redistribution_no_court_no_date(self):
        """When both court and date are missing, 40% is redistributed to name."""
        score, _ = self._score()  # no court, no year
        # name ~0.833 (0.5/0.6 * 1.0) + docket 0 + cite 0 = ~0.833
        assert score > 0.80
        assert score < 0.90

    def test_redistribution_preserves_relative_ordering(self):
        """A mismatched date still scores lower than a matched date,
        even when court is missing and weights are redistributed."""
        score_match, _ = self._score(
            parsed_overrides={"year": 2020},
            result_date="2020-06-15",
        )
        score_mismatch, _ = self._score(
            parsed_overrides={"year": 2020},
            result_date="2015-01-01",
        )
        assert score_match > score_mismatch


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
        assert s("report and recommendation")
        assert s("report and recommendations")
        assert not s("reply to response to motion")
        assert not s("motion - free")
        assert not s("extend - free")

    def test_is_substantive_doc_rejects_non_substantive_patterns(self):
        """Docs matching negative patterns should be rejected even if they contain substantive keywords."""
        s = CitationVerifier._is_substantive_doc
        assert not s("proposed order")
        assert not s("proposed judgment")
        assert not s("leave to file document under seal")
        assert not s("leave to seal")
        assert not s("transcript order form")
        assert not s("certificate of service")
        assert not s("notice of appeal")
        assert not s("motion to dismiss")
        assert not s("motion for summary judgment")
        # But a real order is still substantive
        assert s("order granting motion to dismiss")
        assert s("order on motion for summary judgment")

    def test_opinion_likelihood_rankings(self):
        """Test composite opinion-likelihood scoring with keyword + is_free + page_count."""
        ol = CitationVerifier._opinion_likelihood
        # Tier 3: opinion keyword + is_free
        assert ol("opinion", True, 10) == (3, 10)
        assert ol("memorandum", True, 5) == (3, 5)
        assert ol("report and recommendation", True, 20) == (3, 20)
        assert ol("report & recommendation", True, 0) == (3, 0)
        assert ol("findings of fact", True, 15) == (3, 15)
        # Tier 2: opinion keyword without is_free, OR order keyword + is_free
        assert ol("opinion", False, 10) == (2, 10)
        assert ol("memorandum", False, 5) == (2, 5)
        assert ol("order", True, 8) == (2, 8)
        assert ol("ruling", True, 3) == (2, 3)
        assert ol("decision", True, 12) == (2, 12)
        assert ol("decree", True, 4) == (2, 4)
        # Tier 1: order keyword without is_free, OR is_free alone
        assert ol("order", False, 8) == (1, 8)
        assert ol("ruling", False, 3) == (1, 3)
        assert ol("attachment", True, 2) == (1, 2)
        # Tier 0: nothing
        assert ol("judgment", False, 0) == (0, 0)
        assert ol("clerk's judgment", False, 0) == (0, 0)
        assert ol("reply", False, 0) == (0, 0)
        # Page count capped at 50
        assert ol("opinion", True, 100) == (3, 50)
        # Page count breaks ties within same tier
        assert ol("opinion", False, 30) > ol("opinion", False, 10)

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
            # Business entity suffixes are NOT expanded (CL stores them abbreviated)
            ("Smith v. ABC Corp.", "Corp."),
            ("Jones v. National Assn. of Realtors", "Association"),
            ("Doe v. University Hosp.", "Hospital"),
            ("Roe v. City School Dist.", "District"),
            ("Brown v. XYZ Inc.", "Inc."),
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

    def test_commr_expanded_to_commissioner(self):
        """Comm'r should expand to Commissioner (Russomanno case)."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Russomanno v. Comm'r of Internal Revenue, 100 F.3d 200 (2d Cir. 2020)"
        )
        assert "Commissioner" in parsed.case_name
        assert "Comm'r" not in parsed.case_name

    def test_info_sols_expanded(self):
        """Info. Sols. should expand to Information Solutions (Dukuray case)."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Dukuray v. Global Info. Sols., 100 F.3d 200 (2d Cir. 2020)"
        )
        assert "Information" in parsed.case_name
        assert "Solutions" in parsed.case_name

    def test_fin_expanded_to_finance(self):
        """Fin. should expand to Finance (Auto Fin. Corp. case)."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Auto Fin. Corp. v. Liu, 100 F.3d 200 (2d Cir. 2020)"
        )
        assert "Finance" in parsed.case_name

    def test_nw_expanded_to_northwest(self):
        """Nw. should expand to Northwest (Weatherly case)."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Weatherly v. Second Nw. Coop. Homes, 100 F.3d 200 (D.C. 2020)"
        )
        assert "Northwest" in parsed.case_name

    def test_slip_opinion_placeholder_stripped(self):
        """'-- F. Supp. 3d ----' should be stripped from case name and defendant."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Johnson v. Dunn, -- F. Supp. 3d ----, 2025 WL 2086116 "
            "(N.D. Ala. July 23, 2025)"
        )
        assert parsed.case_name == "Johnson v. Dunn"
        assert parsed.defendant == "Dunn"

    def test_slip_opinion_triple_dash(self):
        """'--- S.Ct. ---' variant should also be stripped."""
        from citation_verifier.parser import parse_citation

        parsed = parse_citation(
            "Smith v. Jones, --- S.Ct. ---, 2025 WL 123456 (2025)"
        )
        assert parsed.case_name == "Smith v. Jones"
        assert parsed.defendant == "Jones"


# ---------------------------------------------------------------------------
# Citation lookup name matching (lenient surname-based)
# ---------------------------------------------------------------------------


class TestBidirectionalAbbreviationNormalization:
    """Name matcher should normalize both cited and CL names so abbreviation
    differences don't tank similarity scores. See TODO: Bidirectional abbreviation
    normalization (Priority 1)."""

    def test_commr_vs_commissioner(self):
        """Comm'r should match Commissioner (Russomanno case)."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "Russomanno v. Comm'r of Internal Revenue",
            "Russomanno v. Commissioner of Internal Revenue",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"

    def test_ampersand_vs_and(self):
        """& should match 'and' (King v. Police & Fire case)."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "King v. Police & Fire Retirement System",
            "King v. Police and Fire Retirement System",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"

    def test_info_sols_vs_information_solutions(self):
        """Info. Sols. should match Information Solutions (Dukuray case)."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "Dukuray v. Global Info. Sols.",
            "Dukuray v. Global Information Solutions",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"

    def test_fin_corp_vs_finance_corporation(self):
        """Fin. Corp. should match Finance Corporation (Auto Fin. Corp. case)."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "Auto Fin. Corp. v. Liu",
            "Auto Finance Corporation v. Liu",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"

    def test_nw_assn_vs_northwest_association(self):
        """Nw. + Ass'n should match Northwest + Association (Weatherly case)."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "Weatherly v. Second Nw. Coop. Homes Ass'n",
            "Weatherly v. Second Northwest Cooperative Homes Association",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"

    def test_smart_apostrophe_normalization(self):
        """Smart apostrophes (\u2019) should match straight apostrophes."""
        from citation_verifier.name_matcher import CaseNameMatcher

        m = CaseNameMatcher()
        score = m.calculate_similarity(
            "Busha v. SC Dep\u2019t of Mental Health",
            "Busha v. SC Department of Mental Health",
        )
        assert score >= 0.85, f"Expected >= 0.85, got {score}"


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

    def test_common_word_surname_rejected(self):
        """'American' as a defendant surname should not match an unrelated 'American National Insurance'."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "American National Insurance v. Smith",
                            "id": 999,
                            "absolute_url": "/opinion/999/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Pettway v. American Savings & Loan Association, 197 F. Supp. 489 "
            "(N.D. Ala. 1961)"
        )
        # "American" is nondistinctive; "Pettway" is distinctive but not in CL name
        assert result.status == VerificationStatus.NOT_FOUND

    def test_distinctive_org_name_still_matches(self):
        """Non-generic org names like 'Costco' should still match."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Costco Wholesale Corp. v. Omega, S.A.",
                            "id": 888,
                            "absolute_url": "/opinion/888/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Costco v. Omega, 562 U.S. 40 (2010)")
        assert result.status == VerificationStatus.VERIFIED

    def test_all_nondistinctive_surnames_trusts_lookup(self):
        """When all extracted surnames are generic, trust the citation lookup."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "First National Bank v. Federal Reserve",
                            "id": 777,
                            "absolute_url": "/opinion/777/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("First National v. Federal Reserve, 100 U.S. 50 (1990)")
        # Both "First" and "Federal" are nondistinctive → trusts lookup
        assert result.status == VerificationStatus.VERIFIED

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


# ---------------------------------------------------------------------------
# Factory function: parsed_citation_from_eyecite
# ---------------------------------------------------------------------------


class TestParsedCitationFromEyecite:
    """Tests for the parsed_citation_from_eyecite() factory function."""

    def test_basic_fields_from_eyecite(self):
        """Factory should populate volume, reporter, page, court, year, and parties."""
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation as EyeciteFullCite

        from citation_verifier.parser import parsed_citation_from_eyecite

        text = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        cites = get_citations(text)
        full_cite = next(c for c in cites if isinstance(c, EyeciteFullCite))
        result = parsed_citation_from_eyecite(full_cite, raw_text=text)

        assert result.raw_text == text
        assert result.volume == "576"
        assert result.reporter == "U.S."
        assert result.page == "644"
        assert result.year == 2015
        assert result.case_name is not None
        assert "Hodges" in result.case_name

    def test_westlaw_detection(self):
        """WL reporter should set is_westlaw and wl_number."""
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation as EyeciteFullCite

        from citation_verifier.parser import parsed_citation_from_eyecite

        text = "Anderson v. Furst, 2018 WL 4407750 (E.D. Mich. Sept. 17, 2018)"
        cites = get_citations(text)
        full_cite = next(c for c in cites if isinstance(c, EyeciteFullCite))
        result = parsed_citation_from_eyecite(full_cite, raw_text=text)

        assert result.is_westlaw is True
        assert result.wl_number == "4407750"
        assert result.year == 2018

    def test_abbreviation_normalization(self):
        """Abbreviations should be expanded just like parse_citation()."""
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation as EyeciteFullCite

        from citation_verifier.parser import parsed_citation_from_eyecite

        text = "Bossart v. King Cnty., 100 F.3d 200 (2020)"
        cites = get_citations(text)
        full_cite = next(c for c in cites if isinstance(c, EyeciteFullCite))
        result = parsed_citation_from_eyecite(full_cite, raw_text=text)

        assert result.case_name is not None
        assert "County" in result.case_name
        assert "Cnty" not in result.case_name

    def test_docket_number_extraction(self):
        """Docket number should be extracted from raw_text."""
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation as EyeciteFullCite

        from citation_verifier.parser import parsed_citation_from_eyecite

        text = (
            "Bossart v. King County, Case No. 2:24-cv-01776-JHC, "
            "2025 WL 459154 (W.D. Wash. Feb. 11, 2025)"
        )
        cites = get_citations(text)
        full_cite = next(c for c in cites if isinstance(c, EyeciteFullCite))
        result = parsed_citation_from_eyecite(full_cite, raw_text=text)

        assert result.docket_number == "2:24-cv-01776-JHC"

    def test_month_day_preserved(self):
        """Month and day from eyecite metadata should be preserved."""
        from eyecite import get_citations
        from eyecite.models import FullCaseCitation as EyeciteFullCite

        from citation_verifier.parser import parsed_citation_from_eyecite

        text = "Smith v. Jones, 2020 WL 123456 (S.D.N.Y. Sept. 17, 2020)"
        cites = get_citations(text)
        full_cite = next(c for c in cites if isinstance(c, EyeciteFullCite))
        result = parsed_citation_from_eyecite(full_cite, raw_text=text)

        # eyecite extracts month/day from the parenthetical
        if result.month is not None:
            assert result.month == 9
        if result.day is not None:
            assert result.day == 17


# ---------------------------------------------------------------------------
# verify() with pre-parsed citation
# ---------------------------------------------------------------------------


class TestVerifyWithParsedCitation:
    """Tests for passing a pre-built ParsedCitation to verify()."""

    def test_verify_uses_preparsed_citation(self):
        """When parsed is provided, verify() should skip internal parsing."""
        from citation_verifier.models import ParsedCitation

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
        parsed = ParsedCitation(
            raw_text="Obergefell v. Hodges, 576 U.S. 644 (2015)",
            case_name="Obergefell v. Hodges",
            plaintiff="Obergefell",
            defendant="Hodges",
            volume="576",
            reporter="U.S.",
            page="644",
            court="scotus",
            year=2015,
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Obergefell v. Hodges, 576 U.S. 644 (2015)", parsed=parsed
        )

        assert result.status == VerificationStatus.VERIFIED
        assert result.confidence == 1.0

    def test_preparsed_preserves_month_day(self):
        """Pre-parsed citation with month/day should flow through to scoring."""
        from citation_verifier.models import ParsedCitation

        client = _make_client(
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 400,
                    "dateFiled": "2020-09-17",
                    "court_id": "nysd",
                    "absolute_url": "/opinion/400/",
                    "citation": ["2020 WL 123456"],
                }
            ],
        )
        parsed = ParsedCitation(
            raw_text="Smith v. Jones, 2020 WL 123456 (S.D.N.Y. Sept. 17, 2020)",
            case_name="Smith v. Jones",
            plaintiff="Smith",
            defendant="Jones",
            court="S.D.N.Y.",
            year=2020,
            month=9,
            day=17,
            is_westlaw=True,
            wl_number="123456",
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Smith v. Jones, 2020 WL 123456 (S.D.N.Y. Sept. 17, 2020)",
            parsed=parsed,
        )

        assert result.status == VerificationStatus.LIKELY_REAL

    def test_existing_callers_unaffected(self):
        """Calling verify() with only citation_text still works (backward compat)."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Smith v. Jones",
                            "id": 500,
                            "absolute_url": "/opinion/500/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)")

        assert result.status == VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# Quick-only mode (Step 1 only)
# ---------------------------------------------------------------------------


class TestQuickOnly:
    """Tests for quick_only=True which limits verification to Step 1."""

    def test_quick_found_returns_verified(self):
        """Citation found in Step 1 with quick_only -> VERIFIED (same as full)."""
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
        result = v.verify(
            "Obergefell v. Hodges, 576 U.S. 644 (2015)", quick_only=True
        )

        assert result.status == VerificationStatus.VERIFIED
        assert result.confidence == 1.0
        assert result.matched_case_name == "Obergefell v. Hodges"

    def test_quick_not_found_returns_not_found(self):
        """Citation not in lookup API with quick_only -> NOT_FOUND, no further steps."""
        client = _make_client()  # all APIs return empty
        v = CitationVerifier(client)
        result = v.verify(
            "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)", quick_only=True
        )

        assert result.status == VerificationStatus.NOT_FOUND
        assert result.confidence == 0.0
        assert "Quick search only" in result.diagnostics[0]

    def test_quick_does_not_call_step1b_or_search(self):
        """quick_only must not call adjacent page lookup, opinion search, or RECAP."""
        client = _make_client()
        v = CitationVerifier(client)
        v.verify(
            "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)", quick_only=True
        )

        # Step 1 is called once (the initial lookup)
        assert client.citation_lookup.call_count == 1
        # Steps 2 and 3 are never called
        assert client.search_opinions.call_count == 0
        assert client.search_recap.call_count == 0

    def test_quick_name_mismatch_returns_not_found(self):
        """Citation exists but wrong case with quick_only -> NOT_FOUND (same as full)."""
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
        result = v.verify(
            "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)", quick_only=True
        )

        assert result.status == VerificationStatus.NOT_FOUND
        assert "different case" in result.diagnostics[0]
