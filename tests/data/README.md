# Test Data for False Negative/Positive Detection

## Overview

This directory contains structured test corpora for:
1. **False negatives** - Real citations we should successfully verify
2. **False positives** - Fake/hallucinated citations we should reject
3. **Parser diagnostics** - Understanding eyecite vs our parser

## Files

### `known_real_citations.json`

Corpus of verified real citations for regression testing. Each entry:

```json
{
  "citation": "Full citation text",
  "expected_cluster_id": 123456,  // Optional: CL cluster ID if known
  "category": "abbreviation_normalization",  // Type of test case
  "notes": "Why this is a test case / what it tests"
}
```

**Categories:**
- `standard_reporter` - Standard U.S. reporter citations (576 U.S. 644)
- `abbreviation_normalization` - Case names with Cnty., Dep't, Corp., etc.
- `docket_number_shorthand` - C15-1228 → 15-cv-1228 conversion
- `recap_with_exact_date` - RECAP cases requiring exact date matching
- `judge_suffix_stripping` - Docket numbers with -JCC, -DCC suffixes
- `multi_defendant_case` - Different caption in CL than cited
- `adjacent_page` - Off-by-one page number (cited 560, case starts 559)
- `california_style` - (2022) 76 Cal.App.5th 685
- `westlaw_citation` - 2018 WL 4407750

**Adding new cases:**
1. Manually verify the citation is real (find it on CourtListener)
2. Get the cluster ID from the URL
3. Add to the JSON file with appropriate category
4. Run tests to verify: `pytest tests/test_false_negatives.py -v`

### `known_fake_citations.json` (TODO)

Corpus of known-fake citations (AI hallucinations, fabricated cases) that we should reject.

```json
{
  "citation": "Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)",
  "category": "hallucinated_case_name",
  "notes": "Completely fabricated case name with plausible citation format",
  "expected_status": "NOT_FOUND"
}
```

**Categories (planned):**
- `hallucinated_case_name` - Fake names with real citation format
- `wrong_name_real_citation` - Real citation but wrong case name
- `wrong_court` - Real case but wrong court
- `future_date` - Citation dated in the future
- `invalid_reporter` - Non-existent reporter abbreviation
- `out_of_range_page` - Page number beyond reporter volume limits

## Usage

### Running false negative tests

```bash
# All known-real citations
pytest tests/test_false_negatives.py -v

# Specific category
pytest tests/test_false_negatives.py -v -k abbreviation

# Show coverage report
pytest tests/test_false_negatives.py::test_categories_coverage -v -s
```

### Parser diagnostics

```bash
# Compare eyecite vs our parser
pytest tests/test_parser_diagnostics.py::test_eyecite_vs_our_parser -v -s

# Abbreviation handling
pytest tests/test_parser_diagnostics.py::test_abbreviation_extraction -v -s

# WestLaw citation handling
pytest tests/test_parser_diagnostics.py::test_westlaw_citations -v -s
```

## Contributing Test Cases

### From `cases_to_investigate.md`

When you identify a false negative:
1. Verify it's truly real (find on CourtListener manually)
2. Add to `known_real_citations.json` with cluster ID
3. Categorize appropriately
4. Note what made it a false negative (what we fixed)

### From user reports

If users report citations that fail:
1. Manually verify on CourtListener
2. If real, add to `known_real_citations.json`
3. If fake, add to `known_fake_citations.json`
4. Use to drive improvements

## Test Philosophy

### False Negatives (Priority 1)
Real cases MUST be found. Every false negative is:
- A missed verification opportunity
- Potential user frustration
- Evidence of parser/search gaps

Track aggressively, fix systematically.

### False Positives (Priority 2)
Fake cases MUST be rejected. Every false positive is:
- A credibility risk
- Potential user harm (citing fake cases)
- Evidence of verification weakness

Less common than false negatives (AI hallucinations are rare in practice), but critical when they occur.

### Parser Gaps
When our regex fallbacks catch what eyecite misses, that's potential upstream contribution. Track for eventual eyecite PRs.

## Reporting to FLP

### Parser improvements (eyecite)
When we have 10+ examples of a pattern eyecite misses:
1. Review `test_parser_diagnostics.py` output
2. Create minimal test case
3. Submit issue/PR to https://github.com/freelawproject/eyecite

### Data quality issues
When we find citation/search problems in CourtListener:
1. Document the pattern (case exists but not searchable, etc.)
2. Collect cluster IDs and examples
3. Submit issue to https://github.com/freelawproject/courtlistener

## Maintenance

Review and update quarterly:
- Remove cases that no longer exist in CL
- Update cluster IDs if CL changes
- Add new categories as patterns emerge
- Prune duplicates
