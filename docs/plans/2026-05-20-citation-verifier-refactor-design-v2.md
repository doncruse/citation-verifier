# Citation Verifier — Refactor Design (Phases 1–4) + Roadmap (Phases 5+)

**Status:** Draft for review (v2 — incorporates decisions from the 2026-05-20 review pass)
**Audience:** Future contributors, Claude Code during implementation
**Purpose:** Specify the refactor that converts citation-verifier from a Python library + parallel Claude skill into a structured library with the schema, instrumentation, classification, and gates needed to support an MCP surface and a thin judgment-layer skill on top.

**Scope discipline.** The refactor proper is Phases 1–4 — that's one coherent deliverable that produces a refactored library. Phases 5+ are roadmap items built on top of the refactored library; each gets its own design doc when it's time to build. This doc fully specifies Phases 1–4 and sketches Phases 5+ at the level of design intents the refactor should not foreclose.

> Prior documents: `2026-05-20-citation-verifier-refactor-design.md` (v1) and `2026-05-20-citation-verifier-refactor-design-review.md` (critique pass). This file (v2) is what the implementation should follow.

---

## 1. Context and motivation

### What exists today

Two artifacts, developed in parallel, both attempting to solve the same problem from opposite directions:

A Python library (`src/citation_verifier/`) that owns a deterministic verification pipeline — extraction via eyecite, resolution via CourtListener's Citation Lookup API, fallback via Opinion Search, fallback via RECAP Search. It returns a flat `VerificationResult` with one of four statuses (`VERIFIED`, `LIKELY_REAL`, `POSSIBLE_MATCH`, `NOT_FOUND`), a confidence score, and a diagnostics list. The library has 103 mocked unit tests, a live regression suite against a known-real corpus, a file cache, and a CLI and web app as consumers.

A Claude skill (`citation-checker`) that teaches a model how to orchestrate the CourtListener MCP tools to do roughly what the library does, but with substantially more nuance: a seven-status taxonomy in its own prose, ingestion from four input shapes (Word context, uploaded PDF, pasted text, CourtListener URL); a full-caption investigation procedure that runs on case-name mismatch warnings; a silent-partial-verification check; environment-adaptive output formatting; an explicit handoff protocol to downstream skills via captured IDs.

The two artifacts overlap heavily. Both run the fallback ladder. Both classify results. Both produce structured output. But they have different statuses, different coverage of edge cases, different consumers, and neither one is finished.

### What's wrong with the current shape

The skill has grown procedural complexity that wants to be code. A 239-line skill that walks the model through a multi-step ladder with branching logic is asking a stochastic system to be deterministic. The model can skip a step, reorder steps, decide a step doesn't apply, or do steps 1–4 cleanly and silently bail on step 5. Failures are silent. The audit trail is whatever the model chose to surface. The procedure is real only to the extent the model felt like making it real on that run.

This is not a "the model needs better prompting" problem. Even if the model followed every instruction perfectly every time, the procedure would still not be *auditable*, *gate-able*, or *machine-checkable* — because those are properties of code, not of model output. Procedural validity is a category that stochastic systems cannot provide by being more compliant. It can only be provided by removing the stochasticity from the procedural layer, which means moving the procedure into code and reserving the model for the judgment layer on top.

The Python repo has classification nuance that's lagged behind the skill's development. The four-status taxonomy collapses meaningful distinctions (partial verification, RECAP-only verification, the WRONG CASE category that's the load-bearing hallucination signature) into a coarser scheme that doesn't tell downstream consumers what they need to know.

The skill is doing code-shaped work badly. The repo is doing classification-shaped work coarsely. They share a job and a maintainer and increasingly share each other's bugs.

### The Lavern-shaped reorganization

Lavern ([github.com/AnttiHero/lavern](https://github.com/AnttiHero/lavern)) is an Apache-2.0 open-source multi-agent legal document review system: 67 specialist AI agents debate findings against a parsed document, with code-enforced gates (a grounding verifier, an evaluator gate, a 10-pass verification pipeline) that mechanically check the agents' work before findings can ship. Its architectural insight — the one this refactor borrows — is the strict separation between *prompts that express agent roles* and *code that enforces procedural rules*. The agents do the judgment work; deterministic gates fail closed on findings that don't meet the rules. The agent literally cannot ship a finding without evidence because the verifier, which is not a prompt, will reject it. This refactor applies the same pattern to citation verification: a deterministic Python pipeline owns the procedure, the model owns the judgment over the pipeline's structured output, and gates between them enforce what can pass.

**The pattern is borrowed; the gate density is not.** Lavern's architecture has many gates because it's verifying outputs from many specialist agents — each agent's findings need their own mechanical check. This verifier has fewer gates because it's verifying outputs from a deterministic Python pipeline plus a single skill consumer. There's one internal gate (API errors must not silently degrade to NOT_FOUND; see §2.8) and a configurable set of caller-policy gates (see §2.7). The principle is what transfers — code owns procedure, model owns judgment, schema is the contract — not the gate count.

The animating principle, borrowed from Lavern's gate architecture:

> **Code owns procedure. The model owns judgment. The schema is the contract between them.**

The verifier's gates aren't prompts asking the agent to check its work — they're code that runs on the agent's output and fails closed. Applied here: the Python pipeline runs the procedure deterministically and produces a structured intermediate; the skill consumes that intermediate and does only the judgment-shaped work that genuinely requires a model.

This split lets each substrate do what it's good at:

- **Code is good at:** running every step in order, never skipping, producing audit trails as a byproduct, handling API errors structurally, applying scoring algorithms consistently, classifying into a finite taxonomy, batching at scale.
- **The model is good at:** interpreting unresolved results, reasoning over open evidence (web searches, secondary sources, plausibility heuristics), adapting presentation to context, prioritizing which findings matter for a particular brief, explaining implications to humans.

The repeated failure mode the refactor must prevent: the verifier sliding back into the same fuzziness problem the skill had. Once the verifier starts inventing categories it can't justify from evidence, it's doing model-shaped work in code-shaped infrastructure — the worst of both worlds.

### Stated design principles

These should be invoked when resolving ambiguous decisions during implementation. If a decision is being made in tension with these, surface it as an open question rather than silently resolving against them.

1. **Code owns procedure. The model owns judgment. The schema is the contract.** Every implementation decision should be checkable against this.
2. **The verifier reports what it observed and what procedures completed; it does not editorialize about meanings the evidence doesn't support.** Auxiliary signals are facts the verifier can vouch for. Status is a verdict the verifier is willing to defend. Anything in between — heuristic guesses, probabilistic classifications, vibes — gets pushed up to the consumer.
3. **Procedure must be unskippable.** If a step in the pipeline is required for a status's semantic meaning, the code runs that step; the model is not asked to remember to run it.
4. **The structured result is the handoff.** Downstream consumers (skills, other tools, the diagnostic runner) must be able to act on the result object alone without re-running procedural logic to extract what they need.
5. **Fail-closed only at the boundary of verifier integrity.** The one internal gate is "API errors must not become silent NOT_FOUND." Beyond that, gates are caller-policy, not verifier policy.
6. **Respect cross-repo consumers.** Citation-verifier's modules (`parser`, `name_matcher`, `client`, `court_map`, `models`) are consumed by external projects — most notably the benchmark project (`~/Projects/case-law-proposition-benchmark`), which reaches deep into internals. The refactor commits to changing only those APIs the refactor's design genuinely requires. Changes to module public APIs must be documented in the changelog with migration notes so cross-repo consumers can plan their upgrades. Gratuitous churn in stable surfaces is to be avoided.

---

## 2. Schema specification

The load-bearing section. This is the contract between the verifier and every consumer (CLI, web app, future MCP clients, the skill, the future diagnostic runner, the benchmark project). Once stable, the Python implementation is constrained, future MCP surfaces are constrained, and the skill's consumption pattern is constrained.

### 2.1 The `VerificationResult` object

```
VerificationResult {
  citation_as_written: string             # The exact input string
  parsed_citation: ParsedCitation | null  # Eyecite/parser output, null if unparseable
  status: Status                          # See 2.2
  final_ids: FinalIds                     # See 2.4
  resolution_path: ResolutionPathEntry[]  # See 2.5
  warnings: Warning[]                     # See 2.6
  gates_failed: GateFailure[]             # See 2.7, empty unless gates specified
  timing: TimingRecord                    # API latency, total elapsed
  cache_hit: bool                         # Whether result was served from cache
}
```

Every field is mandatory in the result object. Fields that don't apply to a given result are explicitly nullable (with type `| null`) rather than absent. This is a hard rule — consumers must be able to introspect any field on any result without `KeyError`-style failures.

**On the missing top-level `confidence` field.** v1 of this design had a top-level `confidence: float | null`. v2 removes it. Confidence is a per-stage concept, not a per-result concept: the math that produces a score is per-stage (name-match similarity in opinion_search, weighted multi-component score in fuzzy fallback, etc.); the decisions it informs are per-stage (which candidate to pick within a stage, when to fall back to the next stage). Carrying a top-level scalar forces incomparable scores onto one scale across statuses (VERIFIED, NOT_FOUND, WRONG_CASE), which is the vestigial behavior of the old taxonomy. v2 moves the field to `ResolutionPathEntry.confidence` (see §2.5) where its meaning is honest. Consumers wanting a headline confidence for a result use the documented accessor in §2.5.

### 2.2 Status taxonomy

Six states, finite, enumerated. Replaces the existing four-status Python taxonomy entirely. Migration is a clean break — see Section 5 for the consumer-update plan.

**Resolved-clean states:**

`VERIFIED` — Citation resolved cleanly via the primary lookup. Case name matches (or any mismatch was investigated and turned out to be pure formatting noise or a CL display-name data bug; in those sub-cases a warning fires but status stays VERIFIED). All IDs captured.

`VERIFIED_PARTIAL` — A parallel citation resolved but the primary reporter cited in the brief did not. Example: brief cites `201 A.D.3d 83` with parallel `2021 NY Slip Op 06798`; the slip-op cite resolves, the A.D.3d reporter is not in CL's index. Authoritative for the case's existence but the cited reporter is unconfirmed.

`VERIFIED_VIA_RECAP` — The opinion is not in CL's `opinions` index, but the RECAP archive contains the actual court filing. Common for unreported district-court orders cited via Westlaw. Downstream consumers needing opinion text pull from the RECAP-document endpoint (see §2.4 `text_source`).

`VERIFIED_DOCKET_ONLY` — The docket exists in CL but has no RECAP documents and no opinion text. The case is real; CL has no filings. Lowest-confidence "verified" state.

**Resolved-but-wrong state:**

`WRONG_CASE` — The reporter resolves to a real case, but the full caption confirms it is a completely different case than the brief named. High severity. This is the classic hallucination signature where a model invents a plausible-looking reporter and attaches it to a made-up case name. Author cannot rely on the citation.

**Unresolved states:**

`NOT_FOUND` — Every applicable resolution path ran to completion. None resolved. The verifier asked everything within its competence and CL has nothing. Could mean the case is fabricated, could mean the case is real but outside CL's coverage, could mean the query failed in a way the verifier cannot detect — the verifier does not pretend to distinguish.

`VERIFICATION_INCOMPLETE` — One or more resolution paths failed to complete due to API errors, rate limits, timeouts, or other infrastructure failures. The verifier cannot give an authoritative answer because it could not fully ask. Never collapse this into `NOT_FOUND`; that compression produces malpractice-shaped silent false negatives.

### 2.3 Status-vs-warning rule, and why these six and not more

**The rule.** `status` answers "what's the relationship between this citation and reality?" `warnings` are facts about *how the verifier reached its answer* or *quirks the consumer should know about the underlying data*. A useful operational test: would removing the underlying fact change the verdict? If yes, it's status; if no, it's warning.

Applied to the dropped seventh status, `VERIFIED_DISPLAY_NAME_MISMATCH` (in v1): the citation *is* verified. CL's display-name bugginess does not change the verdict; it's a quirk of CL's metadata that a careful consumer should know about. By the rule, it's a warning (`cl_display_name_data_bug`), not a status. v2 drops the status; the information lives in `warnings` only.

**On the previous Python statuses `LIKELY_REAL` and `POSSIBLE_MATCH`.** These are *not* preserved. They were trying to encode procedural information (which fallback path resolved this) as confidence bands. That information is now in `resolution_path` (which stage resolved) and the granular `VERIFIED_*` states (how it was resolved). The number that distinguished them lives in per-stage `confidence` (see §2.5). Specifically:

- The information the old four-status taxonomy encoded via confidence bands is preserved, split across two places: which stage resolved the citation (now visible in `resolution_path`) and how well it resolved within that stage (now in the stage's `confidence` field). The top-level scalar that conflated these is removed.

Specifically *not* added to the unresolved branch: a `FABRICATED_LIKELY` or `HALLUCINATION_PROBABLE` status. From inside CourtListener, with the tools available, the verifier cannot honestly distinguish fabricated from coverage-gap from search-malformed. Surfacing that distinction is the skill's job (with web search and judgment) or the diagnostic runner's job (with model-driven diagnosis). The verifier reports `NOT_FOUND` and stops.

### 2.4 The `FinalIds` object

```
FinalIds {
  cluster_id: int | null
  opinion_id: int | null
  docket_id: int | null
  recap_document_id: int | null
  absolute_url: string | null
  text_source: TextSource | null   # "opinion_plain_text" | "opinion_html" | "recap_document" | null
}
```

Required fields with explicit nullability. The `text_source` field tells downstream consumers (proposition-check, quote-check) where to retrieve the opinion text and which endpoint owns it.

- For `VERIFIED`, `VERIFIED_PARTIAL`: expect populated `cluster_id` and `opinion_id` with `text_source: "opinion_plain_text"` (or `"opinion_html"` if `plain_text` was empty and the client fell back per the canonical `_extract_opinion_text` chain).
- For `VERIFIED_VIA_RECAP`: expect populated `recap_document_id` and `docket_id` with `text_source: "recap_document"`. Consumers fetch text from the `/api/rest/v4/recap-documents/{id}/` endpoint's `plain_text` field (RECAP documents are OCR'd; their plain_text field is the canonical text source). PDF download is a fallback only when OCR'd `plain_text` is empty — that's a client implementation detail, not something the status communicates.
- For `VERIFIED_DOCKET_ONLY`: expect populated `docket_id` only; `text_source` is `null` (no document text exists in CL).
- For `WRONG_CASE`: the IDs point to the case the reporter *actually* resolves to (useful context even though the citation is unusable as written). `text_source` is populated as for `VERIFIED`.
- For `NOT_FOUND` and `VERIFICATION_INCOMPLETE`: all IDs null; `text_source` null.

### 2.5 The `ResolutionPathEntry` schema

The resolution path is the verifier's audit trail — every stage attempted, in order, with its query, its result, and its local verdict. This is what consumers inspect when they need to know not just what the verifier concluded but what it did to get there.

```
ResolutionPathEntry {
  stage: StageName               # Enumerated: see below
  query: dict                    # The structured query made (parameters)
  raw_response_summary: dict     # Free-form per stage; see below
  verdict: StageVerdict          # "resolved" | "no_match" | "partial" | "errored" | "skipped"
  confidence: float | null       # 0.0–1.0; see below
  notes: string | null           # Optional diagnostic, e.g., "rate-limited, retried 2x"
  elapsed_ms: int
}
```

Stage names (initial set; new stages can be added without schema change):

- `citation_lookup` — CourtListener Citation Lookup API
- `opinion_search` — fuzzy case-name search via Search API
- `recap_document_search` — `type=rd` search in RECAP documents
- `recap_docket_search` — `type=r` search in dockets with RECAP content
- `plain_docket_search` — `type=d` search in all dockets
- `caption_investigation` — triggered on mismatch warnings; sub-pipeline of cluster → docket → opinion text lookups

A stage entry is recorded for every stage *attempted*, in order. Stages not attempted (because an earlier stage resolved, or because the citation didn't qualify) are not in the path. This means the path's length is itself a signal about how hard the verifier had to work to reach its conclusion.

**`raw_response_summary` shape.** Free-form per stage; consumers should not depend on shape across stages. A consumer reading `path[2].raw_response_summary` must first inspect `path[2].stage` to know what keys to expect. The verifier owns the shape per stage; cross-stage shape stability is explicitly not promised.

**`confidence` semantics.** Score produced by this stage, on a 0.0–1.0 scale, with stage-specific meaning. Populated when the stage's procedure produces a meaningful score (e.g., name-match similarity in `opinion_search`; weighted multi-component score in fuzzy fallback). Omitted (`null`) when the stage is binary (e.g., `citation_lookup` either resolves the reporter or doesn't; there is no in-between to score). Consumers should not compare confidence values across stages — a 0.78 from `opinion_search` and a 1.0 from `citation_lookup` measure different things.

**Per-stage confidence thresholds.** Per-stage thresholds govern when a stage claims resolution vs. falls through to the next stage. The specific thresholds preserved from the current pipeline (notably the 0.40 floor below which `opinion_search` falls through rather than claiming resolution) carry forward unchanged unless Phase 3 surfaces evidence to retune. Implementer note: keep the thresholds named constants in `verifier.py`, not magic numbers.

**Headline-confidence accessor for consumers.** The headline-confidence accessor walks `resolution_path` in reverse and returns the `confidence` of the first entry whose verdict is `resolved` or `partial`. This is the one-line accessor consumers should use when they want a single "how good was this match" number per result. Implementations are encouraged to expose this as a property on the result object so consumers don't reinvent the walk.

### 2.6 The `Warning` schema

Warnings are facts about the resolution that a careful consumer should know but that do not invalidate the result and do not change the status. They are not gates. They are not errors. They are notes.

```
Warning {
  category: WarningCategory
  message: string                # Human-readable detail
  details: dict | null           # Optional structured context
}
```

Enumerated warning categories (closed set; see amendment workflow below):

- `silent_partial_verification` — primary reporter not in CL, only parallel cite resolved (paired with status `VERIFIED_PARTIAL`)
- `cl_display_name_data_bug` — CL's `case_name` differs from the real caption confirmed by the full-caption investigation; citation is fine, CL metadata is the issue
- `court_mismatch_noted` — court in citation differs from CL record; case-name and date match
- `date_close_not_exact` — year differs slightly (+/- 1) from CL record
- `name_formatting_noise` — case name differs from CL purely on abbreviation/punctuation; full-caption investigation confirmed it's the same case
- `unparseable_citation` — eyecite could not parse cleanly; verifier used regex fallback
- `extraction_contamination_detected` — surrounding text may have contaminated name extraction
- `cl_duplicate_clusters` — caption investigation found that CL has multiple clusters matching the same case (e.g., a case ingested twice with different cluster IDs). The verifier emits VERIFIED but the warning names both candidate clusters; consumers should not assume the picked cluster is uniquely canonical. Added Phase 3 (2026-05-22); see CHANGELOG.md.
- `wrong_page_number` — caption investigation found the cited case at a different reporter page than the brief cited. The case is real and at the cited volume + reporter, but at a different page number than the citation claims. Hallucination signal. Added Phase 3 (2026-05-22); see CHANGELOG.md.

**Amendment workflow.** The closed set is closed against silent expansion, not against considered expansion. Phase 3 will surface warning categories not anticipated above; when it does, the addition is a schema change with a changelog entry and a minor-version bump. Removals are a major-version bump (consumers may key on category names). New categories should follow the same rule as initial ones: facts about *how the verifier reached its answer* or *quirks the consumer should know about the underlying data* — not editorialization, not heuristic guesses.

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

Initial gate set (closed; additions follow the same amendment workflow as warnings):

- `no_not_found` — fails if status is `NOT_FOUND`
- `no_wrong_case` — fails if status is `WRONG_CASE`
- `no_verification_incomplete` — fails if status is `VERIFICATION_INCOMPLETE`
- `no_partial_verification` — fails if status is `VERIFIED_PARTIAL`
- `require_primary_reporter_resolved` — fails if `VERIFIED_PARTIAL` (or specifically configured variants)
- `require_caption_investigation_on_mismatch` — fails if any mismatch warning fired but `caption_investigation` stage didn't run

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

### 2.10 Note on `ParsedCitation`

`ParsedCitation` (defined in `models.py`) already carries `year`, `month`, `day`, and `docket_number`. The refactor adds one field: `ecf_document_number: str | None` (or similarly named), so the parser can capture explicit document/ECF numbers when a citation supplies them (e.g., `ECF No. 42` or `Doc. 17`). This is a Phase 1 sub-task — see §3 Phase 1. Other `ParsedCitation` fields stay unchanged.

---

## 3. The refactor (Phases 1–4)

Phased, with concrete acceptance criteria. Phases are dependent in order; later phases assume earlier phases' acceptance criteria are met. **Phase 4 acceptance = "the refactor is done."** Everything after is roadmap (§7), built on top of the refactored library.

### Phase 1 — Schema and types

Pure data structure work. Define the new types in `models.py` per Section 2. No verification logic changes yet.

**Tasks:**
- Define `Status` enum with the six states (§2.2).
- Define `VerificationResult`, `FinalIds`, `ResolutionPathEntry`, `Warning`, `GateSpec`, `GateFailure`, `BatchVerificationResult`, supporting enums.
- Add `ecf_document_number: str | None` to `ParsedCitation` (§2.10). Update the parser to populate it where the underlying text supplies one; otherwise leave `None`.
- Migrate `verifier.py` and tests to construct and consume the new types. Initial mapping from existing four-status taxonomy: `VERIFIED → VERIFIED`, `LIKELY_REAL → VERIFIED` (the resolving stage carries the confidence score in `resolution_path`), `POSSIBLE_MATCH → VERIFIED` (same, with the lower confidence appearing at the stage level), `NOT_FOUND → NOT_FOUND`. The richer states (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`) are not yet *produced* in this phase; only their type definitions exist.
- Move all confidence scoring into the per-stage path entries. Remove top-level `confidence` from any code path that reads it; consumers that need a headline number use the §2.5 accessor.
- Update consumers (CLI, web app, test suite) to use new types. Clean break, no compatibility layer.

**Phase 1 sub-task for verify-brief.** verify-brief is a consumer of `VerificationResult` and so will break if not updated. Tasks:
- Migrate `brief_pipeline.py` to consume the new `VerificationResult` shape. Wherever it calls into citation-verifier's `verify()`, update to the new result type. Map old-status reads to new-status equivalents. Update any reads of `confidence` or `diagnostics` to use the new fields (per-stage confidence via the accessor; warnings replace diagnostics).
- Update `tests/test_brief_pipeline.py` to match.
- Update the verify-brief skill's `SKILL.md` if it references citation-checker-specific status names or output shapes that have changed.
- Update `__main__.py`'s `verify-brief` subcommand for any user-facing status display changes.
- Do NOT rename to verify-proposition in Phase 1 — that's a roadmap item (§7). In Phase 1, verify-brief stays named verify-brief, just updated to consume the new types.

**Acceptance:**
- All existing unit tests pass against new type signatures.
- All async-parity tests pass.
- Live regression suite (`test_false_negatives.py`) passes against new types.
- CLI and web app both function with new result shape.
- `python -m citation_verifier verify-brief <workdir> --full` produces functionally equivalent output to pre-refactor; `tests/test_brief_pipeline.py` passes.

### Phase 2 — Resolution path instrumentation

Modify pipeline stages to emit structured `ResolutionPathEntry` records. No new statuses, no new logic, just instrumentation.

**Tasks:**
- Wrap each stage in `verifier.py` to produce a path entry on entry and exit.
- Capture query parameters, response summary (per-stage shape; see §2.5), verdict, per-stage confidence where meaningful, elapsed time, notes.
- Ensure path is captured even on error / early-exit paths.
- Add path-presence and path-shape tests.

**Acceptance:**
- Every `VerificationResult` produced has a non-empty `resolution_path`.
- Replaying any cached result (or any test fixture) reproduces the same path.
- New tests verify path shape for each fallback scenario.

### Phase 2.5 — Corpus assembly

Build the fixture corpus *before* Phase 3 implementation, not during. Phase 3's acceptance criteria depend on having a corpus rich enough to validate the new statuses across edge cases; the v1 design's ~10 fixtures are not enough.

**Source material.** The maintainer's benchmark project (`~/Projects/case-law-proposition-benchmark`) and its offshoot have ~200 ground-truthed citations covering many edge cases relevant to the new taxonomy. This is the primary source for Phase 2.5.

**Tasks:**
- Survey the benchmark and its offshoot for citations matching each of the six new statuses (and meaningful sub-cases — caption-investigation paths, parallel-cite paths, RECAP paths, docket-only paths, wrong-case paths, infrastructure-failure paths for `VERIFICATION_INCOMPLETE`).
- Build a structured fixture file (suggested: `tests/data/refactor_corpus.json` or split per status) cataloging the curated citations with: input string, expected status, expected key warnings, expected resolving stage, ground-truth IDs where applicable, a one-line rationale for inclusion.
- Aim for 5–10 fixtures per status; ~40–60 total. Some statuses have richer edge-case surface (`VERIFIED` with mismatch warnings; `VERIFIED_PARTIAL` with various parallel-cite shapes) and deserve more.
- Document the corpus's selection criteria so future additions follow the same shape.

**Acceptance:**
- The fixture file exists and is loaded by Phase 3's tests.
- Each of the six statuses has at least five fixtures.
- The fixtures cover, at minimum, the named exemplars in §4 (Koch warning path, Gilliam parallel-cite, Menges WL cite, a WRONG_CASE example, a simulated `VERIFICATION_INCOMPLETE`).

### Phase 3 — Status taxonomy migration

Implement the full six-status taxonomy. Migrate classification logic from the skill's prose into Python.

**Tasks:**
- Implement detection logic for `VERIFIED_PARTIAL` (silent partial verification check).
- Implement detection logic for `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`.
- Implement the full-caption investigation as a method (`_investigate_caption`), triggered automatically on any case-name mismatch warning. The method runs the three-step lookup (cluster `case_name_full` → docket `case_name` → opinion `plain_text` first 500 chars) and classifies the mismatch. The classification populates warnings on the result (`name_formatting_noise`, `cl_display_name_data_bug`) or escalates to status `WRONG_CASE`.
- Implement `WRONG_CASE` classification path.
- Populate `warnings` per §2.6.

**Acceptance:**
- The Phase 2.5 corpus produces the expected status for each fixture.
- Specific named exemplars from §4 produce the correct six-status result.

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

**The refactor is complete here.** The library has the new schema, instrumentation, classification, and gates. It is ready to be consumed by an MCP server, the refactored skill, and the diagnostic runner — none of which are in this refactor. Tag the release at the end of Phase 4 (suggest `v0.3.0`).

---

## 4. Test data inventory

Test fixtures the refactor should preserve and extend. Phase 2.5 (above) is the formal corpus-assembly phase; this section names the existing fixtures and the must-include exemplars.

**Existing in repo:**
- `tests/data/known_real_citations.json` — 5 confirmed real cases (live regression)
- `tests/data/known_fake_citations.json` — 8 confirmed hallucinations
- 103 unit tests in `test_verifier.py` (mocked)
- 30 async-parity tests
- Parser diagnostic tests, CL API limitation tests

**Must-include exemplars (drawn from skill development; structured into the Phase 2.5 corpus):**
- The Koch case (cluster for `857 F.3d 267` displays as "Ricky Koch v. Tote, Incorporated" but real caption is "Koch v. United States") — exemplar for the `cl_display_name_data_bug` warning on a `VERIFIED` result (full-caption investigation confirms it's the right case; CL's display string is buggy).
- The Gilliam parallel-cite case (`201 A.D.3d 83, 88–89` with `2021 NY Slip Op 06798` parallel) — exemplar for `VERIFIED_PARTIAL`.
- A Menges-style WL cite (`Menges v. Cliffs Drilling, 2000 WL 765082`) — exemplar for `VERIFIED_VIA_RECAP` (the RECAP walking path).
- A known `WRONG_CASE` example where the reporter resolves to entirely different parties (the full-caption investigation escalates the mismatch).
- A citation that triggers `VERIFICATION_INCOMPLETE` (simulated API error).

The benchmark project (`~/Projects/case-law-proposition-benchmark`) is the primary source for the broader Phase 2.5 corpus beyond these named exemplars.

---

## 5. Migration strategy for existing consumers

**Decision: clean break.** No legacy result-type compatibility layer.

Rationale: all consumers (CLI, web app, test suite, the skill being rewritten in Phase 6 of the roadmap, the benchmark project) are within projects the maintainer controls. The total surface to migrate is small. A compatibility layer would preserve the old four-status semantic and create a permanent invitation to skip migration — bad for the project's long-term clarity.

**Migration order during Phase 1:**
1. Migrate type definitions.
2. Migrate `verifier.py` to produce new types.
3. Migrate unit tests in lockstep.
4. Migrate CLI and web app.
5. Migrate verify-brief consumer (per Phase 1 sub-task).
6. Update README and docs.

**On the web app specifically.** The existing web app (`web/app.py` plus the three static HTML pages — Retrieve, QC, Debug) consumes the Python library directly: imports `CitationVerifier`, calls `verify()`, gets back a `VerificationResult`, renders it as HTML. When the result shape changes, the web app updates as a consumer like any other. The mechanical changes required are bounded:

- *Status-name handling.* Every place the templates render a status string needs the old→new mapping applied (per §2.2 and Phase 1 task list). New statuses that didn't exist in the old taxonomy (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`) need at minimum a label and a color; ideally a tooltip explaining what each means.
- *Richer result fields.* The new `VerificationResult` exposes `resolution_path`, structured `warnings`, and `final_ids` with multiple ID types. The Debug page should surface most of this (that's what a debug view is for). The Retrieve page can stay headline-only. The QC page should show everything.
- *Headline-confidence accessor.* If any page rendered top-level `confidence`, switch to the §2.5 accessor (walks `resolution_path` in reverse and returns the first `resolved`-or-`partial` entry's confidence).
- *CSV export schema.* If the Debug page exports CSV with status and diagnostic columns, the export schema changes. Mechanical update.

What does *not* change: the FastAPI server structure, the SSE streaming pattern, the batch-of-50 cap, the public-mode flag, the routing, the static HTML/CSS/JS scaffolding. The web app stays a direct library consumer (not an MCP client) — it lives in the same repo and deployment as the library; no reason to add network indirection.

**Functional parity is required; visual polish is not.** Every existing capability must still work after Phase 1. UI enrichment to surface the richer result fields (a nicely rendered resolution_path expandable view, prettier warning rendering, color coding for the new statuses) is follow-on work that can land on its own schedule.

**Note on the web app's evolving strategic role.** If LQ-AI integration becomes a real path (see roadmap §7), the web app's positioning shifts. Today the web app is the primary user-facing surface for verification. In a future where LQ-AI users access the verifier through LQ-AI's chat UI (once their MCP-client subsystem lands), this web app's role narrows from "primary user surface" to "operator and developer tooling surface" — the place to do direct verifier access, debugging, batch operations, and QC review that LQ-AI's general-purpose chat won't surface naturally. That role shift suggests a discipline for future investment: solid functional baseline that exposes the verifier's full surface for power users and debugging = useful permanently. Heavy consumer-grade UI polish on pages a future LQ-AI integration would replace = wasted effort. This is a design-discipline note for the maintainer's future decisions, not a current refactor task.

### Cross-repo consumers: the benchmark project

The benchmark project (`~/Projects/case-law-proposition-benchmark`) is a separate (private) research project that measures how well various AI models (Gemini, OpenAI, Anthropic) can find real cases that support a given legal proposition. It produces (model, proposition, candidate_citation, verifier_result) tuples at volume and uses citation-verifier to confirm whether each candidate citation resolves to a real case — distinguishing actual hallucinations from real-but-CL-uncovered cases is the benchmark's central measurement problem. It also currently re-implements substance checking locally because verify-brief doesn't yet expose a clean atomic API (see roadmap §7). This project is the heaviest external consumer of citation-verifier and the design principle in 1.6 about respecting cross-repo consumers exists specifically because of it.

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

1. Phases 1–4 land on citation-verifier under a new tag (suggest `v0.3.0` for the first refactor cut; further alpha/beta tags as needed during the refactor).
2. The benchmark stays pinned to `v0.2.0` and continues to function on the old API throughout the refactor. No coordination required for citation-verifier's branches and commits to land.
3. When the refactor is far enough along that the benchmark's migration is worth doing, the benchmark gets its own branch. On that branch, the benchmark consumes citation-verifier via editable install (`pip install -e ../citation-verifier`) from a sibling working copy. Benchmark migration to the new API happens on that branch, iterating against an in-progress refactor branch on citation-verifier's side.
4. When both sides are ready, citation-verifier tags `v0.3.0`, the benchmark bumps its `requirements.txt` pin to `v0.3.0`, and the dual-track branches merge in close succession.

The editable-install dev loop is the primitive that makes step 3 practical. Without it, every iteration during dual-track migration would require a tag bump. The doc names this explicitly because it's central to the workflow even though it's not part of either project's runtime story.

**Internal-API change discipline during the refactor.** Per design principle 1.6: the refactor touches `models.py` substantially (the schema rewrite) and `verifier.py` substantially (instrumentation, new classification logic). Other modules — `parser`, `name_matcher`, `client` (both sync and async surfaces), `court_map` — should not change their public APIs unless a specific refactor task genuinely requires it. The one anticipated exception is the `ParsedCitation` addition of `ecf_document_number` (additive; non-breaking for existing consumers). If a Phase 3 implementation discovers it needs to change a signature in one of these modules beyond that, that's a flag-and-discuss moment, not a silent change. Every public-API change to these modules gets a changelog entry with a migration note for cross-repo consumers.

---

## 6. Non-goals

Things this refactor (Phases 1–4) is explicitly not trying to do. Surface as questions if any of these become tempting during implementation:

- **Not building the MCP server.** Phase 1–4 ship a refactored library. The MCP server is a roadmap item (§7) with its own design conversation.
- **Not rewriting the skill.** The skill stays as-is during the refactor; it'll be rewritten as a roadmap item once the library and any MCP surface are settled.
- **Not building the diagnostic runner.** The diagnostic-runner-plus-corpus-flywheel is a roadmap item with its own design.
- **Not building verify-proposition.** The atomic proposition-check primitive is a roadmap item. verify-brief continues to exist during the refactor, just updated to consume the new types (Phase 1 sub-task).
- **Not adding new resolution backends.** No Google Scholar, no Westlaw scraping, no state-court-specific clients. The fallback ladder stays at the current set.
- **Not changing the caching layer.** Existing file cache stays. Schema changes mean cache must be invalidated once on first run, but the caching mechanism is not being redesigned.
- **Not introducing async if it isn't already there.** Current async support is preserved; no new async-first APIs.
- **Not building a UI.** The web app gets compatibility updates only.

---

## 7. Roadmap (Phases 5+)

Built on top of the refactored library. Each gets its own design doc when it's time to build. The refactor must not foreclose these; that's the only constraint they impose on Phases 1–4.

This section sketches design *intents* — what each roadmap item is for and what shape it should preserve — without specifying implementation. The full design conversation for each happens at the point it's ready to ship.

### Phase 5 — MCP server

**Intent.** Wrap the refactored library in a Model Context Protocol surface so MCP clients (Claude Desktop, Claude Code, future hosted clients) can consume the verifier. Thin shell over the library.

**Tools the MCP should expose:** `verify_citation`, `verify_citations_batch`, `verify_with_gates`, plus a separate `inspect_citation_format` helper for cheap deterministic checks (reporter exists in index, volume in known range, date consistent with reporter active period) that return structured facts without prejudging.

**Design intents Phase 1–4 should preserve:**
- The `BatchVerificationResult` grouped-by-status shape is what the MCP returns over the wire; downstream MCP clients should not have to flatten.
- `FinalIds` is rich enough to be the handoff to downstream MCP tools (proposition-check, quote-check) without re-querying.
- Per-stage `resolution_path` survives MCP-transport serialization (JSON, no opaque blobs).

**Deferred design conversations.** Python MCP framework choice (FastMCP vs. official SDK vs. roll-your-own). Transport (stdio vs. SSE/HTTP). Whether the CLI shells through the MCP or both wrap the library. Schema discoverability via MCP resources vs. out-of-band docs. Schema versioning across client/server skew. Self-hosted vs. hosted (open issue: per-user auth against CourtListener for a hosted version is its own multi-quarter project). All of these are Phase 5 design doc material, not refactor material.

### Phase 6 — Skill rewrite (6a) + lq-skills submission (6b)

**Phase 6a — Skill rewrite (lands locally).**

*Intent.* The skill shrinks to its essential job: ingestion, invocation, presentation. Procedural logic is in the library / MCP; the skill no longer describes the fallback ladder, the classification taxonomy, the full-caption procedure, or the silent-partial-verification check.

*Skill retains:* ingestion logic across four input shapes; invocation of the MCP tool with appropriate batching; presentation logic adapted to environment (chat, Word inline, Word appendix); interpretation of `NOT_FOUND` results using web search and model judgment; handoff documentation pointing downstream skills at the `FinalIds` fields. Explicit guidance for the `NOT_FOUND` judgment task — the skill is encouraged to use web search, secondary-source checking, reporter plausibility reasoning, and pattern-matching against known hallucination signatures. Output should be structured (per-citation classification with brief reasoning) not free-form prose.

*Design intents Phase 1–4 should preserve:* the structured result is the handoff (principle 1.4); the skill must be able to act on the result object without re-running procedural logic; the `BatchVerificationResult` grouping supports the skill's summary-then-problem-subset presentation pattern.

**Phase 6b — lq-skills submission (separate decision).**

*Intent.* Submit the post-refactor skill to [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) as a community contribution.

*Prerequisites for 6b (any of which can delay it independently of 6a):* the verifier MCP being independently installable; the skill's frontmatter clearly documenting the MCP dependency (name, where to install, what it provides, failure mode if absent); a settled answer on the "you need to set up a CourtListener API token" friction; review of lq-skills' contribution conventions.

6b might not happen on the same timeline as 6a; they should not be coupled in roadmap planning.

### Phase 7 — Diagnostic runner + benchmark flywheel

**Intent.** Build the regression-corpus runner, the model-driven diagnostic step, and the issue-drafter that make the verifier improve over time. Connect it to the benchmark project so the verifier learns from confirmed false negatives and grows its regression corpus from confirmed ground truth.

**Terminology:** "diagnostic runner," not "evaluator." (Avoids collision with Lavern's "evaluator gate" and the AI-evals world's "evaluator" — both of which mean different things.)

**Design intents Phase 1–4 should preserve:**
- `resolution_path` is rich enough that a diagnostic step can replay what the verifier did and reason about why a `NOT_FOUND` came back.
- `VerificationResult` is stable enough across versions that a corpus of past results stays meaningful (the schema lives long enough to be a regression target).
- The benchmark project can consume the library directly to produce (model, proposition, candidate_citation, verifier_result, ground_truth) tuples; nothing in the refactor breaks that.

**The full Phase 7 design** — corpus runner architecture, model-driven diagnostic prompts, dedup keying, issue-drafter format, MCP surface for `diagnose_not_found_batch`, benchmark-side consumption logic — is its own design conversation. It gets its own design doc once Phases 1–4 land and we know what the diagnostic runner actually has to work with. Splitting it further (corpus runner / diagnostic / MCP+integration) is likely; that decision belongs to the future doc.

### Phase 8 — verify-proposition

**Intent.** The atomic proposition-checking primitive. Given a claim (proposition text + cited case ID, where the case ID comes from a prior citation-verifier resolution), return a structured assessment of whether the case supports the claim. Sibling MCP tool to the verifier.

**Why this is its own phase, not part of the current refactor.** verify-brief currently exists in citation-verifier as a sibling tool with its own skill (`.claude/skills/verify-brief/SKILL.md`), library module (`src/citation_verifier/brief_pipeline.py`), CLI subcommand, tests, and per-brief workdir convention. It depends on citation-verifier's `VerificationResult` and so gets *mechanical* Phase 1 updates (per the Phase 1 sub-task above), but its own Lavern-shaped refactor is a separate design conversation with its own schema spec, its own MCP surface, and its own gate/warning taxonomy.

**Why the rename.** verify-brief conflates two distinct concerns: the *atomic substance check* (does this case support this proposition?) and the *brief-orchestration layer* (parse a whole brief, extract claims via wave1/wave2, merge, generate HTML reports, manage per-brief workdirs). The atomic check is clean, reusable, MCP-shaped, and what downstream consumers actually need. The brief-orchestration layer is messy and bound up with input-format quirks. Phase 8 deliberately scopes to the atomic primitive (verify-proposition) and defers the brief-orchestration layer.

**Why this matters for the refactor.** The benchmark project currently re-implements substance checking locally (in `pilot_a/score.py` and `runners/sdk_assessor.py`) because verify-brief doesn't expose a clean atomic API. The moment verify-proposition exposes one, the benchmark collapses its local re-implementation onto it. This is the primary consumer that drives the verify-proposition API design — its needs should be pulled forward into the Phase 8 design conversation, not surfaced later as a retrofit.

**Design intents Phase 1–4 should preserve:**
- `FinalIds` carries everything verify-proposition needs to fetch opinion text (cluster_id + opinion_id, or recap_document_id, plus `text_source` so the consumer knows which endpoint to hit).
- `text_source` distinguishes opinion-endpoint text from RECAP-document text (relevant because the fetch path differs).
- Nothing in the refactor couples verify-brief's `brief_pipeline.py` to the verifier's internals in ways that block the future atomic split.

**Phase 8 explicitly defers:** the brief-orchestration layer (wave1/wave2/merge/check_quotes/metadata_check/report from current `brief_pipeline.py`); the HTML report template. These can become Phase 9+ items if still wanted, or stay as in-repo tools that consume the verify-proposition MCP.

### Further out

Listed for orientation, not commitment:
- Additional resolution backends (Google Scholar fallback, state-court-specific resolvers)
- Async-first batch processing optimization
- Hosted MCP server with multi-tenant rate limiting and per-user CL auth
- Quote-check as a sibling MCP tool sharing the verifier's resolution infrastructure
- **LQ-AI native integration via their MCP-client subsystem.** LQ-AI ([LegalQuants/lq-ai](https://github.com/LegalQuants/lq-ai)) is a self-hosted open-source platform for legal teams. Their roadmap includes an MCP-client subsystem at M5+ (community-driven, not yet committed to a timeline). When that subsystem ships, the already-published skill (in lq-skills, per Phase 6b) and the verifier MCP (a standard MCP server) become natively available to LQ-AI deployments with no additional work on this project's side — lq-skills is consumed by LQ-AI as a git submodule and any standard MCP server can be wired into the MCP-client subsystem when it exists. Monitor LQ-AI's MCP-client subsystem development; if their MCP server conventions diverge from standard expectations in ways that would affect this project's MCP design, raise as an open question and adapt.

---

## 8. Open questions

Decisions the maintainer hasn't made yet. Some have moved to future design docs as Phases 5+ separated out from the refactor; what remains here is what the refactor (Phases 1–4) needs answers to.

**For the refactor (Phases 1–4):**

- **Per-stage confidence thresholds.** The current pipeline has thresholds (notably 0.40 in `opinion_search`) that gate stage resolution. Decision (2026-05-20): carry forward unchanged into Phase 3; retune only if the Phase 2.5 corpus surfaces evidence that warrants it.
- **`raw_response_summary` size.** Free-form per stage (§2.5), but how much detail per entry? Cached results that store full path entries multiply path size by stage count. Decision (2026-05-20): compact summaries by default; debug mode (configurable) captures more. Per-stage size budget is a Phase 2 implementation detail, not a schema commitment.
- **Warning-amendment workflow detail.** §2.6 promises minor-version bumps for additions, major for removals. The repo doesn't currently follow semver strictly. Decision (2026-05-20): adopt this discipline for `models.py` schema changes starting with the refactor; capture in CHANGELOG entries even if the package version doesn't strictly bump per change.
- **ParsedCitation `ecf_document_number` parsing.** Which input shapes should the parser recognize (`ECF No. 42`, `Doc. 17`, `Dkt. 17`, others)? Decision (2026-05-20): start with the common forms (`ECF No. N`, `Doc. N`, `Dkt. N`, `Dkt. No. N`); widen if the Phase 2.5 corpus surfaces missed forms.

**Deferred to roadmap-item design docs (no decision needed for the refactor):**

- All MCP design questions (framework, transport, hosting, versioning) — Phase 5 doc.
- Whether the skill's web-search-augmented `NOT_FOUND` interpretation is its own skill — Phase 6a doc.
- Aggressiveness of the diagnostic step; whether the diagnostic runner has its own MCP — Phase 7 doc.
- verify-proposition's full schema and API surface — Phase 8 doc.
- Hosted vs. self-hosted verifier deployment — Phase 5 doc (or a separate "hosted verifier" doc).

---

## 9. Implementation philosophy notes for Claude Code

These are reminders, not new content. When in doubt during implementation:

- **Check decisions against the design principles in §1's "Stated design principles."** If a proposed change violates one of them, surface as an open question.
- **Never let the model own the procedure.** If a temptation arises to "have the model figure it out" inside the verifier code, that's a sign the logic belongs in the skill, not in the verifier — or the schema needs to expose a richer signal so the model can figure it out at the consumer layer.
- **Never editorialize in the verifier.** If a status feels like it would be "more informative" if we added a heuristic, that's a sign the heuristic belongs as an auxiliary signal (or in the skill), not as a status.
- **The schema is the contract.** Changes to the schema during implementation require updating this document. Document drift between code and spec is the failure mode that kills refactor projects of this shape.
- **Stay in scope.** Phases 1–4 are the refactor. Anything that smells like Phase 5+ work during the refactor should be flagged as scope creep, not silently absorbed.
