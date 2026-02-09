# Potential Contributions to Free Law Project

This document tracks potential contributions to FLP's projects (CourtListener, eyecite, courts-db, etc.) based on our findings.

## Status Legend

- **DRAFT** - Needs more evidence/testing before submitting
- **READY** - Ready to submit, awaiting decision
- **SUBMITTED** - Already submitted to FLP
- **DECLINED** - Decided not to submit (explain why)

---

## 1. Abbreviation Synonym Coverage for Search

**Status:** READY
**Target:** CourtListener issue [#3367](https://github.com/freelawproject/courtlistener/issues/3367)
**Type:** Data contribution / Comment on existing issue

### Summary

Provide prioritized subset of Indigo Book abbreviations based on real-world false negative analysis. Issue #3367 requests "full Indigo Book table" but that's 100+ terms - we can help prioritize which ones matter most.

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

**Status:** DRAFT
**Target:** CourtListener (new issue)
**Type:** Bug report

### Summary

The RECAP search API `docket` parameter appears to be ignored, returning unfiltered recent results instead of filtering by docket number.

### Evidence Needed

- [ ] Check API documentation for `docket` parameter
- [ ] Test 3-5 different docket numbers systematically
- [ ] Verify `q` parameter workaround works consistently
- [ ] Search FLP issues for existing reports
- [ ] Determine: bug or undocumented behavior?

### Current Status

**What we know:**
- API call: `GET /api/rest/v4/search/?type=r&docket=C15-1228-JCC`
- Expected: Results filtered to that docket
- Actual: Returns recent RECAP results, unrelated to docket number
- Workaround: Use `q="C15-1228"` instead, filter client-side

**What we need:**
- More test cases
- Confirmation it's a bug vs "never implemented"
- Impact assessment (does anyone else rely on this?)

### Next Steps

1. API documentation review
2. Systematic testing
3. Issue search
4. Draft report (if warranted)

**Decision:** ON HOLD - needs investigation before determining if worth reporting

---

## 3. Parser Improvements (eyecite)

**Status:** DECLINED
**Target:** eyecite repository
**Type:** N/A

### Summary

Our parser diagnostics (`tests/test_parser_diagnostics.py`) show that eyecite handles all common citation formats well:
- ✅ WestLaw citations
- ✅ Standard reporters
- ✅ California style
- ✅ Case name extraction
- ✅ Abbreviations (extracted as-is, which is correct behavior)

**Conclusion:** No eyecite contributions needed at this time. Our regex fallbacks don't reveal eyecite gaps - they're for our specific normalization needs.

**Future:** If we find actual eyecite gaps (citations it should parse but doesn't), document here with 10+ examples before submitting.

---

## 4. Data Quality Issues

**Status:** DRAFT
**Target:** CourtListener (TBD - may be multiple issues)
**Type:** Data quality reports

### Issues to Track

As we encounter data quality problems, document them here:

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

## Submission Guidelines

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
