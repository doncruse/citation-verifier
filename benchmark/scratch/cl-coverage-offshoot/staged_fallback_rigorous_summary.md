# Step 4c — staged fallback (rigorous, multi-factor scoring)

Uses the verifier's `_process_results` (multi-factor name+court+date+docket scoring) 
and `_build_fallback_result` (which applies the LIKELY_REAL/POSSIBLE_MATCH thresholds 
PLUS a court-mismatch guard that forces NOT_FOUND when a reporter cite's court doesn't 
match the best candidate's court).

- NOT_FOUND rows from step 4 baseline: 74
- Stage A (opinion search) rescued: 35
- Stage B (RECAP search) rescued: 8
- Still NOT_FOUND after both fallbacks: 31

## Coverage progression by tier

| tier | n | citation_lookup | + opinion search | + RECAP | still NOT_FOUND | cov_after_opn | cov_after_recap |
|---|---|---|---|---|---|---|---|
| SCOTUS | 50 | 47 | +0 | +1 | 2 | 47/50 = 94.0% | 48/50 = 96.0% |
| Circuit | 50 | 43 | +1 | +0 | 6 | 44/50 = 88.0% | 44/50 = 88.0% |
| State_COLR | 50 | 41 | +2 | +1 | 6 | 43/50 = 86.0% | 44/50 = 88.0% |
| State_IAC | 50 | 26 | +8 | +0 | 16 | 34/50 = 68.0% | 34/50 = 68.0% |
| Federal_District | 50 | 19 | +24 | +6 | 1 | 43/50 = 86.0% | 49/50 = 98.0% |

## Overall

- citation_lookup baseline: 176/250 = 70.4%
- after opinion search:     211/250 = 84.4%
- after RECAP search:       219/250 = 87.6%
