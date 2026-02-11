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

**Status:** READY
**Target:** eyecite ([https://github.com/freelawproject/eyecite](https://github.com/freelawproject/eyecite))
**Type:** Bug report / Feature request

### Summary

eyecite's `match_on_tokens()` stops scanning for court/year metadata when it encounters a `ParagraphToken` (newline). This means any PDF where a line break separates a citation from its parenthetical loses court and year data. This is extremely common in court opinion PDFs — we found **101 affected citations across 19 PDFs** (19% of all citations).

### Root Cause

In `eyecite/helpers.py`, `match_on_tokens()` stops at paragraph boundaries by design. When pdfplumber (or any PDF text extractor) produces text like:

```
728 F.2d 911
(7th Cir. 1984)
```

eyecite tokenizes the newline as a `ParagraphToken` and never sees the `(7th Cir. 1984)` parenthetical. The citation is extracted with `year=None, court=None`.

### Evidence

**Simple case — newline before parenthetical:**
```python
from eyecite import get_citations
from eyecite.models import FullCaseCitation

# Same line: WORKS
c = [c for c in get_citations('Citation 123 F.3d 456 (N.D. Ohio 2006).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year == '2006'   # ✓
assert c.metadata.court == 'ohnd'  # ✓

# Newline: FAILS
c = [c for c in get_citations('Citation 123 F.3d 456\n(N.D. Ohio 2006).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year is None    # ✗ lost
assert c.metadata.court is None   # ✗ lost
```

**Pin cite + newline before parenthetical:**
```python
# Common pattern: "962 F.3d 979, 984 (7th Cir.\n2020)"
c = [c for c in get_citations('Citation 962 F.3d 979, 984 (7th Cir.\n2020).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year is None    # ✗ lost
```

**Pin cite on next line:**
```python
# "728 F.2d 911,\n915 (7th Cir. 1984)"
c = [c for c in get_citations('Citation 728 F.2d 911,\n915 (7th Cir. 1984).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year is None    # ✗ lost
```

**Scale of impact (our corpus: 19 court opinion PDFs, 536 citations):**
- 101 citations (19%) had orphaned parentheticals due to this issue
- Every single PDF was affected (repairs per PDF ranged from 1 to 13)
- All common reporters affected: F.2d, F.3d, F.4th, F. Supp. 2d/3d, N.E.2d/3d, S.W.2d/3d, P.3d, Cal. App., WL

### Our Workaround

We implemented a post-extraction repair pass in our pipeline (`extract_citations_batch.py:_repair_orphaned_parentheticals()`):

1. After `get_citations()`, iterate through citations with `year=None`
2. Look at text after `citation.span()[1]` for orphaned parentheticals
3. Use a two-phase regex: first match optional pin cite + `(...)`, then parse court/date from contents
4. Patch `citation.metadata.year`, `.month`, `.day`, `.court`
5. Use eyecite's own `get_court_by_paren()` for court ID mapping

This works but is fragile and duplicates logic that should live in eyecite.

### Proposed Fix

Allow `match_on_tokens()` to continue scanning across a single `ParagraphToken` boundary when looking for a court/year parenthetical. Options:

1. **Least disruptive**: Add an option like `allow_newline_before_paren=True` (default `False` for backward compat)
2. **Better default**: Always scan one token past a `ParagraphToken` if the next non-whitespace token starts with `(`
3. **Most robust**: Treat single newlines differently from double newlines (paragraph breaks) — single `\n` is a line break within a citation, `\n\n` is a true paragraph boundary

### Decision Factors

**Pros:**
- Affects 19% of citations in real court PDFs — this is widespread
- Clear reproduction case with minimal code
- Root cause is well-understood (`ParagraphToken` boundary)
- We have 101 concrete examples across 19 PDFs
- PDF text extraction is a primary eyecite use case

**Cons:**
- Our workaround works (but is fragile and external to eyecite)
- Changing `ParagraphToken` handling could have unintended side effects
- May need careful testing against eyecite's own test suite

**Recommendation:** Submit as a bug report with reproduction code and impact data. This is the kind of concrete, well-documented issue that open source projects appreciate.

### Submission Checklist

- [ ] Verify no existing eyecite issue covers this
- [ ] Run reproduction code against latest eyecite release
- [ ] Draft issue with minimal reproduction + impact numbers
- [ ] Submit issue
- [ ] Update this doc with link

---

## 4. eyecite: Apostrophe Truncates Case Name Words

**Status:** READY
**Target:** eyecite ([https://github.com/freelawproject/eyecite](https://github.com/freelawproject/eyecite))
**Type:** Bug fix PR

### Summary

eyecite's case name extraction regexes use `[\w\-.]+` to match words, but `\w` excludes apostrophes. Legal abbreviations with internal apostrophes (`Att'y`, `Dep't`, `Gov't`, `Comm'n`, `P'ship`, `Nat'l`, `Sec'y`) are truncated at the apostrophe, losing the suffix.

### Root Cause

Three regexes in `eyecite/regexes.py` use character classes that don't include apostrophes:

| Line | Regex | Purpose |
|------|-------|---------|
| 266 | `SHORT_CITE_ANTECEDENT_REGEX`: `[\w\-.]+` | Short cite antecedents ("Adarand, 515 U.S. at 241") |
| 278, 280 | `SUPRA_ANTECEDENT_REGEX`: `[\w\-.]+` | Supra cite antecedents |
| 336 | `PRE_FULL_CITATION_REGEX`: `[a-z\-.]+` | Backward scan for case names before full citations |

### Evidence

```python
from eyecite import get_citations
from eyecite.models import FullCaseCitation

cases = [
    ("Att'y Grievance Comm'n v. Glenn, 341 Md. 448 (2003).",
     "Att'y Grievance Comm'n", "Att' Grievance Comm'"),
    ("Keaau Dev. P'ship LLC v. Lawrence, 571 P.3d 958 (2025).",
     "Keaau Dev. P'ship LLC", "Keaau Dev. P' LLC"),
    ("Am. Nat'l Ins. Co. v. FDIC, 642 F.3d 1137 (2011).",
     "Am. Nat'l Ins. Co.", "Am. Nat' Ins. Co."),
]

for text, expected_plaintiff, actual_plaintiff in cases:
    c = [c for c in get_citations(text) if isinstance(c, FullCaseCitation)][0]
    p = c.metadata.plaintiff or ''
    print(f"Expected: {expected_plaintiff}")
    print(f"Actual:   {p}")
    # All cases: suffix after apostrophe is dropped
```

**Affected abbreviations (standard Indigo Book terms):**
- `Att'y` (Attorney) → `Att'`
- `Dep't` (Department) → `Dep'`
- `Gov't` (Government) → `Gov'`
- `Comm'n` (Commission) → `Comm'`
- `Comm'r` (Commissioner) → `Comm'`
- `P'ship` (Partnership) → `P'`
- `Nat'l` (National) → `Nat'`
- `Int'l` (International) → `Int'`
- `Sec'y` (Secretary) → `Sec'`
- `Ass'n` (Association) → `Ass'`
- `Adm'r` (Administrator) → `Adm'`

**Scale of impact (our corpus):** 8 case names directly affected across 19 PDFs. These abbreviations are extremely common in legal citations generally.

### Proposed Fix

Change three character classes to include straight and curly apostrophes:

```python
# Line 266 (SHORT_CITE_ANTECEDENT_REGEX)
# Before:
[\w\-.]+
# After:
[\w\-.'\u2019]+

# Line 278, 280 (SUPRA_ANTECEDENT_REGEX)
# Same change

# Line 336 (PRE_FULL_CITATION_REGEX)
# Before:
[a-z\-.]+
# After:
[a-z\-.'\u2019]+
```

Including `\u2019` (right single quotation mark / curly apostrophe) handles PDFs that use Unicode typography.

### Risk Assessment

**Low risk:**
- These regexes already allow periods (`.`) and hyphens (`-`), so apostrophes are consistent
- Legal abbreviations with internal apostrophes are well-defined and unambiguous
- Possessives (e.g., "Smith's") are unlikely to appear at word boundaries in case names
- Change is additive — existing matches are unaffected, only previously-truncated words are now captured fully

### Plan

We plan to **fork eyecite and submit a PR** with this fix alongside the ParagraphToken fix (item #3 above). Both are small, focused changes that can be reviewed independently.

### Submission Checklist

- [ ] Fork eyecite repository
- [ ] Create branch for apostrophe fix
- [ ] Make the three regex changes
- [ ] Add test cases for affected abbreviations
- [ ] Verify existing eyecite tests still pass
- [ ] Open PR with reproduction examples and impact data
- [ ] Update this doc with PR link

---

## 5. Federal District Court Opinions Only in RECAP (Not in Opinions DB)

**Status:** DRAFT
**Target:** CourtListener issue [#3790](https://github.com/freelawproject/courtlistener/issues/3790) (closed Oct 2025)
**Type:** Data contribution / Comment on closed issue

### Summary

Federal district court opinions that exist in RECAP (PACER docket data) are not always present in the opinions database (`type=o` search). Our verification pipeline falls back to RECAP search (Step 3) for these cases, finding the document but scoring it lower due to the RECAP discount.

### Our Findings

**From verification run 2026-02-11 (seed 42, 50 citations):**

9 of 50 citations (18%) were found only via RECAP, all federal district courts. After removing 2 false matches and 1 duplicate, **6 unique real cases** were RECAP-only:

| Case | Court | Year | Type | Notes |
|------|-------|------|------|-------|
| Welfare Fund v. HoosierVac LLC | S.D. Ind. | 2025 | Civil | Order on Motion for Reconsideration |
| Dukuray v. Experian Info. Sols. | S.D.N.Y. | 2024 | Civil | Order Adopting Report and Recommendations |
| United States v. Hayes | (F.Supp.3d) | 2025 | **Criminal** | Memorandum Opinion and Order |
| Russomanno v. Comm'r of Soc. Sec. | M.D. Fla. | 2025 | Civil | Order on Social Security Brief |
| King v. Police & Fire Fed. Credit Union | E.D. Pa. | 2019 | Civil | Memorandum and/or Opinion Order |
| Glass v. Foley & Lardner LLP | W.D. Wis. | 2025 | Civil | Order on Motion for Discovery |

### Relationship to #3790

FLP's [#3790 (RECAP into Opinions)](https://github.com/freelawproject/courtlistener/issues/3790) converted 317,728+ civil RECAP documents into opinion records (completed Oct 2025). However:

1. **Criminal cases not yet processed** — Hayes is criminal, explaining why it's missing. Criminal and bankruptcy are planned future phases per #4642.
2. **5 civil cases still missing** — These should have been caught by #3790's civil batch. Possible explanations:
   - Filed/ingested after the batch ran (4 of 5 are 2025 cases)
   - The `recap_into_opinions` command may not run continuously
   - Edge cases missed by the LLM-based case name extraction ([PR #6290](https://github.com/freelawproject/courtlistener/pull/6290))
3. **King v. Police & Fire (2019)** is the oldest and most puzzling — a 2019 civil case should have been in the initial batch.

### Related Issues

- [#3790](https://github.com/freelawproject/courtlistener/issues/3790) — RECAP into Opinions (closed Oct 2025, civil cases done)
- [#4642](https://github.com/freelawproject/courtlistener/issues/4642) — Index cleanup, notes criminal cases still pending
- [#6213](https://github.com/freelawproject/courtlistener/issues/6213) — Parent issue for LLM document ingestion
- [#6065](https://github.com/freelawproject/courtlistener/issues/6065) — ~500 trial court docs ingested since June 2025 lacked HTML with citations (fixed)
- [#6514](https://github.com/freelawproject/courtlistener/issues/6514) — 458 RECAP-sourced opinions have HTML in case name slugs

### Decision Factors

**Pros:**
- Concrete data showing the gap persists post-#3790
- Specific cluster/docket IDs FLP can investigate
- Helps assess whether `recap_into_opinions` needs to run more frequently or continuously
- 18% RECAP-only rate in our sample is significant

**Cons:**
- #3790 is closed — FLP may consider this done for now
- Most of our cases are very recent (2025) — may just need time to be processed
- Small sample size (50 citations)
- Criminal gap is already known (#4642)

**Recommendation:** Wait and collect more data. Run another verification sample in a few months. If the RECAP-only rate remains high for civil cases, comment on #3790 with our data. The King v. Police & Fire (2019) case is worth investigating individually — if it was missed by the civil batch, that's a concrete bug to report.

### Submission Checklist

- [ ] Collect more data (target: 100+ citation sample)
- [ ] Verify King v. Police & Fire (2019) specifically — is it in CL opinions at all?
- [ ] Check if any of the 2025 cases appear in opinions DB after a few weeks
- [ ] If pattern persists, comment on #3790 with data
- [ ] Update this doc with findings

---

## 6. Data Quality Issues

**Status:** DRAFT
**Target:** CourtListener (TBD - may be multiple issues)
**Type:** Data quality reports

### Issues to Track

As we encounter data quality problems, document them here:

**State court coverage gaps:**
- Status: 5 confirmed cases missing from CL
- Examples:
  1. **Rupnow v. Mont. State Auditor & Comm'r of Ins., 542 P.3d 384 (Mont. 2024)** — Montana Supreme Court opinion not in CL at all. Verified real citation (likely_real classification). Source: Thornton v. Flathead County PDF.
  2. **Jindrich v. Weihele, 656 S.W.3d 519 (Tex. App. 2022)** — Texas Court of Appeals. CL has a different opinion for this case (cluster 5174585, "Edward S. Jindrich, Jr. v. Michaela Weihele") but it appears to be the wrong document — the opinion at 656 S.W.3d 519 is not available. Source: Suday v. Suday PDF.
  3. **Jha v. Khan, 520 P.3d 470, 477 (Wash. Ct. App. 2022)** — Washington Court of Appeals. Not in CL. Available at https://www.courts.wa.gov/opinions/pdf/837681.pdf
  4. **Fowler v. Guerin, 515 P.3d 502, 506 (Wash. 2022)** — Washington Supreme Court. Not in CL. Available at https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.showOpinion&filename=1000693MAJ
  5. **M.G. v. Bainbridge Island School District #303, 566 P.3d 132, 147 (Wash. Ct. App. 2025)** — Washington Court of Appeals. Not in CL.
- Action: Collect more examples before reporting. Known CL limitation (#5 in Known CL API Limitations). Washington state courts appear to be a systemic gap (3 of 5 examples).

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
