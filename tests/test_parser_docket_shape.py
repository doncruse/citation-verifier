"""Lever (b) of the 2026-06-11 Check Cite design (docs/plans/2026-06-11-check-cite-design.md §6).

"No. <x>" is only a docket number when <x> is docket-shaped: contains a digit
AND (>= 4 chars or contains -/:). Entity names like "HJSA No. 3, L.P."
(Sundown Energy LP v. HJSA No. 3, L.P., 622 S.W.3d 884 (Tex. 2021)) must keep
"No. 3" in the case name and must NOT extract docket_number="3" — the phantom
docket number fed the Lever-3 contradiction cap and the mangled name poisoned
the search query (the verified-sundown-energy-fallback false negative).
"""
import pytest

from citation_verifier.parser import parse_citation

_SUNDOWN = "Sundown Energy LP v. HJSA No. 3, L.P., 622 S.W.3d 884 (Tex. 2021)"


class TestNonDocketShapedNoSurvives:
    def test_sundown_docket_number_not_extracted(self):
        assert parse_citation(_SUNDOWN).docket_number is None

    def test_sundown_case_name_keeps_no_3(self):
        parsed = parse_citation(_SUNDOWN)
        assert parsed.case_name is not None
        assert "no. 3" in parsed.case_name.lower()

    def test_short_digit_after_no_is_not_a_docket(self):
        parsed = parse_citation(
            "Local No. 7 v. Acme Corp., 100 F.3d 200 (2d Cir. 1996)"
        )
        assert parsed.docket_number is None


class TestDocketShapedExtractionUnchanged:
    @pytest.mark.parametrize("text,expected", [
        ("Lopez v. Bank of Am., No. 14-cv-2524, 2016 WL 4131149 (N.D. Cal. 2016)",
         "14-cv-2524"),
        ("Moore v. Hillman, No. 4:06-CV-43, 2006 WL 1313880 (W.D. Mich. May 12, 2006)",
         "4:06-CV-43"),
        ("Button v. Doherty, Case No. 24 Civ. 5026 (JPC) (KHP), 2025 WL 2776069 (S.D.N.Y. Sept. 30, 2025)",
         "24 Civ. 5026"),
        ("Aikens v. Nw. Dodge, No. 03 C 7956, 2004 WL 432498 (N.D. Ill. 2004)",
         "03 C 7956"),
        ("In re Stuff, No. C 09-02727, 2010 WL 123 (N.D. Cal. 2010)",
         "C 09-02727"),
        # Bare 5-digit form is still docket-shaped (>= 4 chars)
        ("Smith v. Jones, No. 12345, 2020 WL 1 (D. Mass. 2020)", "12345"),
    ])
    def test_docket_extracted(self, text, expected):
        assert parse_citation(text).docket_number == expected

    def test_docket_junk_still_stripped_from_name(self):
        parsed = parse_citation(
            "Button v. Doherty, Case No. 24 Civ. 5026 (JPC) (KHP), "
            "2025 WL 2776069 (S.D.N.Y. Sept. 30, 2025)"
        )
        assert parsed.case_name is not None
        assert "5026" not in parsed.case_name
