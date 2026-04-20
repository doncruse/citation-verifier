# /verify-brief retrospective: make-whole bankruptcy NY research memo

**Date:** 2026-04-20
**Workdir:** `briefs/make-whole-bankruptcy-ny/`
**Input:** `briefs/Are make-whole premiums enforceable if the debt is paid in bankruptcy Indenture governed under New Y.docx` — an AI-generated legal research memo on post-acceleration make-whole enforceability under NY law and SDNY precedent. 5 unique case citations, 20 proposition-citation pairs.
**Result (initial):** 16 Green / 0 Yellow / 0 Red / 4 Unable-to-verify.
**Result (after user-supplied PACER URL):** 20 Green. No hallucinations, no misrepresentations.

## What went well

- First `/verify-brief` run against a `.docx` input (vs. PDF/MD). `python-docx` extraction was clean. 31 paragraphs, ~11K chars.
- Extraction, wave1/wave2 verification, proposition extraction, quote check, and assessment all worked without intervention. 20 claims extracted in one Opus pass with no merge mismatches (the prior Protege run had 6/8 fail on pinpoint formatting — no regression on this run, agent followed the "no pinpoints" rule correctly).
- The MPM Silicones / Momentive Performance Materials name-mismatch flag was handled correctly. The subagent was briefed that these are the same case (MPM is the debtor; Momentive is the parent; CA2 docketed under Momentive) and the final assessment reflects that without a false-positive Red.
- Two concurrent Opus subagents on AMR+MPM and Chemtura+1141Realty saved wall time. When the Chemtura+1141Realty subagent timed out (stream idle — ~394s), splitting it into two smaller concurrent subagents (one per opinion) succeeded cleanly.
- Substantive result: the AI-generated memo was actually accurate. Every quoted string verified (12 VERBATIM, 4 CLOSE — all CLOSE differences were minor editorial insertions like `[MPM's]` or smart-quote normalization, not real word substitutions). Every propositional characterization tracked the underlying holdings.

## The headline operational issue: late detection of missing opinion

**What happened.** Wave 1 returned `NOT_FOUND` for `In re Ultra Petroleum Corp., 624 B.R. 178 (2020)`. Wave 2 found a RECAP docket match but reported `downloaded: 0, failed: 1`. The `--metadata-check` flagged 4 claims as `no_opinion`. I proceeded to Phase 2, marked the 4 rows as "Unable to verify," generated the report, and delivered the end-of-run summary. Only then did the user ask about the case, supply docket URL `https://www.courtlistener.com/docket/4392783/1874/ultra-petroleum-corp/`, and we downloaded a free 43-page RECAP PDF that verified all 4 propositions Green.

The missing opinion IS in CourtListener's system — as a free RECAP PDF, at docket entry 1874, downloadable by any user. The pipeline just didn't find it automatically because the citation-lookup API doesn't index 624 B.R. 178 (the remand opinion is not in CL's opinion corpus — only the CA5 affirmance at 51 F.4th 138 is), and wave2's RECAP docket resolution didn't climb down into docket entries to find the free-on-pacer opinion.

**Why this matters.** 4 of 20 claims (20%) ended up in the "Unable to verify" bucket based on an incomplete automated search. The free PDF was one manual fetch away. Had the user not followed up, the report would have incorrectly implied the 4 Ultra Petroleum citations were unverifiable when they were in fact fully supported.

**User feedback:** "it might be nice to get feedback earlier in the process that we have a missing opinion."

### Suggested fixes

1. **Surface misses as a user-facing checkpoint between Phase 1b and Phase 1c.** After wave1+wave2, if any citation is `NOT_FOUND` or is a `POSSIBLE_MATCH` with no opinion downloaded, the skill should pause and report something like:

   ```
   Missing opinions for 1 citation:
     - In re Ultra Petroleum Corp., 624 B.R. 178 (2020)
       - Wave1: NOT_FOUND (citation-lookup has no record of 624 B.R. 178)
       - Wave2: RECAP docket 4392783 matched (Ultra Petroleum Corp., txsb)
         but no downloadable opinion/order text.
   Before continuing, do you want to:
     (a) proceed and mark these citations as "Unable to verify"
     (b) supply a URL or file path for the opinion manually
     (c) give me 5 more minutes to search RECAP docket entries / CA5 affirmances / secondary sources
   ```

   Currently the skill only mentions a resume-state table in its docs — there's no affirmative "missing opinion" checkpoint in the phase flow. Phase 1d's metadata-check reports `no_opinion` counts at the end, but by then I've already decided to proceed.

2. **Have wave2 drill into free-on-pacer docket entries.** When wave2 finds a RECAP docket but `downloaded: 0`, the pipeline could list the docket's free-on-pacer documents and offer to download the best opinion candidate. For Ultra Petroleum, the 43-page "AMENDED MEMORANDUM OPINION" at entry 1874 was free and obvious — the same ranking logic that `_opinion_likelihood` uses for picking documents within a docket should apply. Not sure whether wave2 currently tries this; worth checking `brief_pipeline.wave2_fallback_and_download`.

3. **When the citation-lookup returns NOT_FOUND, try the reporter-citation-to-docket path more aggressively.** CourtListener has `624 B.R. 178` as a reporter citation on the docket clusters list even when there's no standalone opinion. A targeted docket-entries search filtered by `entry_date_filed` around the citation's year might catch these.

4. **Teach the skill prompt to escalate NOT_FOUND findings to the user proactively, not just as a silent "Unable to verify" at the end.** One sentence added to Phase 1b/1c instructions: *"If wave2 leaves any citation without a downloadable opinion, stop and ask the user before continuing to Phase 2 — they may be able to supply a URL, and a 20% 'Unable to verify' rate is often a fixable data problem rather than a genuinely missing opinion."*

## Rough edges

### 1. Default venv path was wrong for this machine

The startup hook installed by Claude Code says `WINDOWS ENV: Use venv/Scripts/python.exe (not python)`, but the host is macOS and the venv is at `venv/bin/python`. This wasted a tool call early in the run. The hook content doesn't match the host. Not a verify-brief issue; flagging for CLAUDE.md or settings.json cleanup if the user switches between machines.

### 2. Opus subagent stream idle timeout at ~395s

The first Chemtura+1141Realty subagent (2 opinions, 11 claims, combined ~308K chars) hit a stream idle timeout before writing the output file. Splitting into two concurrent subagents (one per opinion, 4 and 7 claims) succeeded in ~280s each. Lesson: when passing two large opinion files to one subagent, budget for 400s+ or split. The skill's "Max 4-5 opinions per subagent" guidance could use a size qualifier — something like *"Max 4-5 opinions OR ~200K combined chars, whichever is smaller."*

### 3. Proposition extraction produced 20 rows cleanly on the first pass

Worth recording because the prior Protege run required manual pinpoint-stripping to get `--merge` to work. This time the extraction agent correctly omitted pinpoints from `cited_case` — either the prompt is clearer now, or Opus 4.7 handled the instruction better. Regardless: no regression, and the `--merge` path reported `20 matched, 0 unmatched` on first try.

## Data lessons

- **624 B.R. 178 is not in CourtListener's opinion database** but is accessible via RECAP (docket 4392783, entry 1874, free-on-pacer). Other Ultra Petroleum opinions that ARE in CL as citable clusters: 575 B.R. 361 (2017 original), 913 F.3d 533 (CA5 2019), 943 F.3d 758 (CA5 remand 2019), 51 F.4th 138 (CA5 affirmance 2022). The 624 B.R. 178 opinion is an "orphan" in CL's indexing.
- **Momentive / MPM Silicones alias**: The Second Circuit's MPM Silicones bankruptcy appeal is docketed under *Momentive Performance Materials Inc. v. BOKF, NA* at CourtListener. Name matcher flags this as a mismatch. It's a legitimate alias — Momentive is the parent, MPM the debtor. Worth noting for future runs; if it recurs in multiple briefs, consider adding to `name_matcher.py` as a known alias.

## Skill changes proposed

1. Add a **missing-opinion checkpoint** between Phase 1b/1c and Phase 2 that surfaces NOT_FOUND + POSSIBLE_MATCH-without-text citations to the user before proceeding.
2. In `brief_pipeline.wave2_fallback_and_download`, when a RECAP docket is matched but no document downloads, explicitly list the docket's free-on-pacer documents with the `_opinion_likelihood` ranking and either auto-select the top ranked or report them to the user.
3. Update the subagent batching guidance in SKILL.md to cap on combined opinion size, not just opinion count.
4. Consider adding "Momentive / MPM Silicones" to a known-aliases list in `name_matcher.py`, or just accept it will surface as a name_mismatch flag that the assessment subagent can resolve (current behavior worked).
