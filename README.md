# Citation Verifier

Verify legal citations against [CourtListener](https://www.courtlistener.com/). Catches hallucinated case citations from AI tools by checking whether a citation actually exists and belongs to the case it claims to.

## Try It

**[Verify and Retrieve](https://citation-verifier.replit.app/)** -- paste citations, verify them against CourtListener, and download the opinion text or PDFs. No installation needed.

## How It Works

```
Input: "Smith v. Jones, 2018 WL 301424 (S.D.N.Y. Mar. 5, 2018)"
  |
  +-- Step 1: Citation Lookup API (fast, precise)
  |     Found + name matches? -> VERIFIED + CourtListener link
  |     Found but different case? -> NOT FOUND ("citation belongs to ...")
  |
  +-- Step 1b: Adjacent Page Fallback
  |     Try pages +/-1 and +/-2 for off-by-one starting pages
  |
  +-- Step 2: Opinion Search (fuzzy fallback)
  |     Search by case name + court + date range
  |     Retries without court filter if no results
  |     Score results by name/court/date/citation similarity
  |
  +-- Step 3: RECAP Search (docket/PACER fallback)
        Search by docket number first (if available),
        then by case name (with/without court filter).
        Query docket-entries API for documents near the cited date
```

### Statuses

| Status | Meaning |
|--------|---------|
| `VERIFIED` | Citation lookup found the exact case |
| `LIKELY_REAL` | Strong fuzzy match (>= 85% confidence) |
| `POSSIBLE_MATCH` | Partial match found (>= 40% confidence) |
| `NOT_FOUND` | No match found in any search step |

### Diagnostics

When a citation isn't fully verified, the tool explains why:

- **"Citation exists but belongs to a different case"** -- the reporter citation is real but for a different case (common AI hallucination pattern)
- **"Name mismatch"** / **"Name differs"** -- case name similarity issues
- **"Court mismatch"** -- cited court doesn't match the found case
- **"Date mismatch"** / **"Date close"** -- year discrepancies
- **"Reporter citation could not be confirmed"** -- CourtListener doesn't have the citation on file
- **"Found in RECAP"** -- case found in PACER docket data, not the opinions database
- **"We found a possible docket match"** -- docket found but no specific document verified

## Installation

```bash
pip install -e .          # core library + CLI
pip install -e ".[web]"   # adds web app (FastAPI, uvicorn)
```

## Configuration

Create a `.env` file in the project root:

```
COURTLISTENER_API_TOKEN=your_token_here
```

Get a free API token at https://www.courtlistener.com/ (Profile > API keys).

The token is required for the Citation Lookup API (Step 1). The Search API (Steps 2-3) works without a token but is rate-limited.

## Usage

### Web App

The quickest way to use the tool — no installation required for end users.

```bash
pip install -e ".[web]"
python web/app.py
# Open http://localhost:8000
```

The app has three pages:

- **Retrieve** (`/`) -- Verify citations and download the matched opinion text or PDFs from CourtListener. Quick search + deep search workflow.
- **QC** (`/qc`) -- Review verification batches and assign QC status (internal use).
- **Debug** (`/debug`) -- Detailed verification with confidence scores, diagnostics, CSV export, and FLP flagging.

Results stream via SSE as each citation completes. Batches capped at 50 citations.

**Public mode:** Set `MODE=public` to expose only the Retrieve page (used for the hosted Replit deployment). Debug and QC routes return 404.

### Command Line

```bash
# Single citation
python -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"

# Multiple citations
python -m citation_verifier "Case One, 576 U.S. 644 (2015)" "Case Two, 999 F.3d 1 (2021)"

# From a file (one citation per line)
python -m citation_verifier --file citations.txt

# JSON output
python -m citation_verifier --json "Obergefell v. Hodges, 576 U.S. 644 (2015)"
```

Exit code is `1` if any citation is `NOT_FOUND` (useful for scripting/CI).

### Python API

```python
from citation_verifier import CitationVerifier

verifier = CitationVerifier()
result = verifier.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")

print(result.status)          # VerificationStatus.VERIFIED
print(result.matched_url)     # https://www.courtlistener.com/opinion/2812209/...
print(result.diagnostics)     # []
```

#### Pre-parsed citations (batch pipelines)

When processing PDFs with eyecite, you can pass pre-parsed citations directly to avoid the lossy string round-trip that drops court, month, and day metadata:

```python
from eyecite import get_citations
from eyecite.models import FullCaseCitation
from citation_verifier import CitationVerifier
from citation_verifier.parser import parsed_citation_from_eyecite

text = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
cite = next(c for c in get_citations(text) if isinstance(c, FullCaseCitation))
parsed = parsed_citation_from_eyecite(cite, raw_text=text)

verifier = CitationVerifier()
result = verifier.verify(text, parsed=parsed)
```

## Supported Citation Formats

- Standard reporters: `576 U.S. 644`, `999 F.3d 1`, `584 S.W.2d 716`
- WestLaw: `2018 WL 301424`
- California style: `(2022) 76 Cal.App.5th 685`
- Docket numbers: `Case No. 24-cv-9429`, `No. 17-cv-12676`, shorthand `C15-1228-JCC`
- Federal parentheticals: `(S.D.N.Y. 2018)`, `(M.D. Ala. July 6, 2018)`
- Reversed date/court: `(Feb. 5, 2026 SDNY)`
- Complex party names: `Macy's Texas, Inc. v. D.A. Adams & Co.`
- Abbreviations auto-expanded: `Cnty.` → `County`, `Dep't` → `Department`, `Corp.` → `Corporation`, etc.

## Testing

```bash
# Unit tests (mocked, no API calls)
pytest tests/test_verifier.py -v

# False negative regression (hits real API, needs token)
pytest tests/test_false_negatives.py -v

# Parser diagnostics (eyecite vs our parser comparison)
pytest tests/test_parser_diagnostics.py -v

# CourtListener API limitation workarounds
pytest tests/test_cl_api_issues.py -v
```

`test_verifier.py` has 103 unit tests covering the full pipeline: citation lookup, name matching, adjacent page fallback, opinion search, RECAP search, court corroboration, scoring and weight redistribution, docket number normalization, abbreviation expansion, surname matching, the eyecite factory function, and the pre-parsed citation path. All API calls are mocked. `test_async_verifier.py` has 30 tests verifying sync/async behavior parity.

`test_false_negatives.py` runs against the real CourtListener API using the corpus in `tests/data/known_real_citations.json` (5 cases). `tests/data/known_fake_citations.json` contains 8 confirmed hallucinations for reference.

## Project Structure

```
src/citation_verifier/
  models.py          -- Data structures (statuses, parsed citations, results)
  court_map.py       -- Court abbreviation -> CourtListener ID mapping (federal courts)
  state_reporter_map.py -- Regional reporter -> state court mapping
  name_matcher.py    -- Multi-factor case name similarity scoring
  text_cleaner.py    -- Contamination phrase removal from extracted names
  parser.py          -- Citation parsing (eyecite + regex fallbacks + eyecite factory)
  client.py          -- CourtListener API wrapper with rate limiting
  cache.py           -- File-based verification result cache
  verifier.py        -- Core three-step verification pipeline
  __main__.py        -- CLI interface

web/
  app.py             -- FastAPI application (SSE streaming, public mode)
  static/get.html    -- Retrieve page (homepage, vanilla HTML/CSS/JS)
  static/index.html  -- Debug page (detailed verification)
  static/qc.html     -- QC review page

tests/
  test_verifier.py             -- Unit tests (mocked API)
  test_false_negatives.py      -- Regression tests (live API)
  test_parser_diagnostics.py   -- Parser comparison diagnostics
  test_cl_api_issues.py        -- CL API limitation tests
  extract_citations_batch.py   -- Batch PDF citation extraction
  verify_sample_citations.py   -- Sample and verify extracted citations
  data/                        -- Test fixtures and results

scratch/                       -- Working notes and utility scripts (not part of the tool)
```

## Contributing

This project is built on the [Free Law Project](https://free.law/)'s infrastructure:

- [CourtListener](https://www.courtlistener.com/) -- the legal research platform and API we verify citations against
- [eyecite](https://github.com/freelawproject/eyecite) -- the citation extraction library that powers our parser

## Scoring

Fuzzy match confidence is a weighted score:

| Component | Weight | Notes |
|-----------|--------|-------|
| Case name | 50% | SequenceMatcher similarity; compares defendants for "State v." style cases |
| Court | 20% | Exact match on CourtListener court ID |
| Date | 20% | Full credit for exact date; granular scoring for same month, same year, +/- 1 year |
| Docket no. | 5% | Normalized comparison (strips division prefix, judge suffix, expands shorthand) |
| Citation | 5% | Reporter citation or WL number found in CourtListener record |

RECAP docket-only matches (no specific document found) receive a 40% score discount.
