# Extraction Pipeline Fixes - Summary

## Date: 2026-02-09

## Problem

The extraction pipeline had 3 critical bugs causing all citations to be classified as "uncertain" and generating garbage "None v." citations:

1. **Context extraction failed** — searched for eyecite's `repr()` string instead of reporter text, so all contexts were empty and the hallucination keyword classifier was blind
2. **Citation text was repr garbage** — stored `"FullCaseCitation('411 F.3d 1006', groups={...})"` instead of clean text
3. **Reconstruction created "None v."** — when eyecite returned None for plaintiff, literally wrote `"None v. Defendant"`

## Fixes Applied

### Fix 1: `extract_citations_batch.py` — Clean text storage

**Before:**
```python
citation_text = str(citation)  # repr() garbage
citation_data = {
    'citation': citation_text,
    'case_name': f"{plaintiff} v. {defendant}",  # literal "None v." when None
    ...
}
```

**After:**
```python
# Build reporter text for context searching
reporter_text = f"{volume} {reporter} {page}"

# Handle "In re" cases properly
if not plaintiff and defendant:
    case_name = f"In re {defendant}"
elif plaintiff and defendant:
    case_name = f"{plaintiff} v. {defendant}"

# Build clean citation string
clean_citation = f"{case_name}, {reporter_text}"
if year:
    clean_citation += f" ({year})"

citation_data = {
    'citation': clean_citation,  # Clean human-readable text
    'reporter_text': reporter_text,  # For PDF context lookup
    'plaintiff': plaintiff,
    'defendant': defendant,
    ...
}
```

### Fix 2: `extract_hallucination_citations.py` — Context extraction

**Before:**
```python
def classify_citation(citation, citation_text, full_text):
    context = get_citation_context(citation_text, full_text)
    # citation_text was repr(), never found in PDF → empty context
```

**After:**
```python
def classify_citation(citation, citation_text, full_text):
    # citation_text is now reporter portion (e.g., "411 F.3d 1006")
    context = get_citation_context(citation_text, full_text)
    # Actually finds the citation in PDF text
```

Updated docstrings to clarify that `citation_text` should be the reporter portion for searching.

### Fix 3: `verify_sample_citations.py` — PDF-based reconstruction

Added `extract_citation_from_pdf()` helper that:
1. Searches PDF for reporter text
2. Grabs 200 chars before to capture case name
3. Handles "In re" pattern: `In re ([^,]+), {reporter}`
4. Handles standard "X v. Y" pattern: `([A-Z][^\n,]+) v. ([^,\n]+), {reporter}`
5. Strips parenthetical aliases like `(Suday I)` from defendant names

Added logic to skip short cites (no case name) rather than trying to verify them.

## Results

### Before Fixes
```
Extracted 536 total citations:
  - 0 likely fake
  - 0 likely real
  - 536 uncertain (100%)

Sample verification had 5 "None v." citations:
  - None v. Daou Systems, Inc.
  - None v. Vioxx Prods. Liability Litig.
  - None v. Suday I)
  - None v. None
  - None v. Officers
```

### After Fixes
```
Extracted 536 total citations:
  - 102 likely fake (19%)
  - 94 likely real (18%)
  - 340 uncertain (63%)

Sample verification (seed=99):
  - 0 "None v." citations
  - 1 short cite properly skipped
  - "In re Daou Systems, Inc." properly extracted
  - All citations have clean, human-readable text
```

## Edge Cases Now Handled

1. **"In re" cases** — eyecite sets plaintiff=None, defendant exists. We detect this and format as `"In re {defendant}"`

2. **Short cites** — No case name at all (e.g., `aff'd, 437 Md. 47`). These get skipped with a clear reason.

3. **Parenthetical aliases** — Case names like `Suday v. Suday (Suday I)` are cleaned to `Suday v. Suday`

4. **Long defendant names** — When eyecite loses the plaintiff due to long party names, PDF reconstruction can recover it

5. **Context-based classification** — Now that context extraction works, the hallucination keyword classifier properly identifies likely_fake citations (keywords like "nonexistent", "fabricated", "AI-generated")

## Files Modified

- `tests/extract_citations_batch.py` — Lines 60-76 (citation reconstruction)
- `tests/extract_hallucination_citations.py` — Lines 62-154 (docstring updates)
- `tests/verify_sample_citations.py` — Added `extract_citation_from_pdf()` helper (lines 52-96), updated `verify_citations_batch()` to handle reconstruction and skipping (lines 99-156)

## Testing

Re-ran extraction:
```bash
python3 tests/extract_citations_batch.py
```

Result: 102 likely_fake, 94 likely_real (vs 0/0 before)

Re-ran verification sample:
```bash
python3 tests/verify_sample_citations.py --sample-size 20 --seed 99
```

Result: 0 "None v." citations, 1 properly skipped, clean output

## Next Steps

1. **Manual review** — Review `citations_extracted_raw.json` to validate the 102 likely_fake classifications
2. **Build known_fake corpus** — Curate the high-confidence likely_fake citations into `known_fake_citations.json`
3. **Test edge cases** — Run verification on the 5 original "None v." citations to confirm they now resolve correctly
4. **False negatives** — Investigate the 8 NOT_FOUND from the sample — are they real hallucinations or verifier gaps?

## Known Limitations

- **PDF reconstruction is heuristic** — relies on regex patterns, may miss unusual citation formats
- **Short cites skipped** — we don't attempt to resolve them back to full citations
- **State courts** — CourtListener coverage gaps mean some real state court citations will appear as NOT_FOUND
