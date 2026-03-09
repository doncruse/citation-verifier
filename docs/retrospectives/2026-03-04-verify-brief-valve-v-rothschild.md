# Verify-Brief Skill Retrospective

## Run: Valve v. Rothschild Daubert Motion (2026-03-04)

**Case:** No. 2:23-cv-01016 (W.D. Wash.)

### Brief Stats
- 23-page Daubert motion, 63 proposition-citation pairs, 25 unique cases
- Result: 14 Green, 17 Yellow, 32 Red (51% problematic)

---

## Phase-by-Phase Notes

### Phase 1: Extract Claims + Citations
- **Model recommendation:** Skill says Opus. User asks if Haiku could handle CSV creation.
- **My take:** The extraction (reading the PDF, identifying proposition-case pairs) genuinely benefits from Opus -- legal comprehension matters for getting the proposition framing right. But the CSV _writing_ part (after extraction is done mentally) is mechanical. Could split: Opus reads and identifies pairs, then a Haiku subagent writes the CSV from a structured handoff.
- **Issue:** Writing 63 rows of CSV in a single Write tool call was slow. The bottleneck is the tool call itself, not the thinking.
- **"Diagnostics is a list, not a string":** Minor -- hit a type error parsing verification.json because `diagnostics` is `List[str]` not `str`. Fixed quickly by joining with `"; "`. Not worth a skill change, just a note for future runs.

### Phase 2: Verify Citations
- **Not using async:** The verification script used `CitationVerifier()` (sync) with a sequential loop. The skill template shows sync code. The async client exists (`AsyncCourtListenerClient`) but the verifier itself (`CitationVerifier`) is sync-only -- there's no `AsyncCitationVerifier` class.
- **User question: Would async help?** For verification (not just downloads), yes -- the 3-step pipeline (citation lookup → opinion search → RECAP search) could overlap across citations. But we'd need an `AsyncCitationVerifier` or at least an async wrapper.
- **User question: Batch quick lookups first, then deep research?** YES -- this is how the web app works. Citation lookup (step 1) is fast and resolves most cases. Opinion search (step 2) and RECAP (step 3) are slower fallbacks. If we batched all step-1 lookups first (async), many citations would resolve as VERIFIED without needing steps 2-3. Then only the remaining NOT_FOUND cases would need the expensive search. This could significantly speed up Phase 2 for briefs with many well-known cases (like this one where 20/25 verified on first lookup).
- **Potential code change:** Add a batch verification mode to the library, or at minimum an async verifier that can run step 1 for all citations concurrently, then step 2-3 only for unresolved ones.

### Phase 2.5: Interactive Review
- **AskUserQuestion is broken.** Three attempts, all returned empty ("User has answered your questions: ."). This has happened before. The UI component may not be surfacing selections back to the tool.
- **User says:** Remove interaction from the skill for now.
- **Workaround for skill:** Auto-accept "Check Name" cases where the docket/judge match (high confidence). Auto-accept all VERIFIED/LIKELY_REAL. Only flag truly suspicious cases and present them as a summary rather than interactive Q&A. For "Not Found" cases, just mark them Red with a note.
- **For HTML report question:** Same issue. Just always generate it -- it's cheap and useful.

### Phase 3: Retrieve Opinion Texts
- **Used async correctly** (`AsyncCourtListenerClient`). Sequential downloads with rate limiting. Worked well.
- **2 cases had no text** (PacTool, Diamondback -- RECAP docket only, no indexed opinion).
- **1 case matched wrong opinion** (Amazon v. Personal Web → downloaded Amazon v. Robojap). The verifier matched the wrong RECAP docket. This is a known limitation when CL doesn't have the opinion indexed.
- **Fortune Dynamic downloaded wrong text** too (got Arthur v. Torres, a 2-page prisoner case). The CL opinion page had the wrong text attached. This was caught during Phase 4 assessment.

### Phase 4: Assess Claims
- **Parallel subagents worked well.** 5 Opus subagents, each reading 3-6 opinions. All returned structured JSON. Total wall time ~3.5 minutes for all 5 (longest was ~3.6 min).
- **Batching strategy:** Grouped by opinion file (read each opinion once, assess all propositions citing it). This was efficient.
- **Key finding:** The subagents were thorough and caught real problems -- fabricated quotes, cases cited for opposite holdings, inapposite citations. The assessment quality was high.
- **Issue:** The subagents returned free-text JSON that I had to manually map back to CSV rows. A more structured handoff (row indices in, row indices out) worked but required careful bookkeeping.

### Phase 5: Report
- Generated HTML report. Straightforward.

---

## Observations from claims.csv

- All 63 rows have `user_action=accepted` -- Phase 2.5 likely auto-accepted everything (AskUserQuestion bug persisted from test 1)
- 10 rows missing opinion files -- all PacTool (WestLaw cite) and Diamondback (docket number cite). POSSIBLE_MATCH status but accepted without text download.
- No NOT_FOUND cases -- everything matched at least something
- Report HTML generated successfully

---

## Findings About the Brief

This was a real defense brief in an active federal case. 51% of citations were Red (unsupported).

**Most concerning patterns:**
1. **Fabricated quotations** -- Language in quotes attributed to cases that don't contain those words (Bilzerian "aura of authority", Crow Tribe "merely tells the jury", Cordis "validity, enforceability, or inequitable conduct")
2. **Cases cited for opposite of their holding** -- Hangarter (upheld expert testimony, cited to exclude), Micro Chem (affirmed expert, cited as if excluded), WBIP/Fox Factory (treat issues as fact questions, cited as "questions of law")
3. **Completely inapposite citations** -- Crowley v. Bannister (prisoner 8th Amendment case cited for fee reasonableness), Bausch & Lomb (patent definiteness cited for expert exclusion)
4. **Misattributed quotes** -- Language from one case attributed to a different case (Finley quote actually from Duncan via Mukhtar)

These patterns are consistent with AI-generated or AI-assisted legal writing where the model hallucinated case holdings.

---

## Process Improvement Ideas

### Skill Changes
1. **Remove AskUserQuestion from Phase 2.5** -- Auto-accept high-confidence matches, auto-Red truly not-found cases. Present a summary table instead of interactive review. User can override in the CSV if needed.
2. **Always generate HTML report** -- Don't ask, just do it.
3. **Phase 1 model split:** Consider whether Haiku can handle CSV creation from an Opus-produced structured list. The extraction needs Opus; the CSV writing is mechanical.
4. **Phase 2 should note async is not available** for the verifier itself, only for downloads.

### Code Changes (citation_verifier library)
1. **Batch verification with async step-1 priority:** New method like `verify_batch(citations)` that runs all citation lookups (step 1) concurrently first, then only runs opinion search (step 2) and RECAP (step 3) for unresolved cases. This mirrors the web app's approach and could cut Phase 2 time significantly.
2. **AsyncCitationVerifier class:** Wrap the 3-step pipeline in async so multiple citations can be verified concurrently with proper rate limiting (semaphore).
3. **Better diagnostics typing:** The `diagnostics` field being `List[str]` is fine in the model but the skill/scripts should know this. Maybe add a `diagnostics_str` property that joins them.

### Assessment Quality Notes
- Opus subagents were excellent at catching fabricated quotes and misrepresented holdings
- The parallel dispatch (5 agents, ~3-4 cases each) was a good balance of parallelism vs. context
- Grouping by opinion file (read once, assess all propositions) was efficient
- Fortune Dynamic false negative: downloaded wrong opinion text from CL, leading to Red assessment that might be Green if correct text were available. Could add a sanity check: if downloaded text doesn't match expected case name, flag it before assessment.
