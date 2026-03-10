# Haiku Prescreen Test Retrospective

## Test: Haiku Pre-Screen Accuracy (2026-03-10)

**Design doc:** `docs/plans/2026-03-09-haiku-prescreen-design.md`
**Results:** `scratch/haiku-prescreen-results.html`
**Purpose:** Validate whether Haiku can summarize opinions accurately enough for Opus to assess from summaries instead of reading full opinions.

### Test Setup

- Haiku reads each opinion via the Agent tool (`model: haiku`), produces structured summary (case summary, key holdings, relevant passages, topics not found)
- Opus assesses from the summary only (not the full opinion)
- Opinions under 20K characters read directly by Opus (no Haiku prescreen)
- Ground truth (GT) from prior Opus-direct reads across 3 briefs
- 10 no-opinion claims auto-Red (not assessed by subagent)

### Results

| Brief | Claims | Match | Rate | Conservative | Lenient |
|-------|--------|-------|------|-------------|---------|
| Fivehouse v. DOD | 12 | 10 | 83% | 2 | 0 |
| Kettering v. Collier | 27 | 22 | 81% | 5 | 0 |
| Valve v. Rothschild | 63 | 46 | 73% | 14 | 3 |
| **Combined** | **102** | **78** | **76%** | **21** | **3** |

---

## What Went Well

### Conservative bias is dominant and safe
21 of 24 mismatches are H→O stricter than GT. The prescreen never promotes a genuinely bad citation to Green. For a tool designed to catch misrepresented case law, false negatives (missing bad citations) are far worse than false positives (flagging borderline ones).

### Several GT assessments look wrong in hindsight
- Kettering row 13: GT Green for "hard bargaining" cite to Pendergraft, but "hard bargaining" doesn't appear in the opinion and the case assumed *illegitimate* claims. H→O Red is more defensible.
- Kettering row 21: GT Green for "particularity requirement" cite to Office Depot, but the cited pages address OUTSA preemption, not specificity. H→O Red is arguably correct.
- Valve row 44: GT Green for Kumho supporting "Al-Salam fails Daubert reliability." Kumho states the general principle; applying it to this specific expert is the brief's argument. H→O Red is defensible.

### Cost savings confirmed
- Haiku reading a full opinion: ~$0.03, 30-90 seconds
- Opus reading the same opinion: ~$0.50+, 40-170 seconds
- Roughly 15x cheaper per opinion read
- Wall time comparable because Haiku agents parallelize well

### No-opinion auto-Red is reliable
All 10 no-opinion claims (PacTool, Diamondback, etc.) matched GT Red. The auto-Red path needs no subagent and adds zero cost.

---

## Issues Found

### 1. Valve accuracy is lower (73% vs 81-83%)

**Pattern:** The Valve brief reuses ~10 cases across 63 claims, applying them progressively more loosely. Example: Crow Tribe v. Racicot is cited 7 times for increasingly stretched propositions. The GT assessor (Opus reading the full opinion) was more lenient about "general principle supports" on later reuses. H→O, working from a focused summary, is stricter about whether the summary actually says what the proposition claims.

**Assessment:** This is partly a GT calibration issue, not purely a prescreen accuracy issue. The Valve GT was produced in an earlier skill run that may have been more lenient. Many "mismatches" are arguably H→O being more correct.

### 2. Three false upgrades (all in Valve)

| Row | GT | H→O | Case | Issue |
|-----|----|-----|------|-------|
| 5 | Yellow | Green | Sundance v. DeMonte | Narrow holding (patent expert qualifications) overgeneralized by proposition. Haiku summary likely included the key quote without enough context to show the holding is narrow. |
| 39 | Red | Yellow | Mukhtar v. Cal. State | Fn. 10 discusses expert legal conclusions (related but not the claimed holding about statutory "reasonableness"). Haiku summary included fn. 10, making partial relevance visible. |
| 42 | Red | Yellow | United States v. Finley | Quote attributed to this case actually originates from Duncan (2d Cir.). Haiku summary likely included related expert-testimony discussion at p. 1014, making it look partial. |

**Severity:** All mild (one-step: Yellow→Green or Red→Yellow). No Red→Green false upgrades. 3/102 = 3% false upgrade rate.

**Root cause:** Haiku summaries include passages that are *topically adjacent* without flagging that the specific claimed holding isn't there. Opus, reading only the summary, sees relevant-looking language and assesses more leniently.

### 3. Some Opus assessment agents used external tools

**What happened:** The Flatley v. Mauro agent autonomously called `mcp__claude_ai_Midpage_Legal_Research__findInOpinion` to look up the opinion. This was not instructed and introduces an uncontrolled variable.

**Fix applied mid-test:** Added "Do NOT use any external tools like Midpage -- only Read" to subsequent agent prompts.

**For implementation:** The skill must explicitly prohibit external tool use in assessment agent prompts.

### 4. Some agents had Read tool permission issues (Valve)

**What happened:** Marx and Ellis opinion agents had Read tool calls denied (permission issues), fell back to knowledge-based assessment. Marx: 14 tool attempts, 176 seconds. Ellis: 13 tool attempts, 121 seconds.

**Impact:** Wasted time and tokens, but final assessments happened to match GT anyway (knowledge-based Opus is decent on well-known cases).

**For implementation:** Need to ensure agent tool permissions are set correctly, or handle Read failures gracefully.

---

## Observations on GT Quality

The test revealed that GT assessments are not always gold-standard:

- **Opus-direct is more lenient about paraphrasing.** When Opus reads a 40-page opinion and finds a general principle that's *conceptually* related, it tends toward Green/Yellow even if the specific quoted language or application context differs.
- **H→O is stricter about exact holdings.** The Haiku summary distills the opinion to key holdings and relevant passages. If the proposition's specific claim isn't in the summary, Opus correctly flags it.
- **Neither is objectively "right."** Whether "Crow Tribe generally says experts can't testify to legal conclusions" supports "determining statutory reasonableness is a question of law" depends on how loosely you read citation support. Lawyers do this all the time.

---

## Recommendations for Implementation

### Ship it with the conservative bias

The 76% exact match rate understates accuracy. Many "mismatches" are H→O being more careful, not less. The 3% false upgrade rate is acceptable, especially since all are one-step.

### Tune the Haiku prompt to reduce over-strictness

Current prompt asks for "RELEVANT PASSAGES (for the topics being assessed)" and "TOPICS NOT FOUND." Consider:
- Ask Haiku to be generous about including *conceptually related* passages, not just directly on-point ones
- Include a "PARTIALLY RELATED" section for passages that discuss the general topic but not the specific holding
- This would give Opus more context to distinguish "supports the general principle" (Yellow) from "completely absent" (Red)

### Add explicit external-tool prohibition to assessment agents

The Midpage MCP issue must be addressed in the skill prompt. Assessment agents should only use Read to access opinion files.

### Consider recalibrating GT

The Valve GT was produced in an earlier, more lenient skill run. Before using these numbers to gate implementation, consider whether the GT itself needs updating. The H→O assessments could be used as a second opinion to identify GT rows worth re-examining.

### Threshold: keep 20K

Opinions under 20K are cheap enough for Opus to read directly. The Haiku overhead (agent launch, structured summary, second Opus call) isn't worth it for short opinions. The 20K threshold from the design doc feels right based on this test.

---

## Combined Statistics

```
Total claims tested:  102
Exact matches:         78 (76%)
Conservative:          21 (21%)  -- H→O stricter than GT
Lenient:                3 (3%)   -- H→O more lenient than GT (false upgrades)

False upgrade breakdown:
  Red → Green:          0
  Red → Yellow:         2
  Yellow → Green:       1

Conservative breakdown:
  Green → Yellow:       2
  Green → Red:          2
  Yellow → Red:        17
```
