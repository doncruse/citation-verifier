# Citation Verifier - Development Guide

## Project Overview

Legal citation verification tool that checks citations against CourtListener's API. Designed to catch AI-hallucinated case citations. Python 3.10+, installed as editable package (`pip install -e .`).

## Architecture

Three-step verification pipeline in `src/citation_verifier/verifier.py`:

1. **Citation Lookup API** (`/api/rest/v4/citation-lookup/`) - Resolves reporter citations (e.g. `576 U.S. 644`). If found, verifies case name matches before returning VERIFIED. If the citation exists but belongs to a different case, returns NOT_FOUND immediately.

2. **Opinion Search** (`/api/rest/v4/search/?type=o`) - Fuzzy search by case name, court, and date range (+/- 1 year). Retries without court filter if no results.

3. **RECAP Search** (`/api/rest/v4/search/?type=r`) - Searches PACER docket data. When a docket is found, queries the **docket-entries API** (`/api/rest/v4/docket-entries/`) filtered by the cited year to find the actual opinion/order document. Important: RECAP `dateFiled` is the case filing date, NOT the opinion date -- always use `entry_date_filed` from individual docket entries.

## Key Design Decisions

- **Multi-factor name matching** (`name_matcher.py`): 4-factor weighted score adapted from CaseStrainer:
  - 0.25 * sequence_similarity (SequenceMatcher)
  - 0.30 * word_overlap (Jaccard index on word sets)
  - 0.20 * substring_similarity (containment check)
  - 0.25 * key_word_similarity (filtered meaningful words)
  - Abbreviated name boost: when short name (≤4 words) is a subset of long name, boosts to 0.85
  - Used in `_score_match()` for the case name component (50% weight)

- **Citation lookup name check** (`_names_match_citation_lookup`): Separate, lenient surname-containment approach. The citation is already proven to exist, so this only rejects truly wrong names (fabricated name + real citation number). Handles common-prefix cases (State v., United States v.) by comparing defendants.

- **Fuzzy search name check** (`_names_match`): Stricter than citation lookup. Compares *defendants* for common-prefix cases to avoid false positives from shared prefixes inflating SequenceMatcher scores.

- **RECAP docket-only matches** get a 0.6x score discount and use "possible" (not "likely") match language, since a docket match without a specific document is weaker evidence.

- **Diagnostics**: The `diagnostics` list on `VerificationResult` explains *why* something wasn't verified. Date/citation diagnostics are suppressed for docket-only RECAP matches (redundant). Court/name diagnostics are always kept.

- **Scoring weights**: Base weights: case name 50% (multi-factor), court 20%, date 20% (granular: exact day/month/year), docket number 5%, reporter/WL citation 5%. **Weight redistribution**: when `parsed.court` or `parsed.year` is None (citation text didn't include that info), the weight is redistributed proportionally to evaluable components. This prevents WestLaw-only citations (no court parenthetical) from being capped at 80%.

- **Reporter citation comparison**: Normalizes spacing around periods ("Cal. Rptr. 3d" matches "Cal.Rptr.3d") for the 5% citation component.

- **Parser**: Forked `eyecite` (rlfordon/eyecite branch `fix-pdf-metadata-parsing`) with PDF parsing improvements: apostrophe preservation in case names, single newline = space (PDF line breaks), consecutive newlines = paragraph break. Main library handles standard reporter citations. Regex fallbacks handle WestLaw (`2018 WL 301424`), California style (`(2022) 76 Cal.App.5th`), reversed parentheticals (`(Feb. 5, 2026 SDNY)`), and complex party names with commas/ampersands. Docket number junk (`Case No. 24-cv-9429`) is stripped from parsed case names.

- **Abbreviation normalization**: 47 Indigo Book terms (87% real-world coverage) expanded client-side in `parser.py:_normalize_case_name()` to work around CourtListener search not matching abbreviations. Categories: government entities, organizations, positions, education, medical, business, geographic, religious. Curly/smart apostrophes (`\u2018`/`\u2019`) are normalized to straight apostrophes before matching, so "Dep\u2019t" correctly expands to "Department".

- **Docket number normalization**: Strips division prefix (`2:`), judge suffix (`-JCC`), expands shorthand (`C15` -> `15-cv`, `CR15` -> `15-cr`), strips leading zeros.

- **State reporter mapping** (`state_reporter_map.py`): Maps regional reporters (P., N.W., S.W., N.E., A., So., S.E.) to possible state court IDs. Used when eyecite doesn't return a court ID.

- **Contamination phrase removal** (`text_cleaner.py`): Removes legal signals ("see", "e.g."), procedural phrases ("de novo", "holding that"), and court references from extracted case names. Used in the PDF extraction pipeline.

- **RECAP state court skip**: RECAP is federal PACER data only. Verifier uses `is_federal_court()` to gate all 3 RECAP API call paths (docket search, docket lookup, docket-entries), saving API calls on state court citations.

- **429 retry handling** (`client.py`): All 4 API endpoints parse `wait_until` ISO-8601 timestamp from CL response body (per FLP #6895), fall back to Retry-After header, retry up to 3 times with exponential backoff.

## Files

### Core library (`src/citation_verifier/`)

| File | Purpose | Dependencies |
|------|---------|--------------|
| `models.py` | Data structures (enums, dataclasses) | None |
| `court_map.py` | Court abbreviation -> CL ID mapping (135 federal courts), federal court check | None |
| `state_reporter_map.py` | Regional reporter -> state court mapping | None |
| `name_matcher.py` | Multi-factor case name similarity (adapted from CaseStrainer) | None |
| `text_cleaner.py` | Contamination phrase removal (adapted from CaseStrainer) | None |
| `parser.py` | Citation parsing (eyecite + regex + abbreviation normalization) | models, eyecite |
| `client.py` | CourtListener API wrapper (rate limiting, 15s timeout, 429 retry) | requests, python-dotenv |
| `verifier.py` | Core 3-step pipeline (with insufficient-data guard, RECAP state skip) | All above |
| `__main__.py` | CLI | verifier |

### Test infrastructure (`tests/`)

| File | Purpose |
|------|---------|
| `test_verifier.py` | 54 comprehensive unit tests (mocked API calls) |
| `test_false_negatives.py` | Regression tests against real CourtListener API |
| `test_parser_diagnostics.py` | eyecite vs our parser comparison |
| `test_cl_api_issues.py` | Documents and tests CL API limitations |
| `extract_citations_batch.py` | Non-interactive batch PDF extraction (PDF cleaning + eyecite + text_cleaner) |
| `extract_hallucination_citations.py` | Interactive PDF extraction with hallucination keyword classifier |
| `verify_sample_citations.py` | Sample and verify citations from extracted results |
| `analyze_not_found_citations.py` | PDF context analysis for NOT_FOUND citations |
| `data/known_real_citations.json` | 5-case real citation regression corpus |
| `data/known_fake_citations.json` | 8-case confirmed hallucination corpus |
| `data/cl_api_issues.json` | 5 documented CL API issues with workarounds |
| `data/citations_extracted_raw.json` | 592 extracted citations from 19 hallucination opinion PDFs |
| `data/verification_sample_50.json` | Previous verification run (stale - needs re-run) |
| `data/hallucination_opinions/` | 19 PDFs of judicial opinions discussing AI-fabricated citations |
| `cases_to_investigate.md` | Informal tracking of edge cases found during testing |

## Environment

### Virtual Environment Setup

**IMPORTANT: Always activate the virtual environment before running any commands.**

```bash
# First-time setup (already done)
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install pytest

# Every new terminal session
cd /Users/fordon.4/Projects/citation-verifier
source venv/bin/activate  # You should see (venv) in your prompt
```

### API Configuration

- API token in `.env` file: `COURTLISTENER_API_TOKEN=...`
- `.env` is in `.gitignore` -- never commit it
- Get token at: https://www.courtlistener.com/ → Profile → API Keys
- All API requests have a 15-second timeout and 1-second rate limiting

## Common Pitfalls

- **CourtListener API response structure**: Citation lookup returns `[{citation, clusters: [...]}]`, not a flat list. Always access `lr["clusters"]` to get actual case data.
- **Court IDs**: `eyecite` sometimes returns CL court IDs directly (e.g. `"almd"`) instead of abbreviations. `lookup_court_id()` handles both.
- **State courts**: The court map only covers federal courts. State court IDs from eyecite are compared via direct string match. Use `state_reporter_map.py` to infer state from regional reporters.
- **RECAP docket param**: The `docket` parameter on the search API is unreliable. Use `q` with a quoted string + client-side filter instead (see `client.py` line 120).
- **Windows console**: Avoid Unicode emoji in CLI output -- use ASCII status labels like `[OK]`, `[?]`, `[X]`.

## Testing

```bash
# Unit tests (mocked, no API calls)
pytest tests/test_verifier.py -v

# False negative regression (hits real API, needs token)
pytest tests/test_false_negatives.py -v

# Parser diagnostics
pytest tests/test_parser_diagnostics.py -v -s

# CL API issue workarounds
pytest tests/test_cl_api_issues.py -v

# Manual single citation
python -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"

# Batch extraction from PDFs
python tests/extract_citations_batch.py

# Sample verification
python tests/verify_sample_citations.py --sample-size 50
```

## Session State (2026-02-09 night - continued)

### What was completed in this session

1. **Forked eyecite fixes working**
   - Cloned user's fork (rlfordon/eyecite) to /Users/fordon.4/Projects/eyecite
   - Branch: `fix-pdf-metadata-parsing`
   - Fix 1: Apostrophe truncation in `_process_case_name()` — regex `\b[a-z]\w*\b` treated apostrophes as word boundaries, stripping "t" from "Dep't", "s" from "People's", etc. Fixed with negative lookbehind `(?<!['\u2019])\b[a-z]\w*\b`
   - Fix 2: ParagraphToken boundary in `match_on_tokens()` — single newlines now treated as spaces (PDF line breaks), consecutive newlines still stop scanning (real paragraph break)
   - Fix 3: Apostrophe added to character classes in SHORT_CITE_ANTECEDENT_REGEX, SUPRA_ANTECEDENT_REGEX, PRE_FULL_CITATION_REGEX
   - All 52 eyecite tests pass (193 HyperscanTokenizer subtests skip — optional C extension)
   - Pushed to rlfordon/eyecite branch fix-pdf-metadata-parsing
   - Installed in citation-verifier venv as editable (`pip install -e /Users/fordon.4/Projects/eyecite`)

2. **Removed _repair_orphaned_parentheticals workaround**
   - Deleted from extract_citations_batch.py — eyecite's ParagraphToken fix handles this natively
   - Removed get_court_by_paren import

3. **Added API 429 retry handling**
   - New `_request_with_retry()` method in client.py
   - Parses `wait_until` ISO-8601 timestamp from CL response body per freelawproject/courtlistener#6895
   - Falls back to Retry-After header, retries up to 3 times
   - All four endpoints now use this method

4. **Added PDF text cleaning pipeline**
   - `_clean_pdf_text()` function in extract_citations_batch.py runs before eyecite
   - Smart quote/apostrophe normalization (U+2018, U+2019, U+201C, U+201D → ASCII)
   - PACER/ECF header stripping (two format variants)
   - Court seal watermark garble line removal
   - Single newline → space normalization (belt-and-suspenders with eyecite fork)
   - eyecite's built-in `underscores` and `inline_whitespace` cleaners
   - Result: 536 → 592 citations extracted (+10%), 2 new courts, 2 new years, 31 case names improved

5. **Added insufficient-data guard in verifier**
   - Returns NOT_FOUND early when both court and year are missing from parsed citation
   - Added "Low confidence" diagnostic when court or date unavailable

6. **"In re" abbreviated name boost fix**
   - name_matcher.py: Skip the 0.85 floor boost for "In re" cases (too generic for subset matching)

7. **Expanded known_fake_citations.json to 8 entries**
   - Added: TIG Ins. Co. v. Carter, Gallagher v. Wilton Enterprises, Gibbs v. Wright
   - Added: Shell Petroleum N.V. v. Republic of Costa Rica, Butler Motors Inc. v. Benosky
   - Previous: Bloomberg, Hogan, Head (from Gonzalez v. Texas Taxpayers)

8. **Skip RECAP for state courts**
   - Added `is_federal_court()` helper in court_map.py
   - RECAP search (3 API call paths) now gated on federal court check
   - Saves 1-3 API calls per state court citation

9. **Investigated FLP codebase for PDF/OCR tools**
   - eyecite has `clean_text()` with built-in cleaners (underscores, inline_whitespace, all_whitespace) — now using these
   - FLP's Doctor microservice uses pdftotext + Tesseract OCR — overkill for our use case
   - juriscraper has harmonize()/clean_string() — we already have equivalent in text_cleaner.py

### What needs to happen next

#### Priority 1: Verification run in progress
- Running with seed 42, sample 50 — results pending
- Will validate all eyecite fork fixes + PDF cleaning + insufficient-data guard + RECAP state skip

#### Priority 2: RECAP document selection bug
- Dehghani v. Castro found document 23/2 (Exhibit, 2025-03-14) instead of document 35 (correct one)
- Issue in `_pick_best_recap_doc` date sorting logic — needs investigation

#### Priority 3: CL fuzzy search limitations
- Fibertext spelling mismatch: "Fibertext" (cited) vs "Fibertex" (actual) — single character difference defeats CL fuzzy search
- Docket number also differs (20-20720-Civ vs 1:20-cv-20718)
- No easy fix — semantic search might help (see Ideas Backlog)

#### Priority 4: Upstream eyecite PR
- Holding until we've used the fork more
- Need to verify all fixes stable across more verification runs

#### Priority 5: Run false negative regression tests
```bash
pytest tests/test_false_negatives.py -v
```
Check that 5 known real citations still verify correctly with all the changes.

## Known CL API Limitations (see `tests/data/cl_api_issues.json`)

1. **Search abbreviation matching** (HIGH) - "Cnty." doesn't match "County". Workaround: client-side normalization. FLP aware (#3089, #3367).
2. **Docket parameter unreliable** (HIGH) - RECAP `docket` param ignored. Workaround: use `q` with quoted string.
3. **Case name variations** (MEDIUM) - CL stores different defendant than cited. Workaround: docket search + fuzzy matching.
4. **Missing citations field** (MEDIUM) - Some cases have empty citations. Workaround: fall through to opinion/RECAP search.
5. **State court coverage gaps** (LOW) - Some state courts incomplete. No workaround.

## FLP Contributions (see `flp_contributions.md`)

1. **Abbreviation priority analysis** - READY to submit as comment on FLP #3367
2. **Data quality issues** - DRAFT, collecting more examples (need 10+)
3. **Docket param issue** - DECLINED (related FLP work already in progress)
4. **Parser improvements** - DECLINED (eyecite handles everything we need)

## Ideas Backlog

### Semantic Search (CourtListener Citegeist)
CL's search API supports semantic search via `semantic=true` parameter (GET) or POST with pre-computed embeddings. Only available for `type=o` (case law). Could help with:
- Abbreviation mismatches without client-side normalization
- Name variations where keyword search fails entirely (e.g., "Estate of Elkins v. Pelayo" vs "Elkins v. California Highway Patrol")
- Multi-defendant cases where CL stores a different caption
- Best fit: new fallback step between current keyword opinion search (Step 2) and RECAP search (Step 3), triggered only when keyword search returns nothing or low-confidence results. Would cost one extra API call only on failures.
- See: https://www.courtlistener.com/help/api/rest/search/#semantic-search

### Justia Diagnostic Script (NOT for production)
Build a one-off script (`tests/compare_justia_coverage.py`) that takes NOT_FOUND citations and checks Justia to distinguish:
1. Real hallucinations (neither CL nor Justia finds it)
2. CL data gaps (Justia finds, CL doesn't — report to FLP)
3. Our search bugs (CL has it, we're not finding it — fix query)
NOT to be added to production pipeline — we are CL-centric and want FLP to benefit.

### Known Fake Citations Corpus
Build `tests/data/known_fake_citations.json` from the hallucination opinion PDFs. Categories planned: hallucinated_case_name, wrong_name_real_citation, wrong_court, future_date, invalid_reporter, out_of_range_page. See `tests/data/README.md` for schema.

### INSUFFICIENT_DATA Status
When a citation is missing both court and date, we currently return NOT_FOUND with a diagnostic ("Insufficient data to verify"). Consider adding a dedicated `INSUFFICIENT_DATA` status to `VerificationStatus` so these are clearly distinguished from actual failed lookups. Court-only-missing is also problematic — a name+year match on generic names like "In re Wright" is too weak to be meaningful (55% POSSIBLE_MATCH on the wrong case). Options:
- Add `INSUFFICIENT_DATA` enum value and return it when court is missing (not just both court+date)
- Or cap score / block match return when court is missing
- Key insight: WL citation "years" come from the volume number, not a court parenthetical — they're weaker evidence than proper `(E.D. Tenn. 2020)` year data
- Root cause is often the extraction pipeline (stale data, PDF line breaks splitting parentheticals). Re-running extraction with current code fixes many cases.

### Short Cite Handling
eyecite may support short cites (e.g., "M.G., 566 P.3d at 146-147") -- investigate. Would need to resolve back to the full citation earlier in the document.

### Upstream Contributions
- Monitor FLP #3367 for abbreviation synonym progress
- Collect 10+ data quality examples before reporting
- If we find eyecite parsing gaps, contribute to https://github.com/freelawproject/eyecite
- Ask CaseStrainer friend about licensing (MIT recommended)
