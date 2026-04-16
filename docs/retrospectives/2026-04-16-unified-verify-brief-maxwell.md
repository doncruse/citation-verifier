# Retrospective: Unified verify-brief + Maxwell v. Michael run

**Date:** 2026-04-16
**Brief tested:** Maxwell v. Michael, No. 1:24-cv-1365-JRS-TAB (S.D. Ind.)
**Document:** Plaintiff's Rebuttal to Defendants' Answer (ECF 134), 21 pages, pro se
**Results:** 29 claims: 10 Green, 4 Yellow, 11 Red, 4 Gray (unable to verify)

---

## What happened

Finished implementing the unified brief verifier plan (Tasks 6-8 from `docs/plans/2026-04-15-unified-brief-verifier-plan.md`), then immediately ran the new `/verify-brief` on Maxwell v. Michael as a test. The run exposed several report quality issues that required multiple iterations to fix during the same session.

## Timeline

- **Tasks 1-5** were already committed from a prior session (report template, syllabus plumbing, metadata check, CLI flags, SKILL.md rewrite)
- **Tasks 6-8** completed quickly: delete proposition-verifier skill, update CLAUDE.md, smoke test on Brooks data
- **Maxwell run** took ~7-8 minutes wall clock (20 citations, 29 claims)
  - Wave 1: 17 VERIFIED, 3 NOT_FOUND (~1-2 min)
  - Wave 2: found 2 more (POSSIBLE_MATCH), 1 still NOT_FOUND
  - CL API calls: ~26-28 total
  - 4 concurrent Opus assessment agents (~2.5 min)
- **Report iteration** took the rest of the session (~1.5 hours of fixes)

## What went well

1. **Pipeline speed** — 7-8 minutes for a 20-citation brief is good. Batch verify + concurrent agents work.
2. **Assessment quality** — The stricter calibration caught real problems: Swierkiewicz (Rule 8(a) case cited for Rule 8(b)(6)), Beauchamp (cited for the *opposite* of its holding), fabricated quotes in David v. Caterpillar, Sojka, Iqbal, Anderson, Whitlock. The Red/Yellow/Green distinctions were mostly correct.
3. **Name mismatch detection** — Kraemer -> Argue v. Davis and Wolfe v. Little -> Abbott v. State were correctly flagged as wrong cases.
4. **Holleman NOT_FOUND handling** — Auto-assessed as Gray without wasting an agent call.

## What went wrong

### 1. Report was just a reskin, not a real improvement (initial run)

The first report looked like the old verify-brief report styled with proposition-verifier CSS. The user immediately noticed:
- Categories too similar to old skill
- "Minor notes" weren't minor
- No exact language from the brief in the dropdown
- No actual opinion passages

**Root cause:** `generate_report()` ignored the new structured columns (`brief_text`, `opinion_text`, `badge_label`) and fell back to `proposition` + parsing `supporting_language`. Fixed by reading the new columns.

### 2. "What the brief claims" showed propositions, not quoted text

The brief puts text in quotation marks and attributes it to a case — that's the most important thing to show. But the report showed the proposition summary instead.

**Root cause:** `generate_report()` used `brief_text` (which agents populated with proposition summaries) instead of `quoted_text` (the actual quoted strings from the brief). Fixed by extracting `quoted_text` from the JSON column and showing it as "Quoted in brief:" when available.

### 3. "What the opinion actually says" showed agent summaries, not actual court language

This was the biggest issue. The proposition-verifier report showed side-by-side blockquotes with the court's actual words. The new report showed agent-written narrative descriptions like "This is a Title VII case about retaliation."

**Root cause:** The SKILL.md prompt told agents to write "the relevant passage from the opinion, using the opinion's own words" into `opinion_text`, but agents consistently wrote summaries instead. The user correctly identified this as something that should be deterministic, not agent-dependent.

**Fix:** Added `_best_match_with_passage()` to programmatically extract the best-matching passage from the opinion text. `check_quotes()` now stores `matched_passage` alongside each quote check result. The report shows this deterministic passage as "Actual language in opinion:" for CLOSE/VERBATIM matches, falling back to agent `opinion_text` for FABRICATED quotes where the matcher is unreliable.

### 4. apply_assessments.py hack

Couldn't inline the assessment JSON in a bash heredoc because of quote escaping. Wrote a throwaway Python script to apply results.

**Root cause:** The skill prompt told agents to return JSON in chat, which then had to be manually pasted into a script. The updated SKILL.md now tells agents to write results to `assessments_{group}.json` files, which a simple merge script can read.

### 5. Duplicate content in report

After adding deterministic passages, the report showed BOTH the matched passage AND the agent's `opinion_text` under "Actual language in opinion." Fixed by only showing one: deterministic passage for CLOSE/VERBATIM, agent text for FABRICATED.

### 6. Deterministic matcher position mapping was broken

Initial version used `_normalize_quote_text()` on the haystack (which changes string length by removing brackets, etc.), then tried to extract passages using positions from the normalized string in the original string. Positions didn't map.

**Fix:** Only lowercase the haystack for matching (preserves positions), normalize only the needle. Also strip HTML from opinion files before matching, not after extraction.

### 7. Sliding window step too coarse

With `step = window // 4`, the matcher sometimes skipped over the correct passage entirely (Scott v. Harris quote was in the opinion but the window landed on a different paragraph).

**Fix:** Tightened to `step = window // 8`. Scott v. Harris then found the correct passage.

## Changes made this session

### Code changes
- `brief_pipeline.py`: `_best_match_with_passage()`, `_extract_passage()`, HTML stripping in `check_quotes()`, `matched_passage` in quote_check JSON, `matched_passages` + `quoted_strings` in `generate_report()` findings, CLOSE/VERBATIM filter for deterministic passages
- `report_template.py`: "Quoted in brief:" vs "What the brief claims:" (show one, not both), "Actual language in opinion:" for deterministic passages, removed duplicate agent text
- `SKILL.md`: Updated agent prompt — agents receive `matched_passage` as input context, write results to JSON files, `opinion_text` is now a case description (not a transcribed passage)

### Commits
- `f32041f` chore: remove proposition-verifier skill + update CLAUDE.md
- `07d780b` fix: generate_report reads structured columns from new-style agents
- `18594bf` feat: improve report quote presentation + Maxwell run
- `dbf4880` feat: deterministic opinion passage extraction for quote comparison
- `c28b9f1` feat: simplify report layout + update skill prompt
- `b89ce31` fix: only show deterministic passages for CLOSE/VERBATIM matches

## Lessons / action items for next run

1. **Run `--check-quotes` AFTER code changes** — The matched_passage feature only populates when you re-run `--check-quotes` with the new code. If you just regenerate the report without re-running quotes, you get the old data.

2. **The deterministic passage extraction only helps for CLOSE/VERBATIM quotes** — In this brief, all CLOSE/VERBATIM quotes were on Green-assessed claims (correctly quoted, correctly supported). The Yellows and Reds all had FABRICATED quotes. So the side-by-side comparison didn't appear in any findings. This is correct behavior but means the feature will really shine on briefs with close-but-not-exact quotes on problematic citations.

3. **Agents should write to JSON files, not return inline** — The updated SKILL.md says this but hasn't been tested. Next run should verify the JSON file workflow works.

4. **The `_normalize_quote_text` on the needle but not the haystack is a trade-off** — It means some matches that worked before (when both sides were normalized) might get slightly lower scores. The benefit is correct position mapping. Watch for regressions.

5. **Still TODO:** Programmatic diff-highlighting (bold differing words between brief quote and opinion passage). Would make CLOSE matches much more readable.

6. **Beauchamp is a real finding** — The brief says "Probable cause dissipates when officers receive exculpatory evidence yet fail to act" and cites Beauchamp, which holds the exact opposite. This is either a hallucinated citation or a serious misreading of the case. Worth flagging to the user as a particularly concerning Red.

7. **Holleman v. Zatecky not in CourtListener** — 951 F.2d 873 (7th Cir. 1991). Cited 4 times in this brief. Would be worth checking Westlaw/Lexis to see if the quotes are real. Could file a data issue with CL if the case should be there.
