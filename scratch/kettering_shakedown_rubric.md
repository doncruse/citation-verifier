# Kettering shakedown — POST-RUN evaluation rubric (2026-06-13)

> **DO NOT read this before/during the cold run.** The shakedown is a
> genuine *cold-invocation* test: a fresh session should drive
> `/proposition-verifier` with the SKILL and nothing else, so naive-path
> failures (e.g. the assess-v2-default gotcha below) surface as real
> findings instead of being pre-solved. This file is the rubric to grade
> the result AFTER the cold attempt, and to debug from only if the run
> outright wedges. Reading it first turns a shippability test into a
> guided integration test.

**Purpose:** first *integrated, cold-invocation* end-to-end run of the new
`/proposition-verifier` pipeline on a real brief. This is the validation
the redesign never got: every prior test is offline replay or a one-job
live smoke. Treat it as a **bug hunt** — the goal is to find integration
gaps on the branch before merging `pipeline-redesign` to main.

Branch: `pipeline-redesign` (all 8 design steps complete, 812 tests green
offline). Commit everything per CLAUDE.md (Windows: `venv/Scripts/python.exe`,
ASCII-only console).

## What has NEVER run live / integrated (the things to watch)

1. **The `extract` verb** — zero live runs. Its first real document run is
   THIS. Watch: citation-count stability, and that `cited_case` carries the
   FULL citation text (case name + reporter + year) — merge links opinions
   by slug tokens off that, so a short-form `cited_case` breaks linkage.
2. **The jobs-mode dispatch arc** — only the SKILL *describes* it; it has
   never executed. Two pend/dispatch/ingest cycles:
   - extract pends → dispatch ONE Agent subagent (prompt = the job's
     `prompt` verbatim + the envelope appendix) → it appends to
     `jobs/extract_results.jsonl` → rerun to ingest.
   - assess pends → dispatch one Agent subagent PER opinion (packed v2
     jobs) → each appends one envelope line PER claim of its `verdicts`
     array → rerun to ingest → apply → report.
   Envelope (matches `executor.verdict_from_json`): one JSON line per claim
   `{"claim_id": "...", "prompt_version": "...", "model": "...", "fields": {...}}`
   where `fields` = the claim's verdict minus `claim_id`. Subagents use ONLY
   Read on the workdir + that append; never edit claims.csv (apply owns it).

## KNOWN GOTCHA — flag/decide before running

The `full` chain defaults to **assess-v1** (`DEFAULT_PROMPT_VERSION`), and
the SKILL doesn't mention `--prompt-version`. So a naive cold
`/proposition-verifier` run gets v1 single-color cards (no opinion blocks)
— NOT the assess-v2 two-axis + report-block output Step 8 built. For this
shakedown, run with **`--prompt-version assess-v2`** explicitly.
**This is itself a likely shakedown finding:** decide whether v2 should
become the default (code change — the regression tests pin v1 as default,
so it's deliberate) and/or whether the SKILL should pass/offer v2. Record
the call in the shakedown retro.

## Steps

1. User supplies the kettering brief (PDF or text). Save it into the
   workdir, e.g. `matters/kettering/brief.pdf` (or `.txt`).
2. `matters/kettering/brief_metadata.json`:
   ```json
   {"title": "Defendants' 12(b)(6) Motion to Dismiss / Rule 56 MSJ",
    "case_name": "Kettering Adventist Healthcare v. Collier",
    "case_number": "No. 3:25-cv-00273 (S.D. Ohio)",
    "filed_date": "August 25, 2025"}
   ```
3. `venv/Scripts/python.exe -m citation_verifier verify-propositions matters/kettering full --document matters/kettering/brief.pdf --prompt-version assess-v2`
4. On each `PENDING`, dispatch Agent subagents (above), then rerun the same
   command. Idempotent verbs resume from the jobs sidecars.
5. Open `matters/kettering/report.html`; summarize (Reds w/ rationale,
   Yellow/Check-Cite counts, Green count, unable-to-verify).

## Comparison target (known-answer validation)

The OLD `/verify-brief` run is committed under `briefs/kettering-v-collier/`:
- `report.html` (the prior report), `claims.csv` (20 citations, the prior
  work product), `citations_to_verify.txt` (the 20-cite list).
- Retro: `docs/retrospectives/2026-03-02-verify-brief-kettering-v-collier.md`.
Diff the new run against it: did extract recover ~the same 20 citations?
Do the verify statuses agree? Do the assessment colors broadly line up
(the scales differ — old verify-brief vs new two-axis — so expect lane
shifts, not identity)? Discrepancies are findings, not failures.

## Deliverable

A retro: `docs/retrospectives/2026-06-13-proposition-verifier-shakedown-kettering.md`
— what worked, what broke, the v1/v2-default decision, and a
ship-readiness call for the merge to main. Commit + push.
