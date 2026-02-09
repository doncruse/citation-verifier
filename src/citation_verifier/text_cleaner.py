"""Text cleaning utilities for extracted case names and citations.

Removes contamination phrases (legal analysis terms, procedural language, signal words)
that can leak into extracted case names from surrounding text.

Adapted from: https://github.com/jafrank88/CaseStrainer
"""

from __future__ import annotations

import re


# Legal signal words that contaminate case name extractions
SIGNAL_WORDS = [
    "see",
    "see also",
    "e.g.",
    "cf.",
    "id.",
    "ibid.",
    "accord",
    "quoting",
    "citing",
    "compare",
    "but see",
    "see generally",
    "contra",
]

# Procedural and analytical phrases
PROCEDURAL_PHRASES = [
    "de novo",
    "questions of law",
    "question of law",
    "federal court",
    "this court reviews",
    "this court",
    "the court",
    "holding that",
    "holds that",
    "concluding that",
    "concludes that",
    "finding that",
    "finds that",
    "ruling that",
    "rules that",
    "deciding that",
    "decides that",
    "stating that",
    "states that",
    "noting that",
    "notes that",
]

# Court references
COURT_REFERENCES = [
    "supreme court",
    "appellate court",
    "court of appeals",
    "district court",
    "circuit court",
    "trial court",
    "court",
    "panel",
    "circuit",
    "district",
]

# All contamination patterns combined
CONTAMINATION_PATTERNS = SIGNAL_WORDS + PROCEDURAL_PHRASES + COURT_REFERENCES


def clean_case_name(case_name: str) -> str:
    """Remove contamination phrases from a case name.

    Args:
        case_name: Raw extracted case name that may contain contamination

    Returns:
        Cleaned case name with contamination removed
    """
    if not case_name:
        return case_name

    cleaned = case_name.strip()

    # Remove each contamination pattern (case-insensitive)
    for pattern in CONTAMINATION_PATTERNS:
        # Match at word boundaries
        regex = r"\b" + re.escape(pattern) + r"\b"
        cleaned = re.sub(regex, "", cleaned, flags=re.IGNORECASE)

    # Remove citation patterns that leak in
    # Pattern: ", 31 Wn.2d 343" or ", 123 F.3d 456"
    cleaned = re.sub(r",\s*\d+\s+[A-Za-z.]+\s+\d+", "", cleaned)

    # Remove partial citations like "[21 U.S."
    cleaned = re.sub(r"\[\d+\s+[A-Z]", "", cleaned)

    # Clean up resulting whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Remove leading/trailing punctuation except closing parens
    cleaned = re.sub(r"^[,;:\s]+", "", cleaned)
    cleaned = re.sub(r"[,;:\s]+$", "", cleaned)

    return cleaned


def remove_trailing_contamination(text: str, case_name: str) -> str:
    """Remove contamination that appears after the case name in extracted text.

    This is for context-based extraction where we grab text around a citation
    and the case name may be followed by procedural language.

    Args:
        text: Full extracted text
        case_name: The case name to clean up

    Returns:
        Cleaned case name
    """
    if not case_name or not text:
        return case_name

    # Find the case name position in text
    idx = text.find(case_name)
    if idx == -1:
        return clean_case_name(case_name)

    # Check what comes after the case name
    after_text = text[idx + len(case_name):idx + len(case_name) + 100].lower()

    # If procedural language follows, truncate before it
    for phrase in PROCEDURAL_PHRASES + SIGNAL_WORDS:
        phrase_idx = after_text.find(phrase.lower())
        if phrase_idx != -1 and phrase_idx < 50:  # Close to case name
            # Truncate case name before the contamination
            case_name = text[idx:idx + len(case_name) + phrase_idx].strip()
            break

    return clean_case_name(case_name)
