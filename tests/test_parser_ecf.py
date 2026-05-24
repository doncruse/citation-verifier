"""Tests for ECF / Doc / Dkt document number parsing (design §2.10)."""
import pytest

from citation_verifier.parser import parse_citation


@pytest.mark.parametrize("text,expected", [
    ("Smith v. Jones, ECF No. 42 (D. Mass. 2024)", "42"),
    ("Smith v. Jones, Doc. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, Dkt. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, Dkt. No. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, ECF No. 142-1 (D. Mass. 2024)", "142-1"),  # attachment suffix
    ("Smith v. Jones, 100 F.3d 200 (D. Mass. 2024)", None),       # no ECF -> None
])
def test_parses_ecf_document_number(text, expected):
    parsed = parse_citation(text)
    assert parsed.ecf_document_number == expected


def test_docket_and_ecf_coexist():
    """When both a docket number and an ECF doc number appear, populate both."""
    parsed = parse_citation(
        "Smith v. Jones, Case No. 24-cv-9429, ECF No. 42 (D. Mass. 2024)"
    )
    assert parsed.docket_number == "24-cv-9429"
    assert parsed.ecf_document_number == "42"
