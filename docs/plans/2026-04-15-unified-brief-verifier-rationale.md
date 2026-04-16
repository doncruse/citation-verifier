# Unified Brief Verifier — Design Rationale

Companion document to `2026-04-15-unified-brief-verifier-plan.md`. Captures the reasoning behind key design decisions, drawn from the A/B test of `/verify-brief` vs `/proposition-verifier` on the Brooks v. Lowe's brief (2026-04-15).

## A/B Test Results

Both skills were run on the same 15-page brief (Memorandum in Support of Plaintiff's Omnibus Motions in Limine, Brooks v. Lowe's Home Centers, No. 1:24-CV-01063, W.D. La.).

### Head-to-head

| | `/verify-brief` | `/proposition-verifier` |
|---|---|---|
| Time | ~9 min active | ~31 min compute |
| API calls | ~21 CL + 17 LLM agents | ~17 CL MCP + parallel agents |
| Results | 9 Green, 8 Yellow, 3 Red | 11 Green, 3 Yellow, 3 Red, 2 Gray |
| Report format | Flat table, quote tags, CL links | Collapsible details, paired blockquotes, methodology |
| Gilliam (NY state) | POSSIBLE_MATCH, confirmed correct | Unable to verify (Gray) |
| Menges (WL-only) | NOT_FOUND (Red) | Unable to verify (Gray) |

### Where they agreed

Both caught Tompkins v. Cyr as the top finding — a complete subject-matter mismatch (case about anti-abortion protesters cited for prior settlement evidence exclusion).

### Where they diverged

| Case | verify-brief | proposition-verifier | Better call |
|---|---|---|---|
| Collins v. Wayne Corp. | Yellow | Red | Prop-verifier — page 784 is about expert cross-exam, not settlement exclusion |
| Abel | Yellow | Red | Prop-verifier — brief inverts the holding (Abel supports broad admissibility, brief says "must demonstrate actual bias") |
| Menges | Red | Gray | Prop-verifier — "unable to verify" is more honest for a CL coverage gap |
| Old Chief p.8 (spoliation) | Red | Green | Verify-brief — the brief applies Rule 403 language to spoliation, which Old Chief never discusses |
| Michelson | Green | Yellow (pinpoint off) | Prop-verifier — arrest discussion isn't at pp. 475-76 |
| Bankcard, Lasha | Green | Yellow (word swaps in "verbatim" quotes) | Prop-verifier — caught granular quote accuracy issues |

Score: proposition-verifier got 5 calls better, verify-brief got 1 (Old Chief p.8).

### Verdict

Proposition-verifier's assessment quality is higher. Verify-brief's mechanical pipeline is faster and finds more cases. The unified skill combines both.

## Key Design Decisions

### 1. Report format: proposition-verifier style

**Decision:** Use collapsible `<details>` sections with paired blockquotes ("What the brief claims" / "What the opinion actually says"), Lora serif headings, methodology disclosure section.

**Why:** The user strongly prefers this format. The side-by-side blockquotes make quote discrepancies immediately visible — you see "policy behind" vs "purpose of" without reading an explanation. The collapsible sections let a lawyer scan the dashboard quickly and drill into specific issues. The methodology section adds credibility by disclosing which opinions were retrieved vs. unavailable. The flat-table format from verify-brief reads like a developer dashboard, not a document a lawyer would trust.

### 2. Assessment calibration: stricter, with examples

**Decision:** The Opus assessment prompt includes explicit calibration examples drawn from the Brooks A/B test (Collins, Abel, Old Chief).

**Why:** Verify-brief's prompts were too lenient. Collins ("excludes irrelevant evidence" but the case favored admission) and Abel ("must demonstrate actual bias" but the case holds bias evidence is broadly admissible) were both Yellow when they should have been Red. The distinction: "partially supported" means the case is topically related and its holding can reasonably be extended to the proposition. "Not supported" means the holding is about a different legal issue or the brief inverts it. Without calibration examples, the assessment agent defaults to lenient — it sees the case is in the right legal domain and says "partially relevant."

### 3. No auto-Green "clean track"

**Decision:** Every claim gets checked against opinion text. The triage determines how deep (fast-track grep + Haiku confirmation vs. full Opus assessment), not whether a claim gets checked at all.

**Why:** An earlier draft of the plan had a "clean track" where claims with no quotes, no metadata flags, and no lead-authority status would auto-Green without any opinion-text verification. This is dangerous. The Brooks results show cases that would pass every surface check but are still problematic:
- McRae cited for "must exclude" when the opinion says exclusion is discretionary (no quotes, VERIFIED status, clean metadata → would have auto-Greened)
- Old Chief p.8 cited for spoliation when the case never discusses spoliation (no quotes, VERIFIED, clean metadata → would have auto-Greened)

The most important verification — does this case actually support what the brief says? — requires reading the opinion. Surface signals can't substitute.

### 4. Grep-first, Haiku-as-fallback (not Haiku-first)

**Decision:** For opinions > 20K chars, grep for the proposition's key terms first. If hits, extract excerpts. If no hits, fall back to Haiku full-read. For opinions < 20K chars, skip grep and read directly.

**Why:** An earlier draft ran Haiku summaries on all large opinions before triage, then used the summaries for both triage and assessment. This was backwards — it did expensive work before knowing which claims needed it. The grep-first approach is:
- Faster: grep is instant, Haiku full-reads take minutes per opinion
- More targeted: excerpts include the specific passages relevant to the proposition, not a general summary
- Self-informative: grep misses are themselves diagnostic — if the opinion doesn't contain "settlement" or "prior verdict," it probably doesn't support a proposition about settlement evidence
- Selective: Haiku full-reads only run when greps miss on large opinions — the rarest path

For fast-track claims, grep hits go to Haiku for a quick SUPPORTED/UNCLEAR/NOT SUPPORTED confirmation. UNCLEAR escalates to Opus. This catches the McRae-style problem (grep finds "exclude" and "Rule 403" but Haiku sees the opinion says "discretionary," not "mandatory" → UNCLEAR → Opus).

### 5. Syllabus data preserved from citation-lookup API

**Decision:** Save the `syllabus` and `nature_of_suit` fields from the cluster object returned by the citation-lookup API. Surface them during metadata check for the skill orchestrator to review.

**Why:** The data is already in the API response — we were just throwing it away. Syllabus catches topic mismatches that grep might miss. A case could use the same legal terminology ("relevance," "prejudice") as the proposition but in a completely different context. Grep would find hits, but the syllabus saying "RICO; anti-abortion protesters; harassment" immediately signals something is off. The comparison doesn't need NLP — the LLM reads "Proposition: prior settlement evidence is irrelevant / Syllabus: RICO, anti-abortion protesters" and flags it.

### 6. Gray status for CL coverage gaps (not Red)

**Decision:** Cases not found on CourtListener are "Unable to verify" (Gray), not Red.

**Why:** Menges v. Cliffs Drilling Co. is a WestLaw-only E.D. La. magistrate opinion from 2000 — likely a real case in a known CL coverage gap. Calling it Red implies the citation is fabricated. Gray is honest: "we can't check this, verify through other sources." The proposition-verifier got this right.

### 7. Quote verification separate from propositional assessment

**Decision:** Quote check (deterministic string matching) runs as a separate phase before assessment. Propositional support (AI judgment) runs later, informed by quote check results.

**Why:** This insight came from the proposition-verifier debrief on context-driven shortcuts. Quote verification is cheap and binary — the string is there or it isn't. Propositional assessment is expensive and judgmental — it requires reading and reasoning. Treating them as separate workflows means:
- Quote check runs on all citations with quotes (cheap, no LLM needed)
- Quote check results inform triage — FABRICATED quotes are automatic flags for full Opus assessment
- The assessment agent can focus on propositional support because quote accuracy is already handled

## Source Documents

- `/verify-brief` retrospective: `docs/retrospectives/2026-04-15-verify-brief-brooks-v-lowes.md`
- `/proposition-verifier` run notes: `briefs-2/gov.uscourts.lawd.207038.49.1_run_notes.md`
- `/proposition-verifier` report: `briefs-2/gov.uscourts.lawd.207038.49.1_proposition_report.html`
- `/verify-brief` report: `briefs/gov.uscourts.lawd.207038.49.1/report.html`
- Proposition-verifier debrief on context shortcuts: provided in conversation (not saved as a file — key insights extracted into this document and the plan)
- Implementation plan: `docs/plans/2026-04-15-unified-brief-verifier-plan.md`
