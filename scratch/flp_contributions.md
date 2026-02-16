# Potential Contributions to Free Law Project

This document tracks potential contributions to FLP's projects (CourtListener, eyecite, courts-db, etc.) based on our findings.

## Table of Contents

| # | Title | Status | Target |
|---|-------|--------|--------|
| [1](#1-abbreviation-synonym-coverage-for-search) | Abbreviation Synonym Coverage for Search | DRAFT | CL [#3367](https://github.com/freelawproject/courtlistener/issues/3367) |
| [2](#2-docket-parameter-unreliability) | Docket Parameter Unreliability | DECLINED | CL |
| [3](#3-eyecite-newline-breaks-metadata-parsing-paragraphtoken-boundary) | eyecite: Newline Breaks Metadata Parsing | SUBMITTED | eyecite [#297](https://github.com/freelawproject/eyecite/issues/297) |
| [4](#4-eyecite-apostrophe-truncates-case-name-words) | eyecite: Apostrophe Truncates Case Names | SUBMITTED | eyecite [#296](https://github.com/freelawproject/eyecite/issues/296) |
| [5](#5-federal-district-court-opinions-only-in-recap-not-in-opinions-db) | Federal Court Opinions Only in RECAP | SUBMITTED | CL [#6963](https://github.com/freelawproject/courtlistener/issues/6963) |
| [6](#6-data-quality-issues) | Data Quality Issues | DRAFT | CL |
| [7](#7-simpler-case-law-apis--feedback-from-citation-verification-consumer) | Simpler Case Law APIs — Consumer Feedback | DRAFT | CL [#6946](https://github.com/freelawproject/courtlistener/issues/6946) |

## Status Legend

- **DRAFT** - Needs more evidence/testing before submitting
- **READY** - Ready to submit, awaiting decision
- **SUBMITTED** - Already submitted to FLP
- **DECLINED** - Decided not to submit (explain why)

---

## 1. Abbreviation Synonym Coverage for Search

**Status:** DRAFT
**Target:** CourtListener issue [#3367](https://github.com/freelawproject/courtlistener/issues/3367)
**Type:** Data contribution / Comment on existing issue

### Summary

Provide prioritized subset of Indigo Book abbreviations based on real-world false negative analysis. Issue #3367 requests "full Indigo Book table" but that's 100+ terms - we can help prioritize which ones matter most. [Note: we decided not to include some of the below abbreviations, so need to review code and update this before submitting]

### Our Findings

**Coverage analysis:**
- Analyzed 53 common Indigo Book abbreviations
- Identified 46 high-priority terms (87% coverage of real cases)
- Intentionally skipped 7 ambiguous terms (N., S., E., W., St., Ave., Blvd.)
- Categorized by type for easier implementation

**False negatives encountered:**
- "Bossart v. King Cnty." → failed to match cluster #69346061 ("Bossart v. King County")
- "Busha v. SC Dep't of Mental Health" → failed to match cluster #14553775 ("SC Department of Mental Health")
- "Townsley v. Lifewise Assurance Co." (with other issues) → benefited from normalization

**Our workaround:**
- Implemented client-side normalization in `parser.py`
- See: `_normalize_case_name()` function
- Test coverage: `tests/check_indigo_book_coverage.py`

### Proposed Comment for Issue #3367

```markdown
### Data: Real-world abbreviation priority analysis

We built a citation verification tool that uncovered false negatives due to abbreviation mismatches in CL search. We analyzed Indigo Book abbreviations to identify which ones matter most in practice.

**High-priority abbreviations (46 terms, ~87% real-world coverage):**

*Government entities (11):*
- Cnty., Cty. → County
- Dept., Dep't → Department
- Comm., Comm'n → Commission
- Bd. → Board
- Div. → Division
- Dist. → District
- Off., Ofc. → Office

*Organizations (8):*
- Corp. → Corporation
- Co. → Company
- Inc. → Incorporated
- Ltd. → Limited
- LLC, L.L.C. → Limited Liability Company
- Assn., Ass'n → Association

*Positions (8):*
- Admin., Adm'r → Administrator
- Exec. → Executive
- Dir. → Director
- Sec'y → Secretary
- Treas. → Treasurer
- Atty. → Attorney
- Gen. → General

*Education (3):*
- Univ. → University
- Coll. → College
- Sch. → School

*Medical/Health (3):*
- Hosp. → Hospital
- Med. → Medical
- Ctr. → Center

*Business/Services (7):*
- Ins. → Insurance
- Mfg. → Manufacturing
- Serv., Servs. → Service/Services
- Transp. → Transportation
- Util. → Utility
- Pub. → Public

*Scope (4):*
- Nat'l, Natl. → National
- Int'l, Intl. → International

*Religious (2):*
- Cath. → Catholic
- Ch. → Church

**Terms we intentionally skipped (ambiguous/risky):**
- N., S., E., W. → could be initials (e.g., "John E. Smith")
- St. → context-dependent (Street vs Saint)
- Ave., Blvd. → addresses, rarely in case names

**False negatives we encountered:**
- Searched: "Bossart v. King Cnty." → No match
- CL has: cluster #69346061 "Bossart v. King County"
- Same issue with "Dep't" → "Department"

**Our workaround:**
We normalize abbreviations client-side before searching, but server-side Elasticsearch synonyms would benefit all CL users.

**Implementation priority:**
Suggest implementing these 46 first (covers 87% of cases) rather than the full 100+ term Indigo Book table. Can add the remaining 13% later based on actual usage data.

Full code/tests available at: [link to repo if/when public]

Happy to provide more data if helpful for prioritization.
```

### Decision Factors

**Pros:**
- Actionable data FLP doesn't have
- Helps prioritize their work
- Shows real false negatives
- Non-demanding tone ("here's data" not "fix this")

**Cons:**
- Issue already exists since 2023 (they know)
- Our workaround works fine
- May not be their priority
- Could be noise if they're already planning implementation

**Recommendation:** Submit as helpful data contribution. It's low-effort for us and might help FLP prioritize. Worst case: they ignore it. Best case: they use our prioritization.

### Submission Checklist

Before submitting:
- [ ] Verify issue #3367 is still open
- [ ] Check recent comments (has someone else provided similar data?)
- [ ] Ensure our repo is public OR remove "link to repo" line
- [ ] Review tone (helpful, not demanding)
- [ ] Submit comment
- [ ] Update this doc with link to our comment

---

## 2. Docket Parameter Unreliability

**Status:** DECLINED (won't report - related issues already exist)
**Target:** CourtListener
**Type:** Bug report / Limitation

### Summary

The RECAP search API `docket` parameter is completely ignored by the API, returning unfiltered recent results instead of filtering by docket number. This appears to be a known limitation tracked in related FLP issues about docket number normalization and search.

### Evidence

**Testing conducted 2025-02-09 using API v4.3:**

Test 1 - Bossart case docket:
```bash
# Using docket parameter - BROKEN
curl "https://www.courtlistener.com/api/rest/v4/search/?type=r&docket=2:24-cv-01776"
# Returns: 60,994,914 results (all recent RECAP docs, unrelated)

# Using q parameter - WORKS
curl "https://www.courtlistener.com/api/rest/v4/search/?type=r&q=\"2:24-cv-01776\""
# Returns: 16 results including correct case (docket ID 69346061)
```

Test 2 - Anderson case docket:
```bash
# Using docket parameter - BROKEN
curl "https://www.courtlistener.com/api/rest/v4/search/?type=r&docket=17-cv-12676"
# Returns: 60,994,914 results (all recent RECAP docs, unrelated)

# Using q parameter - WORKS
curl "https://www.courtlistener.com/api/rest/v4/search/?type=r&q=\"17-cv-12676\""
# Returns: 21 results including correct case (docket ID 6264209)
```

**Conclusion:** The `docket` parameter has no effect on filtering. It's present in the URL but completely ignored.

### Related FLP Issues

Search found several related issues about docket number handling:

1. **[Issue #764](https://github.com/freelawproject/courtlistener/issues/764)** - RECAP docket number search doesn't allow suffixes (judge initials)
2. **[Issue #635](https://github.com/freelawproject/courtlistener/issues/635)** - Normalize PACER docket numbers for search (leading zeroes)
3. **[Issue #6296](https://github.com/freelawproject/courtlistener/issues/6296)** - Docket number clean-up to prep for appellate chain linking
4. **[Issue #6313](https://github.com/freelawproject/courtlistener/issues/6313)** - Implement docket number cleaning to CL workflow

These issues focus on docket number normalization and search via the main search box, but they indicate FLP is aware that docket number search has challenges. The `docket` parameter specifically may never have been fully implemented for the API.

### Our Workaround

From `src/citation_verifier/client.py`:
```python
if docket_number:
    # Use q with quoted string -- the docket param is unreliable
    q_parts = [params.get("q", ""), f'"{docket_number}"']
    params["q"] = " ".join(p for p in q_parts if p)
```

Then in `verifier.py`, we filter results client-side:
```python
# API does fuzzy matching, so filter to actual docket matches
cited_dn = self._normalize_docket_number(parsed.docket_number)
results = [
    r for r in results
    if self._normalize_docket_number(
        r.get("docketNumber") or r.get("docket_number") or ""
    ) == cited_dn
]
```

This two-step approach (search with `q`, then client-side filter) works reliably.

### Decision Factors

**Why not report:**
- Related issues already exist (#764, #635, #6296, #6313)
- FLP is aware docket number search is challenging
- The `docket` parameter may never have been fully implemented (not documented)
- Our workaround is straightforward and works well
- Low priority - affects API users but not web interface users
- Reporting would likely duplicate or overlap with existing work

**Alternative action:**
- Could comment on existing issues with our API testing data
- But seems more useful to wait until FLP addresses the broader docket normalization work

**Recommendation:** Don't create a new issue. If FLP solicits feedback on docket search improvements (e.g., in #635 or #6296), we could contribute our API testing data showing the `docket` parameter doesn't work.

---

## 3. eyecite: Newline Breaks Metadata Parsing (ParagraphToken boundary)

**Status:** SUBMITTED
**Target:** eyecite [#297](https://github.com/freelawproject/eyecite/issues/297)
**Type:** Bug report
**Filed:** 2026-02-16

### Summary

eyecite's `match_on_tokens()` stops scanning at `ParagraphToken` boundaries. A single `\n` becomes a `ParagraphToken`, so court/year parentheticals on the next line are never reached. 101 citations (19%) affected across our 19-PDF corpus. Proposed three approaches: option flag, peek-past-boundary, or single-vs-double newline distinction.

Offered to submit a PR once maintainers indicate preferred approach.

### Draft

See `scratch/drafts/eyecite-newline-metadata.md` for the full issue text as filed.

---

## 4. eyecite: Apostrophe Truncates Case Name Words

**Status:** SUBMITTED
**Target:** eyecite [#296](https://github.com/freelawproject/eyecite/issues/296)
**Type:** Bug report
**Filed:** 2026-02-16

### Summary

eyecite's case name extraction regexes use `[\w\-.]+` to match words, but `\w` excludes apostrophes. Legal abbreviations with internal apostrophes (`Att'y`, `Dep't`, `Gov't`, `Comm'n`, `P'ship`, `Nat'l`, `Sec'y`) are truncated at the apostrophe, losing the suffix. 8 case names affected in our 19-PDF corpus. 11 standard Indigo Book abbreviations identified.

### Suggested fix

Add straight and curly apostrophes to three character classes in `eyecite/regexes.py`:
- `[\w\-.]+` → `[\w\-.'\u2019]+` (SHORT_CITE_ANTECEDENT_REGEX, SUPRA_ANTECEDENT_REGEX)
- `[a-z\-.]+` → `[a-z\-.'\u2019]+` (PRE_FULL_CITATION_REGEX)

Offered to submit a PR if maintainers want one.

### Draft

See `scratch/drafts/eyecite-apostrophe-truncation.md` for the full issue text as filed.

---

## 5. Federal District Court Opinions Only in RECAP (Not in Opinions DB)

**Status:** SUBMITTED
**Target:** CourtListener [#6963](https://github.com/freelawproject/courtlistener/issues/6963) (related to closed #3790)
**Type:** Bug report — 16 civil federal cases in RECAP but not in opinions DB
**Filed:** 2026-02-16

### Summary

16 federal civil cases where the opinion/order document exists in a RECAP docket but is not in the opinions database. 4 pre-sweep cases (2008–2023) are strongest evidence of a pipeline gap. All pre-sweep/edge cases re-verified absent from opinions DB on 2026-02-16.

### Background

CL's RECAP-to-opinions pipeline requires: federal district/bankruptcy, civil case, and case law citations in the document text. Sweep coverage: 1950-05-12 to 2024-08-05, plus daily ingestion. Criminal cases excluded by design (#4642).

### Cases reported in #6963

| Category | Count | Key examples |
|----------|-------|-------------|
| Pre-sweep (2008–2023) | 4 | Fagundes (2008), Mali (2018), King (2019), Ruggierlo (2023) |
| Sweep-edge (Aug 2024) | 1 | Dukuray |
| Post-sweep (2025) | 11 | Button, Tercero, Oneto, Russomanno, Glass, HoosierVac, Thomas, Lahti, Coronavirus Reporter, Davis, O'Brien |

### Excluded from report

- **United States v. Hayes** — criminal case (excluded by design)
- **Lacey v. State Farm** — our tool bug (picked wrong document)
- **O'Brien v. Flick (S.D. Fla.)** — order behind paywall

### Additional examples to add later

As new RECAP-only cases are found in verification runs, add them here and consider commenting on #6963 with a batch update.

| Citation | Year | Court | RECAP Document | Found in run |
|----------|------|-------|---------------|-------------|
| *(none yet)* | | | | |

---

## 6. Data Quality Issues

**Status:** DRAFT
**Target:** CourtListener (TBD - may be multiple issues)
**Type:** Data quality reports

### Issues to Track

As we encounter data quality problems, document them here:

**State court coverage gaps:**
- Status: 7 confirmed cases missing from CL
- Examples:
  1. **Rupnow v. Mont. State Auditor & Comm'r of Ins., 542 P.3d 384 (Mont. 2024)** — Montana Supreme Court opinion not in CL at all. Verified real citation (likely_real classification). Source: Thornton v. Flathead County PDF.
  2. **Jindrich v. Weihele, 656 S.W.3d 519 (Tex. App. 2022)** — Texas Court of Appeals. CL has a different opinion for this case (cluster 5174585, "Edward S. Jindrich, Jr. v. Michaela Weihele") but it appears to be the wrong document — the opinion at 656 S.W.3d 519 is not available. Source: Suday v. Suday PDF.
  3. **Jha v. Khan, 520 P.3d 470, 477 (Wash. Ct. App. 2022)** — Washington Court of Appeals. Not in CL. Available at https://www.courts.wa.gov/opinions/pdf/837681.pdf
  4. **Fowler v. Guerin, 515 P.3d 502, 506 (Wash. 2022)** — Washington Supreme Court. Not in CL. Available at https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.showOpinion&filename=1000693MAJ
  5. **M.G. v. Bainbridge Island School District #303, 566 P.3d 132, 147 (Wash. Ct. App. 2025)** — Washington Court of Appeals. Not in CL.
  6. **Reinlasoder v. City of Billings, 455 P.3d 477 (Mont. 2020)** — Montana Supreme Court. Not in CL. Source: Thornton v. Flathead County PDF.
  7. **Mungo v. State, 486 Md. 158 (2023)** — Maryland Court of Appeals. Not in CL. Source: mezu_v_mezu PDF.
- Action: Collect more examples before reporting. Known CL limitation (#5 in Known CL API Limitations). Washington state courts appear to be a systemic gap (3 of 7 examples). Montana also showing pattern (2 of 7).

**Opinions not marked as free:**
- Status: 2 cases exist in CL but opinions not accessible
- Examples:
  1. **Himes v. Provident Life & Accident Insurance Co., No. 3:19-CV-00215, 2020 WL 9935829 (M.D. Tenn. Mar. 3, 2020)** — federal opinion not marked as free.
  2. **Neravetla v. Virginia Mason Med. Ctr., No. C13-1501-JCC, 2014 WL 12787876, *3-*4 (W.D. Wash. May 23, 2014)** — federal opinion not marked as free. Docket: https://www.courtlistener.com/docket/5262939/neravetla-v-virginia-mason-medical-center/
- Action: Collect more examples. These are federal cases that should be available but aren't searchable via the opinions API.

**Case name format variations:**
- Status: May be expected behavior for multi-party cases
- Need: More examples to determine if systemic
- Examples so far: 2 (Estate of Elkins, Townsley)

**Missing citations field:**
- Status: Need to collect specific cluster IDs
- Impact: Citation lookup fails even when case exists
- Examples: None documented yet

**Cases exist but not searchable:**
- Status: Need to identify specific patterns
- Examples: None documented yet

### Decision Criteria

Before reporting data quality issues:
- Collect 10+ examples showing a pattern
- Verify it's not expected behavior
- Check if already reported
- Assess impact (widespread vs edge case)

---

## 7. Simpler Case Law APIs — Feedback from Citation Verification Consumer

**Status:** DRAFT
**Target:** CourtListener issue [#6946](https://github.com/freelawproject/courtlistener/issues/6946)
**Type:** Comment on existing issue

### Summary

Issue #6946 proposes simpler case law APIs — flatter responses, top-level court filtering, state-level parameters. We've been building a citation verification tool on top of the v4 API and have concrete feedback about what structural changes would help most.

### Proposed Comment for Issue #6946

```markdown
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

\`\`\`python
case_name = r.get("caseName") or r.get("case_name", "")
date_filed = r.get("dateFiled") or r.get("date_filed", "")
\`\`\`

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
```

### Decision Factors

**Pros:**
- Real consumer feedback with concrete code examples
- Links to public repo so FLP can see the actual workarounds
- Constructive tone — acknowledges CL's value while highlighting friction
- Aligns directly with what #6946 is asking for (simpler APIs)
- Quantifies the problem (5-8 API calls per citation, 200+ lines of workaround code)

**Cons:**
- Long comment — may be too detailed for an early-stage discussion
- Some points overlap with existing issues (#3089, #3367, docket param)
- Could overwhelm if they're still in the "what should we build?" phase

**Recommendation:** Wait for some initial discussion on #6946 before posting. If the issue gets traction and FLP is actively soliciting feedback, this is exactly the kind of consumer perspective they need. If the issue goes quiet, may not be worth the noise.

### Submission Checklist

- [ ] Wait for initial discussion on #6946
- [ ] Verify repo is public and links work
- [ ] Review tone one more time
- [ ] Consider shortening to top 5 issues if comment is too long
- [ ] Post comment
- [ ] Update this doc with link

---

## Submission Guidelines

### Use `/file-issue` for New Submissions

The `/file-issue` Claude Code skill walks through the full issue-filing workflow: duplicate search, evidence gathering, repo norm study, drafting, and antipattern review. Use it instead of filing issues manually — it catches the seven antipatterns that get issues ignored.

### Before Submitting Anything

1. **Search existing issues** - Don't duplicate
2. **Verify still relevant** - Is issue already fixed?
3. **Assess value** - Will this help FLP or is it noise?
4. **Check tone** - Helpful data, not complaints
5. **Provide context** - We're users building a tool, sharing findings

### What Makes a Good Contribution

**Good:**
- Concrete data with examples
- Prioritized/categorized findings
- Shows real-world impact
- Includes cluster IDs for verification
- Offers to provide more info
- Respectful of FLP's roadmap

**Bad:**
- Vague "this doesn't work"
- Demands for fixes
- Single edge case without pattern
- No examples or evidence
- Tone-deaf to their constraints

### After Submitting

Update this document:
- Link to our comment/issue
- Note any FLP response
- Track outcome
- Update status

---

## Template for New Potential Contributions

```markdown
## N. [Title]

**Status:** DRAFT/READY/SUBMITTED/DECLINED
**Target:** [Project and issue # if applicable]
**Type:** Bug report / Feature request / Data contribution / Comment

### Summary
[One paragraph: what is this about?]

### Our Findings
[What did we discover? Include examples, data, cluster IDs]

### Evidence
[Test results, code references, reproduction steps]

### Proposed Submission
[Draft of what we'd submit to FLP]

### Decision Factors
**Pros:** [Why submit?]
**Cons:** [Why not?]
**Recommendation:** [Submit / Wait / Decline]

### Next Steps
- [ ] Checklist items before submitting
```

---

## Maintenance

Review this document:
- Before each potential FLP contribution
- After submitting anything (update status, add links)
- Quarterly to remove outdated items
