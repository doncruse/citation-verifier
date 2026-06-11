"""CiteCheck classification (Check Cite design 2026-06-11, §5.1).

The scorer reports a structured outcome for the cited reporter/WL location
vs the matched record's citation list. "Contradicted" requires a SAME-FAMILY
witness (design §3.1): the record must list a citation in the same reporter
family as the cited one. Cross-family absence (cited So. 3d, record lists
only Ala. App.; cited S. Ct., record lists U.S.) is NOT a contradiction —
it's the CL reporter gap / parallel-cite situation, NOT_ON_RECORD.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from citation_verifier.models import CiteCheck, ParsedCitation
from citation_verifier.verifier import CitationVerifier, _reporter_family


class TestReporterFamily:
    @pytest.mark.parametrize("reporter,family", [
        ("N.E.3d", "ne"),
        ("N.E.2d", "ne"),
        ("N.E.", "ne"),
        ("So. 3d", "so"),
        ("So. 2d", "so"),
        ("P.2d", "p"),
        ("P.3d", "p"),
        ("S.W.3d", "sw"),
        ("U.S.", "us"),
        ("S. Ct.", "sct"),
        ("L. Ed. 2d", "led"),
        ("F. Supp. 3d", "fsupp"),
        ("F. Supp.", "fsupp"),
        ("F.3d", "f"),
        ("F.4th", "f"),
        ("Cal.App.5th", "calapp"),
        ("Wn.2d", "wn"),
        ("WL", "wl"),
        ("VT", "vt"),
    ])
    def test_family_normalization(self, reporter, family):
        assert _reporter_family(reporter) == family

    def test_us_and_sct_are_different_families(self):
        assert _reporter_family("U.S.") != _reporter_family("S. Ct.")


def _score(parsed, result):
    v = CitationVerifier(MagicMock())
    return v._score_match(parsed, "Taylor v. State", "ind", "2019-06-01", result)


def _parsed_reporter(volume="133", reporter="N.E.3d", page="708"):
    return ParsedCitation(
        raw_text="x", case_name="Taylor v. State",
        volume=volume, reporter=reporter, page=page, year=2019,
    )


class TestScoreMatchCiteCheck:
    def test_corroborated_when_cited_location_on_record(self):
        _, _, check = _score(
            _parsed_reporter(),
            {"citation": ["133 N.E.3d 708"]},
        )
        assert check is CiteCheck.CORROBORATED

    def test_contradicted_when_same_family_witness_differs(self):
        # The real Taylor v. State's N.E.3d cite is elsewhere — same family,
        # different address. This is the Charlotin bucket-B signature.
        _, _, check = _score(
            _parsed_reporter(),
            {"citation": ["119 N.E.3d 1234"]},
        )
        assert check is CiteCheck.CONTRADICTED

    def test_series_collapse_within_family(self):
        # N.E.2d witness contradicts an N.E.3d cite (same family, older series)
        _, _, check = _score(
            _parsed_reporter(reporter="N.E.3d"),
            {"citation": ["712 N.E.2d 828"]},
        )
        assert check is CiteCheck.CONTRADICTED

    def test_cross_family_absence_is_not_contradiction(self):
        # Muldrow: cited 144 S. Ct. 967, CL lists the U.S. parallel only.
        parsed = ParsedCitation(
            raw_text="x", case_name="Muldrow v. City of St. Louis",
            volume="144", reporter="S. Ct.", page="967", year=2024,
        )
        _, _, check = _score(parsed, {"citation": ["601 U.S. 346"]})
        assert check is CiteCheck.NOT_ON_RECORD

    def test_regional_vs_official_state_reporter_is_not_contradiction(self):
        # cited So. 3d; record lists only the official state reporter
        parsed = ParsedCitation(
            raw_text="x", case_name="Smith v. Jones",
            volume="123", reporter="So. 3d", page="456", year=2013,
        )
        _, _, check = _score(parsed, {"citation": ["57 Ala. App. 89"]})
        assert check is CiteCheck.NOT_ON_RECORD

    def test_not_on_record_when_record_has_no_citations(self):
        _, _, check = _score(_parsed_reporter(), {"citation": []})
        assert check is CiteCheck.NOT_ON_RECORD

    def test_not_on_record_when_citation_field_absent(self):
        _, _, check = _score(_parsed_reporter(), {})
        assert check is CiteCheck.NOT_ON_RECORD

    def test_no_cite_in_input(self):
        parsed = ParsedCitation(
            raw_text="x", case_name="Taylor v. State", year=2019,
            docket_number="19-cv-123",
        )
        _, _, check = _score(parsed, {"citation": ["119 N.E.3d 1234"]})
        assert check is CiteCheck.NO_CITE_IN_INPUT

    def test_wl_corroborated(self):
        parsed = ParsedCitation(
            raw_text="x", case_name="Viken Detection Corp. v. Doe",
            is_westlaw=True, wl_number="2019 WL 5268725", year=2019,
        )
        _, _, check = _score(parsed, {"citation": ["2019 WL 5268725"]})
        assert check is CiteCheck.CORROBORATED

    def test_wl_contradicted_by_other_wl_on_record(self):
        parsed = ParsedCitation(
            raw_text="x", case_name="Navient v. Lohman",
            is_westlaw=True, wl_number="2020 WL 1864871", year=2020,
        )
        _, _, check = _score(parsed, {"citation": ["2020 WL 1867939"]})
        assert check is CiteCheck.CONTRADICTED

    def test_wl_not_on_record_when_record_lists_only_reporters(self):
        parsed = ParsedCitation(
            raw_text="x", case_name="Oracle v. Google",
            is_westlaw=True, wl_number="2016 WL 3181206", year=2016,
        )
        _, _, check = _score(parsed, {"citation": ["872 F.3d 100"]})
        assert check is CiteCheck.NOT_ON_RECORD


class TestCandidateCarriesCiteCheck:
    def test_process_results_sets_cite_check(self):
        v = CitationVerifier(MagicMock())
        candidates = v._process_results(
            [{
                "caseName": "Taylor v. State",
                "id": 42,
                "dateFiled": "2019-06-01",
                "court_id": "ind",
                "citation": ["119 N.E.3d 1234"],
            }],
            _parsed_reporter(),
        )
        assert len(candidates) == 1
        assert candidates[0].cite_check is CiteCheck.CONTRADICTED
