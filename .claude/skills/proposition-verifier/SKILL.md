---
name: proposition-verifier
description: >
  Validate whether cases cited in a legal brief or opinion actually support the propositions
  they are cited for, and whether quoted language actually appears in the cited opinion.
  Use this skill whenever the user asks you to verify what a brief claims a case says, check
  whether quotes in a brief are accurate, validate cited propositions, confirm that cases
  stand for what a brief says they stand for, or "substance-check" a legal document's
  citations. Also trigger when the user says things like "does this case actually say that?"
  or "are these quotes real?" or "check whether the authorities support the arguments."
  This skill relies on the courtlistener-mcp connector -- do NOT use Midpage. This skill
  can run standalone or after citation-checker has already verified citation existence.
---

# Proposition Validator

Verify two things about each citation in a legal document:

1. **Quote accuracy** -- Does quoted language from a cited case actually appear in the opinion? (Near-match, noting even minor differences.)
2. **Propositional support** -- Does the cited case actually support the proposition it's cited for?

## Accepted inputs

The user provides a file path to a PDF, Word doc, or text file. This skill can run standalone (extracting citations itself) or after citation-checker has already identified and verified the citations.

## Step 1 -- Identify citation-proposition pairs

Parse the document and extract every instance where a case is cited alongside either:
- A **direct quote** attributed to the case (text in quotation marks followed or preceded by a citation)
- A **proposition** the case is cited to support (a statement of law or fact followed by "See [Case]" or "[Case] (holding that...)" or similar signal)

For each pair, record:
- The citation (volume/reporter/page)
- The case name as used in the brief
- The proposition or quote attributed to the case
- The pinpoint page if given
- The citation signal used (e.g., "See," "Cf.," no signal, parenthetical)

Focus on substantive legal propositions. Skip purely procedural citations (e.g., "Case No. X, Dkt. 45") and string cites where no specific proposition is attributed to individual cases.

## Step 2 -- Retrieve opinion text

For each unique cited case, retrieve the opinion text from CourtListener:

1. Use `courtlistener-mcp:citation_batch_lookup_citations` to get the cluster ID.
2. Use `courtlistener-mcp:get_cluster` to get the list of sub-opinions.
3. Use `courtlistener-mcp:get_opinion` with the opinion ID to retrieve the full text.

The opinion text is in the `plain_text` field. **Many opinions have empty `plain_text` but have full text in HTML fields.** When `plain_text` is empty, use this fallback order:

1. `html_with_citations` (most common fallback -- strip all HTML tags with regex to get usable text)
2. `html` (same approach)
3. `html_lawbox` (same approach)
4. `xml_harvard` (strip XML tags)

To strip HTML/XML: remove all tags, collapse whitespace, decode HTML entities. The resulting text is usable for both quote matching and propositional assessment.

If ALL text fields are empty, mark the case as **UNABLE TO ACCESS OPINION TEXT** and skip both checks.

Cache opinion texts -- don't re-retrieve the same opinion for multiple citation-proposition pairs.

### Case name verification

When the batch lookup returns a cluster, compare the case name returned by CourtListener against the case name used in the brief. If they don't match -- e.g., the brief says *State v. Carter* but the citation resolves to *Stull v. Combustion Engineering* -- this is a **CASE NAME MISMATCH**. This is a distinct error category: the reporter citation is valid and resolves to a real case, but it's a *different* case than the one the brief names. Flag it immediately -- don't proceed to quote or propositional checks for that citation, since the opinion text belongs to a different case than the brief intends to cite.

### Retrieval discipline -- retrieve, don't guess

Retrieve the full opinion text for every cited case. Do not skip retrieval and rely on training knowledge, even for well-known cases. The point of this skill is to check the brief's claims against the *actual text* of each opinion. Training knowledge may be stale, incomplete, or wrong about specific pinpoint pages. If retrieval fails (CourtListener doesn't have the text), mark the case as UNABLE TO VERIFY and note in the report that it was not verified against opinion text.

### Retrieval priority when context is limited

Some opinions are very large (Supreme Court and California Supreme Court opinions can exceed 50,000 tokens). If retrieving every opinion in full would exceed context window limits, prioritize retrieval in this order:

1. **Citations with direct quotes attributed to them** -- these are the highest priority because quote verification is deterministic: the quoted text either appears in the opinion or it doesn't. A brief that puts language in quotation marks and attributes it to a case is making a concrete, falsifiable claim. Retrieve these first, always.
2. **Citations that carry the most argumentative weight** -- if a case is the linchpin of a dispositive argument (e.g., the primary case for "Ohio does not recognize civil extortion"), retrieve it before a case cited in a string cite or for background procedural standards.
3. **Citations to lesser-known or recent cases** -- training knowledge is less reliable here than for canonical cases like *Iqbal* or *Twombly*.
4. **Canonical cases cited for well-established propositions** -- e.g., *Iqbal* for plausibility pleading. These can be deprioritized for retrieval if context is genuinely exhausted, because the propositions attributed to them are widely known and stable. But they should still be retrieved if possible.

When retrieving large opinions, use targeted searches (grep for key terms, pinpoint pages, or relevant passages) rather than reading the entire opinion into context. The goal is to find the specific passage the brief relies on, not to read every word.

### Transparency in the report

In the report's Methodology section, disclose which opinions were retrieved and reviewed versus which could not be accessed. If, despite these instructions, some opinions were assessed from training knowledge rather than retrieved text (e.g., due to context window limits or API failures), the report must clearly flag those citations as "Assessed from training knowledge -- not verified against retrieved opinion text" so the user can calibrate trust accordingly. Do not mark these citations as "Verified" -- use a distinct label like "No issues identified (not verified against opinion text)" to make the lower confidence level visible.

## Step 3 -- Quote verification (deterministic)

For each direct quote attributed to a case:

1. Normalize both the quoted text and the opinion text: collapse whitespace, normalize dashes/hyphens, normalize quotation mark styles.
2. Search for the quoted text in the opinion using near-match: ignore minor punctuation differences, spacing, and line-break artifacts from PDF extraction.
3. Classify the result:

- **EXACT MATCH** -- The quoted text appears verbatim in the opinion (after normalization).
- **COSMETIC NEAR MATCH** -- The substance and wording are the same but with minor punctuation, spacing, or formatting differences (e.g., em-dash vs. hyphen, different ellipsis style, bracket alterations for grammatical fit). Note the differences but flag as low-concern.
- **SUBSTANTIVE NEAR MATCH** -- The quote is recognizably derived from a specific passage in the opinion, but with word substitutions, singular/plural changes, tense changes, or reordering that preserves the meaning. Show both versions side by side. This is common and not necessarily wrong, but the brief is presenting a paraphrase as a direct quote.
- **PARAPHRASE IN QUOTES** -- The brief uses quotation marks around language that is a loose summary or composite of the opinion's holding, not a passage that appears anywhere in the text. The opinion says something similar in substance, but the "quoted" words were composed by the brief's author, not the court. Flag this clearly -- it's a citation hygiene issue. Identify the closest actual language from the opinion.
- **NOT FOUND** -- The quoted text does not appear in the opinion, and no similar passage can be identified. This is the most serious finding and could indicate fabrication or misattribution.
- **MISATTRIBUTED** -- The quoted text does not appear in the cited opinion, but it does appear (or closely matches) a different opinion that is also cited in the brief. Identify the correct source. This is a distinct error from fabrication.
- **UNABLE TO VERIFY** -- Opinion text was not available from CourtListener.

When reporting near matches, show the brief's version and the opinion's actual text side by side so the user can see exactly what differs.

### Misattribution cross-check

When a quote is NOT FOUND in the cited opinion, search the other retrieved opinions from the brief to see if it appears elsewhere. Legal briefs sometimes attribute a quote to the wrong case in a string cite, or mix up which case in a line of authority said what. If the quote is found in a different case, classify as MISATTRIBUTED rather than NOT FOUND and identify the correct source.

### Parenthetical characterizations

Briefs frequently use citation parentheticals like `(holding that X)` or `("quoted phrase")`. Treat these as follows:
- Parentheticals with quotation marks inside: treat as quote claims and verify the quoted text.
- Parentheticals that paraphrase a holding (e.g., "holding that courts must segregate fees"): treat as propositions and assess support.
- Short signal parentheticals like "(same)" or "(en banc)": skip -- these aren't propositional claims.

Important: OCR and PDF extraction artifacts in CourtListener's text (e.g., "eos[t]" for "cost", broken hyphenation) are common. Don't flag these as quote discrepancies -- they're database artifacts, not brief errors. Use judgment to distinguish brief-side alterations from source-side OCR noise.

## Step 4 -- Propositional support assessment (AI-assisted)

For each proposition attributed to a case:

1. Read the relevant portion of the opinion (use the pinpoint page as a guide, but also check the broader context).
2. Assess whether the opinion supports the proposition. Classify as:

- **SUPPORTED** -- The opinion clearly states or holds what the brief claims. The proposition is a fair reading of the case.
- **PARTIALLY SUPPORTED** -- The opinion touches on the topic but the brief overstates, oversimplifies, or extends the holding beyond what the court actually said. Explain the gap.
- **NOT SUPPORTED** -- The opinion does not support the proposition. The case may address a different issue, hold the opposite, or say nothing relevant. Explain what the case actually says.
- **CASE NAME MISMATCH** -- The reporter citation resolves to a different case than the name used in the brief. The proposition cannot be verified because the citation points to the wrong opinion. Note both the name the brief uses and the name CourtListener returns.
- **DICTA** -- The proposition appears in the opinion but as dicta rather than holding. Note this distinction -- it matters for precedential weight but isn't necessarily wrong.
- **UNABLE TO ASSESS** -- Opinion text was not available.

Be specific in the assessment. Don't just say "supported" -- briefly explain what the opinion actually says and how it relates to the brief's proposition. This helps the user understand the strength of each citation.

Important: Be honest and precise. Many propositions will be supported -- that's normal. Don't strain to find problems. But when a brief stretches a case beyond its holding or mischaracterizes what a court said, flag it clearly.

## Step 5 -- Report

Generate an interactive HTML report. Save it alongside the input brief -- if the brief is at `path/to/brief.pdf`, save the report as `path/to/brief_proposition_report.html`. If a working directory was specified, save there instead.

### Report structure

The report has three sections:

#### Section 1: Problem Summary (always visible)

A compact dashboard at the top showing:
- Total citation-proposition pairs checked
- Counts by severity: how many issues, how many verified
- A list of just the problems, each showing: page number, citation, the issue in plain English, and a severity badge
- Each issue in the list should be an anchor link that jumps to the corresponding finding in the walkthrough

This is the "do I need to worry" view. A lawyer glances here first.

#### Section 2: Document-Order Walkthrough (problems only)

Walk through the brief in page order. For each citation-proposition pair that has an issue (anything other than EXACT MATCH, COSMETIC NEAR MATCH, or SUPPORTED), show:

- **Page number** and the brief's text (the sentence or passage containing the citation)
- **Citation**: case name and reporter citation
- **What the brief claims**: the quote or proposition
- **What the opinion actually says**: the relevant passage from the opinion (expandable to show more context)
- **Verdict badge** in plain English (see badge mapping below)
- **Explanation**: a brief, specific explanation of the gap

Each item should be expandable -- collapsed to a one-line summary by default, expandable to show full detail.

#### Section 3: Verified Citations (collapsed)

A collapsible section at the bottom listing all citation-proposition pairs that passed (EXACT MATCH, COSMETIC NEAR MATCH, SUPPORTED). Each shows the page, citation, proposition, and a green checkmark. Collapsed by default -- the user can expand to see the full audit trail.

### Badge mapping for the report

Use color-coded badges with plain-English labels. The internal classification categories map to user-facing labels as follows:

**Quote badges:**
- EXACT MATCH -> "Verified" (green)
- COSMETIC NEAR MATCH -> "Verified -- minor formatting differences" (green)
- SUBSTANTIVE NEAR MATCH -> "Reworded -- not a verbatim quote" (yellow)
- PARAPHRASE IN QUOTES -> "Paraphrase presented as direct quote" (orange)
- MISATTRIBUTED -> "Quote attributed to wrong case" (red)
- NOT FOUND -> "Quote not found in opinion" (red)

**Proposition badges:**
- SUPPORTED -> "Supported" (green)
- PARTIALLY SUPPORTED -> "Overstated -- case partially supports" (yellow)
- NOT SUPPORTED -> "Not supported by cited case" (red)
- CASE NAME MISMATCH -> "Citation resolves to different case" (red)
- DICTA -> "Dicta, not holding" (blue/info)

**Other badges:**
- UNABLE TO VERIFY / UNABLE TO ASSESS -> "Unable to verify -- opinion text unavailable" (gray)

### Generating the report

Build the HTML report using inline CSS and JavaScript (no external dependencies). Use Google Fonts (Lora for headings/case names, Source Sans 3 for body text). Include all CSS inline in a `<style>` block.

**Key visual patterns:**

- **Expand/Collapse All controls**: Include a small control bar above the walkthrough section with "Expand All" and "Collapse All" buttons. Use simple inline JavaScript:
  ```javascript
  function expandAll() { document.querySelectorAll('details').forEach(d => d.open = true); }
  function collapseAll() { document.querySelectorAll('details').forEach(d => d.open = false); }
  ```
  Style the buttons to be unobtrusive -- small, text-style links or subtle buttons, not primary-action buttons.

- **All-clear signal**: When no serious issues are found (no red badges), display a green banner in the dashboard: "No serious issues found." followed by a count of minor notes if any. When there ARE serious issues, omit the banner and let the issue list speak for itself.

- **Side-by-side blockquotes**: Use two distinct blockquote styles throughout the report. "What the brief says" gets an orange/warm left border and warm background. "What the opinion actually says" gets a green left border and green-tinted background. This visual contrast is the most important design element -- it lets the user instantly compare the two texts.

- **Expandable findings**: Use `<details>` and `<summary>` for each walkthrough item. The summary line shows: page number, case name (italic), a preview of the claim, and the badge. The expanded detail shows the full brief text, opinion text, differences, and explanation.

- **Dashboard issue list**: Each issue in the summary list should link (via anchor) to its corresponding finding in the walkthrough, so the user can click an issue and jump directly to the detail.

- **Severity coloring**: Use a consistent color system -- green for verified, yellow for overstated/reworded, orange for paraphrases in quotes, red for not found/not supported, blue for dicta, gray for unable to verify. Apply these to badges, blockquote borders, and issue list left-borders.

**Print-friendly CSS**: Include an `@media print` block that expands all `<details>` elements, removes shadows, and adjusts font sizes.

### Tone and language

The report should read like a professional memo, not a diagnostic log. Write in complete sentences. Use the internal category names only in the underlying data -- the user-facing report uses the plain-English badges and explanations. Avoid jargon like "propositional support assessment" -- say "whether the case supports this claim" instead.

## Important caveats to include in the report

Include a "Methodology & Limitations" section at the bottom of the report:
- **Quote verification** is near-deterministic but limited by the quality of CourtListener's text. Minor discrepancies may reflect OCR artifacts in the source database rather than errors in the brief.
- **Propositional support** assessment is an AI judgment. It reflects Claude's reading of the opinion text and should be verified by counsel. Reasonable lawyers may disagree about whether a case "supports" a given proposition.
- This report checks whether cited cases say what the brief claims they say. It does not assess the overall legal merit of the brief's arguments or whether the cited cases are the best authorities available.
- Some opinions may not have full text available in CourtListener. Cases marked "unable to verify" should be checked through other sources (Westlaw, Lexis, etc.).
- **Verification method disclosure**: List which opinions were retrieved from CourtListener and reviewed against their full text, and which (if any) were assessed from training knowledge without retrieval. This lets the user know exactly which citations received the strongest level of verification.
