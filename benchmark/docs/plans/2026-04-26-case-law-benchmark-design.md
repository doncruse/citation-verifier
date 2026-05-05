# US Case Law Retrieval Benchmark — Design

**Status:** Brainstorm output. Not yet a build plan.
**Date:** 2026-04-26

## Why

There is no open benchmark for evaluating how well language models — raw or RAG-augmented — find supporting case law for a given legal proposition in US jurisdictions. Existing benchmarks cover adjacent ground but not this:

- **Reasoning** ([LegalBench](https://hazyresearch.stanford.edu/legalbench/), [LawBench](https://arxiv.org/pdf/2309.16289), [LEXam](https://arxiv.org/html/2505.12864v1)) — rule application, classification, MCQ; not retrieval over a real corpus.
- **Holding identification** ([CaseHOLD](https://reglab.stanford.edu/data/casehold-benchmark/)) — multiple choice given a citing context. Closed-form.
- **Hallucination audits** ([Dahl et al. 2024](https://arxiv.org/abs/2401.01301), [Magesh et al. 2025](https://onlinelibrary.wiley.com/doi/full/10.1111/jels.12413)) — measure raw hallucination rates; do not evaluate quality of retrieved cases against propositions.
- **Retrieval over caselaw** ([CLERC](https://aclanthology.org/2025.findings-naacl.441/)) — retrieves the case originally cited in a citing context. Single right answer; doesn't model real research where many cases support a proposition.
- **RAG over statutes** ([RegLab Bar Exam QA / Housing Statute QA](https://reglab.github.io/legal-rag-benchmarks/), [Isaacus Legal RAG Bench](https://huggingface.co/datasets/isaacus/legal-rag-bench)) — works because statutes have one authoritative form per jurisdiction. US case law doesn't.
- **Vendor benchmarks** ([Vals VLAIR](https://www.vals.ai/vlair)) — leaderboard format with vendor cooperation. Methodology contested; vendors withdrew; gold-answer quality disputed by participating attorneys.

The Vals experience identifies the central design hazard: any benchmark whose gold standard is "what some legal expert thinks the right answer is" inherits the moving-standard problem (lawyers disagree on correct answers) and the maintenance problem (answers go stale fast).

## What we're building

An **open evaluation instrument** — code, dataset, scoring methodology — that anyone can run locally to evaluate any model on US case-law retrieval. Not a leaderboard with a central referee. Not a vendor showcase. A reproducible measurement device.

### Two design moves that distinguish this from prior work

1. **Fresh-mined gold, not expert-curated gold.** Mine `(proposition, cited case)` pairs from published federal opinions filed **after model training cutoffs** (primary path). The gold's authority is provenance — these citations passed through Article III judges and adversarial briefing — not someone's opinion about what the right citation is. This sidesteps the moving-standard problem.

   **Primary data source: fresh post-cutoff opinion mining.** Pilot A (2026-04-26) found that Sonnet 4.6 scored 48% Green on LePaRD-sampled propositions vs. 16% on fresh post-cutoff D.D.C. parentheticals — a 32 pp gap (95% CI [+14, +50]), exceeding the 15 pp contamination threshold in the pilot's decision rule. Prior-dataset sources such as LePaRD are too easy for current models and are viable only as supplementary or ablation data. See `benchmark/pilot_a/summary.md`.

2. **Federated structure.** A federal-layer benchmark maintained in this repo, plus a **forkable kit** — schema, mining playbook, scoring code — that any state, jurisdiction, or research group can use to build their own benchmark. State coverage scales without us building it.

## Goals and non-goals

**Goals (v1)**

- Open dataset of `(proposition, jurisdiction, gold case, acceptable alternatives)` records mined from federal opinions across all court levels (SCOTUS, circuit, district)
- Standardized prompt templates supporting parametric, web-search, and proprietary-RAG eval modes
- Multi-axis scoring rubric: real / name-matches / supports-proposition / good-law / jurisdictionally-appropriate
- Reference scorecards on a representative set of frontier models in multiple eval modes (raw + with web access), demonstrating the harness produces meaningful comparisons
- Forkable kit with documented schema, mining playbook, and quality gates

**Non-goals (v1)**

- Central leaderboard hosting. Submitters publish their own scorecards; the repo links to community-submitted results.
- State law coverage. The kit makes state forks possible; we don't build them.
- PACER brief mining. Deferred to v2.
- Statutory or regulatory retrieval. Adjacent benchmarks already cover this.
- Single headline accuracy number. Multi-axis is the primary output; an optional weighted summary may be offered for sortability, but the breakdown is the contribution.

## The instrument

```
┌─────────────────────────────────────────────────┐
│  open dataset of (proposition + jurisdiction)   │
│  + gold case + acceptable-alternatives oracle   │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
            standardized prompt template
                       │
   ┌───────────────────┼───────────────────┐
   ▼                   ▼                   ▼
 raw model        raw model + web    legal RAG tool
 (parametric)     search tool        (proprietary corpus)
   │                   │                   │
   └───────────────────┼───────────────────┘
                       ▼
        eyecite extraction → citation-verifier
                       │
                       ▼
       multi-axis scorecard per model
       (real / name-matches / supports /
        good-law / jurisdiction)
```

### Dataset

Each record:

```yaml
id: fed-12345
proposition: "An agency action is arbitrary and capricious if the agency entirely failed to consider an important aspect of the problem."
proposition_paraphrase: "When evaluating whether agency action passes APA review, courts have held that ignoring a key dimension of the problem renders the decision invalid."
jurisdiction: "9th Cir."
year_window: [2018, 2024]
gold_case:
  name: "Motor Vehicle Mfrs. Assn. v. State Farm Mut. Auto. Ins. Co."
  citation: "463 U.S. 29"
  cluster_id: 110855
acceptable_alternatives: []  # populated lazily by the oracle at scoring time
mined_from:
  citing_opinion_cluster_id: 4567890
  citing_court: "ca9"
  citing_court_level: "circuit"
  citing_year: 2022
quality_flags:
  good_law_at_mining_time: true
  lexical_dissimilarity_score: 0.78
```

The `proposition_paraphrase` field is what gets sent to the model — lightly paraphrased to avoid keyword-match shortcuts, following the [Isaacus lexical-dissimilarity methodology](https://huggingface.co/datasets/isaacus/legal-rag-bench).

`acceptable_alternatives` is populated **at scoring time, not mining time**: when a model returns a case that isn't the gold case, the existing `/verify-brief` Phase 2 substance assessor judges whether the model's case substantively supports the proposition. If yes, score as correct and cache the alternative for future runs. This dodges the up-front "list every acceptable alternative" annotation problem.

### Scoring rubric (multi-axis)

For each example × model output, score five axes:

| Axis | What it measures | How |
|---|---|---|
| **Real** | Did the model name a real case? | citation-verifier existence check |
| **Name matches** | Does the cited case name match the citation? | citation-verifier name matcher |
| **Supports proposition** | Does the named case substantively support the stated proposition? | `/verify-brief` Phase 2 substance assessor (Opus subagent) — same code path used in the existing brief-verifier pipeline |
| **Good law** | Is the cited case still good law? | CL good-law signals when available; reported as N/A otherwise |
| **Jurisdictionally appropriate** | Is the cited case binding or persuasive in the stated jurisdiction? | rule-based check using court hierarchy + year |

Output is a per-axis breakdown and an optional weighted summary. The breakdown is the primary contribution; raw and RAG-augmented models fail in opposite ways on these axes, and a single number obscures the comparison.

### Eval modes

The harness runs the same dataset against models in any of these configurations, distinguished by submission metadata:

- **Parametric only** — no tool use, model answers from training
- **Web search** — model has a web-search tool (variants for ChatGPT consumer search, Claude web search, Gemini grounding, etc.)
- **Proprietary RAG** — commercial tool answers from its own corpus (Westlaw AI, Lexis+ AI, Harvey, etc.)
- **DIY RAG** — open-source model + user-configured retrieval over CL or other corpus

Each submission declares its mode. The leaderboard format displays mode alongside scores so comparisons are honest.

### Citation extraction

Models return free text (raw chat models) or structured outputs (legal tools). The harness uses the existing `parser.py` (eyecite + regex fallbacks + abbreviation normalization) to extract citations from any format. No structured-output requirement on submissions.

## Federated kit

The repo contains:

1. **`SCHEMA.md`** — record format spec, required and optional fields, validation rules
2. **`MINING_PLAYBOOK.md`** — how to extract `(proposition, cited case)` pairs from a corpus of opinions; configurable hooks for adapting to a different jurisdiction
3. **`QUALITY_GATES.md`** — automated checks every record must pass (case is real, lexical-dissimilarity threshold, currency check if available, etc.)
4. **`PROMPT_TEMPLATES/`** — standardized templates for each eval mode
5. **`scoring/`** — multi-axis scorer using `citation-verifier` and the `/verify-brief` Phase 2 substance assessor as the equivalence oracle
6. **`SUBMISSION.md`** — JSON spec for model outputs that the harness consumes
7. **`reference/federal/`** — our federal layer dataset, demonstrating the schema in use

A state fork is then: clone the kit, swap the corpus to (e.g.) California Supreme Court + California Court of Appeal opinions, run the mining playbook, ship the dataset. The federal layer is also our test case: if the kit isn't cleanly factored, we can't build the federal layer either.

### Mining playbook: precedential-status filter (required for fresh district data)

CourtListener's `/api/rest/v4/search/?type=o` endpoint defaults to `stat_Published=on` only. PACER-flagged district court opinions arrive on CL with `precedential_status=Unknown` and are **silently excluded** under the default filter.

For fresh post-cutoff district-court mining, the query **must** include `stat_Published=on&stat_Unknown=on`. Without it, the playbook silently constrains forks to roughly one district's worth of fresh data — an apparent infrastructure failure that is actually a filter artifact.

Verified 2026-04-26 (see `benchmark/pilot_a/summary.md`):

| District | Default count | With `stat_Unknown` lifted |
|---|---:|---:|
| C.D. Cal. | 0 | 185 |
| S.D. Tex. | 0 | 357 |
| N.D. Ill. | 0 | 327 |
| D.D.C. | 598 | 598 (unchanged) |

`MINING_PLAYBOOK.md` must document `stat_Published=on&stat_Unknown=on` (or the equivalent non-search-API parameter) as a required query parameter, not an optional tuning knob. Forks that omit it will silently produce unrepresentative coverage.

### Quality gates

Every record must pass automated checks before inclusion:

- Cited case resolves on CourtListener (citation-verifier returns VERIFIED or LIKELY_REAL)
- Cited case has not been overruled or vacated as of the citing opinion's date (where citator data is available)
- Lexical-dissimilarity score between proposition and the cited case's headnote/holding above a threshold (so models can't keyword-match)
- Citing opinion is published (not a memorandum or unpublished disposition, where the distinction exists)
- Citing opinion's `(proposition, cite)` extraction passes the existing brief-verifier confidence threshold

Gates are configurable per fork; some states won't have citator data or published/unpublished distinctions. Forks declare which axes their data supports; the scorer reports per-axis coverage.

## v1 scope

**In scope**

- Federal opinions corpus (SCOTUS + circuit + district), mined via existing CL infrastructure
- Multi-axis scoring built on existing `citation-verifier` and `/verify-brief` Phase 2 stack
- Three prompt-template variants (parametric / web-search / RAG)
- Forkable kit with documented mining playbook
- Reference scorecards on a small representative model set, sufficient to show the harness produces interpretable multi-axis comparisons (exact model selection deferred to implementation)

**Out of scope**

- State law coverage (kit-enabled, not built)
- PACER brief mining (kit-enabled, not built; deferred to v2)
- Central leaderboard hosting (community-submitted scorecards link out from repo README)
- Vendor cooperation (raw outputs are submitted by anyone running the harness)
- LLM judge calibration study (we use the existing Phase 2 assessor; calibration is a follow-up research question)

## Open methodological questions

These are deliberate open questions to resolve in implementation, not blockers to specifying the design:

1. **Corpus age window** — How recent should citing opinions be? Recent enough that gold cases are still good law; old enough for citator data to settle. Likely a 2-4 year lookback window with explicit cutoff.
2. **Court level distribution** — Should we sample equally across SCOTUS / circuit / district, or weight by the realistic distribution of legal-research targets? Probably stratified sampling with explicit slice metadata.
3. **Proposition extraction** — Existing `/verify-brief` extracts propositions from briefs; same approach should work on opinions but needs validation. May produce noisier propositions than briefs because judicial writing is more elliptical.

   **LePaRD `destination_context` quality caveat (from Pilot A):** LePaRD's preceding-paragraph text is noisier than expected as a proposition source. A non-trivial fraction of sampled propositions were paragraph fragments rather than coherent legal claims; a few caused Sonnet 4.6 to flag the prompt as a possible injection attempt. When using LePaRD as a supplementary data source, either: (a) extract a single trimmed sentence from `destination_context`, or (b) prefer parentheticals with holding/finding/concluding/noting verbs over preceding-context. Option (b) aligns with the fresh-mining approach already adopted as primary and sidesteps the fragment problem entirely. See `benchmark/pilot_a/summary.md`.
4. **Lexical-dissimilarity threshold** — Threshold value for the quality gate. Too high excludes valid examples; too low lets keyword-matching shortcut succeed. Calibrate on a held-out validation slice.
5. **Headline summary score** — Whether to ship a weighted summary number alongside the breakdown. Tension between leaderboard sortability and not reproducing single-number-misleadingness.
6. **State-fork audit signal** — Whether to add a "validated" badge for state forks that meet quality bars. Risks recentralizing the referee role; benefits reliability. Likely defer to whenever a second fork exists.

## Why this is well-suited to this repo

The technical lift is small because the heavy machinery already exists:

- `parser.py` extracts citations from arbitrary text (eyecite + regex + abbreviation normalization)
- `verifier.py` does the existence and name-match checks
- `brief_pipeline.py` Phase 2 substance assessor is exactly the equivalence oracle the scorer needs
- `state_reporter_map.py` and `court_map.py` give the harness jurisdiction-awareness for state forks from day one
- CL infrastructure is already wired; corpus access is solved

The new code is mostly orchestration: dataset schema, mining script, prompt templates, scorecard formatting, repo scaffolding for the kit.

## What this is *not*

- Not a leaderboard with a central referee. The repo doesn't decide who's on top.
- Not a vendor compliance audit. We do not require vendor cooperation; we score whatever raw outputs are submitted.
- Not a measurement of "lawyer accuracy." The gold is what a published opinion cited, not what a careful lawyer would conclude is the right answer.
- Not a replacement for [LegalBench](https://hazyresearch.stanford.edu/legalbench/) or [CLERC](https://aclanthology.org/2025.findings-naacl.441/) — it complements them by addressing open-corpus retrieval against real propositions, which neither does.

## References

- [LegalBench](https://hazyresearch.stanford.edu/legalbench/)
- [CaseHOLD](https://reglab.stanford.edu/data/casehold-benchmark/)
- [Large Legal Fictions (Dahl et al. 2024)](https://arxiv.org/abs/2401.01301)
- [Hallucination-Free? (Magesh et al. 2025)](https://onlinelibrary.wiley.com/doi/full/10.1111/jels.12413)
- [CLERC (NAACL 2025)](https://aclanthology.org/2025.findings-naacl.441/)
- [A Reasoning-Focused Legal Retrieval Benchmark](https://reglab.github.io/legal-rag-benchmarks/)
- [Isaacus Legal RAG Bench](https://huggingface.co/datasets/isaacus/legal-rag-bench)
- [CaseFacts (2026)](https://arxiv.org/abs/2601.17230)
- [Vals VLAIR](https://www.vals.ai/vlair)
- [Free Law Project Citator progress report](https://free.law/2025/05/01/citator/)
- [The AI Benchmarking Tightrope (Artificial Lawyer)](https://www.artificiallawyer.com/2025/05/15/the-ai-benchmarking-tightrope-moving-from-good-intentions-to-gold-standards/)
