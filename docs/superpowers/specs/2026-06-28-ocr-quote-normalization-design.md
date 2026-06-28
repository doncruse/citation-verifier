# OCR-Confusion Normalization for Quote-Fidelity Matching

**Date:** 2026-06-28
**Status:** Approved design — ready for implementation plan
**Borrow source:** `LegalQuants/lq-ai` → `api/app/citation/normalization.py` (private)
**Version:** bumps citation-verifier `0.4.0` → `0.5.0` (additive, backward-compatible)

## Problem

CV's quote-fidelity checker (`check_quotes` → `_best_match_with_passage`) compares a
quote drawn from a brief against the text of the cited opinion. When the opinion
text was produced by OCR (optical character recognition of a scanned/image PDF),
predictable character misreads — most commonly the serif pair `rn` read as `m`,
and the letter/digit confusions `O`↔`0`, `l`↔`1` — make an *honest, verbatim*
quote score below the VERBATIM/CLOSE thresholds. The result is a **false
negative**: the tool flags a faithful quote as CLOSE or FABRICATED.

This hurts every CV consumer of `check_quotes` output: the proposition/brief
pipelines, the web app, and the new eval grader in the `us-legal-research` repo.

## Goal

Layer a conservative, one-directional OCR-confusion normalization *under* CV's
existing quote normalization, applied **only** when the opinion is known to be
OCR'd, so that faithful quotes against OCR'd opinions stop false-negativing —
without raising the risk of a **false positive** (approving a quote that does
not actually match) on clean text.

Non-goals: changing the VERBATIM/CLOSE/FABRICATED thresholds; changing the
quote-floor calibration; RECAP-document OCR handling (opinions only for now);
re-architecting the matcher.

## Background: what we're borrowing, and what we already have

lq-ai's `normalize(text, *, was_ocrd=False)` has two layers:

1. **Always-on layer** — smart quotes → straight, collapse whitespace, canonicalize
   CRLF, strip. **CV already does all of this** in `_normalize_quote_text` (and the
   haystack-cleaning step in `check_quotes`), and does *more*: CV also strips
   bracketed alterations (`[T]`→`t`) and ellipses, which are legal-quote
   conventions lq-ai lacks. **We borrow nothing from this layer.**
2. **OCR-conditional layer** — three substitutions, applied only when `was_ocrd`:
   - `rn` → `m` when preceded by a word char: `(?<=\w)rn`
   - `O` → `0` when adjacent to a digit: `(?<=\d)O|O(?=\d)`
   - `l` → `1` when adjacent to a digit: `(?<=\d)l|l(?=\d)`

   **This is the entire borrow.** Each rule is one-directional and applied to
   *both* the brief quote and the opinion text, so clean words containing
   mid-word `rn` ("attorney", "return", "concern", "modern") collapse to the
   *same* target on both sides — clean-text matching is unaffected. The residual
   false-positive risk (a brief that wrote the m-form where the opinion genuinely
   has the rn-form, or vice-versa) is exactly what the OCR gate eliminates.

### Threshold reconciliation

lq-ai compares with `rapidfuzz.fuzz.ratio` against a strict threshold of **95**
(0–100 scale). CV compares with `difflib.SequenceMatcher.ratio()` on a **0–1
scale**, with VERBATIM > 0.85 and CLOSE ≥ 0.6 (`check_quotes`). CV's verbatim cut
is *more forgiving* than lq-ai's. We therefore **keep CV's thresholds unchanged**;
the OCR rules simply raise the ratio on a true match against OCR'd text, nudging
it from CLOSE up toward VERBATIM (or FABRICATED up toward CLOSE). No threshold or
quote-floor change is needed.

## Design decision: the OCR gate (the crux)

**Gate on CourtListener's `extracted_by_ocr` boolean** (confirmed present on the
`opinions` endpoint). Apply the OCR rules **only** when that flag is `True` for
the opinion backing a claim. When the flag is unknown — RECAP-document text,
user-supplied / prepared-pairs opinion files, legacy workdirs — **default to
`False`** (rules off). This is the cautious default: we never apply OCR
substitutions unless CL authoritatively tells us the source was OCR'd.

Rejected alternatives:
- *Apply unconditionally* (no gate): simpler, and the symmetric-collapse property
  makes it mostly safe, but leaves a nonzero false-positive risk on clean
  opinions. The false-positive constraint is paramount here, so we gate.
- *Heuristic OCR detection from the text*: no authoritative signal; risks both
  missing real OCR and falsely triggering on clean text.

### Plumbing the flag from CL → workdir → checker

The flag lives on the opinion JSON at fetch time but the quote checker reads only
the downloaded opinion *file*. Three small, localized changes carry it across:

1. **`client.py` — capture.** In both `get_opinion_text_with_metadata` variants
   (sync + async) and their `_resolve_opinion_text_with_metadata` helpers, when a
   sub-opinion yields usable text, read `opinion.get("extracted_by_ocr")` from
   that same opinion JSON and add `"extracted_by_ocr": bool | None` to the
   returned metadata dict. RECAP/docket and PDF-fallback return paths set it to
   `None` (unknown). No extra API calls — the opinion JSON is already fetched.
2. **`proposition_pipeline.py::_download_opinion` — persist a sidecar.** After a
   successful text/HTML download, write `opinions/<base>.meta.json` containing at
   least `{"extracted_by_ocr": <bool|null>, "source_url": <url>}`. The sidecar
   sits beside the opinion file using the same `<base>` stem. (Sidecar chosen over
   a new claims.csv/verification_results.csv column so the CSV schema — and the
   `run_check_quotes` output the eval grader consumes — is untouched.)
3. **`proposition_pipeline.py::check_quotes` — read + apply.** For each claim's
   `opinion_file`, look up the sibling `<stem>.meta.json`; treat
   `extracted_by_ocr is True` as the gate. Missing sidecar / missing key / `null`
   → gate off. Pass the resolved boolean into `_best_match_with_passage`.

## Matcher changes (`_best_match_with_passage` and helpers)

### New pure function: `_normalize_ocr_confusions(text: str) -> str`

The borrow, ported verbatim in spirit:

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

Properties (enforced by tests): one rule per pair, one-directional, **idempotent**
(`f(f(t)) == f(t)`), and a no-op on clean text that lacks the gated patterns.

### Ordering constraint (the subtle bug to avoid)

The `O`→`0` and `l`→`1` rules are **case-sensitive** (capital `O`, lowercase `l`).
CV lowercases text before matching (`_normalize_quote_text(needle).lower()`,
`haystack.lower()`). OCR normalization must therefore run **before** `.lower()`,
or those two rules silently never fire. Pipeline per side: raw → existing
normalization → **OCR normalization (case-preserving)** → `.lower()`.

### Where it applies in `_best_match_with_passage`

`_best_match_with_passage` gains an `ocr: bool = False` parameter (default `False`
keeps every existing caller and test unchanged).

- **Needle:** `needle_norm = _normalize_quote_text(needle)`; if `ocr`, then
  `_normalize_ocr_confusions(...)`; then `.lower()`.
- **Haystack for *comparison*:** because `rn`→`m` is length-*changing*, it would
  break the 1:1 position mapping the passage extractor relies on. So we keep the
  original `haystack` for passage extraction and build a **separate**
  OCR-normalized comparison string only when `ocr` is true: apply
  `_normalize_ocr_confusions` to the haystack *before* lowercasing, and run the
  exact-substring check and the sliding-window `SequenceMatcher` against that
  string. The matched start index found in the normalized string is used to slice
  a passage from the **original** haystack. Length drift from `rn`→`m` is bounded
  by the number of `rn` occurrences before the match; the extractor already adds
  ±80 chars of context and trims to sentence boundaries, so a small offset is
  cosmetically tolerable and never changes the verdict. When `ocr` is false,
  behavior is byte-for-byte identical to today (no normalized copy built).

`check_quotes` passes the gate boolean through to `_best_match_with_passage`.

## Backward compatibility (consumer constraint)

- **`run_check_quotes` return shape (`QuoteCheckStats`) is unchanged.** No new
  fields, no removed fields. The eval grader keeps working as-is.
- **`quote_check` / `quote_check_worst` / `quote_floor` CSV columns are
  unchanged** in shape. Values can *improve* on OCR'd opinions (a quote that was
  CLOSE/FABRICATED may now be VERBATIM/CLOSE) — that is the intended behavior
  change, not a schema change.
- **No new required column.** The OCR flag travels in a per-opinion sidecar file,
  invisible to existing CSV consumers.
- **New artifact:** `opinions/<base>.meta.json` sidecar files. Additive; consumers
  that don't read them are unaffected.

If a later need arises to expose per-quote "was OCR-normalized" provenance, it
would be an *additive optional key* on the `quote_check` entry dict and a separate
decision — out of scope here.

## Testing (cassette-backed, offline)

New tests in `tests/` (alongside `test_proposition_pipeline.py`):

1. **Per-rule unit tests** for `_normalize_ocr_confusions`:
   - `rn`→`m` fires mid-word ("modern"→"modem", "concern"→"concem") and **not**
     word-initially ("rnage" unchanged).
   - `O`→`0` fires only adjacent to a digit ("O5"→"05", "5O"→"50"); "Office"
     unchanged.
   - `l`→`1` fires only adjacent to a digit ("l5"→"15", "5l"→"51"); "liability"
     unchanged.
2. **Idempotence:** `f(f(t)) == f(t)` over a representative input set.
3. **Clean-text non-regression:** for inputs lacking any gated pattern, `f(t) == t`;
   and at the matcher level, a clean-text quote/opinion pair yields the *same*
   ratio with `ocr=True` and `ocr=False` (symmetric collapse).
4. **OCR true-positive at the matcher level:** an opinion haystack containing the
   OCR'd form ("modem" rendered as "modern") + a brief needle with the true form
   ("modem") scores VERBATIM with `ocr=True`, but below VERBATIM with `ocr=False`
   (demonstrates the fix and that the gate matters).
5. **Gate plumbing:** `check_quotes` applies the rules iff the sidecar says
   `extracted_by_ocr: true`; with no sidecar / `false` / `null`, behavior is
   unchanged. `client` metadata dict carries `extracted_by_ocr` from the opinion
   JSON (mocked response).
6. **Passage extraction:** with `ocr=True` and an `rn`→`m` collapse before the
   match, the extracted passage still comes from the original haystack and is
   coherent (no index-out-of-range, sane bounds).

### Regression guard

Run the existing suite — especially the real-citation benchmark guard and the
existing quote-check tests — and confirm **no regressions**. The `ocr=False`
default path must remain byte-for-byte identical to current behavior.

## Version & changelog

- Bump `pyproject.toml` `0.4.0` → `0.5.0`.
- Add a CHANGELOG entry under `v0.5.0` describing the OCR-conditional quote
  normalization, the `extracted_by_ocr` plumbing + sidecar, and the explicit
  backward-compat guarantee for `run_check_quotes` output, so the
  `us-legal-research` eval grader can pin the upgraded CV.

## Files touched

| File | Change |
|------|--------|
| `src/citation_verifier/client.py` | Capture `extracted_by_ocr` into the metadata dict (sync + async resolvers). |
| `src/citation_verifier/proposition_pipeline.py` | `_normalize_ocr_confusions`; `ocr` param on `_best_match_with_passage`; write meta sidecar in `_download_opinion`; read sidecar + gate in `check_quotes`. |
| `tests/test_proposition_pipeline.py` (or a new `tests/test_ocr_normalization.py`) | Per-rule, idempotence, clean-text non-regression, true-positive, gate, passage tests. |
| `pyproject.toml` | Version `0.4.0` → `0.5.0`. |
| `CHANGELOG.md` | `v0.5.0` entry. |
| `CLAUDE.md` | One-line note on the OCR gate + sidecar under the `check-quotes` / `_best_match_with_passage` description. |
