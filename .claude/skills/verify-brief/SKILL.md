---
name: verify-brief
description: Use when user wants to verify citations in a legal brief, check if cited cases support the propositions they're cited for, or analyze a brief for hallucinated or misrepresented case law. Triggers on "verify brief", "check citations in brief", "analyze brief citations".
argument-hint: "[path to brief PDF or Word doc]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /verify-brief — Legal Brief Citation Verifier

Multi-phase pipeline: extract citations from a brief, verify against CourtListener, download opinion texts, assess whether each citation supports its proposition.

**Requirements:** `citation_verifier` package installed, `COURTLISTENER_API_TOKEN` in `.env`.

## Startup Checks

1. `venv/Scripts/python.exe -m citation_verifier --help` — if fails, tell user to install
2. Check `.env` has `COURTLISTENER_API_TOKEN` — if missing, guide to https://www.courtlistener.com/ > Profile > API Keys

## Working Directory

Create `briefs/<brief-name>/` in the project root. Ask user for a short name if not obvious.

```
briefs/<brief-name>/
├── brief.txt (or .pdf)       # Source brief
├── citations_to_verify.txt   # Phase 1a output
├── claims.csv                # Master table (evolves through phases)
├── verification_results.csv  # Pipeline output
├── opinions/                 # Downloaded opinion texts (.html/.txt/.pdf)
└── report.html               # Phase 4 output
```

## Phases

### Phase 1a: Extract Citation List

Read the brief (PDF via Read tool, or text). Extract every **case citation** — one per line in `citations_to_verify.txt`.

Rules:
- Case citations only (with reporter volume and page)
- Exclude: statutes, regulations, constitutional provisions, treatises, secondary sources, Federalist Papers
- Deduplicate — same case with different pinpoints = one line (use base citation without pinpoint)
- Format: `Case Name, Vol Reporter Page (Year)` — exactly as the brief cites it, minus pinpoint

Report: "Extracted X unique case citations."

### Phase 1b: Wave 1 — Batch Verify + Download

Run the pipeline CLI:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --wave1
```

This does a single batch API call and downloads opinion texts for all hits. Takes ~1-2 minutes.

### Phase 1c: Propositions + Wave 2 (Concurrent)

Launch **two concurrent agents**:

**Agent 1 (Opus) — Extract propositions:**
- Read the brief
- Reference the citation list from `citations_to_verify.txt`
- Extract every proposition-case pair into `claims.csv` with columns: `page,proposition,cited_case`
- CRITICAL: The `cited_case` column MUST start with the exact full citation text from `citations_to_verify.txt` (including case name, reporter, and year). Append pinpoint pages after the start page (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Do NOT abbreviate, omit the reporter, or use short-form case names.
- Same case cited for different propositions = separate rows
- Same proposition supported by multiple cases = separate rows
- Exclude non-case sources

**Agent 2 (background bash) — Wave 2 fallback (only if wave1 had misses):**
Check wave1 output first. If wave1 reported "Misses for wave 2: 0", skip wave2 entirely. Otherwise:
```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --wave2
```

**After both finish — Merge:**
```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --merge
```

This joins `claims.csv` with `verification_results.csv`, linking each claim to its verification status and opinion file.

If merge reports unmatched claims, fix the `cited_case` values in `claims.csv` to match exactly what's in `citations_to_verify.txt` (with pinpoint pages appended), then re-run `--merge`.

### Phase 2: Assess Wave 1 Cases (Opus Subagents)

Group claims by opinion file. For each opinion with a downloaded file, launch an Opus subagent.

**Subagent input:**
- Opinion file path to read
- List of claims: `[{row_index, proposition, cited_case}]`
- Assessment criteria (below)

**Subagent instructions:**
> Read the entire opinion using the Read tool. Do NOT use grep, search, or scripting to analyze it — you must read and comprehend the full text. For opinions > 80K characters, read in chunks using offset/limit (2000 lines per chunk). Read ALL chunks.
>
> For each claim, find passages that address the proposition. Write your response as a JSON array:
> ```json
> [{"row_index": 7, "assessment": "Green", "supporting_language": "(1) Supports: \"exact quote...\""}]
> ```

**Assessment criteria:**
- **Green** — case directly and accurately supports the proposition as stated
- **Yellow** — partially relevant, support weaker than represented, pinpoint off, or proposition overstates holding
- **Red** — does not support, misleading, or quoted language doesn't appear in opinion

**Special cases:**
- POSSIBLE_MATCH: subagent reads opinion and decides if it's the right case. If wrong case → Red.
- No opinion text available (empty `opinion_file`): auto-Yellow — "Case verified but opinion text not available for review." No subagent needed.

**Batching:** One subagent per opinion file. Each reads the opinion once, assesses all propositions citing it.

After all subagents return, update `claims.csv` with `assessment` and `supporting_language`.

### Phase 3: Assess Wave 2 Cases (Opus Subagents)

Same contract as Phase 2 for Wave 2 cases that resolved with opinion text.

**NOT_FOUND with no opinion text → auto-Red:**
- `assessment`: "Red"
- `supporting_language`: "Case not found on CourtListener -- cannot verify citation."
- No subagent needed for these.

After all subagents return, update `claims.csv`.

### Phase 4: Report

Always generate both a chat summary and `report.html`.

**Chat summary:**
- Stats: X Green, Y Yellow, Z Red
- List all Red with proposition + brief rationale
- List all Yellow with brief notes
- Green count only (no detail unless asked)

**`report.html`:**
- Styled table with color-coded assessment column (green=#d4edda, yellow=#fff3cd, red=#f8d7da)
- Supporting language as blockquotes
- Multiple passages as separate labeled blockquotes
- Brief metadata header (filename, date, total citations, summary stats)
- CourtListener URLs as clickable links

## Resuming

If `claims.csv` already exists, detect state and resume:

| State | Resume at |
|-------|-----------|
| No `claims.csv` | Phase 1a |
| Has `cited_case` but no `cl_status` | Phase 1b (wave1) |
| Has `cl_status` but no `assessment` | Phase 2 |
| Has `assessment` | Phase 4 (report) |

Announce: "Found existing work. Resuming at Phase N."
