# Proposition Verifier — pipeline redesign (Tier 3 #11)

**Date:** 2026-06-11
**Status:** Approved for planning (user sign-off in session; see §13)
**Replaces:** the SKILL.md-orchestrated `/verify-brief` flow
**Roadmap:** `docs/plans/2026-06-10-prioritized-roadmap.md` Tier 3 #11 (folds in Tier 2 #7)
**Baselines:** `tests/data/withers_aberdeen/README.md` (existence + assessment), `tests/ab_test_cases.json` (62 cases)

---

## 1. The problem

`/verify-brief` works, but as ~400 lines of SKILL prose orchestrating a mix of
CLI steps, Agent-tool subagents, and ad-hoc session judgment. Twelve
retrospectives accumulate the same complaints: extraction is nondeterministic
(59 vs. 62 vs. 20 claims on the same brief), assessment results re-enter
claims.csv through throwaway scripts, runs are not resumable except by reading
the SKILL's state table, nothing is A/B-testable except through a parallel
harness with its own prompt copy, and every run needs a live Claude Code
session babysitting it.

It is also misnamed. The tool verifies **propositions against authorities**.
Its true input is a set of *(citation, proposition)* pairs; the brief PDF is
just one way to obtain them. The Withers corpus proved this: the entire
assessment measurement ran from a CSV of pairs with no brief anywhere.

### Measure-first results (both committed)

**Existence layer** (`measure_withers_baseline.py`): the verifier handles
existence well — 0/3 hallucinated cites clean-verified, 44/51 reals located —
but **0/19 of the exhibit's yellows are catchable by the verifier**, because
yellows are proposition-support and quote-accuracy problems on correctly cited
real cases. That gap is the assessment layer's whole job.

**Assessment layer** (`measure_withers_assessment.py`, 2026-06-11): the
current Phase 2 path (real pipeline front end + the established Opus
single-claim prompt) over 19 yellows + 3 reds + 12 sampled greens:

| | result |
|---|---|
| Yellows caught (Yellow or Red) | **12/19** — 6 exact, 6 over-shot to Red |
| Yellows missed (called Green) | **7** — ~3 mechanically catchable, ~4 judgment calls (3 on author-hedged rows) |
| Greens | 9/12 exact, 2 over-flagged (1 hedged), 1 Gray (WL gap) |
| Reds | 1 Red via WRONG_CASE, 2 Gray (NOT_FOUND, "unable to verify") |

Three design-shaping facts from that run:

1. **The deterministic quote check is the strongest single lever.** 5 of 12
   catches came from the FABRICATED flag + the "FABRICATED → at least Yellow"
   prompt floor. Three of the seven misses fall to deterministic extensions
   (§6.4): a CLOSE-quote floor (Anderson) and ≥2-word quote extraction
   (Am. Auto ×2). Realistic corpus ceiling ≈ 15-16/19; the rest is
   irreducible-disagreement band.
2. **Severity-scale mismatch, not model failure, explains the over-shoots.**
   The exhibit's colors encode existence (red = hallucinated); ours encode
   support severity (Red = unsupported). The fix is an explicit two-axis
   output (§6.9), not prompt tuning.
3. **`claude -p` cannot be the only LLM transport.** Nested `claude -p` fails
   auth (401) inside a Claude Code session even with `ANTHROPIC*`/`CLAUDE*`
   env stripped, while Agent-tool subagents work cleanly — and the user
   expects the CLI transport to be superseded by the Agent SDK regardless.
   Hence the pluggable executor (§5).

Also surfaced (work items, §11): `matched_name` is empty in
`verification_results.csv` on the batch path, silently breaking
`merge_claims`' opinion-file linkage for 16/29 rows; and
`556 F. App'x 288` (Scott v. Carpanzano) resolves VERIFIED@1.0 to a cluster
CL captions "Rick Scott v. Amer. Natl Trust" (surname-only overlap passes the
lenient lookup name check).

---

## 2. Rename and input contract

- **Name:** `proposition-verifier` (revives the merged-in skill's name; the
  report style already carries its DNA).
- **Module:** `src/citation_verifier/proposition_pipeline.py`, evolving from
  `brief_pipeline.py` (which becomes a deprecated alias re-exporting from the
  new module for one minor version).
- **CLI:** `python -m citation_verifier verify-propositions <workdir> <verb>`
  (`verify-brief` kept as an alias for one version).
- **Workdirs:** `matters/<name>/` (the `briefs/` directory is frozen for old
  runs; nothing migrates).
- **Input contract:** a list of claims — as `claims.csv` or programmatically
  as `list[Claim]`:

```
Claim:
  claim_id        stable row id (e.g. <matter>-NN)
  cited_case      citation exactly as the source cites it (pinpoint allowed)
  proposition     the full assertion the source attributes to the case
  cited_for       optional: the scoped assertion per parenthetical/signal (§6.3)
  quoted_text     JSON array of strings the source places in quotation marks
  brief_sentence  the source sentence(s), verbatim (report display)
  page            page/doc locator in the source
```

- **Front ends** (all optional, all producing the same contract):
  1. *Document extraction* — brief/motion/order PDF → claims.csv, as an LLM
     job through the executor (§5). No longer SKILL prose: the extraction
     prompt is a versioned template, so claim counts stop drifting run-to-run.
  2. *Prepared pairs* — a CSV/JSON the user already has (the Withers corpus
     consumed this way; also the path for spot-checking a single proposition).
  3. *Web app* — future; out of scope here (§12).

The **skill front end shrinks to a thin trigger** (~20 lines): create the
workdir, run the CLI verbs in order, dispatch Agent-tool subagents when the
executor is in jobs mode, open the report. The pipeline is complete without
it; the skill exists because (a) "/proposition-verifier this brief" is how
interactive runs start, and (b) inside a Claude Code session the Agent-tool
executor is the one transport that always works (§1 fact 3).

---

## 3. Pipeline architecture

Nine idempotent verbs over a workdir. Deterministic unless marked **LLM**.

| # | verb | does | state written |
|---|------|------|---------------|
| 0 | `extract` (**LLM**, optional) | document → claims.csv + TOA/body citation lists | `claims.csv`, `citations_toa.txt`, `citations_body.txt` |
| 1 | `verify` | `verify_batch` wave1+wave2 + opinion downloads; **fixes the empty-`matched_name` batch-path bug** | `verification_results.csv`, `opinions/` |
| 2 | `merge` | join claims↔results; **slug-token opinion linkage** replaces name-containment | `claims.csv` |
| 3 | `check-quotes` | deterministic quote verdicts + floors (§6.4) | `claims.csv` |
| 4 | `crosscheck` | TOA-vs-body diff, court check, pincite check (§6.5) | `claims.csv` |
| 5 | `triage` | assessment depth per claim; optional Haiku prescreen jobs (§6.7) | `claims.csv`, `jobs/prescreen*.json` |
| 6 | `assess` (**LLM**) | grouped assessment jobs through the executor (§5, §6.8) | `jobs/assess.json`, `jobs/assess_results.jsonl` |
| 7 | `apply-assessments` | verdicts JSONL → claims.csv (§6.6) | `claims.csv` |
| 8 | `report` | claims.csv → report.html (existing template + §6.9 lanes) | `report.html` |

`--full` chains 1→8 (and 0 when given a document). Each verb checks its
prerequisites and refuses or no-ops if already satisfied, so **resume = rerun
the verb**; a `status` verb prints which phase each claim is in.

**Every verb is both a CLI command and an importable library function**, and
each operates on *any* conforming workdir — not just ones the pipeline
created. That is what lets benchmarking, the A/B harness, and one-off
experiments call `check_quotes(workdir)` or `assess(workdir, config)` over a
hand-built or frozen workdir without going through the full chain. (Decided
2026-06-11, user comment #3.)

**Reproducibility.** `run.json` in the workdir records git hash, prompt
template versions, model IDs, executor, and per-verb timestamps. Prompt
templates live in `src/citation_verifier/prompts/` (e.g. `assess.md` with a
version header), not in SKILL prose or harness code — the A/B harness and the
pipeline render the same template.

**A/B testing per phase.** A "config" = {executor, model, prompt version,
prescreen on/off, batching caps}. The harness runs any single verb (usually
`assess`) over a *frozen workdir* with config A vs. B and scores against
ground truth (§7-8). The existing 62 cases convert to one frozen workdir per
source brief; Withers is already a workdir
(`tests/data/withers_aberdeen/assessment_workdir/`).

---

## 4. State and schema

`claims.csv` remains the single evolving state file (column names kept
compatible with `brief_pipeline.py` so legacy claims.csv and the report
fallbacks still load):

- input: `claim_id, page, proposition, cited_for, cited_case, quoted_text, brief_sentence`
- after `merge`: `cl_status, cl_url, retrieved_case, opinion_file, syllabus, diagnostics`
- after `check-quotes`: `quote_check, quote_check_worst, quote_floor`
- after `crosscheck`: `crosscheck_flags` (JSON: `toa_mismatch`, `court_mismatch`, `pincite_flag`, each with details)
- after `triage`: `triage_track` (`full` | `fast`), `prescreen_hint`
- after `apply-assessments`: `support` (§6.9), `assessment` (color), `badge_label, brief_block, opinion_block, finding_analysis`, `assessed_by` (model + prompt version)

Sidecars: `jobs/<phase>.json` (the job list), `jobs/<phase>_results.jsonl`
(append-only verdicts; the resume key is `claim_id`), `run.json`.

---

## 5. LLM executor

The assessment job is fundamentally **one LLM call**: (claim fields + opinion
text) → verdict JSON. Agentic file-reading exists today only because the work
runs inside Claude Code. So LLM verbs emit a transport-neutral jobs file and
consume a verdicts JSONL; the executor between them is pluggable:

```python
class LLMExecutor(Protocol):
    def run(self, jobs: list[Job]) -> Iterable[Verdict]: ...

Job:      job_id, claim_ids, prompt (rendered template), files (opinion paths),
          schema (expected JSON), max_chars
Verdict:  claim_id, fields per schema, model, prompt_version, elapsed_s, cost_usd
```

| adapter | transport | auth/cost | use |
|---|---|---|---|
| **AgentSDKExecutor** (headless default) | `claude-agent-sdk` (Python), `allowed_tools=["Read"]`, model from config | CLI/subscription auth, no per-token bill | unattended runs, A/B harness, terminal |
| **AgentToolExecutor** ("jobs mode") | writes `jobs/<phase>.json` and exits with "pending"; the orchestrating Claude Code session dispatches Agent-tool subagents (one per job) which append to the results JSONL; rerun the verb to ingest | session subscription | interactive `/proposition-verifier` runs (the only transport that works inside a session today) |
| **RecordedExecutor** (replay) | serves verdicts from a stored `jobs/<phase>_results.jsonl` keyed by `claim_id` + prompt version; misses raise (like `CassetteMiss`) | none — offline | tests, scoring, CI; the assessment-side mirror of `cassette_client.py` |
| **MessagesAPIExecutor** (optional, build last) | `anthropic` SDK, opinion text inlined (no tools), structured outputs; optionally the Batches API at 50% cost | API key, per-token | CI live runs, bulk re-scoring |

The measurement script validated the jobs-mode flow end-to-end (jobs file →
Agent-tool subagents → JSONL → scoring). `claude -p` is **not** an adapter:
it is the transport the Agent SDK supersedes, and it cannot run inside a
session.

The same protocol serves `extract` (document in `files`, claims-array schema
out) and the Haiku prescreen (summary-hint schema out).

### 5.1 Executor PoC results (2026-06-11, this machine)

`tests/poc_agent_sdk_executor.py`:

- `claude-agent-sdk` 0.2.97 installs into the venv and runs a headless
  `query()` end-to-end — the transport returns a structured `ResultMessage`
  with `result`, `is_error`, `total_cost_usd`, `num_turns`, `duration_ms`.
  **Fully validated 2026-06-11 (post-login):** auth smoke PASS, and the real
  `withers-01` assess job returned a parseable verdict (Yellow) via
  `allowed_tools=["Read"]` reading the opinion from the workdir — the **same
  call the Agent-tool subagent made**, so the two transports agree on that
  row (cross-transport consistency signal).
- Auth is the standalone CLI's stored OAuth credentials, and they **do not
  auto-refresh headlessly**: the token in `~/.claude/.credentials.json` had
  expired 2026-06-03 (the desktop app refreshes its own auth, not the
  CLI's), producing the initial 401 in both `claude -p` and the SDK; a
  `claude login` refresh cleared it and the PoC went green.
  **Operational prerequisite:** the executor must detect the 401 and tell the
  user to run `claude login` instead of failing N jobs silently.
- Parent-session env (`ANTHROPIC_BASE_URL`, `CLAUDE*`) must be stripped
  before spawning the SDK/CLI from inside a Claude Code session — the
  AgentSDKExecutor does this; jobs mode remains the in-session default.
- Consuming the SDK's async generator partially (early return) segfaults at
  shutdown on Windows — adapters must drain the generator.

---

## 6. The folded-in decisions

### 6.1 Rename + input contract
As §2. Decided: `proposition-verifier`.

### 6.2 Pipeline architecture
As §3 and §5. Decided: library-first; phases as idempotent CLI verbs;
pluggable executor with Agent SDK as the headless default.

### 6.3 Proposition scoping — option (c), both fields
`extract` emits `proposition` (the full assertion in context) **and**
`cited_for` (what the signal/parenthetical attributes to this specific case,
when narrower). The assessment template judges `cited_for` when present and
uses `brief_sentence` for context, so compound-argument sentences (the State
v. Kelly class) stop producing false Yellows/Reds. Prepared-pairs input may
supply either or both.

### 6.4 Fabricated-quote check — separate criterion + deterministic floors
Quote accuracy is its own axis, never blended into support:

- `check-quotes` extracts quoted spans at **≥2 words** (was ≥4 in the
  measurement script; the 2-word quoted term "judicial admissions" is exactly
  what the Am. Auto misses hinged on) and records per-quote
  VERBATIM/CLOSE/FABRICATED + matched passage (existing matcher).
- Deterministic **floors** written into `quote_floor` and enforced by
  `apply-assessments` (the agent can lower a color, never raise it past the
  floor): FABRICATED quote → at most Yellow; **CLOSE quote inside quotation
  marks → at most Yellow** (the Anderson miss; also the Fletcher retro's
  five false Greens and the Brooks Bankcard/Lasha class).
- Known matcher limits stay on record (star pagination, bracket alterations —
  TODO "Quote checker limitations") and are normalization fixes inside the
  existing matcher, not new machinery.

Withers projection: these rules alone move 12/19 → ~15/19 caught.

### 6.5 TOA / court / pincite cross-check — new deterministic `crosscheck` verb
- **TOA vs. body:** `extract` writes both citation lists; `crosscheck` diffs
  volume/reporter/page/year per case (the Bryant "597 F.3d" vs "97 F.3d"
  class). Both variants go to `verify` (already SKILL policy; now enforced).
- **Court check:** cited court vs. matched CL court — catches Doe v. City of
  Memphis (6th, not 5th) and Donovan (2d, not 5th) with zero LLM involvement.
  Renders as a flag on the card even when support is otherwise fine.
- **Pincite check (best-effort):** pinpoint within the opinion's
  star-pagination range; footnote-number existence grep for `n.X` pincites
  (the In re OCA n.32-vs-n.2 class). Produces *flags*, not verdicts —
  feeds triage and the report, never the color function directly.

### 6.6 Assessment-to-CSV + report — CLI verbs
TODO option (c), decided: `apply-assessments` ingests the verdicts JSONL into
claims.csv (validating against floors and schema); `report` renders. The
throwaway `apply_assessments.py` scripts and Write-denied-subagent workaround
disappear: subagents only append JSON lines; the pipeline owns the CSV.

### 6.7 Haiku prescreen (Tier 2 #7) — a `triage` option
`triage` config `prescreen: haiku` (opinions ≥20K chars): Haiku summary-hint
jobs through the same executor, hints stored in `prescreen_hint` and passed
to the assessment template — exactly the A/B "with-hints" configs. Prior data
(76% exact, 3% one-step-lenient, ~15× cheaper) suggested default ON, but the
Valve outlier (73%) said decide by re-running the A/B harness. **RESOLVED
2026-06-13 (Step 8 9.5): default OFF.** The per-phase re-run (opus-v2 vs
opus-v2-hints over the 3 corpora) found hints give no A/B gain (55/61 both)
and regress Withers 16→14 yellows caught, both losses lenient-direction —
the summary topline compresses away the brief-vs-holding gap that support
assessment turns on. Machinery stays wired for a redesigned (non-summary)
hint; see `docs/retrospectives/2026-06-12-pipeline-redesign-steps1-8.md`.

### 6.8 Subagent batching + external-tool prohibition
Assess jobs group claims by opinion, then pack into jobs capped at **≤4-5
opinions AND ≤200K combined chars** (the Chemtura/1141-Realty timeout
lesson). The external-tool prohibition lives in the versioned prompt template
*and* at the transport: Agent SDK `allowed_tools=["Read"]`; Agent-tool prompt
includes the prohibition; Messages API has no tools at all.

### 6.9 Two-axis output; CITE_UNCONFIRMED as a first-class lane
Every claim carries three independent verdicts:

- **existence** — the verifier status verbatim (+ warnings, incl.
  `cite_contradicted` / `cite_not_on_record`)
- **support** — `supported | partial | unsupported | unverifiable`
- **quote** — worst of the per-quote verdicts

Report **color is a documented function** of the three:

| existence | support/quote | color/lane |
|---|---|---|
| NOT_FOUND / INSUFFICIENT_DATA / INCOMPLETE (no text) | — | Gray "Unable to verify" |
| WRONG_CASE | assessed vs. resolved text | Red "Citation resolves to different case" |
| **CITE_UNCONFIRMED** | assessed vs. downloaded text | **amber "Check Cite" lane — never Red** |
| VERIFIED-family | supported + VERBATIM/NO_QUOTES | Green |
| VERIFIED-family | supported + CLOSE/FABRICATED | Yellow (floor, §6.4) |
| VERIFIED-family | partial | Yellow |
| VERIFIED-family | unsupported | Red |

Scoring against external audits uses a documented mapping (Withers yellow ≈
our {Yellow ∪ Red on a real case}; Withers red ≈ our {WRONG_CASE, NOT_FOUND,
Check Cite}) and compares axes separately — the measurement's ad-hoc mapping
becomes part of the harness.

### 6.10 Web app onto `verify_batch()` (Tier 1 Step 5)
**Out of scope.** Independent small PR. The web app is noted only as a future
front end of the §2 contract.

---

## 7. Assessment corpora + replay (the "cassette" for the LLM layer)

The verifier's accuracy work became tractable when CL responses got a
record/replay harness (`cassette_client.py`). The assessment layer gets the
same treatment, with the verdicts JSONL as the cassette:

- **`tests/data/assessment_corpora/<name>/`** — one *frozen workdir* per
  corpus: `claims.csv` (through the deterministic phases), `opinions/`,
  `ground_truth.csv` (expected per-axis verdicts + provenance), and
  `jobs/assess_results.jsonl` (a recorded live run — the cassette).
- **Offline by default:** tests and scoring run the pipeline with
  `RecordedExecutor` over the frozen workdirs — no LLM calls, seconds not
  minutes, CI-able. A prompt-template change invalidates the recording
  (version key mismatch) → re-record live, exactly the cassette policy.
- **Seed corpora:** `withers` (54 rows; workdir already committed at
  `tests/data/withers_aberdeen/assessment_workdir/`, moves here),
  `payne` (28) and `wainwright` (34) — opinions already committed under
  `briefs/`, ground truth in `ab_test_cases.json`.
- **Candidate additions** (ground truth recoverable from retros/claims.csv;
  add opportunistically, not blocking): `kettering`, `brooks`
  (gov.uscourts.lawd.207038.49.1), `maxwell`. Fletcher / Fivehouse / Valve
  exist only as local uncommitted workdirs — commit them during
  consolidation or drop them.
- `ab_test_cases.json` stays as the human-review ledger; the corpus
  `ground_truth.csv` files are generated from it (and from the Withers
  exhibit) so there is one scoring path, not two.

## 8. Acceptance baseline

The redesign is measured against, and must not regress:

1. **Withers corpus (54 rows)** via `measure_withers_assessment.py` re-pointed
   at the new pipeline. Targets: yellows caught **≥15/19**; green over-flags
   **≤2/12** sampled; reds **3/3** flagged in {Red, Check Cite, Gray-unable};
   the two §1 baseline tables in `tests/data/withers_aberdeen/README.md` are
   the before numbers.
2. **62 A/B ground-truth cases** (Payne + Wainwright) via the re-pointed
   harness: overall accuracy **≥ the 85% Opus baseline**, no new
   lenient-direction (Red→Yellow→Green) errors vs. the recorded runs.
3. **Mocked suite** stays green; `brief_pipeline` alias keeps
   `test_brief_pipeline.py` passing until the alias is dropped.

Both corpora score per the §6.9 two-axis mapping.

---

## 9. Skill and harness disposition

- `.claude/skills/verify-brief/SKILL.md` → replaced by
  `.claude/skills/proposition-verifier/SKILL.md`, a thin wrapper: startup
  checks, workdir creation, verb sequence, jobs-mode agent dispatch, report
  open. All assessment criteria, batching rules, and prohibitions move into
  versioned prompt templates.
- `tests/ab_test_runner.py` → re-pointed at the executor + frozen-workdir
  contract (and optionally relocated to `tools/` per roadmap Tier 2 #9).
  `ab_test_cases.json` and `build_review_page.py` stay as-is.
- `measure_withers_assessment.py` becomes the rerunnable Withers regression.

## 10. Implementation sketch (ordering only; plan doc comes after sign-off)

1. Corpus consolidation (§7): `tests/data/assessment_corpora/` with withers +
   payne + wainwright frozen workdirs and `ground_truth.csv` generation;
   RecordedExecutor + the executor protocol — this lands the offline TDD
   harness everything else builds on.
2. `proposition_pipeline.py` skeleton: verbs 1-2 (verify/merge) ported, the
   `matched_name` bug fixed at the source, slug linkage replacing
   name-containment; `brief_pipeline` alias.
3. Verb 3 quote-check extensions (≥2-word spans, floors) — pure TDD off the
   Withers frozen workdir.
4. AgentToolExecutor (jobs mode) + verbs 6-7 (assess/apply-assessments);
   prompt templates extracted.
5. AgentSDKExecutor (after a `claude login` refresh; PoC §5.1 re-run green);
   `extract` verb (template + TOA/body lists).
6. Verb 4 crosscheck; verb 5 triage (+ prescreen wiring).
7. Report lanes (§6.9), new SKILL stub, A/B harness re-point.
8. Acceptance runs (§8); retro.

## 11. Work items logged (not blocking this design)

- **Bug:** batch path leaves `raw_response_summary["case_name"]` empty →
  `matched_name` blank in `verification_results.csv` (fix in step 1 above).
- **Existence-layer FP class:** `556 F. App'x 288` → VERIFIED@1.0 on CL
  cluster captioned "Rick Scott v. Amer. Natl Trust" (text appears to be
  Carpanzano under a stale caption — investigate; candidate
  `cl_display_name_data_bug` vs. F. App'x page-collision; relates to the
  lenient `_names_match_citation_lookup` surname rule).
- Nested `claude -p` 401 inside Claude Code sessions — documented; no fix
  planned (Agent SDK + jobs mode are the answers).
- Owed separately: the check-cite live acceptance pass (full `-m live_api` +
  fake/real corpora re-record) on this token machine — unrelated to this
  design, must not be forgotten.

## 12. Out of scope (explicit)

- Web app changes (incl. Tier 1 Step 5 `verify_batch()` re-point).
- Statute/rule verification; Word-doc input (config hook only).
- Bankruptcy docket ranking; semantic-search fallback (Tier 3 #12).
- Any scoring/threshold change in the core verifier.
- Migrating old `briefs/` workdirs.

## 13. Decisions log (sign-off record)

| decision | ruling | by |
|---|---|---|
| Name | `proposition-verifier` | user, 2026-06-11 |
| Architecture | A — library-first, phases as CLI verbs | user ("leaning A"), 2026-06-11 |
| Skill front end | thin optional wrapper; pipeline complete without it | user question + agreement, 2026-06-11 |
| Headless executor default | Agent SDK | user, 2026-06-11 |
| Taxonomy | two-axis, color derived | user ("lean two-axis"), 2026-06-11 |
| Fold-ins 3-10 defaults | as §6 (user: no changes requested) | user, 2026-06-11 |
| Full design | approved "ok lets do it" | user, 2026-06-11 |
| Executor PoC before plan | done — SDK transport validated; stale-CLI-token auth caveat (§5.1) | user comment #1, 2026-06-11 |
| Assessment corpora + replay executor | yes — §7, mirrors cassette policy | user comment #2, 2026-06-11 |
| Every verb CLI-exposed + importable | yes — §3 | user comment #3, 2026-06-11 |
