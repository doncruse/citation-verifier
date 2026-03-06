# verify-brief Skill Test 2 Feedback

**Date:** 2026-03-04
**Brief tested:** Valve v. Rothschild Daubert Motion, No. 2:23-cv-01016 (W.D. Wash.)
**Results:** 63 proposition-case pairs, 32 unique cases. 14 Green, 17 Yellow, 32 Red.

## Source

Reconstructed from TODO.md notes. Full retrospective was written to Claude memory on the other machine at `.claude/projects/-Users-fordon-4-Projects-citation-verifier/memory/verify-brief-retrospective.md` but not committed to the repo.

## Key Takeaways (from TODO)

1. **AskUserQuestion broken** -- remove from skill entirely. Auto-accept high-confidence matches. Always generate HTML report (don't ask).

2. **Phase 2 needs async batch mode** -- run all citation lookups (step 1) concurrently first, then steps 2-3 only for unresolved. Mirrors the web app approach. Could cut Phase 2 time significantly. Requires new `AsyncCitationVerifier` or batch method in the library.

3. **Phase 1 CSV writing is slow** -- Opus extraction is needed, but CSV writing from structured data could be Haiku.

4. **Fortune Dynamic wrong text** -- CL opinion page had Arthur v. Torres attached. Need sanity check: compare downloaded case name to expected.

5. **Brief had 51% Red citations** -- fabricated quotes, cases cited for opposite holdings, inapposite cases. Patterns consistent with AI-generated legal writing.

## Observations from claims.csv (reconstructed 2026-03-06)

- All 63 rows have `user_action=accepted` -- Phase 2.5 likely auto-accepted everything (AskUserQuestion bug persisted from test 1)
- 10 rows missing opinion files -- all PacTool (WestLaw cite) and Diamondback (docket number cite). POSSIBLE_MATCH status but accepted without text download.
- No NOT_FOUND cases -- everything matched at least something
- Report HTML generated successfully

## Skill Changes Needed (cumulative with test 1)

1. **Remove AskUserQuestion entirely** -- broken twice across two tests. Replace with:
   - Auto-accept VERIFIED/LIKELY_REAL (high confidence)
   - Auto-flag POSSIBLE_MATCH with name mismatch for user review in the CSV
   - Always generate HTML report
2. **Phase 2 async batch** -- concurrent step 1 lookups, sequential steps 2-3 for stragglers
3. **Phase 1 model split** -- Opus for extraction, Haiku for CSV writing
4. **Phase 3 sanity check** -- compare downloaded opinion case name against expected case name
5. **Phase 4** -- still unknown if Read tool or grep scripts were used in test 2
