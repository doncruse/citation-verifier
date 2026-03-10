# Verify-Brief Pipeline Retrospective

## Run: Fivehouse v. DOD — Pipeline Test (2026-03-09)

**Case:** No. 2:25-cv-00041-M-RN (E.D.N.C.)
**Document:** DE 86 — Response in Opposition to Plaintiff's Motion to Supplement the Record
**Purpose:** First real-world test of the new `brief_pipeline.py` module and rewritten `/verify-brief` skill

### Brief Stats
- 9-page government opposition brief, 13 proposition-citation pairs, 5 unique cases
- Result: 4 Green, 2 Yellow, 7 Red (54% Red — matches the old skill run exactly)
- All 5 cases verified as real — the issue is holdings misattribution, not hallucinated case names

### Compared to Old Skill Run (same brief, same day)
- Old: 2 Green, 4 Yellow, 7 Red
- New: 4 Green, 2 Yellow, 7 Red
- The Red set is identical. The difference is in Green/Yellow — the new run is slightly less cautious on the Overton Park cites (upgraded 2 Yellows to Green). Both are defensible readings.

---

## What Went Well

### Pipeline speed
- Wave 1 verified all 5 citations in a single batch API call and downloaded 5 HTML opinions. Total: ~30 seconds.
- Wave 2 was a no-op (0 misses). Merge took <1 second.
- Compare to old skill: sync verification loop (~5 sec) + async downloads (~20 sec) + manual CSV wiring. Similar total time, but the pipeline is one command and zero boilerplate.

### HTML opinion downloads
- All 5 opinions downloaded as `.html` (via `prefer_html=True`). The old skill run got `.txt` files.
- HTML preserves citation hyperlinks and formatting, which helps Opus subagents navigate long opinions.

### Merge worked cleanly
- Pinpoint stripping correctly matched `484 U.S. 518, 527 (1973)` to `484 U.S. 518 (1973)`.
- 12 of 13 claims matched on first merge. The 1 miss was a bug in the agent prompt, not the pipeline (see below).

### Assessment quality
- Same Red findings as the old skill run: Dow AgroSciences (3 Red), Ohio Valley (3 Red), Sierra Club (1 Red).
- Subagents correctly identified that these opinions don't discuss the cited propositions at all.

---

## Issues Found

### 1. Phase 1a was not delegated to Haiku
**What happened:** The skill says Phase 1a (citation extraction) should use a lighter model. Instead, the main Opus context did it inline.
**Impact:** Minor — this brief only has 5 cases. Would matter more for a 50-case brief where citation extraction is mechanical.
**Fix:** Could use a Haiku subagent, but the real benefit is small for short briefs. Worth doing for briefs with 15+ citations.

### 2. Proposition agent omitted full citation for Camp v. Pitts
**What happened:** The Phase 1c agent wrote `Camp v. Pitts` in the `cited_case` column instead of `Camp v. Pitts, 411 U.S. 138, 142 (1973)`. The merge couldn't match it because the normalized forms don't match (`camp v. pitts` vs `camp v. pitts, 411 u.s. 138 (1973)`).
**Impact:** Required manual fix before re-merge.
**Root cause:** The agent prompt said "use `cited_case` values from the citation list exactly" but didn't enforce it strongly enough. The agent paraphrased instead of copying.
**Fix:** Tighten the Phase 1c agent prompt: "The `cited_case` column MUST start with the exact text from citations_to_verify.txt. Append pinpoint pages after the start page. Do NOT abbreviate or omit the reporter citation." Could also add a post-merge validation step that flags any claims with empty `cl_status`.

### 3. Wave2 runs even when there are 0 misses
**What happened:** `--wave2` CLI was called, printed "0 misses to resolve...", and returned immediately. Harmless but unnecessary.
**Fix:** Skip the wave2 CLI call entirely when wave1 reports 0 misses. The skill should check wave1 output before launching wave2.

### 4. Assessment subagents are expensive on fabricated citations
**What happened:** The Dow AgroSciences subagent spent 35 seconds and 5 tool uses reading an opinion about FIFRA jurisdiction to conclude it has nothing about record supplementation. The Sierra Club subagent spent 43 seconds and 6 tool uses on a 114K-character ESA opinion for the same reason.
**Impact:** ~80 seconds and ~70K tokens wasted on opinions that are completely off-topic.
**Pattern:** This is the same issue noted in the old skill retrospective (#5: "Token budget awareness"). When the cited proposition is entirely absent from the opinion, the subagent reads the whole thing just to confirm it's not there.

---

## Proposed Changes

### A. Grep pre-screen for assessment subagents (design needed)

**Problem:** Opus subagents read entire opinions to assess claims. When the opinion is completely off-topic (fabricated holding attribution), this wastes significant time and tokens.

**Idea:** Before dispatching an Opus subagent, grep the opinion file for a broad set of terms related to the proposition. If zero hits, skip the subagent and auto-mark the claim.

**Concern (from Rebecca):** What if the case discusses the same legal principle using different terminology? A zero-hit grep could false-positive on a legitimate citation.

**Resolution:** The key is the *magnitude* of the mismatch. Use a broad term cluster (~10-15 terms spanning the topic area), not narrow proposition-specific words. For "extra-record supplementation," search for: `record|supplementat|extra.record|discovery|completeness|outside the record|beyond the record|augment|additional materials|bad faith`. If *none* of those hit in a 35K+ opinion, it's almost certainly not relevant.

**Safe default:** When grep finds zero hits, mark as Yellow ("Could not locate relevant passages — manual review recommended") rather than auto-Red. The reviewer still looks at it, but the Opus subagent is skipped.

**Cost-benefit:** For this brief, would have saved ~80 seconds and ~70K tokens (4 of 5 subagents could have been pre-screened). For the Valve v. Rothschild brief (25 cases, several fabricated), savings would be much larger.

**Status:** Needs design. Questions to resolve:
- How to generate the term cluster from a proposition? Static per-topic, or LLM-generated?
- What's the right threshold? Zero hits vs. fewer than N hits?
- Should we search the full opinion or just the cited page range?
- What assessment to assign on zero-hit: Yellow or Red?

### B. Tighten Phase 1c agent prompt
- Enforce exact citation text from `citations_to_verify.txt`
- Add validation: after merge, flag claims with empty `cl_status` and prompt for correction

### C. Skip wave2 when 0 misses
- Trivial code change in the skill: check `wave1.miss_indices` before launching wave2 agent

### D. Post-merge validation step
- After merge, count matched vs. unmatched
- If unmatched > 0, print which claims didn't match and why (missing from verification_results.csv? Normalization mismatch?)
- Could be added to `merge_claims()` return value or as a separate CLI flag

---

## Comparison: Old Skill vs. New Pipeline

| Aspect | Old Skill (same brief) | New Pipeline |
|--------|----------------------|--------------|
| Verification | Sync loop, 5 API calls | Single batch call |
| Downloads | Async, plain text | Async, HTML (prefer_html) |
| Merge | Manual CSV wiring in skill | `--merge` CLI command |
| Opinion count | 5 .txt files | 5 .html files |
| Boilerplate code | ~40 lines embedded in skill | 0 (CLI commands) |
| Assessment | Same 7 Red findings | Same 7 Red findings |
| Total phases | 5 (with Phase 2.5) | 4 (no interactive review) |
| AskUserQuestion | Worked (for once) | Not used |

The pipeline eliminates the embedded code snippets that were the #1 source of skill errors across all three retrospectives. The skill now orchestrates only the LLM-hard parts (extraction, assessment).
