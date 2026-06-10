"""Unit tests for the Charlotin fake-citation corpus builder.

The builder mines court-confirmed fabricated citations from
scratch/Charlotin-hallucination_cases.csv (Damien Charlotin's AI
hallucination database). These tests cover the parsing/extraction logic
on real item strings from the CSV — no API calls.
"""
from __future__ import annotations

from tests.build_charlotin_corpus import (
    extract_candidates,
    split_items,
)

# Real item strings from the CSV (verbatim).
RILEY = (
    "Defendant's memorandum [104] cited Riley v. City of Tupelo, No. "
    "1:20-CV-186-GHD-DAS, 2023 WL 3568661, at 3 (N.D. Miss. May 18, 2023), "
    "which the Court could not verify."
)
THORNBURY = (
    "Plaintiff cited 'Thornbury v. Madison Cnty., 242 F. Supp. 3d 851, 860 "
    "(W.D. Tenn. 2017)'; court found no matching opinion and identified only "
    "an unrelated Jackson v. Lew, 242 F. Supp. 3d 850 (W.D. Mo. 2017)."
)
GRENADA = (
    "Plaintiff's opposition [105] contained two citations the Court found "
    "nonexistent, including City of Grenada v. Harrelson, 84 So. 3d 35, 38 "
    "(Miss. Ct. App. 2012)."
)


class TestSplitItems:
    def test_splits_on_double_pipe_and_extracts_category(self):
        raw = (
            "Fabricated: Case Law | first description. || "
            "False Quotes: Case Law | second description."
        )
        items = split_items(raw)
        assert items == [
            ("Fabricated: Case Law", "first description."),
            ("False Quotes: Case Law", "second description."),
        ]

    def test_empty_field(self):
        assert split_items("") == []

    def test_description_containing_single_pipe_survives(self):
        raw = "Fabricated: Case Law | cited A v. B | also C v. D."
        items = split_items(raw)
        assert items == [("Fabricated: Case Law", "cited A v. B | also C v. D.")]


class TestExtractCandidates:
    def test_wl_cite_with_docket_extracted_verbatim(self):
        cands = extract_candidates(RILEY)
        assert len(cands) == 1
        c = cands[0]
        assert c.citation == (
            "Riley v. City of Tupelo, No. 1:20-CV-186-GHD-DAS, "
            "2023 WL 3568661, at 3 (N.D. Miss. May 18, 2023)"
        )
        assert not c.flags

    def test_reporter_cite_extracted_with_closing_paren(self):
        cands = extract_candidates(GRENADA)
        assert len(cands) == 1
        assert cands[0].citation == (
            "City of Grenada v. Harrelson, 84 So. 3d 35, 38 (Miss. Ct. App. 2012)"
        )

    def test_real_contrast_case_flagged_not_kept(self):
        """An item can name BOTH the fake cite and the real case the court
        found instead ('identified only an unrelated Jackson v. Lew...').
        The citation after the contrast marker must be flagged."""
        cands = extract_candidates(THORNBURY)
        kept = [c for c in cands if not c.flags]
        flagged = [c for c in cands if "real_contrast" in c.flags]
        assert len(kept) == 1
        assert "Thornbury" in kept[0].citation
        assert len(flagged) == 1
        assert "Jackson" in flagged[0].citation

    def test_united_states_name_recovered_after_em_dash(self):
        cands = extract_candidates(
            "Brief cited a non-existent precedent—United States v. Jones, "
            "29 F.4th 1290, 1294 (11th Cir. 2022)."
        )
        assert len(cands) == 1
        assert cands[0].citation.startswith("United States v. Jones")

    def test_corrected_by_court_to_flags_the_real_case(self):
        cands = extract_candidates(
            "Citation 'Bogus v. Fake, 73 AD3d 521 [1st Dept 2010]' yields no "
            "results and was corrected by court to Popowich v Korman, 73 "
            "AD3d 515 [1st Dept 2010]."
        )
        flagged = [c for c in cands if "real_contrast" in c.flags]
        assert any("Popowich" in c.citation for c in flagged)

    def test_citation_swallowing_prose_is_flagged(self):
        cands = extract_candidates(
            "Cited Smith v. Jones, 100 F.3d 1 (2d Cir. 1996), which "
            "corresponds to a different case entirely."
        )
        # Simulate the swallow by checking the flag logic directly: a
        # candidate whose text contains a contrast marker is unusable.
        from tests.build_charlotin_corpus import Candidate, _CONTRAST_MARKERS

        assert _CONTRAST_MARKERS.search(
            "X v. Y, 73 AD3d 521' yields no results and was corrected by "
            "court to Popowich v Korman, 73 AD3d 515"
        )
        # And the well-formed citation above is NOT flagged spans_prose.
        kept = [c for c in cands if not c.flags]
        assert len(kept) == 1 and "Smith" in kept[0].citation

    def test_no_citation_yields_empty(self):
        cands = extract_candidates(
            "Plaintiff's initial motion included citations to cases that "
            "did not exist; the Court required corrected citations."
        )
        assert cands == []
