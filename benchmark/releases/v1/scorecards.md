# Case Law Retrieval Benchmark v1 — Scorecard

**N per model:** 200  
**Models:** Sonnet 4.6, Opus 4.7, GPT-5  
**Eval mode:** closed-book  
**Substance assessor:** Opus 4.7

**Note:** GPT-5 ran with provider-default temperature (1) — the API rejects temperature=0. Claude models also use provider
default. Temperature comparability is a known caveat, not a
comparability gate.

## Per-model headlines

| Model | % Green | Hallucination rate | UNKNOWN rate | Right-case rate |
|---|---:|---:|---:|---:|
| sonnet | 31.0% | 12.8% | 53.0% | 11.5% |
| opus | 37.0% | 16.7% | 22.0% | 14.0% |
| gpt-5 | 51.0% | 17.0% | 6.0% | 16.5% |

## Pairwise diffs (Green rate, 95% CI via 5000-sample bootstrap)

| Pair | Green diff | 95% CI |
|---|---:|---|
| opus − sonnet | +6.0pp | [-3.0, +15.5] |
| opus − gpt-5 | **-14.0pp** | [-23.5, -4.5] |
| sonnet − gpt-5 | **-20.0pp** | [-29.5, -10.5] |

Bold pairs have CI excluding zero (statistically distinguishable).

## Per-district breakdown (Green rate)

| Model | cand | dcd | ilnd | mad | txsd |
|---|---:|---:|---:|---:|---:|
| sonnet | 42.5% | 27.5% | 22.5% | 17.5% | 45.0% |
| opus | 57.5% | 22.5% | 40.0% | 15.0% | 50.0% |
| gpt-5 | 65.0% | 32.5% | 65.0% | 25.0% | 67.5% |