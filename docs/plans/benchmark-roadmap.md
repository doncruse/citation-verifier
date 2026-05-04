# Case Law Retrieval Benchmark — Roadmap

Living doc. Tracks deferred work from v1 plus ideas surfaced during runs.

**Current state:** v1 shipped May 2026 (effective N=130 after dedup, 3 models, Opus-assessed). v1.1 validation studies done (assessor calibration + 60K truncation re-test — see `## v1.1 — Validation studies`). v1.2 methodology hardening in progress: gold-DB design + plan landed 2026-05-03 ([design](2026-05-03-gold-db-design.md), [plan](2026-05-03-gold-db-plan.md)) and subsumes three of the deferred items (verified-citations cache, acceptable-alternatives caching, per-case metadata extraction). **Mid-flight findings (2026-05-04):** the gold-pair self-score pass surfaced two material methodology issues, both written up in retrospectives: (a) `pilot_a/score.py:fetch_opinion_text` silently truncates at 20K — affected Task 10's "60K" gold-pair pass and the v1.1 calibration study (see [2026-05-04-truncation-bug-and-red-audit.md](../retrospectives/2026-05-04-truncation-bug-and-red-audit.md)); (b) eyecite/build_dataset mis-attaches parentheticals to the wrong case in chained citations — 3 of 5 v1 "Reds" at full text were parser bugs, not court errors (see [2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md](../retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md)). Sonnet 4.6 at full text is now the leading candidate for v2 assessor (90.6% Green on v1 gold pairs, ~5× cheaper than Opus); Haiku 4.5 fails badly even at full text (54.7% Red, agreement matrix shows it disagrees with Sonnet on 60+ Greens).

---

## v1.2 — Methodology hardening

These items were called out in the v1 design as deferred. Keep them grouped so a v1.2 release can sweep them together. The **gold-DB** ([design](2026-05-03-gold-db-design.md), [plan](2026-05-03-gold-db-plan.md), in progress 2026-05-03) is the framing artifact for v1.2: a cumulative SQLite corpus of (proposition, case, verdict) tuples that subsumes three of the items below (marked) and unlocks the rest.

| Item | Why deferred from v1 | What it unlocks |
|---|---|---|
| Forkable kit scaffolding (SCHEMA.md, MINING_PLAYBOOK.md, QUALITY_GATES.md, PROMPT_TEMPLATES/, scoring/, SUBMISSION.md) | Federal-layer was the reference implementation; kit comes after a working v1 | External contributors can fork the kit and run state-court / circuit / topic-specific variants |
| Web-search and tool-augmented eval modes | Closed-book first to establish baseline | Tests retrieval-augmented frontier behavior (e.g. Sonnet+web vs. Opus closed-book) |
| Currency axis (good-law check) | Needs CL citator data integration | Catches "real case but bad law" — overruled, vacated, distinguished |
| Jurisdictional-appropriateness axis | Needs court-hierarchy rules | Penalizes citing 3rd Cir. for a 5th Cir. proposition |
| Lexical-dissimilarity quality gate | Pilot A recorded raw similarity but didn't filter | Removes propositions that are near-paraphrases of the gold case name |
| Multi-source existence oracle (CL + Justia + Caselaw Access Project) | CL-coverage bias is acknowledged in v1; quantification deferred | Vendor RAG benchmarks (v1.2+) need broader-than-CL coverage to be fair |
| **Acceptable-alternatives caching** → *subsumed by [gold-DB](2026-05-03-gold-db-design.md)* | v1 records (model, gold, alternative-found-by-Opus) but no cache | Re-runs don't re-judge known-acceptable substitutes |
| Mining-stage deduplication on `(citing_cluster_id, citation_text, parenthetical)` | v1 mining produced ~10× duplication of each paren inside its source opinion (eyecite picking up the same citation in full + short forms); 35% of the 200-row sampled dataset turned out to be duplicates of other rows; deduped to 130 unique propositions for the report | Saves CL API calls during build; prevents over-weighting in the final sample; lets v1.2 hit a true N=200 instead of an effective N=130 (or v2 starts fresh at the target) |
| **Verified-citations cache** (`citation_text → cluster_id, case_name`) → *subsumed by [gold-DB](2026-05-03-gold-db-design.md)* | v1 has gold-case verifications in `dataset.csv` but doesn't reuse them — every scoring run re-asks CL for known-real cases | Speed (skip CL for cached hits), reliability (fewer chances for CL bugs to bite), and a diff-able audit artifact that grows across runs |
| Stratified sampling by tier of cited case (target ~33% SCOTUS / circuit / district) | v1's gold cases are 60% circuit, 19% SCOTUS, only 9% district — driven by what district opinions cite, not what the benchmark needs to test. The hint that district-case retrieval is dramatically harder (Sonnet: 0 cited; Opus: 1/5 Green; GPT-5: 0/9 Green) is buried under low n | Lets us make a serious claim about district vs appellate hallucination rates instead of an n=5 hint |
| **Per-case metadata extraction** (court ID + filing year of each cited case) → *gold-DB schema has the columns ([gold-DB design](2026-05-03-gold-db-design.md)); a one-shot CL fetch to fill them is a follow-up v1.2 item* | v1 records cited case name, citation, and CL cluster ID, but not the court or year of the cited case (the cluster has both — just unused). Without it we can't break down hallucination rate by jurisdiction or case age | Enables tier breakdown (the dimension above) without re-running, plus opens questions like "do models hallucinate more on older cases?" or "is recency bias real for legal retrieval?" |
| Default opinion window 20K → 60K (or grep tool) | v1 used a 20K-char truncation. v1 follow-up (`benchmark_v1/truncation_experiment.md`) re-assessed every v1 Red at 60K and found 22/59 (37%) flipped to Green/Yellow. Per-model corrected Green rates: Sonnet 31.5% (no change), Opus 36.2% → 39.3%, GPT-5 46.2% → 52.4% | Eliminates the conservative-against-the-model bias the v1 caveats already disclosed. Cost: ~3× the assessor budget. A grep / relevance-aware retrieval tool would target relevance directly; deferred as future work |
| **Gold-DB itself** ([design](2026-05-03-gold-db-design.md), [plan](2026-05-03-gold-db-plan.md)) — in progress 2026-05-03 | v1's data was scattered across CSVs; verdicts repeated across runs; no shared corpus that outlives any one dataset | One cumulative SQLite artifact: build- and score-side caches, calibration self-scores as first-class data, schema for v2 fresh mining to extend |
| **Fix `pilot_a/score.py:fetch_opinion_text` 20K truncation** — surfaced 2026-05-04 by gold-pair audit | Function silently caps every opinion at 20K chars; bypassed only by the original truncation experiment (which read cache directly). Affected Task 10's gold-pair self-scores, calibrate_assessor.py, and v1's main score.py loop. See [retrospective](../retrospectives/2026-05-04-truncation-bug-and-red-audit.md). | Honest-window measurements; lets v2's assessor see the full opinion by default; eliminates ~17 spurious Reds in the v1 gold-pair set |
| **Fix eyecite parenthetical mis-attribution in chained citations** — surfaced 2026-05-04 by Reds-in-context audit | When a citation chain has form `Case_A; Case_B (parenthetical)` or `Case_A (quoting Z); see Case_B (parenthetical)`, eyecite/build_dataset sometimes attaches the substantive parenthetical to the wrong case. 3 of 5 v1 full-text Reds were this bug. Footnote text adjacent to a parenthetical can also leak in. See [retrospective](../retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md). | v2 mining quality: today an unknown fraction of "verified" propositions are actually attributed to the wrong case but happen to score Green by luck. Fix is either upstream eyecite PR or post-processing in build_dataset.py. |
| ~~Re-run gold-pair Opus at full text~~ — **resolved 2026-05-04 via relabel** | Task 10's 117 gold-pair Opus rows were stored as `(v1, 60000)` but actually scored at 20K. Sonnet@FT (Tasks ~done) supersedes the need for a canonical Opus@FT baseline — Sonnet IS the v2 assessor candidate. Rather than re-running Opus, we relabeled the 117 rows to `(v1-task10, 20000)` to reflect actual scoring conditions. The new prompt_version distinguishes Task 10's re-scoring from the original v1 Pass 3 model_answer scorings (also at `v1, 20000`) without UNIQUE collision. | DB labels are honest; no new Opus spend; v2's Sonnet@FT becomes the canonical calibration baseline going forward |
| **Random-sample Green/Yellow audit** — measure parenthetical-mis-attribution prevalence | The 3-of-5-Reds finding only tells us about the Reds. We don't know how often the same misattribution affects propositions that scored Green or Yellow despite the parenthetical actually belonging to a different case. 50-100 random non-Red gold pairs read in context would settle it. | Estimate of the v1 dataset's true proposition-attribution accuracy; tells us how aggressively v2 mining needs to be fixed |

---

## v1.1 — Validation studies ✅ done (May 2026)

> *Two small additive studies grouped under v1.1 because they validate v1's methodology without expanding scope: (a) the assessor calibration study (Sonnet/Haiku vs Opus) and (b) the 20K → 60K truncation re-test (`benchmark_v1/truncation_experiment.md` and `truncation_experiment_60k.csv`). Both are documented below; the calibration study has the bigger writeup. v1.2 is methodology hardening (gold-DB, dedup, stratified sampling, etc.).*

> ⚠️ **2026-05-04 update — calibration conclusion is provisional.** The calibration study scored all three models at 20K-truncated input (its own `MAX_OPINION_CHARS = 20000`). Subsequent gold-pair work at full opinion text suggests Sonnet's failure mode at 20K was largely a truncation artifact: at full text, Sonnet matches the audit's truth estimate (~91% Green on v1 gold pairs), comparable to expected Opus@full-text behavior. **Sonnet may pass the 90% bar at full text and is currently the leading v2 assessor candidate.** Haiku's failure is robust across input windows. A definitive answer requires re-running the 514-cell calibration at full text (~1000 calls; subscription quota); see v1.4 follow-ups in [the 2026-05-04 retrospective](../retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md).

**Outcome:** both candidates failed the bar. Opus stays as primary assessor.

| Model | Overall agreement | Red recall | Red precision | Cohen's κ |
|---|---:|---:|---:|---:|
| Sonnet 4.6 | 68.9% | 52.2% | 87.8% | 0.50 |
| Haiku 4.5 | 65.4% | 55.1% | 67.9% | 0.41 |
| *Bar* | ≥90% | ≥85% | — | — |

Both miss by ~20pp on overall and ~30pp on Red recall — robustly below the bar across CIs at n=257. Sonnet's Red precision is high (87.8%) but its Red recall is only 52% — half the hallucinations Opus catches would slip through. Yellow is the failure mode for both candidates (precision 21–32%): neither model treats the Yellow boundary the way Opus does.

**Implication:** the cost-scaling path (5–10× the run by switching assessors) is closed. v1.x stays at N≈200 within Opus's budget envelope; cheaper-frontier-model substitution is not the lever.

**Artifacts:**
- [`benchmark_v1/calibration.md`](../../benchmark_v1/calibration.md) — confusion matrices, per-class metrics
- [`benchmark_v1/calibration_results.csv`](../../benchmark_v1/calibration_results.csv) — 514 calls, full coverage
- [`tests/benchmark_v1/calibrate_assessor.py`](../../tests/benchmark_v1/calibrate_assessor.py) — runner (direct API, `temperature=0`, resume-safe)
- [`tests/benchmark_v1/calibrate_assessor_report.py`](../../tests/benchmark_v1/calibrate_assessor_report.py) — aggregator
- [`docs/retrospectives/2026-05-02-v1.2-assessor-calibration.md`](../retrospectives/2026-05-02-v1.2-assessor-calibration.md) — run notes + keying-bug postmortem

**Original goal and method preserved below for the trail.**

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
| Larger N (500–1000) | Originally predicated on the assessor calibration (v1.1, done) cutting per-cell cost; **that conclusion is now provisional** — Sonnet@full-text appears to match Opus's expected accuracy at ~5× lower cost (see 2026-05-04 retrospective). If full-text re-calibration confirms, larger N becomes affordable. |
| **Sonnet 4.6 at full text as default assessor** | Surfaced 2026-05-04 by gold-pair full-text comparison: Sonnet hit 90.6% Green on v1's 117 gold pairs (matches audit's truth estimate); Haiku hit 41.9% Green and is unusable. Switching from Opus to Sonnet cuts assessor cost ~5×. Subscription-only quota — no out-of-pocket impact, but real impact on per-run wall time and total Claude Code usage. |
| Mining pipeline overhaul before v2 | Three v1 issues need addressing: (a) eyecite duplicate-citation bug (deduped to 130 unique props from 200 raw rows in v1 — already a known item above); (b) parenthetical mis-attribution in chained citations (3 of 5 v1 Reds — see 2026-05-04 retrospective); (c) full-text fetcher (don't reuse pilot_a's 20K-truncating function). Together these determine v2's data-quality ceiling. |

---

## Observations from v1 run (worth reusing)

These aren't roadmap items but are factual lessons from running v1 that shouldn't be forgotten.

| Observation | Where it shows up |
|---|---|
| GPT-5 needs `max_completion_tokens >= 8000` for closed-book legal prompts; 2000 left ~67% of responses empty (all hit the budget exactly on reasoning) | `tests/benchmark_v1/model_adapter.py` `_call_gpt5` comment |
| Claude CLI `claude -p --model sonnet` calls can take >60s on real prompts; 120s timeout is safer; max OK call observed was 59.5s | `tests/benchmark_v1/run_model.py` `TIMEOUT_S` comment |
| Sonnet's UNKNOWN rate is far higher than Opus or GPT-5 (53% vs 22% vs 6%) — implies hallucination rate alone misranks; pair with UNKNOWN rate or use Green-rate-of-real | Will live in `benchmark_v1/scorecards.md` once v1 finishes |
| 20K char opinion truncation hides supporting passages ~37% of the time when the cited opinion exceeds 20K. Measured by re-assessing all v1 Reds at 60K (see `benchmark_v1/truncation_experiment.md`); SCOTUS and circuit Reds flip at indistinguishable rates (43% vs 41%), so the SCOTUS-leans-easy pattern in Table 4 is a knowledge effect, not a syllabus artifact. District Reds did not flip at all (0/8) | Default opinion window raised to 60K in v1.1 (see above). A grep / relevance-aware retrieval tool is deferred as future work for cases where 60K is still insufficient |
| Stdout buffering through bash redirect (`>` log file) hides progress until process exits; results.csv is the real progress signal | Future runners: tail `results.csv`, not the log |

---

## When to spin out to its own repo

**Recommendation: at v1.2, when the forkable kit ships.** Not before.

Today's setup (benchmark inside citation-verifier) is the right call because:
- The benchmark depends on citation-verifier *internals*: `parsed_citation_from_eyecite`, `verify_batch`, parser normalization, name matcher. These aren't a stable public API yet.
- Pilot A code is reused via `sys.path` injection, not a clean import boundary.
- Single venv, single .env, single dev loop — high velocity for iteration.
- v1's deliverable is a **scorecard + dataset**, not a kit. No external forkers are arriving yet.

Spin out when these are all true:
1. **Forkable kit lands (v1.2)**. SCHEMA.md, MINING_PLAYBOOK.md, etc. exist. External contributors are the audience.
2. **citation-verifier exposes a stable public API** that the benchmark can pin a version of (`citation-verifier>=X.Y`). Until then, internal-API churn breaks the benchmark in a separate repo.
3. **At least 2–3 outside people have signaled they want to fork** (state-court variant, topic-specific variant, etc.). One-off curiosity isn't enough — the cost of a separate repo is real.
4. **A clean release story is needed** — DOI, arXiv companion, NeurIPS-style benchmark track submission, GitHub releases with versioned datasets. These all want a top-level repo to point at.

Practical mechanics when the time comes:
- New repo name candidates: `case-law-retrieval-benchmark`, `claire-bench`, etc.
- citation-verifier becomes a pinned pip dependency (publish to PyPI first, or git+https)
- Move `tests/benchmark_v1/` → benchmark repo's `runners/`, `benchmark_v1/` → benchmark repo's `releases/v1/`
- Roadmap, design docs, retrospectives migrate too
- Leave a stub in citation-verifier pointing at the new repo

Anti-pattern to avoid: spinning out before v1.2 just because it "feels cleaner." External contributors aren't there yet, and you'd pay the cross-repo PR / dependency-version-bump cost without a benefit.

---

## How this doc evolves

- Add a row when a v1.x or v2 release ships an item (mark as ✅, link to commit/PR)
- Promote items that get scoped down to a release (e.g. mark "v1.1 — Validation studies" as ✅ done with the headline result, as was done in May 2026)
- Don't delete completed items; they're the trail of how we got here
