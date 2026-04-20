# /verify-brief retrospective: Protege AI make-whole premiums Q&A

**Date:** 2026-04-20
**Workdir:** `briefs/protege-makewhole/`
**Input:** `briefs/Protege make-whole premiums.md` — an AI Assistant's answer to a bankruptcy research question, cleaned up into markdown in the same session before verification.
**Result:** 3 Green / 4 Yellow / 1 Red across 8 propositions / 6 cases.

## What this run tested

First time running `/verify-brief` against a document that isn't a traditional filed brief — a Lexis/Protege-style AI research response, structured as narrative prose with block-quoted case excerpts following each attribution. The pipeline held up. Extraction, verification, download, assessment, and report generation all worked.

The headline finding was a genuine "inverts the holding" result on *Del. Trust Co. v. EFIH*, 842 F.3d 247 — the AI cites it to support the Momentive clear-language rule, but Judge Ambro's opinion actually rejects Momentive as "unpersuasive." That's the kind of substantive error the pipeline is built to catch, and it caught it.

## The headline legal finding

The user highlighted "consistently required" from line 41 of the brief:

> However, in bankruptcy, SDNY courts have consistently required clear and unambiguous language in the governing agreements to enforce make-whole premiums after acceleration.

That framing is the load-bearing claim for the entire "New York Law and SDNY Precedent" section, and it's the overstatement the EFH assessment exposes. *EFH* is not evidence that SDNY courts "consistently require" clear language — it's a Third Circuit opinion criticizing bankruptcy courts for stretching Northwestern's clear-statement rule beyond prepayment premiums. The AI pulled *EFH* into a citation string for a proposition *EFH* was decided against. The Yellow assessments on rows 4, 6, and 7 show the same pattern in milder form: the AI's statement of the rule is framed more categorically than any one of its citations actually supports.

## Rough edges that required intervention

### 1. Wrong opinion file for Hertz 2024 (citation-lookup returned a 2.5KB stub)

The citation-lookup API resolved *Reorganized Debtors v. Hertz Corp.*, 2024 U.S. App. LEXIS 34433, to a 57-line CourtListener cluster that's actually a September 25, 2024 procedural ORDER vacating and re-issuing the opinion under a corrected caption — not the substantive Third Circuit opinion. The cluster id the pipeline picked up (10124964) is the stub; the real opinion lives at cluster 10265999.

The pipeline had no way to detect this: it trusts whatever the API returns. The user caught it only because I paused to spot-check the opinion files and the 2.5KB file size stood out.

**Suggested fix:** Add a sanity check in `brief_pipeline.py` / `client.py`. If the downloaded opinion text is under some threshold (~5KB, or under N pages from the cluster metadata), warn the operator before using it as the grounding document. A deferred fallback to alternative clusters on the same citation may also help.

I recovered manually by using the CourtListener MCP to `get_cluster(10265999)` → `get_opinion(10732589)` and writing the `html_with_citations` field to replace the stub file. This is the first session where the MCP has been used alongside the citation_verifier package — they're separate codepaths hitting the same API.

### 2. Pinpoint pages in `cited_case` broke `--merge`

The SKILL instructs the propositions agent to append pinpoints after the start page (e.g., `874 F.3d 787, 802. (2017)`). The agent followed that instruction correctly — I could see the pinpoints in `claims.csv`. But `--merge` does exact-string matching of `cited_case` against `verification_results.csv`, which stores bare citations (no pinpoints). Result: 6 of 8 claims came back `unmatched` on the first merge.

I fixed it by stripping the pinpoints from `cited_case` with five manual Edits, then re-ran `--merge` to get 8/8 matched. Workaround, not a fix.

**Suggested fix:** Either (a) have the propositions agent omit pinpoints from `cited_case` entirely and put them in a separate column, or (b) make `merge_claims()` match on a normalized form that ignores trailing pinpoints. The SKILL and the CLI disagree about what `cited_case` should look like; one of them needs to change.

### 3. Opus assessment subagents couldn't write their output files

Both Batch A and Batch B subagents (general-purpose, given Read-only instructions per the SKILL) were denied the Write tool and denied `Bash` heredoc-writes. Each returned the JSON payload in its final summary message instead of writing the file. I then copied the JSON into `assessments_A.json` / `assessments_B.json` myself with the Write tool.

**Suggested fix:** Either (a) explicitly grant general-purpose subagents Write access to the workdir via a settings permission, or (b) change the SKILL to expect JSON returned in the agent summary rather than written to disk. Option (b) is cleaner and matches how subagents actually behaved here.

### 4. No CLI step for applying assessments — I had to write `apply_assessments.py`

**This is the answer to "explain why you had to write and run apply_assessments.py."** The pipeline has CLI subcommands for every mechanical step of the run:

- `--wave1`, `--wave2` — verify citations and download opinions
- `--merge` — join claims.csv with verification_results.csv
- `--check-quotes` — run the deterministic quote matcher
- `--metadata-check` — flag name mismatches and surface syllabus data
- `--report` — generate the HTML report from claims.csv

Every phase of the pipeline produces a specific CSV enrichment via a CLI command — **except** the assessment merge. After the Opus subagents produce `assessments_A.json` / `assessments_B.json` with the new columns (`assessment`, `badge_label`, `brief_block`, `opinion_block`, `finding_analysis`), there is no CLI step that reads those JSON files and writes the columns into `claims.csv`. The SKILL just says "read their JSON output files and merge them into claims.csv."

The maxwell-v-michael run that preceded this one left behind an ad-hoc `apply_assessments.py` — but it was written for an older assessment schema (`brief_text`, `opinion_text`, `explanation`) and also had the assessment results pasted inline into the script rather than read from JSON files. It couldn't be reused without rewriting the column names and the input pathway. Rather than modify it in place (where it exists as a historical artifact of that run), I wrote a new 30-line `briefs/protege-makewhole/apply_assessments.py` that reads both JSON files, merges by `row_index`, and writes the five target columns.

**Suggested fix:** Add a CLI subcommand — `python -m citation_verifier verify-brief <workdir> --apply-assessments` — that globs `assessments_*.json` in the workdir, merges them by `row_index`, and writes to claims.csv. The existing `merge_claims()` module in `brief_pipeline.py` is the right home. This would eliminate the one-off script and the column-name drift between runs. `--full` could then chain apply-assessments between assessment and report.

### 5. Windows vs Mac path confusion in the SKILL

The SKILL specifies `venv/Scripts/python.exe` (Windows) throughout. The SessionStart hook also said "WINDOWS ENV." But this session was darwin, and the first command failed. I switched to `source venv/bin/activate && python -m citation_verifier ...` for the rest of the run. No big deal for a one-off, but the SKILL should probably use a portable invocation (`python -m ...` after activation) or branch on platform.

## What worked well

- **Extraction was clean.** The propositions agent correctly identified that the quoted block passages are context, not claim-level quoted language — every `quoted_text` came back `[]`, which matches the document's structure.
- **Name-mismatch handling.** I warned both assessment subagents that the "In re: The Hertz Corporation v." / "Wells Fargo Bank, National Association v. The Hertz Corporation" / "Momentive Performance Materials Inc. v. BOKF, NA" retrieved names were CL caption shortcuts rather than real case mismatches. Both agents correctly ignored the name-mismatch flag and focused on substance. Good division of labor between deterministic (metadata check) and judgment (Opus).
- **Parallel subagents for assessment.** Two batches (3 + 3 opinions) ran concurrently in the background; saved wall time.
- **The Red on EFH is an appropriate strict call.** A less careful reviewer could have softened it to "Partial" because EFH does discuss the clear-language debate — but the relevant holding really does cut the other way, and the AI's proposition is the Momentive framing that EFH rejects. Batch B got that right.

## Followups worth filing

1. **Pipeline TODO:** Word-count / page-count sanity check on downloaded opinions; flag suspiciously short results from citation-lookup. (Hertz 2024 was the trigger.)
2. **Pipeline TODO:** `--apply-assessments` CLI step. Eliminates ad-hoc per-run scripts, enforces a single schema for the assessment columns.
3. **SKILL fix:** Pinpoint handling in `cited_case`. Either drop them before merge, or teach merge to normalize them out.
4. **SKILL fix:** Change subagent output contract — expect JSON in the returned summary, not a file write, since the subagents don't have Write perms in the default configuration.
5. **SKILL fix:** Portable Python invocation (not `venv/Scripts/python.exe`).

## Files left behind

- `briefs/protege-makewhole/brief.md` — copy of the cleaned-up input
- `briefs/protege-makewhole/brief_metadata.json`
- `briefs/protege-makewhole/citations_to_verify.txt`
- `briefs/protege-makewhole/claims.csv` — final merged state
- `briefs/protege-makewhole/verification_results.csv`
- `briefs/protege-makewhole/opinions/` — 6 opinion HTML files (Hertz 2024 replaced manually)
- `briefs/protege-makewhole/assessments_A.json`, `assessments_B.json`
- `briefs/protege-makewhole/apply_assessments.py` — ad-hoc merge script
- `briefs/protege-makewhole/report.html`
