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


import pytest  # noqa: E402


class TestNewContrastMarkers:
    """2026-06-11 triage: 15 bucket-A FPs were poisoned extractions — the
    court's named REAL case entered the fake corpus. These finder-verb
    markers (documented in the charlotin retro) introduce the real case."""

    @pytest.mark.parametrize(
        "finder_phrase",
        [
            "the closest match is",
            "the closest possible match is",
            "counsel intended to cite",
            "the intended citation was",
            "the citation maps to",
            "the citation points to",
            "the Court traced to a page within",
            "the cited page falls within",
            "the court's search retrieved",
            "the citation may relate to",
            "the nearby real citation was",
            "the only real",
            # B/C sweep additions (same finder-verb family):
            "found two cases that appear to match the named parties:",
            "Plaintiff likely intended",
        ],
    )
    def test_finder_phrase_flags_following_citation(self, finder_phrase):
        text = (
            "Plaintiff cited 'Bogus v. Fake, 100 F.3d 1 (2d Cir. 1996)', "
            f"which the court could not locate; {finder_phrase} "
            "Genuine v. Case, 200 F.3d 2 (2d Cir. 1999)."
        )
        cands = extract_candidates(text)
        kept = [c for c in cands if not c.flags]
        flagged = [c for c in cands if "real_contrast" in c.flags]
        assert len(kept) == 1 and "Bogus" in kept[0].citation
        assert len(flagged) == 1 and "Genuine" in flagged[0].citation

    def test_bare_court_found_is_not_a_marker(self):
        """'court found' is ambiguous ('court found the citation to FAKE'
        vs 'court found REAL instead') — must NOT flag. Documented in the
        charlotin retro; Lampe-style items are handled by the adjudicated
        drop list instead."""
        cands = extract_candidates(
            "Court found the citation to 'Bogus v. Fake, 100 F.3d 1 "
            "(2d Cir. 1996)' does not exist as cited."
        )
        kept = [c for c in cands if not c.flags]
        assert len(kept) == 1 and "Bogus" in kept[0].citation


class TestAdjudicatedEntries:
    """Per-entry adjudication of the 2026-06-11 live run
    (scratch/charlotin_bucketA_adjudication.csv): corpus mislabels and
    marker-proof poisoned extractions are dropped or relabeled by
    normalized cite key."""

    def _decide(self, citation):
        from tests.build_charlotin_corpus import adjudication_for

        return adjudication_for(citation)

    @pytest.mark.parametrize(
        "citation",
        [
            # Poisoned, no safe marker catches the item text:
            "Lampe v. Genuine Parts Co., 463 F. Supp. 2d 928, 934 (E.D. Wis. 2006)",
            "Curtis v. Oliver, 479 F. Supp. 3d 1039, 1088 (D.N.M. 2020)",
            # Charlotin mislabels — real, correctly-cited cases:
            "Tubra v. Cooke, 233 Or App 339, 225 P3d 862 (2010)",
            "Kidd v. Mando Am. Corp., 731 F.3d 1196, 1200 (11th Cir. 2013)",
            "State v. Clark, 2012 ND 135",
            "Perez v. Zazo, 498 So. 2d 463, 465 (Fla. 3d DCA 1986)",
            "Chambers v. Time Warner, Inc., 282 F.3d 147, 152-53 (2d Cir. 2002)",
            # B/C sweep (2026-06-10 session): real cases named by the court
            # with finder verbs too generic to be markers:
            "Jones v.\nJones, No. M201801746COAR3CV, 2019 WL 1036077",
            "Nandigam Neurology, PLC v. Beavers, 639 S.W.3d 651 (Tenn. Ct. App. 2021)",
            "Vargas v. Sotelo, 2017 NY Slip Op 50417(U)(Civ. Ct., Bronx Cty. 2017)",
            "Lozada v. E.L.A., 174 DPR 650 (2008)",
            # Post-fix replay (2026-06-10 session): CL resolves the cite to
            # cluster "Manfer v. Manfer" — same case, so the entry is a
            # mislabel (court's complaint was inconsistent citations):
            "In re Marriage of Manfer (2006) 144 Cal.App.4th 925",
        ],
    )
    def test_dropped_entries(self, citation):
        action, reason = self._decide(citation)
        assert action == "drop"
        assert reason

    def test_holden_relabeled_wrong_pincite(self):
        action, _ = self._decide(
            "Holden v. Holiday Inn Club Vacations, Inc., 98 F.4th 1359"
        )
        assert action == "relabel:charlotin_real_case_wrong_pincite"

    def test_bolin_relabeled_wrong_court(self):
        action, _ = self._decide(
            "Bolin v. Story, 225 F.3d 1234, 1239 (6th Cir. 2000)"
        )
        assert action == "relabel:charlotin_real_case_wrong_court"

    def test_unadjudicated_citation_returns_none(self):
        assert self._decide(
            "City of Grenada v. Harrelson, 84 So. 3d 35, 38 (Miss. Ct. App. 2012)"
        ) is None
