# Haiku Prescreen Test: Fletcher v. Experian

## Test Date: 2026-03-10

**Brief:** Fletcher v. Experian, No. 25-20086 (5th Cir.)
**Claims:** 59 proposition-case pairs across 19 opinions
**Ground truth:** Opus-direct assessments from initial verify-brief run

## Two Runs Performed

1. **Run 1 (Opus summaries):** Summary agents ran on Opus 4.6 (general-purpose subagent). Not a true Haiku prescreen test.
2. **Run 2 (Haiku summaries):** Summary agents ran on Haiku via Explore subagent. Proper apples-to-apples comparison with the prior 3-brief test.

Both runs used Opus for the assessment phase. Edwards (19K chars, under 20K threshold) was read directly by Opus in both runs.

---

## Results Comparison

| Metric | Prior 3-Brief | Run 1 (Opus sum) | Run 2 (Haiku sum) |
|--------|--------------|------------------|-------------------|
| Total claims | 102 | 59 | 59 |
| **Exact match** | **76%** | **64%** | **75%** |
| Conservative | 21% | 24% | 22% |
| **Lenient** | **3%** | **12%** | **3%** |
| R->G | 0 | 1 | 0 |
| R->Y | 2 | 2 | 1 |
| Y->G | 1 | 4 | 1 |

**Run 2 (Haiku) nearly matches the prior 3-brief test.** The Opus-summary run was significantly worse due to richer summaries providing more "topically adjacent" material for false upgrades.

---

## Run 2 (Haiku) Detailed Results

### Summary statistics

| Metric | Count | Rate |
|--------|-------|------|
| Total claims | 59 | |
| Exact match | 44 | 75% |
| Conservative | 13 | 22% |
| Lenient | 2 | 3% |

### Conservative breakdown
| Direction | Count | Rows |
|-----------|-------|------|
| G -> Y | 4 | 32 (Hensley), 45 (Matta), 51 (Childs), 52 (Mendez) |
| G -> R | 0 | |
| Y -> R | 9 | 1, 31, 37, 38 (Vaughan), 39 (Cooter), 8 (Morrison), 40 (Bryant), 44, 56 (Lewis) |

### Lenient breakdown (false upgrades)
| Direction | Count | Rows |
|-----------|-------|------|
| R -> G | 0 | |
| R -> Y | 1 | 16 (Cooter -- fabricated quote at p.393, principle at pp.403-404) |
| Y -> G | 1 | 4 (Coghlan -- "no desire to deter" language rated Green, GT Yellow) |

### Full Row-by-Row Comparison

| Row | Opinion | GT | Run1 | Run2 | R1 Match | R2 Match | Notes |
|-----|---------|-----|------|------|----------|----------|-------|
| 1 | Vaughan | Y | Y | R | Y | conserv | Haiku more emphatic about topics not found |
| 2 | Cooter | Y | R | Y | conserv | Y | Haiku summary fixed this |
| 3 | Vaughan | Y | Y | Y | Y | Y | |
| 4 | Coghlan | Y | Y | G | Y | lenient | Haiku included "no desire to deter" quote |
| 5 | Edwards | R | R | R | Y | Y | Read directly |
| 6 | Morrison | G | G | G | Y | Y | |
| 7 | Peterson | Y | Y | Y | Y | Y | |
| 8 | Morrison | Y | Y | R | Y | conserv | Haiku noted standard is reckless disregard not bad faith |
| 9 | Morrison | G | G | G | Y | Y | |
| 10 | Morrison | R | R | R | Y | Y | |
| 11 | Freeh | R | R | R | Y | Y | |
| 12 | Freeh | R | R | R | Y | Y | |
| 13 | Edwards | R | R | R | Y | Y | Read directly |
| 14 | Miller | R | R | R | Y | Y | |
| 15 | Fox | R | R | R | Y | Y | |
| 16 | Cooter | R | **G** | Y | **R->G** | R->Y | Haiku downgraded from false Green to false Yellow |
| 17 | Fox | R | R | R | Y | Y | |
| 18 | Cooter | Y | Y | Y | Y | Y | |
| 19 | Fox | R | R | R | Y | Y | |
| 20 | Cooter | Y | G | Y | lenient | Y | Haiku fixed this false upgrade |
| 21 | Puckett | R | R | R | Y | Y | |
| 22 | Puckett | Y | G | Y | lenient | Y | Haiku fixed this false upgrade |
| 23 | Freeh | R | R | R | Y | Y | |
| 24 | Edwards | R | R | R | Y | Y | Read directly |
| 25 | Vaughan | R | Y | R | lenient | Y | Haiku fixed this false upgrade |
| 26 | Fox | G | G | G | Y | Y | |
| 27 | Fox | R | R | R | Y | Y | |
| 28 | Vaughan | R | R | R | Y | Y | |
| 29 | Fox | G | G | G | Y | Y | |
| 30 | Vaughan | R | Y | R | lenient | Y | Haiku fixed this false upgrade |
| 31 | Vaughan | Y | R | R | conserv | conserv | Both runs flagged "flat percentage" |
| 32 | Hensley | G | Y | Y | conserv | conserv | Both runs assessed as loose paraphrase |
| 33 | Vaughan | Y | Y | Y | Y | Y | |
| 34 | Fox | Y | Y | Y | Y | Y | |
| 35 | Fox | G | G | G | Y | Y | |
| 36 | Vaughan | Y | R | Y | conserv | Y | Haiku fixed this -- now matches GT |
| 37 | Vaughan | Y | R | R | conserv | conserv | Both flagged "bulk allocation" |
| 38 | Vaughan | Y | R | R | conserv | conserv | Both flagged "line-item segregation" |
| 39 | Cooter | Y | G | R | lenient | conserv | Haiku flipped from false upgrade to conservative |
| 40 | Bryant | Y | R | R | conserv | conserv | Both: proposition not stated |
| 41 | In re Case | Y | Y | Y | Y | Y | |
| 42 | Coghlan | G | G | G | Y | Y | |
| 43 | Bryant | G | G | G | Y | Y | |
| 44 | Lewis | Y | R | R | conserv | conserv | Both: standard is vexatious multiplication |
| 45 | Matta | G | R | Y | conserv | conserv | Haiku less severe (G->Y vs G->R) |
| 46 | Cooter | Y | G | Y | lenient | Y | Haiku fixed this false upgrade |
| 47 | Fox | R | R | R | Y | Y | |
| 48 | Cooter | Y | R | Y | conserv | Y | Haiku fixed this |
| 49 | Vaughan | Y | Y | Y | Y | Y | |
| 50 | Coghlan | Y | Y | Y | Y | Y | |
| 51 | Childs | G | Y | Y | conserv | conserv | Both: editorial addition |
| 52 | Mendez | G | R | Y | conserv | conserv | Haiku less severe (G->Y vs G->R) |
| 53 | Thomas | G | G | G | Y | Y | |
| 54 | Donaldson | Y | Y | Y | Y | Y | |
| 55 | In re Case | Y | Y | Y | Y | Y | |
| 56 | Lewis | Y | R | R | conserv | conserv | Both: same as Row 44 |
| 57 | Fox | R | R | R | Y | Y | |
| 58 | Cooter | Y | R | Y | conserv | Y | Haiku fixed this |
| 59 | Vaughan | Y | Y | Y | Y | Y | |

### Analysis by Opinion (Run 2 / Haiku)

| Opinion | Claims | Match | Conserv | Lenient |
|---------|--------|-------|---------|---------|
| Vaughan | 12 | 8 (67%) | 4 | 0 |
| Fox | 10 | 10 (100%) | 0 | 0 |
| Cooter Gell | 8 | 6 (75%) | 1 | 1 |
| Morrison | 4 | 3 (75%) | 1 | 0 |
| Edwards | 3 | 3 (100%) | 0 | 0 |
| Freeh/Deepwater | 3 | 3 (100%) | 0 | 0 |
| Coghlan | 3 | 2 (67%) | 0 | 1 |
| Bryant | 2 | 1 (50%) | 1 | 0 |
| Puckett | 2 | 2 (100%) | 0 | 0 |
| In re Case | 2 | 2 (100%) | 0 | 0 |
| Lewis | 2 | 0 (0%) | 2 | 0 |
| Others (7) | 7 | 4 (57%) | 3 | 0 |

---

## Key Findings

### 1. Haiku summaries outperform Opus summaries for this pipeline

This is the most important finding. Haiku summaries produced a 75% match rate and 3% false upgrade rate, vs. Opus summaries at 64% match and 12% false upgrades. The reason: **Opus summaries are too rich.** They include more "topically adjacent" passages that enable false Green/Yellow assessments. Haiku's more focused summaries are actually better for this task.

### 2. Cooter Gell improved dramatically (13% -> 75%)

The biggest improvement. In Run 1, Cooter Gell had 4 false upgrades (Y->G). In Run 2, only 1 lenient mismatch remains (Row 16, R->Y for fabricated quote). The Haiku summary was more cautious about what the opinion actually holds vs. what it merely discusses.

### 3. Vaughan improved (50% -> 67%)

The two false upgrades (Rows 25, 30) from Run 1 were fixed — Haiku's emphatic "all ten propositions are fundamentally inapplicable" in TOPICS NOT FOUND made the assessor correctly rate Red. But Row 1 flipped from match to conservative, suggesting the emphatic language may have been slightly too strong.

### 4. Zero R->G false upgrades

The most dangerous failure mode (Red case rated Green) occurred once in Run 1 but zero times in Run 2. Row 16 (Cooter, fabricated quote) was downgraded from the R->G false upgrade to a milder R->Y.

### 5. The 2 remaining false upgrades are both mild

- **Row 16 (R->Y):** Cooter Gell fabricated quote. The principle IS in the case at pp.403-404, just not at p.393 where the brief cites it. A separate verbatim-quote checker would catch this.
- **Row 4 (Y->G):** Coghlan "no desire to deter" language. The quote is real; GT rated Yellow because the opinion's overall thrust is pro-sanctions. A reasonable disagreement.

### 6. Conservative mismatches are stable and safe

13 conservative mismatches (22%) — comparable to the prior 3-brief test (21%). The pattern is consistent: H->O is stricter about fabricated legal terminology ("line-item segregation," "causation segregation," "bad faith" when standard is vexatious multiplication). This is safe for a tool catching misrepresented case law.

---

## Combined 4-Brief Statistics (Run 2 Haiku + Prior 3 Briefs)

| Metric | Prior 3-Brief | Fletcher (Haiku) | Combined |
|--------|--------------|------------------|----------|
| Total claims | 102 | 59 | 161 |
| Exact match | 78 (76%) | 44 (75%) | 122 (76%) |
| Conservative | 21 (21%) | 13 (22%) | 34 (21%) |
| Lenient | 3 (3%) | 2 (3%) | 5 (3%) |
| R->G | 0 | 0 | 0 |
| R->Y | 2 | 1 | 3 |
| Y->G | 1 | 1 | 2 |

**161 claims across 4 briefs: 76% exact match, 21% conservative, 3% lenient, 0 R->G.**

---

---

## Four-Way Comparison: Court vs. RealityCheck vs. GT (Opus-direct) vs. H->O (Haiku prescreen)

### Mapping convention

GT = Opus reading full opinion (ground truth from initial verify-brief run)
H->O = Haiku summary -> Opus assessment (Run 2)
"Worst" = most critical assessment across all relevant rows for that citation

| Citation | Court | RealityCheck | GT (Opus-direct) | H->O (Haiku prescreen) |
|----------|-------|-------------|-------------------|------------------------|
| Fox (834-36 quote) | Fabricated | Fabricated + misstated | Red | Red |
| Fox (836 but-for quotes) | Fabricated (3) | (bundled) | **Green** (missed) | **Green** (missed) |
| Cooter (393 quote) | Fabricated | Fabricated | Red (row 16) | Yellow (row 16) -- partial miss |
| Cooter (397 quote) | Fabricated | (bundled) | Yellow (row 39) | **Red** (row 39) -- improved |
| Deepwater Horizon (2 quotes) | Fabricated + misrep | Misstated | Red | Red |
| Vaughan (2 quotes) | Fabricated | "Couldn't verify" | Red + Yellow | **Red** (rows 25,30 fixed) |
| Bryant (quote) | Fabricated | Wrong case + fabricated | Yellow (row 40) | **Red** (row 40) -- improved |
| In re Case (quote) | Fabricated | Fabricated | Yellow | Yellow |
| Mendez (quote) | Fabricated | Misstated | **Green** (missed) | **Yellow** (row 52) -- improved |
| Thomas (quote) | Fabricated + misstated | Fabricated | **Green** (missed) | **Green** (missed) |
| Donaldson (quote) | Fabricated | (not listed) | Yellow | Yellow |
| Bridgecrest brief quote | Fabricated | N/A (not a case) | N/A (out of scope) | N/A (out of scope) |
| Edwards | Misrepresentation | Misstated | Red | Red |
| Deepwater (informal notice) | Misrepresentation | (bundled) | Red | Red |
| "No Rule 11 motion served" | Misrepresentation | N/A (record fact) | N/A (out of scope) | N/A (out of scope) |
| Miller | Misrepresentation | Misstated | Red | Red |
| Lewis | Misrepresentation | **Not flagged** | Yellow | **Red** -- improved |
| Puckett | **Not flagged** | Fabricated + misstated | Red | Red |
| Morrison (row 10) | **Not flagged** | Material fact error | **Red** (unique find) | **Red** (unique find) |
| Hensley | **Not flagged** | Misstated | **Green** (missed) | **Yellow** -- improved |
| 28 U.S.C. 1927 standard | **Not flagged** | Wrong statutory standard | N/A (out of scope) | N/A (out of scope) |
| Peterson | **Not flagged** | Caution (overbroad) | Yellow | Yellow |
| Matta | **Not flagged** | Misstated + wrong standard | Green | Yellow -- conservative |
| Childs | **Not flagged** | Misstated | Green | Yellow -- conservative |

### H->O vs. GT: What changed?

**H->O caught things GT missed (improved):**
- **Mendez** (row 52): GT=Green, H->O=Yellow. Haiku summary noted sanctions discussion is about inherent powers, not Rule 11. Opus assessor correctly downgraded.
- **Hensley** (row 32): GT=Green, H->O=Yellow. Haiku noted Hensley frames fee allocation around "results obtained," not "causation." Assessor caught the concept substitution.
- **Cooter 397** (row 39): GT=Yellow, H->O=Red. Haiku didn't find fee-shifting prohibition as a primary holding, so assessor rated Red.
- **Bryant** (row 40): GT=Yellow, H->O=Red. Haiku confirmed "collateral to merits" not stated.
- **Lewis** (rows 44,56): GT=Yellow, H->O=Red. Haiku correctly identified "vexatious multiplication" standard, not bad faith.
- **Vaughan scope** (rows 25,30): GT=Red but Run 1 false-upgraded to Yellow. Haiku's emphatic TOPICS NOT FOUND kept it at Red.
- **Matta** (row 45): GT=Green, H->O=Yellow. Haiku noted sec 1927 discussion limited to client/attorney distinction.
- **Childs** (row 51): GT=Green, H->O=Yellow. Haiku flagged editorial additions.

**H->O missed things GT caught (regressed):**
- **Cooter 393** (row 16): GT=Red, H->O=Yellow. Haiku summary included the real temporal-anchoring passage at pp.403-404; assessor saw it as partial support and rated Yellow. GT rated Red because the exact quote at p.393 is fabricated. One-step regression (R->Y).
- **Coghlan** (row 4): GT=Yellow, H->O=Green. Haiku included the "no desire to deter" quote; assessor rated Green. GT Yellow because opinion's overall thrust is pro-sanctions. One-step regression (Y->G).

**Same misses as GT:**
- **Fox but-for quotes** (rows 26,29,35): Both Green. The substance is right (Fox does hold this). The court flagged these because the specific quoted words in the brief are fabricated. This gap requires a verbatim-quote checker, not a better summary.
- **Thomas** (row 53): Both Green. Same issue -- substance is right, but the brief's quoted language doesn't appear verbatim.

### vs. the Court (16 fabricated quotes + 5 misrepresentations = 21 issues)

| Metric | GT (Opus-direct) | H->O (Haiku prescreen) |
|--------|-------------------|------------------------|
| Issues caught (Red or Yellow) | 19 of 21 (90%) | 19 of 21 (90%) |
| Caught at Red | 14 | **17** (+3) |
| Caught at Yellow only | 5 | 2 |
| False negatives (Green) | 5 | **3** (-2) |
| Out of scope | 2 | 2 |

H->O catches the same 19/21 issues but is **stricter on severity**: 17 Red vs GT's 14 Red. This is the conservative bias working correctly -- three citations that GT rated Yellow (Cooter 397, Bryant, Lewis) are now Red, matching the court's assessment more closely.

The 3 remaining false negatives (Green when court said fabricated) are all the same type: **substance correct, quote fabricated.** Fox rows 26/29/35 and Thomas row 53 need a verbatim-quote checker, not better assessment.

### vs. BriefCatch RealityCheck

**RC caught that H->O also now catches:**
- **Hensley framing**: GT=Green, H->O=Yellow. Both RC and H->O now flag this.

**RC caught that H->O still misses:**
- **Bryant 97 F.3d wrong reporter**: Deterministic Layer 1 catch. Still a pipeline gap.
- **28 U.S.C. 1927 statutory standard**: Out of scope (statute, not case citation).

**H->O catches that RC missed (maintained from GT):**
- **Vaughan substance**: H->O Red, matching court. RC hedged.
- **Lewis v. Brown & Root**: H->O Red (improved from GT Yellow). RC missed entirely.
- **Morrison row 10**: H->O Red. Neither RC nor court flagged this.
- **Fox additional misattributions**: H->O Red on rows 15,17,19,27,47,57.

**H->O uniquely improves over both GT and RC:**
- **Mendez**: GT=Green, RC="Misstated", H->O=Yellow. H->O now agrees with RC that something is off.
- **Matta**: GT=Green, RC="Misstated", H->O=Yellow. H->O now agrees with RC.
- **Childs**: GT=Green, RC="Misstated", H->O=Yellow. H->O now agrees with RC.

---

## Summary Scorecard

| Source | Issues flagged | False negatives | Unique finds |
|--------|---------------|-----------------|--------------|
| Court (21 issues) | 21 | 0 | 2 (vs us/RC) |
| RealityCheck | ~17 | 1 (Lewis) | 2 (Bryant reporter, 1927 statute) |
| GT (Opus-direct) | 19 + Morrison | 5 (Green for fabricated quotes) | 1 (Morrison) |
| **H->O (Haiku prescreen)** | **19 + Morrison** | **3** (Fox but-for, Thomas) | **1 (Morrison)** |

The Haiku prescreen reduces GT's false negatives from 5 to 3 while maintaining all unique finds. It catches 3 additional citations that RC flagged but GT missed (Mendez, Matta, Childs at Yellow). The only regression is Cooter row 16 (R->Y) and Coghlan row 4 (Y->G), both mild one-step changes.

---

## Session Notes

### Agent model discovery
- Custom agent definitions in `.claude/agents/` with `model: haiku` do NOT work via the `subagent_type` parameter
- The **Explore** subagent type runs on Haiku and has Read/Glob/Grep access — use this for Haiku summary agents
- Available subagent_types: general-purpose, statusline-setup, Explore, Plan, claude-code-guide, superpowers:code-reviewer
- Explore agents need `"very thorough"` in the prompt to do deep file reads (not just quick searches)

### Key methodological finding: Opus summaries are WORSE than Haiku summaries
- Opus summaries (Run 1): 64% match, 12% lenient (false upgrades)
- Haiku summaries (Run 2): 75% match, 3% lenient
- Reason: Opus produces richer summaries with more "topically adjacent" passages that enable false Green/Yellow assessments
- **For the production pipeline: always use Haiku (Explore agent) for summaries, never Opus**

### Verbatim quote checking insight
- All 3 remaining false negatives (Fox rows 26/29/35, Thomas row 53) share the same pattern: substance correct, but brief puts fabricated words in quotation marks
- Neither Haiku summaries nor Opus-direct reading catches this — both assess substance, not verbatim accuracy
- The court treats ANY non-verbatim text in quotation marks as fabrication
- This needs a separate check, not a better summarizer

---

## Recommendation

The Haiku prescreen results on Fletcher confirm the prior 3-brief findings. Ship it.

- Use Haiku (Explore agent) for summaries, Opus for assessment
- The 3% false upgrade rate is acceptable (all one-step, no R->G)
- The 21% conservative rate is safe for a hallucination-catching tool
- The conservative bias actually improves court-alignment: 17 Red vs GT's 14 Red on court-flagged issues
- Add a verbatim-quote checker step before Opus assessment (see plan below)

---

## Plan: Verbatim Quote Checker

### Problem
The brief puts fabricated language in quotation marks. Our pipeline assesses whether the case *substantively* supports the proposition, but never checks whether quoted text actually appears in the opinion. The court treats any non-verbatim quotation as fabrication regardless of substance.

### Proposed architecture

```
Phase 1c (existing): Extract propositions from brief
    |
    v
NEW STEP: Extract quoted text from each proposition
    - Parse quotation marks from the brief text (not the proposition summary)
    - For each quoted string, search the opinion file for exact or near-exact match
    - Flag: VERBATIM (exact match), CLOSE (fuzzy match, e.g. minor word changes), FABRICATED (not found)
    |
    v
Phase 2 (existing): Haiku summary -> Opus assessment
    - Pass the quote-check results INTO the assessment prompt
    - Opus can now assess both substance AND quote accuracy
    - A claim can be Green-substance + FABRICATED-quote
```

### Implementation options

1. **Deterministic (preferred for V1):** Regex extract quoted strings from brief text, then fuzzy string search (difflib.SequenceMatcher or similar) against opinion plain text. Fast, cheap, no LLM needed. Threshold: >0.85 similarity = VERBATIM, 0.6-0.85 = CLOSE, <0.6 = FABRICATED.

2. **Haiku-assisted:** Have Haiku include the opinion's actual key quotes in its summary. Opus compares brief quotes against summary quotes. More flexible but risks the "topically adjacent" problem.

3. **Hybrid:** Deterministic search first, then Haiku confirmation for CLOSE matches only.

### Dependencies
- Need the raw brief text with quotation marks preserved (not just the extracted propositions)
- Need opinion plain text (already have — downloaded in Wave 1)
- Phase 1c proposition extraction must preserve or separately extract quoted strings from the brief

### Test plan
- Test on the 4 known false negatives (Fox rows 26/29/35, Thomas row 53) — all have fabricated quotes that deterministic search should catch
- Test on the 10 Green rows to ensure real quotes aren't false-flagged
- Test on a few Yellow rows where quotes are close paraphrases (Cooter row 16, In re Case rows 41/55)

### Expected impact
- Would catch 3-4 of the remaining false negatives
- Combined with Haiku prescreen: ~0 false negatives on fabricated-quote cases
- Cost: near-zero for deterministic approach (string matching, no API calls)
