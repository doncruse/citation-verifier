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

- **Parser**: `eyecite` handles standard reporter citations. Regex fallbacks handle WestLaw (`2018 WL 301424`), California style (`(2022) 76 Cal.App.5th`), reversed parentheticals (`(Feb. 5, 2026 SDNY)`), and complex party names with commas/ampersands. Docket number junk (`Case No. 24-cv-9429`) is stripped from parsed case names.

- **Abbreviation normalization**: 47 Indigo Book terms (87% real-world coverage) expanded client-side in `parser.py:_normalize_case_name()` to work around CourtListener search not matching abbreviations. Categories: government entities, organizations, positions, education, medical, business, geographic, religious. Curly/smart apostrophes (`\u2018`/`\u2019`) are normalized to straight apostrophes before matching, so "Dep\u2019t" correctly expands to "Department".

- **Docket number normalization**: Strips division prefix (`2:`), judge suffix (`-JCC`), expands shorthand (`C15` -> `15-cv`, `CR15` -> `15-cr`), strips leading zeros.

- **State reporter mapping** (`state_reporter_map.py`): Maps regional reporters (P., N.W., S.W., N.E., A., So., S.E.) to possible state court IDs. Used when eyecite doesn't return a court ID.

- **Contamination phrase removal** (`text_cleaner.py`): Removes legal signals ("see", "e.g."), procedural phrases ("de novo", "holding that"), and court references from extracted case names. Used in the PDF extraction pipeline.

## Files

### Core library (`src/citation_verifier/`)

| File | Purpose | Dependencies |
|------|---------|--------------|
| `models.py` | Data structures (enums, dataclasses) | None |
| `court_map.py` | Court abbreviation -> CL ID mapping (135 federal courts) | None |
| `state_reporter_map.py` | Regional reporter -> state court mapping | None |
| `name_matcher.py` | Multi-factor case name similarity (adapted from CaseStrainer) | None |
| `text_cleaner.py` | Contamination phrase removal (adapted from CaseStrainer) | None |
| `parser.py` | Citation parsing (eyecite + regex + abbreviation normalization) | models, eyecite |
| `client.py` | CourtListener API wrapper (rate limiting, 15s timeout) | requests, python-dotenv |
| `verifier.py` | Core 3-step pipeline | All above |
| `__main__.py` | CLI | verifier |

### Test infrastructure (`tests/`)

| File | Purpose |
|------|---------|
| `test_verifier.py` | 54 comprehensive unit tests (mocked API calls) |
| `test_false_negatives.py` | Regression tests against real CourtListener API |
| `test_parser_diagnostics.py` | eyecite vs our parser comparison |
| `test_cl_api_issues.py` | Documents and tests CL API limitations |
| `extract_citations_batch.py` | Non-interactive batch PDF extraction (uses eyecite + text_cleaner) |
| `extract_hallucination_citations.py` | Interactive PDF extraction with hallucination keyword classifier |
| `verify_sample_citations.py` | Sample and verify citations from extracted results |
| `analyze_not_found_citations.py` | PDF context analysis for NOT_FOUND citations |
| `data/known_real_citations.json` | 5-case real citation regression corpus |
| `data/known_fake_citations.json` | 3-case confirmed hallucination corpus (from Gonzalez v. Texas Taxpayers) |
| `data/cl_api_issues.json` | 5 documented CL API issues with workarounds |
| `data/citations_extracted_raw.json` | 536 extracted citations from 19 hallucination opinion PDFs |
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

## Session State (2026-02-09 evening - continued)

### What was completed in this session

1. **Fixed Python environment setup**
   - Created virtual environment (`venv/`)
   - Installed all dependencies (requests, eyecite, python-dotenv, courts-db, etc.)
   - Installed pytest for testing
   - Installed pdfplumber for PDF extraction scripts
   - Added virtual environment activation instructions to CLAUDE.md
   - Added pytest and pdfplumber to pyproject.toml as optional dev dependencies

2. **Fixed API token issue**
   - Discovered leading "y" typo in .env file causing "Invalid token" errors
   - Corrected token, verified with curl and CLI
   - All API calls now working correctly

3. **Completed Priority 1-2-5: Verification pipeline tested and validated**
   - ✅ **Unit tests**: All 50 tests in test_verifier.py passed — multi-factor name matching works correctly with no regressions
   - ✅ **Re-ran verification**: 26/35 citations VERIFIED (74%), 1 POSSIBLE_MATCH (3%), 6 NOT_FOUND (17%), 2 SKIPPED (6%)
   - ✅ **False negative tests**: All 7 tests passed — known real citations still verify correctly with new name matcher
   - ✅ **Parser diagnostics**: All 3 tests passed — parser handling all citation formats correctly
   - ✅ **CL API issues**: 5 passed, 3 skipped — documented workarounds still valid

4. **Key findings from verification run**
   - **Two confirmed fabrications caught**: "Hogan v. AT&T, Inc., 917 F. Supp. 1275 (1994)" and "Surety Co. v. Superior Court, 153, 6 Cal.App.3d 467 (1984)" are fabricated names with real citations (verifier correctly identified mismatch)
   - **Four need manual investigation**: "Farhan v. 2715 NMA LLC, 161 F.4th 475 (2025)", "In re A.S., 319 Kan. 396", "Bloomberg L.P. v. Bd. of Govs. of the Fed. Reserve Sys., 649 F. 3d 651", "Ramirez v. Humala, No. 24-cv-242, 2025 WL 1384161 (2025)"
   - **Note**: F.4th IS a valid reporter (Federal Reporter, Fourth Series) — initial analysis was incorrect

5. **Manual investigation of 6 NOT_FOUND citations (completed)**
   - [1] Farhan v. 2715 NMA LLC, 161 F.4th 475 (2025) → **FALSE NEGATIVE** — real case in CL (empty citations field + LLC expansion broke search)
   - [2] In re A.S., 319 Kan. 396 → **FALSE NEGATIVE** — real case in CL (parser returned None for "In re" case names)
   - [3] Bloomberg L.P. v. Bd. of Govs. of the Fed. Reserve Sys., 649 F. 3d 651 → **CONFIRMED HALLUCINATION** — court says "do not exist"
   - [4] Hogan v. AT&T, Inc., 917 F. Supp. 1275 (1994) → **CONFIRMED HALLUCINATION** — fabricated name with real citation
   - [5] Surety Co. v. Superior Court, 153, 6 Cal.App.3d 467 (1984) → **PDF EXTRACTION BUG** — real case "Aetna Cas. & Surety Co. v. Superior Court, 153 Cal. App. 3d 476" but line numbers contaminated parsing
   - [6] Ramirez v. Humala, No. 24-cv-242, 2025 WL 1384161 → **PARTY NAME VARIATION** — found in RECAP as "Ramirez v. El Tri MX Restaurant & Bar Corp"

6. **Fixed 3 bugs identified from investigation**
   - **Abbreviation over-expansion** (parser.py): Removed business entity suffix expansions (LLC, Inc., Corp., Co., Ltd.) that broke CL search matching. CL stores these abbreviated; expanding "LLC" → "Limited Liability Company" prevented matches. Kept Cnty., Dept., Bd., etc. (CL stores these expanded).
   - **"In re" case name parsing** (parser.py): Added fallback regex for "In re" / "Ex parte" / "Matter of" cases that lack "v." — parser now correctly extracts case names like "In re A.S."
   - **PDF line number contamination** (extract_citations_batch.py): Added `_strip_line_numbers()` that detects court document line numbers (1-28 in left margin) and strips them before eyecite processes the text. Joins stripped lines with spaces so citations spanning lines parse correctly.

7. **Integrated state_reporter_map into search pipeline (completed)**
   - Fixed bug in `get_states_for_reporter()` — normalization was broken, always returned empty list
   - Built comprehensive state reporter mapping (470 reporters) using Free Law Project's courts-db:
     - All 50 states supreme courts (Kan., Cal., N.Y., etc.)
     - All appellate courts (Kan. App., Cal. App., etc.)
     - All series (2d, 3d, 4th, 5th)
   - Created `scripts/generate_state_reporter_map.py` for maintainability
   - Integrated into verifier: when reporter maps to single state (e.g., "Kan." → "kan"), uses as court filter in searches
   - Results: Farhan: NOT_FOUND → POSSIBLE_MATCH (64%). In re A.S.: would improve if citation existed in CL.

8. **Re-ran extraction + verification with all fixes (completed)**
   - Extraction: 536 citations extracted (stable, same as before)
   - Verification results (seed 42, same sample):
     - **Baseline**: 26 VERIFIED (74%), 1 POSSIBLE_MATCH (3%), 6 NOT_FOUND (17%), 2 SKIPPED
     - **After fixes**: 26 VERIFIED (74%), **4 POSSIBLE_MATCH (11%)**, **3 NOT_FOUND (9%)**, 2 SKIPPED
   - **3 citations improved** from NOT_FOUND to POSSIBLE_MATCH:
     1. Farhan v. 2715 NMA LLC (LLC expansion fix)
     2. In re A.S., 319 Kan. 396 ("In re" parser + state reporter map)
     3. Two new California cases from PDF line number stripping (Zurich American, National Steel Products)
   - **Remaining NOT_FOUND (3)**: All confirmed issues (Bloomberg/Hogan = hallucinations, Ramirez = party name variation)
   - **Success rate**: 30/33 valid citations found (91%) — only hallucinations and party variations remain as NOT_FOUND

9. **Fixed low-confidence scoring for correct matches (completed)**
   - Root cause: `_score_match()` awarded 0 points for court/date when `parsed.court`/`parsed.year` was None, penalizing citations without court parentheticals (e.g., WestLaw-only citations like "2017 WL 3877860")
   - **Fix 1: Weight redistribution** — when court/date are not parseable from the citation text, their weight is redistributed proportionally to evaluable components (name, docket, reporter)
   - **Fix 2: Curly apostrophe normalization** — `\u2019` (right single quotation mark) now normalized to straight apostrophe in both parser.py and name_matcher.py, so "Dep\u2019t" correctly expands to "Department"
   - **Fix 3: "Educ." abbreviation** — added to both parser and name matcher abbreviation maps
   - **Fix 4: Period-separated initials** — name_matcher now collapses "L.P." to "LP" before comparison, preventing false token splits
   - **Fix 5: Reporter citation spacing** — "Cal. Rptr. 3d" now matches "Cal.Rptr.3d" via space normalization around periods
   - **Fix 6: Opinion/RECAP search uses `q=` instead of `case_name=`** — confirmed correct; `q=` does fuzzy search (finds "Kadince" when cited as "Kadince, Inc.") while `case_name=` does exact match. False positive risk is mitigated by downstream name matching and court corroboration.
   - Results: Pointe Wholesale 0.675->0.833, Moore v. Hillman 0.750->0.933, Noland 0.500->0.917, Anonymous 0.502->0.933
   - All 54 unit tests pass

10. **Second verification run (seed 123) and manual investigation**
   - 21 VERIFIED (60%), 5 POSSIBLE_MATCH (14%), 6 NOT_FOUND (17%), 3 SKIPPED (9%)
   - Confirmed bug fixes working: "In re A.S." now VERIFIED, "Surety Co. v. Superior" now VERIFIED
   - User manually investigated all POSSIBLE_MATCH and NOT_FOUND results
   - Confirmed fakes: Shell Petroleum N.V. v. Republic of Costa Rica (wrong_name_real_citation), Motors Inc. v. Benosky (wrong page - cited 857, actual 304)
   - Confirmed false negatives: Garner v. Kadince (in CL but not found), Fibertext Corp (spelling "Fibertext" vs "Fibertex")

11. **Started known_fake_citations.json**
   - Created with 3 entries from Gonzalez v. Texas Taxpayers (Bloomberg, Hogan, Head)
   - Still need to add: Shell Petroleum (from Flowz Digital), Motors/Benosky (from Wilcox v. Gingrich)

### What needs to happen next

#### Priority 1: Expand known_fake_citations.json
Add confirmed fakes from second verification run:
- Shell Petroleum N.V. v. Republic of Costa Rica, 608 F. Supp. 2d 269 (wrong_name_real_citation) — court says "unable to locate"
- Butler Motors, Inc. v. Benosky, 181 N.E.3d 857 (wrong_page_number) — actual citation is 181 N.E.3d 304

#### Priority 2: Re-run verification with scoring fixes
All the scoring/search improvements need to be validated with a fresh sample run.

#### Priority 3: Remaining bugs from manual investigation
- **Incomplete party name extraction**: "Motors, Inc. v. Benosky" — should be "Butler Motors, Inc. v. Benosky" (PDF extraction lost "Butler")
- **Parser miss**: "Bradley v. Wallrad, No. 1:06 cv 246, 2006 WL 1133220" treated as short cite but has a case name — eyecite didn't capture it
- **State case RECAP search**: Should skip RECAP for state cases (RECAP is federal PACER data only) — wastes API calls
- **Wrong RECAP document selection**: Dehghani v. Castro found document 23/2 (Exhibit, 2025-03-14) instead of document 35 (correct one) — date sorting issue in `_pick_best_recap_doc`
- **Fibertext spelling mismatch**: "Fibertext" (cited) vs "Fibertex" (actual) — single character difference defeats CL fuzzy search. Docket number also differs (20-20720-Civ vs 1:20-cv-20718)

#### Priority 4: Run false negative regression tests
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

### Short Cite Handling
eyecite may support short cites (e.g., "M.G., 566 P.3d at 146-147") -- investigate. Would need to resolve back to the full citation earlier in the document.

### Upstream Contributions
- Monitor FLP #3367 for abbreviation synonym progress
- Collect 10+ data quality examples before reporting
- If we find eyecite parsing gaps, contribute to https://github.com/freelawproject/eyecite
- Ask CaseStrainer friend about licensing (MIT recommended)
