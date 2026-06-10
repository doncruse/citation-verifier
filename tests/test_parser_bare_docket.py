"""Tests for bare federal docket-number extraction (no 'No.' prefix).

Motivating case: "Johnson v. Mitchell, 2:20-cv-1882, 2020 WL 5649609
(S.D. Ohio Sept. 23, 2020)" — a fabricated citation whose docket number is
written bare. Extracting it lets the Lever 3 docket-contradiction cap reject
the match against the real (different-docket) Johnson v. Mitchell.
"""
import pytest

from citation_verifier.parser import parse_citation


@pytest.mark.parametrize("text,expected", [
    # Bare docket, no "No." prefix
    ("Johnson v. Mitchell, 2:20-cv-1882, 2020 WL 5649609 (S.D. Ohio Sept. 23, 2020)",
     "2:20-cv-1882"),
    ("Doe v. Roe, 1:13-cr-00045, 2014 WL 123 (S.D.N.Y. 2014)", "1:13-cr-00045"),
    # Plain reporter citation must NOT be mistaken for a docket number
    ("Thompson v. Best, 989 N.E.2d 299 (Ind. Ct. App. 2013)", None),
    ("Obergefell v. Hodges, 576 U.S. 644 (2015)", None),
])
def test_bare_federal_docket_extraction(text, expected):
    assert parse_citation(text).docket_number == expected


def test_no_prefix_docket_still_wins():
    """The explicit 'No.'-prefixed form is unaffected."""
    assert parse_citation(
        "Lopez v. Bank of Am., No. 14-cv-2524, 2016 WL 4131149 (N.D. Cal. 2016)"
    ).docket_number == "14-cv-2524"
