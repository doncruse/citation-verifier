"""Tests for executor._parse_json_object.

The three malformed fixtures are REAL claude-sonnet-5 assess-v1 outputs
captured 2026-07-01 (scratch/parse_failure_raw.txt) that the parser
dropped as "unparseable" -- the model intermittently emits almost-valid
JSON. Two observed failure modes, both defeating all pre-repair
candidates (they share the same malformed text):

  1. unescaped inner double-quotes in a string value
  2. a missing closing brace (object never terminated)
"""
from citation_verifier.executor import _parse_json_object

# --- real captured failures -------------------------------------------------

# Mode 1: unescaped inner quotes around "real impairment"
UNESCAPED_INNER_QUOTES = (
    '{"assessment": "Yellow", "rationale": "The case does support that '
    'deemed admissions under Rule 36 are conclusive and can support summary '
    'judgment, but the specific quoted language is fabricated and the case '
    'does not address the prejudice standard or "real impairment" concept '
    'claimed in points 4-5."}'
)

# Mode 2: no closing brace (rationale string is closed, object is not)
MISSING_CLOSING_BRACE_YELLOW = (
    '{"assessment": "Yellow", "rationale": "Footnote 10 does say purely '
    "clerical/secretarial tasks shouldn't be billed at paralegal rates while "
    'distinguishing legal work like investigation and drafting '
    'correspondence, but it never affirmatively addresses or discusses '
    "emailing/calling clients as 'essential professional activities' exempt "
    'from that caution, so the proposition extrapolates beyond what the '
    'footnote actually holds."'
)

MISSING_CLOSING_BRACE_RED = (
    '{"assessment": "Red", "rationale": "Nix v. Whiteside addresses an '
    "attorney's duty to refuse cooperation with client perjury under the "
    'Sixth Amendment, not conflicts of interest rules or their purpose of '
    'protecting client interests and judicial integrity, and page 166 '
    'discusses ethical canons on candor to the court rather than '
    'conflicts-of-interest doctrine."'
)


def test_recovers_unescaped_inner_quotes():
    result = _parse_json_object(UNESCAPED_INNER_QUOTES)
    assert result is not None
    assert result["assessment"] == "Yellow"
    assert isinstance(result.get("rationale"), str) and result["rationale"]


def test_recovers_missing_closing_brace_yellow():
    result = _parse_json_object(MISSING_CLOSING_BRACE_YELLOW)
    assert result is not None
    assert result["assessment"] == "Yellow"
    assert isinstance(result.get("rationale"), str) and result["rationale"]


def test_recovers_missing_closing_brace_red():
    result = _parse_json_object(MISSING_CLOSING_BRACE_RED)
    assert result is not None
    assert result["assessment"] == "Red"


# --- regression: existing behavior must be preserved ------------------------

def test_parses_clean_json():
    assert _parse_json_object('{"assessment": "Green"}') == {
        "assessment": "Green"}


def test_parses_fenced_block():
    text = 'Here you go:\n```json\n{"assessment": "Red"}\n```'
    assert _parse_json_object(text) == {"assessment": "Red"}


def test_parses_trailing_prose_without_braces():
    text = '{"assessment": "Yellow"}\n\nThat is my assessment.'
    assert _parse_json_object(text) == {"assessment": "Yellow"}


def test_returns_none_on_non_json():
    assert _parse_json_object("I could not complete this task.") is None
