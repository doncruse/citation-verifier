# Retrospective: Brooks full-pipeline rerun + topic/name-mismatch prompt refinements

**Date:** 2026-04-17 (session 2)
**Briefs tested:**
- Brooks v. Lowe's Home Centers, LLC — full rerun from Phase 1c
- Maxwell v. Michael — targeted Phase 2c reruns on topic/name-mismatch findings
**Prior commit:** b85bc7c (retrospective for agent-authored-blocks Maxwell rerun + dashboard teaser fix)

---

## Background

The previous retrospective flagged that the brief_sentence (Phase 1c) and
agent-authored brief_block (Phase 2c rendering) paths had not been tested
end-to-end. This session ran the Brooks brief from Phase 1c onward to
exercise those paths, then iterated on the Phase 2c prompt twice in
response to user feedback on report quality.

The session was interactive: user reviewed each regenerated report,
flagged specific weaknesses, and the prompt was refined between runs.

## What shipped

### 1. Brooks full-pipeline rerun (Phase 1c onward)

Archived the existing `report.html` → `report-old.html` and `claims.csv`
→ `claims-old.csv`. Preserved the expensive artifacts from the prior run:
`citations_to_verify.txt`, `verification_results.csv`, `opinions/`. Then:

- **Phase 1c** — One Opus agent read the brief PDF and extracted
  19 proposition-case pairs into a fresh `claims.csv` with the new
  `brief_sentence` column populated.
- **Phase 1d** — Merged, ran `--check-quotes` and `--metadata-check`.
  All 19 claims merged cleanly. Quote check: 6 VERBATIM, 4 CLOSE,
  2 FABRICATED, 9 no-quotes, 1 no-opinion (Menges).
- **Phase 2c** — Four parallel Opus subagents (grouped by opinion file,
  ~4 opinions each) assessed all 18 non-Menges claims.
- **Phase 3** — Regenerated report.

Result: 3 Red, 7 Yellow, 8 Green, 1 Gray. Red findings matched the
original proposition-verifier Brooks output exactly (Tompkins, Collins,
Abel). Yellows expanded from 3 → 7 because (a) Gilliam was re-found on
CL and caught as paraphrase-as-quote, and (b) agents were stricter than
the proposition-verifier skill on "wide discretion" (McRae) and
"must have acted in 'bad faith.'" (King-2), flagging these as reworded
where the original run considered them Green.

### 2. Topic-mismatch prompt refinement (iteration 1)

User reviewed the Brooks report and flagged: "the instances where the
case is about something else entirely are not coming out that clear."
Diagnosis: agents *did* include subject-matter framing but buried it in
paragraph 2 or 3, behind pinpoint-specific analysis.

Two prompt changes landed:

- **`opinion_block` MUST be empty for pure topic-mismatch findings.**
  Opening-framing quotes like "This appeal presents a chronicle of
  abortion protestors..." are noise, not signal — they dilute the punch.
  `finding_analysis` carries the weight in plain prose.
- **`finding_analysis` MUST lead with a one-sentence subject-matter
  description** in the form "X v. Y is a [type] case about [facts]. It
  does not address [brief's topic]." This MUST be the first sentence.
- **New Red badge: "Case on unrelated subject"** — distinct from the
  generic "Not supported by cited case." Signals the type of
  hallucination (real case, fabricated proposition attribution) in the
  dashboard teaser itself.

Reran Phase 2c on all 9 topic-mismatch findings across both briefs
(Brooks: Tompkins, Collins; Maxwell: Swierkiewicz, David×2, Sojka,
Iqbal, Whitlock, Anderson). All 9 now open with the mandated lead
sentence and have empty opinion_block. Dramatically clearer.

### 3. Name-mismatch prompt refinement (iteration 2)

User observed: "Another one where we don't need a quote from actual
language in the opinion." Same principle — the resolved case's language
doesn't add signal over the analysis prose.

Applied the same treatment to "Citation resolves to different case":

- **`opinion_block` MUST be empty.**
- **`finding_analysis` MUST lead with** "The citation [vol reporter
  page] resolves to [resolved case], not [case named in brief].
  [Resolved case] is a [type] case about [facts] — it does not address
  [brief's topic]."

Reran Phase 2c on all 3 name-mismatch findings in Maxwell (Kraemer
rows 7 + 28, Wolfe-resolved-to-Abbott row 26). Leads are now sharp:

> "The citation 371 F. Supp. 2d 765 resolves to Argue v. David Davis
> Enterprises, Inc. (E.D. Pa. 2009), not Kraemer v. Franklin & Marshall
> College. Argue is an ADEA/PHRA attorneys' fees petition ... — it does
> not address Rule 11 sanctions, documentary evidence, or the
> consequences of denying facts in pleadings."

## What went well

1. **Purpose-based prompt refinement reliably moved the needle.** Each
   iteration was ~5 lines of prompt text and produced visible report
   improvements on the first rerun. No need for schema changes or code
   changes.
2. **Rerunning only the affected findings was fast and cheap.** Topic-
   mismatch rerun: 3 parallel agents, ~1 min wall clock. Name-mismatch
   rerun: 1 agent, ~30 seconds. Total marginal API cost to iterate was
   tiny relative to the quality improvement.
3. **Brooks brief_sentence extraction worked on first try.** 19/19
   claims merged, no `cited_case` format mismatches. The Phase 1c
   prompt tightening from earlier sessions held up.
4. **The new "Case on unrelated subject" badge communicates in the
   dashboard.** A reader scanning the issue list sees this badge and
   immediately understands this is a different type of hallucination
   than "Not supported" (which is more subtle).

## What went less well

### 1. McRae-style over-strictness on verbatim quotes in generic contexts

Agents marked `"wide discretion"` (verbatim at the cited page) as
"Reworded — not a verbatim quote" because the opinion uses the phrase
generically rather than as a Rule-403-specific holding. Similar call
on King row 11 for `"must have acted in 'bad faith.'"` where the opinion
says "King must show that ICR acted in 'bad faith.'" — the quoted
fragment is verbatim but framed differently.

These are defensible Yellows but arguably over-strict; the original
proposition-verifier skill called them Green. Worth noting as a
calibration question for future prompt iteration: do we want the
assessment to catch *structural* quote inaccuracy (what we have) or
only *substantive* quote inaccuracy (which would Green these)?

### 2. JSON output format drift (one agent wrapped vs. array)

`assessments_topic_M2.json` came back as `{"assessments": [...]}`
instead of a top-level array (the expected format). The patch script
caught and handled both shapes gracefully, but the prompt could be
clearer. All four Brooks subagents and the name-mismatch subagent
produced top-level arrays as instructed.

**Potential fix:** in the worked-example JSON in SKILL.md, explicitly
note "top-level array, NOT wrapped in `{"assessments": [...]}`."

### 3. OCR correction still partial

From the Maxwell rerun last session, "This ease" survived in
Swierkiewicz's opinion_block even though the prompt says to correct
obvious OCR. Now that Swierkiewicz's opinion_block is empty (topic
mismatch), that's moot. But the underlying OCR-conservatism issue
would resurface in reworded-quote findings. Not critical; leaving for
future iteration.

### 4. Dashboard teaser truncation on long opening sentences

The new mandated lead sentences for topic mismatches ("X is a [type]
case about [multi-clause description]...") are sometimes longer than
the 220-char cap set in commit b85bc7c. They truncate cleanly at word
boundary, but we lose the "It does not address [topic]" part. Not
urgent — the finding card itself shows the full sentence — but the
teaser could be smarter (e.g., find the ". " after the subject-matter
clause and prefer it over a word-boundary truncation).

## Lessons

1. **Visual noise is worse than missing information.** The Kraemer
   "adjust the lodestar upward..." opinion_block was worse than nothing.
   Same for Tompkins' "This appeal presents a chronicle..." intro.
   Default: when a direct quote doesn't land, leave it out.
2. **"Lead with the answer" applies to legal findings too.** Three
   paragraphs of analysis are useless if the reader has to parse them
   to understand the basic nature of the problem.
3. **Small, purpose-scoped prompt changes beat schema changes.** Both
   this session's iterations were ~5 lines of prompt text. The
   infrastructure (agent-authored blocks, three-field schema, dashboard
   rendering) held up without modification.
4. **Partial reruns are cheap enough to iterate fast.** Three parallel
   Opus agents in ~1 min wall clock; the Phase 1a/1b/1d artifacts
   preserved. This makes "iterate on prompt, observe, iterate again"
   the natural loop rather than a big bang.

## Artifacts kept

Brooks (`briefs/gov.uscourts.lawd.207038.49.1/`):
- `claims.csv`, `claims-old.csv`, `report.html`, `report-old.html`
- `brief_metadata.json`
- `assessments_A.json`, `B.json`, `C.json`, `D.json` (initial Phase 2c)
- `assessments_topic_A.json` (Tompkins + Collins rerun with new badge)

Maxwell (`briefs/maxwell-v-michael/`):
- `claims.csv`, `report.html` (updated)
- `assessments_topic_M1.json` (5 topic-mismatch reruns)
- `assessments_topic_M2.json` (Whitlock + Anderson reruns)
- `assessments_namemismatch.json` (Kraemer + Wolfe reruns)

## Next test candidates

1. **Calibration on the McRae/King-2 style Yellows.** If you want to
   dial back to the proposition-verifier's more permissive Green
   standard on verbatim-in-generic-context quotes, one targeted prompt
   iteration would do it. If the current stricter read is the desired
   behavior, no action needed — just something to watch across future
   briefs.
2. **A genuinely new brief, small (3–5 citations).** Now that all four
   common finding types (topic mismatch, inverted holding, reworded
   quote, name mismatch) have landed cleanly on Brooks and Maxwell, a
   run on a fresh brief tests the whole pipeline end-to-end including
   the automatic triage in Phase 2a.
3. **Remove the `tests/ab_test_single.json` file** (untracked, looks
   stale — confirm with user before deleting).
