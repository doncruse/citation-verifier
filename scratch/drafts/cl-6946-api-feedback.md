# Comment on #6946: Simpler Case Law APIs

Hi -- great to see this issue opened. I've been building a citation verification tool ([rlfordon/citation-verifier](https://github.com/rlfordon/citation-verifier)) that checks legal citations against the CourtListener API to catch AI-hallucinated case references. I've been living inside the v4 API for a while now and wanted to share some friction points from a real consumer's perspective that might be useful as you think about what a simpler API looks like.

### The verification pipeline today

To verify a single citation like `Obergefell v. Hodges, 576 U.S. 644 (2015)`, my tool makes up to **5-8 API calls**:

1. `POST /citation-lookup/` — exact reporter match
2. Up to 4 more citation lookups trying adjacent pages (off-by-one is common in briefs)
3. `GET /search/?type=o` — fuzzy opinion search as fallback
4. `GET /search/?type=r` — RECAP search as second fallback
5. `GET /docket-entries/` — paginated follow-up to find the actual opinion document within a docket

Each step exists because the previous one lacks something. A lot of this could collapse into fewer round trips with some structural changes.

### Specific issues I've hit

**1. Citation lookup is text-only, no structured input**

`/citation-lookup/` takes a raw text string and does its own internal parsing. My parser has already extracted `volume=576, reporter="U.S.", page=644` but I have to serialize it back to a string and hope CL's parser agrees. When there's an off-by-one page number (common in briefs that cite a pinpoint page instead of the starting page), I can't say "find cases near page 644 in 576 U.S." — I have to make 4 extra calls trying pages 643, 645, 642, 646 individually. A structured lookup with a page tolerance would eliminate these.

**2. Opinions and RECAP are parallel universes**

I maintain two entirely separate processing pipelines (~200 lines each) because the response shapes and semantics are so different. Some real cases exist only in opinions, some only in RECAP, some in both with different metadata. There's no unified "does this case exist?" query. I've found [16 confirmed real federal cases](https://github.com/rlfordon/citation-verifier/blob/main/scratch/flp_contributions.md) that exist only in RECAP and not in the opinions DB.

**3. RECAP returns dockets, not documents**

When I search RECAP I get docket-level results, but I need a specific document (the opinion, not the "Certificate of Service"). So I have to: query docket-entries filtered by date, iterate all entries and their nested documents, then run my own keyword heuristic to distinguish opinions from procedural filings. There's no `doc_type` filter on RECAP search or docket-entries. A way to search for "opinion documents matching X" directly would save 1-2 round trips per citation and a lot of client-side heuristic code.

**4. `dateFiled` means different things on different endpoints**

On opinion search, `dateFiled` is the opinion date. On RECAP search, `dateFiled` is the case filing date (which can be years before the opinion). The actual document date is buried in `entry_date_filed` on individual docket entries, which I can only get by querying the docket-entries API. This semantic inconsistency requires a follow-up API call every time I need to verify a date against a RECAP result.

**5. Field naming is inconsistent across v4 endpoints**

I have dual-key lookups everywhere because search returns camelCase (`caseName`, `dateFiled`, `docketNumber`) while REST endpoints return snake_case (`case_name`, `date_filed`, `docket_number`). Same API version, different conventions:

```python
case_name = r.get("caseName") or r.get("case_name", "")
date_filed = r.get("dateFiled") or r.get("date_filed", "")
```

**6. URLs are sometimes relative, sometimes absent**

I have URL construction logic in 5 separate places — the API returns relative paths sometimes, absolute URLs sometimes, and nothing at all sometimes (just a cluster_id). Canonical absolute URLs on every result would help.

**7. Search doesn't handle standard legal abbreviations**

"Cnty." doesn't match "County", "Dep't" doesn't match "Department". I maintain a [47-term normalization table](https://github.com/rlfordon/citation-verifier/blob/main/src/citation_verifier/parser.py) expanding Indigo Book abbreviations client-side before every search call. I know this is tracked in #3089 and #3367, but it's worth noting here because it's one of the biggest sources of false negatives in practice and a simpler API could address it.

**8. No match-quality signal in search responses**

Search results come back with no indication of match strength. I built a [270-line multi-factor name matcher](https://github.com/rlfordon/citation-verifier/blob/main/src/citation_verifier/name_matcher.py) and a 200-line weighted scoring system because the API gives me a flat list with no signal about how well a result matches my query. Even a rough relevance score or match-type indicator ("exact match" vs "partial" vs "keyword") would help consumers avoid rebuilding this.

**9. The `docket` search parameter is silently broken**

The RECAP search `docket` parameter appears to be ignored — it returns unfiltered results regardless. I work around this by passing quoted docket numbers through the `q` parameter and filtering client-side. A parameter that silently does nothing is worse than a missing one. (Happy to provide test cases if this isn't already known.)

**10. The `citation` field on results is structurally unpredictable**

Sometimes it's a list, sometimes a string, sometimes empty even for cases that have reporter citations. WestLaw citations are almost never present. This makes it impossible to confirm whether a found case actually matches the cited reporter volume/page, which is a key verification signal.

### What would help most

From my use case, the highest-impact changes would be:

1. **Structured citation lookup** — accept volume/reporter/page with tolerance, not just raw text
2. **Unified case search** across opinions and RECAP in one call with one response shape
3. **Document-type filtering** on RECAP/docket-entries (e.g., `doc_type=opinion`)
4. **Consistent field naming and absolute URLs** across all v4 endpoints
5. **Abbreviation synonyms** in the search index (the Indigo Book table from #3367)

Happy to provide more specific examples or test cases for any of these. And thanks for all the work on CourtListener — even with these friction points, it's an incredible resource and the only reason a tool like mine is possible.
