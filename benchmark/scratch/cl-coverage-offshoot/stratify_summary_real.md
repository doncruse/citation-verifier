# Step 3 — stratification summary

- Valid citations loaded: 1148
- After short-form filter: 1042 (dropped 106)
- After foreign filter: 1042 (dropped 0)
- After dedup: 997 (removed 45)
- After K=5 cap per (citing_cluster, cited_tier): 618 (dropped 379)
- Stratified sample: 250 rows (target 250)

## Pool distribution by cited tier

| tier | n in pool | target | sample |
|---|---|---|---|
| SCOTUS | 121 | 50 | 50 |
| Circuit | 210 | 50 | 50 |
| State_COLR | 73 | 50 | 50 |
| State_IAC | 60 | 50 | 50 |
| Federal_District | 152 | 50 | 50 |
| Other | 2 | — | (not sampled) |

## Per-target-tier yield from this cohort

Pool drawn from 79 citing opinions (after cap).
- SCOTUS: 121/79 = 1.53 per opinion
- Circuit: 210/79 = 2.66 per opinion
- State_COLR: 73/79 = 0.92 per opinion
- State_IAC: 60/79 = 0.76 per opinion
- Federal_District: 152/79 = 1.92 per opinion

## Caveats
- Regional reporters (A.3d, P.3d, N.E.3d, etc.) default to State_COLR; actual COLR/IAC split waits on step 4 CL lookup.
- Hallucinated citations (~175, ~13.5% of LLM output) are excluded by using citations_valid only.
- Citing-court mix: 60 federal + 18 state opinions, with deliberate gaps on cal/nysd/texapp (see size_probe_2026-05-14.md and the mining commit).
