# Analysis: case.dev API Integration

**Date:** 2026-03-06
**Status:** Exploring

## Idea

Use case.dev's `verify()` endpoint as the first pass in the verify-brief pipeline. Single API call for a whole block of text, free. Results waterfall into our existing CourtListener pipeline for anything case.dev misses.

## Relevant Endpoints

| Endpoint | Cost | What it does | Our use |
|----------|------|-------------|---------|
| `verify(text)` | Free | Extract citations from text, verify they exist | Phase 2 first pass |
| `citations(text)` | Free | Parse Bluebook components from text | Could supplement eyecite |
| `fullText(url)` | $0.01 | Full document content with highlights | Skip -- we already have `get_opinion_text()` via CL API (free) |
| `find(query)` | $0.01 | Semantic case search | Skip -- only useful for v2 "suggest alternatives" |

## Proposed Waterfall

```
Brief text
    |
    v
case.dev verify(text)          <-- Single call, free, extracts + verifies
    |
    |-- VERIFIED citations     <-- Accept, move to Phase 3 (retrieve opinions)
    |
    +-- NOT FOUND / missing    <-- Fall through to our CourtListener pipeline
        |                        (citation-lookup -> opinion search -> RECAP)
        v
    Our existing 3-step verifier (per citation)
```

## Why This Makes Sense

- **Speed**: One call vs. 20+ rate-limited CL calls. Phase 2 goes from ~30 seconds to near-instant.
- **Cost**: verify() is free. It's a pass-through to public CourtListener data.
- **Our value-add stays intact**: case.dev tells you "does this citation exist?" Our skill tells you "does the case *support the proposition*?" Phases 1, 4, 5 are where we do unique work.
- **Graceful fallback**: Their data source is CourtListener RECAP, so our pipeline is the natural fallback.

## Open Questions

1. **Response format**: What fields does verify() return? Do we get CourtListener URLs? Case names? Enough to populate `claims.csv`?
2. **Coverage**: Does it handle WestLaw cites (2018 WL 301424), California style ((2022) 76 Cal.App.5th), Ohio parallel cites?
3. **Name matching quality**: Do they do fuzzy matching or exact? Our 4-factor name matcher catches things simple matching misses.
4. **Error handling**: What happens with malformed citations? Rate limits?
5. **citations() endpoint**: Could it replace/supplement eyecite for parsing? What Bluebook components does it extract?

## Testing Plan

1. Run Kettering v. Collier brief text through `verify()` and compare results to our pipeline
2. Run individual citations through `citations()` and compare to eyecite parsing
3. Check edge cases: Ohio parallel cites, WestLaw cites, California style
4. Evaluate response metadata completeness
