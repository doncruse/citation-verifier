# OCR-Confusion Quote Normalization + Public `verify_quote` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a public `verify_quote(quote, opinion_text, *, was_ocrd=False) -> QuoteVerification` primitive with built-in OCR-confusion normalization, and refactor CV's existing quote checker to use it (gated on CourtListener's per-opinion `extracted_by_ocr` flag).

**Architecture:** A new `quote_matcher.py` module holds the moved quote internals plus the new public primitive. The three OCR rules (`rn`→`m`, `O`→`0`, `l`→`1`) are conservative, one-directional, applied to both sides of the comparison, and gated by a `was_ocrd` argument. CV's pipeline sources that flag per opinion from a new `opinions/ocr_status.json` manifest fed by `client.py`, written during the (sequential) opinion-download loops, and read by `check_quotes`.

**Tech Stack:** Python 3.10+, `difflib.SequenceMatcher` (existing matcher — NOT rapidfuzz), `dataclasses`, `enum`, `pytest`. Editable install (`pip install -e .`).

## Global Constraints

- **Windows env:** the Python executable is `venv/Scripts/python.exe` (never `python`/`python3`). No `head`/`tail`/`grep` in Git Bash — use dedicated tools. ASCII-only CLI output.
- **Do NOT change thresholds:** VERBATIM is `ratio > 0.85`, CLOSE is `ratio >= 0.6`, else FABRICATED. The quote-floor calibration (`_CLOSE_FLOOR_MAX_SIM = 0.75`) is unchanged.
- **`was_ocrd=False` path must be byte-for-byte behavior-identical to today.** No normalized copies built, no extra work, when the flag is off.
- **OCR normalization runs BEFORE `.lower()`** — the `O`→`0` and `l`→`1` rules are case-sensitive.
- **`rn`→`m` is length-changing:** keep the original haystack for passage extraction; use an OCR-normalized copy only for the ratio/substring comparison.
- **Locked cross-repo contract** (us-legal-research grader has a pinned contract test): `result` is an exported `QuoteMatch(str, Enum)`; fields are `quote` / `result` / `similarity` / `matched_passage` / `was_ocrd`; `quote` echoes the RAW input; NO `verbatim: bool`.
- **Backward-compat:** nothing existing renamed/removed. `run_check_quotes` / `QuoteCheckStats` and the `quote_check` / `quote_check_worst` / `quote_floor` CSV columns keep their shapes. The moved names (`_normalize_quote_text`, `_best_match_with_passage`, `_extract_passage`, `check_quotes`, `QuoteCheckStats`, `extract_quoted_spans`) MUST remain importable from `citation_verifier.proposition_pipeline` (and therefore the `brief_pipeline` alias) — `tests/test_brief_pipeline.py:15` imports them from `brief_pipeline`.
- **Version:** bump `pyproject.toml` `0.4.0` → `0.5.0`; add a `CHANGELOG.md` `v0.5.0` entry; one-line `CLAUDE.md` note.
- **Spec:** `docs/superpowers/specs/2026-06-28-ocr-quote-normalization-design.md` is the source of truth.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/citation_verifier/quote_matcher.py` | **New.** Moved internals (`_normalize_quote_text`, `_best_match_with_passage`, `_extract_passage`) + new `_normalize_ocr_confusions`, thresholds, `QuoteMatch`, `QuoteVerification`, `verify_quote`. |
| `src/citation_verifier/proposition_pipeline.py` | Re-imports moved names from `quote_matcher`; OCR-manifest helpers; `_download_opinion` records OCR flag; waves write `opinions/ocr_status.json`; `check_quotes` reads manifest + calls `verify_quote`. |
| `src/citation_verifier/client.py` | Captures `extracted_by_ocr` from the sub-opinion JSON into the metadata dict (sync + async resolvers). |
| `src/citation_verifier/__init__.py` | Exports `verify_quote`, `QuoteVerification`, `QuoteMatch`. |
| `tests/test_quote_matcher.py` | **New.** Per-rule, idempotence, clean-text non-regression, OCR true-positive, contract, passage-coherence tests. |
| `tests/test_proposition_pipeline.py` | Manifest-gate test; client `extracted_by_ocr` capture test. |
| `pyproject.toml`, `CHANGELOG.md`, `CLAUDE.md` | Version + docs. |

---

## Task 1: Extract quote internals into `quote_matcher.py` (pure refactor)

Behavior-preserving move so later tasks build the primitive in its own module. No logic changes.

**Files:**
- Create: `src/citation_verifier/quote_matcher.py`
- Modify: `src/citation_verifier/proposition_pipeline.py` (remove the three function defs + the `_CLOSE_FLOOR_MAX_SIM` neighbor stays put; add a re-import)
- Test: existing `tests/test_brief_pipeline.py`, `tests/test_proposition_pipeline.py` (no new test; this is a characterization-by-existing-suite refactor)

**Interfaces:**
- Produces (importable from `quote_matcher` AND, via re-import, from `proposition_pipeline`):
  - `_normalize_quote_text(text: str) -> str`
  - `_best_match_with_passage(needle: str, haystack: str, context_chars: int = 80) -> tuple[float, str]`
  - `_extract_passage(text: str, match_start: int, match_len: int, context: int) -> str`

- [ ] **Step 1: Create `quote_matcher.py` with the moved functions**

Create `src/citation_verifier/quote_matcher.py`:

```python
"""Quote-fidelity matching primitives.

Public surface: `verify_quote`, `QuoteVerification`, `QuoteMatch` (added in
later tasks). The module also houses the legal-quote normalization and the
fuzzy best-match helpers, previously private to proposition_pipeline.
"""
from __future__ import annotations

import difflib
import re

# --- Quote text normalization (moved verbatim from proposition_pipeline) ---

_QUOTE_SPAN = re.compile(r'"([^"]+)"')


def _normalize_quote_text(text: str) -> str:
    """Normalize quoted text for fuzzy matching.

    Strips bracketed alterations, ellipses, smart quotes, and excess whitespace.
    """
    s = text.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = re.sub(r"\[([A-Z])\]", lambda m: m.group(1).lower(), s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.replace("…", " ")
    s = re.sub(r"\.{3,}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _best_match_with_passage(
    needle: str, haystack: str, context_chars: int = 80,
) -> tuple[float, str]:
    """Find the best fuzzy match ratio and extract the matching passage."""
    if not needle or not haystack:
        return 0.0, ""
    needle_norm = _normalize_quote_text(needle).lower()
    haystack_lower = haystack.lower()

    if not needle_norm:
        return 0.0, ""

    if needle_norm in haystack_lower:
        pos = haystack_lower.index(needle_norm)
        return 1.0, _extract_passage(haystack, pos, len(needle_norm), context_chars)

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
    if start > 0:
        dot = passage.find(". ")
        if 0 < dot < context:
            passage = passage[dot + 2:]
    if end < len(text):
        dot = passage.rfind(". ")
        if dot > len(passage) - context and dot > 0:
            passage = passage[:dot + 1]
    return passage.strip()
```

(Note: `_QUOTE_SPAN` here is a local copy ONLY if `extract_quoted_spans` is also moved — it is NOT. Leave `extract_quoted_spans` and its `_QUOTE_SPAN` in `proposition_pipeline.py`. Delete the unused `_QUOTE_SPAN` line above if it is not referenced by anything in `quote_matcher.py` — it is not, so remove it before committing.)

- [ ] **Step 2: Remove the moved defs from `proposition_pipeline.py` and re-import**

In `src/citation_verifier/proposition_pipeline.py`:
- Delete the bodies of `_normalize_quote_text` (≈ lines 103-119), `_best_match_with_passage` (≈ lines 1746-1792), and `_extract_passage` (≈ lines 1795-1812).
- Add to the import block near the top (after the existing intra-package imports):

```python
from .quote_matcher import (
    _best_match_with_passage,
    _extract_passage,
    _normalize_quote_text,
)
```

Keep `extract_quoted_spans`, `_QUOTE_SPAN`, `_CLOSE_FLOOR_MAX_SIM`, `_quote_floor`, and `check_quotes` where they are.

- [ ] **Step 3: Run the existing quote/brief suites to verify no behavior change**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py tests/test_proposition_pipeline.py -q`
Expected: PASS (same counts as before the refactor). In particular `tests/test_brief_pipeline.py`'s `_normalize_quote_text` tests (≈ lines 473-495) still pass via the `brief_pipeline` alias.

- [ ] **Step 4: Commit**

```bash
git add src/citation_verifier/quote_matcher.py src/citation_verifier/proposition_pipeline.py
git commit -m "refactor: move quote internals into quote_matcher.py"
```

---

## Task 2: Add `_normalize_ocr_confusions`

**Files:**
- Modify: `src/citation_verifier/quote_matcher.py`
- Test: `tests/test_quote_matcher.py` (create)

**Interfaces:**
- Produces: `_normalize_ocr_confusions(text: str) -> str` — applies `rn`→`m` (mid-word), `O`→`0` (digit-adjacent), `l`→`1` (digit-adjacent). One-directional, idempotent, case-preserving.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_quote_matcher.py`:

```python
from citation_verifier.quote_matcher import _normalize_ocr_confusions


class TestNormalizeOcrConfusions:
    def test_rn_to_m_midword(self):
        assert _normalize_ocr_confusions("modern") == "modem"
        assert _normalize_ocr_confusions("concern") == "concem"

    def test_rn_not_word_initial(self):
        assert _normalize_ocr_confusions("rnage") == "rnage"

    def test_O_to_0_only_digit_adjacent(self):
        assert _normalize_ocr_confusions("O5") == "05"
        assert _normalize_ocr_confusions("5O") == "50"
        assert _normalize_ocr_confusions("Office") == "Office"

    def test_l_to_1_only_digit_adjacent(self):
        assert _normalize_ocr_confusions("l5") == "15"
        assert _normalize_ocr_confusions("5l") == "51"
        assert _normalize_ocr_confusions("liability") == "liability"

    def test_idempotent(self):
        for s in ["modern attorney", "O5 l5 5O", "no confusions here", "concern"]:
            once = _normalize_ocr_confusions(s)
            assert _normalize_ocr_confusions(once) == once

    def test_clean_text_with_no_gated_patterns_is_unchanged(self):
        s = "The court held that summary judgment was proper."
        assert _normalize_ocr_confusions(s) == s
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py -q`
Expected: FAIL with `ImportError: cannot import name '_normalize_ocr_confusions'`.

- [ ] **Step 3: Implement**

Add to `src/citation_verifier/quote_matcher.py` (after `_normalize_quote_text`):

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/quote_matcher.py tests/test_quote_matcher.py
git commit -m "feat: add _normalize_ocr_confusions (rn->m, O->0, l->1)"
```

---

## Task 3: Add `ocr` parameter to `_best_match_with_passage`

**Files:**
- Modify: `src/citation_verifier/quote_matcher.py`
- Test: `tests/test_quote_matcher.py`

**Interfaces:**
- Produces: `_best_match_with_passage(needle, haystack, context_chars=80, *, ocr: bool = False) -> tuple[float, str]`. When `ocr=False`, identical to today. When `ocr=True`, both sides are OCR-normalized (before lowercasing) for the comparison; the passage is sliced from the ORIGINAL haystack.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_quote_matcher.py`:

```python
from citation_verifier.quote_matcher import _best_match_with_passage


class TestBestMatchOcr:
    def test_ocr_false_is_unchanged_default(self):
        # "modem" (true) vs an opinion that has the OCR'd "modern": no exact hit
        r_off, _ = _best_match_with_passage("modem device", "the modern device works")
        assert r_off < 1.0

    def test_ocr_true_collapses_to_verbatim(self):
        # Opinion text OCR'd "m" as "rn"; quote has the true "m"
        ratio, passage = _best_match_with_passage(
            "the modem device", "before the modern device after", ocr=True,
        )
        assert ratio == 1.0
        assert passage  # non-empty, sliced from the original haystack
        assert "device" in passage

    def test_ocr_true_clean_text_same_ratio_as_off(self):
        q = "summary judgment was proper"
        h = "the court held that summary judgment was proper here"
        on, _ = _best_match_with_passage(q, h, ocr=True)
        off, _ = _best_match_with_passage(q, h, ocr=False)
        assert on == off == 1.0

    def test_ocr_passage_in_bounds_with_collapses_before_match(self):
        # Many rn-words before the match must not throw / must stay in-bounds.
        prefix = "return concern attorney govern modern " * 20
        h = prefix + "the quoted phrase here"
        ratio, passage = _best_match_with_passage(
            "the quoted phrase here", h, ocr=True,
        )
        assert ratio == 1.0
        assert isinstance(passage, str) and passage != ""
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py::TestBestMatchOcr -q`
Expected: FAIL (`ocr` is an unexpected keyword argument).

- [ ] **Step 3: Implement**

Replace `_best_match_with_passage` in `quote_matcher.py` with:

```python
def _best_match_with_passage(
    needle: str, haystack: str, context_chars: int = 80, *, ocr: bool = False,
) -> tuple[float, str]:
    """Find the best fuzzy match ratio and extract the matching passage.

    When ``ocr`` is True, both the needle and a COPY of the haystack are
    OCR-normalized (before lowercasing) for the comparison; the displayed
    passage is still sliced from the ORIGINAL haystack. Because ``rn``->``m``
    shortens text, the sliced position can drift by the number of collapses
    before the match — bounded, cosmetic, and never affects the returned ratio
    (the verdict). When ``ocr`` is False this is byte-for-byte the old path.
    """
    if not needle or not haystack:
        return 0.0, ""

    needle_norm = _normalize_quote_text(needle)
    if ocr:
        needle_norm = _normalize_ocr_confusions(needle_norm)
    needle_norm = needle_norm.lower()

    if ocr:
        haystack_cmp = _normalize_ocr_confusions(haystack).lower()
    else:
        haystack_cmp = haystack.lower()

    if not needle_norm:
        return 0.0, ""

    if needle_norm in haystack_cmp:
        pos = haystack_cmp.index(needle_norm)
        pos = min(pos, len(haystack))  # guard against length drift
        return 1.0, _extract_passage(haystack, pos, len(needle_norm), context_chars)

    best = 0.0
    best_start = 0
    window = len(needle_norm)
    step = max(1, window // 8)
    for start in range(0, max(1, len(haystack_cmp) - window + 1), step):
        chunk = haystack_cmp[start:start + window + window // 2]
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
        best_start = min(best_start, len(haystack))  # guard against drift
        passage = _extract_passage(
            haystack, best_start, window + window // 2, context_chars,
        )
    return best, passage
```

- [ ] **Step 4: Run to verify pass (and no regression on the moved suite)**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py tests/test_brief_pipeline.py tests/test_proposition_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/quote_matcher.py tests/test_quote_matcher.py
git commit -m "feat: add ocr param to _best_match_with_passage"
```

---

## Task 4: Add `QuoteMatch`, `QuoteVerification`, and `verify_quote`

**Files:**
- Modify: `src/citation_verifier/quote_matcher.py`
- Test: `tests/test_quote_matcher.py`

**Interfaces:**
- Produces:
  - `class QuoteMatch(str, enum.Enum)` with members `VERBATIM`, `CLOSE`, `FABRICATED` (values equal to names).
  - `@dataclass(frozen=True) class QuoteVerification` with fields `quote: str`, `result: QuoteMatch`, `similarity: float`, `matched_passage: str`, `was_ocrd: bool`.
  - `verify_quote(quote: str, opinion_text: str, *, was_ocrd: bool = False) -> QuoteVerification`. Buckets on the existing thresholds (`> 0.85` VERBATIM, `>= 0.6` CLOSE, else FABRICATED); `similarity` is the ratio rounded to 2 places; `quote` echoes the raw input.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_quote_matcher.py`:

```python
from citation_verifier.quote_matcher import (
    QuoteMatch,
    QuoteVerification,
    verify_quote,
)


class TestVerifyQuoteContract:
    def test_returns_quoteverification_with_enum_result(self):
        qv = verify_quote("hello world", "well, hello world!")
        assert isinstance(qv, QuoteVerification)
        assert qv.result is QuoteMatch.VERBATIM
        assert isinstance(qv.result, QuoteMatch)

    def test_quotematch_is_str_enum(self):
        assert issubclass(QuoteMatch, str)
        assert QuoteMatch.VERBATIM.value == "VERBATIM"

    def test_echoes_raw_input_quote(self):
        raw = "[T]he  court “held”"
        qv = verify_quote(raw, "irrelevant text")
        assert qv.quote == raw  # raw, NOT normalized

    def test_was_ocrd_echoed_and_defaults_false(self):
        assert verify_quote("a phrase", "x").was_ocrd is False
        assert verify_quote("a phrase", "x", was_ocrd=True).was_ocrd is True

    def test_similarity_in_unit_range(self):
        qv = verify_quote("totally absent phrase zzz", "unrelated opinion text")
        assert 0.0 <= qv.similarity <= 1.0

    def test_no_verbatim_attribute(self):
        assert not hasattr(verify_quote("a", "a"), "verbatim")

    def test_buckets(self):
        assert verify_quote("hello world", "say hello world now").result is QuoteMatch.VERBATIM
        assert verify_quote("zzz qqq vvv", "nothing alike here").result is QuoteMatch.FABRICATED


class TestVerifyQuoteOcr:
    def test_ocr_fixes_false_negative(self):
        # opinion OCR'd "modem" as "modern"; quote has the true "modem"
        opinion = "The parties used the modem to connect."
        quote = "used the modem to connect"
        off = verify_quote(quote, opinion, was_ocrd=False)
        on = verify_quote(quote, opinion, was_ocrd=True)
        assert on.result is QuoteMatch.VERBATIM
        assert off.result is not QuoteMatch.VERBATIM
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py::TestVerifyQuoteContract -q`
Expected: FAIL (`cannot import name 'QuoteMatch'`).

- [ ] **Step 3: Implement**

Add to the top imports of `quote_matcher.py`:

```python
import enum
from dataclasses import dataclass
```

Add at the end of `quote_matcher.py`:

```python
# --- Public quote primitive ---

# Bucketing thresholds (unchanged from check_quotes). VERBATIM is strictly
# above _VERBATIM_MIN; CLOSE is at or above _CLOSE_MIN; else FABRICATED.
_VERBATIM_MIN = 0.85
_CLOSE_MIN = 0.6


class QuoteMatch(str, enum.Enum):
    """How well a quote matched the opinion text."""
    VERBATIM = "VERBATIM"
    CLOSE = "CLOSE"
    FABRICATED = "FABRICATED"


@dataclass(frozen=True)
class QuoteVerification:
    """Result of verifying one quote against one opinion's text."""
    quote: str              # the RAW input quote, echoed verbatim
    result: QuoteMatch
    similarity: float       # 0.0-1.0 (difflib ratio; 1.0 = exact substring)
    matched_passage: str    # best-matching span from opinion_text ("" if none)
    was_ocrd: bool          # whether OCR-confusion rules were applied


def verify_quote(
    quote: str, opinion_text: str, *, was_ocrd: bool = False,
) -> QuoteVerification:
    """Verify a quote against opinion text. Public primitive.

    Applies CV's legal-quote normalization always, and the conservative
    OCR-confusion rules only when ``was_ocrd`` is True. Buckets the fuzzy ratio
    into VERBATIM/CLOSE/FABRICATED on the existing thresholds.
    """
    ratio, passage = _best_match_with_passage(quote, opinion_text, ocr=was_ocrd)
    if ratio > _VERBATIM_MIN:
        result = QuoteMatch.VERBATIM
    elif ratio >= _CLOSE_MIN:
        result = QuoteMatch.CLOSE
    else:
        result = QuoteMatch.FABRICATED
    return QuoteVerification(
        quote=quote,
        result=result,
        similarity=round(ratio, 2),
        matched_passage=passage,
        was_ocrd=was_ocrd,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/quote_matcher.py tests/test_quote_matcher.py
git commit -m "feat: add public verify_quote + QuoteVerification + QuoteMatch"
```

---

## Task 5: Export the primitive from the package

**Files:**
- Modify: `src/citation_verifier/__init__.py`
- Test: `tests/test_quote_matcher.py`

**Interfaces:**
- Produces: `from citation_verifier import verify_quote, QuoteVerification, QuoteMatch` works.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quote_matcher.py`:

```python
def test_public_exports():
    import citation_verifier as cv
    assert hasattr(cv, "verify_quote")
    assert hasattr(cv, "QuoteVerification")
    assert hasattr(cv, "QuoteMatch")
    assert "verify_quote" in cv.__all__
    assert "QuoteVerification" in cv.__all__
    assert "QuoteMatch" in cv.__all__
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py::test_public_exports -q`
Expected: FAIL (`module 'citation_verifier' has no attribute 'verify_quote'`).

- [ ] **Step 3: Implement**

Edit `src/citation_verifier/__init__.py`:

```python
from .client import CourtListenerClient
from .models import (
    CandidateMatch,
    ParsedCitation,
    Status,
    VerificationResult,
)
from .parser import parse_citation
from .quote_matcher import QuoteMatch, QuoteVerification, verify_quote
from .verifier import CitationVerifier

__all__ = [
    "CitationVerifier",
    "CourtListenerClient",
    "CandidateMatch",
    "ParsedCitation",
    "QuoteMatch",
    "QuoteVerification",
    "Status",
    "VerificationResult",
    "parse_citation",
    "verify_quote",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_quote_matcher.py::test_public_exports -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/__init__.py tests/test_quote_matcher.py
git commit -m "feat: export verify_quote, QuoteVerification, QuoteMatch"
```

---

## Task 6: Capture `extracted_by_ocr` in the client metadata

**Files:**
- Modify: `src/citation_verifier/client.py` (sync `_resolve_opinion_text_with_metadata` ≈ 441-546; async ≈ 901-1010)
- Test: `tests/test_proposition_pipeline.py`

**Interfaces:**
- Produces: both `get_opinion_text_with_metadata` variants return a dict that includes `"extracted_by_ocr": bool | None`, read from the same sub-opinion JSON that yielded the text. Docket/RECAP and PDF-fallback returns set it to `None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_proposition_pipeline.py` (a focused unit test on the sync resolver with a stubbed `_request_with_retry`):

```python
def test_resolver_captures_extracted_by_ocr(monkeypatch):
    from citation_verifier.client import CourtListenerClient

    client = CourtListenerClient(api_token="x")

    def fake_request(method, url, **kwargs):
        class R:
            def __init__(self, payload):
                self._p = payload
            def json(self):
                return self._p
        if "/clusters/" in url:
            return R({"sub_opinions": ["https://cl/api/opinions/9/"],
                      "case_name": "Demo v. Test", "citations": [], "docket": ""})
        if "/opinions/" in url:
            return R({"plain_text": "Some opinion body text.",
                      "extracted_by_ocr": True})
        return R({})

    monkeypatch.setattr(client, "_request_with_retry", fake_request)
    data = client.get_opinion_text_with_metadata(
        "https://www.courtlistener.com/opinion/123/demo-v-test/",
    )
    assert data is not None
    assert data["extracted_by_ocr"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py::test_resolver_captures_extracted_by_ocr -q`
Expected: FAIL (`KeyError: 'extracted_by_ocr'`).

- [ ] **Step 3: Implement (sync resolver)**

In `client.py` sync `_resolve_opinion_text_with_metadata`, change the sub-opinion loop to capture the flag, and add the key to BOTH the PDF-fallback dict and the success dict:

```python
            text = None
            fmt = "text"
            extracted_by_ocr = None
            for op_url in cluster.get("sub_opinions", []):
                op_id = op_url.rstrip("/").split("/")[-1]
                opinion_resp = self._request_with_retry(
                    "GET", f"{self.BASE_URL}/opinions/{op_id}/"
                )
                opinion = opinion_resp.json()
                t, f = _extract_opinion_text(opinion, prefer_html=prefer_html)
                if t:
                    text = t
                    fmt = f
                    extracted_by_ocr = opinion.get("extracted_by_ocr")
                    break
```

In the PDF-fallback `return {...}` add `"extracted_by_ocr": None,`. In the final success `return {...}` add `"extracted_by_ocr": extracted_by_ocr,`.

- [ ] **Step 4: Implement (async resolver + docket path)**

Apply the identical change to async `_resolve_opinion_text_with_metadata` (≈ 921-932 loop; ≈ 945-956 PDF dict; ≈ 995-1005 success dict):

```python
            text = None
            fmt = "text"
            extracted_by_ocr = None
            for op_url in cluster.get("sub_opinions", []):
                op_id = op_url.rstrip("/").split("/")[-1]
                opinion = await self._request_with_retry(
                    "GET", f"{self.BASE_URL}/opinions/{op_id}/"
                )
                t, f = _extract_opinion_text(opinion, prefer_html=prefer_html)
                if t:
                    text = t
                    fmt = f
                    extracted_by_ocr = opinion.get("extracted_by_ocr")
                    break
```

Add `"extracted_by_ocr": None,` to the async PDF-fallback dict, and `"extracted_by_ocr": extracted_by_ocr,` to the async success dict. In BOTH `get_opinion_text_with_metadata` docket/RECAP success dicts (sync ≈ 884-894, async ≈ 884-894 equivalent) add `"extracted_by_ocr": None,` (RECAP text has no opinion-level OCR flag).

- [ ] **Step 5: Run to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py::test_resolver_captures_extracted_by_ocr tests/test_client_html.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/citation_verifier/client.py tests/test_proposition_pipeline.py
git commit -m "feat: capture extracted_by_ocr from sub-opinion JSON in client metadata"
```

---

## Task 7: Write the `opinions/ocr_status.json` manifest during downloads

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (`_download_opinion` ≈ 379-488; `wave1_verify_and_download` ≈ 494-541; `wave2_fallback_and_download` ≈ 548-594; add manifest helpers)
- Test: `tests/test_proposition_pipeline.py`

**Interfaces:**
- Produces:
  - `_ocr_manifest_path(workdir) -> Path`, `_read_ocr_manifest(workdir) -> dict[str, object]`, `_write_ocr_manifest(workdir, mapping) -> None` (merges into existing).
  - `_download_opinion(..., ocr_manifest: dict | None = None)` — records `ocr_manifest[filename] = data.get("extracted_by_ocr")` for text/html downloads. Return type unchanged (`str | None`).
  - Manifest keyed by bare filename (e.g. `"State_v_Kelly.html"`), matching `Path(opinion_file).name`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_proposition_pipeline.py`:

```python
def test_ocr_manifest_roundtrip(tmp_path):
    from citation_verifier.proposition_pipeline import (
        _read_ocr_manifest, _write_ocr_manifest,
    )
    assert _read_ocr_manifest(tmp_path) == {}
    _write_ocr_manifest(tmp_path, {"A.html": True})
    _write_ocr_manifest(tmp_path, {"B.txt": None})  # merge, don't clobber
    m = _read_ocr_manifest(tmp_path)
    assert m["A.html"] is True
    assert "B.txt" in m
    assert (tmp_path / "opinions" / "ocr_status.json").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py::test_ocr_manifest_roundtrip -q`
Expected: FAIL (`cannot import name '_read_ocr_manifest'`).

- [ ] **Step 3: Implement the helpers**

Add near the top of `proposition_pipeline.py` (after imports; `json_mod` is the module's existing `json` alias — verify the alias name in the file and use it):

```python
def _ocr_manifest_path(workdir: Path) -> Path:
    return Path(workdir) / "opinions" / "ocr_status.json"


def _read_ocr_manifest(workdir: Path) -> dict[str, object]:
    """Read opinions/ocr_status.json -> {filename: extracted_by_ocr}. {} if absent."""
    path = _ocr_manifest_path(workdir)
    if not path.exists():
        return {}
    try:
        data = json_mod.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json_mod.JSONDecodeError, OSError):
        return {}


def _write_ocr_manifest(workdir: Path, mapping: dict[str, object]) -> None:
    """Merge `mapping` into opinions/ocr_status.json (no-op if mapping empty)."""
    if not mapping:
        return
    merged = _read_ocr_manifest(workdir)
    merged.update(mapping)
    path = _ocr_manifest_path(workdir)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json_mod.dumps(merged, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Wire `_download_opinion` to record the flag**

Change the signature:

```python
async def _download_opinion(
    client: AsyncCourtListenerClient,
    workdir: Path,
    result: VerificationResult,
    citation: str,
    ocr_manifest: dict[str, object] | None = None,
) -> str | None:
```

In the text/html success branch (after `(opinions_dir / filename).write_text(...)`, before `return filename`):

```python
        ext = ".html" if fmt == "html" else ".txt"
        filename = f"{base}{ext}"
        (opinions_dir / filename).write_text(text, encoding="utf-8")
        if ocr_manifest is not None:
            ocr_manifest[filename] = data.get("extracted_by_ocr")
        return filename
```

(PDF branch unchanged — PDFs are not quote-checked.)

- [ ] **Step 5: Wire both waves to build + persist the manifest**

In `wave1_verify_and_download`, before the `async with AsyncCourtListenerClient()` block add `ocr_manifest: dict[str, object] = {}`; pass it into the `_download_opinion` call (`await _download_opinion(client, workdir, result, cite, ocr_manifest)`); after the `for` loop (still inside or just after the `async with`, before `_write_verification_csv`) add `_write_ocr_manifest(workdir, ocr_manifest)`.

Apply the same three edits to `wave2_fallback_and_download` (its own local `ocr_manifest`, passed into `_download_opinion`, `_write_ocr_manifest` after the loop — it MERGES into wave1's manifest).

- [ ] **Step 6: Run to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py::test_ocr_manifest_roundtrip tests/test_brief_pipeline.py -q`
Expected: PASS (existing wave tests still green — the new param defaults to None for any direct callers).

- [ ] **Step 7: Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: write opinions/ocr_status.json manifest during downloads"
```

---

## Task 8: Route `check_quotes` through `verify_quote`, gated by the manifest

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (`check_quotes` ≈ 1842-1963)
- Test: `tests/test_proposition_pipeline.py`

**Interfaces:**
- Consumes: `verify_quote`, `_read_ocr_manifest`.
- Produces: `check_quotes` calls `verify_quote(quote, opinion_text, was_ocrd=<manifest gate>)` per quote and maps the result onto the EXISTING `quote_check` entry dict (`quote`/`result`/`similarity`/optional `matched_passage`) and the `QuoteCheckStats` counters. Output shape unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_proposition_pipeline.py` (drives `check_quotes` over a tiny workdir; the manifest flips a near-miss to VERBATIM):

```python
def test_check_quotes_applies_ocr_gate(tmp_path):
    import csv, json
    from citation_verifier.proposition_pipeline import (
        check_quotes, _write_ocr_manifest,
    )
    wd = tmp_path
    (wd / "opinions").mkdir()
    # Opinion text OCR'd "modem" as "modern":
    (wd / "opinions" / "Op.txt").write_text(
        "The court found the modern was defective and unusable here.",
        encoding="utf-8",
    )
    rows = [{
        "claim_id": "c-1",
        "proposition": "p",
        "brief_sentence": "",
        "quoted_text": json.dumps(["the modem was defective and unusable"]),
        "opinion_file": "opinions/Op.txt",
    }]
    cols = list(rows[0].keys())
    with open(wd / "claims.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(rows)

    # Without the gate -> not verbatim
    check_quotes(wd)
    with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
        worst_off = list(csv.DictReader(f))[0]["quote_check_worst"]
    assert worst_off != "VERBATIM"

    # Mark the opinion OCR'd, re-check -> verbatim
    _write_ocr_manifest(wd, {"Op.txt": True})
    check_quotes(wd)
    with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
        worst_on = list(csv.DictReader(f))[0]["quote_check_worst"]
    assert worst_on == "VERBATIM"
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py::test_check_quotes_applies_ocr_gate -q`
Expected: FAIL (second assert: still not VERBATIM, gate not wired).

- [ ] **Step 3: Implement**

In `check_quotes`, after loading `claims` and before the per-claim loop, add:

```python
    ocr_manifest = _read_ocr_manifest(workdir)
```

Inside the per-claim loop, after `opinion_text = opinion_cache[opinion_file]`, compute the gate:

```python
        was_ocrd = bool(ocr_manifest.get(Path(opinion_file).name, False))
```

Replace the per-quote matching block (the `for quote in quotes:` body that calls `_best_match_with_passage` and buckets) with a `verify_quote` call, preserving the entry dict + stats:

```python
        for quote in quotes:
            qv = verify_quote(quote, opinion_text, was_ocrd=was_ocrd)
            result = qv.result.value
            if result == "VERBATIM":
                stats.verbatim += 1
            elif result == "CLOSE":
                stats.close += 1
            else:
                stats.fabricated += 1

            entry: dict[str, object] = {
                "quote": quote,
                "result": result,
                "similarity": qv.similarity,
            }
            if qv.matched_passage:
                entry["matched_passage"] = qv.matched_passage
            results.append(entry)

            if _WORST_ORDER.get(result, 0) > _WORST_ORDER.get(worst, 0):
                worst = result
```

Add `verify_quote` to the `from .quote_matcher import (...)` block at the top of `proposition_pipeline.py`.

- [ ] **Step 4: Run to verify pass + full quote suite**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py tests/test_brief_pipeline.py tests/test_quote_matcher.py -q`
Expected: PASS. The `was_ocrd=False` default path keeps existing `check_quotes` tests green (identical numbers/verdicts).

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: gate check_quotes OCR normalization on the manifest via verify_quote"
```

---

## Task 9: Version bump, CHANGELOG, CLAUDE.md note

**Files:**
- Modify: `pyproject.toml`, `CHANGELOG.md`, `CLAUDE.md`

- [ ] **Step 1: Bump the version**

In `pyproject.toml` change `version = "0.4.0"` to `version = "0.5.0"`.

- [ ] **Step 2: Add the CHANGELOG entry**

Insert at the top of `CHANGELOG.md` (after the title/preamble, above the `v0.4.0` section):

```markdown
## v0.5.0 — 2026-06-28 (Public quote primitive + OCR-confusion normalization)

Design: `docs/superpowers/specs/2026-06-28-ocr-quote-normalization-design.md`.

Additive feature layer; core verifier unchanged.

### New public API (`quote_matcher.py`, exported from the package)

- **`verify_quote(quote, opinion_text, *, was_ocrd=False) -> QuoteVerification`** —
  workdir-free quote-fidelity primitive. `QuoteVerification` carries
  `quote` (raw input), `result` (`QuoteMatch` enum), `similarity` (0-1),
  `matched_passage`, `was_ocrd`. `QuoteMatch(str, Enum)` = VERBATIM/CLOSE/FABRICATED.
- The legal-quote internals (`_normalize_quote_text`, `_best_match_with_passage`,
  `_extract_passage`) moved into `quote_matcher.py`; still re-exported from
  `proposition_pipeline` (and the `brief_pipeline` alias) for compatibility.

### OCR-confusion normalization

- Conservative one-directional rules (`rn`->`m` mid-word, `O`->`0` / `l`->`1`
  digit-adjacent), applied to both quote and opinion text, ONLY when the opinion
  was OCR'd. Gated on CourtListener's per-sub-opinion `extracted_by_ocr` field,
  carried into the workdir via a new `opinions/ocr_status.json` manifest. Thresholds
  and quote-floors unchanged; clean text is unaffected (symmetric collapse).

### Backward compatibility

- `run_check_quotes` / `QuoteCheckStats` and the `quote_check` / `quote_check_worst`
  / `quote_floor` columns keep their shapes. No claims.csv schema change. Values may
  improve on OCR'd opinions (intended). New artifact: `opinions/ocr_status.json`.
```

- [ ] **Step 3: Add the CLAUDE.md note**

In `CLAUDE.md`, add a `quote_matcher.py` row to the Core-library table and a one-line note under the `proposition_pipeline.py` `check-quotes` description:

```markdown
| `quote_matcher.py` | Quote-fidelity primitives. Public `verify_quote(quote, opinion_text, *, was_ocrd=False) -> QuoteVerification` (+ `QuoteMatch` enum), exported from the package. Houses `_normalize_quote_text`, `_best_match_with_passage`, `_extract_passage` (re-exported from `proposition_pipeline` for compat) and `_normalize_ocr_confusions` (conservative `rn`->`m` / `O`->`0` / `l`->`1`, applied only when `was_ocrd`). |
```

Note on `check-quotes`: "OCR gate sourced per opinion from `opinions/ocr_status.json` (CL `extracted_by_ocr`); rules off by default when unknown."

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md CLAUDE.md
git commit -m "docs: bump to 0.5.0, changelog + CLAUDE.md for verify_quote/OCR"
```

---

## Task 10: Full regression gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full offline suite**

Run: `venv/Scripts/python.exe -m pytest -q --ignore=tests/test_false_negatives.py --ignore=tests/test_false_positives.py`
(The `--ignore`d suites hit the live CL API and need a token; run them separately if a token is present.)
Expected: PASS, with no NEW failures vs. a pre-change baseline. If anything fails, fix it in the owning task's module before proceeding (do not mark this task complete with failures).

- [ ] **Step 2: Run the real-citation benchmark guard explicitly**

Run: `venv/Scripts/python.exe -m pytest tests/test_benchmark_regression.py -v`
Expected: PASS (or a clean skip if no cassette is recorded). The guard's job is to catch any new false-negative on real citations — there must be none. The OCR path defaults off, so this should be unaffected.

- [ ] **Step 3: Sanity-check the public primitive end to end**

Run:
```bash
venv/Scripts/python.exe -c "from citation_verifier import verify_quote, QuoteMatch; r=verify_quote('the modem was used','the modern was used', was_ocrd=True); print(r.result, r.similarity, r.was_ocrd); assert r.result is QuoteMatch.VERBATIM"
```
Expected: prints `QuoteMatch.VERBATIM 1.0 True` and the assert passes.

- [ ] **Step 4: Final commit / push**

```bash
git add -A
git commit -m "test: full regression gate for verify_quote + OCR normalization" --allow-empty
git push
```

(Push per the project's always-commit-and-push workflow; the user syncs across machines via git.)

---

## Self-Review

**Spec coverage:**
- Public `verify_quote` + `QuoteVerification` + `QuoteMatch` → Tasks 4, 5. ✅
- OCR rules (`rn`/`O`/`l`) → Task 2. ✅
- Ordering (OCR before lower) → Task 3 implementation. ✅
- Passage-position handling (original haystack, drift guard) → Task 3. ✅
- Gate on `extracted_by_ocr` (sub-opinion, not cluster) → Task 6. ✅
- Manifest carrier `opinions/ocr_status.json` → Task 7. ✅
- `check_quotes` refactor + gate → Task 8. ✅
- Module move + re-import compat → Task 1. ✅
- Thresholds unchanged → Task 4 constants copied from check_quotes; Global Constraints. ✅
- Backward-compat (output shapes, importability) → Tasks 1, 8; Global Constraints. ✅
- Version + CHANGELOG + CLAUDE.md → Task 9. ✅
- Regression guard (full suite + benchmark) → Task 10. ✅
- Contract test mirroring grader's → Task 4 `TestVerifyQuoteContract`. ✅

**Type consistency:** `QuoteMatch` / `QuoteVerification` / `verify_quote` signatures match across Tasks 4, 5, 8, 9. `_best_match_with_passage(..., *, ocr=False)` consistent Tasks 3, 4. Manifest helpers `_read_ocr_manifest`/`_write_ocr_manifest`/`_ocr_manifest_path` consistent Tasks 7, 8. Manifest keyed by bare filename in both writer (`_download_opinion`, Task 7) and reader (`Path(opinion_file).name`, Task 8). ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. One implementation note to honor at execution time: confirm the existing `json` import alias name in `proposition_pipeline.py` (the file uses `json_mod`) and the exact line numbers (drift since 2026-06-28) before editing.
