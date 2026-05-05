# Case Law Retrieval Benchmark v1 — Scorecard (deduped)

**N per model:** 130  
**Models:** Sonnet 4.6, Opus 4.7, GPT-5  
**Eval mode:** closed-book  
**Substance assessor:** Opus 4.7

**Note:** This scorecard runs on the deduplicated subset. The mining pass produced ~10x duplication of each parenthetical inside its source opinion (eyecite picking up the same citation in multiple forms), and 35% of the v1 dataset rows turned out to be duplicates of others. Numbers below run on the unique (proposition, gold_cite) cells only — N is per-model unique propositions, not the original 200.

**Note:** GPT-5 ran with provider-default temperature (1) — the API rejects temperature=0. Claude models also use provider
default. Temperature comparability is a known caveat, not a
comparability gate.

## Per-model headlines

| Model | % Green | Hallucination rate | UNKNOWN rate | Right-case rate |
|---|---:|---:|---:|---:|
| sonnet | 31.5% | 12.9% | 52.3% | 8.5% |
| opus | 36.2% | 20.0% | 26.9% | 13.8% |
| gpt-5 | 46.2% | 16.5% | 6.9% | 14.6% |

## Pairwise diffs (Green rate, 95% CI via 5000-sample bootstrap)

| Pair | Green diff | 95% CI |
|---|---:|---|
| opus − sonnet | +4.6pp | [-6.9, +16.2] |
| opus − gpt-5 | -10.0pp | [-21.5, +1.5] |
| sonnet − gpt-5 | **-14.6pp** | [-26.2, -3.1] |

Bold pairs have CI excluding zero (statistically distinguishable).

## Per-district breakdown (Green rate)

| Model | cand | dcd | ilnd | mad | txsd |
|---|---:|---:|---:|---:|---:|
| sonnet | 47.1% | 25.0% | 26.9% | 20.7% | 50.0% |
| opus | 52.9% | 22.2% | 42.3% | 20.7% | 59.1% |
| gpt-5 | 64.7% | 30.6% | 61.5% | 24.1% | 68.2% |