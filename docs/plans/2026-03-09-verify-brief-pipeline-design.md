# Verify-Brief Pipeline Redesign

**Date:** 2026-03-09
**Status:** Design approved
**Motivation:** Move all mechanical work out of the skill into a Python pipeline module. The skill orchestrates only the LLM-hard parts (proposition extraction, opinion assessment). Incorporates feedback from Kettering (test 1) and Valve v. Rothschild (test 2) retrospectives.

## Problem

The current `/verify-brief` skill embeds code snippets for verification, downloading, and merging. Every mechanical step left to LLM interpretation has gone wrong at least once: grep instead of Read, sync instead of async, CLI instead of API, wrong diagnostics type, no sanity checks. Moving mechanical work into tested Python code fixes this.

## Pipeline Module: `src/citation_verifier/brief_pipeline.py`

### Public API

```python
async def wave1_verify_and_download(workdir: Path, citations: list[str]) -> Wave1Result
```
- Calls `verify_batch(citations, quick_only=True)` — single API call
- Downloads opinions for all hits (VERIFIED, LIKELY_REAL, POSSIBLE_MATCH)
- Download priority: `html_with_citations` → `plain_text` → PDF
- Sanity check: compare downloaded case name to expected (flag mismatches in diagnostics)
- Writes `verification_results.csv` (hits only)
- Returns: list of results, list of miss indices, download stats

```python
async def wave2_fallback_and_download(workdir: Path, citations: list[str], miss_indices: list[int]) -> Wave2Result
```
- Runs full verify pipeline (opinion search + RECAP) for each miss
- Downloads opinions for any that resolve
- Appends to `verification_results.csv`
- Returns: results for misses, download stats

```python
def merge_claims(workdir: Path) -> MergeStats
```
- Reads `claims.csv` (Phase 1 output: `page, proposition, cited_case`)
- Reads `verification_results.csv`
- Joins on base citation (pinpoint stripping only — no fuzzy matching)
- Fills in: `retrieved_case`, `cl_url`, `cl_status`, `diagnostics`, `opinion_file`
- Handles non-case citations gracefully (treatises, etc. get no verification data)
- Returns: matched/unmatched/status counts/opinion counts

```python
async def full_pipeline(workdir: Path, citations: list[str]) -> PipelineResult
```
- Convenience wrapper: wave1 → wave2 → merge sequentially

### CLI Entry Point

`python -m citation_verifier verify-brief <workdir> [--wave1 | --wave2 | --merge]`

### Data Structures

- `Wave1Result(results, miss_indices, download_stats)`
- `Wave2Result(results, download_stats)`
- `MergeStats(matched, unmatched, statuses, opinion_counts)`
- Uses existing `Diagnostic(category, message)` objects throughout

### Download Priority

1. `html_with_citations` — raw HTML with citation links preserved → `opinions/case-name.html`
2. `plain_text` → `opinions/case-name.txt`
3. PDF via `filepath_local` → `opinions/case-name.pdf`

Opus Read tool handles all three formats natively.

### Sanity Checks

- **Wrong opinion text (Fortune Dynamic problem):** After downloading, compare case name from `get_opinion_text_with_metadata()` to expected case name. If low match score, add diagnostic: "Warning: downloaded text may be wrong case."
- **No text available (PacTool/Diamondback):** Mark `opinion_file` empty, add diagnostic "No opinion text available on CourtListener."
- **Duplicate citations:** Deduplicate for verification, keep all rows in claims.csv.

### Changes to `client.py`

- Modify `get_opinion_text_with_metadata()` to optionally return raw HTML (new parameter `prefer_html=True`)
- Add PDF download fallback when no text/HTML available

## Skill: `/verify-brief` (Revised)

### Phase Structure

| Phase | Model | What happens |
|-------|-------|-------------|
| 1a | Haiku | Read brief, extract `citations_to_verify.txt` |
| 1b | — (pipeline) | `--wave1`: batch verify + download hits |
| 1c | Opus + pipeline | **Concurrent:** Opus extracts propositions → `claims.csv`. Pipeline `--wave2` for misses. Then `--merge`. |
| 2 | Opus subagents | Assess Wave 1 cases (parallel subagents, one per opinion) |
| 3 | Opus subagents | Assess Wave 2 cases. NOT_FOUND with no opinion → auto-Red. |
| 4 | — | Always generate `report.html` + summary in chat |

### Concurrency Diagram

```
1a: Haiku extracts citations (~30 sec)
1b: Pipeline wave1 verify+download (~1-2 min)
1c: ┌─ Opus extracts propositions (~3 min) ─────────────┐
    └─ Pipeline wave2 fallback+download (~2 min) ─┘     │
    merge ◄──────────────────────────────────────────────┘
2:  Opus subagents assess Wave 1 cases (~3-4 min) ──────────────┐
3:  Opus subagents assess Wave 2 cases (~1-2 min, after wave2) ─┤
4:  Generate report ◄───────────────────────────────────────────┘
```

### Phase 1a: Extract Citation List (Haiku)

- Reads brief directly (PDF or text — no preprocessing needed)
- Outputs `citations_to_verify.txt`, one citation per line
- Excludes statutes, regulations, constitutional provisions, treatises, secondary sources
- Only case citations with reporter volume and page

### Phase 1b: Wave 1 Verify + Download (Pipeline)

- `python -m citation_verifier verify-brief <workdir> --wave1`
- Reads `citations_to_verify.txt`
- Batch verify (single API call), download all with matched URLs
- Writes `verification_results.csv`

### Phase 1c: Propositions + Wave 2 (Concurrent)

**Opus proposition extraction:**
- Reads the brief
- Receives the citation list from 1a as reference
- Instructed: "Use `cited_case` values from the citation list exactly, adding pinpoint pages as needed"
- Writes `claims.csv` with columns: `page, proposition, cited_case`
- Excludes non-case sources

**Pipeline wave2 (concurrent):**
- `python -m citation_verifier verify-brief <workdir> --wave2`
- Fallback verify for NOT_FOUND misses
- Downloads any that resolve

**After both finish:**
- `python -m citation_verifier verify-brief <workdir> --merge`
- Joins claims.csv with verification results

### Phase 2: Assess Wave 1 Cases (Opus Subagents)

**Subagent contract — Input:**
- Opinion file path (`.html`, `.txt`, or `.pdf`)
- List of `(row_index, proposition, cited_case, pinpoint_page)` tuples
- Assessment criteria

**Subagent contract — Output:**
```json
[
  {
    "row_index": 7,
    "assessment": "Green",
    "supporting_language": "(1) Supports: \"The President's authority...\""
  }
]
```

**Assessment criteria:**
- **Green** — case directly and accurately supports the proposition
- **Yellow** — partially relevant, support weaker than represented, pinpoint off, or proposition overstates holding
- **Red** — does not support, misleading, case not found, or quoted language doesn't appear

**Special cases:**
- POSSIBLE_MATCH: subagent reads opinion and determines if it's the right case. If not → Red.
- No opinion text available: auto-Yellow "Case verified but opinion text not available for review"
- Downloaded text sanity check failed: subagent notified via diagnostics, can assess independently

**Batching:** One subagent per opinion file (or 2-3 small opinions per subagent). Each reads the opinion once, assesses all propositions citing it.

**Long opinions (> 80K chars):** Read in chunks via Read tool offset/limit. Read full text — do not skip sections.

### Phase 3: Assess Wave 2 Cases (Opus Subagents)

Same contract as Phase 2. NOT_FOUND with no opinion → auto-Red, no subagent needed.

### Phase 4: Report

- Summary in chat: X Green, Y Yellow, Z Red
- List all Red with proposition + rationale
- List all Yellow with brief notes
- Green count only
- Always generate `report.html` (no AskUserQuestion)

### Resuming

Detection based on `claims.csv` state:
- No `claims.csv` → start at Phase 1a
- Has `cited_case` but no `cl_status` → Phase 1b (wave1)
- Has `cl_status` but no `assessment` → Phase 2
- Has `assessment` → Phase 4 (report)

### Working Directory

```
briefs/<brief-name>/
├── brief.txt (or .pdf)       # Source brief
├── citations_to_verify.txt   # Phase 1a output
├── claims.csv                # Master table (evolves through phases)
├── verification_results.csv  # Pipeline output
├── opinions/                 # Downloaded opinion texts (.html/.txt/.pdf)
└── report.html               # Phase 4 output
```

## Removed from Skill

- All embedded code snippets
- AskUserQuestion (POSSIBLE_MATCH decided by Opus during assessment)
- Phase 2.5 interactive review
- `verification.json` sidecar
- Model recommendation table (models specified per-phase in the phase descriptions)

## Future Optimizations

- **Move wave2 to Phase 2:** Currently wave2 runs concurrent with Opus proposition extraction (Phase 1c). If wave2 fallback is slow (many NOT_FOUND cases), it might be better to run it concurrent with Phase 2 Opus assessment instead — overlapping the two longest steps. Depends on the ratio of batch hits to misses. Worth revisiting after more real-world runs.
- **Haiku citation-extractor plugin agent:** A custom agent with `model: haiku` was prototyped at `.claude/plugins/citation-verifier/agents/citation-extractor.md`. Could be used for Phase 1a instead of the built-in Explore agent, which has a smaller context window and fell back to grep on a 138K-char brief.
- **Streaming assessment dispatch:** Instead of two discrete waves, dispatch Opus subagents as soon as each opinion downloads. True async producer-consumer. Complexity may not be worth it if wave1 resolves most cases.
