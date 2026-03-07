# Batch Citation Lookup — Design Doc

**Date:** 2026-03-07
**Status:** Approved

## Problem

`verify_batch()` makes N individual `citation_lookup()` API calls — one per citation. CL's citation-lookup endpoint accepts a text block with multiple citations and returns results for all of them in one call. Our testing (see `scratch/casedev/test_narrative.md`, Tests 4 and 6) showed that a single batch call resolves ~94% of citations with zero additional API calls needed, and the remaining ~6% fall through to opinion search / RECAP as before.

## Design

### What changes

| File | Change |
|------|--------|
| `verifier.py` | New private method `_batch_citation_lookup()` on `CitationVerifier` |
| `verifier.py` | `verify_batch()` rewritten to call batch lookup first, then branch |

### What doesn't change

- `verify()` — sync single citation (CLI use), unchanged
- `verify_async()` — no new params, no new behavior
- `_process_citation_lookup_hit()` — already exists, already does name matching
- `_search_fallback_async()` — unchanged
- `client.py` — unchanged (already accepts text blocks)
- `models.py` — unchanged

### Flow

```
verify_batch(citations)
        |
        v
  Parse all citations
  (reuse parsed= if provided)
        |
        v
  _batch_citation_lookup()
  (new method, see below)
        |
        v
  Returns {index: cluster} for hits
        |
        v
  For each citation:
        |
   +----+----+
   |         |
  HIT      NO HIT
   |         |
   v         v
  _process_citation_    verify_async()
  lookup_hit()          (opinion search +
  (instant, no API,      RECAP, rate-limited,
   does name matching)   unchanged)
   |         |
   v         v
  VERIFIED / POSSIBLE_MATCH    LIKELY_REAL / NOT_FOUND
        |
        v
  Merge results, return in input order
```

Key: citations with a batch hit go directly to the existing `_process_citation_lookup_hit()` — no API call, no semaphore, no waiting. Only citations without a hit go through `verify_async()` with its rate-limited opinion search and RECAP fallback.

### `_batch_citation_lookup()` — new private method

**Signature:** `async def _batch_citation_lookup(self, async_client, citations: list[str]) -> dict[int, dict]`

**Responsibilities:**

1. **Build text block** — join citation texts with newlines
2. **Chunk if needed** — split into chunks under ~50K chars (64K API limit minus margin), splitting on newline boundaries so citations aren't cut in half
3. **POST each chunk with retry** — up to 3 attempts, using existing `_request_with_retry` logic (handles 429s)
4. **Fallback on total failure** — if a chunk still fails after 3 retries, make individual `citation_lookup()` calls for just those citations (graceful degradation to current behavior, not a full skip to opinion search)
5. **Map results back** — match each CL response entry to the original citation index using `start_index` / `end_index` positions in the text block. Pick the first cluster from each entry.

**Returns:** `dict[int, dict]` mapping citation index → cluster dict. Citations with no hit are absent from the dict.

### Result mapping

CL's citation-lookup response includes `start_index` and `end_index` for each found citation, pointing into the submitted text block. To map back:

- Track the starting offset of each citation in the joined text block
- For each response entry, find which citation's range contains the `start_index`
- If a citation has clusters, take the first one as the hit

Edge case: CL may find parallel citations (e.g., both the Ohio St. 3d and N.E.2d cite for Hecht) and return multiple entries for the same input citation. We take the first cluster match per input citation.

### Chunking strategy

- **Chunk size:** ~50,000 characters (leaves margin under the 64K API limit)
- **Split on newline boundaries** so citations aren't truncated
- **Track offsets per chunk** for result mapping
- **Independent retry per chunk** — a failure in chunk 2 doesn't affect chunk 1's results

In practice, 50 citations at ~60 chars each = ~3K chars. We'd need ~800+ citations to trigger chunking. The `/verify-brief` skill typically processes 20-60 citations. Chunking is a safety net, not a common path.

### Retry strategy

- 3 attempts per chunk (consistent with existing `_request_with_retry` behavior)
- On total failure for a chunk: fall back to **individual** `citation_lookup()` calls for those citations
- This is important — a batch failure should NOT skip citations straight to opinion search. The individual lookup is still the fast path; we just lose the batch optimization for that chunk.

### Testing plan

**Existing tests (should pass unchanged):**
- 101 unit tests in `test_verifier.py` (mock at client level, don't touch `verify_batch`)
- 29 async parity tests in `test_async_verifier.py`

**New tests:**

`_batch_citation_lookup()`:
- Text block construction and offset tracking
- Result mapping by start_index/end_index
- Chunking when text exceeds 50K chars
- Retry on failure (mock 500 then 200)
- Fallback to individual calls after 3 failures
- Empty input (no citations)
- Citations with no hits (empty clusters)

`verify_batch()` integration:
- Batch hit path: citations resolved by batch lookup go through `_process_citation_lookup_hit()`, not `verify_async()`
- No-hit path: citations without batch hits go through full `verify_async()` pipeline
- Mixed: some hits, some misses, results returned in input order
- Progress callback still works
- `quick_only` still works (batch hits resolved, no-hits return NOT_FOUND without fallback)

## Background

See `scratch/casedev/test_narrative.md` for the full testing narrative that motivated this design. Key findings:

- CL citation-lookup works as batch (Test 6): 50 citations in one 8.6s call
- Batch + name matching resolves 94% of citations with zero per-citation API calls (Test 4)
- Name matching is essential — 6% of "verified" citations in our hallucination dataset are actually name mismatches (Test 4)
- case.dev verify() produces identical results but is not needed as a dependency; CL's own endpoint is sufficient
