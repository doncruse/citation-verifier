# Step 4b — staged fallback rescue

- NOT_FOUND rows from step 4 baseline: 43
- Stage A (opinion search) rescued: 34
- Stage B (RECAP search) rescued: 3
- Still NOT_FOUND after both fallbacks: 6

## Coverage progression by tier

| tier | n | citation_lookup | + opinion search | + RECAP | still NOT_FOUND | cov_after_opn | cov_after_recap |
|---|---|---|---|---|---|---|---|
| SCOTUS | 50 | 47 | +3 | +0 | 0 | 50/50 = 100.0% | 50/50 = 100.0% |
| Circuit | 50 | 43 | +4 | +2 | 1 | 47/50 = 94.0% | 49/50 = 98.0% |
| State_COLR | 50 | 41 | +6 | +1 | 2 | 47/50 = 94.0% | 48/50 = 96.0% |
| State_IAC | 50 | 26 | +21 | +0 | 3 | 47/50 = 94.0% | 47/50 = 94.0% |

## Overall

- citation_lookup baseline: 157/200 = 78.5%
- after opinion search:     191/200 = 95.5%
- after RECAP search:       194/200 = 97.0%

## Methodology

- Score threshold for 'credible match': 0.5 (matches the verifier's internal cutoff)
- CaseNameMatcher: 4-factor weighted similarity (sequence / Jaccard / substring / key-words)
- Stage A queries: search_opinions(q=cited_case_name, filed_after=year-1, filed_before=year+1); falls back to no year window if empty
- Stage B queries: search_recap(q=cited_case_name); RECAP = PACER docket data, primarily federal
- Still NOT_FOUND rows after both stages are the strongest candidates for real CL gaps; step 5 audit still recommended.
