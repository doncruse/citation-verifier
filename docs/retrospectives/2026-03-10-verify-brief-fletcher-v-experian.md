# Verify-Brief Skill Retrospective

## Run: Fletcher v. Experian Information Solutions (2026-03-10)

**Case:** No. 25-20086 (5th Cir.)
**Document:** Docket Entry 44 — Appellant's Reply Brief (filed 09/02/2025)
**Filed by:** Heather Hersh, FCRA Attorneys, for Appellant Robert Fletcher
**Source:** RECAP (CourtListener docket 72051574, recap-document 469181248) — purchased from PACER during this session

### Brief Stats
- 30-page reply brief, 19 unique case citations, 59 proposition-case pairs
- Result: **12 Green (20%), 28 Yellow (47%), 19 Red (32%)**
- All 19 cases verified as real — every issue is fabricated quotes or misattributed holdings, not hallucinated case names
- This is the Fifth Circuit's landmark AI-sanctions opinion: the court found Hersh "used artificial generative intelligence to draft a substantial portion—if not all—of her reply brief"

### Ground Truth Available
- **Fifth Circuit sanctions opinion** (Feb. 18, 2026, Chief Judge Elrod): enumerated 16 fabricated quotations + 5 misrepresentations
- **BriefCatch RealityCheck report**: independent analysis finding 16 incorrect, 1 caution, 4 verified across 21 citations

---

## Phase-by-Phase Notes

### Phase 1a: Extract Citations
- **Smooth.** RECAP plain_text was clean (44K chars). No PDF parsing needed.
- **Extracted 19 unique case citations.** The brief's Table of Authorities was well-formatted and matched the body citations.
- **Bryant reporter discrepancy missed:** The TOA lists "597 F.3d 678" but the body (p.23) cites "97 F.3d 678." I used the TOA version without noticing. BriefCatch caught this — 97 F.3d 678 resolves to *US v. NYC Transit Authority* (2d Cir. 1996), not Bryant. **This is a bug in our pipeline** — we should cross-check TOA citations against body-text citations and flag discrepancies.

### Phase 1b: Wave 1 Verify
- **All 19 verified in a single batch.** Zero misses. ~1 minute total.
- No wave 2 needed.
- All 19 opinion texts downloaded successfully (HTML format via prefer_html).

### Phase 1c: Propositions + Merge
- **Proposition extraction agent returned 59 claims.** Good coverage.
- **Merge: 59/59 matched, 0 unmatched.** Clean run — the tightened `cited_case` instructions from prior retros worked. No merge fixups needed.
- **Workaround for CSV update:** The subagent JSON results had to be written to claims.csv. Tried inline Bash heredoc but Windows Git Bash choked on single quotes in the assessment strings. Fell back to writing a throwaway Python script (`update_assessments.py`), then deleted it after. **This is a workflow gap** — the skill should specify how assessment results get into the CSV. Options: (a) have subagents write JSON sidecar files that a merge step reads, (b) have the orchestrator use Edit tool on the CSV directly, (c) build a `--update-assessments` CLI command.

### Phase 2: Assess Claims
- **7 parallel Opus subagents**, grouped by opinion file (Vaughan 12 claims, Fox 10, Cooter 8, Morrison 4, Edwards 3, Deepwater/Puckett/Peterson 6, remaining 11 opinions 16 claims).
- **Performance:** All completed in ~90-150 seconds. The "remaining 11 opinions" agent was slowest (149s, 39 tool uses, 119K tokens) because it had to read 11 separate opinion files.
- **Grouping strategy matters:** Batching by opinion file (not by claim count) is correct — each agent reads an opinion once and assesses all claims against it. The "remaining" batch was too large; should have split into 2-3 agents for parallelism.

### Phase 4: Report
- HTML report generated via a second throwaway Python script (`generate_report.py`), also deleted after. Same workflow gap as the CSV update — report generation should ideally be a CLI command (`--report`).

---

## Accuracy Assessment: Three-Way Comparison

### vs. the Court (16 fabricated quotes + 5 misrepresentations = 21 issues)

| Metric | Result |
|--------|--------|
| Issues we also caught | **19 of 21** (90%) |
| Issues we caught at correct severity | 14 Red + 3 Yellow = 17 correctly flagged as problematic |
| Issues we missed entirely | 2 — both record-fact misstatements (Bridgecrest "concession" quote, Rule 11 service assertion), which are outside our scope (not case citations) |
| False negatives (rated Green when court said fabricated) | **5** — Fox rows 27, 30, 36 (close paraphrases); Mendez row 53; Thomas row 54 |

### vs. BriefCatch RealityCheck (16 incorrect + 1 caution + 4 verified)

**RC caught that we missed:**
- **Bryant 97 F.3d wrong reporter** — deterministic Layer 1 catch. We used TOA version and verified the wrong citation. Clear pipeline gap.
- **Hensley framing** — exact quote is real but proposition framing is misleading. We rated Green; RC flagged it.
- **28 U.S.C. 1927 statutory standard** — brief attributes procedural requirements not in the statute. Outside our scope but valid.

**We caught that RC missed:**
- **Vaughan substance** — RC hedged ("couldn't fully verify... holding accurately stated"). We and the court both found the fee-segregation language fabricated and holding mischaracterized. RC underperformed here.
- **Lewis v. Brown & Root** — brief says Lewis reversed; Lewis affirmed. RC didn't flag this. Court did.
- **Morrison row 11** — brief claims Morrison says 1927 can't punish ultimately-failing claims; Morrison affirms sanctions for exactly that. Neither RC nor the court flagged this.
- **Fox additional misattributions** (rows 18, 20, 48, 58) — we flagged 5 additional Red Fox claims beyond the fabricated quote. RC only analyzed Fox once.

**RC arguably wrong:**
- **Morrison "material fact error"** — RC says the opinion doesn't mention Fletcher. But the brief uses Morrison as a *distinguishing* case — that's how distinguishing works. Likely a false positive from RC's AI layer.

**We were wrong:**
- **Fox rows 27, 30, 36; Mendez row 53; Thomas row 54** — rated Green for substantive accuracy, but the court and RC correctly flag these as fabricated quotes because the exact words in quotation marks don't appear in the opinions. Our assessment criteria didn't enforce verbatim accuracy for quoted material.

---

## Key Lessons

### 1. Verbatim quote checking needs to be a separate criterion
Our Green/Yellow/Red assessment conflates two questions: (a) does the case support the proposition? and (b) does the quoted language actually appear in the opinion? A case can get Green on (a) and Red on (b). The court treats anything in quotation marks that isn't verbatim as a fabrication, full stop. **Action: Add a "FABRICATED QUOTE" flag separate from the proposition-support assessment.** A claim can be Green-substance + Red-quote.

### 2. Cross-check TOA vs. body citations
The Bryant 97/597 F.3d discrepancy is exactly the kind of error a deterministic check should catch. **Action: In Phase 1a, extract citations from both the TOA and the body independently, then flag any discrepancies in reporter volume, page, or year.**

### 3. Assessment subagent batching
The "remaining 11 opinions" agent took 149s and 119K tokens. Splitting into 3-4 agents of 3-4 opinions each would have finished faster. **Rule of thumb: max 4-5 opinion files per subagent.**

### 4. Assessment-to-CSV workflow
Writing throwaway Python scripts to update the CSV and generate the report is clunky. Two options:
- **CLI commands:** `--update-assessments assessments.json` and `--report` in `brief_pipeline.py`
- **Subagent writes directly:** Have each assessment subagent append to a JSON sidecar, then a single merge step updates claims.csv

### 5. Our depth advantage is real
59 proposition-level claims vs. RC's 21 citation-level verdicts means we catch things like Morrison row 11 (correct case, wrong characterization of one specific use) that a per-citation tool misses. A case can be correctly cited in 3 places and fabricated in 1 — per-citation tools can't distinguish this.

### 6. Statute/rule checking is a gap
RC flagged 28 U.S.C. 1927 for wrong statutory standard (attributing procedural requirements not in the statute). Our pipeline only checks case citations. This is a known scope limitation, not a bug, but worth noting for future expansion.

---

## Comparison Summary Table

| Citation | Court | RealityCheck | Us |
|----------|-------|-------------|-----|
| Fox (834-36 quote) | Fabricated | Fabricated + misstated | Red |
| Fox (836 but-for quotes) | Fabricated (3) | (bundled above) | **Green** (missed) |
| Cooter (393 quote) | Fabricated | Fabricated | Red |
| Cooter (397 quote) | Fabricated | (bundled) | Yellow |
| Deepwater Horizon (2 quotes) | Fabricated + misrep | Misstated | Red |
| Vaughan (2 quotes) | Fabricated | "Couldn't verify" | Red + Yellow |
| Bryant (quote) | Fabricated | **Wrong case + fabricated** | Yellow |
| In re Case (quote) | Fabricated | Fabricated | Yellow |
| Mendez (quote) | Fabricated | Misstated | **Green** (missed) |
| Thomas (quote) | Fabricated | Fabricated + misstated | **Green** (missed) |
| Donaldson (quote) | Fabricated | (not listed separately) | Yellow |
| Bridgecrest brief quote | Fabricated | N/A (not a case) | N/A (out of scope) |
| Edwards | Misrepresentation | Misstated | Red |
| Deepwater (informal notice) | Misrepresentation | (bundled above) | Red |
| "No Rule 11 motion served" | Misrepresentation | N/A (record fact) | N/A (out of scope) |
| Miller | Misrepresentation | Misstated | Red |
| Lewis | Misrepresentation | **Not flagged** (missed) | Yellow |
| Puckett | **Not flagged** | Fabricated + misstated | Red |
| Morrison (row 11) | **Not flagged** | Material fact error (dubious) | **Red** (unique find) |
| Hensley | **Not flagged** | Misstated | **Green** (missed) |
| 28 U.S.C. 1927 standard | **Not flagged** | Wrong statutory standard | N/A (out of scope) |
| Peterson | **Not flagged** | Caution (overbroad) | Yellow |
| Matta | **Not flagged** | Misstated + wrong standard | Green (disagree w/ RC) |
| Childs | **Not flagged** | Misstated | Green (disagree w/ RC) |
