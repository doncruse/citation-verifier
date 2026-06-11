"""Bug 1 (Charlotin 2026-06-11 triage): parse_citation returned
case_name=None on NY, California, paren-led, and surname-only citation
forms. A nameless parse that resolved at citation-lookup skipped the
name-mismatch check entirely and blind-VERIFIED@1.0 against whatever
cluster CL returned (20+ false positives, the dominant FP mechanism).

These tests pin name extraction for each failing form, plus negatives
for forms that genuinely carry no name (those flow to the
VERIFIED_PARTIAL + name_unverified policy in the verifier instead).
"""

from __future__ import annotations

import pytest

from citation_verifier.parser import parse_citation


class TestNYNameForms:
    """NY citations write 'v' without a period and often arrive with the
    'Matter' of 'Matter of' truncated by extraction."""

    def test_v_without_period(self):
        p = parse_citation(
            "Harris v Seward Park Housing Corp., 147 AD3d 589 (1st Dep't 2017)"
        )
        assert p.case_name is not None
        assert p.case_name.startswith("Harris v. Seward Park")
        assert p.plaintiff == "Harris"

    def test_v_without_period_with_ampersand_defendant(self):
        p = parse_citation(
            "DiLorenzo v D.C. & D. Transp. Corp., 39 AD2d 950 (2nd Dept, 1972)"
        )
        assert p.case_name is not None
        assert p.case_name.startswith("DiLorenzo v.")

    def test_truncated_matter_of_prefix_stripped(self):
        # eyecite span extraction loses "Matter", leaving "of Knapp v Knapp".
        p = parse_citation("of Knapp v Knapp, 225 AD2d 1010 (4th Dept 1996)")
        assert p.case_name == "Knapp v. Knapp"

    def test_truncated_of_prefix_with_org_parties(self):
        p = parse_citation(
            "of Medical Transport v NY State Dept of Health, "
            "294 A.D.2d 574 (2d Dept 2002)"
        )
        assert p.case_name is not None
        assert p.case_name.startswith("Medical Transport v.")

    def test_paren_led_citation(self):
        p = parse_citation(
            "(Backus v. City of Rochester, 148 AD3d 1697 [4th Dept 2017])"
        )
        assert p.case_name == "Backus v. City of Rochester"


class TestCaliforniaNameForms:
    """California family-law/probate styles: no 'v.', and the year
    parenthetical sits between name and cite."""

    def test_marriage_of_with_comma_cite(self):
        p = parse_citation("Marriage of Smith, 195 Cal. App. 4th 1007, 1018 (2011)")
        assert p.case_name == "Marriage of Smith"

    def test_estate_of_with_cal_year_style(self):
        p = parse_citation("Estate of Layton (1938) 29 Cal.App.2d 599")
        assert p.case_name == "Estate of Layton"
        assert p.year == 1938

    def test_in_re_marriage_with_cal_year_style(self):
        p = parse_citation("In re Marriage of L.B. (2018) 30 Cal.App.5th 1076")
        assert p.case_name == "In re Marriage of L.B."

    def test_in_re_with_comma_cite_still_works(self):
        # Regression: the existing In re fallback must keep working.
        p = parse_citation("In re Hudson, 11 U.S. 225 (U.S. 1812)")
        assert p.case_name == "In re Hudson"


class TestSurnameOnlyForms:
    """Bare '<Surname>, <vol> <reporter> <page>' citations (usually a
    truncated 'In re X'). The surname is enough to catch a wrong-cluster
    resolution, so extract it."""

    @pytest.mark.parametrize(
        "citation,expected",
        [
            ("Waitz, 255 Ga. 474 (1986)", "Waitz"),
            ("Barlow, 59 B.R. 707", "Barlow"),
            ("Jager, 344 B.R. 349 (Bankr. D. Colo. 2006)", "Jager"),
        ],
    )
    def test_surname_extracted(self, citation, expected):
        p = parse_citation(citation)
        assert p.case_name == expected


class TestGenuinelyNamelessForms:
    """Forms with no recoverable name must stay None — the verifier's
    name_unverified policy handles them, not a junk extraction."""

    def test_citation_junk_word_not_a_name(self):
        p = parse_citation("Citation 849 F. Supp. 1206 (N.D. Ind. 1994)")
        assert p.case_name is None

    def test_louisiana_paren_led_cite_only(self):
        p = parse_citation("(La. App. 4 Cir. 10/30/13), 127 So.3d 156")
        assert p.case_name is None

    def test_bare_reporter_cite(self):
        p = parse_citation("127 So.3d 156")
        assert p.case_name is None


class TestExistingFormsUnchanged:
    """Regression guards: standard forms keep parsing identically."""

    def test_standard_federal(self):
        p = parse_citation("Obergefell v. Hodges, 576 U.S. 644 (2015)")
        assert p.case_name == "Obergefell v. Hodges"
        assert p.plaintiff == "Obergefell"
        assert p.defendant == "Hodges"

    def test_full_matter_of_form(self):
        p = parse_citation("Matter of Knapp v Knapp, 225 AD2d 1010 (4th Dept 1996)")
        assert p.case_name is not None
        assert "Knapp" in p.case_name

    def test_docket_number_form_keeps_name_and_docket(self):
        p = parse_citation(
            "Chetal v. AmeriCredit Corp., No. C 09-02727 WHA, "
            "2011 WL 2560243 (N.D. Cal. 2011)"
        )
        assert p.case_name == "Chetal v. AmeriCredit Corp."
        assert p.docket_number == "C 09-02727 WHA"
