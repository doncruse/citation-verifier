---
name: proposition-verifier
description: Use when the user wants to verify that cited cases support the propositions they're cited for -- in a brief, motion, or opinion PDF, or a prepared list of (citation, proposition) pairs. Triggers on "verify propositions", "proposition verifier", "verify this brief", "check the citations in this brief". Supersedes /verify-brief (which stays frozen for old runs in briefs/).
argument-hint: "[path to brief PDF, or path to a prepared claims.csv]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /proposition-verifier — thin trigger for the proposition pipeline

All logic lives in the pipeline (`python -m citation_verifier verify-propositions`, design `docs/plans/2026-06-11-proposition-verifier-pipeline-design.md`) and the versioned prompt templates in `src/citation_verifier/prompts/`. **Do not add assessment criteria, batching rules, or prompt text to this file** — that is template work (a new prompt version + re-record).

## Steps

1. **Startup checks:** `venv/Scripts/python.exe -m citation_verifier --help` runs, and `.env` contains `COURTLISTENER_API_TOKEN` (else point the user at courtlistener.com > Profile > API Keys). Windows: always `venv/Scripts/python.exe`.
2. **Workdir:** create `matters/<short-name>/` (ask for a name if not obvious). If the source document has a caption, write `matters/<name>/brief_metadata.json` with `{"title", "case_name", "case_number", "filed_date"}` (used for the report header). For prepared pairs, copy the user's CSV to `matters/<name>/claims.csv` (columns per design §2; missing optional columns are tolerated).
3. **Run the chain:**
   - Document input: `venv/Scripts/python.exe -m citation_verifier verify-propositions matters/<name> full --document <path>`
   - Prepared pairs: the same command without `--document`.
4. **When the CLI prints PENDING** (extract, prescreen, or assess jobs), dispatch agents (step 5), then **rerun the same `full` command** — every verb is idempotent and resumes from the jobs sidecars.
5. **Jobs-mode dispatch:** read the pending jobs file (`jobs/extract.json`, `jobs/assess.json`, or `jobs/prescreen.json`). For each job, launch one general-purpose Agent subagent whose prompt is the job's `prompt` field verbatim, plus this appendix:

   > After producing your JSON object, append it to `<workdir>/jobs/<phase>_results.jsonl` as ONE line PER claim. For single-claim jobs the line is:
   > `{"claim_id": "<the job's claim_ids[0]>", "prompt_version": "<the job's prompt_version>", "model": "<your model>", "fields": <your JSON object>}`
   > For packed assess jobs (multiple claim_ids), write one line per entry of your `verdicts` array, with `fields` = that entry minus its `claim_id`.
   > Use only the Read tool on files in the workdir, plus those appends. No other tools.

   Run assess subagents in parallel, at most ~5 at a time. Do not edit claims.csv yourself — `apply-assessments` owns it (design §6.6).
6. **Finish:** the chain ends with `[OK] report: matters/<name>/report.html`. Open it for the user and summarize in chat: each Red finding with a one-line rationale; Yellow and Check Cite counts with brief notes; Green count; unable-to-verify cases.

## Resuming

Rerun the `full` command. Each verb no-ops when its output exists (`--force` to redo extract/verify), and the chain stops at the first pending LLM step.
