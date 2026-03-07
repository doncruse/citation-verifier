# case.dev API Testing Narrative

**Testing dates:** 2026-03-06 through 2026-03-07

This document records our evaluation of the [case.dev](https://case.dev) legal API as a potential first-pass layer in the citation verification pipeline. We tested three endpoints across multiple datasets to understand what case.dev does well, where it falls short, and whether it's worth integrating.

---

## Test 1: verify() Endpoint — First Look

**Script:** `test_verify.py`
**Date:** 2026-03-06
**Data:** 20 unique citations from the Kettering v. Collier brief

We sent all 20 citations as a single text block to `POST /legal/v1/verify`. The response came back instantly with 22 citation matches (parallel cites like Hecht's Ohio St. 3d and N.E.2d entries were counted separately).

**Results:** 20 verified, 1 not_found, 1 multiple_matches.

The not_found was In re Protech (51 F.4th 714) — same case our pipeline can't find either, so that's consistent. The multiple_matches was Kenty (72 Ohio St.3d 415), where CourtListener has two cluster IDs for the same case. Our pipeline resolves this automatically; case.dev surfaces both candidates and leaves the choice to the caller.

**The critical finding:** Two citations came back "verified" even though the case names didn't match:

- **State v. Carter, 72 Ohio App.3d 553** — case.dev said "verified" but the case at that location is actually *Stull v. Combustion Engineering*. Our pipeline flags this as POSSIBLE_MATCH.
- **State v. Milam, 2022-Ohio-3965** — case.dev said "verified" but it's actually *State v. Eddy*. Same problem.

This is the hallucination pattern we're specifically trying to catch. case.dev confirms that a reporter-volume-page combination exists in CourtListener, but it doesn't check whether the case name the user provided matches the case name at that location. For a tool whose purpose is detecting fabricated citations, this is a dealbreaker as a standalone solution — but it's fine as a first pass if we layer our name-matching on top.

## Test 2: citations() Endpoint — Bluebook Parser

**Script:** `test_verify.py` (second function)
**Date:** 2026-03-06
**Data:** Same 20 Kettering citations

The `POST /legal/v1/citations` endpoint parses Bluebook-formatted citations and returns structured components.

It parsed 21 citations from the text block (one more than we sent — likely split a parallel cite). Federal reporters were handled correctly. Ohio neutral cites (2021-Ohio-2131 etc.) were recognized but without volume/reporter/page decomposition, which is expected.

**Problem:** Three Ohio St. 3d citations came back with `components: null` — the parser couldn't decompose them (66 Ohio St. 3d 458, 72 Ohio St. 3d 415, 78 Ohio St. 3d 134). Notably, verify() found all three just fine.

**Verdict:** eyecite handles all of these formats without issues. The citations() endpoint doesn't add value over what we already have. The `found: true/false` field is a nice quick-check, but verify() provides that plus more metadata. We won't use this endpoint.

## Test 3: Waterfall Pipeline — case.dev as First Pass

**Script:** `test_waterfall.py`
**Date:** 2026-03-06, re-run 2026-03-07
**Data:** Kettering v. Collier (27 unique citations) and Valve v. Rothschild (32 unique citations)

This was the main experiment. The idea: use case.dev verify() as a fast batch lookup, run the results through our name-matching logic, and only fall back to the full CourtListener pipeline for citations that case.dev couldn't resolve.

The waterfall works like this:

1. **case.dev verify()** — Send all citations as a text block. One API call, ~6-10 seconds regardless of count.
2. **Name matching** — For each "verified" result, check if the case name case.dev returned matches the case name in the citation. If not, flag as POSSIBLE_MATCH. For "multiple_matches," try each candidate.
3. **CL fallback** — Citations that case.dev couldn't find (not_found, no reporter citation, pinpoint-only cites like `556 U.S. at 678`) go through our full 3-step CL pipeline.

### Kettering Results (27 citations)

| Metric | Value |
|--------|-------|
| Resolved by case.dev | 17 (63%) |
| Name mismatches caught | 2 (Carter/Stull, Milam/Eddy) |
| CL fallback needed | 8 |
| case.dev time | 6.1s |
| CL fallback time | 11.9s |
| Total time | 18.0s |
| Status match vs. ground truth | 25/27 (93%) |

The 2 mismatches against ground truth were pinpoint citations (`72 Ohio St.3d at 419` and `66 Ohio St. 3d at 460-61`) — these lack a starting page number so case.dev can't look them up, and our CL fallback also struggled with them. Both are for cases that were verified elsewhere in the brief via their full citations.

### Valve Results (32 citations)

| Metric | Value |
|--------|-------|
| Resolved by case.dev | 24 (75%) |
| Name mismatches caught | 0 |
| CL fallback needed | 8 |
| case.dev time | 10.1s |
| CL fallback time | 81.3s |
| Total time | 91.4s |
| Status match vs. ground truth | 32/32 (100%) |

The 8 fallback cases were WestLaw citations (2009 WL 10705131), docket-number-only citations, and pinpoint cites — none of which case.dev can resolve. These are the same cases that required our RECAP pipeline.

### Waterfall Assessment

The waterfall saves roughly 70% of CourtListener API calls. The case.dev batch call is essentially free and fast. The real time cost is in the CL fallback for the remaining ~25-30% of citations, especially WestLaw and RECAP lookups.

Name matching is essential. Without it, two hallucinated citations in Kettering would have been marked "verified." With our name-matching layer on top, the waterfall catches everything our standalone pipeline catches.

## Test 4: Full Waterfall — 50 Citations from the Main Dataset

**Scripts:** `batch_verify_50.py` (case.dev call) then `waterfall_batch_50.py` (name matching + CL fallback)
**Date:** 2026-03-07
**Data:** 50 unverified citations from `citations_for_review.csv` (the 525-citation master dataset)

This was the real test of the waterfall at scale — not against a single brief with ground truth, but against a diverse sample from our full corpus of citations extracted from hallucination-flagged opinions.

### Step 1: case.dev batch call

We pulled the first 50 unverified citations and sent them as a single text block (2,941 characters, well under the 64K limit). One API call returned results for all 50.

**case.dev raw results:** 39 verified, 8 multiple_matches, 3 not_found.

### Step 2: Waterfall (name matching + CL fallback)

We then ran the cached case.dev results through the full waterfall — name matching on every verified/multiple_matches result, CL fallback only for the 3 not_found cases.

**Final results:**

| Status | Count | Source |
|--------|-------|--------|
| VERIFIED | 44 | 44 from case.dev, 0 from CL |
| POSSIBLE_MATCH | 4 | 3 from case.dev name check, 1 from CL |
| LIKELY_REAL | 1 | CL fallback |
| NOT_FOUND | 1 | CL fallback |

**94% resolved without a single CourtListener API call.** Only 3 of the 50 citations needed the CL fallback pipeline at all.

### Name mismatches caught

The waterfall flagged 3 citations that case.dev alone called "verified" — all three are likely hallucinated citations where the reporter location exists but belongs to a different case:

| # | Citation in brief | case.dev said "verified" | Actually at that location |
|---|------------------|------------------------|--------------------------|
| 1 | Townsend v. Meyer, 129 Md. App. 598 (2000) | verified | *State Dept. of Assessments & Taxation v. North Baltimore Center* |
| 2 | Furr v. Furr, 199 Md. App. 1 (2011) | verified | *People's Insurance Counsel Division v. Allstate Insurance* |
| 21 | United States v. Smith, 629 F.3d 1082 (9th Cir. 2011) | verified | *Lands Council v. McNair* |

Without the name-matching layer, all three would have been reported as verified — exactly the kind of false negative that makes a citation verifier dangerous to rely on. These are fabricated citations that happen to land on real reporter locations, and case.dev has no mechanism to detect them.

### The 3 CL fallback cases

- **Parekh v. CBS Corp., 820 F. App'x 827** — case.dev not_found. CL fallback found a possible match (*Niklesh Parekh v. CBS Corporation*) but flagged it as POSSIBLE_MATCH due to name differences.
- **Monell v. Dep't of Soc. Servs., 436 U.S. 659** — Wrong page number (should be 658). case.dev not_found. CL fallback also couldn't resolve it — returned NOT_FOUND with a partial match to *McDaniel v. The City of New York*. The correct Monell cite (436 U.S. 658) was verified by case.dev elsewhere in the batch.
- **Brown v. Federation of State Med. Boards, 830, 26 F.2d 1429** — Junk from PDF extraction (the `830,` is a stray page number from a neighboring citation). case.dev couldn't parse it. CL fallback found the case as LIKELY_REAL.

### The 8 multiple_matches

All 8 were cases where CourtListener has duplicate opinion records (same case, different cluster IDs). The waterfall's name-matching step successfully disambiguated every one:

- Kaplan v. DaimlerChrysler — 2 candidates, correct one picked
- Malautea v. Suzuki Motor Co. — 2 candidates, correct one picked
- Lopez v. Smith — 2 candidates, correct one picked
- Genzler v. Longanbach — 2 candidates, correct one picked
- Taylor v. Cnty. of Pima — 2 candidates, correct one picked
- Mars Steel Corp. v. Continental Bank — 2 candidates, correct one picked
- Trust Corp. v. Dabney — 2 candidates, correct one picked
- Hanlon v. Chrysler Corp. — 2 candidates, correct one picked

### What this tells us

The batch-50 test confirmed everything the brief-level tests suggested, but at a more meaningful scale and against messier data:

1. **case.dev + name matching resolves ~94% of citations with zero CL API calls.** The brief-level tests showed ~70%, but that was dragged down by pinpoint cites and WestLaw citations. The main dataset has fewer of those edge cases.

2. **Name matching is non-negotiable.** 3 out of 50 citations (6%) were hallucinations that case.dev would have called "verified." That's not a rare edge case — it's the base rate in our hallucination-focused dataset.

3. **The CL fallback is only needed for genuinely hard cases** — wrong page numbers, PDF extraction artifacts, and citations not in CourtListener at all. These are cases where any automated system would struggle.

4. **multiple_matches is a solved problem.** All 8 multiple_matches cases were resolved by name matching. This is a strength of combining case.dev's candidate surfacing with our matching logic.

## Test 5: docket() Endpoint — RECAP Alternative

**Script:** `test_docket.py`
**Date:** 2026-03-06
**Data:** 3 cases from the Valve brief that went through our RECAP pipeline

We tested whether case.dev's docket endpoint could replace our RECAP search + docket-entries pipeline. The endpoint supports two modes: `search` (find dockets by case name and court) and `lookup` (get a specific docket with entries).

### PacTool v. Kett Tool (W.D. Wash.)
- **Search:** Found 5 dockets. The correct one (docket 4410019, "Pactool International Ltd v. Dewalt Industrial Tool Co") was the first result. Matched our pipeline's result.
- **Time:** 6.2s (search + lookup)

### Amazon v. Personal Web Tech (W.D. Wash.)
- **Search:** Found 1,600 dockets — the query "Amazon.com" is too broad for this court. The actual case wasn't in the first page of results. This is a relevance ranking problem; our pipeline handles it by including the docket number in the search.
- **Time:** 5.8s

### Diamondback v. Repeat Precision (W.D. Tex.)
- **Search:** Found 13 dockets. Correct one (docket 14534075) was the first result.
- **Time:** 2.4s

### Docket Assessment

The docket endpoint works well when the case name is distinctive (PacTool, Diamondback) but struggles with common party names (Amazon). Our current RECAP pipeline uses docket numbers and date filtering which gives better precision for ambiguous cases.

The lookup mode with entries is useful — it returns the full docket sheet with descriptions and document metadata, similar to what we get from CL's docket-entries API. But we'd need to add our own document ranking logic (`_opinion_likelihood`) on top.

**Verdict:** Not a drop-in replacement for our RECAP pipeline yet, but worth revisiting if they add docket-number filtering to the search mode.

## Test 6: CL Citation-Lookup as Batch — Head-to-Head with case.dev

**Script:** `test_cl_batch_50.py`
**Date:** 2026-03-07
**Data:** Same 50 citations from Test 4

After seeing case.dev's batch verify work so well, we wondered: does CourtListener's own citation-lookup endpoint also support batch requests? Our pipeline has always called it one citation at a time, but the API accepts a `text` parameter that could contain anything — including a block of 50 citations.

We sent the exact same 50-citation text block to `POST /api/rest/v4/citation-lookup/`.

### Results

It works. CL returned 50 entries, one per citation, in 8.6 seconds.

| | case.dev verify() | CL citation-lookup |
|--|------------------|-------------------|
| Citations parsed | 50 | 50 |
| With cluster match | 47 | 47 |
| No match | 3 | 3 |
| Time | ~6s | 8.6s |

The same 3 citations came back empty from both APIs — Parekh (820 F. App'x 827), the wrong-page Monell (436 U.S. 659), and the PDF-junk Brown (26 F.2d 1429). This makes sense: case.dev's verify endpoint queries CourtListener under the hood, so the results should be identical for citation-lookup-level queries.

### Response structure comparison

CL's batch response is well-structured for mapping back to input text:

```json
{
  "citation": "129 Md. App. 598",
  "normalized_citations": [...],
  "start_index": 0,
  "end_index": 20,
  "status": "...",
  "error_message": "...",
  "clusters": [{ full cluster object with 40+ fields }]
}
```

case.dev's response is leaner:

```json
{
  "original": "129 Md. App. 598",
  "normalized": "129 Md. App. 598",
  "span": { "start": 0, "end": 20 },
  "status": "verified",
  "confidence": 1,
  "case": { "id": ..., "name": "...", "url": "...", "dateDecided": "..." }
}
```

Both include positional information (`start_index`/`end_index` vs. `span`) for mapping results back to input text. The key difference is payload size: CL returns full cluster objects with 40+ fields (judges, attorneys, procedural history, etc.), while case.dev returns just the fields you need for verification. For our use case — where we only need the case name, URL, and date — case.dev's response is more practical. But CL's response gives us richer metadata if we ever need it without a second API call.

### What this means for the waterfall

This was a surprise finding. We'd been assuming case.dev was needed as a fast batch layer in front of CL, but CL's own citation-lookup already supports batch mode at comparable speed. The waterfall could work with either backend:

**Option A: case.dev as Step 0** (current waterfall)
- Pro: Leaner responses, slightly faster (~6s vs ~9s)
- Pro: Doesn't count against CL rate limits
- Con: Extra API dependency and key to manage
- Con: Proxies CL data — adds a middleman

**Option B: CL citation-lookup as batch Step 1**
- Pro: Direct source, no middleman
- Pro: One fewer API dependency
- Pro: Richer metadata in the response
- Con: Slightly slower
- Con: Counts against CL's rate limits (though 1 batch call is negligible)

**Option C: Both** — case.dev first (it's free), CL batch as fallback if case.dev is down.

The real value of the waterfall isn't *which* API we use for the batch lookup — it's the name-matching layer on top and the targeted CL fallback (opinion search + RECAP) for the ~6% of citations that need it. Either batch backend gets us to the same 94% resolution rate.

---

## API Limits

From the [case.dev rate limits docs](https://docs.case.dev/rate-limits.md):

- **verify() text limit:** 64,000 characters per request
- **Rate limits by tier (RPM):**

| Tier | Spend | Search RPM |
|------|-------|------------|
| Free | $0 | 200 |
| Tier 1 | $10+ | 1,000 |
| Tier 2 | $50+ | 3,000 |

Since verify() accepts a full text block, one request with 50 citations = 1 RPM. Effectively unlimited for our use case.

The docs say responses should include `x-ratelimit-limit-requests` and related headers, but our test responses (as of 2026-03-07) did not include any rate-limit headers. They may only appear when approaching the limit, or it may be a documentation-vs-implementation gap.

## Overall Assessment

**The batch waterfall pattern works — and either case.dev or CL can power it.**

The key insight from this testing is that the value isn't in case.dev specifically, but in the *pattern*: batch citation lookup + name matching + targeted fallback. CL's own citation-lookup endpoint supports the same batch pattern at similar speed (Test 6), which means we're not locked into case.dev as a dependency.

What matters for hallucination detection:
- **Batch lookup** (either API) resolves ~94% of citations in one call
- **Name matching** (our layer) catches the ~6% of citations where the reporter location exists but belongs to a different case — the core hallucination signal
- **Targeted fallback** (CL opinion search + RECAP) handles WestLaw cites, pinpoint cites, and docket-number-only citations that no citation-lookup API can resolve

What case.dev adds over CL directly:
- Leaner response payloads (5 fields vs. 40+)
- Doesn't count against CL rate limits
- Free tier is generous (200 RPM)
- Slightly faster (~6s vs ~9s for 50 citations)

What case.dev can't do:
- Name matching (the critical gap)
- WestLaw citation resolution
- Pinpoint citation resolution (e.g., `556 U.S. at 678`)
- Docket-number-based search

**Recommended integration:** Use batch citation-lookup (CL directly, or case.dev as a front) as Step 0, layer our name-matching on top, and fall back to CL opinion search + RECAP for the remaining ~6%. This saves ~94% of per-citation CL API calls.
