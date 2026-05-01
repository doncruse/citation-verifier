# Case Law Retrieval Benchmark v1

A 3-model leaderboard on freshly-mined federal district-court parentheticals,
scored on Real / Name-match / Supports axes. Closed-book mode only.

**Spec:** [../docs/plans/2026-04-30-benchmark-v1-design.md](../docs/plans/2026-04-30-benchmark-v1-design.md)
**Predecessor pilot:** [../docs/plans/2026-04-26-benchmark-pilot-a.md](../docs/plans/2026-04-26-benchmark-pilot-a.md)
**Implementation plan:** [../docs/plans/2026-04-30-benchmark-v1-plan.md](../docs/plans/2026-04-30-benchmark-v1-plan.md)

## What's here

| File | Description |
|---|---|
| `dataset.csv` | The benchmark instrument — proposition + gold case per row, sampled across 5 federal districts |
| `_raw_pool.json` | Full mined pool per district (resolved + unresolved), for CL-coverage bias auditing |
| `outputs_sonnet.csv` | Claude Sonnet 4.6 closed-book responses |
| `outputs_opus.csv` | Claude Opus 4.7 closed-book responses |
| `outputs_gpt5.csv` | OpenAI GPT-5 closed-book responses |
| `results.csv` | Per-(model, example) cell with three-axis scoring |
| `scorecards.md` | Headline numbers + bootstrap CIs |

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

# Score (~30 min — Opus assessor on each real case)
venv/Scripts/python.exe tests/benchmark_v1/score.py

# Generate scorecard (instant)
venv/Scripts/python.exe tests/benchmark_v1/scorecard.py
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
