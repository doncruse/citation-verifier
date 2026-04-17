# Retrospective: Agent-authored finding blocks + full-Maxwell Phase 2c rerun

**Date:** 2026-04-17
**Brief retested:** Maxwell v. Michael, No. 1:24-cv-1365-JRS-TAB (S.D. Ind.)
**Commit:** 2dd2917 (feat: agent-authored finding blocks + Brooks-style report polish)
**Follow-up commit:** (this retrospective + dashboard teaser fix + test artifacts)

---

## Background

After the 2026-04-16 Maxwell run, the user flagged that the regenerated
report was "just a reskin, not a real improvement." The critique landed
on four points:

1. Dashboard categories too similar to old skill.
2. Agent `opinion_text` field capped at 1–2 sentences.
3. The SKILL prompt forbade agents from transcribing passages, reserving
   opinion language for the deterministic matcher.
4. When the deterministic matcher produced junk (FABRICATED quotes), the
   report had no opinion-side content at all.

This session reworked the Phase 2c agent prompt and the report template
to restore the Brooks-style quality from the old proposition-verifier
skill (deleted in `f32041f`, recovered from git history this session).

## What we shipped (2dd2917)

- Phase 2c subagents now author three freeform blocks per finding:
  `brief_block`, `opinion_block`, `finding_analysis` (plus discrete
  `assessment` and `badge_label`). No length caps; no transcription ban.
- The prompt is purpose-based: tell the agent what each block is *for*,
  show worked examples, let the agent pick form per finding.
- Deterministic `matched_passage` is now a *hint* to the agent, not a
  mandated report block. Template falls back to matched_passage at
  ≥0.65 similarity only for legacy claims.csv without agent-authored
  blocks.
- Phase 1c also extracts `brief_sentence` (brief's own sentence +
  parenthetical) for the brief-side fallback rendering.
- Report polish: grouped unable-to-verify cards by cited case (4×
  Holleman → 1 card with "cited 4×" suffix and propositions listed
  inside); dashboard label "Minor notes" → "Concerns"; OCR-handling
  instruction distinguishing `opinion_block` (silently correct CL
  database artifacts) from `brief_block` (preserve verbatim).

## Test run — full-Maxwell Phase 2c rerun

Kept wave1/wave2/quote-check outputs from the previous Maxwell run and
re-ran Phase 2c only, with three parallel Opus subagents covering all
15 Red+Yellow findings. Opinion files already downloaded — zero API
calls outside the subagent spawns.

### Timing

- Wall clock: ~3 min (three parallel agents, all finished in under 90s)
- Tokens: ~233k across the three agents

### Outputs

| Metric | Legacy schema | Agent-authored |
|---|---|---|
| Findings with green opinion-language box | 0 | 15 |
| Analysis blocks | 15 | 15 |
| Paragraphs inside analyses | 33 | 44 |
| Brooks-style contrast quotes present | no | yes |

Specific contrast quotes that landed in the regenerated report:

- **Beauchamp** (Red, inverts holding): *"Once an officer has established
  probable cause on every element of a crime, he need not continue
  investigating to test the suspect's claim of innocence"* — the opinion's
  actual holding, directly contradicting the brief's proposition.
- **McMurtrey** (Yellow, reworded): *"obvious reasons to doubt the
  veracity"* — the exact parallel sentence so the reader sees the
  substitution against the brief's "doubt the truth of what he or she
  is asserting."
- **Kraemer** (Red, citation resolves to different case): Argue v. David
  Davis Enterprises language quoted in both Kraemer findings (rows 7 and
  28), making the mismatch visually obvious.
- **Wolfe v. Little** (Red, same pattern): Abbott v. State language
  establishing that the resolved opinion is a completely unrelated
  criminal appeal.

All 15 assessments matched prior human calls. No regressions.

## What went well

1. **Three parallel agents are fast and efficient.** Grouping by opinion
   file + batching 4–5 opinions per agent worked well. No timeouts, no
   agent exceeded ~90s wall clock.
2. **Purpose-based prompts reliably produced rich prose.** Average
   analysis block grew from ~2 paragraphs (legacy) to ~3 paragraphs
   (agent-authored), with specific case-name-level detail.
3. **Agent judgment on opinion_block was correct on the hard cases.**
   Beauchamp's inverted-holding quote and McMurtrey's parallel-sentence
   extraction are the two places the old schema struggled most. Both
   nailed on first try.
4. **Wrong-case findings handled correctly.** Kraemer and Wolfe cases
   (where CL returned a different opinion than the brief named) got
   opinion_block content from the *resolved* case that makes the
   mismatch obvious, not from the case the brief claimed to cite.
5. **No hallucinated opinion language.** Spot-check of every
   `opinion_block` against the source opinion files: all quotes appear
   verbatim or with a minor OCR correction.

## What went less well

### 1. opinion_block sometimes quotes introductory framing rather than holding

In Group A especially, several Red findings quoted the opinion's *opening*
sentences (e.g., "This ease presents the question whether...", "Lori
David filed this action against Caterpillar...") rather than the specific
holding language that would sharpen the contrast with the brief's claim.
For topic mismatches the intro does establish "this case is about
something else," so it's not wrong — but a short holding quote lands
harder. Group C (Beauchamp) chose the holding quote directly and was much
punchier.

**Possible fix:** add a sentence to the prompt clarifying that for topic
mismatches, a one-sentence statement of the actual holding is more
powerful than the case's opening framing. Worked example already in
the prompt is Tompkins, which does use framing — could swap it for a
holding-quote example.

### 2. OCR instruction applied conservatively

Agents corrected obvious OCR artifacts like "MeMurtrey" → "McMurtrey"
and "King Spalding" → "King & Spalding", but preserved "This ease"
(OCR for "This case") in Swierkiewicz's opinion_block. The "if in doubt,
leave as-is" clause was applied too broadly — "ease" in "This ease
presents the question whether a complaint..." is semantically impossible
and a textbook c→e OCR confusion.

**Possible fix:** strengthen the OCR instruction with more examples of
semantically-impossible word substitutions ("ease" for "case", "ho lds"
for "holds"), or drop the "if in doubt, leave as-is" clause for clear
semantic impossibilities. Acceptable to leave as-is since it's cosmetic.

### 3. Dashboard teaser cutoff

The dashboard issue list pulls a teaser from the first sentence of
`finding_analysis`. Capped at 140 chars with mid-word truncation. With
richer agent-authored prose, first sentences often exceed 140 chars and
got clipped ugly. **Fixed in this follow-up commit:** bumped cap to 220
chars and truncate at the last word boundary before the cap (with an
ellipsis). First-sentence preference retained.

### 4. Agent did populate brief_block with empty string per instructions

This is by design — Maxwell's claims.csv predates the `brief_sentence`
Phase 1c column, so the fallback path (quoted strings rendered as
"Quoted in brief") was the right choice. But it meant we didn't test
the new agent-authored brief_block rendering in this rerun.

**Not a fix needed this run.** The fresh-brief run (next test) will
populate brief_sentence and exercise agent-authored brief_block.

## Next test

Run `/verify-brief` on a smaller *fresh* brief end-to-end. Target: 5–10
citations, non-federal if possible to exercise state-court paths. The
goal is to validate:

- Phase 1c `brief_sentence` extraction into claims.csv (unexercised
  this session — Maxwell data predates this column).
- Phase 2c against freshly-extracted data (not the pre-populated
  Maxwell quote_check cache).
- The `brief_block` agent-authored path (we only tested the
  deterministic `brief_sentence` fallback this session).
- The end-to-end pipeline with the updated SKILL prompt, including
  Phase 2a triage + Phase 2b grep/Haiku confirmation.

Candidates: any short motion-in-limine or reply brief from the user's
corpus that has known issues worth catching. The Brooks brief that
originally inspired this design would be a natural A/B test against the
pre-change proposition-verifier output.

## Artifacts kept

- `briefs/maxwell-v-michael/assessments_A.json`
- `briefs/maxwell-v-michael/assessments_B.json`
- `briefs/maxwell-v-michael/assessments_C.json`
- `briefs/maxwell-v-michael/assessments_test.json` (earlier 3-claim test)
- `briefs/maxwell-v-michael/claims.csv` (patched with agent-authored
  blocks for all 15 Red/Yellow findings)
- `briefs/maxwell-v-michael/report.html` (regenerated)

Useful reference for future Phase 2c prompt iteration.
