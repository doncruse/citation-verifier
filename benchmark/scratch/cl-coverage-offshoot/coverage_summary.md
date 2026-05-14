# Pilot coverage results

- Citations looked up: 158
- In CL (any non-NOT_FOUND status): 127
- NOT_FOUND (real CL gap or fabrication — needs spot-check): 31 (19.6%)

## Per status breakdown

| status | n | % |
|---|---|---|
| VERIFIED | 124 | 78.5% |
| LIKELY_REAL | 0 | 0.0% |
| POSSIBLE_MATCH | 3 | 1.9% |
| NOT_FOUND | 31 | 19.6% |

## Per opinion

| tier | cluster | case | total | in_cl | miss_rate |
|---|---|---|---|---|---|
| Circuit_9th | 4695642 | Joseph Wojcicki v. SCANA Corporation | 36 | 35 | 2.8% |
| Circuit_DC | 2807857 | Randy Brown v. Whole Foods Market Group, Inc | 22 | 20 | 9.1% |
| SCOTUS | 118395 | Bush v. Gore | 16 | 11 | 31.2% |
| State_COLR | 2585895 | Caceci v. Di Canio Construction Corp. | 66 | 45 | 31.8% |
| State_IAC | 4236900 | People v. Smith | 18 | 16 | 11.1% |

## Next step

Manually inspect the 31 NOT_FOUND rows in `coverage_per_citation.csv` — for each, decide whether it's a real CL gap or a model fabrication. (Google the cited_case_name; if it's a real published case, count as CL gap.)