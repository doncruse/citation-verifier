# Citation Verifier - Development Guide

## Project Overview

Legal citation verification tool that checks citations against CourtListener's API. Designed to catch AI-hallucinated case citations. Python 3.10+, installed as editable package (`pip install -e .`).

## Architecture

Three-step verification pipeline in `src/citation_verifier/verifier.py`:

1. **Citation Lookup API** (`/api/rest/v4/citation-lookup/`) - Resolves reporter citations (e.g. `576 U.S. 644`). If found, verifies case name matches before returning VERIFIED. If the citation exists but belongs to a different case, returns NOT_FOUND immediately.

2. **Opinion Search** (`/api/rest/v4/search/?type=o`) - Fuzzy search by case name, court, and date range (+/- 1 year). Retries without court filter if no results.

3. **RECAP Search** (`/api/rest/v4/search/?type=r`) - Searches PACER docket data. When a docket is found, queries the **docket-entries API** (`/api/rest/v4/docket-entries/`) filtered by the cited year to find the actual opinion/order document. Important: RECAP `dateFiled` is the case filing date, NOT the opinion date -- always use `entry_date_filed` from individual docket entries.

## Key Design Decisions

- **Case name matching**: Uses `_names_match()` for citation lookup verification. Compares *defendants* (not full names) for common-prefix cases like "State v." or "United States v." to avoid false positives from shared prefixes inflating SequenceMatcher scores.

- **RECAP docket-only matches** get a 0.6x score discount and use "possible" (not "likely") match language, since a docket match without a specific document is weaker evidence.

- **Diagnostics**: The `diagnostics` list on `VerificationResult` explains *why* something wasn't verified. Date/citation diagnostics are suppressed for docket-only RECAP matches (redundant). Court/name diagnostics are always kept.

- **Parser**: `eyecite` handles standard reporter citations. Regex fallbacks handle WestLaw (`2018 WL 301424`), California style (`(2022) 76 Cal.App.5th`), reversed parentheticals (`(Feb. 5, 2026 SDNY)`), and complex party names with commas/ampersands. Docket number junk (`Case No. 24-cv-9429`) is stripped from parsed case names.

## Files

| File | Purpose | Dependencies |
|------|---------|--------------|
| `models.py` | Data structures (enums, dataclasses) | None |
| `court_map.py` | Court abbreviation -> CL ID mapping | None |
| `parser.py` | Citation parsing | models, eyecite |
| `client.py` | CourtListener API wrapper | requests, python-dotenv |
| `verifier.py` | Core pipeline | All above |
| `__main__.py` | CLI | verifier |

## Environment

- API token in `.env` file: `COURTLISTENER_API_TOKEN=...`
- `.env` is in `.gitignore` -- never commit it
- All API requests have a 15-second timeout and 1-second rate limiting

## Common Pitfalls

- **CourtListener API response structure**: Citation lookup returns `[{citation, clusters: [...]}]`, not a flat list. Always access `lr["clusters"]` to get actual case data.
- **Court IDs**: `eyecite` sometimes returns CL court IDs directly (e.g. `"almd"`) instead of abbreviations. `lookup_court_id()` handles both.
- **State courts**: The court map only covers federal courts. State court IDs from eyecite are compared via direct string match.
- **Windows console**: Avoid Unicode emoji in CLI output -- use ASCII status labels like `[OK]`, `[?]`, `[X]`.

## Testing

```bash
# Known-real citation (should be VERIFIED)
python -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"

# Known-fake case name with real citation (should be NOT_FOUND)
python -m citation_verifier "Fakename v. Nobody, 999 F.3d 1 (S.D.N.Y. 2020)"

# WestLaw citation in RECAP
python -m citation_verifier "flycatcher v. affable, Case No. 24-cv-9429, 2026 WL 103589130 (Feb. 5, 2026 SDNY)"

# California-style citation
python -m citation_verifier "Estrada v. Royalty Carpet Mills, Inc. (2022) 76 Cal.App.5th 685"
```
