# Design: Haiku Prescreen + Verbatim Quote Checker

**Date:** 2026-03-10
**Status:** Approved

## Overview

Two additions to the verify-brief pipeline:
1. **Haiku summary step** — Explore (Haiku) agents produce claim-targeted summaries of opinions. Opus assesses from summaries instead of full text. Opinions under 20K chars skip summarization.
2. **Verbatim quote checker** — Deterministic string matching extracts quoted text from `claims.csv`, searches opinion files for matches, writes results back to CSV. Results are passed to Opus assessment.

## Key Decisions

- **Architecture split (C):** Summaries stay in SKILL.md (Explore agents). Quote checker goes in `brief_pipeline.py` (deterministic Python).
- **Quoted text storage (B):** New `quoted_text` column in claims.csv as JSON array.
- **Summary format (B):** Claim-targeted summaries with TOPICS FOUND / TOPICS NOT FOUND structure. Tested at 75% exact match / 3% lenient across 161 claims.
- **Size threshold (A):** 20K chars. Opinions under this go straight to Opus — no summary step.
- **Quote-check flow (A):** Persisted as CSV columns, passed into Opus assessment prompt as additional context.

## Data Flow

```
Phase 1a: Extract citations → citations_to_verify.txt
Phase 1b: Wave 1 verify + download → verification_results.csv + opinions/
Phase 1c: Extract propositions + quoted_text → claims.csv
Phase 1b continued: Wave 2 fallback + merge → claims.csv updated
NEW: Quote check → claims.csv quote_check columns filled
NEW: Haiku summaries → opinions/*_summary.txt files written
Phase 2: Opus assessment (reads summaries + quote_check) → claims.csv assessment filled
Phase 4: Report generation → report.html
```

## Phase 1c Changes

Add `quoted_text` column to `claims.csv`. JSON array of any text appearing in quotation marks in the brief for that claim.

```csv
page,proposition,cited_case,quoted_text
21,"Court held sanctions require bad faith","Fox v. Vice, 563 U.S. 826, 834 (2011)","[""no desire to deter"", ""but-for causation""]"
14,"Statute allows fee shifting","Cooter & Gell v. Hartmarx, 496 U.S. 384, 393 (1990)","[]"
```

Phase 1c prompt instruction: "For each claim, extract any text that appears inside quotation marks in the brief's sentence. Put these in the `quoted_text` column as a JSON array. If the claim has no quoted text, use `[]`."

## Verbatim Quote Checker (`brief_pipeline.py`)

New function `check_quotes(workdir)`:

1. Read `claims.csv`, iterate rows where `quoted_text` is non-empty and `opinion_file` exists
2. For each quoted string, normalize both quote and opinion text:
   - Strip smart quotes → straight quotes
   - Normalize whitespace
   - Remove `[bracketed alterations]` and `...` ellipses before matching
3. Use `difflib.SequenceMatcher` to find best match in opinion text
4. Classify:
   - `VERBATIM`: ratio > 0.85
   - `CLOSE`: 0.6–0.85
   - `FABRICATED`: < 0.6
5. Write per-quote results to `quote_check` column as JSON array:
   ```json
   [{"quote": "no desire to deter", "result": "FABRICATED", "similarity": 0.31}]
   ```
6. Write worst-case roll-up to `quote_check_worst` column: `VERBATIM`, `CLOSE`, `FABRICATED`, or `NO_QUOTES`

CLI: `python -m citation_verifier verify-brief <workdir> --check-quotes`

## Haiku Summary Step (`SKILL.md`)

New phase between merge and assessment. For each unique opinion file in `claims.csv`:

1. Check file size. If < 20K chars → skip (Opus reads directly in assessment)
2. Group claims by opinion file
3. Launch Explore (Haiku) agent per opinion with prompt:
   - "Read the full opinion at `{path}`. For each proposition below, report what you found."
   - Structured output: `TOPICS FOUND:` with supporting quotes/page refs, `TOPICS NOT FOUND:` with emphatic statement of absence
4. Write summary to `opinions/{case_name}_summary.txt`

## Opus Assessment Changes (`SKILL.md`)

Assessment prompt updated to include:
- For opinions > 20K: summary file instead of full opinion
- For opinions < 20K: full opinion (unchanged)
- Quote-check results for each claim: "Quote check: {result} — brief quotes '{text}' {match detail}"
- Updated criteria: a claim can be Green on substance but should be downgraded to at least Yellow if quotes are FABRICATED

## New CSV Columns

| Column | Type | Example |
|--------|------|---------|
| `quoted_text` | JSON array | `["no desire to deter"]` |
| `quote_check` | JSON array | `[{"quote": "...", "result": "FABRICATED", "similarity": 0.31}]` |
| `quote_check_worst` | string | `FABRICATED` / `CLOSE` / `VERBATIM` / `NO_QUOTES` |

## What Doesn't Change

- Wave 1/Wave 2 verification logic
- Opinion downloading
- Merge logic (passes through new columns)
- Report generation (can optionally surface quote_check_worst)

## Test Plan

### Quote checker
- Test on 4 known false negatives (Fox rows 26/29/35, Thomas row 53) — fabricated quotes that deterministic search should catch
- Test on 10 Green rows to ensure real quotes aren't false-flagged
- Test on Yellow rows with close paraphrases (Cooter row 16, In re Case rows 41/55)
- Test non-quoted propositions correctly return NO_QUOTES

### Haiku prescreen
- Already validated across 4 briefs / 161 claims: 76% exact match, 21% conservative, 3% lenient, 0 R->G

## Evidence

- `scratch/fletcher-prescreen-results.md` — Full Fletcher test results and four-way comparison
- `docs/retrospectives/2026-03-10-verify-brief-fletcher-v-experian.md` — Fletcher retrospective
- Prior 3-brief test: 102 claims, 76% match (referenced in fletcher-prescreen-results.md)
