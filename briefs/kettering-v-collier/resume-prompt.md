# Resume Prompt: verify-brief Skill Iteration

Paste this to pick up where we left off:

---

We just finished the first test run of the `/verify-brief` skill (at `~/.claude/skills/verify-brief/SKILL.md`) against a real brief (Kettering v. Collier motion to dismiss). The test results and detailed feedback are in `briefs/kettering-v-collier/skill-test-feedback.md`. The approved design is in `docs/plans/2026-03-02-verify-brief-skill-design.md`. The test output (claims.csv, opinions/, report.html) is all in `briefs/kettering-v-collier/`.

We need to iterate on both the skill and the codebase based on what we learned. Read `briefs/kettering-v-collier/skill-test-feedback.md` for the full issue list, but the key fixes are:

**Skill fixes:**
1. Phase 2: Use Python API directly instead of CLI (CLI mixes progress into JSON stdout)
2. Phase 2.5/5: AskUserQuestion returned empty answers twice and Claude assumed defaults instead of re-asking. Need explicit handling.
3. Phase 3: Document the correct `async with AsyncCourtListenerClient()` pattern. Reference any new sync/CLI interface we add.
4. Phase 4: Claude ignored the design and wrote grep scripts instead of reading opinions with the Read tool. Skill must be explicit: "Read each opinion with Read tool, do NOT write search scripts." Add parallel subagent guidance (one per case).
5. Add model recommendations per phase (Haiku for mechanical phases 2/2.5/3, Opus for extraction/assessment, Sonnet for reporting).
6. Phase 3 parallelism won't work due to CL API 1-second rate limiting. Phase 4 parallelism (subagents per case) will work.

**Codebase fixes:**
1. Add sync `get_opinion_text()` to `CourtListenerClient` in `client.py` (currently only on async client)
2. Send progress messages to stderr when `--json` flag is used in `__main__.py`
3. Consider a `download-texts` CLI subcommand

**Deferred:**
- Baseline test (TDD RED phase — run without skill to see what Claude does naturally) was skipped. Should we do it?
- Word doc support not tested
- RAG pipeline deferred; parallel subagents in Phase 4 may make it unnecessary

Let's start by reading the feedback file, then decide how to tackle the fixes.
