# case.dev API Exploration

**Date:** 2026-03-06 (updated 2026-03-07)

Exploratory tests of the [case.dev](https://case.dev) legal API to evaluate whether it could serve as a fast first-pass in our citation verification pipeline, reducing CourtListener API calls.

## API Endpoints Tested

| Endpoint | Purpose | Auth | Cost |
|----------|---------|------|------|
| `POST /legal/v1/verify` | Verify citations exist in CL | Bearer token (`CASEDEV_API_KEY`) | Free |
| `POST /legal/v1/citations` | Bluebook citation parser | Bearer token | Free |
| `POST /legal/v1/docket` | Docket search and lookup | Bearer token | Free |

## Files

| File | Description |
|------|-------------|
| **Test scripts** | |
| `test_verify.py` | Tests `verify()` and `citations()` endpoints against 20 Kettering citations |
| `test_waterfall.py` | Waterfall pipeline: case.dev verify -> name check -> CL fallback (Kettering + Valve) |
| `test_docket.py` | Tests `docket()` endpoint (search + lookup) against 3 RECAP cases from Valve |
| `batch_verify_50.py` | Sends 50 unverified citations from `citations_for_review.csv` to verify |
| **Results** | |
| `test_narrative.md` | Full narrative of all tests, findings, and assessment |
| **Raw responses** | |
| `verify_response.json` | Raw verify() response (20 Kettering citations) |
| `citations_response.json` | Raw citations() response |
| `waterfall_kettering.json` | Waterfall summary stats for Kettering |
| `waterfall_valve.json` | Waterfall summary stats for Valve |
| `docket_response.json` | Raw docket endpoint responses |
| `batch_verify_50_response.json` | Raw response from 50-citation batch |
| `waterfall_batch_50.py` | Runs waterfall (name matching + CL fallback) on cached case.dev results |
| `waterfall_batch_50.json` | Waterfall results for the 50-citation batch |
| `test_cl_batch_50.py` | Sends same 50 citations to CL citation-lookup as batch comparison |
| `cl_batch_50_response.json` | Raw CL citation-lookup batch response |

## The Waterfall

The key outcome of this exploration is the **waterfall pipeline** — using case.dev as a fast first pass with our name-matching logic on top, falling back to CourtListener only for unresolved citations.

```
  All citations (batch text block)
            |
    case.dev verify()          <-- single API call, ~6-10s, free
            |
    +-------+--------+
    |                |
  found           not found / no reporter cite
    |                |
  name match?     CL fallback (Steps 1-3)
    |                ~1-10s per citation
  +-----+-----+
  |           |
VERIFIED   POSSIBLE_MATCH
           (hallucination signal)
```

**Result:** Saves ~70% of CL API calls. See `test_narrative.md` for full details and per-citation breakdowns.

## Running

Requires `CASEDEV_API_KEY` in `.env`.

```bash
# Verify + citations endpoints
python scratch/casedev/test_verify.py

# Waterfall pipeline (also needs CL token)
python scratch/casedev/test_waterfall.py

# Docket endpoint
python scratch/casedev/test_docket.py
```
