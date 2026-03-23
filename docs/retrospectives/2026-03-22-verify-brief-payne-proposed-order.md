# Verify-Brief Skill Retrospective

## Run: State of Georgia v. Hannah Renee Payne (2026-03-22)

**Case:** Case No. 2019CR01737-14 (Superior Court of Clayton County, GA)
**Document:** Proposed Order Denying Defendant's Motion for New Trial as Amended
**Prepared by:** Deborah Leslie, Assistant District Attorney, Appellate Division, Clayton Judicial Circuit
**Source:** User-provided PDF (`briefs/payne-proposed.pdf`)

### Brief Stats
- 37-page proposed order, 53 unique case citations, 84 proposition-case pairs
- Result: **48 Green (57%), 16 Yellow (19%), 20 Red (24%)**
- Citation lookup: 44 VERIFIED, 5 POSSIBLE_MATCH, 2 NOT_FOUND (wave 1), both NOT_FOUND resolved in wave 2
- Quote check: 14 VERBATIM, 2 CLOSE, 8 FABRICATED, 65 NO_QUOTES
- **Notable:** This is a state-court criminal order (Georgia), not a federal brief. First run on Georgia caselaw — mostly state reporter citations (Ga., Ga. App.) rather than federal reporters.

### Key Findings

**Wrong case at citation (5 citations, 7 claims):**
- **Reynolds v. State, 306 Ga. 630 (2019)** — cited twice (pp. 12, 24) for adopting the Strickland test in Georgia. Actually resolves to Bailey v. State, a short opinion about denial of an out-of-time appeal. Has nothing to do with adopting Strickland.
- **Harbuck v. State, 288 Ga. 768 (2011)** — cited for citizen's arrest immediacy requirement. Actually State v. Rozier, a quiet title property action about island ownership. Completely unrelated to criminal law.
- **Bryant v. State, 268 Ga. App. 362 (2004)** — cited for witness testimony requirements. Actually In the Interest of D.L., a termination of parental rights case.
- **Jones v. State, 283 Ga. 155 (2008)** — cited for declining to find prejudice from omitted instructions. Actually Moore v. State at that citation. (Moore is partially related, so Yellow.)
- **Patel v. State, 279 Ga. 50** — confirmed typo. The correct citation is 279 Ga. 750 (which is correctly cited elsewhere in the order). 279 Ga. 50 is Smith v. State.

**Case exists but doesn't address the cited topic (8 citations, 12 claims):**
- **Manzano v. State, 282 Ga. 557 (2007)** — cited 3x for justification subsuming citizen's arrest. Actually about involuntary manslaughter instructions and cross-examination. Never mentions justification or citizen's arrest. Includes fabricated quotes.
- **State v. Rumph, 307 Ga. 477 (2019)** — cited 2x for IAC/strategic decisions deference. Actually a Miranda/custody suppression case. Never discusses IAC.
- **Davis v. State, 285 Ga. 343 (2009)** — cited 3x for IAC re: jury instructions and citizen's arrest deadly force. Actually about accident jury instructions in a stabbing case. No IAC analysis whatsoever.
- **Durden v. State, 327 Ga. App. 173 (2014)** — cited for citizen's arrest/justification. Actually about accident defense in a sword assault. Fabricated quote.
- **Lang v. State, 344 Ga. App. 623 (2018)** — cited for citizen's arrest defense. Actually about gang activity and firearm possession. Fabricated quote.
- **State v. Kelly, 290 Ga. 29 (2011)** — cited for justification charge covering citizen's arrest. Actually about felony murder instructions on inherent dangerousness of predicate felony.
- **Virgil v. State, 227 Ga. App. 96** — cited 2x for citizen's arrest charge requirements. Actually a DUI case about actual physical control of a vehicle.
- **Goldsby v. State, 273 Ga. App. 523 (2005)** — cited for "testimony of a single witness is generally sufficient." Actually discusses the opposite: accomplice corroboration requirements. Fabricated quote.

**Pattern:** The problematic citations cluster heavily in the citizen's arrest / justification sections (pp. 15, 27-31). The Strickland IAC framework citations (pp. 12, 16-17, 24-26) and the sufficiency-of-evidence citations (pp. 33-35) are all accurate. This suggests the citizen's arrest legal analysis may have been drafted differently (possibly AI-assisted) from the rest of the order.

---

## Phase-by-Phase Notes

### Phase 1a: Extract Citations
- **Smooth.** PDF read in two chunks (1-20, 21-37). Clear formatting.
- **53 unique case citations** extracted. One citation omitted per rules: United States v. Valenzuela-Bernal (1982) has no reporter citation in the brief.
- **Citation inconsistency caught:** Patel v. State appears as both 279 Ga. 750 (pp. 29, 33) and 279 Ga. 50 (p. 31). Both variants included per skill rules. Verification confirmed the 279 Ga. 50 is a typo (resolves to Smith v. State).

### Phase 1b: Wave 1 Verify
- 44 VERIFIED, 5 POSSIBLE_MATCH, 2 NOT_FOUND in ~1 minute.
- Wave 2 resolved both NOT_FOUNDs (Reynolds v. State, Lang v. State). 51 opinion texts downloaded.

### Phase 1c: Propositions + Merge
- **76 propositions extracted** by Opus agent. After merge: **84 matched, 0 unmatched.** Clean merge — no fixups needed.
- The increased claim count (84 vs 76 extracted) is because some citations appear in both the written and oral enumeration sections, producing duplicate propositions matched to the same opinion.

### Phase 1d: Quote Check + Haiku Summaries
- Quote check: 14 VERBATIM, 2 CLOSE, **8 FABRICATED**, 65 NO_QUOTES.
- All 8 FABRICATED quotes are in the brief's text — the brief puts words in quotation marks that do not appear in the cited opinion. This is not an error in our pipeline.
- **29 opinions >= 20K chars** sent to Haiku summarizers (7 batches, run in parallel). 22 opinions < 20K skipped.
- Haiku summaries were valuable for catching topic mismatches early (e.g., Durden = sword assault/accident, Lang = gang activity, Kelly = felony murder dangerousness). These findings were passed as hints to Phase 2 agents.

### Phase 2: Assess Claims
- **6 Opus assessment agents** launched in parallel:
  1. Strickland (8 claims) — all Green, used summary
  2. POSSIBLE_MATCH cases (7 claims) — 4 Red, 2 Yellow, 1 Red
  3. Small opinions group A (18 claims) — read directly
  4. Small opinions group B (13 claims) — read directly
  5. Big opinions group A (12 claims) — read with Haiku hints
  6. Big opinions group B (26 claims) — read full opinions
- Big opinions group B was the slowest (128s, 186K tokens, 28 tool uses) — too many opinions in one batch. Should have split.
- Total assessment time: ~2-3 minutes (parallelized).

### Phase 4: Report
- Initial report generated with a simple format. User requested Kettering-style report with:
  - "Retrieved" column showing what CL actually found (with links)
  - Quote comparisons: exact brief text shown with VERBATIM/CLOSE/FABRICATED tags
  - Color-coded passage blocks
  - Compact Green table (no supporting language column)
- Rebuilt report via `build_report.py` script in the working directory.

---

## Timing & Cost

| Phase | Wall Clock | Notes |
|-------|-----------|-------|
| Phase 1a (extract) | ~2 min | PDF read + citation extraction |
| Phase 1b (wave 1) | ~1 min | 53 CL API calls |
| Phase 1c (propositions + wave 2) | ~2 min | Concurrent: Opus extraction + wave 2 |
| Phase 1d (quote check + summaries) | ~2 min | Quote check + 7 Haiku agents parallel |
| Phase 2 (assessment) | ~3 min | 6 Opus agents parallel |
| Phase 4 (report) | ~1 min | Script generation |
| **Total** | **~15-20 min** | |

**Token usage (estimated):**
- Haiku: ~346K tokens (~$0.52)
- Opus: ~676K tokens (~$20.29)
- **Total: ~$21**

**CourtListener API calls:** ~58

---

## A/B Testing Infrastructure (New)

Built an A/B testing harness during this session to compare assessment approaches:

**Files created:**
- `tests/ab_test_cases.json` — 27 ground-truth test cases extracted from this run (9 Red, 13 Green, 5 Yellow)
- `tests/ab_test_configs.json` — 4 configs: opus-baseline, sonnet-baseline, sonnet-with-hints, opus-with-hints
- `tests/ab_test_runner.py` — Harness using `claude -p` (headless mode) to run test cases without API costs

**First A/B result — Sonnet baseline:**
- 22/27 correct (81%)
- Green: 13/13 (100%) — Sonnet never misses a supported citation
- Red: 7/9 (78%) — missed State v. Kelly (called Green) and Virgil (called Yellow)
- Yellow: 2/5 (40%) — tends to over-call Red on borderline cases
- Cost: $2.54, 427s total (15.8s/case avg)

**Next experiments to run:**
- Opus baseline (compare accuracy on the 5 Sonnet misses)
- Sonnet with Haiku hints (can hints compensate for smaller model?)
- Batch mode (send all claims for one opinion together, matching real pipeline conditions)

---

## Issues & Improvements

### Report Format
- **User preference:** Kettering-style report with quote comparisons, Retrieved column, color-coded passages. This should be the default going forward.
- **Action:** Update SKILL.md Phase 4 to reference `build_report.py` pattern or add `--report` CLI command.

### Haiku Summary Value
- Haiku summaries correctly identified topic mismatches (Durden, Lang, Kelly, Virgil) that some Phase 2 agents also caught independently. Value is unclear — A/B test the "with hints" vs "without hints" configs to quantify.
- At $0.52 for 29 summaries, cost is negligible. Question is whether they improve Opus/Sonnet accuracy.

### Assessment Agent Batching
- Big opinions group B (26 claims) was too large: 186K tokens, 128s. Split into 2-3 agents for better parallelism.
- Consider capping at ~15 claims per agent.

### Georgia State Court Coverage
- All 53 citations resolved on CourtListener (after wave 2). Georgia state reporters (Ga., Ga. App.) have good coverage.
- State court IDs from eyecite worked via direct string match as expected.

### Citizen's Arrest Section Quality
- 12 of 20 Red assessments come from the citizen's arrest / justification / defense-of-others sections (pp. 15, 27-31). These sections cite cases that are completely unrelated to the cited propositions.
- The Strickland/IAC sections (pp. 12, 16-17, 24-26) and sufficiency-of-evidence sections (pp. 33-35) are almost entirely accurate (all Green).
- This pattern is consistent with selective AI-assisted drafting of specific legal argument sections.

### A/B Test Infrastructure
- Harness works end-to-end using `claude -p` headless mode (no API costs beyond subscription).
- Ground truth needs expansion: add Kettering test cases, and eventually other briefs.
- Yellow cases are the hardest to get consistent results on — these are genuinely borderline and may need more nuanced expected values (e.g., "Yellow or Red" acceptable range).
