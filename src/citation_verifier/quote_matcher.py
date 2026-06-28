"""Quote-fidelity matching primitives.

Public surface: `verify_quote`, `QuoteVerification`, `QuoteMatch` (added in
later tasks). The module also houses the legal-quote normalization and the
fuzzy best-match helpers, previously private to proposition_pipeline.
"""
from __future__ import annotations

import difflib
import re

# --- Quote text normalization (moved verbatim from proposition_pipeline) ---


def _normalize_quote_text(text: str) -> str:
    """Normalize quoted text for fuzzy matching.

    Strips bracketed alterations, ellipses, smart quotes, and excess whitespace.
    """
    # Smart quotes to straight
    s = text.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    # Strip bracketed alterations: [T] -> t (lowercase), [word] -> ""
    s = re.sub(r"\[([A-Z])\]", lambda m: m.group(1).lower(), s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    # Strip ellipses
    s = s.replace("…", " ")  # unicode ellipsis
    s = re.sub(r"\.{3,}", " ", s)  # three+ dots
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --- OCR-confusion normalization (borrowed from lq-ai, conservative) ---
# One-directional substitutions applied to BOTH the quote and the opinion text
# when the opinion was OCR'd, so faithful quotes against OCR'd serif PDFs stop
# false-negativing. Case-sensitive O/l rules => must run BEFORE any .lower().
_OCR_RN_RE = re.compile(r"(?<=\w)rn")
_OCR_O_RE = re.compile(r"(?<=\d)O|O(?=\d)")
_OCR_L_RE = re.compile(r"(?<=\d)l|l(?=\d)")


def _normalize_ocr_confusions(text: str) -> str:
    """Collapse the three canonical OCR misreads. Idempotent; clean-text no-op."""
    out = _OCR_RN_RE.sub("m", text)
    out = _OCR_O_RE.sub("0", out)
    out = _OCR_L_RE.sub("1", out)
    return out


def _best_match_with_passage(
    needle: str, haystack: str, context_chars: int = 80,
) -> tuple[float, str]:
    """Find the best fuzzy match ratio and extract the matching passage.

    Returns (ratio, passage) where passage is the best-matching text from
    the haystack with surrounding context.  The haystack should already be
    HTML-stripped clean text (check_quotes does this).  We normalize the
    needle for matching but extract the passage from the original haystack
    using haystack_lower (same length as haystack, so positions map 1:1).
    """
    if not needle or not haystack:
        return 0.0, ""
    needle_norm = _normalize_quote_text(needle).lower()
    # Only lowercase the haystack (don't normalize — preserves positions)
    haystack_lower = haystack.lower()

    if not needle_norm:
        return 0.0, ""

    # Exact substring = verbatim
    if needle_norm in haystack_lower:
        pos = haystack_lower.index(needle_norm)
        return 1.0, _extract_passage(haystack, pos, len(needle_norm), context_chars)

    # Sliding window with fine step
    best = 0.0
    best_start = 0
    window = len(needle_norm)
    step = max(1, window // 8)
    for start in range(0, max(1, len(haystack_lower) - window + 1), step):
        chunk = haystack_lower[start:start + window + window // 2]
        ratio = difflib.SequenceMatcher(
            None, needle_norm, chunk, autojunk=False,
        ).ratio()
        if ratio > best:
            best = ratio
            best_start = start
            if best > 0.95:
                break

    passage = ""
    if best >= 0.4:
        passage = _extract_passage(
            haystack, best_start, window + window // 2, context_chars,
        )
    return best, passage


def _extract_passage(
    text: str, match_start: int, match_len: int, context: int,
) -> str:
    """Extract a passage from text around a match, trimmed to sentences."""
    start = max(0, match_start - context)
    end = min(len(text), match_start + match_len + context)
    passage = text[start:end].strip()
    # Trim leading partial sentence
    if start > 0:
        dot = passage.find(". ")
        if 0 < dot < context:
            passage = passage[dot + 2:]
    # Trim trailing partial sentence
    if end < len(text):
        dot = passage.rfind(". ")
        if dot > len(passage) - context and dot > 0:
            passage = passage[:dot + 1]
    return passage.strip()
