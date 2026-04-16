---
name: verify-brief
description: Use when user wants to verify citations in a legal brief, check if cited cases support the propositions they're cited for, or analyze a brief for hallucinated or misrepresented case law. Triggers on "verify brief", "check citations in brief", "analyze brief citations".
argument-hint: "[path to brief PDF or Word doc]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /verify-brief — Legal Brief Citation Verifier

Multi-phase pipeline: extract citations from a brief, verify against CourtListener, download opinion texts, check quotes, triage, assess whether each citation supports its proposition, generate an interactive report.

**Requirements:** `citation_verifier` package installed, `COURTLISTENER_API_TOKEN` in `.env`.

## Startup Checks

1. `venv/Scripts/python.exe -m citation_verifier --help` — if fails, tell user to install
2. Check `.env` has `COURTLISTENER_API_TOKEN` — if missing, guide to https://www.courtlistener.com/ > Profile > API Keys

## Working Directory

Create `briefs/<brief-name>/` in the project root. Ask user for a short name if not obvious.

```
briefs/<brief-name>/
├── brief.pdf (or .txt)       # Source brief
├── brief_metadata.json       # Case name, number, filed date (for report header)
├── citations_to_verify.txt   # Phase 1a output
├── claims.csv                # Master table (evolves through phases)
├── verification_results.csv  # Pipeline output
├── opinions/                 # Downloaded opinion texts (.html/.txt/.pdf)
└── report.html               # Phase 4 output
```

After creating the working directory, write `brief_metadata.json`:
```json
{
  "title": "Brief title as it appears on the document",
  "case_name": "Plaintiff v. Defendant",
  "case_number": "No. X:XX-CV-XXXXX (Court)",
  "filed_date": "Month Day, Year"
}
```

## Phases

### Phase 1a: Extract Citation List

Read the brief (PDF via Read tool, or text). Extract every **case citation** — one per line in `citations_to_verify.txt`.

Rules:
- Case citations only (with reporter volume and page)
- Exclude: statutes, regulations, constitutional provisions, treatises, secondary sources, Federalist Papers
- Deduplicate — same case with different pinpoints = one line (use base citation without pinpoint)
- Format: `Case Name, Vol Reporter Page (Year)` — exactly as the brief cites it, minus pinpoint
- **Citation inconsistencies**: If the Table of Authorities and the body text cite different reporter volumes or page numbers for the same case, include BOTH variants in `citations_to_verify.txt` (on separate lines) so the verifier can look up both. Note the discrepancy for the user.

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
- Extract every proposition-case pair into `claims.csv` with columns: `page,proposition,cited_case,quoted_text`
- CRITICAL: The `cited_case` column MUST start with the exact full citation text from `citations_to_verify.txt` (including case name, reporter, and year). Append pinpoint pages after the start page (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Do NOT abbreviate, omit the reporter, or use short-form case names.
- `quoted_text`: JSON array of any text that appears inside quotation marks in the brief's sentence for this claim. Extract the exact quoted words from the brief. If the claim has no quoted text, use `[]`. Example: `["no desire to deter", "but-for causation"]`
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

This joins `claims.csv` with `verification_results.csv`, linking each claim to its verification status, opinion file, and syllabus metadata (from the citation-lookup API). The syllabus column is used in Phase 1d for topic-mismatch triage.

If merge reports unmatched claims, fix the `cited_case` values in `claims.csv` to match exactly what's in `citations_to_verify.txt` (with pinpoint pages appended), then re-run `--merge`.

### Phase 1d: Quote Check + Metadata Check

Run sequentially:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --check-quotes
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --metadata-check
```

The quote check verifies every quoted string against the opinion file. The metadata check flags name mismatches, NOT_FOUND citations, and surfaces syllabus data for each claim.

Report the results of both, including the syllabus items. For any claim that has syllabus data, print:
```
  Syllabus check:
    - p.3: "Prior settlement evidence is irrelevant" / Syllabus: "RICO; anti-abortion protesters; harassment"
    - p.6: "Bad faith required for spoliation" / Syllabus: "spoliation; bad faith; adverse inference"
```

Review these for obvious topic mismatches. A proposition about "settlement evidence" paired with a syllabus about "RICO, anti-abortion protesters" is an immediate red flag — add it to the mandatory assessment list.

These results determine the triage for Phase 2.

### Phase 2: Triage + Assess

This phase has three steps: triage, grep/summarize, and Opus assessment. The triage happens first so we only do expensive work on claims that need it.

#### Step 2a: Triage

Split claims into two tracks based on Phase 1d results (quote check + metadata check + syllabus review). **Every claim gets checked against the opinion text** — the triage determines *how deep*, not *whether*.

**Full Opus assessment** (any of these flags):
- `quote_check_worst` is `FABRICATED` or `CLOSE`
- Metadata check flagged `name_mismatch`
- Syllabus vs. proposition topic mismatch (LLM judgment from the syllabus items above)
- Claim has quoted text (`quoted_text` is not `[]`)
- Case is the lead authority in a section of the brief (first citation in a paragraph that introduces an argument)

**Fast track** (all of these must be true):
- `quote_check_worst` is `NO_QUOTES` or `VERBATIM`
- No metadata flags or syllabus concerns
- Not a lead authority

Fast-track claims still get verified — they go through the grep step (Step 2b) and get a Haiku confirmation. The difference is they don't get a full Opus assessment unless the grep or Haiku step raises a concern. See Step 2b for the fast-track flow.

Report: "Triage: X claims for full Opus assessment, Y claims for fast-track verification."

#### Step 2b: Grep + opinion research (all claims)

For each opinion file, grep for each claim's key terms. This serves two purposes: gathering excerpts for Opus assessment (full-assessment claims) and verifying topical relevance (fast-track claims).

**For all claims citing an opinion, run grep searches:**

1. **Grep for the brief's exact quoted language** (if any). Use a distinctive 4-6 word substring from the quote, not the whole thing (handles line breaks and minor formatting).
2. **Grep for 2-3 key legal terms from the proposition.** Example: if the proposition is about "prior settlement evidence is irrelevant," grep for `settlement`, `prior verdict`, `collateral source`.
3. **Grep for the brief's parenthetical language** if the citation has one.

For each grep hit, use the Read tool to read ~100 lines around the hit (50 before, 50 after) to capture the full paragraph and surrounding context.

**When greps find relevant passages:**

- For **full-assessment claims**: save the excerpts to `opinions/{case_name}_excerpts.txt` with grep terms noted. These go to the Opus assessment agent in Step 2c.
- For **fast-track claims**: the excerpts go to a Haiku confirmation agent (see below).

**When greps find nothing (all searches return 0 hits):**

This strongly suggests the opinion doesn't discuss the proposition's topic at all — but the opinion might use different terminology. This applies to both tracks:

- For **full-assessment claims on large opinions (>= 20K chars)**: launch a Haiku full-read as a safety net (see prompt below).
- For **fast-track claims**: the grep miss is itself a red flag. Escalate the claim to full Opus assessment — if the opinion doesn't even contain the proposition's key terms, something may be wrong.
- For **any claim on opinions < 20K chars**: skip grep entirely. Opus reads the full opinion directly in Step 2c (fast-track claims get Haiku confirmation from the full text instead).

**Haiku full-read** (only for large opinions with grep misses):

Launch an **Explore** agent (runs on Haiku; include "very thorough" in the prompt):

> Very thorough search needed. Read the ENTIRE opinion file at `{opinion_path}` using the Read tool. This is a legal opinion.
>
> I searched for the following terms and found NOTHING:
> {list of grep terms that returned 0 hits}
>
> Propositions to check (these are claims a brief makes about this case):
> {numbered list of propositions from ALL claims citing this opinion — both full-assessment and escalated fast-track}
>
> **Your job:** Determine whether this opinion discusses these topics AT ALL, even using different terminology. The grep misses suggest it might not, but confirm by reading.
>
> **Output format — follow exactly:**
>
> CASE SUMMARY:
> [1-2 sentences: what this case is actually about — its core dispute and holding]
>
> KEY HOLDINGS:
> [Bullet list of actual holdings]
>
> PROPOSITION ANALYSIS:
> For each proposition, write:
> - Proposition N: FOUND or NOT FOUND
>   - If FOUND: quote the relevant passage verbatim (with page/section reference if visible). Explain why the grep terms missed it (different terminology, etc.).
>   - If NOT FOUND: confirm the opinion does not discuss this topic. State what the opinion actually covers instead. Be specific.
>
> Be precise. Only summarize — do NOT assess whether propositions are supported.

Save the agent's output to `opinions/{case_name}_summary.txt`.

**Haiku fast-track confirmation** (for fast-track claims with grep hits):

For fast-track claims where grep found relevant passages, launch an **Explore** agent (Haiku) to confirm the proposition is supported:

> Read the following excerpts from `{opinion_path}`. These are passages found by searching for terms related to the proposition.
>
> Excerpts:
> {the grep excerpts — ~100 lines of context per hit}
>
> Proposition the brief attributes to this case:
> "{proposition text}"
>
> **Question:** Based on these excerpts, does the opinion support this proposition? Answer one of:
> - SUPPORTED: [one sentence explaining how, with a key quote from the excerpts]
> - UNCLEAR: [the excerpts touch on the topic but it's not clear whether they support the specific proposition — needs full Opus assessment]
> - NOT SUPPORTED: [the excerpts discuss a different aspect of the topic, or contradict the proposition]
>
> Be precise. If in doubt, say UNCLEAR.

- If Haiku says SUPPORTED → mark Green with the supporting quote
- If Haiku says UNCLEAR or NOT SUPPORTED → escalate to full Opus assessment in Step 2c

**Batching:** Run all Haiku agents (full-reads and fast-track confirmations) concurrently in background.

Report: "Opinion research: X claims grep-searched, Y fast-track confirmed by Haiku, Z escalated to Opus, W sent to Haiku full-read."

#### Step 2c: Opus assessment subagents

Group all full-assessment claims (original + escalated from fast-track) by opinion file. For each opinion, launch an Opus subagent (general-purpose agent).

**Subagent input — opinion source (in priority order):**
1. If opinion < 20K chars: read the **full opinion** directly
2. If `opinions/{case}_excerpts.txt` exists (grep hits): read the **excerpts**
3. If `opinions/{case}_summary.txt` exists (Haiku full-read): read the **summary**

Also provide for each claim:
- `row_index`, `page`, `proposition`, `cited_case`, `quoted_text`
- `quote_check_worst` (VERBATIM, CLOSE, FABRICATED, NO_QUOTES, NO_OPINION)
- `matched_passage` from `quote_check` — the actual text from the opinion that the deterministic quote matcher found as the best match. This is what the report will show as "Actual language in opinion." The agent does NOT need to find or transcribe this — it's already extracted. But reading it helps the agent understand the quote comparison.

Example claim input:
```
Row 11 (p.4): United States v. McMurtrey, 704 F.3d 502, 508 (7th Cir. 2013)
  Proposition: Reckless disregard under Franks is established where an officer has obvious reasons to doubt the truth of what he or she is asserting
  Quoted: "obvious reasons to doubt the truth of what he or she is asserting."
  Quote check: FABRICATED (sim=0.58)
  Matched passage: "Franks motion permitted a reasonable inference of falsity because it provided 'obvious reasons to doubt the veracity' of the allegations."
```

The agent sees both the brief's quote and the opinion's actual language, which helps it make an informed assessment.

**Subagent instructions:**

> Read the opinion text (or summary). For each claim, assess **propositional support** — does the case support the proposition it's cited for?
>
> **Quote accuracy is already handled deterministically** by the pipeline's quote checker, which found the best-matching passage from the opinion (provided to you as `matched_passage`). You do NOT need to search for quotes or transcribe opinion text. Use the matched passage to inform your assessment — e.g., if the brief quotes "reasons to doubt the truth" but the opinion says "reasons to doubt the veracity," that's a reworded quote, not a fabrication.
>
> **Propositional support** — classify as:
> - **Supported** — the opinion directly and accurately supports the proposition
> - **Partially supported** — the opinion touches on the topic but the brief overstates, oversimplifies, or extends the holding. Explain the gap.
> - **Not supported** — the opinion does NOT support the proposition. This includes:
>   - The case addresses a completely different topic
>   - The case holds the OPPOSITE of what the brief claims
>   - The brief attributes a specific principle to the case that doesn't appear in it
>   - The case's dicta or background discussion touches the topic but the holding does not
>
> Be strict on the distinction between "partially supported" and "not supported":
> - If the case is topically related and its holding can reasonably be extended to the proposition, that's "partially supported"
> - If the case's holding is about a different legal issue entirely and would require a leap of logic to reach the proposition, that's "not supported" — even if the case happens to use some of the same legal terminology
>
> **Assessment calibration examples:**
> - Brief says "courts exclude prior settlement evidence" and cites a case about anti-abortion protesters → **Not supported** (completely different topic)
> - Brief says "bias evidence must demonstrate actual bias" and cites a case that holds bias evidence is broadly admissible → **Not supported** (inverts the holding)
> - Brief overstates "must be excluded" when the case says "may be excluded at the court's discretion" → **Partially supported** (same topic, overstated standard)
>
> **Combining quote + propositional assessment into a color:**
> - The `quote_check_worst` tells you the quote status. Combine with your propositional assessment:
>   - Supported + (VERBATIM or NO_QUOTES) → Green
>   - Supported + (CLOSE with minor differences like "truth" vs "veracity") → Green (use badge "Supported")
>   - Supported + FABRICATED (quote not in opinion but proposition is supported) → Yellow (use badge "Paraphrase presented as direct quote")
>   - Partially supported (regardless of quote status) → Yellow
>   - Not supported (regardless of quote status) → Red
>
> Do NOT use any external tools — only use Read to access opinion files provided in the workdir.
>
> **Output:** Write a JSON file to `{workdir}/assessments_{group_name}.json`:
> ```json
> [
>   {
>     "row_index": 7,
>     "assessment": "Red",
>     "badge_label": "Not supported by cited case",
>     "opinion_text": "1-2 sentence description of what this case is actually about. This provides context when the deterministic quote matcher found no passage (FABRICATED cases) or when the case is on a completely different topic. Do NOT transcribe passages from the opinion — the pipeline already extracted the matched passage.",
>     "explanation": "1-3 sentence assessment explaining why this is Red/Yellow. Written for a lawyer audience — specific, not vague."
>   }
> ]
> ```
>
> **Badge labels:**
> - "Supported" (Green)
> - "Overstated -- case partially supports" (Yellow)
> - "Reworded -- not a verbatim quote" (Yellow, when quote is CLOSE but substance is fine)
> - "Paraphrase presented as direct quote" (Yellow, when brief uses quotation marks around non-verbatim language but the proposition is supported)
> - "Not supported by cited case" (Red)
> - "Quote not found in opinion" (Red, when the quote is FABRICATED and the proposition is also not supported)
> - "Citation resolves to different case" (Red, for name mismatches)

**Batching:** Max 4-5 opinions per subagent. If more than 5 opinions need assessment, split into multiple subagents and run in parallel.

After all subagents return, read their JSON output files, then update `claims.csv` with `assessment`, `badge_label`, `opinion_text`, and `explanation` columns.

**Special cases (no subagent needed):**
- NOT_FOUND with no opinion text → assessment: "Red", badge_label: "Unable to verify", route to `unable_to_verify` in the report (Gray, not Red)
- VERIFIED but no opinion file → assessment: "Yellow", badge_label: "Case verified but opinion text not available for review"

### Phase 3: Generate Report

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --report
```

This reads `claims.csv` and `brief_metadata.json` and generates `report.html`:
- Dashboard with severity counts and clickable issue list
- Collapsible findings with:
  - "Quoted in brief:" — the brief's exact quoted text (or proposition if no quote)
  - "Actual language in opinion:" — the deterministically-extracted matching passage from the opinion
  - Agent's assessment explaining the issue
- Collapsed verified section with green checkmarks
- Methodology section listing which opinions were retrieved vs. unavailable

Open the report in the user's browser and give a chat summary:
- Stats: X Green, Y Yellow, Z Red, W Unable to verify
- List all Red with proposition + brief rationale
- List all Yellow with brief notes
- Green count only

## Resuming

If `claims.csv` already exists, detect state and resume:

| State | Resume at |
|-------|-----------|
| No `claims.csv` | Phase 1a |
| Has `cited_case` but no `cl_status` | Phase 1b (wave1) |
| Has `cl_status` but no `quote_check_worst` | Phase 1d (quote check + metadata check) |
| Has `quote_check_worst` but no `assessment` | Phase 2 (triage + assess) |
| Has `assessment` | Phase 3 (report) |

**Phase 2 sub-steps** (when resuming at Phase 2):
1. Triage: classify claims as full-assessment or fast-track based on quote_check + metadata + syllabus
2. Grep all claims: search opinion files for key terms, gather excerpts
3. Haiku confirmation for fast-track claims with grep hits; Haiku full-read when greps miss on large opinions; escalate to Opus if Haiku says UNCLEAR
4. Opus assessment: assess all full-assessment claims (original + escalated) using excerpts/summaries/full text

Announce: "Found existing work. Resuming at Phase N."
