# case.dev API Test Results

**Date:** 2026-03-06
**Test data:** 20 unique citations from Kettering v. Collier brief

## verify() Endpoint

Single API call with all 20 citations as a text block. Free, instant response.

**Summary:** 22 citation matches found (parallel cites counted separately), 20 verified, 1 not_found, 1 multiple_matches.

### Comparison with Our Pipeline

| Citation | case.dev | Our pipeline | Notes |
|----------|----------|-------------|-------|
| Simpson (2021-Ohio-2131) | verified | VERIFIED | Match |
| Angelini (2012-Ohio-2136) | verified | VERIFIED | Match |
| Heskett (2006-Ohio-6900) | verified | VERIFIED | Match |
| Iqbal (556 U.S. 662) | verified | VERIFIED | Match |
| Twombly (550 U.S. 544) | verified | VERIFIED | Match |
| Hecht (66 Ohio St. 3d 458) | verified | VERIFIED | Match |
| Hecht (613 N.E.2d 585) | verified (parallel) | -- | Parallel cite, separate result |
| Surace (25 Ohio St. 3d 229) | verified | VERIFIED | Match |
| Surace (495 N.E.2d 939) | verified (parallel) | -- | Parallel cite, separate result |
| **Carter (72 Ohio App.3d 553)** | **verified (as Stull)** | **POSSIBLE_MATCH** | **case.dev doesn't flag name mismatch** |
| **Milam (2022-Ohio-3965)** | **verified (as Eddy)** | **POSSIBLE_MATCH** | **case.dev doesn't flag name mismatch** |
| Kenty (72 Ohio St.3d 415) | multiple_matches (2 clusters) | VERIFIED | We picked the right one; they surfaced both |
| Pendergraft (297 F.3d 1198) | verified | VERIFIED | Match |
| Jackson (180 F.3d 55) | verified | VERIFIED | Match |
| Flatley (39 Cal.4th 299) | verified | VERIFIED | Match |
| Kulch (78 Ohio St.3d 134) | verified | VERIFIED | Match |
| Office Depot (821 F. Supp. 2d 912) | verified | VERIFIED | Match |
| **Protech (51 F.4th 714)** | **not_found** | **NOT_FOUND** | Match |
| Stolle (605 F. App'x 473) | verified | VERIFIED | Match |
| Van Buren (593 U.S. 374) | verified | VERIFIED | Match |
| Royal Truck (974 F.3d 756) | verified | VERIFIED | Match |
| Wilson (517 F.3d 421) | verified | VERIFIED | Match |

### Key Findings

1. **No name matching.** case.dev verifies the citation *location* exists but doesn't compare the case name the user provided against the case name at that location. Citations #10 (Carter -> Stull) and #11 (Milam -> Eddy) are returned as "verified" even though they belong to different cases. This is the critical gap for hallucination detection.

2. **Parallel citations counted separately.** Hecht and Surace each have two reporter citations, producing 22 results from 20 unique cases. Would need dedup logic.

3. **multiple_matches status.** Kenty returned 2 clusters (same case, different CL opinion IDs). Our pipeline resolved this; case.dev surfaces both as candidates.

4. **Response includes CL URLs, case names, dates, cluster IDs.** Enough metadata to populate claims.csv and proceed to opinion download without additional lookups.

## citations() Endpoint

Bluebook parser. Free, instant.

### Findings

- Parsed 21 citations from the text block
- **3 Ohio St. 3d citations returned `components: null`** (66 Ohio St. 3d 458, 72 Ohio St. 3d 415, 78 Ohio St. 3d 134) -- parser couldn't decompose them, though verify() found them fine
- Federal reporters (F.3d, F.4th, F. Supp. 2d, U.S.) parsed correctly with volume/reporter/page
- Ohio neutral cites (2021-Ohio-2131 etc.) parsed but without volume/reporter/page (expected)
- Case names populated from CL data (not parsed from input text)
- `found: true/false` indicates whether the citation was located in CL

### Comparison with eyecite

eyecite handles all of these citation formats. The citations() endpoint doesn't add value over eyecite for parsing, but the `found` field provides a quick existence check.

## Raw Responses

- `verify_response.json` -- full verify() response
- `citations_response.json` -- full citations() response
