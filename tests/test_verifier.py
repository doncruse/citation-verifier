"""Tests for the citation verification pipeline.

All tests mock CourtListenerClient so no real API calls are made.

Migrated to the v0.3 schema (Phase 1, Task 2). Task 1 (Phase 3) removed
the legacy _DiagnosticLike / _CATEGORY_PATTERNS / _classify_note /
_diagnostics / _matched_case_name bridge; assertions now read
result.warnings and _winning_path_entry() directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from citation_verifier.models import StageName, StageVerdict, Status, WarningCategory
from citation_verifier.parser import parse_citation
from citation_verifier.verifier import CitationVerifier, _VERIFIED_SCORE_THRESHOLD


def _winning_path_entry(result):
    """Return the resolution_path entry that drove the result (highest-
    confidence resolved/partial entry, else the last entry).

    Phase 2 emits one entry per stage attempted; the last is not always
    the winner (e.g. opinion_search resolved, then recap_docket_search
    ran afterward as a no_match). This helper picks the entry that
    actually decided the verdict so tests can assert against its
    raw_response_summary, notes, etc."""
    if not result.resolution_path:
        return None
    resolved = [
        e for e in result.resolution_path
        if e.verdict in (StageVerdict.resolved, StageVerdict.partial)
    ]
    if resolved:
        return max(resolved, key=lambda e: e.confidence or 0.0)
    return result.resolution_path[-1]


def _make_client(**overrides):
    """Create a mock CourtListenerClient with sensible defaults."""
    client = MagicMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    # New for Phase 3 caption_investigation — Task 5 wires the production
    # call sites; default these to empty dicts so existing tests don't break.
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text.return_value = overrides.get("get_opinion_text", None)
    client.get_opinion_text_with_metadata.return_value = overrides.get(
        "get_opinion_text_with_metadata", None
    )
    # Phase 4 Task 4 doc-detail fetch for VIA_RECAP score gate refinement.
    # Default to None (no detail available); tests that exercise the fetch
    # path set recap_document_metadata to a dict.
    recap_doc_metadata = overrides.get("recap_document_metadata", None)
    if isinstance(recap_doc_metadata, Exception):
        client.get_recap_document_metadata.side_effect = recap_doc_metadata
    else:
        client.get_recap_document_metadata.return_value = recap_doc_metadata
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

        assert result.status == Status.VERIFIED
        assert result.headline_confidence == 1.0
        assert _winning_path_entry(result).raw_response_summary.get("matched_case_name") == "Obergefell v. Hodges"
        assert "courtlistener.com" in result.final_ids.absolute_url

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

        assert result.status == Status.VERIFIED
        assert result.final_ids.absolute_url == "https://www.courtlistener.com/opinion/456/"

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
            result.final_ids.absolute_url
            == "https://www.courtlistener.com/opinion/456/smith-v-jones/"
        )


# ---------------------------------------------------------------------------
# Step 1: Citation Lookup — syllabus passthrough (Phase 1 retro Q5)
# ---------------------------------------------------------------------------


class TestStep1SyllabusPassthrough:
    """Restored in fix/restore-syllabus: citation_lookup raw_response_summary
    carries `syllabus` and `nature_of_suit` when CL provides them, and
    VerificationResult.syllabus accessor joins them."""

    def test_syllabus_present_in_raw_response_summary(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Tompkins v. Cyr",
                            "id": 19782,
                            "absolute_url": "/opinion/19782/tompkins-v-cyr/",
                            "syllabus": "RICO; anti-abortion protesters; harassment",
                            "nature_of_suit": "Civil Rights",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)")

        winning = _winning_path_entry(result)
        assert winning.raw_response_summary.get("syllabus") == (
            "RICO; anti-abortion protesters; harassment"
        )
        assert winning.raw_response_summary.get("nature_of_suit") == "Civil Rights"

    def test_keys_absent_when_cluster_has_neither_field(self):
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

        winning = _winning_path_entry(result)
        # Per the implementation: omit empty keys rather than store None / ""
        assert "syllabus" not in winning.raw_response_summary
        assert "nature_of_suit" not in winning.raw_response_summary

    def test_keys_absent_when_cluster_has_empty_strings(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                            "syllabus": "",
                            "nature_of_suit": "",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")

        winning = _winning_path_entry(result)
        assert "syllabus" not in winning.raw_response_summary
        assert "nature_of_suit" not in winning.raw_response_summary

    def test_accessor_joins_syllabus_and_nature_of_suit(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Tompkins v. Cyr",
                            "id": 19782,
                            "absolute_url": "/opinion/19782/",
                            "syllabus": "RICO; anti-abortion protesters",
                            "nature_of_suit": "Civil Rights",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)")

        assert result.syllabus == "RICO; anti-abortion protesters; Civil Rights"

    def test_accessor_returns_syllabus_alone_when_nature_of_suit_missing(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Tompkins v. Cyr",
                            "id": 19782,
                            "absolute_url": "/opinion/19782/",
                            "syllabus": "RICO; anti-abortion protesters",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)")

        assert result.syllabus == "RICO; anti-abortion protesters"

    def test_accessor_returns_none_when_no_citation_lookup_entry(self):
        # No citation_lookup hit; falls through to NOT_FOUND with no
        # opinion_search / RECAP candidates. resolution_path will not
        # contain a resolved citation_lookup entry.
        client = _make_client(citation_lookup=[])
        v = CitationVerifier(client)
        result = v.verify("Made Up v. Fake Case, 999 U.S. 999 (2099)")

        assert result.syllabus is None

    def test_accessor_returns_none_when_citation_lookup_entry_lacks_syllabus(self):
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Obergefell v. Hodges",
                            "id": 123,
                            "absolute_url": "/opinion/123/",
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")

        assert result.syllabus is None


# ---------------------------------------------------------------------------
# Step 1: Citation Lookup — NOT_FOUND (name mismatch)
# ---------------------------------------------------------------------------


class TestStep1NameMismatch:
    def test_possible_match_when_citation_belongs_to_different_case(self):
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

        # Phase 3: caption_investigation finds no party overlap between
        # "Smith v. Jones" and "Totally Different v. Case" → WRONG_CASE.
        # Per design §2.4: final_ids still populate with the actual CL cluster.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 789
        # The citation_lookup stage resolved (confidence=1.0 internally) and
        # caption_investigation ran; path has both entries.
        stages = [e.stage for e in result.resolution_path]
        assert StageName.citation_lookup in stages
        assert StageName.caption_investigation in stages

    def test_possible_match_different_defendant_same_prefix(self):
        """'United States v. Smith' should not verify as 'United States v. Johnson'."""
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

        # Phase 3: caption_investigation — "Smith" is not in "Johnson",
        # common-prefix case, distinctive-word overlap fails → WRONG_CASE.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 111


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

        assert result.status == Status.VERIFIED
        assert result.headline_confidence is not None
        assert result.headline_confidence >= 0.85
        assert _winning_path_entry(result).raw_response_summary.get("best_case_name") == "Smith v. Jones"

    def test_not_found_when_no_results(self):
        client = _make_client()  # everything returns []
        v = CitationVerifier(client)
        result = v.verify("Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)")

        assert result.status == Status.NOT_FOUND
        assert result.headline_confidence is None

    def test_no_retry_without_court_filter(self):
        """Opinion search does NOT retry without court filter (removed: never found correct matches)."""
        client = _make_client()
        client.search_opinions.return_value = []
        v = CitationVerifier(client)
        v.verify("Smith v. Jones, 500 F.3d 200 (2d Cir. 2020)")

        assert client.search_opinions.call_count == 1


class TestOpinionSearchGates:
    """Issue #7: temporal + name-token gates on the opinion-search fallback."""

    def test_temporal_gate_rejects_wrong_decade_with_matching_name(self):
        """A candidate with a matching case name but a wildly wrong decade
        must be rejected by the temporal gate. Without the gate this would
        score high enough to surface as a POSSIBLE_MATCH (the bug Sam
        reported in issue #7)."""
        client = _make_client(
            citation_lookup=[],  # forces fallback
            search_opinions=[
                {
                    # Name matches the citation almost exactly — without the
                    # temporal gate this would clear the POSSIBLE_MATCH
                    # threshold.
                    "caseName": "Jovel v. Boiron",
                    "cluster_id": 4147982,
                    "dateFiled": "1901-03-14",  # 112-year gap from 2013
                    "court_id": "tex",
                    "absolute_url": "/opinion/4147982/jovel-v-boiron/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Jovel v. Boiron, 2013 WL 12164622 (C.D. Cal. 2013)")

        assert result.status == Status.NOT_FOUND
        assert result.final_ids.cluster_id is None

    def test_temporal_gate_keeps_within_window_match(self):
        """A candidate within the 5-year window with a matching case name
        passes the gate and gets scored normally."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 1234567,
                    "dateFiled": "2016-06-01",  # 2-year gap from 2018
                    "court_id": "cacd",
                    "absolute_url": "/opinion/1234567/smith-v-jones/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2018 WL 999999 (C.D. Cal. 2018)")

        # Candidate survived the gate and bubbled up as the match.
        assert result.final_ids.cluster_id == 1234567

    def test_temporal_gate_boundary_exactly_5_years(self):
        """A 5-year gap is at the boundary — `>5` rejects, so exactly 5
        years away should still pass."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 1234568,
                    "dateFiled": "2013-06-01",  # exactly 5 years from 2018
                    "court_id": "cacd",
                    "absolute_url": "/opinion/1234568/smith-v-jones/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2018 WL 999999 (C.D. Cal. 2018)")

        # 5-year gap is within the gate window (`abs(diff) > 5` is the
        # reject condition, so 5 itself is kept).
        assert result.final_ids.cluster_id == 1234568

    def test_token_gate_rejects_no_shared_distinctive_tokens(self):
        """A candidate whose case name shares no distinctive >=4-char
        non-stoplist token with the cited case must be rejected by the
        name-token gate. Without the gate this candidate would score
        high enough on year+court alone to surface as a POSSIBLE_MATCH.

        Mirrors Sam's example: Harris v. CVS Pharmacy -> Medearis case.
        """
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    # No shared >=4-char non-stoplist token with the cited
                    # case ("Harris", "Pharmacy" stoplisted, "CVS" too
                    # short). All within the 5-year window so the temporal
                    # gate doesn't fire.
                    "caseName": "Medearis v. Whatever",
                    "cluster_id": 7312533,
                    "dateFiled": "2014-05-01",
                    "court_id": "nysd",
                    "absolute_url": "/opinion/7312533/medearis-v-whatever/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Harris v. CVS Pharmacy, 2015 WL 4694047 (S.D.N.Y. 2015)")

        assert result.status == Status.NOT_FOUND
        assert result.final_ids.cluster_id is None

    def test_token_gate_keeps_shared_distinctive_token(self):
        """A candidate sharing one distinctive >=4-char non-stoplist
        token (here: 'Garamszegi') passes the gate."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Smith v. Garamszegi",
                    "cluster_id": 9999,
                    "dateFiled": "2018-04-01",
                    "court_id": "cacd",
                    "absolute_url": "/opinion/9999/smith-v-garamszegi/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Lindsay-Stern v. Garamszegi, 2018 WL 1234 (C.D. Cal. 2018)"
        )

        assert result.final_ids.cluster_id == 9999

    def test_token_gate_rejects_stoplist_only_overlap(self):
        """When the candidate shares ONLY a stoplist token with the
        citation (here: 'Bank' — both cited and candidate contain it),
        the gate must still reject. Without the stoplist, 'Bank' alone
        would falsely qualify them as the same case.
        """
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    # Shares only 'bank' (stoplisted) with the cited
                    # case. No other >=4-char non-stoplist overlap.
                    "caseName": "Wilson v. Bank of New York",
                    "cluster_id": 5978123,
                    "dateFiled": "2019-08-15",
                    "court_id": "nysd",
                    "absolute_url": "/opinion/5978123/wilson-v-bony/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Snyder v. Bank of America, 2020 WL 6462400 (S.D.N.Y. 2020)"
        )

        assert result.status == Status.NOT_FOUND
        assert result.final_ids.cluster_id is None


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

        # Phase 3 Task 4: RECAP doc "Order on Motion to Compel" has no
        # opinion keyword, so strict gate fails -> VERIFIED_DOCKET_ONLY.
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.headline_confidence is not None
        assert "anderson-v-furst" in result.final_ids.absolute_url

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

        winner = _winning_path_entry(result)
        assert winner is not None and winner.notes and "Order" in winner.notes
        assert winner is not None and "Reply" not in (winner.notes or "")

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

        winner = _winning_path_entry(result)
        assert winner is not None and winner.notes and "possible docket match" in winner.notes.lower()
        # Score should be discounted: base ~0.7 * 0.6 = ~0.42
        assert result.headline_confidence is not None
        assert result.headline_confidence < 0.6

    def test_docket_only_sets_matched_docket_id_not_cluster_id(self):
        """Issue #6: docket-only RECAP fallback must put docket_id in
        matched_docket_id, not matched_cluster_id (different namespaces).
        """
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Lindsay-Stern v. Garamszegi",
                    "docket_id": 18158469,
                    "court_id": "cacd",
                    "docket_absolute_url": "/docket/18158469/",
                    "recap_documents": [],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Lindsay-Stern v. Garamszegi, No. 2:18-cv-01234 (C.D. Cal. 2018)"
        )

        assert result.final_ids.docket_id == 18158469
        assert result.final_ids.cluster_id is None

    def test_recap_doc_match_sets_matched_docket_id_not_cluster_id(self):
        """A RECAP doc match (with a specific recap_document) carries a
        docket_id but no cluster_id — confirm we set the right field."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Bear Warriors United v. Lambert",
                    "docket_id": 65698058,
                    "court_id": "flmd",
                    "docket_absolute_url": "/docket/65698058/",
                    "recap_documents": [],
                }
            ],
            get_docket_entries=[
                {
                    "date_filed": "2024-06-15",
                    "description": "ORDER granting summary judgment",
                    "recap_documents": [
                        {
                            "short_description": "Opinion",
                            "absolute_url": "/docket/65698058/42/bear-warriors-v-lambert/",
                            "page_count": 30,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Bear Warriors United v. Lambert, No. 6:22-cv-01155 (M.D. Fla. 2024)"
        )

        assert result.final_ids.docket_id == 65698058
        assert result.final_ids.cluster_id is None

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
        assert "/11/" in result.final_ids.absolute_url

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
        assert "/21/" in result.final_ids.absolute_url

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
        assert "/11/" in result.final_ids.absolute_url

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
        assert "/40/" in result.final_ids.absolute_url


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

        assert result.status == Status.NOT_FOUND
        winner = _winning_path_entry(result)
        # Phase 2: per-stage instrumentation removed the synthetic
        # "court corroboration failed" terminal entry; the candidate's
        # actual mismatches now carry the diagnostic. The "Reporter
        # citation ... could not be confirmed" message appears among
        # the candidate's mismatches; the court mismatch is also there.
        assert winner is not None and winner.notes and "could not be" in winner.notes.lower()
        assert winner is not None and winner.notes and "Court" in winner.notes

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

        assert result.status != Status.NOT_FOUND


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
        assert any(m.category == "name" for m in mismatches)

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
        assert any(m.category == "court" for m in mismatches)

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
        assert any(m.category == "date" for m in mismatches)

    def test_date_mismatch_adds_nothing(self):
        score, mismatches = self._score(
            parsed_overrides={"court": "S.D.N.Y.", "year": 2020},
            result_court="nysd",
            result_date="2015-01-01",
        )
        # name (0.5) + court (0.2) + date (0)
        assert score == pytest.approx(0.7, abs=0.01)
        assert any(m.category == "date" for m in mismatches)

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
        assert any(m.category == "docket" for m in mismatches)

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
        """High confidence (>=0.85) -> 'likely', mid confidence -> 'possible'."""
        # High-scoring match → confidence >= 0.85 → "likely"
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
        assert result.status == Status.VERIFIED
        assert result.headline_confidence is not None
        assert result.headline_confidence >= 0.85
        winner = _winning_path_entry(result)
        assert winner is not None and winner.notes and "likely match" in winner.notes

    def test_match_word_possible_for_lower_score(self):
        """Lower confidence (0.40-0.85) -> 'possible'."""
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
        if (
            result.status == Status.VERIFIED
            and result.headline_confidence is not None
            and 0.40 <= result.headline_confidence < 0.85
        ):
            winner = _winning_path_entry(result)
            assert winner is not None and winner.notes and "possible match" in winner.notes


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

        # Phase 3 Task 4: RECAP doc "Order" has no opinion keyword and no
        # id field, so strict gate fails -> VERIFIED_DOCKET_ONLY.
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.headline_confidence is not None
        # The unrelated case should have been filtered out
        winner = _winning_path_entry(result)
        matched_name = (winner.raw_response_summary.get("matched_case_name")
                        or winner.raw_response_summary.get("best_case_name")
                        or "") if winner else ""
        assert "Unrelated" not in matched_name

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

        assert result.status == Status.NOT_FOUND


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

        assert result.status == Status.VERIFIED

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

        assert result.status == Status.VERIFIED

    def test_completely_wrong_name_returns_wrong_case(self):
        """Fabricated name + real citation should return WRONG_CASE after investigation."""
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

        # Phase 3: no party overlap between "Johnson v. Microsoft" and
        # "David M. Fink v. James H. Gomez" → WRONG_CASE.
        # Per design §2.4: final_ids still populate with the actual CL cluster.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 772039

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
        # Phase 3: "Pettway" is distinctive but not in CL name, "American" is
        # shared but not distinctive enough to pass party-overlap → WRONG_CASE.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 999

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
        assert result.status == Status.VERIFIED

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
        assert result.status == Status.VERIFIED

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
        assert result.status == Status.VERIFIED


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

        assert result.status == Status.VERIFIED
        assert result.headline_confidence == 1.0

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

        assert result.status == Status.VERIFIED
        assert result.headline_confidence is not None
        assert result.headline_confidence >= 0.85

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

        assert result.status == Status.VERIFIED


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

        assert result.status == Status.VERIFIED
        assert result.headline_confidence == 1.0
        assert _winning_path_entry(result).raw_response_summary.get("matched_case_name") == "Obergefell v. Hodges"

    def test_quick_not_found_returns_not_found(self):
        """Citation not in lookup API with quick_only -> NOT_FOUND, no further steps."""
        client = _make_client()  # all APIs return empty
        v = CitationVerifier(client)
        result = v.verify(
            "Smith v. Jones, 100 F.3d 200 (2d Cir. 2020)", quick_only=True
        )

        assert result.status == Status.NOT_FOUND
        assert result.headline_confidence is None
        winner = _winning_path_entry(result)
        assert winner is not None and winner.notes and "Quick search only" in winner.notes

    def test_quick_does_not_call_search(self):
        """quick_only must not call opinion search or RECAP."""
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

    def test_quick_name_mismatch_returns_wrong_case(self):
        """Citation exists but wrong case with quick_only -> WRONG_CASE after investigation."""
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

        # Phase 3: caption_investigation runs even in quick_only mode when
        # citation_lookup flagged a name mismatch. No party overlap → WRONG_CASE.
        assert result.status == Status.WRONG_CASE
        assert result.final_ids.cluster_id == 789


# ---------------------------------------------------------------------------
# Docket Number Parsing and Normalization
# ---------------------------------------------------------------------------


class TestDocketParsing:
    """Test that the parser extracts docket numbers with spaces correctly."""

    def test_extract_c_space_number(self):
        p = parse_citation(
            "Chetal v. AmeriCredit Corp., No. C 09-02727 WHA, "
            "2011 WL 2560243 (N.D. Cal. 2011)"
        )
        assert p.docket_number == "C 09-02727 WHA"

    def test_extract_cv_space_number(self):
        p = parse_citation(
            "Riggs v. Twitter, Inc., No. CV 09-04302 LHK, "
            "2011 WL 2182299 (N.D. Cal. 2011)"
        )
        assert p.docket_number == "CV 09-04302 LHK"

    def test_extract_number_c_number(self):
        p = parse_citation(
            "Aikens v. Shalala, No. 03 C 7956, "
            "2005 WL 1307020 (N.D. Ill. 2005)"
        )
        assert p.docket_number == "03 C 7956"


class TestDocketNormalization:
    """Test _normalize_docket_number() expansion and cleanup."""

    @staticmethod
    def _norm(dn):
        return CitationVerifier._normalize_docket_number(dn)

    # --- Already working (regression) ---
    def test_division_prefix_and_leading_zeros(self):
        assert self._norm("2:17-cv-00012676") == "17-cv-12676"

    def test_cv_uppercase_who(self):
        # 20-CV-00155-WHO → 20-cv-155
        assert self._norm("20-CV-00155-WHO") == "20-cv-155"

    def test_shorthand_c_prefix(self):
        # C15-1228 → 15-cv-1228
        assert self._norm("C15-1228") == "15-cv-1228"

    def test_shorthand_cr_prefix(self):
        # CR15-1228 → 15-cr-1228
        assert self._norm("CR15-1228") == "15-cr-1228"

    # --- New patterns ---
    def test_c_space_number(self):
        # C 09-02727 → 9-cv-2727  (after judge suffix stripped)
        assert self._norm("C 09-02727 WHA") == "9-cv-2727"

    def test_cv_space_number(self):
        # CV 09-04302 → 9-cv-4302
        assert self._norm("CV 09-04302 LHK") == "9-cv-4302"

    def test_number_c_number(self):
        # 03 C 7956 → 3-cv-7956
        assert self._norm("03 C 7956") == "3-cv-7956"

    def test_c_hyphen_number(self):
        # C-12-6320 → 12-cv-6320
        assert self._norm("C-12-6320") == "12-cv-6320"

    def test_civ_suffix(self):
        # 20-20720-Civ → 20-cv-20720
        assert self._norm("20-20720-Civ") == "20-cv-20720"

    def test_civ_suffix_uppercase(self):
        # 24-61529-CIV → 24-cv-61529
        assert self._norm("24-61529-CIV") == "24-cv-61529"

    def test_civ_suffix_with_division_prefix(self):
        # 1:10-23641-CIV → 10-cv-23641
        assert self._norm("1:10-23641-CIV") == "10-cv-23641"

    def test_multi_segment_judge_suffix(self):
        # 2:24-CV-00326-JPH-MJD → 24-cv-326
        assert self._norm("2:24-CV-00326-JPH-MJD") == "24-cv-326"

    def test_trailing_hyphen(self):
        # 24-cv-00953-DC- → 24-cv-953
        assert self._norm("24-cv-00953-DC-") == "24-cv-953"


# ---------------------------------------------------------------------------
# Syllabus preservation
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="v0.3: matched_syllabus dropped from VerificationResult. "
    "Phase 1 only persists final_ids + resolution_path; cluster-level "
    "syllabus metadata is no longer surfaced. Revisit if a consumer "
    "needs it (would belong in resolution_path[*].raw_response_summary)."
)
class TestSyllabusPreservation:
    """Verify that syllabus data from citation-lookup is preserved."""

    def test_citation_lookup_preserves_syllabus(self):
        """When citation-lookup returns a cluster with syllabus, it's on the result."""
        client = _make_client(
            citation_lookup=[
                {
                    "citation": "202 F.3d 770",
                    "clusters": [
                        {
                            "case_name": "Tompkins v. Cyr",
                            "id": 19782,
                            "absolute_url": "/opinion/19782/tompkins-v-cyr/",
                            "court": "ca5",
                            "date_filed": "2000-01-26",
                            "syllabus": "RICO; anti-abortion protesters; harassment; emotional distress",
                            "nature_of_suit": "440 Civil Rights: Other",
                        }
                    ],
                }
            ]
        )

        v = CitationVerifier(client)
        result = v.verify("Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)")

        assert result.matched_syllabus is not None
        assert "RICO" in result.matched_syllabus or "abortion" in result.matched_syllabus

    def test_citation_lookup_no_syllabus(self):
        """When cluster has no syllabus, field is None."""
        client = _make_client(
            citation_lookup=[
                {
                    "citation": "337 F.3d 550",
                    "clusters": [
                        {
                            "case_name": "King v. Illinois Central Railroad",
                            "id": 8437633,
                            "absolute_url": "/opinion/8437633/king/",
                            "court": "ca5",
                            "date_filed": "2003-07-16",
                        }
                    ],
                }
            ]
        )

        v = CitationVerifier(client)
        result = v.verify("King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)")

        assert result.matched_syllabus is None


# ---------------------------------------------------------------------------
# Phase 2: ResolutionPath shape + terminal finalize helper
# ---------------------------------------------------------------------------


REQUIRED_KEYS = {
    (StageName.citation_lookup, StageVerdict.resolved): {
        "matched_cluster_id", "matched_case_name", "clusters_returned",
    },
    (StageName.citation_lookup, StageVerdict.no_match): {"clusters_returned"},
    (StageName.citation_lookup, StageVerdict.errored): {"error_type"},
    (StageName.opinion_search, StageVerdict.resolved): {
        "candidate_count", "best_score", "best_case_name", "best_cluster_id",
    },
    (StageName.opinion_search, StageVerdict.no_match): {"candidate_count"},
    (StageName.opinion_search, StageVerdict.errored): {"error_type"},
    (StageName.recap_document_search, StageVerdict.resolved): {
        "docket_count", "best_score", "best_docket_id", "best_case_name",
    },
    (StageName.recap_document_search, StageVerdict.no_match): {"docket_count"},
    (StageName.recap_document_search, StageVerdict.errored): {"error_type"},
    (StageName.recap_docket_search, StageVerdict.resolved): {
        "docket_count", "best_score", "best_docket_id", "best_case_name",
    },
    (StageName.recap_docket_search, StageVerdict.no_match): {"docket_count"},
    (StageName.recap_docket_search, StageVerdict.errored): {"error_type"},
}


class TestResolutionPathShape:
    """Phase 2 path-shape coverage for the citation_lookup stage.

    These tests assert on path entries directly (not via the
    _diagnostics compat helper), because the entries are what
    Phase 2 instruments. The compat helper covers warnings+notes
    legacy reads; this class covers structured path-entry reads.
    """

    def test_citation_lookup_hit_produces_one_resolved_entry(self):
        client = _make_client(citation_lookup=[
            {"clusters": [{"id": 100, "case_name": "Foo v. Bar", "absolute_url": "/opinion/100/"}]},
        ])
        verifier = CitationVerifier(client=client)
        result = verifier.verify("100 U.S. 1 (2020)")

        assert result.status == Status.VERIFIED
        assert len(result.resolution_path) == 1
        entry = result.resolution_path[0]
        assert entry.stage == StageName.citation_lookup
        assert entry.verdict == StageVerdict.resolved
        assert entry.confidence == 1.0
        assert entry.raw_response_summary == {
            "matched_cluster_id": 100,
            "matched_case_name": "Foo v. Bar",
            "clusters_returned": 1,
        }
        assert entry.query["text"].startswith("100 U.S. 1")
        assert entry.elapsed_ms >= 0

    def test_citation_lookup_miss_quick_only_records_no_match_entry(self):
        client = _make_client(citation_lookup=[])
        verifier = CitationVerifier(client=client)
        result = verifier.verify("999 U.S. 999 (2099)", quick_only=True)

        assert result.status == Status.NOT_FOUND
        assert len(result.resolution_path) == 1
        entry = result.resolution_path[0]
        assert entry.stage == StageName.citation_lookup
        assert entry.verdict == StageVerdict.no_match
        assert entry.raw_response_summary == {"clusters_returned": 0}

    def test_citation_lookup_error_records_errored_entry_then_falls_through(self):
        """The §2.8 internal API-error gate lands in Phase 4. In Phase 2,
        an errored citation_lookup entry must still appear in the path,
        and the verifier must still fall through to opinion_search (no
        behavior change vs. Phase 1)."""
        client = _make_client()
        client.citation_lookup.side_effect = ConnectionError("network down")
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Smith v. Jones, 1 F.3d 1 (1st Cir. 1990)")

        # First entry is citation_lookup, errored.
        assert result.resolution_path[0].stage == StageName.citation_lookup
        assert result.resolution_path[0].verdict == StageVerdict.errored
        assert result.resolution_path[0].raw_response_summary == {"error_type": "ConnectionError"}
        assert "ConnectionError" in (result.resolution_path[0].notes or "")
        # Falls through to opinion_search per existing Phase 1 behavior.
        assert len(result.resolution_path) >= 2
        assert result.resolution_path[1].stage == StageName.opinion_search

    def test_opinion_search_hit_after_citation_lookup_miss(self):
        client = _make_client(
            citation_lookup=[],
            search_opinions=[{
                "caseName": "Foo v. Bar",
                "cluster_id": 200,
                "dateFiled": "2020-06-15",
                "court_id": "scotus",
                "absolute_url": "/opinion/200/",
                "citation": ["100 U.S. 1"],
                "docketNumber": "",
            }],
        )
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Foo v. Bar, 100 U.S. 1 (Sup. Ct. 2020)")

        stages = [e.stage for e in result.resolution_path]
        assert stages == [StageName.citation_lookup, StageName.opinion_search]
        assert result.resolution_path[0].verdict == StageVerdict.no_match
        assert result.resolution_path[1].verdict == StageVerdict.resolved
        # raw_response_summary shape on opinion_search resolved
        summary = result.resolution_path[1].raw_response_summary
        assert summary["candidate_count"] >= 1
        assert "best_score" in summary
        assert summary["best_case_name"] == "Foo v. Bar"
        assert summary["best_cluster_id"] == 200

    def test_recap_docket_search_attempted_when_opinion_search_misses(self):
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[{
                "caseName": "Smith v. Jones",
                "docket_id": 500,
                "court_id": "cand",
                "docket_absolute_url": "/docket/500/",
                "recap_documents": [{
                    "short_description": "Opinion and order",
                    "date_filed": "2020-06-15",
                    "is_free_on_pacer": True,
                    "page_count": 20,
                    "absolute_url": "/recap/500/1/",
                    "entry_date_filed": "2020-06-15",
                    "entry_description": "ORDER granting motion to dismiss",
                }],
            }],
        )
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Smith v. Jones, No. 20-cv-1234 (N.D. Cal. June 15, 2020)")

        stages = [e.stage for e in result.resolution_path]
        # docket_number present -> recap_document_search runs;
        # case_name present -> recap_docket_search runs after.
        assert StageName.citation_lookup in stages
        assert StageName.opinion_search in stages
        assert StageName.recap_docket_search in stages or StageName.recap_document_search in stages
        # The RECAP stage that resolved should be a `resolved` verdict.
        recap_entries = [
            e for e in result.resolution_path
            if e.stage in (StageName.recap_document_search, StageName.recap_docket_search)
        ]
        assert any(e.verdict == StageVerdict.resolved for e in recap_entries)

    def test_all_stages_miss_produces_no_match_path(self):
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)")

        assert result.status == Status.NOT_FOUND
        stages = [e.stage for e in result.resolution_path]
        # Must include citation_lookup + opinion_search at minimum.
        assert stages[0] == StageName.citation_lookup
        assert StageName.opinion_search in stages
        # Every entry's verdict is no_match (no errored or resolved).
        assert all(
            e.verdict == StageVerdict.no_match for e in result.resolution_path
        )

    def test_state_court_skips_recap_stages(self):
        """RECAP is federal PACER data only. State-court citations should
        not emit recap_*_search entries (the guard is in _search_fallback)."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        verifier = CitationVerifier(client=client)
        # "(Cal. Ct. App. 2020)" -> state court
        result = verifier.verify("Foo v. Bar, 99 Cal.App.5th 99 (Cal. Ct. App. 2020)")

        stages = [e.stage for e in result.resolution_path]
        assert StageName.recap_document_search not in stages
        assert StageName.recap_docket_search not in stages

    def test_opinion_search_error_falls_through_to_recap(self):
        client = _make_client(citation_lookup=[])
        client.search_opinions.side_effect = ConnectionError("opinion search down")
        client.search_recap.return_value = []
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)")

        entries_by_stage = {e.stage: e for e in result.resolution_path}
        assert entries_by_stage[StageName.opinion_search].verdict == StageVerdict.errored
        assert entries_by_stage[StageName.opinion_search].raw_response_summary == {
            "error_type": "ConnectionError",
        }

    @pytest.mark.parametrize("scenario_name,citation,client_kwargs,quick_only", [
        (
            "citation_lookup_resolved",
            "Foo v. Bar, 100 U.S. 1 (2020)",
            {"citation_lookup": [{"clusters": [
                {"id": 1, "case_name": "Foo v. Bar", "absolute_url": "/opinion/1/"},
            ]}]},
            False,
        ),
        (
            "citation_lookup_no_match_quick_only",
            "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)",
            {"citation_lookup": []},
            True,
        ),
        (
            "opinion_search_resolved",
            "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
            {"citation_lookup": [], "search_opinions": [{
                "caseName": "Foo v. Bar", "cluster_id": 200,
                "dateFiled": "2020-06-15", "court_id": "ca1",
                "absolute_url": "/opinion/200/", "citation": ["100 F.3d 100"],
                "docketNumber": "",
            }]},
            False,
        ),
        (
            "opinion_search_no_match",
            "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
            {"citation_lookup": [], "search_opinions": [], "search_recap": []},
            False,
        ),
        (
            "recap_resolved",
            "Smith v. Jones, No. 20-cv-1234 (N.D. Cal. June 15, 2020)",
            {"citation_lookup": [], "search_opinions": [], "search_recap": [{
                "caseName": "Smith v. Jones", "docket_id": 500, "court_id": "cand",
                "docket_absolute_url": "/docket/500/",
                "recap_documents": [{
                    "short_description": "Opinion and order",
                    "date_filed": "2020-06-15", "is_free_on_pacer": True,
                    "page_count": 20, "absolute_url": "/recap/500/1/",
                    "entry_date_filed": "2020-06-15",
                    "entry_description": "ORDER granting motion to dismiss",
                }],
            }]},
            False,
        ),
    ])
    def test_raw_response_summary_required_keys_per_stage_verdict(
        self, scenario_name, citation, client_kwargs, quick_only,
    ):
        """Every (stage, verdict) tuple has a documented minimum key set
        in raw_response_summary. Each scenario exercises a different stage
        combination; the assertion runs across every entry produced."""
        client = _make_client(**client_kwargs)
        verifier = CitationVerifier(client=client)
        result = verifier.verify(citation, quick_only=quick_only)
        assert result.resolution_path, f"{scenario_name}: empty resolution_path"
        for entry in result.resolution_path:
            required = REQUIRED_KEYS.get((entry.stage, entry.verdict))
            assert required is not None, (
                f"{scenario_name}: no required-keys spec for "
                f"({entry.stage}, {entry.verdict}) — update REQUIRED_KEYS or fix the verdict"
            )
            missing = required - entry.raw_response_summary.keys()
            assert not missing, (
                f"{scenario_name}: stage {entry.stage}, verdict {entry.verdict}: "
                f"missing keys {missing} in raw_response_summary={entry.raw_response_summary}"
            )

    @pytest.mark.parametrize("error_target", [
        "citation_lookup", "search_opinions", "search_recap",
    ])
    def test_errored_entry_carries_error_type_key(self, error_target):
        """Errored stage entries must have raw_response_summary={'error_type': ...}.
        Exercises each stage's error path independently."""
        client = _make_client(citation_lookup=[], search_opinions=[], search_recap=[])
        getattr(client, error_target).side_effect = ConnectionError("down")
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)")
        errored = [e for e in result.resolution_path if e.verdict == StageVerdict.errored]
        assert errored, f"expected at least one errored entry when {error_target} raises"
        for e in errored:
            assert e.raw_response_summary == {"error_type": "ConnectionError"}


class TestFinalizeResultTerminalShape:
    """The terminal helper wraps the builder's accumulated entries into
    a VerificationResult and is the only public producer of results
    inside the verifier. Phase 1's _build_result is gone."""

    def test_verifier_module_does_not_expose_build_result(self):
        from citation_verifier import verifier as v
        # Phase 1's _build_result is replaced by _finalize_result in Phase 2.
        # If you see _build_result on the class, the migration is incomplete.
        assert not hasattr(v.CitationVerifier, "_build_result"), (
            "_build_result should be removed in Phase 2; use _finalize_result"
        )
        assert hasattr(v.CitationVerifier, "_finalize_result")


# ---------------------------------------------------------------------------
# Phase 3 Task 3: VERIFIED_PARTIAL detection (silent partial verification)
# ---------------------------------------------------------------------------


class TestVerifiedPartial:
    """Phase 3: silent partial verification (design §2.2 VERIFIED_PARTIAL)."""

    def test_partial_when_primary_reporter_not_in_cluster_citations(self):
        """NY A.D.3d + slip op pattern: parallel resolves, primary does not."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Gilliam v. Uni Holdings",
                            "id": 5305052,
                            "absolute_url": "/opinion/5305052/gilliam/",
                            # CL's citation index has the slip op but NOT
                            # the A.D.3d reporter — that's what makes it
                            # the silent-partial case.
                            "citations": [
                                {"volume": "2021", "reporter": "NY Slip Op",
                                 "page": "06798", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Gilliam v. Uni Holdings, 201 A.D.3d 83, 88-89, "
            "2021 NY Slip Op 06798 (N.Y. App. Div. 2021)"
        )
        assert result.status == Status.VERIFIED_PARTIAL
        assert any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )
        # The citation_lookup stage still resolved — confidence stays high.
        assert _winning_path_entry(result).verdict == StageVerdict.resolved

    def test_verified_not_partial_when_primary_in_cluster_citations(self):
        """Peerenboom-shape: A.D.3d IS in CL — VERIFIED not PARTIAL."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Peerenboom v. Marvel Entertainment",
                            "id": 4376072,
                            "absolute_url": "/opinion/4376072/peerenboom/",
                            "citations": [
                                {"volume": "148", "reporter": "A.D.3d",
                                 "page": "531", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Peerenboom v. Marvel Entertainment, LLC, 148 A.D.3d 531 "
            "(N.Y. App. Div. 2017)"
        )
        assert result.status == Status.VERIFIED
        assert not any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )

    def test_verified_when_wl_only_input(self):
        """A WL-only citation (no parallel reporter) is VERIFIED, not PARTIAL."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Some Case",
                            "id": 999,
                            "absolute_url": "/opinion/999/",
                            "citations": [
                                {"volume": "2020", "reporter": "WL",
                                 "page": "123456", "type": 9},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Some Case, 2020 WL 123456 (D. Md. 2020)")
        assert result.status == Status.VERIFIED


class TestVerifiedViaRecapVsDocketOnly:
    """Phase 3 Task 4: strict VIA_RECAP gate per maintainer Q1.

    Tests at the doc-type + date-match boundary. Cabot/Hunter shape:
    has-text-but-procedural-order -> DOCKET_ONLY. Mehar shape:
    opinion-typed + date-matched -> VIA_RECAP.
    """

    def test_via_recap_when_opinion_typed_doc_matches_date(self):
        client = _make_client(
            citation_lookup=[],          # no opinion cluster
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": "OPINION on motion to dismiss",
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.docket_id == 5474769
        assert result.final_ids.recap_document_id == 18720567
        assert result.final_ids.cluster_id is None
        assert result.final_ids.text_source.value == "recap_document"

    def test_docket_only_when_doc_is_motion_filing_mentioning_opinion(self):
        """Reciprocal gap to Mehar: a party-filed motion whose description
        mentions 'OPINION' as the target of the motion (e.g.
        'MOTION FOR RECONSIDERATION OF OPINION') must NOT be accepted as the
        cited opinion, even though it contains the 'opinion' keyword and
        falls within the ±14 day date window. Phase 3 Task 4 code-review
        follow-up: '_PROCEDURAL_KEYWORDS' deliberately excludes the
        'motion for' substring so that 'OPINION on motion for X' is still
        accepted, but a doc whose description *starts* with 'motion for'
        is a party filing, not the court's opinion."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Sample v. Counterparty",
                    "docket_id": 99999001,
                    "id": 99999001,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/99999001/sample/",
                    "dateFiled": "2020-05-01",
                    "docketNumber": "1:20-cv-00001",
                    "recap_documents": [
                        {
                            "id": 99999101,
                            "entry_date_filed": "2020-05-01",
                            "short_description": "MOTION FOR RECONSIDERATION OF OPINION",
                            "page_count": 4,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Sample v. Counterparty, 2020 WL 1234567 (W.D. Tex. May 1, 2020)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 99999001
        assert result.final_ids.recap_document_id is None

    def test_docket_only_when_doc_is_procedural_order(self):
        """Cabot v. Lewis shape: order certifying interlocutory appeal
        is text-bearing but procedural. Strict reading: DOCKET_ONLY."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": "ORDER CERTIFYING INTERLOCUTORY APPEAL",
                            "page_count": 2,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 4275225
        assert result.final_ids.recap_document_id is None
        assert result.final_ids.text_source is None

    def test_docket_only_when_date_mismatches(self):
        """Menges-actual shape: docket exists, doc on docket is dated
        June 12 but cited May 31 (12-day delta — actually WITHIN ±14 day
        window). DOCKET_ONLY here because the doc description matches the
        'motion in limine' procedural keyword, not because of date. See
        test_phase3_corpus_acceptance.py for a true outside-window case."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Menges v. Cliffs Drilling Co.",
                    "docket_id": 10993603,
                    "id": 10993603,
                    "court_id": "laed",
                    "docket_absolute_url": "/docket/10993603/menges/",
                    "dateFiled": "1999-07-16",
                    "docketNumber": "99-2061",
                    "recap_documents": [
                        {
                            "id": 476627754,
                            "entry_date_filed": "2000-06-12",
                            "short_description": "ORDER & REASONS on motion in limine",
                            "page_count": 4,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. May 31, 2000)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 10993603
        assert result.final_ids.recap_document_id is None


# ---------------------------------------------------------------------------
# Phase 4 Task 4: score-based VIA_RECAP gate (Q2)
# ---------------------------------------------------------------------------


class TestVerifiedViaRecapScoreGate:
    """Phase 4 Task 4 (Q2): score-based VIA_RECAP gate catches
    substantive-but-keyword-poor opinion descriptions like Mehar
    Holdings' 'ORDER GRANTING Motion for Reconsideration'."""

    def test_score_based_gate_accepts_substantive_long_form_doc(self):
        """Mehar Holdings shape: 12-page is_free_on_pacer doc with
        'ORDER GRANTING' description -> VIA_RECAP via score gate."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.recap_document_id == 18720567

    def test_score_gate_does_not_override_procedural_keywords(self):
        """Cabot v. Lewis shape: 'ORDER CERTIFYING INTERLOCUTORY APPEAL'
        matches a procedural keyword and stays DOCKET_ONLY even with
        a 5-page count + is_free_on_pacer."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": (
                                "ORDER CERTIFYING INTERLOCUTORY APPEAL"
                            ),
                            "page_count": 8,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY

    def test_score_gate_requires_both_page_count_and_is_free(self):
        """A short doc (page_count < 5) fails the score gate even with
        a non-procedural description and is_free_on_pacer=True."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    # Full caption (both cited parties) so the party-mismatch
                    # cap does not fire — this test isolates the page_count /
                    # is_free score gate, not name matching.
                    "caseName": "Short Case v. Other",
                    "docket_id": 9999,
                    "id": 9999,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/9999/short/",
                    "dateFiled": "2020-06-15",
                    "docketNumber": "1:20-cv-00001",
                    "recap_documents": [
                        {
                            "id": 12345,
                            "entry_date_filed": "2020-06-15",
                            "short_description": "ORDER on motion",
                            "page_count": 2,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Short Case v. Other, 2020 WL 999999 (W.D. Tex. June 15, 2020)")
        assert result.status == Status.VERIFIED_DOCKET_ONLY

    def test_score_gate_fetches_doc_detail_when_search_omits_metadata(self):
        """search_recap may return docs with page_count=None / is_free_on_pacer=None.

        Those fields are only populated on /recap-documents/{id}/. When the
        keyword/date gate path (b) fails AND page_count==0 (the zero sentinel
        meaning "not populated"), the verifier fetches the doc detail and re-
        applies the score gate. If the detail says page_count>=5 and
        is_free_on_pacer=True, the result should be VERIFIED_VIA_RECAP.
        """
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            # No opinion keyword, no date window match → path (b) fails.
                            # page_count/is_free_on_pacer omitted by search → zero/False.
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": None,
                            "is_free_on_pacer": None,
                        }
                    ],
                }
            ],
            # doc-detail fetch supplies the real values
            recap_document_metadata={
                "id": 18720567,
                "page_count": 12,
                "is_free_on_pacer": True,
            },
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.recap_document_id == 18720567
        # Verify the doc-detail fetch was actually called
        client.get_recap_document_metadata.assert_called_once_with(18720567)

    def test_score_gate_doc_detail_fetch_failure_falls_back_to_docket_only(self):
        """If the doc-detail fetch raises, the gate stays DOCKET_ONLY.

        A failed refinement must NOT promote to VERIFICATION_INCOMPLETE /
        errored — it should silently leave the result at DOCKET_ONLY.
        """
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": None,
                            "is_free_on_pacer": None,
                        }
                    ],
                }
            ],
            # Simulate a network/API failure on the doc-detail fetch.
            recap_document_metadata=ConnectionError("simulated network failure"),
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        # Refinement failed → fall through to DOCKET_ONLY, no exception raised.
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.status != Status.VERIFICATION_INCOMPLETE


class TestNamesMatchXvUnitedStates:
    """Phase 4 Task 5 (Q3): generic-government-defendant patterns must
    require defendant-side overlap, mirroring the existing United-
    States-as-plaintiff logic."""

    @pytest.fixture
    def parser(self):
        from citation_verifier.parser import parse_citation
        return parse_citation

    def test_koch_v_us_with_different_us_defendant_fails_match(self, parser):
        """Brief: 'Koch v. United States'. CL returns: 'Ricky Koch v. Tote,
        Incorporated'. The defendant (United States) and CL's defendant
        (Tote) don't overlap; the new gate must return False so
        caption_investigation fires and emits cl_display_name_data_bug."""
        parsed = parser("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Ricky Koch v. Tote, Incorporated")
        assert result is False, (
            "X v. United States with a CL-side different defendant must "
            "NOT lenient-match; caption_investigation must fire."
        )

    def test_koch_v_us_with_same_us_defendant_passes_match(self, parser):
        """Sanity: when CL also has 'X v. United States' shape with the
        same plaintiff, the lenient match still works."""
        parsed = parser("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Koch v. United States")
        assert result is True

    def test_x_v_state_pattern_requires_defendant_overlap(self, parser):
        parsed = parser("Smith v. State, 100 So. 3d 100 (Ala. 2020)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Smith v. ABC Corp")
        assert result is False

    def test_x_v_commonwealth_pattern_requires_defendant_overlap(self, parser):
        parsed = parser("Doe v. Commonwealth, 200 S.E.2d 200 (Va. 2020)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Doe v. XYZ Inc.")
        assert result is False


# ---------------------------------------------------------------------------
# INSUFFICIENT_DATA short-circuit — promote NOT_FOUND when the parsed citation
# lacks both court and year anchors. Distinct from NOT_FOUND because "we
# couldn't tell" is a different signal than "we tried and found nothing
# convincing". See scratch/TODO.md "INSUFFICIENT_DATA" entry.
# ---------------------------------------------------------------------------


class TestInsufficientData:
    """Promotion fires only when status would otherwise be NOT_FOUND AND
    parsed.court is None AND parsed.year is None. Other statuses keep
    their semantics — they each carry more actionable signal than the
    INSUFFICIENT_DATA promotion would."""

    def _parsed_with(self, *, court: str | None, year: int | None):
        from citation_verifier.models import ParsedCitation
        return ParsedCitation(
            raw_text="Doe v. Roe",
            case_name="Doe v. Roe",
            plaintiff="Doe",
            defendant="Roe",
            court=court,
            year=year,
        )

    def test_promotes_to_insufficient_data_when_court_and_year_missing(self):
        """Main case: lookup misses, opinion_search misses, court+year both
        None → INSUFFICIENT_DATA (not NOT_FOUND)."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Doe v. Roe",
            parsed=self._parsed_with(court=None, year=None),
        )
        assert result.status == Status.INSUFFICIENT_DATA

    def test_promotion_nulls_final_ids(self):
        """Mirrors the VERIFICATION_INCOMPLETE pattern (design v2 §2.8):
        consumers cannot mistake INSUFFICIENT_DATA for partial verification.
        All FinalIds are nulled on promotion."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Doe v. Roe",
            parsed=self._parsed_with(court=None, year=None),
        )
        assert result.status == Status.INSUFFICIENT_DATA
        assert result.final_ids.cluster_id is None
        assert result.final_ids.docket_id is None
        assert result.final_ids.recap_document_id is None
        assert result.final_ids.absolute_url is None
        assert result.final_ids.text_source is None

    def test_no_promotion_when_court_is_set(self):
        """Court present blocks promotion — opinion_search could filter by
        court even if year is missing. Stay NOT_FOUND."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Doe v. Roe",
            parsed=self._parsed_with(court="ca9", year=None),
        )
        assert result.status == Status.NOT_FOUND

    def test_no_promotion_when_year_is_set(self):
        """Year present blocks promotion — even without court, opinion_search
        gets a date window. Stay NOT_FOUND."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Doe v. Roe",
            parsed=self._parsed_with(court=None, year=2020),
        )
        assert result.status == Status.NOT_FOUND

    def test_no_promotion_when_lookup_succeeds(self):
        """VERIFIED keeps its semantics regardless of parse weakness — we
        actually found the case via citation_lookup, the parse quality is
        moot. Promotion only fires on NOT_FOUND."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Doe v. Roe",
                            "id": 12345,
                            "absolute_url": "/opinion/12345/doe-v-roe/",
                        }
                    ]
                }
            ],
            search_opinions=[],
            search_recap=[],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Doe v. Roe",
            parsed=self._parsed_with(court=None, year=None),
        )
        assert result.status == Status.VERIFIED
        assert result.final_ids.cluster_id == 12345


class TestRecapHardGates:
    """Lever 1 (Tier 1 Step 2): the RECAP path must apply the same
    name-token and temporal hard-gates the opinion-search path
    (_process_results) already applies -- with the temporal gate made
    ONE-SIDED, because a RECAP result's dateFiled is the case *filing*
    date, not the opinion date. An opinion cannot predate its own case,
    so a cite far *before* the filing year is impossible and gets
    rejected; a cite *after* filing (an opinion issued years into a
    long-running case) is legitimate and must be kept. See
    docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
    """

    def test_name_token_gate_rejects_zero_overlap_docket(self):
        """A RECAP docket sharing no distinctive name token with the cited
        caption is gated out. South Pointe Wholesale -> Thompson v.
        Martuscello was a v0.3 false positive (VERIFIED_DOCKET_ONLY 0.42)."""
        v = CitationVerifier(_make_client())
        parsed = parse_citation(
            "South Pointe Wholesale, Inc. v. Vilardi, No. 16-CV-6758, "
            "2017 WL 11570668 (E.D.N.Y. May 2, 2017)"
        )
        results = [{
            "caseName": "Thompson v. Martuscello",
            "docket_id": 13440058,
            "court_id": "nyed",
            "dateFiled": "2017-03-01",
            "recap_documents": [],
        }]
        assert v._process_recap_results(results, parsed) == []

    def test_temporal_gate_rejects_cite_far_before_filing(self):
        """In re Hudson: an 1812 cite against a 2018-filed docket is
        impossible (an opinion cannot predate its case). The name token
        'hudson' matches, so ONLY the temporal gate can reject it -- this
        was a v0.3 false positive (VERIFIED_DOCKET_ONLY 0.50)."""
        v = CitationVerifier(_make_client())
        parsed = parse_citation("In re Hudson, 11 U.S. 225 (U.S. 1812)")
        results = [{
            "caseName": "In re Hudson",
            "docket_id": 7786215,
            "court_id": "txsb",
            "dateFiled": "2018-06-01",
            "recap_documents": [],
        }]
        assert v._process_recap_results(results, parsed) == []

    def test_temporal_gate_rejects_pre_pacer_cite_with_null_filing_date(self):
        """In re Hudson actually resolves to a null-dateFiled appellate
        docket (CL never populated date_filed for it), so the date-diff
        check can't fire. An 1812 cite predates PACER's electronic records
        entirely, so a bare RECAP docket match on the surname 'hudson' is
        impossible -> reject via the PACER-era floor. This is the residual
        the dated-docket temporal test above does not cover."""
        v = CitationVerifier(_make_client())
        parsed = parse_citation("In re Hudson, 11 U.S. 225 (U.S. 1812)")
        results = [{
            "caseName": "In re: Hudson",
            "docket_id": 67311035,
            "court_id": "ca6",
            "dateFiled": None,
            "docketNumber": "16-6270",
            "recap_documents": [],
        }]
        assert v._process_recap_results(results, parsed) == []

    def test_temporal_gate_keeps_cite_long_after_filing(self):
        """ONE-SIDED guard: Oracle v. Google cites a 2016 opinion in a
        2010-filed case (6-year gap). A symmetric +/-5yr gate would
        wrongly reject this real citation; the one-sided gate keeps it."""
        v = CitationVerifier(_make_client())
        parsed = parse_citation(
            "Oracle Am., Inc. v. Google Inc., No. C 10-03561 WHA, "
            "2016 WL 3181206 (N.D. Cal. June 8, 2016)"
        )
        results = [{
            "caseName": "Oracle America, Inc. v. Google Inc.",
            "docket_id": 4177532,
            "court_id": "cand",
            "dateFiled": "2010-08-12",
            "recap_documents": [],
        }]
        assert len(v._process_recap_results(results, parsed)) == 1

    def test_name_token_gate_keeps_shared_token_docket(self):
        """A docket sharing a distinctive token with a plausible filing
        date is kept (guards against over-gating real RECAP matches)."""
        v = CitationVerifier(_make_client())
        parsed = parse_citation(
            "Marlite, Inc. v. Eckenrod, No. 10-23641-CIV, "
            "2012 WL 3614212 (S.D. Fla. Aug. 22, 2012)"
        )
        results = [{
            "caseName": "Marlite, Inc. v. Eckenrod",
            "docket_id": 4233374,
            "court_id": "flsd",
            "dateFiled": "2010-10-08",
            "recap_documents": [],
        }]
        assert len(v._process_recap_results(results, parsed)) == 1


class TestPartyMismatchPenalty:
    """Lever 2 (Tier 1 Step 2): _score_match must penalize a candidate that
    matches only ONE cited party while the other cited party is entirely
    absent -- surname-coincidence inflation. The penalty hits the name
    component only, so a real opinion whose court/date corroborate (a
    cl_display_name_data_bug case) survives; the false positives, which are
    wrong-court matches, drop below the resolution threshold. See
    docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
    """

    def _scorer(self):
        return CitationVerifier(_make_client())

    def test_defendant_only_match_drops_below_threshold(self):
        """Johnson v. Mitchell -> Scudder v. Mitchell: defendant 'Mitchell'
        matches, plaintiff 'Johnson' absent. Reconstructs the live v0.3
        false positive (VERIFIED 0.50): the wrong case is in the SAME court
        (ohsd) with an off-by-one date, so court+date corroborate and only
        the party-mismatch penalty can sink it."""
        v = self._scorer()
        parsed = parse_citation(
            "Johnson v. Mitchell, 2:20-cv-1882, 2020 WL 5649609 "
            "(S.D. Ohio Sept. 23, 2020)"
        )
        score, _ = v._score_match(
            parsed, "Scudder v. Mitchell", "ohsd", "2021-03-29", {}
        )
        assert score < _VERIFIED_SCORE_THRESHOLD

    def test_plaintiff_only_match_drops_below_threshold(self):
        """Thompson v. Best -> Thompson v. Thompson: plaintiff 'Thompson'
        matches, defendant 'Best' absent. Reconstructs the live v0.3 false
        positive (VERIFIED 0.625): wrong court but same year (2013), so the
        date credit must be overcome by the penalty."""
        v = self._scorer()
        parsed = parse_citation("Thompson v. Best, 989 N.E.2d 299 (Ind. Ct. App. 2013)")
        score, _ = v._score_match(
            parsed, "Thompson v. Thompson", "ind", "2013-08-30", {}
        )
        assert score < _VERIFIED_SCORE_THRESHOLD

    def test_party_mismatch_with_corroborating_court_date_still_capped(self):
        """Johnson v. Mitchell -> Laile v. Mitchell via RECAP: the wrong
        case sits in the SAME court (ohsd) with a 2020 document, so
        court+date alone reach ~0.45 regardless of the penalized name. The
        cited WL number is not in the candidate, so the match is
        uncorroborated and must be capped below threshold. The name-only
        multiplier is insufficient when court+date coincidentally match --
        this is why the cap (party mismatch AND no cite corroboration)
        exists. Discovered when Lever 2's opinion-path fix pushed Johnson
        down into a RECAP docket-only match on the same surname."""
        v = self._scorer()
        parsed = parse_citation(
            "Johnson v. Mitchell, 2:20-cv-1882, 2020 WL 5649609 "
            "(S.D. Ohio Sept. 23, 2020)"
        )
        score, _ = v._score_match(parsed, "Laile v. Mitchell", "ohsd", "2020-09-23", {})
        assert score < _VERIFIED_SCORE_THRESHOLD

    def test_party_mismatch_escapes_cap_when_cite_corroborates(self):
        """Safety hatch: a real opinion whose CL *display name* lists a
        different party (cl_display_name_data_bug) but whose reporter cite
        matches must NOT be capped -- the cite vouches for it. Same
        party-mismatch shape as above, but the candidate carries the cited
        reporter cite, so it stays resolvable."""
        v = self._scorer()
        parsed = parse_citation("Johnson v. Mitchell, 123 F.3d 456 (6th Cir. 2020)")
        result = {"citation": ["123 F.3d 456"]}
        score, _ = v._score_match(parsed, "Laile v. Mitchell", "ca6", "2020-06-01", result)
        assert score >= _VERIFIED_SCORE_THRESHOLD

    def test_both_parties_match_not_penalized(self):
        """Control: when both cited parties are present in the candidate
        (the real case, right court + date), the score stays resolvable --
        the penalty must not fire."""
        v = self._scorer()
        parsed = parse_citation("Thompson v. Best, 989 N.E.2d 299 (Ind. Ct. App. 2013)")
        score, _ = v._score_match(
            parsed, "Thompson v. Best", "indctapp", "2013-05-01", {}
        )
        assert score >= _VERIFIED_SCORE_THRESHOLD


class TestContradictionCap:
    """Lever 3 (Tier 1 Step 2): a candidate whose cited docket number or
    reporter/WL cite is PRESENT on both sides but CONTRADICTS the matched
    record is the wrong record -- even when name + court + date corroborate
    (the fake names a real case but a fabricated pinpoint cite). Cap below
    threshold, unless the cite or docket independently corroborates. The cap
    must never fire on an ABSENT value: real cites where CL simply lacks the
    WL/reporter number on the record keep passing. See
    docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
    """

    def _scorer(self):
        return CitationVerifier(_make_client())

    def test_docket_number_contradiction_caps_score(self):
        """Lopez v. Bank of Am., No. 14-cv-2524 -> the real Lopez/BofA
        docket 3:10-cv-01207. Name+court+date match the real docket; only
        the docket number contradicts (14-cv vs 10-cv). Was a v0.3 false
        positive (VERIFIED_DOCKET_ONLY 0.85)."""
        v = self._scorer()
        parsed = parse_citation(
            "Lopez v. Bank of Am., N.A., No. 14-cv-2524, 2016 WL 4131149 "
            "(N.D. Cal. Aug. 3, 2016)"
        )
        result = {"docketNumber": "3:10-cv-01207"}
        score, _ = v._score_match(
            parsed, "Lopez v. Bank of America, N.A.", "cand", "2016-08-03", result
        )
        assert score < _VERIFIED_SCORE_THRESHOLD

    def test_absent_docket_number_not_capped(self):
        """Same cite, but the candidate record carries NO docket number ->
        absent, not contradicting -> must NOT cap. Real RECAP matches often
        lack a docket number on the search result."""
        v = self._scorer()
        parsed = parse_citation(
            "Lopez v. Bank of Am., N.A., No. 14-cv-2524, 2016 WL 4131149 "
            "(N.D. Cal. Aug. 3, 2016)"
        )
        score, _ = v._score_match(
            parsed, "Lopez v. Bank of America, N.A.", "cand", "2016-08-03", {}
        )
        assert score >= _VERIFIED_SCORE_THRESHOLD

    def test_docket_contradiction_escaped_when_cite_matches(self):
        """A docket-number contradiction is forgiven when the reporter cite
        positively matches -- the cite vouches for the record (a typo'd
        docket on an otherwise-correct citation)."""
        v = self._scorer()
        parsed = parse_citation(
            "Lopez v. Bank of Am., N.A., No. 14-cv-2524, 789 F.3d 146 "
            "(9th Cir. 2016)"
        )
        result = {"docketNumber": "3:10-cv-01207", "citation": ["789 F.3d 146"]}
        score, _ = v._score_match(
            parsed, "Lopez v. Bank of America, N.A.", "ca9", "2016-08-03", result
        )
        assert score >= _VERIFIED_SCORE_THRESHOLD
