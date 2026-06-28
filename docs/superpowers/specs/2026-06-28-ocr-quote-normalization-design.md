# OCR-Confusion Normalization + Public `verify_quote` Primitive

**Date:** 2026-06-28
**Status:** Approved design (pending cross-repo contract confirmation) — ready for implementation plan
**Borrow source:** `LegalQuants/lq-ai` → `api/app/citation/normalization.py` (private)
**Cross-repo consumer:** `us-legal-research` eval grader (axis Q)
**Version:** bumps citation-verifier `0.4.0` → `0.5.0` (additive, backward-compatible)

## Problem

Two coupled problems, one fix.

1. **OCR false negatives.** CV's quote-fidelity checker compares a quote from a
   brief against the cited opinion's text. When that text was produced by OCR
   (scanned/image PDF), predictable misreads — the serif pair `rn` read as `m`,
   and `O`↔`0`, `l`↔`1` — make an *honest, verbatim* quote score below the
   VERBATIM/CLOSE thresholds: a **false negative** on a faithful quote.
2. **No reusable quote primitive.** The reusable logic (`_best_match_with_passage`
   + `_normalize_quote_text`) is private and bound to the workdir pipeline.
   `run_check_quotes(workdir)` reads `citations_toa.txt` / opinion files from a
   directory; it is not a `(quote, opinion_text) → match` function. The
   `us-legal-research` eval grader (axis Q) cannot consume CV's quote-checking
   without reaching into privates, violating the single-seam / drift discipline.

## Goal

Expose a clean **public quote primitive** with OCR normalization built in, and
refactor CV's own pipeline to use it. Concretely:

```python
def verify_quote(quote: str, opinion_text: str, *, was_ocrd: bool = False) -> QuoteVerification
```

- The primitive is pure: no workdir, no files. The caller supplies the OCR flag
  as a parameter.
- OCR normalization is conservative, one-directional, and applied to *both* the
  quote and the opinion text, so clean text is unaffected (symmetric collapse).
- CV's `check_quotes` is refactored to call `verify_quote` internally, sourcing
  `was_ocrd` per opinion from the workdir.

Non-goals: changing the VERBATIM/CLOSE/FABRICATED thresholds or quote-floor
calibration; RECAP-document OCR handling (opinions only for now); re-architecting
the fuzzy matcher.

## Architecture: two layers

```
                        ┌─────────────────────────────────────────────┐
 us-legal-research  ───▶│  verify_quote(quote, opinion_text,           │  PUBLIC
   eval grader (Q)      │                *, was_ocrd=False)            │  primitive
                        │      → QuoteVerification                     │  (quote_matcher.py)
                        └──────────────────┬──────────────────────────┘
                                           │ called internally, per quote
                        ┌──────────────────▼──────────────────────────┐
 CV brief/matter   ───▶ │  check_quotes(workdir) / run_check_quotes    │  WORKDIR
   pipeline + web app   │   - sources `was_ocrd` per opinion           │  pipeline
                        │   - maps QuoteVerification → existing CSV     │  (proposition_pipeline.py)
                        └─────────────────────────────────────────────┘
```

The two consumers hit *different seams*. The grader hits the pure primitive and
passes `was_ocrd` directly — so the OCR gate, from the grader's perspective, is
just a function argument. CV's own pipeline hits the workdir layer, which is the
only place that has to *source* `was_ocrd` from somewhere (see "OCR gate" below).

## The borrow (what's new vs. what CV already has)

lq-ai's `normalize(text, *, was_ocrd=False)` has two layers:

1. **Always-on layer** — smart quotes → straight, collapse whitespace,
   canonicalize CRLF, strip. **CV already does all of this** in
   `_normalize_quote_text` (+ the haystack-cleaning in `check_quotes`), and does
   *more* (strips bracketed alterations `[T]`→`t` and ellipses — legal-quote
   conventions lq-ai lacks). **We borrow nothing here.**
2. **OCR-conditional layer** — three substitutions, the entire borrow:
   - `rn` → `m` when preceded by a word char: `(?<=\w)rn`
   - `O` → `0` when adjacent to a digit: `(?<=\d)O|O(?=\d)`
   - `l` → `1` when adjacent to a digit: `(?<=\d)l|l(?=\d)`

   One rule per pair, one-directional, applied to both sides so clean words with
   mid-word `rn` ("attorney", "return", "concern", "modern") collapse to the same
   target on both sides. The residual false-positive risk (brief wrote the m-form
   where the opinion genuinely has the rn-form, or vice-versa) is exactly what the
   OCR gate eliminates.

### Threshold reconciliation

lq-ai uses `rapidfuzz.fuzz.ratio` vs. a strict **95** (0–100). CV uses
`difflib.SequenceMatcher.ratio()` on **0–1**, VERBATIM > 0.85, CLOSE ≥ 0.6 — a
*more forgiving* verbatim cut. We **keep CV's thresholds unchanged**; the OCR
rules just raise the ratio on a true match against OCR'd text, nudging CLOSE →
VERBATIM (or FABRICATED → CLOSE). No threshold or quote-floor change.

## Public contract (pins the grader's contract test)

New module `src/citation_verifier/quote_matcher.py`, exported from `__init__.py`:

```python
@dataclass(frozen=True)
class QuoteVerification:
    quote: str            # the input quote, echoed
    result: str           # "VERBATIM" | "CLOSE" | "FABRICATED"
    similarity: float     # 0.0–1.0 (difflib ratio; 1.0 = exact substring match)
    matched_passage: str  # best-matching span from opinion_text w/ context ("" if none)
    was_ocrd: bool        # echo of the input flag — whether OCR rules were applied

def verify_quote(
    quote: str,
    opinion_text: str,
    *,
    was_ocrd: bool = False,
) -> QuoteVerification: ...
```

**Proposed, pending the `us-legal-research` session's confirmation** (see the
coordination question in the cover note):

- `result` is a plain `str` with the three documented values (minimal, stable
  contract surface). Switchable to an exported `QuoteMatch` enum if the grader
  prefers to assert on a type.
- Field names `result` / `similarity` / `matched_passage`. Aligning before their
  contract test is written is cheaper than after.

Bucketing (the 0.85 / 0.6 thresholds, currently inline in `check_quotes`) moves
*into* `verify_quote` so the primitive is complete. `check_quotes` then maps a
`QuoteVerification` back onto its existing `{quote, result, similarity,
matched_passage}` entry dict (no change to that on-disk shape — see Backward
compatibility).

## Module layout (`quote_matcher.py`)

Moves the quote-matching internals out of `proposition_pipeline.py` into a
well-bounded module (matching the `name_matcher.py` / `text_cleaner.py` pattern),
giving the grader a stable seam decoupled from the pipeline:

- `_normalize_quote_text` (moved) — existing legal-quote normalization.
- `_normalize_ocr_confusions` (new) — the borrow.
- `_best_match_with_passage` (moved) — gains an `ocr: bool = False` param.
- `_extract_passage` (moved).
- thresholds + `verify_quote` + `QuoteVerification` (new).

`proposition_pipeline.py` imports these from `quote_matcher`. Any current
`proposition_pipeline` references to the moved names are re-pointed; a module-level
re-import alias keeps internal call sites and existing tests working
(`from .quote_matcher import _normalize_quote_text, _best_match_with_passage`).

### New pure function: `_normalize_ocr_confusions(text) -> str`

```python
_OCR_RN_RE = re.compile(r"(?<=\w)rn")
_OCR_O_RE  = re.compile(r"(?<=\d)O|O(?=\d)")
_OCR_L_RE  = re.compile(r"(?<=\d)l|l(?=\d)")

def _normalize_ocr_confusions(text: str) -> str:
    out = _OCR_RN_RE.sub("m", text)
    out = _OCR_O_RE.sub("0", out)
    out = _OCR_L_RE.sub("1", out)
    return out
```

Properties (tested): one-directional, **idempotent** (`f(f(t)) == f(t)`), no-op
on clean text lacking the gated patterns.

### Ordering constraint (the subtle bug to avoid)

`O`→`0` and `l`→`1` are **case-sensitive** (capital `O`, lowercase `l`). CV
lowercases before matching. OCR normalization must run **before** `.lower()`, or
those two rules silently never fire. Per side: raw → `_normalize_quote_text` →
**`_normalize_ocr_confusions` (case-preserving)** → `.lower()`.

### Passage-position constraint

`rn`→`m` is length-*changing*, so it cannot touch the haystack used for passage
extraction (the extractor relies on 1:1 positions). When `was_ocrd` is true,
`_best_match_with_passage` builds a **separate** OCR-normalized comparison string
(OCR-normalize then lowercase) for the exact-substring check and the
sliding-window `SequenceMatcher`, but slices the displayed passage from the
**original** haystack. The extractor already pads ±80 chars and trims to sentence
boundaries, so the bounded offset from `rn`→`m` collapses is cosmetic and never
changes the verdict. When `was_ocrd` is false, the code path is byte-for-byte
identical to today (no normalized copy built).

## The OCR gate (now an internal CV concern only)

The grader passes `was_ocrd` directly, so the gate is a non-issue for it. CV's
*own* `check_quotes` still needs to source the flag per opinion. The flag is known
at download time (`verify` step) but needed at check time (`check-quotes` step),
in an offline/idempotent model — so it must be persisted in the workdir.

**Decision: a single per-workdir manifest** `opinions/ocr_status.json` mapping
opinion filename → bool. Chosen over a per-opinion sidecar (fewer files) and over
a claims.csv column (keeps the CSV — and CV's own report/web-app consumers —
untouched; no schema churn). Default when absent/unknown (legacy workdirs,
user-supplied opinion files, RECAP/PDF text) is `False` — rules off, the cautious
default.

Plumbing:

1. **`client.py` — capture.** In both `get_opinion_text_with_metadata` variants
   (sync + async) + `_resolve_opinion_text_with_metadata`, when a sub-opinion
   yields usable text, read `opinion.get("extracted_by_ocr")` and add
   `"extracted_by_ocr": bool | None` to the returned metadata dict. RECAP/docket
   and PDF-fallback paths set it `None`. No extra API calls.
2. **`proposition_pipeline.py` — write the manifest.** `_download_opinion` returns
   the OCR flag alongside the filename; the download orchestrator (wave1/wave2)
   collects `{filename: flag}` after the concurrent gather and writes
   `opinions/ocr_status.json` once (race-free — single writer post-gather).
3. **`proposition_pipeline.py::check_quotes` — read + gate.** Load
   `opinions/ocr_status.json` once; for each claim look up its `opinion_file`;
   pass `was_ocrd=manifest.get(basename, False)` into `verify_quote`.

## Backward compatibility

- **Public addition only:** `verify_quote` + `QuoteVerification` are new exports.
  Nothing existing is removed or renamed.
- **`run_check_quotes` / `QuoteCheckStats` shape unchanged.** The grader is moving
  to the `verify_quote` seam, so this is no longer an *external* contract — but we
  still preserve it for CV's own report + web app. The `quote_check` /
  `quote_check_worst` / `quote_floor` CSV columns keep their shape; values may
  *improve* on OCR'd opinions (intended behavior change, not schema change).
- **No new claims.csv / verification_results.csv column.** The OCR flag rides in
  `opinions/ocr_status.json` (a new additive artifact), invisible to CSV consumers.
- `__init__.py` `__all__` gains `verify_quote`, `QuoteVerification` (and
  `QuoteMatch` if the enum option is chosen).

## Testing (cassette-backed, offline)

New `tests/test_quote_matcher.py`:

1. **Per-rule unit tests** for `_normalize_ocr_confusions`: `rn`→`m` mid-word
   ("modern"→"modem"), not word-initial ("rnage" unchanged); `O`→`0` only next to
   a digit ("O5"→"05"), "Office" unchanged; `l`→`1` only next to a digit
   ("l5"→"15"), "liability" unchanged.
2. **Idempotence:** `f(f(t)) == f(t)` over a representative set.
3. **Clean-text non-regression:** `f(t) == t` for inputs lacking gated patterns;
   and `verify_quote(clean_q, clean_op, was_ocrd=True).similarity ==
   verify_quote(clean_q, clean_op, was_ocrd=False).similarity` (symmetric collapse).
4. **OCR true-positive:** opinion text with the OCR'd form ("modem" rendered
   "modern") + quote with the true form ("modem") → `result == "VERBATIM"` with
   `was_ocrd=True`, but below VERBATIM with `was_ocrd=False` (fix works; gate
   matters).
5. **Contract test** (mirrors the grader's): `verify_quote` returns a
   `QuoteVerification` with the agreed fields/types; `result` ∈ the three values;
   `similarity` ∈ [0, 1]; `was_ocrd` echoes the input; default `was_ocrd=False`.
6. **Passage coherence:** with `was_ocrd=True` and an `rn`→`m` collapse before the
   match, `matched_passage` is sliced from the original opinion text and is
   in-bounds/coherent.

Pipeline-level (in `tests/test_proposition_pipeline.py`):

7. **Manifest gate:** `check_quotes` applies OCR rules iff
   `opinions/ocr_status.json` marks the opinion `true`; absent/`false` → unchanged
   behavior. `client` metadata dict carries `extracted_by_ocr` from a mocked
   opinion JSON.

### Regression guard

Run the full suite — especially the real-citation benchmark guard and the existing
quote-check tests — and confirm **no regressions**. The `was_ocrd=False` default
path must remain byte-for-byte identical to current behavior.

## Version & changelog

- Bump `pyproject.toml` `0.4.0` → `0.5.0`.
- CHANGELOG `v0.5.0` entry: the public `verify_quote`/`QuoteVerification`
  primitive, OCR-conditional normalization, `extracted_by_ocr` plumbing +
  `ocr_status.json` manifest, and the explicit backward-compat guarantees — so the
  `us-legal-research` grader can pin the upgraded CV.

## Files touched

| File | Change |
|------|--------|
| `src/citation_verifier/quote_matcher.py` | **New.** `_normalize_quote_text` (moved), `_normalize_ocr_confusions` (new), `_best_match_with_passage` (moved, +`ocr` param), `_extract_passage` (moved), thresholds, `verify_quote`, `QuoteVerification`. |
| `src/citation_verifier/__init__.py` | Export `verify_quote`, `QuoteVerification` (+ `QuoteMatch` if enum). |
| `src/citation_verifier/client.py` | Capture `extracted_by_ocr` into the metadata dict (sync + async resolvers). |
| `src/citation_verifier/proposition_pipeline.py` | Import quote internals from `quote_matcher`; `_download_opinion` returns OCR flag; orchestrator writes `opinions/ocr_status.json`; `check_quotes` reads manifest + calls `verify_quote` per quote. |
| `tests/test_quote_matcher.py` | **New.** Per-rule, idempotence, clean-text, true-positive, contract, passage tests. |
| `tests/test_proposition_pipeline.py` | Manifest-gate + client `extracted_by_ocr` tests. |
| `pyproject.toml` | Version `0.4.0` → `0.5.0`. |
| `CHANGELOG.md` | `v0.5.0` entry. |
| `CLAUDE.md` | Note the new `quote_matcher.py` module, the `verify_quote` public primitive, OCR gate + `ocr_status.json`. |

## Open items requiring cross-repo confirmation

1. `result` as `str` vs. exported `QuoteMatch` enum.
2. Field names `result` / `similarity` / `matched_passage` (vs. e.g. `category` /
   `score`).
3. Whether the grader wants `quote` echoed (post- or pre-normalization — proposal:
   echo the raw input verbatim).
