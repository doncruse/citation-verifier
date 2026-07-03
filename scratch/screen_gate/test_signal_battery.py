"""Tests for signal_battery.py — the Tier-0 deterministic screening battery,
ported onto citation-verifier's eyecite spine.

Two layers:
  * Fixture acceptance: the known-bad brief (support-community-mph--cand-63.md)
    must fire each signal exactly as characterized in the corpus notes, and in
    particular must produce NO false toa_body_diff after the case-name
    extraction is rebased on eyecite + parser + text_cleaner.
  * Synthetic unit tests: small inline paragraphs isolating single behaviors,
    so a regression names the broken signal directly.

Run: pytest test_signal_battery.py   (offline — no network / no CourtListener)
"""

import os

import pytest

import signal_battery as sb

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "support-community-mph--cand-63.md")


@pytest.fixture(scope="module")
def result():
    with open(FIXTURE, encoding="utf-8", errors="replace") as fh:
        return sb.screen(fh.read())


def _by_signal(result, name):
    return [f for f in result["flags"] if f["signal"] == name]


# ------------------------------------------------------------- fixture criteria

def test_c1_court_contradiction(result):
    flags = _by_signal(result, "court_contradiction")
    assert len(flags) == 1
    f = flags[0]
    assert f["prose_court"] == "Ninth Circuit"
    assert f["cite_court"] == "Fed. Cir."
    assert "Intel Corp. v. VIA Techs." in f["context"]


def test_c2_authority_drift(result):
    flags = _by_signal(result, "authority_drift")
    assert len(flags) == 1, [f["case_key"] for f in flags]
    f = flags[0]
    assert f["case_key"] == "new|vanlaw"
    # The two authorities must be the print cite and the WL cite. Exact string
    # formatting is eyecite's normalized form ("34 Cal.4th" -> "34 Cal. 4th").
    assert f["cites"] == ["17 Cal. 5th 703", "2025 WL 1190980"]
    # The single-citation cases whose apparent drift is extraction noise must
    # NOT flag (series-splitting, spacing, short-form).
    keys = {f["case_key"] for f in flags}
    for spurious in ("masterson", "robinson", "han"):
        assert not any(spurious in k for k in keys), keys


def test_c3_statute_grammar(result):
    flags = _by_signal(result, "statute_grammar")
    assert len(flags) == 1
    assert flags[0]["match"].replace(" ", "") == "Cal.UCC".replace(" ", "")


def test_c4_arithmetic(result):
    flags = _by_signal(result, "arithmetic")
    assert len(flags) == 1
    f = flags[0]
    assert f["rate_per_month"] == 1300
    assert f["stated_total"] == 55900
    assert f["expected_total"] == 70200


def test_c5_style_variance(result):
    flags = _by_signal(result, "style_variance")
    kinds = [f["kind"] for f in flags]
    assert kinds.count("v_period_mixed") == 1
    v_flag = next(f for f in flags if f["kind"] == "v_period_mixed")
    assert any("Yeti v Molly" in ex for ex in v_flag["no_period_examples"])
    comma = [f for f in flags if f["kind"] == "comma_court_paren"]
    assert len(comma) == 3
    assert all(f["match"] == "(Cal., 2025)" for f in comma)


def test_c6_toa_body_diff_no_false_positive(result):
    """This document's TOA and body cover the same authorities — the correct
    output is no toa_body_diff flag, or one whose diff lists are empty."""
    flags = _by_signal(result, "toa_body_diff")
    for f in flags:
        assert not f["in_toa_not_body"], f["in_toa_not_body"]
        assert not f["in_body_not_toa"], f["in_body_not_toa"]


def test_c7_recall_preserved(result):
    # eyecite spine extracts materially more than the regex spine's 65; the
    # source's floor was 55 and remains a conservative regression guard.
    assert result["n_cites_extracted"] >= 55


# --------------------------------------------------------- synthetic unit tests

def test_clean_paragraph_zero_flags():
    """Consistent correct citations, matching prose/parenthetical courts, and
    arithmetic that reconciles: nothing should fire."""
    text = (
        "Summary judgment is proper. Celotex Corp. v. Catrett, 477 U.S. 317, "
        "323 (1986). The Ninth Circuit agreed in Doe v. Roe, 200 Cal. App. 4th "
        "5, 9 (9th Cir. 2011). Defendant saved $1,000 per month, totaling "
        "$12,000, from January 2020 to December 2020."
    )
    assert sb.screen(text)["flags"] == []


def test_prose_cite_court_mismatch_flags():
    """Prose says Second Circuit; the parenthetical says (9th Cir. 2010)."""
    text = (
        "As the Second Circuit explained, the rule is settled. See Doe v. "
        "Roe, 123 F. Supp. 2d 456, 460 (9th Cir. 2010)."
    )
    flags = [f for f in sb.screen(text)["flags"]
             if f["signal"] == "court_contradiction"]
    assert len(flags) == 1
    assert flags[0]["prose_court"] == "Second Circuit"
    assert flags[0]["cite_court"] == "9th Cir."


def test_one_case_two_citations_flags_drift():
    """A single case name cited two materially different ways must drift."""
    text = (
        "The court agreed. Smith v. Jones, 100 U.S. 200 (2001). Later "
        "authority confirmed this. Smith v. Jones, 55 Cal. App. 4th 10 (1997)."
    )
    flags = [f for f in sb.screen(text)["flags"]
             if f["signal"] == "authority_drift"]
    assert len(flags) == 1
    assert flags[0]["case_key"] == "smith|jones"
    assert len(flags[0]["cites"]) == 2


def test_party1_over_capture_does_not_split_case():
    """Sentence-context prefix on party 1 must not defeat TOA<->body matching:
    a TOA entry and a body occurrence with a 'As the court recognized in'
    prefix are the same case, so no toa_body_diff arises from that pair."""
    text = (
        "TABLE OF AUTHORITIES Cases Lewis v. YouTube, LLC, 197 Cal. App. 4th "
        "1387 (2011) INTRODUCTION As the court recognized in Lewis v. YouTube, "
        "LLC, 197 Cal. App. 4th 1387, 1394 (2011), the rule applies."
    )
    flags = [f for f in sb.screen(text)["flags"]
             if f["signal"] == "toa_body_diff"]
    for f in flags:
        assert not f["in_toa_not_body"], f["in_toa_not_body"]
        assert not f["in_body_not_toa"], f["in_body_not_toa"]
