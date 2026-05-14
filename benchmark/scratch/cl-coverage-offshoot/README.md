# CL Coverage Offshoot

**Status:** active (started 2026-05-13)
**Goal:** Measure CourtListener coverage of cited cases, stratified across SCOTUS / Circuit / State COLR / State IAC.
**Target:** 50/50/50/50 = 200 cited-case sample. Each row is a (proposition, cited_case) pair captured as written from a citing opinion.

This is a methodology offshoot — not v1.3, not v2. Lives entirely under this folder. After it concludes, if any helper is reusable, it gets promoted out.

## Why not CL parentheticals

CL's `parentheticals-*.csv.bz2` bulk file has every parenthetical CL has extracted, but each row's `described_opinion_id` is a foreign key to a CL opinion. So the cited case is in CL by construction. Useful for many things; useless for coverage measurement (every row is a 100% hit). The 273 MB bz2 sitting in `../parenthetical-probe/` was downloaded before this was clarified — leaving it for now in case useful elsewhere; not part of this offshoot.

## Why not v1's existing cases table

v1 prefiltered citations to "CL resolves" before storing them in `gold.db.cases`. So the 386 cases in the table are all CL-resolved by construction (same circularity as parentheticals).

## What we're using instead

[`benchmark/releases/v1/_raw_pool.json`](../../releases/v1/_raw_pool.json) — v1's raw mined pool from 6 federal districts (dcd, cand, txsd, ilnd, nysd, mad) over 2026-01-01 to 2026-04-30. 3,070 raw rows → 307 unique after dedup on `(citing_cluster, citation_text, parenthetical)`. Every row has `v_status` from v1's verifier already populated, so the file is already a coverage-measurement dataset for v1's federal-source mix.

## v1 raw pool — per-tier yield (initial scan, 2026-05-13)

| Tier | (system, level) | n | NOT_FOUND | POSS_MATCH | Miss rate |
|---|---|---|---|---|---|
| SCOTUS | (federal, colr) | 26 | 0 | 0 | 0.0% |
| Circuit | (federal, iac) | 132 | 10 | 1 | 8.3% |
| State COLR | (state, colr) | 4 | 2 | 0 | 50% |
| State IAC | (state, iac) | 2 | 0 | 0 | 0% |
| Federal trial | (federal, trial) | 73 | 52 | 1 | 72.6% |
| Federal (none) | (federal, None) | 38 | 21 | 0 | 55.3% |
| State (other) | (state, None/gjc/ljc) | 15 | 1 | 0 | 6.7% |
| Unknown | — | 17 | 5 | 1 | 35.3% |
| **All** | | **307** | **91** | **3** | **30.6%** |

`NOT_FOUND` ≠ "not in CL" — v1's verifier has false negatives (eyecite mis-extraction, name-mismatch on real cases, paren-attribution bug at ~3–12% rate). These rates are an upper bound on true CL miss rates. Step 2 (re-verify with current verifier) refines them.

## Plan (revised after step 2 discoveries)

Step 2 surfaced a methodology question: the current `verify_batch` is strict on name matching and downgrades many citations from VERIFIED to LIKELY_REAL / POSSIBLE_MATCH even when CL has them. Worse, some "NOT_FOUND" rows are bad input data (eyecite paren-attribution bug: wrong year, truncated case name) rather than real CL gaps. Re-extracting citations from source opinions with an LLM bypasses these issues.

| Step | Action | Status |
|---|---|---|
| 1 | Extract SCOTUS + Circuit dedup rows from v1 raw pool | ✅ Done |
| 2 | Re-verify 158 with current verifier; analyze v1-vs-current diff | ✅ Done — revealed eyecite input bugs & verifier-strictness changes |
| 3 | **LLM citation extractor via `claude -p` sonnet** — bypass eyecite bugs by re-extracting citations from CL-resident opinion text | In progress |
| 3a | Pilot extractor on 5 opinions across tiers; measure cost, time, "hallucination" (= cite-not-in-source) rate | ✅ Done; 3 of 5 timed out at 240s — bumped to 900s |
| 3b | Re-run timeouts with 900s; reclassify successful extractions to new schema | In progress (bg task) |
| 4 | CL lookup pass: feed every extracted citation through `verify_batch(quick_only=True)` and bucket VERIFIED / LIKELY_REAL / POSSIBLE_MATCH / NOT_FOUND | Script ready (`06_lookup_coverage.py`); waiting on step 3b |
| 5 | Audit pilot NOT_FOUND list — distinguish real CL gaps from model fabrications | TODO |
| 6 | Scale to full coverage measurement (target 200 cited citations stratified 50/50/50/50) | TODO |

## Files

| File | Purpose |
|---|---|
| `01_extract_v1_scotus_circuit.py` | Step 1 |
| `v1_scotus_circuit.csv` | Step 1 output: 158 dedup rows from v1 raw pool |
| `02_reverify.py` | Step 2: re-verify v1 rows with current verifier |
| `reverify_results.csv` | Step 2 output: old + new `v_status` per row |
| `reverify_summary.md` | Step 2 narrative — surfaced verifier-strictness and eyecite-input issues |
| `extract_citations.py` | LLM extractor module (claude -p sonnet, 900s timeout) |
| `03_pilot_extraction.py` | Step 3a: pilot extractor on 5 opinions across tiers |
| `04_rerun_timeouts.py` | Step 3b: re-run timed-out opinions with bumped timeout |
| `05_reclassify_existing.py` | Bring older 2-bucket extractions to the new 3-bucket schema |
| `06_lookup_coverage.py` | Step 4: CL lookup on all extracted citations, per-tier coverage table |
| `pilot_opinions/` | Raw opinion text for each pilot cluster (one .txt per cluster_id) |
| `pilot_extractions/` | LLM extraction output (one .json per cluster_id) |
| `pilot_summary.csv` / `.md` | Pilot run stats |
| `reclassified_summary.csv` | Pilot citation classification: appears / near_miss / not_in_source |
| `coverage_per_citation.csv` / `coverage_per_opinion.csv` / `coverage_summary.md` | Step 4 outputs (when run) |

## Design decisions (settled 2026-05-13)

### Per-opinion citation cap: K=5

For each (citing_opinion, cited_tier), keep at most 5 cited citations in the stratified pool. Reason: prevents one chatty opinion (e.g. a SCOTUS opinion citing 100 prior SCOTUS cases) from dominating its tier; gives meaningful row-level statistical independence without being wasteful. Within an opinion below cap, take all citations. Dedup at `(citing_cluster, citation_text, parenthetical)` first, then apply cap.

### Citing-opinion source: mixed federal + state

- **Federal citing opinions**: yield ~0.7 SCOTUS-cited, ~4 Circuit-cited, ~0.1 State-COLR-cited, ~0.05 State-IAC-cited per opinion (estimated from v1 raw pool).
- **State citing opinions**: yield more state-cited cases (state high-court / IAC opinions cite their own state's COLR and IAC heavily — estimated 5-15 per opinion before cap, ~5 after K=5 cap).

Federal-only mining can't reach 50 state-cited from any realistic volume (~500-1000 federal opinions needed per state tier). Mixed sources are required to hit the 50/50/50/50 target.

Citing-side bias to disclose in writeup: mixed source means we're measuring CL coverage across "what federal-and-state courts cite," not "what federal courts cite" or "what state courts cite" in isolation. Different question than v1, but useful for the cross-tier comparison.

### Volume target (rough)

- ~70-100 federal citing opinions (for SCOTUS + Circuit cited; also yield incidental state)
- ~15-25 state citing opinions (for State-COLR + State-IAC cited)
- Total ~85-125 citing opinions
- After dedup + K=5 cap: ~200-400 distinct cited citations in the pool
- Stratified sample 50 per cited tier → 200 final rows

The final 200 will have an uneven distribution of *citing-tier* (most rows will come from federal citing opinions, with a heavy concentration of state-cited rows coming from state citing opinions). This is a known property of the design, not a bias to fix.

## Pipeline (revised)

1. Mine citing opinions (~100 across federal + state)
2. LLM-extract all citations from each (`extract_citations.py`)
3. Dedup at `(citing_cluster, citation_text, parenthetical)` within and across opinions
4. Tier-classify each cited citation by reporter pattern
5. Apply K=5 cap per `(citing_cluster, cited_tier)`
6. Stratified sample 50 per cited-tier → 200 rows
7. `verify_batch(quick_only=True)` against CL for each → coverage status
8. Manual audit of NOT_FOUND rows → separate real CL gaps from fabrications
9. Report per-tier miss rate

## Caveats to disclose in any writeup

1. NOT_FOUND from `verify_batch(quick_only=True)` can be either a real CL gap or a model fabrication. Manual audit splits them.
2. Citing-side opinions sourced from CL — modest bias toward citation patterns of well-covered courts.
3. Mixed citing-source (federal + state) — see "Citing-opinion source" decision above.
4. K=5 per-opinion cap chosen as a balance between independence and yield; sensitivity to K not measured.
5. Sonnet 4.6 via `claude -p` runs at temperature=1.0 (CLI default; no flag exposed). Extraction variance unknown but lower than the ~13% measured for assessor verdicts. Re-running a subset to measure would be a useful follow-up.
