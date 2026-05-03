# Case Law Retrieval Benchmark — Roadmap

Living doc. Tracks deferred work from v1 plus ideas surfaced during runs.

**Current state:** v1 in progress (200 cells × 3 models, scoring underway).

---

## v1.1 — Methodology hardening

These items were called out in the v1 design as deferred. Keep them grouped so a v1.1 release can sweep them together.

| Item | Why deferred from v1 | What it unlocks |
|---|---|---|
| Forkable kit scaffolding (SCHEMA.md, MINING_PLAYBOOK.md, QUALITY_GATES.md, PROMPT_TEMPLATES/, scoring/, SUBMISSION.md) | Federal-layer was the reference implementation; kit comes after a working v1 | External contributors can fork the kit and run state-court / circuit / topic-specific variants |
| Web-search and tool-augmented eval modes | Closed-book first to establish baseline | Tests retrieval-augmented frontier behavior (e.g. Sonnet+web vs. Opus closed-book) |
| Currency axis (good-law check) | Needs CL citator data integration | Catches "real case but bad law" — overruled, vacated, distinguished |
| Jurisdictional-appropriateness axis | Needs court-hierarchy rules | Penalizes citing 3rd Cir. for a 5th Cir. proposition |
| Lexical-dissimilarity quality gate | Pilot A recorded raw similarity but didn't filter | Removes propositions that are near-paraphrases of the gold case name |
| Multi-source existence oracle (CL + Justia + Caselaw Access Project) | CL-coverage bias is acknowledged in v1; quantification deferred | Vendor RAG benchmarks (v1.1+) need broader-than-CL coverage to be fair |
| Acceptable-alternatives caching | v1 records (model, gold, alternative-found-by-Opus) but no cache | Re-runs don't re-judge known-acceptable substitutes |
| Mining-stage deduplication on `(citing_cluster_id, citation_text, parenthetical)` | v1 mining produced ~10× duplication of each paren inside its source opinion (eyecite picking up the same citation in full + short forms); 35% of the 200-row sampled dataset turned out to be duplicates of other rows; deduped to 130 unique propositions for the report | Saves CL API calls during build; prevents over-weighting in the final sample; lets v1.1 hit a true N=200 instead of an effective N=130 |
| Verified-citations cache (`citation_text → cluster_id, case_name`) | v1 has gold-case verifications in `dataset.csv` but doesn't reuse them — every scoring run re-asks CL for known-real cases | Speed (skip CL for cached hits), reliability (fewer chances for CL bugs to bite), and a diff-able audit artifact that grows across runs |
| Stratified sampling by tier of cited case (target ~33% SCOTUS / circuit / district) | v1's gold cases are 60% circuit, 19% SCOTUS, only 9% district — driven by what district opinions cite, not what the benchmark needs to test. The hint that district-case retrieval is dramatically harder (Sonnet: 0 cited; Opus: 1/5 Green; GPT-5: 0/9 Green) is buried under low n | Lets us make a serious claim about district vs appellate hallucination rates instead of an n=5 hint |
| Per-case metadata extraction (court ID + filing year of each cited case) | v1 records cited case name, citation, and CL cluster ID, but not the court or year of the cited case (the cluster has both — just unused). Without it we can't break down hallucination rate by jurisdiction or case age | Enables tier breakdown (the dimension above) without re-running, plus opens questions like "do models hallucinate more on older cases?" or "is recency bias real for legal retrieval?" |
| Default opinion window 20K → 60K (or grep tool) | v1 used a 20K-char truncation. v1 follow-up (`benchmark_v1/truncation_experiment.md`) re-assessed every v1 Red at 60K and found 22/59 (37%) flipped to Green/Yellow. Per-model corrected Green rates: Sonnet 31.5% (no change), Opus 36.2% → 39.3%, GPT-5 46.2% → 52.4% | Eliminates the conservative-against-the-model bias the v1 caveats already disclosed. Cost: ~3× the assessor budget. A grep tool would target relevance directly (see v1.2 below) |

---

## v1.2 — Assessor calibration study

**Goal:** quantify whether Sonnet or Haiku can do the substance assessment job as well as Opus.

**Motivation:**
- The "Opus marks own Opus homework" objection is weaker than the v1 design treated it. The closed-book test-time model answers from memory; the assessor reads the actual opinion. Different tasks, different inputs.
- Opus is the bottleneck in v1: ~50% of cells trigger the assessor, ~15–25s per call. A capable cheaper assessor would 5–10× the run.
- That unlocks N=500 or N=1000 datasets, more model variants per run, and cheap re-runs as new frontier models ship.

**Method (sketch):**
1. Re-run the assessor on v1's 600 cells with Sonnet and Haiku. Opinion text is already cached so it's just the model calls.
2. Build a confusion matrix per pair (Opus vs Sonnet, Opus vs Haiku).
3. Quantify agreement on Green/Yellow/Red — overall accuracy, kappa, and per-class precision/recall.
4. Decide a primary assessor for v2 based on the results.

**Deliverable:** `tests/benchmark_v1/calibrate_assessor.py` + a `calibration.md` report. Doesn't touch v1's data — strictly additive.

**Acceptance bar:** if cheaper-assessor agreement with Opus is ≥ 90% overall AND ≥ 85% on Red specifically, switch the primary. Red precision matters most because Reds are the hallucinations we're catching.

---

## v2 — Scope expansion

| Item | Why |
|---|---|
| Circuits + SCOTUS | Pilot A and v1 are districts only. Circuits have richer parentheticals; SCOTUS would expose strong-recall vs. accuracy tradeoffs |
| State-law forks | Federal layer is the reference; state implementations exercise the kit and surface state-specific quirks (regional reporters, citation styles) |
| Larger N (500–1000) | Predicated on the calibration study (v1.2) cutting per-cell cost |

---

## Observations from v1 run (worth reusing)

These aren't roadmap items but are factual lessons from running v1 that shouldn't be forgotten.

| Observation | Where it shows up |
|---|---|
| GPT-5 needs `max_completion_tokens >= 8000` for closed-book legal prompts; 2000 left ~67% of responses empty (all hit the budget exactly on reasoning) | `tests/benchmark_v1/model_adapter.py` `_call_gpt5` comment |
| Claude CLI `claude -p --model sonnet` calls can take >60s on real prompts; 120s timeout is safer; max OK call observed was 59.5s | `tests/benchmark_v1/run_model.py` `TIMEOUT_S` comment |
| Sonnet's UNKNOWN rate is far higher than Opus or GPT-5 (53% vs 22% vs 6%) — implies hallucination rate alone misranks; pair with UNKNOWN rate or use Green-rate-of-real | Will live in `benchmark_v1/scorecards.md` once v1 finishes |
| 20K char opinion truncation hides supporting passages ~37% of the time when the cited opinion exceeds 20K. Measured by re-assessing all v1 Reds at 60K (see `benchmark_v1/truncation_experiment.md`); SCOTUS and circuit Reds flip at indistinguishable rates (43% vs 41%), so the SCOTUS-leans-easy pattern in Table 4 is a knowledge effect, not a syllabus artifact. District Reds did not flip at all (0/8) | Default opinion window raised to 60K in v1.1 (see above). v1.2 may add a grep / relevance-aware retrieval tool for cases where 60K is still insufficient |
| Stdout buffering through bash redirect (`>` log file) hides progress until process exits; results.csv is the real progress signal | Future runners: tail `results.csv`, not the log |

---

## When to spin out to its own repo

**Recommendation: at v1.1, when the forkable kit ships.** Not before.

Today's setup (benchmark inside citation-verifier) is the right call because:
- The benchmark depends on citation-verifier *internals*: `parsed_citation_from_eyecite`, `verify_batch`, parser normalization, name matcher. These aren't a stable public API yet.
- Pilot A code is reused via `sys.path` injection, not a clean import boundary.
- Single venv, single .env, single dev loop — high velocity for iteration.
- v1's deliverable is a **scorecard + dataset**, not a kit. No external forkers are arriving yet.

Spin out when these are all true:
1. **Forkable kit lands (v1.1)**. SCHEMA.md, MINING_PLAYBOOK.md, etc. exist. External contributors are the audience.
2. **citation-verifier exposes a stable public API** that the benchmark can pin a version of (`citation-verifier>=X.Y`). Until then, internal-API churn breaks the benchmark in a separate repo.
3. **At least 2–3 outside people have signaled they want to fork** (state-court variant, topic-specific variant, etc.). One-off curiosity isn't enough — the cost of a separate repo is real.
4. **A clean release story is needed** — DOI, arXiv companion, NeurIPS-style benchmark track submission, GitHub releases with versioned datasets. These all want a top-level repo to point at.

Practical mechanics when the time comes:
- New repo name candidates: `case-law-retrieval-benchmark`, `claire-bench`, etc.
- citation-verifier becomes a pinned pip dependency (publish to PyPI first, or git+https)
- Move `tests/benchmark_v1/` → benchmark repo's `runners/`, `benchmark_v1/` → benchmark repo's `releases/v1/`
- Roadmap, design docs, retrospectives migrate too
- Leave a stub in citation-verifier pointing at the new repo

Anti-pattern to avoid: spinning out before v1.1 just because it "feels cleaner." External contributors aren't there yet, and you'd pay the cross-repo PR / dependency-version-bump cost without a benefit.

---

## How this doc evolves

- Add a row when a v1.x or v2 release ships an item (mark as ✅, link to commit/PR)
- Promote items that get scoped down to a release (e.g. v1.2 calibration → "v1.2 (in progress)")
- Don't delete completed items; they're the trail of how we got here
