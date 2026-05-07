# Case Law Retrieval Benchmark v1

A 3-model leaderboard on freshly-mined federal district-court parentheticals,
scored on Real / Name-match / Supports axes. Closed-book mode only.

**Spec:** [../docs/plans/2026-04-30-benchmark-v1-design.md](../docs/plans/2026-04-30-benchmark-v1-design.md)
**Predecessor pilot:** [../docs/plans/2026-04-26-benchmark-pilot-a.md](../docs/plans/2026-04-26-benchmark-pilot-a.md)
**Implementation plan:** [../docs/plans/2026-04-30-benchmark-v1-plan.md](../docs/plans/2026-04-30-benchmark-v1-plan.md)

## Headlines (v1 results)

200 examples per model, single closed-book run, scored by Opus 4.7. Numbers
below are after a post-run dedup audit that found 35% of the 200 rows were
duplicates of other rows (mining-stage bug). Effective N is 130 unique
propositions per model.

| Model | % Green | Hallucination rate | UNKNOWN rate |
|---|---:|---:|---:|
| Sonnet 4.6 | 31.5% (41/130) | 12.9% (8/62) | 52.3% (68/130) |
| Opus 4.7 | 36.2% (47/130) | 20.0% (19/95) | 26.9% (35/130) |
| **GPT-5** | **46.2%** (60/130) | 16.5% (20/121) | 6.9% (9/130) |

GPT-5 leads on Green rate. Only one pairwise diff has 95% CI excluding zero
at this sample size:

| Pair | Green diff | 95% CI |
|---|---:|---|
| Opus − GPT-5 | −10.0pp | [−21.5, +1.5] |
| Sonnet − GPT-5 | **−14.6pp** | [−26.2, −3.1] |
| Opus − Sonnet | +4.6pp | [−6.9, +16.2] |

Sonnet's low hallucination rate is partly a denominator effect — its
52% UNKNOWN rate excludes most responses from the hallucination tally.
The recall (Green) vs precision (low Hallucination) tradeoff is the
shape of the leaderboard.

See `scorecards-deduped.md` for the deduped scorecard with per-district
breakdown; `scorecards.md` preserves the original inflated numbers.

## What's here

| File | Description |
|---|---|
| `dataset.csv` | The benchmark instrument — proposition + gold case per row, sampled across 5 federal districts |
| `_raw_pool.json` | Full mined pool per district (resolved + unresolved), for CL-coverage bias auditing. **Contains 3,070 rows but only 307 unique parentheticals — every parenthetical is duplicated ~10x by an eyecite full+short-cite mining bug.** Always dedup on `(citing_cluster_id, citation_text, parenthetical[:60])` before counting. The intra-opinion-dedup fix is v1.3 bugfix #2 (see `docs/plans/2026-05-05-v1.3-design.md` §Bugfixes). |
| `outputs_sonnet.csv` | Claude Sonnet 4.6 closed-book responses |
| `outputs_opus.csv` | Claude Opus 4.7 closed-book responses |
| `outputs_gpt5.csv` | OpenAI GPT-5 closed-book responses |
| `results.csv` | Per-(model, example) cell with three-axis scoring |
| `scorecards.md` | Original scorecard (inflated by mining-stage dedup bug; preserved for transparency) |
| `scorecards-deduped.md` | Corrected scorecard after dedup (the numbers cited in this README) |

## How to reproduce

Requires:
- Python 3.10+, repo's `venv/`
- `COURTLISTENER_API_TOKEN` and `OPENAI_API_KEY` in `.env`
- Claude Code CLI with active subscription (for `claude -p`)
- `openai>=1.40` (`pip install openai`)

```bash
# Build dataset (~30–60 min, hits CL throttle)
venv/Scripts/python.exe tests/benchmark_v1/build_dataset.py

# Run each model (~30 min each, idempotent — can resume)
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model sonnet
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model opus
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model gpt-5

# Score (~3 hr — Opus assessor on each real case)
venv/Scripts/python.exe tests/benchmark_v1/score.py

# Generate scorecards (instant)
venv/Scripts/python.exe tests/benchmark_v1/scorecard.py            # original numbers (scorecards.md)
venv/Scripts/python.exe tests/benchmark_v1/scorecard.py --dedupe   # corrected numbers (scorecards-deduped.md)
```

All scripts are idempotent — interrupted runs resume from where they left off.

## Methodology notes

**Sampling:** 40 examples per district from D.D.C., N.D. Cal., S.D. Tex.,
N.D. Ill., and a fifth district (NYSD if available, else MAD or PAED as
fallback). Stratified, not pooled-random — guarantees coverage.

**Date range:** filed 2026-01-01 to 2026-04-30. Post-training-cutoff for
all three models tested (Sonnet 4.6 ~Aug 2025, Opus 4.7 ~Jan 2025, GPT-5
~Sep 2024 to Aug 2025 depending on snapshot).

**Eval prompt:** identical for all three models — `tests/benchmark_v1/model_adapter.py`
holds the canonical version.

**Temperature:** Claude models use provider default (CLI doesn't expose it).
GPT-5 uses provider default (1) because the API rejects `temperature=0`.
Cross-provider temperature comparability is a known caveat documented in
the scorecard footer; not a comparability gate.

**Substance assessor:** Opus 4.7 judges Green/Yellow/Red on the assertion
"this case substantively supports this proposition" given the proposition,
the model's named case, and the cited opinion's text (≤ 20K chars).

## Methodology adjustments during the run

The run surfaced four issues that needed in-flight or post-run adjustments.
The first three were patched during the run; the fourth was caught by a
post-run audit and addressed by deduplicating the scoring data.

| Issue | Adjustment | Affects |
|---|---|---|
| GPT-5's spec-suggested 2000-token budget left ~67% of responses empty (every empty hit the budget exactly on reasoning) | Bumped to 8000 in `model_adapter.py` `_call_gpt5` | GPT-5's "answered" rate would have been ~33% under the original budget; now ~94% |
| Sonnet's 60s timeout cut off ~28% of calls (max OK call observed: 59.5s) | Bumped to 120s in `run_model.py` `TIMEOUT_S` | Sonnet's UNKNOWN rate would have included ~28% TIMEOUTs; now ~1% |
| CourtListener's citation-lookup API silently truncates the response at ~200 entries even when the request body is well within size limits | Patched `_batch_citation_lookup` in `verifier.py` to chunk by both char count (50K) and citation count (150) | All three models' real-rates were under-reported on the first scoring pass; GPT-5 (last in batch order) was hit hardest, going from real=4 to real=175 after the patch |
| Mining pass produced ~10× duplication of each parenthetical inside its source opinion (eyecite picking up the same citation in full + short forms); 35% of the sampled dataset turned out to be duplicates | Added `--dedupe` flag to `scorecard.py` to filter to canonical (proposition, gold_cite) cells before aggregating; published numbers run on this 130-row deduped subset (preserved at `scorecards-deduped.md`) | GPT-5's % Green dropped from 51.0% (inflated) to 46.2% (deduped); the Opus–GPT-5 pairwise CI shifted from clearly excluding zero to straddling it. v1.1 will fix the bug at the mining stage |

The chunking fix landed as `7eeb0a4`. The other adjustments are documented
inline in the adapter / runner / scorecard.

## Known biases (CL-coverage)

The benchmark filters to cases that resolve via CourtListener's citation-
lookup API. The full mined pool (in `_raw_pool.json`) includes both
resolved and unresolved parentheticals so the bias can be audited.

Pilot A's resolution rate was ~40%; v1's chunked verifier with quick_only
gets ~50–80% per district. Most unresolved cases appear to be real cases
with parsing/normalization mismatches (eyecite name extraction quirks,
reporter format edge cases) rather than missing-from-CL. Spot-checking
unresolved samples and quantifying the real-but-CL-missed rate is on the
v1.1 roadmap.

For closed-book v1 this bias mostly affects which propositions enter the
dataset. For future vendor-RAG evaluations (v1.1+), the bias becomes more
significant — vendors with broader-than-CL coverage get no credit for
breadth. A multi-source existence check (CL + Justia + Caselaw Access
Project) is the planned mitigation.

## Scope

**In v1:**
- 3 models, closed-book mode only
- Federal districts only (5 districts × 40 examples)
- 3 scoring axes (Real, Name-match, Supports)

**Deferred to v1.1:**
- Forkable kit scaffolding (SCHEMA.md, MINING_PLAYBOOK.md, etc.)
- Web-search and tool-augmented eval modes
- Currency axis (good-law check)
- Jurisdictional-appropriateness axis
- Multi-source existence oracle

**Deferred to v2:**
- Circuits and SCOTUS
- State-law forks

See spec for full design rationale.
