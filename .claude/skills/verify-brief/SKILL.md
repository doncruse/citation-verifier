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
- Extract every proposition-case pair into `claims.csv` with columns: `page,proposition,cited_case,quoted_text,brief_sentence`
- CRITICAL: The `cited_case` column MUST start with the exact full citation text from `citations_to_verify.txt` (including case name, reporter, and year). Append pinpoint pages after the start page (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Do NOT abbreviate, omit the reporter, or use short-form case names.
- `proposition`: your summary of the legal claim the brief is attributing to this case (one sentence, your words).
- `quoted_text`: JSON array of any text that appears inside quotation marks in the brief's sentence for this claim. Extract the exact quoted words from the brief. If the claim has no quoted text, use `[]`. Example: `["no desire to deter", "but-for causation"]`
- `brief_sentence`: the brief's actual sentence (or sentences) containing the citation, reproduced as written — including any quoted language, signal word (See, Cf., etc.), and parenthetical attributed to the case. This is what the report will display as "What the brief claims," so the reader can see exactly how the brief used the authority. Normalize whitespace (collapse line breaks), but do not paraphrase. If the sentence is very long, you may trim with `[...]` to keep the cited-case fragment and the immediately surrounding context. Example: `"Courts consistently hold that evidence of prior settlement amounts is irrelevant to liability and damages. See Tompkins v. Cyr, 202 F.3d 770, 787 (5th Cir. 2000) (evidence must be relevant to a 'consequential fact' in the case at bar)."`
- Same case cited for different propositions = separate rows (with potentially different `brief_sentence` values).
- Same proposition supported by multiple cases = separate rows.
- Exclude non-case sources.

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
- `row_index`, `page`, `proposition`, `cited_case`, `quoted_text`, `brief_sentence`
- `quote_check_worst` (VERBATIM, CLOSE, FABRICATED, NO_QUOTES, NO_OPINION)
- `matched_passage` from `quote_check` — the actual text from the opinion that the deterministic quote matcher found as the best match. This is raw material for the agent's analysis.

Example claim input:
```
Row 11 (p.4): United States v. McMurtrey, 704 F.3d 502, 508 (7th Cir. 2013)
  Proposition: Reckless disregard under Franks is established where an officer has obvious reasons to doubt the truth of what he or she is asserting
  Brief sentence: "Reckless disregard is established where an officer has 'obvious reasons to doubt the truth of what he or she is asserting.' United States v. McMurtrey, 704 F.3d 502, 508 (7th Cir. 2013)."
  Quoted strings: ["obvious reasons to doubt the truth of what he or she is asserting."]
  Quote check: FABRICATED (sim=0.58)
  Matched passage: "Franks motion permitted a reasonable inference of falsity because it provided 'obvious reasons to doubt the veracity' of the allegations."
```

**Subagent instructions:**

> You are reviewing a legal brief's citations against the opinions they cite. For each claim below, produce:
>
> 1. An **assessment color** — Green, Yellow, or Red.
> 2. A **badge label** — a short plain-English phrase describing the issue (see list below).
> 3. Three content blocks that will be rendered in the report card, in order:
>    - `brief_block` — what the brief claims (rendered in an orange-bordered box)
>    - `opinion_block` — what the opinion actually says on this topic (rendered in a green-bordered box)
>    - `finding_analysis` — your prose analysis of the gap (rendered as paragraphs beneath the two quote boxes)
>
> The pipeline pre-computes a best-match `matched_passage` from the opinion using a deterministic fuzzy matcher. This is given to you as a hint — above ~0.65 similarity it's usually the passage you want to quote; below that it's often junk. You decide what to show; you are not required to use it.
>
> ### How to write each block
>
> **`brief_block`** — reproduce the brief's own language for this citation. Usually that's the `brief_sentence` you've been given, reproduced verbatim or lightly trimmed. If the cited-case fragment is buried in a very long sentence, trim with `[...]` but keep enough context that the reader understands the claim. Do not paraphrase. Leave empty only if there truly is nothing distinctive to show (rare).
>
> **`opinion_block`** — reproduce the language from the opinion that best illuminates the comparison. This is the key judgment call. **Only populate this block when a direct quote from the opinion adds contrast-value that a prose description cannot.** When in doubt, leave it empty and let `finding_analysis` carry the weight.
> - **Reworded quote (CLOSE)**: quote the opinion's actual parallel language so the reader can see the word substitution at a glance. The `matched_passage` is usually correct here — use it, or trim it to the sentence that parallels the brief's quote.
> - **Inverted holding (Red)**: quote the opinion's actual contrary rule — the sentence(s) that hold the opposite of what the brief claims. This is the devastating quote the reader needs to see.
> - **Pinpoint off**: quote the opinion's discussion of the actual topic (wherever in the opinion it appears), prefaced briefly if you need to orient the reader ("Later in the opinion, Justice Jackson writes: ...").
> - **Paraphrase-as-quote**: quote the opinion's real phrasing so the reader can see the brief's rewording.
> - **Pure topic mismatch — LEAVE EMPTY.** When the cited case is about a completely different area of law, there is no single opinion passage that makes the mismatch sharper than a plain-prose description would. Opening-framing quotes like "This appeal presents a chronicle of abortion protestors..." are noise, not signal — they dilute the punch rather than sharpen it. Let `finding_analysis` do the work (see below).
> - **Citation resolves to different case — LEAVE EMPTY.** When the reporter citation returned a different opinion than the one the brief named (e.g., brief cites "Kraemer v. Franklin & Marshall Coll." but CL returned "Argue v. David Davis Enterprises"), quoting the resolved case's language adds no contrast — it's just evidence that it's a different case, which the analysis prose already makes clear. Let `finding_analysis` state what the citation actually resolves to.
>
> Do NOT invent opinion language. Every quote in `opinion_block` must appear in the opinion file you were given. Quote verbatim, preserve punctuation, and use ellipses for elisions.
>
> **OCR handling.** CourtListener's opinion text sometimes contains OCR artifacts — character-level misreads like "MeMurtrey" for "McMurtrey", "This ease" for "This case", missing ampersands in case names ("King Spalding" for "King & Spalding"), `l`/`1` or `rn`/`m` confusions. These come from the source database, not from the court. When quoting in `opinion_block`, silently correct obvious OCR errors to the intended word so the comparison reads cleanly. Use judgment: if the same case name appears correctly elsewhere in the opinion, or if the "word" is semantically impossible in context, it's OCR — fix it. If in doubt, leave it and the reader will understand. This rule applies ONLY to `opinion_block` quoting from the CL-sourced opinion text; `brief_block` reproduces the brief verbatim (any typos there are the brief's own and matter for verification).
>
> **`finding_analysis`** — your prose assessment of the gap between brief and opinion. Written for a lawyer audience. Form follows the problem:
> - **Pure topic mismatch (Red)**: LEAD with a one-sentence subject-matter description in the form "X v. Y is a [type] case about [factual context]. It does not address [brief's topic / area of law]." This must be the first sentence so the mismatch is instantly visible to a reader scanning the card. Only after that opening should the analysis dive into pinpoint-page specifics or quote-not-found details. Total length 3–5 sentences.
>   - Good opening: *"Tompkins v. Cyr is a civil RICO case about anti-abortion protesters who harassed a doctor. It does not address Rule 401 relevance or prior settlement evidence."*
>   - Bad opening (buries the lead): *"The phrase 'consequential fact' does not appear in the opinion. Page 787 discusses Texas's one-satisfaction rule..."* — the subject-matter mismatch is mentioned only in paragraph 3.
> - **Citation resolves to different case (Red)**: LEAD with the resolution mismatch in the form "The citation [vol reporter page] resolves to [resolved case], not [case named in the brief]. [Resolved case] is a [type] case about [facts] — it does not address [brief's topic]." The first sentence must make both the name mismatch and the unrelated subject matter visible.
> - **Inverted holding (Red)**: lead with the inversion ("X holds the opposite of what the brief claims"), then name the actual holding.
> - **Reworded quote where substance survives**: one or two sentences identifying the word substitution and noting whether it changes the meaning.
> - **Pinpoint off but proposition supported elsewhere**: note where the relevant discussion actually appears and confirm the substance is in the case.
> - **Partial support**: explain the specific gap — what the case decided versus what the brief claims.
>
> Plain prose, complete sentences, no headers or bullets. Paragraphs separated by blank lines. Length follows what the finding needs; do not pad.
>
> ### Propositional support classification
>
> - **Supported** — the opinion directly and accurately supports the proposition.
> - **Partially supported** — the opinion touches on the topic but the brief overstates, oversimplifies, or extends the holding.
> - **Not supported** — the opinion does not support the proposition. This includes: (a) the case addresses a completely different topic; (b) the case holds the opposite of what the brief claims; (c) the brief attributes a specific principle to the case that does not appear in it.
>
> Be strict about "partially" vs. "not":
> - Topically related and the holding can reasonably be extended → **Partially**.
> - Different legal issue entirely → **Not supported**, even if the opinion uses some of the same vocabulary.
>
> ### Assessment color
>
> | Propositional support | Quote status | Color |
> |---|---|---|
> | Supported | VERBATIM / CLOSE / NO_QUOTES | Green |
> | Supported | FABRICATED (quote not in opinion but proposition is sound) | Yellow |
> | Partially supported | any | Yellow |
> | Not supported | any | Red |
>
> ### Badge labels
>
> Pick the phrase that best describes the issue. Reuse these when they fit; invent a new one only if none fit.
>
> - "Supported" (Green)
> - "Overstated -- case partially supports" (Yellow — pinpoint off, overstates holding, partial topic overlap)
> - "Reworded -- not a verbatim quote" (Yellow — CLOSE quote, substance accurate)
> - "Paraphrase presented as direct quote" (Yellow — FABRICATED quote but proposition is supported)
> - **"Case on unrelated subject"** (Red — the cited case is in a different area of law entirely; the proposition does not appear anywhere in the opinion and the case does not even touch the topic. Use this for pure topic-mismatch findings — a common hallucination pattern where a real case is cited for a fabricated proposition it has no relation to.)
> - "Not supported by cited case" (Red — the case is topically adjacent but does not actually support the specific proposition; use when the case is *about* the area of law in question but doesn't go as far as the brief claims, and the fit is worse than "Overstated")
> - "Quote not found in opinion" (Red — FABRICATED quote and proposition also not supported; usually paired with or subsumed by "Case on unrelated subject" when the whole citation is off-topic)
> - "Inverts the holding" (Red — case holds the opposite of what the brief claims)
> - "Citation resolves to different case" (Red — CourtListener returned a different opinion than the brief named)
>
> ### Output
>
> Write a JSON file to `{workdir}/assessments_{group_name}.json`:
> ```json
> [
>   {
>     "row_index": 7,
>     "assessment": "Red",
>     "badge_label": "Case on unrelated subject",
>     "brief_block": "Courts consistently and uniformly hold that evidence of prior settlement or verdict amounts is irrelevant to the issues of liability and damages in a subsequent, unrelated accident. See Tompkins v. Cyr, 202 F.3d 770, 787 (5th Cir. 2000) (evidence must be relevant to a 'consequential fact' in the case at bar).",
>     "opinion_block": "",
>     "finding_analysis": "Tompkins v. Cyr is a civil RICO case about anti-abortion protesters who engaged in targeted picketing and harassment of a doctor, resulting in an $8 million jury verdict. It does not address Rule 401 relevance, prior settlement evidence, or the concept of a 'consequential fact' — the quoted phrase does not appear anywhere in the opinion. The relevance discussions in Tompkins concern whether evidence of anonymous threats and an unrelated Florida murder bore on the plaintiffs' emotional-distress damages. Page 787 of the opinion addresses Texas's one-satisfaction rule for double-recovery of damages — a completely different issue. The brief's citation appears to be a fabricated attribution."
>   },
>   {
>     "row_index": 11,
>     "assessment": "Yellow",
>     "badge_label": "Reworded -- not a verbatim quote",
>     "brief_block": "Reckless disregard under Franks is established where an officer has 'obvious reasons to doubt the truth of what he or she is asserting.' United States v. McMurtrey, 704 F.3d 502, 508 (7th Cir. 2013).",
>     "opinion_block": "... the Franks motion permitted a reasonable inference of falsity because it provided 'obvious reasons to doubt the veracity' of the allegations. See United States v. Whitley, 249 F.3d 614, 621 (7th Cir. 2001) ...",
>     "finding_analysis": "The brief substitutes 'the truth of what he or she is asserting' for the opinion's actual phrase, 'the veracity.' The substance of the Franks standard is preserved, but the substitution means the quotation marks in the brief are not quite accurate."
>   }
> ]
> ```
>
> Do NOT use any external tools — only use Read to access the opinion files in the workdir.

**Batching:** Max 4-5 opinions per subagent. If more than 5 opinions need assessment, split into multiple subagents and run in parallel.

After all subagents return, read their JSON output files and merge them into `claims.csv` — specifically the columns `assessment`, `badge_label`, `brief_block`, `opinion_block`, and `finding_analysis`.

**Special cases (no subagent needed):**
- NOT_FOUND with no opinion text → assessment: "Red", badge_label: "Unable to verify", route to `unable_to_verify` in the report (Gray, not Red)
- VERIFIED but no opinion file → assessment: "Yellow", badge_label: "Case verified but opinion text not available for review"

### Phase 3: Generate Report

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --report
```

This reads `claims.csv` and `brief_metadata.json` and generates `report.html`:
- Dashboard with severity counts and a clickable issue list (teaser is first sentence of `finding_analysis`)
- Collapsible findings, each with three agent-authored blocks:
  - "What the brief claims:" — `brief_block` (orange-bordered box). Falls back to `brief_sentence` with quoted strings bolded if the agent left it empty.
  - "Actual language in opinion:" — `opinion_block` (green-bordered box). Omitted when the agent intentionally leaves it empty (e.g., no useful single quote exists). Falls back to the deterministic `matched_passage` for legacy data that pre-dates agent-authored blocks.
  - `finding_analysis` — agent's prose analysis, rendered as paragraphs beneath the two quote boxes.
- Unable-to-verify cards grouped by cited case (one card per unavailable case, with all attributed propositions listed inside)
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
