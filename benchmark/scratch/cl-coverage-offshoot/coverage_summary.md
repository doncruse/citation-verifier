# Step 4 — coverage results (pre-audit)

- Sample size: 200
- In CL (any status != NOT_FOUND): 157
- NOT_FOUND (real gap OR extraction artifact): 43 (21.5%)

**NOT_FOUND is an upper bound on the true CL gap rate.** Step 5
audits each NOT_FOUND row to split real gaps from extraction noise
(LLM-mis-parsed cites, slip-opinion patterns, etc.). Final per-tier
coverage rate = (n - real_gaps) / n, computed after audit.

## Status breakdown — overall

| status | n | % |
|---|---|---|
| VERIFIED | 156 | 78.0% |
| LIKELY_REAL | 0 | 0.0% |
| POSSIBLE_MATCH | 1 | 0.5% |
| NOT_FOUND | 43 | 21.5% |

## Per-tier coverage (pre-audit)

| tier | n | VERIFIED | LIKELY_REAL | POSSIBLE_MATCH | NOT_FOUND | in_cl | NOT_FOUND % |
|---|---|---|---|---|---|---|---|
| SCOTUS | 50 | 47 | 0 | 0 | 3 | 47 | 6.0% |
| Circuit | 50 | 42 | 0 | 1 | 7 | 43 | 14.0% |
| State_COLR | 50 | 41 | 0 | 0 | 9 | 41 | 18.0% |
| State_IAC | 50 | 26 | 0 | 0 | 24 | 26 | 48.0% |

## Methodology notes

- `verify_batch(quick_only=True)`: CL citation-lookup API only. No
  search/RECAP fallback. We measure 'reporter cite indexed in CL',
  not 'findable by any method'.
- Cited tier assigned pre-lookup from reporter pattern + court_hint
  (Bluebook 10.4 parenthetical) — no CL data, no measurement bias.
- POSSIBLE_MATCH = citation found but case_name mismatch. Counts
  as in-CL for coverage but is a separate signal worth flagging.
