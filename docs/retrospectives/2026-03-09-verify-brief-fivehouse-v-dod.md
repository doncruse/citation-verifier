# Verify-Brief Skill Retrospective

## Run: Fivehouse v. U.S. Department of Defense (2026-03-09)

**Case:** No. 2:25-cv-00041-M-RN (E.D.N.C.)
**Document:** DE 86 — Response in Opposition to Plaintiff's Motion to Supplement the Record (filed 12/23/2025)
**Filed by:** AUSA Rudy Renfer for Defendants

### Brief Stats
- 9-page government opposition brief, 13 proposition-citation pairs, 5 unique cases
- Result: 2 Green, 4 Yellow, 7 Red (54% problematic)
- All 5 cases verified as real — the issue is holdings misattribution, not hallucinated case names

---

## Phase-by-Phase Notes

### Phase 1: Extract Claims + Citations
- **Smooth.** Short brief, clean text from RECAP plain_text field. No PDF parsing needed.
- **Short-form citation reconstruction:** The brief only cited "Dow AgroSciences, 637 F.3d at 268–69" (short-form, no full citation anywhere in the brief). Reconstructed as *Dow AgroSciences LLC v. National Marine Fisheries Service, 637 F.3d 259 (4th Cir. 2011)* from context (4th Circuit brief, 637 F.3d volume). It verified correctly, but this is a step where errors could creep in. The skill should note this as a risk factor.
- **Fetching from CourtListener docket URL:** WebFetch returned 403 on the docket entry page. Had to use the API directly: docket-entries endpoint → recap-documents endpoint → plain_text. Worked fine but required 3 API calls to get to the text.

### Phase 2: Verify Citations
- **Used sync `CitationVerifier()` in a loop** — only 5 unique citations, so batch/async wasn't needed. All verified on first lookup (citation-lookup API hit for all 5). Total time ~5 seconds.
- **No issues.** All VERIFIED, no fallback to opinion search or RECAP needed.

### Phase 2.5: Interactive Review
- **Skipped entirely** — no Check or Not Found cases. This is the ideal scenario.

### Phase 3: Retrieve Opinion Texts
- **Used `AsyncCourtListenerClient` with `get_opinion_text_with_metadata()`.**
- **Did NOT pass `prefer_html=True`** — all files came back as plain text. Should have used `prefer_html=True` for better formatting. This is a skill template bug: the download code example in the skill doesn't include the parameter.
- **All 5 downloaded successfully.** No missing texts. Sizes ranged from 10K (Camp v. Pitts) to 114K (Ohio Valley, Sierra Club).

### Phase 4: Assess Claims
- **Parallel subagents worked well.** 5 subagents dispatched, one per case.
- **Performance varied dramatically by opinion length:**

| Case | Chars | Tool Uses | Tokens | Time | Assessment |
|------|-------|-----------|--------|------|------------|
| Camp v. Pitts | 10K | 1 | 17K | 13s | Green |
| Overton Park | 33K | 1 | 24K | 32s | Mixed |
| Dow AgroSciences | 35K | 1 | 27K | 32s | All Red |
| Ohio Valley | 114K | 17 | 52K | 105s | Mostly Red |
| Sierra Club | 114K | 6 | 58K | 43s | Red |

- **Ohio Valley was the most expensive** — 17 tool uses suggests it read the opinion in many small chunks. The agent mentioned "lines 404-430 of the wrapped file," suggesting it was trying to map reporter page numbers to line numbers in line-wrapped OCR text. Inefficient but got the right answer.
- **Sierra Club consumed the most tokens** (58K) despite fewer tool uses (6) — it read in larger chunks but had to scan the entire 114K opinion to confirm the proposition wasn't discussed anywhere. All that work for a definitive Red.
- **Targeted reading could save cost:** When all pinpoints cite the same page (Ohio Valley cites all at *201), the agent could read that section first, then only do a full read if the passage isn't found or is ambiguous. For Sierra Club, a keyword search for "extra-record" / "supplemental" before reading the full text would have quickly revealed the citation is off-topic.

### Phase 5: Report
- **HTML report generated cleanly.** Color-coded table with supporting language blockquotes.
- **AskUserQuestion worked** for the "generate HTML report?" prompt — returned a clear "Yes". (This was broken in the Valve v. Rothschild run.)

---

## Findings: Quality of the Brief

This was a government brief (DOJ/AUSA), not a pro se or AI-generated filing, which makes the results surprising:

- **Camp v. Pitts** (1 cite) — Green. Accurate verbatim quote.
- **Overton Park** (4 cites) — 1 Green, 3 Yellow. The Green cite is solid. The Yellows overstate or decontextualize specific passages (presumption of regularity without the qualification, bad-faith requirement presented as broader than it is).
- **Ohio Valley** (4 cites) — 1 Yellow, 3 Red. At page 201, the court is discussing NEPA exceptions to the record-limitation rule. The brief cites it as if the court is reinforcing the general prohibition. The specific propositions about "presumption of completeness" and "mere allegations" don't appear in the opinion at all.
- **Dow AgroSciences** (3 cites) — All Red. The case is about APA jurisdiction over NMFS biological opinions. It contains no discussion of extra-record evidence, discovery, or record supplementation. All three propositions are wholly unsupported.
- **Sierra Club** (1 cite) — Red. ESA/pipeline case with zero discussion of extra-record evidence at the cited pages or anywhere.

**Pattern:** The two Supreme Court cases are accurately cited. The three circuit court cases are real cases cited for holdings they don't contain. This is consistent with AI-assisted drafting where the model confabulated the holdings while using real case names and reporters.

---

## Skill Improvements Identified

1. **Add `prefer_html=True` to download template** in the skill's Phase 3 code example.
2. **Flag short-form-only citations** — when a case appears only in short form (no full citation in the brief), note this as a risk in the CSV or report. The reconstructed full citation could be wrong.
3. **Targeted reading for long opinions** — when all pinpoints cite the same page, try reading that section first. Use keyword search before full reads to quickly identify off-topic citations.
4. **WebFetch 403 on CL docket pages** — the skill should document the API-based fallback path (docket-entries → recap-documents → plain_text) as the primary approach for CL URLs, since web scraping doesn't work.
5. **Token budget awareness** — the 114K opinions consumed disproportionate resources. Consider a "quick scan" mode: grep for key terms from the proposition before committing to a full read. If zero hits, mark Red immediately.

---

## Second Run Notes (same session, different machine)

A parallel run on this same brief produced slightly different results: **2 Green, 3 Yellow, 8 Red** (vs 4G/2Y/7R above). The stricter run rated Overton Park's "presumption of regularity" cite as Yellow (noting the qualification "not to shield his action from a thorough, probing, in-depth review" in the next sentence) and the "strong showing" cite as Yellow (noting it applies narrowly to mental-process inquiry, not all extra-record evidence). Assessment variance between runs is worth tracking.

### Alternative interpretation: Citation Bluffing vs AI-Assisted Drafting

The first run characterized the pattern as "consistent with AI-assisted drafting." An alternative framing: **citation bluffing** — real cases from the right circuit and topic area, with plausible-sounding propositions, banking on nobody checking pinpoint cites. This is distinct from AI hallucination (which invents cases entirely). Both interpretations are plausible; distinguishing them would require examining whether the specific fabricated propositions match common AI confabulation patterns.

### Investigation: On-the-fly RAG for Assessment

3 of 5 subagents read entire opinions (up to 115K chars) only to find zero relevant content. Could a lightweight RAG approach reduce wasted reads?

- **Approach:** Chunk opinion → embed → query with proposition text → assess only matching chunks
- **Simpler alternative:** Grep for key phrases from each proposition before dispatching Opus subagent. If zero hits on distinctive phrases (e.g., "extra-record," "supplementation," "discovery"), flag as likely Red without full read.
- **Trade-off:** Risk of false negatives if the opinion uses different terminology. But for cases like Dow AgroSciences (FIFRA jurisdiction) and Sierra Club (ESA/pipeline), even basic keyword search would catch the mismatch instantly.
- **Status:** Flagged for investigation.
