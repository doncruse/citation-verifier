# verify-brief Skill Test Feedback

**Date:** 2026-03-02
**Brief tested:** Kettering v. Collier, 3:25-cv-00273-WHR-CHG (S.D. Ohio)
**Results:** 27 proposition-case pairs, 20 unique cases. 16 Green, 1 Yellow, 10 Red.

## Issues Found During Test

### Phase 1 (Extract) - Worked Well
- Claude extracted claims correctly from pasted text
- Proposition-case pair granularity worked as designed
- No issues

### Phase 2 (Verify) - CLI Output Problem
- **Problem:** Skill says to shell out to `python -m citation_verifier --file temp.txt --json`, but the CLI mixes progress messages ("Verifying 1/20...") into stdout with JSON output. First attempt used `grep -v` to filter, which mangled the JSON and produced 21 results instead of 20.
- **Fix needed (skill):** Use Python API directly instead of CLI: `CitationVerifier().verify(citation)` in a loop, saving results to JSON.
- **Fix needed (codebase):** Progress messages should go to stderr, not stdout. Or add `--quiet` flag.
- **Secondary issue:** Simpson was VERIFIED on first run but NOT_FOUND on second run (caching inconsistency with Ohio citation format).

### Phase 2.5 (Review) - AskUserQuestion Broken
- **Problem:** AskUserQuestion returned "User has answered your questions: ." but the user NEVER answered. Claude treated empty response as an answer and continued with assumed defaults.
- **This happened twice** (Phase 2.5 and Phase 5).
- **Fix needed (skill):** Add explicit instruction: "If AskUserQuestion returns without clear answer text, do NOT assume a default. Re-ask or wait for the user to respond." Possibly restructure to use simpler yes/no questions one at a time instead of multi-question batches.

### Phase 3 (Retrieve) - Three False Starts
1. Tried sync `CourtListenerClient` → no `get_opinion_text` method (only on async client)
2. Tried `AsyncCourtListenerClient()` without `async with` → assertion error ("Use 'async with' to create the client")
3. Finally worked with `async with AsyncCourtListenerClient() as client:`

- **Fix needed (codebase):** Add `get_opinion_text()` to the sync client, OR create a standalone CLI command: `python -m citation_verifier download-text <url> [--output-dir DIR]`
- **Fix needed (skill):** Document the correct async pattern, or (better) reference whatever new CLI/sync interface we add.
- **Parallelism note:** CL API has 1-second rate limiting, so parallelism won't help for downloads. Sequential with rate limiting is the right approach. Could batch with asyncio but still rate-limited.

### Phase 4 (Assess) - Ignored Design, Used Wrong Approach
- **Problem:** The design said Claude should READ each opinion file directly (using Read tool) and assess with LLM understanding. Instead, Claude wrote Python scripts to grep for keywords — exactly the "regex approach" we rejected during brainstorming.
- **Root cause:** Opinion files are large (up to 120K chars for Kulch). Claude pragmatically chose keyword search to avoid consuming context, but this wasn't what we agreed on.
- **The keyword approach missed things:** Flatley's nuanced holding (the case found conduct WAS extortion, but distinguishes legitimate demands), and Wilson's complete lack of HIPAA content, were caught — but only because of broad keyword searches. Direct reading would have been more reliable.
- **Fix needed (skill):** Be explicit: "Read each opinion file using the Read tool. Do NOT write scripts to search for keywords." Add guidance for handling long opinions (read in chunks if > X chars).
- **Parallelism:** Assessment per case IS parallelizable. Each case's opinion can be read and assessed independently. Use subagents (one per case or small batches). This would also solve the context window concern since each subagent gets its own context.
- **RAG consideration:** Deferred to v2. Parallel subagents may solve the immediate problem better than RAG since each subagent only reads 1-2 opinions.

### Phase 5 (Report) - Worked, but AskUserQuestion failed again
- HTML report generated correctly
- Summary in chat was useful
- AskUserQuestion about "do you want HTML report" got no answer but Claude generated it anyway (which happened to be the right thing, but for the wrong reason)

## Model Selection Recommendations

| Phase | Model | Rationale |
|-------|-------|-----------|
| 1 (Extract) | Opus | Deep legal comprehension needed to identify propositions |
| 2 (Verify) | Haiku | Mechanical: run verifier, parse JSON, update CSV |
| 2.5 (Review) | Haiku | Present results, collect user input |
| 3 (Retrieve) | Haiku | Mechanical: API calls, save files |
| 4 (Assess) | Opus (in subagents) | Deep comprehension of opinion text. Parallelizable per case. |
| 5 (Report) | Sonnet | Formatting/summarization |

## Deferred Items

- **Baseline test:** The writing-skills process requires a RED test (run without skill) before writing the skill. This was skipped. Should be done before considering the skill "deployed."
- **Word document support:** Not tested. Need to decide: python-docx dependency, or just have user paste text?
- **Case substitution (v2):** User can upload cases for Not Found, but no search for alternatives.
- **RAG pipeline (v2):** For very long opinions. Parallel subagents may make this unnecessary.

## Codebase Changes Needed

1. **client.py:** Add sync `get_opinion_text()` to `CourtListenerClient`, or create a CLI download command
2. **__main__.py:** Send progress messages to stderr (not stdout) when `--json` is used, or add `--quiet`
3. **Consider:** A `download-texts` CLI subcommand: `python -m citation_verifier download-texts --urls-file FILE --output-dir DIR`

## Skill Changes Needed

1. **Phase 2:** Use Python API directly, not CLI. Provide exact code snippet.
2. **Phase 2.5:** Handle AskUserQuestion failures. Simpler questions. One at a time.
3. **Phase 3:** Document correct async pattern. Reference any new sync/CLI interface.
4. **Phase 4:** Explicit instruction to READ opinions with Read tool, not write search scripts. Add parallel subagent guidance. Chunk guidance for long opinions.
5. **Phase 5:** Same AskUserQuestion fix as 2.5.
6. **General:** Add model recommendations per phase. Add parallelism notes.
7. **General:** The skill is ~200 lines — within the recommended size for a technique skill.
