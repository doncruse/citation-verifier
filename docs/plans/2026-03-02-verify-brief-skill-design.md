# Design: `/verify-brief` Skill

**Date:** 2026-03-02
**Status:** Approved

## Overview

A Claude Code skill that guides users through verifying every citation in a legal brief. Takes a brief (PDF, Word doc, or pasted text), extracts each legal claim with its supporting citation, verifies and retrieves each case via CourtListener, then reads the retrieved opinions to assess whether each citation actually supports the proposition it's cited for.

The user brings their own CourtListener API key. No LLM API key is needed -- all claim extraction and text analysis happens in the Claude Code chat.

## Skill Identity

- **Name:** `verify-brief`
- **Invocation:** `/verify-brief` or natural language ("verify a brief", "check citations in a brief")
- **Location:** `~/.claude/skills/verify-brief/SKILL.md`
- **Tools needed:** Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion

## Prerequisites (checked at startup)

1. `citation_verifier` package installed (`python -m citation_verifier --help`)
2. `COURTLISTENER_API_TOKEN` set in environment (or `.env` file)
3. If either is missing, guide the user through setup

## Working Directory

Each brief gets its own directory in the current working directory:

```
briefs/<brief-name>/
├── brief.txt              # Extracted/pasted brief text
├── claims.csv             # Master table (6 columns + internal fields)
├── verification.json      # Raw verification results from CLI
├── opinions/              # Downloaded opinion texts
│   ├── obergefell-v-hodges.txt
│   └── ...
└── report.html            # Optional HTML report
```

## CSV Schema

### User-facing columns

| # | Column | Description |
|---|--------|-------------|
| 1 | **page** | Page number in the brief where the proposition and citation appear |
| 2 | **proposition** | The specific legal claim, proposition of law, or quoted language as it appears in the brief. Direct quotes use quotation marks. |
| 3 | **cited_case** | Full case citation as provided in the brief (case name, reporter, pinpoint cite if given). One case per row. |
| 4 | **retrieved_case** | Matched case name, date, and status from CourtListener verification |
| 5 | **supporting_language** | Specific passage(s) from the retrieved case that support or fail to support the proposition. Multiple passages numbered: (1) "..." (2) "..." |
| 6 | **assessment** | Green / Yellow / Red with brief rationale |

### Internal columns

| Column | Description |
|--------|-------------|
| **cl_url** | CourtListener match URL |
| **cl_status** | Raw verification status (VERIFIED, LIKELY_REAL, POSSIBLE_MATCH, NOT_FOUND) |
| **diagnostics** | Verification diagnostics (List[Diagnostic] with .category and .message) |
| **user_action** | User override: "accepted", "rejected", "uploaded", "fake", "inapplicable" |
| **opinion_file** | Path to downloaded opinion text file |

## Phases

### Phase 1: Extract Claims + Citations

1. Read the brief (PDF via Read tool, pasted text, or Word doc converted to text)
2. Work through the brief page by page
3. For each proposition of law supported by a citation, create a row:
   - One row per **proposition-case pair** (same case cited for different propositions = multiple rows; same proposition supported by multiple cases = multiple rows)
4. Write `claims.csv` with `page`, `proposition`, and `cited_case` filled in; other columns empty
5. Present summary in chat: "Found X propositions citing Y unique cases across Z pages"
6. User can review/edit the CSV before proceeding

### Phase 2: Verify Citations

1. Read `claims.csv`, extract unique cases from `cited_case`
2. Write a temp file with one citation per line
3. Run `python -m citation_verifier --file temp.txt --json`
4. Parse results, update `claims.csv`:
   - `retrieved_case`: matched case name + date + display status
   - `cl_url`: CourtListener URL
   - `cl_status`: raw verification status
   - `diagnostics`: Diagnostic objects (each with .category and .message)

**Display status mapping** (aligned with web app Retrieve page):

| VerificationStatus | Display | Color |
|---|---|---|
| VERIFIED, LIKELY_REAL | **Ready** | Green |
| POSSIBLE_MATCH (name mismatch) | **Check Name** | Yellow |
| POSSIBLE_MATCH (court mismatch) | **Check Court** | Yellow |
| POSSIBLE_MATCH (date mismatch) | **Check Date** | Yellow |
| POSSIBLE_MATCH (no specific diagnostic) | **Review** | Yellow |
| NOT_FOUND | **Not Found** | Red |

Multiple "Check" flags can appear together (e.g., "Check Name, Check Date").

5. Save raw verification JSON to `verification.json`
6. Report summary: "X Ready, Y need review, Z not found"

### Phase 2.5: Interactive Review

After verification, present results and let the user take action:

1. **"Check" cases** -- Show each case with its match details. User can:
   - **Accept** -- treat as verified (mark `user_action=accepted`)
   - **Reject** -- mark as not the right case

2. **"Not Found" cases** -- For each, user can:
   - **Upload a case** -- provide a file path or paste text. Saved to `opinions/`, marked `user_action=uploaded`
   - **Mark as fake** -- confirmed hallucinated citation. Sets assessment to Red, supporting_language to "Case confirmed fictitious -- citation does not exist." Marked `user_action=fake`
   - **Mark as inapplicable** -- wrong case entirely, not worth checking. Sets assessment to Red, supporting_language to "Citation inapplicable -- removed by reviewer." Marked `user_action=inapplicable`
   - **Skip** -- leave as Not Found, assess as Red later

3. Update `claims.csv` with user decisions

### Phase 3: Retrieve Opinion Texts

1. For each case with status Ready or user_action=accepted:
   - Extract the CourtListener URL from verification results
   - Download opinion text via Python (`get_opinion_text()` from the client library)
   - Save to `opinions/<case-name-slug>.txt`
2. Skip cases marked fake/inapplicable
3. Include user-uploaded texts (already in `opinions/`)
4. Report: "Downloaded X of Y opinion texts"
5. Update `claims.csv` with `opinion_file` paths

### Phase 4: Assess Claims

1. Group rows by cited case (read each opinion only once)
2. For each case with an opinion file:
   - Claude reads the full opinion text
   - Evaluates **all** propositions that cite this case
   - Identifies **all** relevant passages (supporting and contradicting)
3. Fill in:
   - `supporting_language`: Multiple passages numbered, each labeled with its relationship:
     - "(1) Supports: '...' (2) Contradicts: '...' (3) Addresses different issue: '...'"
   - `assessment`:
     - **Green** -- case directly and accurately supports the proposition as stated
     - **Yellow** -- partially relevant, support is weaker than represented, pinpoint cite is off, or proposition overstates the holding
     - **Red** -- does not support the proposition, is misleading, case not found, or quoted language doesn't appear
4. For fake/inapplicable/not-found cases: pre-filled in Phase 2.5
5. Update `claims.csv` incrementally (save after each case)

### Phase 5: Report

1. Present formatted summary in chat:
   - Overall stats: X green, Y yellow, Z red
   - List all Red assessments with details
   - List all Yellow assessments with brief notes
   - Green cases summarized as count only
2. Ask if user wants an HTML report
3. If yes, generate `report.html`:
   - Styled table with color-coded assessment column
   - Supporting language shown as expandable blockquotes
   - Each passage labeled with its relationship to the proposition
   - Brief metadata at top (file name, date, total citations)

## Design Decisions

- **LLM for extraction, not regex** -- Claude reads the brief directly and understands legal context. No PDF/docx parsing libraries needed for the brief itself.
- **CLI for verification** -- Shell out to `python -m citation_verifier` rather than importing Python modules. Keeps the skill portable and decoupled from project internals.
- **CSV as checkpoint** -- Users can pause after any phase, edit the CSV, and resume. Standard format, opens in Excel/Sheets.
- **Start simple, add RAG later** -- Claude reads full opinion texts directly. If context limits become an issue with very long opinions, a RAG pipeline can be added as a future enhancement without changing the skill structure.
- **No case substitution in v1** -- Users can upload cases for Not Found citations, but there's no mechanism to search for alternative citations. Deferred to v2.

## Future Enhancements

- RAG pipeline for very long opinions
- Case substitution search (suggest alternative citations)
- Integration with the web app for streaming verification results
- Support for multiple briefs in a single analysis (e.g., motion + response)
- Export to Word document with tracked changes / comments
