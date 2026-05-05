# Case Law Retrieval Benchmark — v1 Design

**Status:** Design, ready for implementation plan.
**Parent design:** [2026-04-26-case-law-benchmark-design.md](2026-04-26-case-law-benchmark-design.md)
**Predecessor pilot:** [2026-04-26-benchmark-pilot-a.md](2026-04-26-benchmark-pilot-a.md), results in [benchmark/pilot_a/summary.md](../../benchmark/pilot_a/summary.md)
**Date:** 2026-04-30

## What v1 produces

A 3-model leaderboard on 200 freshly-mined federal district-court parentheticals, scored on three axes by Opus 4.7. Single eval mode (closed-book, no tools). Out-of-pocket budget: **~$10–15 for GPT-5** (OpenAI direct API). Sonnet 4.6, Opus 4.7, and the Opus assessor run through `claude -p` against the Claude Code subscription quota — no separate billing — but consume ~700 Claude calls' worth of quota in a tight burst.

The contribution is the **scorecard plus dataset**, not a forkable kit. The kit comes in v1.1 once we have a working reference implementation worth pointing forks at.

## Scope decisions

Decisions locked during 2026-04-30 brainstorming, with rationale:

| Decision | Choice | Why |
|---|---|---|
| Sample size (N) | **200** | Pilot A used 50/cell; doubling per-cell to 200 narrows CIs without overspending |
| Court level | **Districts only** | Matches Pilot A's contamination signal; circuits + SCOTUS deferred to v2 |
| Districts | **DDC, CAND, TXSD, ILND, NYSD** (5) | Geographic + caseload diversity; DDC reuses Pilot A data |
| N per district | **40 each** (stratified) | Guarantees coverage; pooled-random risks one-district dominance |
| Date range | **filed 2026-01-01 to 2026-04-30** | Post-training-cutoff for all 3 models (verify in build step) |
| Models | **Sonnet 4.6, Opus 4.7, GPT-5** | Two Anthropic + one obvious frontier competitor |
| Eval mode | **Closed-book only** | Web-search and tool-augmented modes deferred to v1.1 |
| Substance assessor | **Opus 4.7** | "Marking your own homework" objection answered; ~$30 more than Sonnet |
| Scoring axes | **Real, Name-match, Supports** (3) | Currency + jurisdictional-appropriateness deferred to v1.1 |
| Forkable kit | **Deferred to v1.1** | Federal-layer data is the kit's reference implementation |

## Sample construction

5 federal districts, **40 examples each**, stratified.

| District | Role |
|---|---|
| **DDC** (D.C.) | Admin/agency-law heavy; data already mined for Pilot A |
| **CAND** (N.D. Cal.) | Tech/IP heavy, large docket |
| **TXSD** (S.D. Tex.) | Criminal/immigration heavy |
| **ILND** (N.D. Ill.) | Diversified commercial |
| **NYSD** (S.D.N.Y.) | Securities/commercial |

If NYSD is empty after the precedential-status fix (Pilot A's probe found 0 with default filter; `stat_Unknown=on` should resolve, but verify), swap to **MAD** (D. Mass.) or **PAED** (E.D. Pa.).

**Date range:** `filed_after=2026-01-01&filed_before=2026-04-30`. The build step verifies each model's training cutoff is on or before 2025-12-31; push the start date forward if any model's cutoff is later than expected.

**Mining filter:** reuse Pilot A's parenthetical extractor (`build_fresh_dc_sample.py`), parameterized over court IDs. Same constraints:

- Parenthetical 15–80 words
- Starts with holding-style verb (holding, finding, concluding, noting, explaining, stating, recognizing, ...) — full list in Pilot A code
- Cited case verifies via `citation-verifier` (`VERIFIED` or `LIKELY_REAL`, batch lookup with `quick_only=True`)
- Aggressive whitespace normalization on opinion plain_text (Pilot A finding)

**CL search query:** `type=o&court={id}&filed_after=...&filed_before=...&stat_Published=on&stat_Unknown=on&order_by=dateFiled%20desc`. The `stat_Unknown=on` flag is required (Pilot A finding).

**Sample size validation:** before sampling, the verified pool per district should be ≥80 to allow random selection of 40 with margin. If a district yields fewer, document and proceed with what's available; the v1 dataset is allowed to be sub-200 if a district under-delivers.

## Models scored

| Model | API path |
|---|---|
| Claude Sonnet 4.6 | `claude -p --model sonnet` (matches Pilot A) |
| Claude Opus 4.7 | `claude -p --model opus` |
| GPT-5 | OpenAI Python SDK (`pip install openai`), uses `OPENAI_API_KEY` from `.env` |

All three call paths share one Python interface in `model_adapter.py` so `run_model.py --model {name}` is symmetric. Closed-book, same prompt template as Pilot A.

**Per-provider quirks** (verified 2026-04-30):

- **Sonnet/Opus** (via `claude -p`): temperature defaults to model default; we do not set explicitly. (Claude CLI doesn't expose temperature; matches Pilot A.)
- **GPT-5** (via OpenAI SDK): temperature **must be omitted** — GPT-5 only accepts the default (1) and rejects `temperature=0` with a 400. `max_completion_tokens` must be ≥ 2000 because GPT-5 consumes reasoning tokens out of the same budget; with the default budget responses are silently empty. The actual model id resolved at call time is recorded per-row in `outputs_gpt5.csv` for reproducibility (e.g. `gpt-5-2025-08-07`).

The benchmark accepts that GPT-5 runs at temperature 1 while Claude runs at provider default — this is a methodology footnote in the scorecard, not a comparability gate.

Prompt template (same as Pilot A):

```
You are a legal research assistant. I will give you a legal proposition.
Name a US federal case that supports it.

Respond ONLY with the case name and citation, in this format:
<Case Name>, <Volume> <Reporter> <Page> (<Court> <Year>)

Do not include any explanation, parenthetical, or commentary. If you do
not know a supporting case, respond with "UNKNOWN".

Proposition: {proposition}
```

The Claude calls run from a hermetic temp dir (Pilot A finding — repo CLAUDE.md leaks role-confusion otherwise).

## Scoring

Three axes per (model, example) cell:

| Axis | Method |
|---|---|
| **Real** | `citation-verifier` existence check on the model's extracted citation |
| **Name match** | `CaseNameMatcher.calculate_similarity` ≥ 0.65 between model's named case and CL's resolved name |
| **Supports** | Opus 4.7 substance assessor — given proposition + model's named case + downloaded opinion text (≤20K chars), returns Green / Yellow / Red |

Per-axis bootstrap 95% CIs on pairwise model differences.

The substance assessor runs **only when Real == Y** (no point judging support if the case isn't real). Single-shot Opus call per (model, example) cell where applicable. Opinion-text cache is shared across cells (same case across multiple model outputs hits the cache).

Headline metrics in scorecard:

- **% Green** per model
- **Hallucination rate** per model (Real == N OR Name == N, denominator excludes UNKNOWN responses)
- **UNKNOWN rate** per model
- **Pairwise Green-rate diffs with 95% CIs** (3 pairs: Sonnet-Opus, Sonnet-GPT5, Opus-GPT5)

## Output artifacts

```
benchmark/releases/v1/
├── dataset.csv          # 200 rows, frozen, the benchmark instrument
├── outputs_sonnet.csv   # 200 rows, raw model responses
├── outputs_opus.csv     # 200 rows, raw model responses
├── outputs_gpt5.csv     # 200 rows, raw model responses
├── results.csv          # 600 rows (200 × 3), per-cell scoring
├── scorecards.md        # aggregate tables + CIs + decision call-outs
└── README.md            # reproduction instructions, scope, caveats
```

`benchmark/releases/v1/` lives at repo root, not under `scratch/` — this is a published artifact, not working state.

## Code organization

New module `benchmark/runners/` mirroring Pilot A's separately-runnable script pattern:

| Script | Purpose |
|---|---|
| `build_dataset.py` | Mine 40 parens × 5 districts → `benchmark/releases/v1/dataset.csv` |
| `model_adapter.py` | Unified call interface (Claude CLI + OpenAI SDK) |
| `run_model.py --model {sonnet,opus,gpt-5}` | One model run; writes `benchmark/releases/v1/outputs_{model}.csv` |
| `score.py` | Joins all model outputs + runs Opus assessor → `benchmark/releases/v1/results.csv` |
| `scorecard.py` | Aggregate `results.csv` → `benchmark/releases/v1/scorecards.md` |

Each script independently re-runnable. Mid-run failures don't lose work. Opinion-text cache reuses Pilot A's at `benchmark/pilot_a/cited_opinion_cache/` (avoids re-fetching the same case across model cells).

## Explicitly NOT in v1

Listed so future contributors know what's intentionally deferred:

- Forkable kit scaffolding (SCHEMA.md, MINING_PLAYBOOK.md, QUALITY_GATES.md, PROMPT_TEMPLATES/, scoring/, SUBMISSION.md) — v1.1 once federal layer is stable
- Web-search and tool-augmented eval modes — v1.1
- Currency axis (good-law check) — v1.1; needs CL citator data integration
- Jurisdictional-appropriateness axis — v1.1; needs court-hierarchy rules
- LePaRD as supplementary data — deferred indefinitely; Pilot A found `destination_context` too noisy
- Circuits and SCOTUS — v2
- State-law forks — v2
- Lexical-dissimilarity quality gate (parent spec §QualityGates) — v1.1
- Acceptable-alternatives caching — v1 just records (model, gold, alternative-found-by-Opus); v1.1 adds the cache structure

## Open questions resolved at design time

These were 6 open methodological questions in the parent spec; v1 takes a position:

1. **Corpus age window** → `2026-01-01` to `2026-04-30`, 4-month window. Will widen if pool is too small.
2. **Court level distribution** → districts only in v1; explicit sub-tier deferred.
3. **Proposition extraction** → parentheticals only (Pilot A: `destination_context` is noisy).
4. **Lexical-dissimilarity threshold** → not enforced in v1; record raw similarity in `dataset.csv` for later filtering.
5. **Headline summary score** → no single number; multi-axis breakdown is the contribution.
6. **State-fork audit signal** → N/A, no state forks in v1.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| GPT-5 cutoff is later than 2025-12-31 | Verified 2026-04-30: gpt-5-2025-08-07 has Aug 2025 cutoff; safe |
| GPT-5 quirks (temperature, token budget) | Documented above; model_adapter handles per-provider |
| NYSD still empty after `stat_Unknown` | Documented swap to MAD or PAED |
| One district's verified pool < 80 | Documented graceful degrade; v1 dataset can be < 200 |
| Opus assessor and Sonnet assessor disagree systematically | Out of scope for v1; calibration study is v1.2 |
| GPT-5 API cost overrun | Hard cap at $30 out-of-pocket; abort GPT-5 phase if blown |
| Claude Code quota burn | Glance at quota usage before kicking off; pause-and-resume if depleted |
| Mid-run interrupts | All scripts idempotent; outputs/{model}.csv written incrementally with flush |

## Cost estimate

Two ledgers — Claude calls hit the Claude Code subscription quota; GPT-5 is the only true out-of-pocket cost.

**Out-of-pocket (OpenAI direct API):**

| Component | Calls | Cost/call | Subtotal |
|---|---|---|---|
| GPT-5 model calls | 200 | $0.05 (est) | $10 |
| **Total out-of-pocket** | | | **~$10–15** |

Hard cap: abort GPT-5 phase if running total exceeds $30.

**Subscription quota (no separate billing, but counts against your usage):**

| Component | Calls | Notional cost/call | Notional subtotal |
|---|---|---|---|
| Sonnet model calls | 200 | $0.05 | $10 |
| Opus model calls | 200 | $0.15 | $30 |
| Opus assessor (real cases only, ~50%) | 300 | $0.15 | $45 |
| **Total quota usage** | **~700 calls** | | **~$85 notional** |

Pilot A reported $8.40 notional for 100 model + ~30 assessor calls; v1 scales that ~7×. Glance at quota usage before kicking off so the burst doesn't surprise you.

## Success criteria

V1 is shippable when:

- [ ] `benchmark/releases/v1/dataset.csv` has 200 rows (or documented < 200 with reason)
- [ ] All 3 models produce outputs for every dataset row (with UNKNOWN allowed)
- [ ] `benchmark/releases/v1/results.csv` has all (model, example) cells scored
- [ ] `benchmark/releases/v1/scorecards.md` shows the leaderboard with CIs
- [ ] At least one pairwise model diff has CI excluding 0 (otherwise v1 doesn't differentiate models)
- [ ] Reproduction instructions in README work from a clean clone

If the last criterion fails (no pairwise diff has CI excluding 0), v1 ships anyway with a note: "current frontier models are statistically indistinguishable on this dataset at N=200."
