# Stratification summary

- Total citations extracted: 158
- After intra-opinion dedup: 157
- After K=5 cap per (citing_opinion, cited_tier): 51

## Pool distribution by cited tier

| tier | n in pool | target | sample |
|---|---|---|---|
| SCOTUS | 14 | 50 | 14 |
| Circuit | 10 | 50 | 10 |
| State_COLR | 10 | 50 | 10 |
| State_IAC | 5 | 50 | 5 |
| Federal_District | 0 | — | (not sampled) |
| Other | 12 | — | (not sampled) |

## Volume needed to hit 50/50/50/50

Current pool from 5 citing opinions. Per-citing-opinion yield:
- SCOTUS: 14/5 = 2.80 per opinion → need 18 citing opinions for 50
- Circuit: 10/5 = 2.00 per opinion → need 25 citing opinions for 50
- State_COLR: 10/5 = 2.00 per opinion → need 25 citing opinions for 50
- State_IAC: 5/5 = 1.00 per opinion → need 50 citing opinions for 50

Caveats:
- Regional reporters (A.3d, P.3d, N.E.3d, etc.) default to State_COLR — actual COLR/IAC split won't be known until CL lookup.
- Mixed citing-opinion source (federal + state) gives different yields per tier than federal-only. State citing opinions will dominate State_COLR + State_IAC yield.
