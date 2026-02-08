# Citation Verifier

Verify legal citations against [CourtListener](https://www.courtlistener.com/). Catches hallucinated case citations from AI tools by checking whether a citation actually exists and belongs to the case it claims to.

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
| `NOT_FOUND` | No match, or citation belongs to a different case |

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
pip install -e .
```

## Configuration

Create a `.env` file in the project root:

```
COURTLISTENER_API_TOKEN=your_token_here
```

Get a free API token at https://www.courtlistener.com/ (Profile > API keys).

The token is required for the Citation Lookup API (Step 1). The Search API (Steps 2-3) works without a token but is rate-limited.

## Usage

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

## Supported Citation Formats

- Standard reporters: `576 U.S. 644`, `999 F.3d 1`, `584 S.W.2d 716`
- WestLaw: `2018 WL 301424`
- California style: `(2022) 76 Cal.App.5th 685`
- Docket numbers: `Case No. 24-cv-9429`, `No. 17-cv-12676`, shorthand `C15-1228-JCC`
- Federal parentheticals: `(S.D.N.Y. 2018)`, `(M.D. Ala. July 6, 2018)`
- Reversed date/court: `(Feb. 5, 2026 SDNY)`
- Complex party names: `Macy's Texas, Inc. v. D.A. Adams & Co.`
- Abbreviations auto-expanded: `Cnty.` → `County`, `Dep't` → `Department`, `Corp.` → `Corporation`, etc.

## Project Structure

```
src/citation_verifier/
  models.py      -- VerificationStatus, ParsedCitation, CandidateMatch, VerificationResult
  court_map.py   -- Court abbreviation -> CourtListener ID mapping (federal courts)
  parser.py      -- Citation parsing (eyecite + regex fallbacks)
  client.py      -- CourtListener API wrapper with rate limiting
  verifier.py    -- Core three-step verification pipeline
  __main__.py    -- CLI interface
```

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
