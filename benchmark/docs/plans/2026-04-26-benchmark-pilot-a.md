# Pilot A — Contamination Test for Case Law Benchmark Data Source

**Status:** Plan, ready to execute.
**Parent design:** [2026-04-26-case-law-benchmark-design.md](2026-04-26-case-law-benchmark-design.md)
**Date:** 2026-04-26

## Question this pilot answers

Does sampling proposition-citation pairs from existing public datasets (LePaRD) produce a meaningfully easier benchmark than freshly mining them from federal district court opinions filed *after* model training cutoffs?

If **yes** (≥15 percentage point gap in model accuracy on fresh-mined vs. LePaRD), the parent spec should pivot to fresh mining — the contamination concern is real and the work is justified.

If **no** (within 5 pp), the parent spec should pivot to LePaRD + CL parentheticals — the work of fresh mining isn't buying us harder questions.

If **in between** (5-15 pp gap), run Pilot B (temporal stratification of LePaRD) before deciding.

## Method

```
┌──────────────────────┐    ┌─────────────────────────────┐
│ 50 LePaRD samples    │    │ 50 fresh district-court     │
│ (random, federal,    │    │ parentheticals from federal │
│  any year)           │    │ DC opinions filed Q1-Q2 2026│
└──────────┬───────────┘    └──────────────┬──────────────┘
           │                               │
           └───────────┬───────────────────┘
                       │
            standardized prompt template
            (closed-book, single model)
                       │
                       ▼
         Claude Sonnet 4.6 (no web access)
                       │
                       ▼
            citation extraction (eyecite)
                       │
                       ▼
       /verify-brief Phase 2 substance assessor
                       │
                       ▼
      per-example scorecard + aggregated stats
```

### Step 1 — Build the LePaRD sample

- Pull LePaRD from [HuggingFace / GitHub](https://github.com/rmahari/LePaRD)
- Random sample of 50 rows, no stratification (we want the natural distribution)
- For each row, extract: `proposition` (the preceding context, lightly trimmed to a single coherent statement), `gold_case` (the cited target passage's source case + citation), `citing_court`, `citing_year`
- Write to `benchmark/pilot_a/lepard_sample.csv`

### Step 2 — Build the fresh district-court sample

- Query CourtListener for opinions filed `2026-01-01` to `2026-04-25`, court level = district
- Download text for ~200 such opinions (oversampling because not every opinion has parentheticals)
- Run existing `parser.py` over each opinion's text, extract every `(citation, parenthetical)` pair where the parenthetical begins with `holding`, `finding`, `concluding`, `noting that`, etc.
- Filter: parenthetical must be ≥15 words and ≤80 words (excludes signal-only parentheticals like "(emphasis added)" and bloated string-cites)
- Filter: cited case must resolve via citation-verifier as VERIFIED or LIKELY_REAL
- Random sample of 50 from the filtered pool
- Write to `benchmark/pilot_a/fresh_dc_sample.csv` with same schema as LePaRD sample

### Step 3 — Standardized prompt template

```
You are a legal research assistant. I will give you a legal proposition.
Name a US federal case that supports it.

Respond ONLY with the case name and citation, in this format:
<Case Name>, <Volume> <Reporter> <Page> (<Court> <Year>)

Do not include any explanation, parenthetical, or commentary. If you do
not know a supporting case, respond with "UNKNOWN".

Proposition: {proposition}
```

No web access. No tool use. Single attempt per proposition.

### Step 4 — Run the model

- Model: Claude Sonnet 4.6 (matches what's already wired in `client.py`)
- Temperature: 0
- 100 calls total (50 LePaRD + 50 fresh DC)
- Capture raw output, tokens, latency

### Step 5 — Score each output on three axes

The full multi-axis scorer the parent spec proposes is overkill for the pilot. Score on the three axes that matter for the contamination question:

| Axis | How |
|---|---|
| **Real** | citation-verifier existence check on the extracted citation |
| **Name matches** | citation-verifier name matcher between extracted name and CL's resolved name |
| **Supports proposition** | `/verify-brief` Phase 2 substance assessor — give it the proposition + the model's named case + downloaded opinion text; record green/yellow/red |

Skip currency and jurisdictional-fit for the pilot — they don't move the contamination question.

### Step 6 — Compare

Compute, for each sample:

- **Headline accuracy**: % of outputs scoring green on Phase 2 (case substantively supports proposition)
- **Hallucination rate**: % where citation isn't real OR name doesn't match
- **"Right case" rate**: % where the extracted citation is the *gold* citation (strict; the user-facing benchmark wouldn't require this, but it's diagnostic)

Bootstrap 95% CIs on the difference between samples (small N, so reporting uncertainty matters).

## Decision rule

| Outcome | Spec revision |
|---|---|
| Fresh-DC headline accuracy is ≥15 pp lower than LePaRD | Pivot to fresh-mining as the spine. Contamination concern validated. |
| Difference is within 5 pp | Pivot to LePaRD + CL parentheticals. Save the mining work. |
| Difference is 5-15 pp | Run Pilot B (LePaRD stratified by citing year) before deciding. |
| Either sample's hallucination rate is so high (>40%) that the substance score is noisy | Note in the spec that closed-book mode is broken for legal retrieval and the with-web-access mode is the more interesting evaluation. |

## Deliverables

- `benchmark/pilot_a/lepard_sample.csv` — 50 examples, LePaRD-sourced
- `benchmark/pilot_a/fresh_dc_sample.csv` — 50 examples, freshly-mined district court
- `benchmark/pilot_a/results.csv` — one row per example with model output and three-axis scores
- `benchmark/pilot_a/summary.md` — short report: headline numbers, CIs, decision recommendation, anything surprising in the data

## Code organization

New module: `benchmark/pilot_a/`

- `benchmark/pilot_a/build_lepard_sample.py` — Step 1
- `benchmark/pilot_a/build_fresh_dc_sample.py` — Step 2
- `benchmark/pilot_a/run_model.py` — Steps 3-4 (loads both CSVs, prompts model, writes raw outputs)
- `benchmark/pilot_a/score.py` — Step 5 (loads outputs, runs three-axis scorer using existing pipeline)
- `benchmark/pilot_a/summarize.py` — Step 6 (CSV → summary stats + markdown report)

Each script is independently runnable so we can re-run any phase without redoing earlier work.

## Cost and time estimate

- Engineering time: ~half a day to write all five scripts and validate end-to-end on a 5-example smoke test
- Run time: ~30 minutes for the full 100-example evaluation
- API costs: ~$5-15 (100 Sonnet calls + ~100 Phase 2 Opus calls for substance assessment)
- CL data egress: trivial (~200 opinion texts)

## What this pilot is not

- Not the benchmark itself. It's diagnostic infrastructure to inform a spec revision.
- Not a model comparison. One model, one mode. We'd add models when we know the data is sound.
- Not a methodology study. We assume eyecite extraction and Phase 2 assessment are reasonably accurate; if they're not, the parent benchmark has bigger problems than the pilot can surface.

## Open questions to resolve before executing

1. **Which LePaRD field is the "proposition"?** LePaRD has `preceding_context` (paragraph before the citation) and `target_passage` (the cited text). Likely we want `preceding_context`, but it may need light cleanup to extract a single proposition. Inspect during Step 1.
2. **Should the fresh-DC sample exclude cases that have been cited many times?** The contamination concern is sharper for *less-cited* cases. But filtering on citation count adds complexity. Likely v1: don't filter; report citation-count distribution alongside results.
3. **Single model is enough?** Probably yes for go/no-go signal. If the chosen model happens to be unusually bad or good on legal tasks, results could mislead. Mitigation: pick Claude Sonnet 4.6 specifically because it's known to be strong at legal tasks per VLAIR — if it's contaminated on LePaRD, weaker models will be too.
