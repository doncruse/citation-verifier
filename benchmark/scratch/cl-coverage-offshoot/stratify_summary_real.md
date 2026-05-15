# Step 3 — stratification summary

- Valid citations loaded: 1122
- After short-form filter: 1021 (dropped 101)
- After foreign filter: 1021 (dropped 0)
- After dedup: 978 (removed 43)
- After K=5 cap per (citing_cluster, cited_tier): 611 (dropped 367)
- Stratified sample: 190 rows (target 200)

## Pool distribution by cited tier

| tier | n in pool | target | sample |
|---|---|---|---|
| SCOTUS | 121 | 50 | 50 |
| Circuit | 210 | 50 | 50 |
| State_COLR | 71 | 50 | 50 |
| State_IAC | 40 | 50 | 40 |
| Federal_District | 152 | — | (not sampled) |
| Other | 17 | — | (not sampled) |

## Per-target-tier yield from this cohort

Pool drawn from 75 citing opinions (after cap).
- SCOTUS: 121/75 = 1.61 per opinion
- Circuit: 210/75 = 2.80 per opinion
- State_COLR: 71/75 = 0.95 per opinion
- State_IAC: 40/75 = 0.53 per opinion

## Caveats
- Regional reporters (A.3d, P.3d, N.E.3d, etc.) default to State_COLR; actual COLR/IAC split waits on step 4 CL lookup.
- Hallucinated citations (~175, ~13.5% of LLM output) are excluded by using citations_valid only.
- Citing-court mix: 60 federal + 18 state opinions, with deliberate gaps on cal/nysd/texapp (see size_probe_2026-05-14.md and the mining commit).
