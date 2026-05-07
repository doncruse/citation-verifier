# State-Court Smoke Test — 2026-05-06

**Status:** complete
**Owner:** project lead
**Predecessor:** [`docs/plans/2026-05-05-v1.3-design.md`](../plans/2026-05-05-v1.3-design.md), §"State-court contingency rule"
**Artifacts:** [`benchmark/scratch/state-court-smoke-test/`](../../scratch/state-court-smoke-test/)
**Decision:** **Go** for 25/25/25/25 stratification, with two prerequisite infrastructure fixes called out below.

---

## Summary

| Metric | Result | Threshold | Status |
|---|---|---|---|
| Court resolvable to courts-db | 19/22 (86%) | ≥ 70% | PASS |
| Citation-verifier name match | 19/22 (86%) | (combined w/ above) | PASS |
| Full-text reachable in any format | 19/22 (86%) | ≥ 50% | PASS |
| Full-text via `plain_text` only | 2/22 (9%) | (informational) | trap — see fix #1 |

Both contingency thresholds met by wide margins. Recommend proceeding with state COLR + COA as the fourth tier in v1.3's 25/25/25/25 stratification.

## Method

1. Loaded v1's `_raw_pool.json` (3,070 candidate parentheticals across DCD/CAND/TXSD/ILND/MAD).
2. Filtered to state-tier candidates by reporter regex (regional + state-specific COLR/COA) AND by cited-court-id resolving to `(state, _)` via `gold_db.lookup_court()`, excluding `ljc`/`gjc` (limited / general trial-jurisdiction).
3. Deduped on `(citation_text, parenthetical[:60])` — same key v1.3's intra-opinion-dedup design uses.
4. Result: 22 unique items (target was 30; pool was thinner than expected — see "Volume" below). All 22 carried through, no further sampling.
5. For each item, ran the v1.3 verification flow:
   - Citation-verifier (already cached in raw_pool's `v_status`).
   - For matched items: fetched cluster, parsed `court_id`, called `lookup_court()` to confirm courts-db coverage.
   - Probed every opinion-text field (`plain_text`, `html_with_citations`, `html`, `html_lawbox`, `html_columbia`, `html_anon_2020`, `xml_harvard`), HTML-stripped, and recorded the longest non-empty representation.

## Findings

### 1. State-opinion text is in CL, but rarely as `plain_text` (FIX REQUIRED)

Of 19 verified state opinions:

| Best format | Count |
|---|---|
| `html_with_citations` | 9 |
| `html_lawbox` | 8 |
| `plain_text` | 2 |

**The `plain_text`-only path covers 9% of state opinions in the sample.** Falling back to HTML/XML lifts coverage to 86%. This finding has been rediscovered multiple times across this project (see [Recurring finding] below).

`citation_verifier.client._resolve_opinion_text_with_metadata` already falls back to `html_with_citations` + `html`, but **misses `html_lawbox`, `html_columbia`, `html_anon_2020`, and `xml_harvard`**. Those four account for roughly half the wins above. Fix tracked separately and applied alongside this retrospective.

### 2. courts-db `level` is uneven for state courts (CALLOUT, NOT BLOCKER)

courts-db returns `level=None` for several state COLR / COA courts that should be classifiable:

| court_id | system | level (courts-db) | Should be |
|---|---|---|---|
| `mont` | state | None | colr |
| `tex` | state | None | colr |
| `massappct` | state | None | iac |

For 7 of 19 (37%) verified state opinions, `level` was unpopulated. courts-db's federal coverage was already known to need normalization (see `gold_db.lookup_court()` federal block); state courts need a parallel normalization layer for v1.3 to consistently emit a tier label. This is a follow-up implementation task, not a smoke-test blocker — `system='state'` resolution worked for all 19/19 verified items.

### 3. Three NOT_FOUND items are plausibly real but not in CL

| Citation | Case |
|---|---|
| `648 N.E.2d 435` | Ins. Exch. v. Propac-Mass, Inc. |
| `260 N.E.3d 309` | Tody's Serv., Inc. v. Liberty Mut. Ins. Co. |
| `85 N.E.3d 50` | SCVNGR, Inc. v. Punchh, Inc. |

All three are Massachusetts cases (regional N.E. reporter). CL's citation-lookup returned 404 for each; the v1.3 design treats this case as a `Gray` verdict ("right case named, but cited opinion text isn't available for reading"). Acceptable for the smoke test; relevant when computing the v1.3 effective-N denominator.

### 4. Volume — federal-source state mining is sparse

22 unique state items from 3,070 raw candidates (~0.7%). The dedup ratio is also harsh (220 raw → 22 unique = 10×, matching the v1 intra-opinion duplication bug noted in the v1.3 design).

Implications for v1.3 mining:

- To get 50 unique state-tier items in the stratified sample, expect to mine on the order of 7,000–10,000 raw state-tier candidates.
- The v1 source-district list (5 districts) is too narrow. The v1.3 design already calls for ~10 districts; this is a feasibility nudge to the high end of that range.
- Consider extending the date window if 10 districts × 4 months still doesn't yield enough state cites. (Federal opinions cite federal authority preferentially; state cites are a long tail.)

### 5. courts-db state coverage gaps (minor)

Two items had a state cite where eyecite extracted no `court` and the cited-court field was empty (`(unresolved)` × 3 in the per-court table). All three coincide with the NOT_FOUND set above, so `lookup_court()` was never called — but had we tried, courts-db would have nothing to anchor on. Mitigation: the design's two-pass tier classification (pool-time reporter regex + verified-time courts-db) handles this — the reporter regex still bucketed these into the state tier.

## Per-court breakdown

| court_id | n | system / level (courts-db) | Name match | Full-text ≥ 500 |
|---|---|---|---|---|
| dc | 5 | state / iac | 5/5 | 5/5 |
| ill | 2 | state / colr | 2/2 | 2/2 |
| illappct | 2 | state / iac | 2/2 | 2/2 |
| mass | 1 | state / colr | 1/1 | 1/1 |
| massappct | 6 | state / **None** | 6/6 | 6/6 |
| mont | 1 | state / **None** | 1/1 | 1/1 |
| tex | 2 | state / **None** | 2/2 | 2/2 |
| (unresolved) | 3 | NOT_FOUND | 0/3 | 0/3 |

## Decision

**Go** with 25/25/25/25 (SCOTUS / Federal COA / Federal District / State COLR + COA), conditional on:

1. **Required infrastructure fix:** broaden HTML fallback in `citation_verifier.client._resolve_opinion_text_with_metadata` to include `html_lawbox`, `html_columbia`, `html_anon_2020`, and `xml_harvard`. Without this, state-tier coverage drops from 86% to 9% — the difference between "go" and "no-go" depends on this single helper.
2. **Implementation task:** add state-side normalization to `gold_db.lookup_court()` so courts like `massappct`, `mont`, `tex` emit a populated `level`. Otherwise ~37% of state items can't be tier-labeled at the published level. Not a smoke-test blocker, but blocks consistent state-COLR-vs-state-COA breakdown in v1.3 reports.

The smoke test is a one-day investigation — both fixes are small enough to land in Week 1–2 alongside the rest of the v1.3 prep.

## Recurring finding — the `plain_text`-only trap

This is at least the third time this project has discovered that CL's `plain_text` is empty for many opinions while HTML/XML variants are populated. Prior surfacings:

- `benchmark/pilot_a/score.py:fetch_opinion_text` has the fallback chain (`plain_text → html → html_with_citations → html_lawbox → xml_harvard`), with comments explaining the gap.
- `benchmark/runners/score_gold_pairs_fulltext.py` similarly notes "plain_text + stripped HTML fallback".
- `tests/test_client_html.py` and `tests/test_client_opinion_text.py` test prefer_html / fallback behavior in `client.py`.

Despite the fallback logic existing in those callers, **the canonical `client.get_opinion_text()` helper does not include all the format variants**, and ad-hoc scripts (including this smoke test's first pass) keep rediscovering the gap. The fix accompanying this retrospective consolidates the fallback chain into the canonical client helper so future callers don't need to remember to handle it.

## Files

- [`build_sample.py`](../../scratch/state-court-smoke-test/build_sample.py) — state-tier filter + dedup → `sample.json`.
- [`run_pipeline.py`](../../scratch/state-court-smoke-test/run_pipeline.py) — citation-verifier + cluster fetch + courts-db lookup → `results.json`.
- [`probe_fulltext.py`](../../scratch/state-court-smoke-test/probe_fulltext.py) — multi-format full-text probe (extends `results.json`).
- [`results.json`](../../scratch/state-court-smoke-test/results.json) — per-item record (22 rows).
