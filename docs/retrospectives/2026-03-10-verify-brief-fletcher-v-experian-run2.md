# Verify-Brief Skill Retrospective — Run 2

## Run: Fletcher v. Experian Information Solutions (2026-03-10, Run 2)

**Case:** No. 25-20086 (5th Cir.)
**Document:** Docket Entry 44 — Appellant's Reply Brief (filed 09/02/2025)
**Source:** briefs/brief.txt (plain text)
**Prior runs:** GT (Opus-direct, 59 claims), H->O prescreen (Haiku summary -> Opus assessment, 59 claims)

### Brief Stats
- 30-page reply brief, 19 unique case citations, **62 proposition-case pairs**
- Result: **5 Green (8%), 36 Yellow (58%), 21 Red (34%)**
- All 19 cases verified as real on CourtListener
- **First run with Phase 1d quote check integrated** (`--check-quotes`)

---

## Phase-by-Phase Notes

### Phase 1a: Extract Citations
- Opus read the brief directly (not via Haiku agent). For a 30-page brief this is fine.
- Extracted 19 unique case citations from TOA + body.
- **Bryant reporter discrepancy noticed but not both-looked-up.** TOA says "597 F.3d 678", body p.23 says "97 F.3d 678". Used TOA version only. The skill was updated mid-session to say "look up both variants" but the fix came after extraction. **Still a gap.**

### Phase 1b: Wave 1 Verify
- All 19 verified in a single batch. Zero misses. ~2 minutes.

### Phase 1c: Propositions + Merge
- **62 claims extracted** (vs 59 in prior runs). Slightly broader extraction — 3 additional proposition-case pairs.
- Merge: 62/62 matched, 0 unmatched. Clean.

### Phase 1d: Quote Check + Summaries

**Quote check results:** 0 VERBATIM, 6 CLOSE, 13 FABRICATED, 43 NO_QUOTES.

This is the key new step. The 13 FABRICATED flags directly drove several assessment improvements in Phase 2.

**Haiku summaries:** 7 Explore agents launched in parallel covering 18 opinions (Edwards < 20K, skipped).
- Wall clock: ~64s (parallel). Total: 196s sequential, 293K tokens.
- **Wide variance in agent behavior:** Fox/Vaughan/Morrison/Deepwater used 1-5 tool calls; Cooter used 30; Coghlan used 21; batch-of-12 used 26. The high-tool-use agents were grep-searching instead of just reading. This wastes tokens and time.
- **Suggestion:** The prompt should explicitly say "Read the file with the Read tool in one call, then analyze" to prevent excessive searching.

### Phase 2: Assess Cases
- 5 Opus subagents launched in parallel. Wall clock: ~38s.
- Assessment data had to be written back to CSV via a throwaway `update_assessments.py` script. First attempt as a bash one-liner failed due to quote escaping on Windows. **Same workflow gap as Run 1.**

### Phase 4: Report
- Generated via throwaway `generate_report.py`. **Same gap.**
- HTML report saved to `briefs/fletcher-v-experian/report.html`.

### Session startup issues
- Wasted ~2 minutes on python/head/which command failures. All documented in CLAUDE.md but not followed. Created a SessionStart hook to prevent this in future sessions.

---

## Comparison vs. Prior Runs

### Overall numbers

| Metric | GT (Run 1) | H->O (Prescreen) | This Run |
|--------|-----------|-------------------|----------|
| Claims | 59 | 59 | 62 |
| Green | 12 (20%) | ~12 | 5 (8%) |
| Yellow | 28 (47%) | ~28 | 36 (58%) |
| Red | 19 (32%) | ~19 | 21 (34%) |

### vs. H->O (Haiku prescreen — best prior results)

**Improvements (5):**

| Citation | H->O | Our Run | Why |
|----------|------|---------|-----|
| Thomas (fabricated quote) | Green (missed) | **Red** | Quote check: FABRICATED |
| Cooter row 16 (fabricated quote at p.393) | Yellow (H->O regression) | **Red** | Quote check: FABRICATED |
| In re Case (fabricated quote) | Yellow | **Red** | Quote check: FABRICATED |
| Donaldson (fabricated quote) | Yellow | **Red** | Quote check: FABRICATED |
| Coghlan row 4 ("no desire to deter") | Green (H->O regression) | **Yellow** | Fixed H->O false upgrade |

All 4 of the fabricated-quote improvements are directly attributable to the Phase 1d `--check-quotes` step.

**Regressions (2):**

| Citation | H->O | Our Run | Why |
|----------|------|---------|-----|
| Lewis v. Brown & Root | Red (both rows) | Yellow (rows 45,46), Green (row 57) | Summary agent didn't emphasize "vexatious multiplication" standard strongly enough |
| Hensley v. Eckerhart | Yellow | Green (row 33) | CLOSE quote check didn't trigger downgrade; assessor saw substance as accurate |

Both regressions go back to the GT (Opus-direct) level — they are not new failures, but loss of improvements that the H->O prescreen had achieved.

**Persistent misses (3):**
- Fox but-for quotes (rows 26, 29): Still Green. Substance correct, but quoted words are fabricated. Quote check says CLOSE but assessors rate substance Green.
- Fox row 35 (from prior runs): Now Yellow in our run — partial improvement via CLOSE flag.

### vs. Court (16 fabricated quotes + 5 misrepresentations = 21 issues)

| Metric | GT | H->O | This Run |
|--------|-----|------|----------|
| Issues caught (Red or Yellow) | 19/21 | 19/21 | 19/21 |
| Caught at Red | 14 | 17 | **18** |
| Caught at Yellow only | 5 | 2 | 1 |
| False negatives (Green) | 5 | 3 | **2** (Fox rows 26,29) |

We now catch 18 of 21 court-flagged issues at Red severity — the best result across all runs. False negatives dropped from 5 (GT) → 3 (H->O) → 2 (this run).

---

## Key Findings

### 1. Quote check is the highest-impact improvement since Haiku prescreen

The `--check-quotes` step drove 4 of 5 improvements over H->O, all fabricated-quote catches. It also fixed both of H->O's regressions (Cooter row 16, Coghlan row 4 indirectly). The deterministic string matching catches what neither Haiku summaries nor Opus assessment can: whether exact quoted words appear in the opinion.

### 2. CLOSE quotes still fall through

Fox rows 26 and 29 have CLOSE quotes (minor word differences like "paid" vs "incurred"). The assessors see the substance is right and rate Green. The court would call these fabricated because the exact words in quotation marks don't match. **The assessment criteria need to enforce: CLOSE quote in quotation marks = at least Yellow.**

### 3. Lewis regression suggests summary quality variance

The Lewis regression (Red in H->O, Yellow/Green here) is likely due to the Explore agent not emphasizing the "vexatious multiplication" vs "bad faith" distinction as strongly as the prior run's summary did. This is inherent variance in summary generation. The fix is either:
- More prescriptive summary prompts ("identify the exact legal standard stated in the opinion")
- Or accept this as noise within the 3% false-upgrade tolerance

### 4. Explore agents are inconsistent in tool usage

Tool uses per agent ranged from 1 to 30. Some agents read the file once and analyzed; others grep-searched extensively. The prompt should explicitly instruct "Read the file with the Read tool in a single call, then analyze the full text."

### 5. Assessment-to-CSV workflow remains the biggest DX gap

Third run generating throwaway Python scripts. This needs to be a CLI command.

---

## Suggestions for Future Features

### High priority

1. **Enforce CLOSE quote → at least Yellow.** Change Phase 2 assessment criteria: "If `quote_check_worst` is CLOSE, the maximum assessment is Yellow regardless of substance. Only VERBATIM or NO_QUOTES can be Green." This would fix the 2 remaining false negatives (Fox rows 26, 29).

2. **`--update-assessments` CLI command.** Accept a JSON file of `[{row_index, assessment, supporting_language}]` and merge into claims.csv. Eliminates throwaway scripts.

3. **`--report` CLI command.** Generate `report.html` from claims.csv. The HTML template is stable across runs.

4. **Both-variant citation lookup.** When Phase 1a finds a discrepancy between TOA and body citations, include both in `citations_to_verify.txt` and flag the discrepancy. This would catch the Bryant 97/597 F.3d issue.

### Medium priority

5. **Explore agent prompt improvement.** Add to the summary prompt: "Read the ENTIRE file with a single Read tool call. Do NOT use Grep or Glob to search — read the full text and analyze it directly." This should reduce the 1-30 tool use variance.

6. **Per-opinion summary quality check.** After Haiku summaries, have Opus scan for any summary that says "the opinion is about [completely unrelated topic]" (like Deepwater Horizon = oil spill fraud). Auto-Red those claims without needing a full assessment agent.

7. **Claim count stability.** 59 vs 62 claims across runs makes comparison harder. Consider a deterministic extraction approach (eyecite + regex) rather than LLM extraction to stabilize claim counts.

### Low priority

8. **Haiku agent invocation — unsolved.** We have a well-structured custom agent at `.claude/agents/haiku-summarizer.md` with `model: haiku` in the frontmatter, but no confirmed way to invoke it programmatically:
   - `subagent_type: "haiku-summarizer"` → "Agent type not found" (only built-in types: general-purpose, Explore, Plan, etc.)
   - The claude-code-guide claims custom agents are invoked via "automatic delegation" or "explicit request by name" — but this is unverified and may be hallucinated
   - Current workaround: Explore agent (runs on Haiku, has Read/Glob/Grep) with the summary prompt inlined in the skill
   - **This is unsatisfying.** The Explore agent wasn't designed for this — it's optimized for codebase exploration, not document summarization. It sometimes grep-searches instead of reading straight through (1-30 tool use variance). A purpose-built Haiku summarizer agent should produce better, more consistent results. Investigate: `/agents` CLI command, whether custom agents work as slash commands, whether there's an SDK/API path, or whether this is a feature gap to report to Anthropic.

9. **Statute/rule checking.** The brief attributes procedural requirements to 28 U.S.C. 1927 that aren't in the statute. Out of scope for now, but could be a future expansion.

10. **Report format improvements.** Add a "by-case summary" section showing the worst assessment per citation (useful for quick triage). Add the four-way comparison table format from the prescreen doc.

---

## Run Metadata

- **Duration:** ~9 minutes total (Phase 1a-1b: 4min, 1c: 2min, 1d: 1min, Phase 2: 1min, Phase 4: 1min)
- **Haiku tokens (summaries):** 293K across 7 agents
- **Opus tokens (assessments):** 85K across 5 agents
- **Opus tokens (proposition extraction):** 40K
- **Quote check:** Deterministic, ~0 cost
