# Citation Verifier — Refactor Design

**Status:** Draft for review
**Audience:** Future contributors, Claude Code during implementation
**Purpose:** Specify the refactor that converts citation-verifier from a Python library + parallel Claude skill into a structured MCP server with a thin judgment-layer skill on top.

> Companion review: `2026-05-20-citation-verifier-refactor-design-review.md` (Claude's critique pass; tracks issues to address in follow-up revisions).

---

## 1. Context and motivation

### What exists today

Two artifacts, developed in parallel, both attempting to solve the same problem from opposite directions:

A Python library (`src/citation_verifier/`) that owns a deterministic verification pipeline — extraction via eyecite, resolution via CourtListener's Citation Lookup API, fallback via Opinion Search, fallback via RECAP Search. It returns a flat `VerificationResult` with one of four statuses (`VERIFIED`, `LIKELY_REAL`, `POSSIBLE_MATCH`, `NOT_FOUND`), a confidence score, and a diagnostics list. The library has 103 mocked unit tests, a live regression suite against a known-real corpus, a file cache, and a CLI and web app as consumers.

A Claude skill (`citation-checker`) that teaches a model how to orchestrate the CourtListener MCP tools to do roughly what the library does, but with substantially more nuance: a seven-status taxonomy (`VERIFIED`, `VERIFIED (partial)`, `VERIFIED (via RECAP)`, `VERIFIED (docket-only)`, `VERIFIED (CL display-name mismatch noted)`, `WRONG CASE`, `NOT FOUND`); ingestion from four input shapes (Word context, uploaded PDF, pasted text, CourtListener URL); a full-caption investigation procedure that runs on case-name mismatch warnings; a silent-partial-verification check; environment-adaptive output formatting; an explicit handoff protocol to downstream skills via captured IDs.

The two artifacts overlap heavily. Both run the fallback ladder. Both classify results. Both produce structured output. But they have different statuses, different coverage of edge cases, different consumers, and neither one is finished.

### What's wrong with the current shape

The skill has grown procedural complexity that wants to be code. A 239-line skill that walks the model through a multi-step ladder with branching logic is asking a stochastic system to be deterministic. The model can skip a step, reorder steps, decide a step doesn't apply, or do steps 1–4 cleanly and silently bail on step 5. Failures are silent. The audit trail is whatever the model chose to surface. The procedure is real only to the extent the model felt like making it real on that run.

This is not a "the model needs better prompting" problem. Even if the model followed every instruction perfectly every time, the procedure would still not be *auditable*, *gate-able*, or *machine-checkable* — because those are properties of code, not of model output. Procedural validity is a category that stochastic systems cannot provide by being more compliant. It can only be provided by removing the stochasticity from the procedural layer, which means moving the procedure into code and reserving the model for the judgment layer on top.

The Python repo has classification nuance that's lagged behind the skill's development. The four-status taxonomy collapses meaningful distinctions (partial verification, RECAP-only verification, display-name data bugs, the WRONG CASE category that's the load-bearing hallucination signature) into a coarser scheme that doesn't tell downstream consumers what they need to know.

The skill is doing code-shaped work badly. The repo is doing classification-shaped work coarsely. They share a job and a maintainer and increasingly share each other's bugs.

### The Lavern-shaped reorganization

Lavern ([github.com/AnttiHero/lavern](https://github.com/AnttiHero/lavern)) is an Apache-2.0 open-source multi-agent legal document review system: 67 specialist AI agents debate findings against a parsed document, with code-enforced gates (a grounding verifier, an evaluator gate, a 10-pass verification pipeline) that mechanically check the agents' work before findings can ship. Its architectural insight — the one this refactor borrows — is the strict separation between *prompts that express agent roles* and *code that enforces procedural rules*. The agents do the judgment work; deterministic gates fail closed on findings that don't meet the rules. The agent literally cannot ship a finding without evidence because the verifier, which is not a prompt, will reject it. This refactor applies the same pattern to citation verification: a deterministic Python pipeline owns the procedure, the model owns the judgment over the pipeline's structured output, and gates between them enforce what can pass.

The animating principle, borrowed from Lavern's gate architecture:

> **Code owns procedure. The model owns judgment. The schema is the contract between them.**

The verifier's gates aren't prompts asking the agent to check its work — they're code that runs on the agent's output and fails closed. The agent literally cannot ship a finding without evidence because the verifier won't let it. Applied here: the Python pipeline runs the procedure deterministically and produces a structured intermediate; the skill consumes that intermediate and does only the judgment-shaped work that genuinely requires a model.

This split lets each substrate do what it's good at:

- **Code is good at:** running every step in order, never skipping, producing audit trails as a byproduct, handling API errors structurally, applying scoring algorithms consistently, classifying into a finite taxonomy, batching at scale.
- **The model is good at:** interpreting unresolved results, reasoning over open evidence (web searches, secondary sources, plausibility heuristics), adapting presentation to context, prioritizing which findings matter for a particular brief, explaining implications to humans.

The repeated failure mode the refactor must prevent: the verifier sliding back into the same fuzziness problem the skill had. Once the verifier starts inventing categories it can't justify from evidence, it's doing model-shaped work in code-shaped infrastructure — the worst of both worlds.

### Stated design principles

These should be invoked when resolving ambiguous decisions during implementation. If a decision is being made in tension with these, surface it as an open question rather than silently resolving against them.

1. **Code owns procedure. The model owns judgment. The schema is the contract.** Every implementation decision should be checkable against this.
2. **The verifier reports what it observed and what procedures completed; it does not editorialize about meanings the evidence doesn't support.** Auxiliary signals are facts the verifier can vouch for. Status is a verdict the verifier is willing to defend. Anything in between — heuristic guesses, probabilistic classifications, vibes — gets pushed up to the consumer.
3. **Procedure must be unskippable.** If a step in the pipeline is required for a status's semantic meaning, the code runs that step; the model is not asked to remember to run it.
4. **The structured result is the handoff.** Downstream consumers (skills, other tools, the evaluator) must be able to act on the result object alone without re-running procedural logic to extract what they need.
5. **Fail-closed only at the boundary of verifier integrity.** The one internal gate is "API errors must not become silent NOT_FOUND." Beyond that, gates are caller-policy, not verifier policy.
6. **Respect cross-repo consumers.** Citation-verifier's modules (`parser`, `name_matcher`, `client`, `court_map`, `models`) are consumed by external projects — most notably the benchmark project, which reaches deep into internals. The refactor commits to changing only those APIs the refactor's design genuinely requires. Changes to module public APIs must be documented in the changelog with migration notes so cross-repo consumers can plan their upgrades. Gratuitous churn in stable surfaces is to be avoided.

---

## 2. Schema specification

The load-bearing section. This is the contract between the verifier and every consumer (CLI, web app, MCP clients, the skill, the evaluator, the benchmark project). Once stable, the Python implementation is constrained, the MCP surface is constrained, and the skill's consumption pattern is constrained.

### 2.1 The `VerificationResult` object

```
VerificationResult {
  citation_as_written: string             # The exact input string
  parsed_citation: ParsedCitation | null  # Eyecite/parser output, null if unparseable
  status: Status                          # See 2.2
  confidence: float | null                # 0.0–1.0, null for resolved-clean statuses
  final_ids: FinalIds                     # See 2.4
  resolution_path: ResolutionPathEntry[]  # See 2.5
  warnings: Warning[]                     # See 2.6
  gates_failed: GateFailure[]             # See 2.7, empty unless gates specified
  timing: TimingRecord                    # API latency, total elapsed
  cache_hit: bool                         # Whether result was served from cache
}
```

Every field is mandatory in the result object. Fields that don't apply to a given result are explicitly nullable (with type `| null`) rather than absent. This is a hard rule — consumers must be able to introspect any field on any result without `KeyError`-style failures.

### 2.2 Status taxonomy

Seven states, finite, enumerated. Replaces the existing four-status Python taxonomy entirely. Migration is a clean break — see Section 3 for the consumer-update plan.

**Resolved-clean states:**

`VERIFIED` — Citation resolved cleanly via the primary lookup. Case name matches (or warning was pure formatting noise). All IDs captured.

`VERIFIED_PARTIAL` — A parallel citation resolved but the primary reporter cited in the brief did not. Example: brief cites `201 A.D.3d 83` with parallel `2021 NY Slip Op 06798`; the slip-op cite resolves, the A.D.3d reporter is not in CL's index. Authoritative for the case's existence but the cited reporter is unconfirmed.

`VERIFIED_VIA_RECAP` — The opinion is not in CL's `opinions` index, but the RECAP archive contains the actual court filing as a PDF document. Common for unreported district-court orders cited via Westlaw. Downstream consumers needing opinion text must pull PDF text, not `plain_text`.

`VERIFIED_DOCKET_ONLY` — The docket exists in CL but has no RECAP documents and no opinion text. The case is real; CL has no filings. Lowest-confidence "verified" state.

`VERIFIED_DISPLAY_NAME_MISMATCH` — Case verified, full caption confirms it's the right case, but CL's `case_name` display string differs meaningfully from the opinion's actual caption (known CL data bug). The citation is fine; CL's metadata is the issue.

**Resolved-but-wrong state:**

`WRONG_CASE` — The reporter resolves to a real case, but the full caption confirms it is a completely different case than the brief named. High severity. This is the classic hallucination signature where a model invents a plausible-looking reporter and attaches it to a made-up case name. Author cannot rely on the citation.

**Unresolved states:**

`NOT_FOUND` — Every applicable resolution path ran to completion. None resolved. The verifier asked everything within its competence and CL has nothing. Could mean the case is fabricated, could mean the case is real but outside CL's coverage, could mean the query failed in a way the verifier cannot detect — the verifier does not pretend to distinguish.

`VERIFICATION_INCOMPLETE` — One or more resolution paths failed to complete due to API errors, rate limits, timeouts, or other infrastructure failures. The verifier cannot give an authoritative answer because it could not fully ask. Never collapse this into `NOT_FOUND`; that compression produces malpractice-shaped silent false negatives.

### 2.3 Why these seven and not more

Open question worth noting: the previous Python statuses `LIKELY_REAL` (>= 85% confidence) and `POSSIBLE_MATCH` (>= 40%) are *not* preserved. They were trying to encode procedural information (which fallback path resolved this) as confidence bands. That information is now in `resolution_path` and the granular VERIFIED_* states. Carrying `confidence` as a separate field on the result handles the "how sure are we" dimension without overloading the status enum.

Specifically *not* added to the unresolved branch: a `FABRICATED_LIKELY` or `HALLUCINATION_PROBABLE` status. From inside CourtListener, with the tools available, the verifier cannot honestly distinguish fabricated from coverage-gap from search-malformed. Surfacing that distinction is the skill's job (with web search and judgment) or the evaluator's job (with model-driven diagnosis). The verifier reports `NOT_FOUND` and stops.

### 2.4 The `FinalIds` object

```
FinalIds {
  cluster_id: int | null
  opinion_id: int | null
  docket_id: int | null
  recap_document_id: int | null
  absolute_url: string | null
  text_source: TextSource | null   # "plain_text" | "html_with_citations" | "recap_pdf" | null
}
```

Required fields with explicit nullability. The `text_source` field tells downstream consumers (proposition-check, quote-check) where to retrieve the opinion text. For `VERIFIED` and `VERIFIED_PARTIAL` and `VERIFIED_DISPLAY_NAME_MISMATCH`, expect populated `cluster_id` and `opinion_id`. For `VERIFIED_VIA_RECAP`, expect populated `recap_document_id` and `docket_id` with `text_source: "recap_pdf"`. For `VERIFIED_DOCKET_ONLY`, expect populated `docket_id` only. For `WRONG_CASE`, the IDs point to the case the reporter *actually* resolves to (useful context even though the citation is unusable as written). For `NOT_FOUND` and `VERIFICATION_INCOMPLETE`, all IDs null.

### 2.5 The `ResolutionPathEntry` schema

The resolution path is the verifier's audit trail — every stage attempted, in order, with its query, its result, and its local verdict. This is what consumers inspect when they need to know not just what the verifier concluded but what it did to get there.

```
ResolutionPathEntry {
  stage: StageName               # Enumerated: see below
  query: dict                    # The structured query made (parameters)
  raw_response_summary: dict     # Compact summary of what came back
  verdict: StageVerdict          # "resolved" | "no_match" | "partial" | "errored" | "skipped"
  notes: string | null           # Optional diagnostic, e.g., "rate-limited, retried 2x"
  elapsed_ms: int
}
```

Stage names (initial set; new stages can be added without schema change):

- `citation_lookup` — CourtListener Citation Lookup API
- `adjacent_page_fallback` — retry with +/-1, +/-2 page offsets
- `opinion_search` — fuzzy case-name search via Search API
- `recap_document_search` — `type=rd` search in RECAP documents
- `recap_docket_search` — `type=r` search in dockets with RECAP content
- `plain_docket_search` — `type=d` search in all dockets
- `caption_investigation` — triggered on mismatch warnings; sub-pipeline of cluster → docket → opinion text lookups

A stage entry is recorded for every stage *attempted*, in order. Stages not attempted (because an earlier stage resolved, or because the citation didn't qualify) are not in the path. This means the path's length is itself a signal about how hard the verifier had to work to reach its conclusion.

### 2.6 The `Warning` schema

Warnings are facts about the resolution that a careful consumer should know but that do not invalidate the result and do not change the status. They are not gates. They are not errors. They are notes.

```
Warning {
  category: WarningCategory
  message: string                # Human-readable detail
  details: dict | null           # Optional structured context
}
```

Enumerated warning categories (closed set; additions require schema update):

- `silent_partial_verification` — primary reporter not in CL, only parallel cite resolved
- `cl_display_name_data_bug` — CL's `case_name` differs from real caption; citation is fine
- `court_mismatch_noted` — court in citation differs from CL record, case-name and date match
- `date_close_not_exact` — year differs slightly (+/- 1) from CL record
- `name_formatting_noise` — case name differs from CL purely on abbreviation/punctuation
- `unparseable_citation` — eyecite could not parse cleanly; verifier used regex fallback
- `extraction_contamination_detected` — surrounding text may have contaminated name extraction

The skill is expected to surface warnings appropriately in its presentation layer — some may be footnoted, some may be highlighted, some may be omitted depending on user intent. The verifier reports them all; the skill decides which to elevate.

### 2.7 Gates: the optional fail-closed layer

Gates are *caller policy*, not verifier policy. The verifier accepts a `gates` parameter on the verify call. When specified, the verifier evaluates each gate after producing the result and populates `gates_failed` with structured failure records. The caller decides what to do with a gate failure — block delivery, surface to a human, log and continue.

```
GateSpec {
  name: GateName
  config: dict | null    # Optional gate-specific configuration
}

GateFailure {
  gate: GateName
  reason: string         # Why this gate failed for this result
  details: dict | null   # Optional structured context
}
```

Initial gate set (closed; additions require schema update):

- `no_not_found` — fails if status is `NOT_FOUND`
- `no_wrong_case` — fails if status is `WRONG_CASE`
- `no_verification_incomplete` — fails if status is `VERIFICATION_INCOMPLETE`
- `no_partial_verification` — fails if status is `VERIFIED_PARTIAL`
- `require_primary_reporter_resolved` — fails if `VERIFIED_PARTIAL` (or specifically configured variants)
- `require_caption_investigation_on_mismatch` — fails if any mismatch warning fired but caption_investigation stage didn't run

Gates do not block the verifier's procedure — they evaluate after. A gate failure does not change the result's status or content; it appears only in `gates_failed`. The caller's policy choices stay legible to consumers and reviewers.

### 2.8 The one internal gate

API errors, rate limits, and timeouts must not silently degrade to `NOT_FOUND`. The verifier itself enforces this: any stage that errors out without a clean "no match" response triggers status `VERIFICATION_INCOMPLETE`. The resolution_path captures which stage(s) failed. No caller policy can disable this — it protects the integrity of the verifier's own semantics.

### 2.9 Batch results

```
BatchVerificationResult {
  total: int
  by_status: dict[Status, VerificationResult[]]   # Grouped, not flat
  errors: BatchError[]                            # Per-citation failures that prevented even calling the pipeline
  elapsed_ms: int
}
```

Returning results grouped by status (rather than as a flat list the consumer has to filter) is a deliberate ergonomic choice for the skill. The skill's most common job is "tell me about the problem citations" — a grouped result makes that one field access, not a filter loop. Flat-list consumers can flatten trivially; grouped consumers get a fast path.

The grouping is more than ergonomic preference: typical use involves verifying every citation in a brief, which is routinely 100–200 citations and sometimes more. At that scale, the skill cannot reason in free-form prose about each citation individually without producing an unscannable wall of text. The grouped-by-status shape lets the skill present a brief summary line ("verified 178; 14 not found; 6 verification incomplete; 2 wrong case") and then handle only the problem subset with structured per-citation judgment. The schema is shaped for this presentation pattern because the alternative does not scale.

---

## 3. Refactor plan

Phased, with concrete acceptance criteria. Phases are dependent in order; later phases assume earlier phases' acceptance criteria are met.

### Phase 1 — Schema and types

Pure data structure work. Define the new types in `models.py` per Section 2. No verification logic changes yet.

**Tasks:**
- Define `Status` enum with the seven states.
- Define `VerificationResult`, `FinalIds`, `ResolutionPathEntry`, `Warning`, `GateSpec`, `GateFailure`, `BatchVerificationResult`, supporting enums.
- Migrate `verifier.py` and tests to construct and consume the new types. Initial mapping from existing four-status taxonomy: `VERIFIED → VERIFIED`, `LIKELY_REAL → VERIFIED` (with confidence field), `POSSIBLE_MATCH → VERIFIED` (with lower confidence), `NOT_FOUND → NOT_FOUND`. The richer states (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, etc.) are not yet *produced* in this phase; only their type definitions exist.
- Update consumers (CLI, web app, test suite) to use new types. Clean break, no compatibility layer.

**Acceptance:**
- All 103 existing unit tests pass against new type signatures.
- All 30 async-parity tests pass.
- Live regression suite (`test_false_negatives.py`) passes against new types.
- CLI and web app both function with new result shape.

### Phase 2 — Resolution path instrumentation

Modify pipeline stages to emit structured `ResolutionPathEntry` records. No new statuses, no new logic, just instrumentation.

**Tasks:**
- Wrap each stage in `verifier.py` to produce a path entry on entry and exit.
- Capture query parameters, response summary, verdict, elapsed time, notes.
- Ensure path is captured even on error / early-exit paths.
- Add path-presence and path-shape tests.

**Acceptance:**
- Every `VerificationResult` produced has a non-empty `resolution_path`.
- Replaying any cached result (or any test fixture) reproduces the same path.
- New tests verify path shape for each fallback scenario.

### Phase 3 — Status taxonomy migration

Implement the full seven-status taxonomy. Migrate classification logic from the skill's prose into Python.

**Tasks:**
- Implement detection logic for `VERIFIED_PARTIAL` (silent partial verification check).
- Implement detection logic for `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`.
- Implement the full-caption investigation as a method (`_investigate_caption`), triggered automatically on any case-name mismatch warning. The method runs the three-step lookup (cluster `case_name_full` → docket `case_name` → opinion `plain_text` first 500 chars) and classifies the mismatch as `name_formatting_noise`, `cl_display_name_data_bug`, or `WRONG_CASE`.
- Implement `WRONG_CASE` classification path.
- Implement `VERIFIED_DISPLAY_NAME_MISMATCH` as the outcome of a caption investigation that finds the citation is correct but CL's display name is buggy.
- Populate `warnings` per Section 2.6.

**Acceptance:**
- A regression corpus (see Section 4 below) produces the expected status for each test case.
- Specific fixtures from the skill's edge-case discoveries (the Koch case-name bug, the Gilliam parallel-cite case, the Menges WL cite, and others to be inventoried) produce the correct seven-status result.

### Phase 4 — Gates

Add optional `gates` parameter to verify calls. Implement gate-failure reporting. Implement the internal API-error gate.

**Tasks:**
- Add `gates: list[GateSpec] | None` parameter to verifier entry points.
- Implement gate evaluation as a post-procedure step.
- Implement `VERIFICATION_INCOMPLETE` triggering on any stage with `verdict: errored` (the one internal gate, not caller-configurable).
- Distinguish stage-erroring (caused by infrastructure) from stage-returning-no-match (clean negative).

**Acceptance:**
- Verify calls with no gates parameter behave identically to Phase 3.
- Verify calls with gates produce `gates_failed` populated correctly.
- API failures consistently produce `VERIFICATION_INCOMPLETE`, never silent `NOT_FOUND`.
- New tests cover each gate and the internal API-error gate.

### Phase 5 — MCP server

Thin shell over the library. Wraps the existing entry points in the MCP protocol.

**Tasks:**
- Implement an MCP server exposing tools: `verify_citation`, `verify_citations_batch`, `verify_with_gates`.
- Add `inspect_citation_format` as a separate helper tool — cheap deterministic checks (reporter exists in index, volume in known range, date consistent with reporter active period) returning structured facts without prejudging. This is the auxiliary signal surface the skill can call when it wants to inform its judgment about a `NOT_FOUND`.
- Result serialization for MCP transport (JSON shape matching Section 2 types).
- Authentication: the verifier MCP requires a CourtListener API token in its environment (`COURTLISTENER_API_TOKEN`), same model as the existing Python library. The MCP makes direct HTTP calls to CourtListener via the existing sync/async client infrastructure — it does not proxy through the CourtListener MCP. Rationale: batch verification of a brief's 100-200 citations requires the concurrency, connection pooling, and rate-limit handling of the existing Python clients; MCP-to-MCP forwarding of that volume of calls through Claude's tool-use loop is not viable. The friction this creates for end users who don't have CL tokens is acknowledged and deliberately deferred to a separate future project (see Section 7 open questions). The MCP returns a clean structured error when no token is configured so the calling skill can surface "you need to set up a CourtListener API token" guidance to the user.
- Rate limiting honors CourtListener's published limits via the existing client logic.

**Acceptance:**
- An MCP client can call each tool and receive a structured result matching the schema.
- The batch tool returns grouped-by-status results per Section 2.9.
- The `inspect_citation_format` tool returns deterministic results without invoking verification.

### Phase 6 — Skill rewrite

The skill shrinks to its essential job: ingestion, invocation, presentation.

**Tasks:**
- Strip all procedural logic from `citation-checker/SKILL.md`. The skill no longer describes the fallback ladder, the classification taxonomy, the full-caption procedure, or the silent-partial-verification check — all of these now live in the verifier.
- Retain: ingestion logic across four input shapes; invocation of the MCP tool with appropriate batching; presentation logic adapted to environment (chat, Word inline, Word appendix); interpretation of `NOT_FOUND` results using web search and model judgment; handoff documentation pointing downstream skills at the `FinalIds` fields.
- Add explicit guidance for the `NOT_FOUND` judgment task — the skill is encouraged to use web search, secondary-source checking, reporter plausibility reasoning, and pattern-matching against known hallucination signatures. Output should be structured (per-citation classification with brief reasoning) not free-form prose.
- Submit the post-refactor skill to [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) as a community contribution. The skill's frontmatter must clearly document the verifier MCP dependency: name, where to install it, what it provides, and the failure mode if it's not installed. Users discovering the skill through the lq-skills catalog need to know what additional infrastructure they need.

**Acceptance:**
- Skill is under 100 lines (target; not a hard cap).
- Skill references no procedural logic.
- Skill delegates all verification to the MCP.
- Skill's presentation of batch results is structured (e.g., grouped table) not free-form per-citation prose.
- Skill is submitted to lq-skills with explicit verifier-MCP dependency documentation in its frontmatter.

### Phase 7 — Evaluator and regression harness

Build the corpus runner, the diagnostic step, and the issue-drafter. This is what makes the verifier improve over time.

**Tasks:**
- Implement a regression corpus runner that replays the verifier against a curated set of citations with known ground truth, producing a failure report.
- Implement a model-driven diagnostic step that takes failed corpus cases (or external candidates — see below) and classifies the failure cause: `hallucination_confirmed`, `mis_cite_corrected` (with the corrected citation captured), `verifier_miss` (with the ground-truth resolution captured), or `ambiguous`. The diagnostic uses Claude with CourtListener access to investigate each case.
- Implement deduplication: citations classified once are cached, keyed by normalized citation string.
- Implement an issue-drafter that converts `verifier_miss` diagnoses into structured GitHub issues: title, reproduction steps, expected vs. actual behavior, hypothesized cause, suggested fix area.
- Expose the evaluator via its own MCP surface: `diagnose_not_found`, `diagnose_not_found_batch`. Design these as public interfaces — the benchmark project will consume them.

**External integration:**

The evaluator is designed for the assumption that `NOT_FOUND` candidates may come from multiple sources: manual review, automated runs against test briefs, and external projects like the proposition-benchmark project. The diagnostic step is uniform across sources. The benchmark project consumes `diagnose_not_found_batch` and routes:
- `hallucination_confirmed` → benchmark logs the confirmed hallucination (this is signal for the benchmark)
- `verifier_miss` → both the benchmark and the verifier's corpus get notified; the corpus grows with this real false negative
- `mis_cite_corrected` → benchmark logs the model-cited-real-case-badly outcome; verifier may consider whether the corrected variant should have been found via fuzzy fallback
- `ambiguous` → flagged for human review

The benchmark's role is broader than just feeding NOT_FOUNDs, though. The benchmark continuously generates ground-truthed citation results across many models and propositions — every benchmark run produces (model, proposition, candidate_citation, verifier_result, ground_truth) tuples. The ground-truthed subset is direct corpus material: cases where the benchmark already knows the right answer (because human review, secondary source confirmation, or cross-model consensus has established it), and the verifier's verdict can be compared to that ground truth on every regression run. The Phase 7 design should anticipate ingesting structured ground truth from external sources, not just diagnosing isolated NOT_FOUNDs.

This creates the flywheel: the benchmark generates volume → evaluator turns volume into signal → verifier improves from confirmed false negatives and grows its regression corpus from confirmed ground truth → improved verifier sharpens benchmark measurements. The evaluator is the connective tissue.

**Acceptance:**
- Running the evaluator against a known-failing test corpus produces structured diagnoses.
- Diagnoses with `verifier_miss` classification produce draft GitHub issues a human can review and submit.
- The benchmark project (separate repo) can consume the evaluator's batch tool and receive structured results.
- Deduplication prevents repeated diagnosis of the same citation across runs.

### Phase 8+ — Roadmap (not in this refactor)

Listed so Claude Code knows what's coming and doesn't architect against future phases:

- Additional resolution backends (e.g., Google Scholar fallback, state-court-specific resolvers)
- Async-first batch processing optimization
- Hosted MCP server with multi-tenant rate limiting
- Surely integration (if the broader litigation system project goes forward)
- Quote-check as a sibling MCP tool sharing the verifier's resolution infrastructure (verify-proposition handles the proposition-support side; see Phase 9)
- **LQ-AI native integration via their MCP-client subsystem.** LQ-AI ([LegalQuants/lq-ai](https://github.com/LegalQuants/lq-ai)) is a self-hosted open-source platform for legal teams. Their roadmap includes an MCP-client subsystem at M5+ (community-driven, not yet committed to a timeline). When that subsystem ships, the already-published skill (in lq-skills, per Phase 6) and the verifier MCP (a standard MCP server) become natively available to LQ-AI deployments with no additional work on this project's side — lq-skills is consumed by LQ-AI as a git submodule and any standard MCP server can be wired into the MCP-client subsystem when it exists. Monitor LQ-AI's MCP-client subsystem development; if their MCP server conventions diverge from standard expectations in ways that would affect this project's MCP design, raise as an open question and adapt. Otherwise, no proactive work required.

### Phase 9 — verify-proposition (renamed from verify-brief)

The atomic proposition-checking primitive. Given a claim (proposition text + cited case ID, where the case ID comes from a prior citation-verifier resolution), return a structured assessment of whether the case supports the claim.

**Why this is its own phase, not part of the current refactor.** verify-brief currently exists in citation-verifier as a sibling tool with its own skill (`.claude/skills/verify-brief/SKILL.md`), library module (`src/citation_verifier/brief_pipeline.py`), CLI subcommand (`python -m citation_verifier verify-brief`), tests, and per-brief workdir convention. It depends on citation-verifier's `VerificationResult` and so will need *mechanical* Phase 1 updates (see Phase 1 sub-task below), but its own Lavern-shaped refactor is a separate design conversation with its own schema spec, its own MCP surface, and its own gate/warning taxonomy.

**Why the rename.** verify-brief conflates two distinct concerns: the *atomic substance check* (does this case support this proposition?) and the *brief-orchestration layer* (parse a whole brief, extract claims via wave1/wave2, merge, generate HTML reports, manage per-brief workdirs). The atomic check is clean, reusable, MCP-shaped, and what downstream consumers actually need. The brief-orchestration layer is messy and bound up with input-format quirks. Phase 9 deliberately scopes to the atomic primitive (verify-proposition) and *defers* the brief-orchestration layer. The brief-orchestration layer can be revisited in a later phase once verify-proposition is stable. Renaming up front signals the scope discipline.

**Why this matters now.** The benchmark project currently re-implements substance checking locally (in `pilot_a/score.py` and `runners/sdk_assessor.py`) because verify-brief doesn't expose a clean atomic API. The moment verify-proposition exposes one, the benchmark collapses its local re-implementation onto it. This is the primary consumer that drives the verify-proposition API design — the benchmark's needs should be pulled forward into the design conversation, not surfaced later as a retrofit.

**What Phase 9 will deliver:**
- A schema spec for the proposition-check result (analogous to but distinct from `VerificationResult`).
- A library implementation in `src/citation_verifier/proposition.py` (renamed from `brief_pipeline.py`).
- An MCP tool: `verify_proposition` (atom: one claim, one assessment).
- A rewritten skill at `.claude/skills/verify-proposition/SKILL.md` (renamed from `verify-brief`).
- A renamed CLI subcommand: `python -m citation_verifier verify-proposition`.
- Updated tests at `tests/test_proposition.py`.

**What Phase 9 explicitly defers:**
- The brief-orchestration layer (wave1/wave2/merge/check_quotes/metadata_check/report from current `brief_pipeline.py`). This can become a Phase 10+ item if it's still wanted; or it can be left to the benchmark and other consumers to do their own multi-claim orchestration on top of `verify_proposition`.
- The HTML report template. Same logic — defer until the orchestration layer is reconsidered.

**Phase 1 sub-task for verify-brief (mandatory now, even though full refactor is Phase 9).** verify-brief is a consumer of `VerificationResult` and so breaks if not updated in Phase 1. Tasks:
- Migrate `brief_pipeline.py` to consume the new `VerificationResult` shape. Wherever it calls into citation-verifier's `verify()`, update to the new result type. Map old-status reads to new-status equivalents. Update any reads of `confidence` or `diagnostics` to use the new fields.
- Update `tests/test_brief_pipeline.py` to match.
- Update the verify-brief skill's `SKILL.md` if it references citation-checker-specific status names or output shapes that have changed.
- Update `__main__.py`'s `verify-brief` subcommand for any user-facing status display changes.
- Do NOT rename to verify-proposition in Phase 1 — that's a Phase 9 task. In Phase 1, verify-brief stays named verify-brief, just updated to consume the new types.

Acceptance for this sub-task: `python -m citation_verifier verify-brief <workdir> --full` produces functionally equivalent output to pre-refactor, and `tests/test_brief_pipeline.py` passes.

---

## 4. Test data inventory

Test fixtures the refactor should preserve and extend:

**Existing in repo:**
- `tests/data/known_real_citations.json` — 5 confirmed real cases (live regression)
- `tests/data/known_fake_citations.json` — 8 confirmed hallucinations
- 103 unit tests in `test_verifier.py` (mocked)
- 30 async-parity tests
- Parser diagnostic tests, CL API limitation tests

**To add as fixtures from skill development:**
- The Koch case (cluster for `857 F.3d 267` displays as "Ricky Koch v. Tote, Incorporated" but real caption is "Koch v. United States") — exemplar for `VERIFIED_DISPLAY_NAME_MISMATCH`
- The Gilliam parallel-cite case (`201 A.D.3d 83, 88–89` with `2021 NY Slip Op 06798` parallel) — exemplar for `VERIFIED_PARTIAL`
- A Menges-style WL cite (`Menges v. Cliffs Drilling, 2000 WL 765082`) — exemplar for the RECAP walking path
- A known `WRONG_CASE` example where reporter resolves to entirely different parties
- A citation that triggers `VERIFICATION_INCOMPLETE` (simulated API error)

These should be inventoried into a structured fixture file before Phase 3, since they're the acceptance criteria for that phase.

---

## 5. Migration strategy for existing consumers

**Decision: clean break.** No legacy result-type compatibility layer.

Rationale: all consumers (CLI, web app, test suite, the skill being rewritten in Phase 6) are within projects the maintainer controls. The total surface to migrate is small. A compatibility layer would preserve the old four-status semantic and create a permanent invitation to skip migration — bad for the project's long-term clarity.

**Migration order during Phase 1:**
1. Migrate type definitions.
2. Migrate `verifier.py` to produce new types.
3. Migrate unit tests in lockstep.
4. Migrate CLI and web app.
5. Update README and docs.

**On the web app specifically.** The existing web app (`web/app.py` plus the three static HTML pages — Retrieve, QC, Debug) consumes the Python library directly: imports `CitationVerifier`, calls `verify()`, gets back a `VerificationResult`, renders it as HTML. When the result shape changes, the web app updates as a consumer like any other. The mechanical changes required are bounded:

- *Status-name handling.* Every place the templates render a status string needs the old→new mapping applied (per Section 2.2 and Phase 1 task list). New statuses that didn't exist in the old taxonomy (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `VERIFIED_DISPLAY_NAME_MISMATCH`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`) need at minimum a label and a color; ideally a tooltip explaining what each means.
- *Richer result fields.* The new `VerificationResult` exposes `resolution_path`, structured `warnings`, and `final_ids` with multiple ID types. The Debug page should surface most of this (that's what a debug view is for). The Retrieve page can stay headline-only. The QC page should show everything.
- *CSV export schema.* If the Debug page exports CSV with status and diagnostic columns, the export schema changes. Mechanical update.

What does *not* change: the FastAPI server structure, the SSE streaming pattern, the batch-of-50 cap, the public-mode flag, the routing, the static HTML/CSS/JS scaffolding. The web app stays a direct library consumer (not an MCP client) — it lives in the same repo and deployment as the library; no reason to add network indirection.

**Functional parity is required; visual polish is not.** Every existing capability must still work after Phase 1. UI enrichment to surface the richer result fields (a nicely rendered resolution_path expandable view, prettier warning rendering, color coding for the new statuses) is follow-on work that can land on its own schedule.

**Note on the web app's evolving strategic role.** If LQ-AI integration becomes a real path (see Phase 8+ in Section 3), the web app's positioning shifts. Today the web app is the primary user-facing surface for verification. In a future where LQ-AI users access the verifier through LQ-AI's chat UI (once their MCP-client subsystem lands), this web app's role narrows from "primary user surface" to "operator and developer tooling surface" — the place to do direct verifier access, debugging, batch operations, and QC review that LQ-AI's general-purpose chat won't surface naturally. That role shift suggests a discipline for future investment: solid functional baseline that exposes the verifier's full surface for power users and debugging = useful permanently. Heavy consumer-grade UI polish on pages a future LQ-AI integration would replace = wasted effort. This is a design-discipline note for the maintainer's future decisions, not a current refactor task.

### Cross-repo consumers: the benchmark project

The benchmark is a separate (private) research project that measures how well various AI models (Gemini, OpenAI, Anthropic) can find real cases that support a given legal proposition. It produces (model, proposition, candidate_citation, verifier_result) tuples at volume and uses citation-verifier to confirm whether each candidate citation resolves to a real case — distinguishing actual hallucinations from real-but-CL-uncovered cases is the benchmark's central measurement problem. It also currently re-implements substance checking locally because verify-brief doesn't yet expose a clean atomic API (see Phase 9). This project is the heaviest external consumer of citation-verifier and the design principle in 1.6 about respecting cross-repo consumers exists specifically because of it.

The benchmark consumes citation-verifier as a tag-pinned git dependency:

```
# Benchmark's requirements.txt
citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.2.0
```

The benchmark deliberately keeps this dependency out of `[project.dependencies]` in `pyproject.toml` (so the git URL doesn't leak into package metadata) and relies on `requirements.txt` as the source of truth.

The benchmark reaches into citation-verifier's internals, not just `verify()`. Imports include:

- `verifier.CitationVerifier` — the primary verification entry point
- `parser.parsed_citation_from_eyecite`, `parser.parse_citation` — citation parsing
- `name_matcher.CaseNameMatcher` — name similarity scoring
- `client.CourtListenerClient`, `client.AsyncCourtListenerClient` — both sync and async CL API wrappers
- `models.VerificationStatus`, `models.VerificationResult` — type definitions
- `court_map.lookup_court_id` — court ID resolution

Used across multiple benchmark production paths: `runners/build_dataset.py`, `runners/score.py`, `runners/score_gold_pairs*.py`, `runners/red_audit_fulltext.py`, `runners/backfill_v1_court_metadata.py`, `pilot_a/build_fresh_dc_sample.py`, `pilot_a/score.py`. The benchmark's own CLAUDE.md acknowledges this consumption pattern explicitly as "published library API, but with reach-through into internals."

**The migration model: tag-pin staging.** The tag-pin gives natural staging that decouples citation-verifier's release schedule from the benchmark's. The refactor's release model:

1. Phases 1+ land on citation-verifier under a new tag (suggest `v0.3.0` for the first refactor cut; further alpha/beta tags as needed during the refactor).
2. The benchmark stays pinned to `v0.2.0` and continues to function on the old API throughout the refactor. No coordination required for citation-verifier's branches and commits to land.
3. When the refactor is far enough along that the benchmark's migration is worth doing, the benchmark gets its own branch. On that branch, the benchmark consumes citation-verifier via editable install (`pip install -e ../citation-verifier`) from a sibling working copy. Benchmark migration to the new API happens on that branch, iterating against an in-progress refactor branch on citation-verifier's side.
4. When both sides are ready, citation-verifier tags `v0.3.0`, the benchmark bumps its `requirements.txt` pin to `v0.3.0`, and the dual-track branches merge in close succession.

The editable-install dev loop is the primitive that makes step 3 practical. Without it, every iteration during dual-track migration would require a tag bump. The doc names this explicitly because it's central to the workflow even though it's not part of either project's runtime story.

**Internal-API change discipline during the refactor.** Per design principle 1.6: the refactor touches `models.py` substantially (the schema rewrite) and `verifier.py` substantially (instrumentation, new classification logic). Other modules — `parser`, `name_matcher`, `client` (both sync and async surfaces), `court_map` — should not change their public APIs unless a specific refactor task genuinely requires it. If a Phase 3 implementation discovers it needs to change a signature in one of these modules, that's a flag-and-discuss moment, not a silent change. Every public-API change to these modules gets a changelog entry with a migration note for cross-repo consumers.

---

## 6. Non-goals

Things this refactor is explicitly not trying to do. Surface as questions if any of these become tempting during implementation:

- **Not adding new resolution backends.** No Google Scholar, no Westlaw scraping, no state-court-specific clients. The fallback ladder stays at the current four-plus-caption-investigation set.
- **Not changing the caching layer.** Existing file cache stays. Schema changes mean cache must be invalidated once on first run, but the caching mechanism is not being redesigned.
- **Not introducing async if it isn't already there.** Current async support is preserved; no new async-first APIs.
- **Not building a UI.** The web app gets compatibility updates only.
- **Not implementing proposition-checking or quote-checking.** Those are downstream tools with their own architectures and their own design docs. They will consume this verifier's `FinalIds` for their input, but their implementation is not in scope.
- **Not implementing the benchmark project's side of the flywheel.** The evaluator's MCP surface (`diagnose_not_found_batch`) is built as a public interface; the benchmark's consumption logic is built in the benchmark's own repo.

---

## 7. Open questions

Decisions the maintainer hasn't made yet. Claude Code should surface these rather than silently resolving them.

- **How aggressive should the evaluator's diagnostic step be?** Specifically: when a citation looks "real but obscure," how hard should the model try to verify it before classifying? More effort = better signal, more cost.
- **Should `resolution_path` entries include raw API responses or just summaries?** Raw responses are more debuggable; summaries are smaller. Tentative answer: summaries by default, with a debug mode that captures raw responses.
- **Should the MCP server be local-only or designed for hosting?** Local-only is simpler and matches the current development setup. Hosted opens up integration with the broader Claude ecosystem. Tentative answer: local-only for this refactor; hosting can be a Phase 8 follow-on.
- **What's the right granularity for the gates enum?** The initial set in Section 2.7 covers the obvious cases. Real usage may surface more specific gates (e.g., "fail if any VERIFIED_PARTIAL has the primary reporter being a federal reporter," etc.). Tentative answer: start with the initial set, accept additions only with strong use-case justification.
- **Should `inspect_citation_format` live on the same MCP server as the verifier, or be a separate tool?** Same server is simpler. Separate is cleaner architecturally. Tentative answer: same server, separate tool surface — the implementation overlap is too high to split into separate servers.
- **For Phase 6's skill rewrite: should the skill's web-search-augmented `NOT_FOUND` interpretation be its own skill, or stay inside `citation-checker`?** Separation would let other workflows reuse the interpretation logic. Bundling keeps the skill cohesive. Tentative answer: bundled for v1; revisit if a second consumer of the interpretation logic emerges.
- **How much should the refactor commit to preserving citation-verifier's internal APIs (`parser`, `name_matcher`, `client`, `court_map`) for cross-repo consumers like the benchmark?** Tight preservation reduces the benchmark's migration cost but constrains the refactor. Loose preservation gives the refactor more freedom but pushes more work onto the benchmark side. Tentative answer (already encoded in design principle 1.6): preserve where reasonable; document any breaks in the changelog with migration notes; rely on tag-pin staging (see Section 5) for coordinated upgrades. Re-examine if the refactor genuinely needs to break one of these modules' APIs and the migration cost looks high.
- **Should the verifier MCP be designed for self-hosted deployment only, or should we also support a hosted-service mode?** A hosted service would let users connect without managing their own CourtListener API token (solving the well-known "users don't know where their CL key is" friction), but it requires real per-user auth infrastructure: an OAuth flow against CourtListener (or a proxy), per-user token management, rate-limit isolation across tenants, and the operational burden of running a multi-tenant service. None of that is in this refactor's scope. Tentative answer: self-hosted only for v1. The verifier MCP is designed to run in the user's own environment (Claude Desktop, Claude Code, a developer's machine, or a deployment they control) with a CL token they've configured. A hosted version is a separate future project with its own design conversation, not a Phase 8+ item to silently add to this roadmap.

---

## 8. Implementation philosophy notes for Claude Code

These are reminders, not new content. When in doubt during implementation:

- **Check decisions against the design principles in Section 1.5.** If a proposed change violates one of them, surface as an open question.
- **Never let the model own the procedure.** If a temptation arises to "have the model figure it out" inside the verifier code, that's a sign the logic belongs in the skill, not in the verifier — or the schema needs to expose a richer signal so the model can figure it out at the consumer layer.
- **Never editorialize in the verifier.** If a status feels like it would be "more informative" if we added a heuristic, that's a sign the heuristic belongs as an auxiliary signal (or in the skill), not as a status.
- **The schema is the contract.** Changes to the schema during implementation require updating this document. Document drift between code and spec is the failure mode that kills refactor projects of this shape.
