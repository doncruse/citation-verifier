# Citation Verifier - Development Guide

## Project Overview

Legal citation verification tool that checks citations against [CourtListener](https://www.courtlistener.com/)'s API. Designed to catch AI-hallucinated case citations. Python 3.10+, installed as editable package (`pip install -e .`).

Uses a forked [eyecite](https://github.com/freelawproject/eyecite) (rlfordon/eyecite branch `fix-pdf-metadata-parsing`) with PDF parsing improvements: apostrophe preservation in case names, single newline = space (PDF line breaks), consecutive newlines = paragraph break. Installed as editable: `pip install -e /Users/fordon.4/Projects/eyecite`.

## Architecture

Three-step verification pipeline in `src/citation_verifier/verifier.py`:

1. **Citation Lookup API** (`/api/rest/v4/citation-lookup/`) - Resolves reporter citations (e.g. `576 U.S. 644`). If found, verifies case name matches before returning VERIFIED. If the citation exists but belongs to a different case, returns NOT_FOUND immediately.

2. **Opinion Search** (`/api/rest/v4/search/?type=o`) - Fuzzy search by case name, court, and date range (+/- 1 year). Retries without court filter if no results.

3. **RECAP Search** (`/api/rest/v4/search/?type=r`) - Searches PACER docket data. When a docket is found, queries the **docket-entries API** (`/api/rest/v4/docket-entries/`) filtered by the cited year to find the actual opinion/order document. Important: RECAP `dateFiled` is the case filing date, NOT the opinion date -- always use `entry_date_filed` from individual docket entries.

## Key Design Decisions

- **Multi-factor name matching** (`name_matcher.py`): 4-factor weighted score (sequence similarity 0.25, word overlap 0.30, substring 0.20, key words 0.25). Abbreviated name boost to 0.85 when short name is a subset of long name (skipped for "In re" cases).

- **Two name-matching thresholds**: `_names_match_citation_lookup` is lenient (surname containment — citation already proven to exist). `_names_match` is stricter (used for fuzzy search). Both compare defendants for common-prefix cases (State v., United States v.).

- **Scoring weights**: case name 50%, court 20%, date 20%, docket number 5%, reporter/WL citation 5%. Weights redistribute proportionally when court or year is missing from the citation. RECAP docket-only matches get a 0.6x score discount.

- **Parser** (`parser.py`): eyecite handles standard reporters. Regex fallbacks handle WestLaw (`2018 WL 301424`), California style (`(2022) 76 Cal.App.5th`), reversed parentheticals (`(Feb. 5, 2026 SDNY)`), and complex party names. Docket number junk is stripped from case names. `parsed_citation_from_eyecite()` builds a `ParsedCitation` directly from an eyecite `FullCaseCitation`, avoiding the lossy string round-trip that drops court, month, and day fields.

- **Pre-parsed citation path**: `verify()` accepts an optional `parsed: ParsedCitation` parameter. When provided, the internal `parse_citation()` call is skipped. This lets batch pipelines pass eyecite-extracted metadata (court, month, day) without information loss. All existing callers (CLI, tests) are unaffected.

- **Abbreviation normalization**: 47 Indigo Book terms expanded client-side in `parser.py:_normalize_case_name()` to work around CL search not matching abbreviations. Smart apostrophes normalized to straight before matching.

- **Docket number normalization**: Strips division prefix (`2:`), judge suffix (`-JCC`), expands shorthand (`C15` -> `15-cv`), strips leading zeros.

- **RECAP state court skip**: RECAP is federal PACER data only. `is_federal_court()` gates all RECAP API calls.

- **429 retry handling** (`client.py`): Parses `wait_until` ISO-8601 timestamp from CL response body, falls back to Retry-After header, retries up to 3 times.

## Files

### Core library (`src/citation_verifier/`)

| File | Purpose |
|------|---------|
| `models.py` | Data structures (enums, dataclasses) |
| `court_map.py` | Court abbreviation -> CL ID mapping (135 federal courts), `is_federal_court()` |
| `state_reporter_map.py` | Regional reporter -> state court mapping |
| `name_matcher.py` | Multi-factor case name similarity (adapted from CaseStrainer) |
| `text_cleaner.py` | Contamination phrase removal (adapted from CaseStrainer) |
| `parser.py` | Citation parsing (eyecite + regex + abbreviation normalization + eyecite factory) |
| `client.py` | CourtListener API wrapper (rate limiting, 15s timeout, 429 retry) |
| `verifier.py` | Core 3-step pipeline (with insufficient-data guard, RECAP state skip) |
| `__main__.py` | CLI |

### Tests and tools (`tests/`)

| File | Purpose |
|------|---------|
| `test_verifier.py` | 62 unit tests (mocked API calls) |
| `test_false_negatives.py` | Regression tests against real CourtListener API |
| `test_parser_diagnostics.py` | eyecite vs our parser comparison |
| `test_cl_api_issues.py` | Documents and tests CL API limitations |
| `extract_citations_batch.py` | Batch PDF citation extraction (reads from `scratch/hallucination_opinions/`) |
| `extract_hallucination_citations.py` | Hallucination keyword classifier (imported by batch extractor) |
| `verify_from_csv.py` | Iterative CSV-based verification (master workflow — see below) |
| `verify_sample_citations.py` | Sample and verify citations from JSON extraction results (ad-hoc exploration) |
| `data/known_real_citations.json` | 5-case real citation regression corpus |
| `data/known_fake_citations.json` | 8-case confirmed hallucination corpus |
| `data/cl_api_issues.json` | 5 documented CL API issues with workarounds |
| `data/results/` | Timestamped extraction and verification output (gitignored) |

### Other

| File | Purpose |
|------|---------|
| `scratch/` | Working notes, utility scripts, hallucination opinion PDFs (not part of the tool) |
| `scratch/citations_for_review.csv` | Master CSV — 515 citations with verification results and QC status |
| `scratch/verification_quality_log.md` | Per-run QC breakdowns and observations |
| `scratch/flp_contributions.md` | Drafted contributions to Free Law Project (with submission checklists) |
| `scratch/TODO.md` | Bug/feature tracking with prioritized items |

## Environment

**Always activate the virtual environment before running any commands.**

```bash
source venv/bin/activate
```

### API Configuration

- API token in `.env` file: `COURTLISTENER_API_TOKEN=...`
- `.env` is in `.gitignore` -- never commit it
- Get token at: https://www.courtlistener.com/ -> Profile -> API Keys
- All API requests have a 15-second timeout and 1-second rate limiting

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

## Iterative Verification Workflow

The master state file is `scratch/citations_for_review.csv`. Each row tracks a citation through extraction → verification → human QC.

### CSV columns

The CSV has 25 columns: 18 original extraction columns + 7 verification/QC columns:

| Column | Values | Purpose |
|--------|--------|---------|
| `v_status` | `VERIFIED`, `LIKELY_REAL`, `POSSIBLE_MATCH`, `NOT_FOUND`, `SKIPPED`, (empty) | Verifier result. Empty = not yet run. |
| `v_confidence` | 0.0–1.0, (empty) | Confidence score |
| `v_url` | URL or empty | CourtListener match URL for QC |
| `v_matched_name` | case name or empty | What CL matched (for QC comparison) |
| `v_git_hash` | short hash or empty | Code version that produced this result |
| `qc_status` | `approved`, `rerun`, `duplicate`, `ignore`, `investigate`, `data`, (empty) | Human QC decision. Empty = not yet reviewed. |
| `qc_notes` | free text | Human notes |

### qc_status vocabulary

- **approved** — verified result is correct, no action needed
- **rerun** — needs re-verification after code fix (cleared on next run)
- **duplicate** — duplicate citation in the CSV, skip in future runs
- **ignore** — not worth verifying (e.g. short cite, junk extraction)
- **investigate** — QC issue that may require a code fix (tracked in `scratch/TODO.md`)
- **data** — CL data gap to follow up with FLP (tracked in `scratch/flp_contributions.md` §6)

### One iteration

```bash
# 1. Run verification on next batch
python tests/verify_from_csv.py --sample-size 50

# 2. QC review (in conversation)
#    - Review NOT_FOUND and POSSIBLE_MATCH from JSON sidecar
#    - Update qc_status and qc_notes in CSV
#    - Items marked "investigate" → add to scratch/TODO.md
#    - Items marked "data" → add to scratch/flp_contributions.md §6

# 3. After code fixes, re-verify affected rows
#    (set qc_status=rerun on rows to re-check)
python tests/verify_from_csv.py --rerun-only
```

### Post-run checklist

After running `verify_from_csv.py`, prompt the user to:
1. Review NOT_FOUND and POSSIBLE_MATCH items from the JSON sidecar
2. Set `qc_status` on reviewed rows in the CSV
3. Update `scratch/TODO.md` with any new `investigate` items
4. Update `scratch/flp_contributions.md` §6 with any new `data` items
5. Update `scratch/verification_quality_log.md` with run summary

### CLI reference

```bash
python tests/verify_from_csv.py [options]
  --csv PATH          (default: scratch/citations_for_review.csv)
  --sample-size N     (default: 50)
  --seed N            (default: random)
  --all               verify all pending, no sampling
  --rerun-only        only rows where qc_status=rerun
  --dry-run           show what would be verified, don't call API
```

## Common Pitfalls

- **CL API response structure**: Citation lookup returns `[{citation, clusters: [...]}]`, not a flat list. Always access `lr["clusters"]`.
- **Court IDs**: eyecite sometimes returns CL court IDs directly (e.g. `"almd"`) instead of abbreviations. `lookup_court_id()` handles both.
- **State courts**: The court map only covers federal courts. State court IDs from eyecite are compared via direct string match. Use `state_reporter_map.py` to infer state from regional reporters.
- **RECAP docket param**: The `docket` parameter on the search API is unreliable. Use `q` with a quoted string + client-side filter instead.
- **Windows console**: Avoid Unicode emoji in CLI output -- use ASCII status labels like `[OK]`, `[?]`, `[X]`.
