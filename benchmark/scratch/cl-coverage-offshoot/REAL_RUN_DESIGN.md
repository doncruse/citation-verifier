# Real run design — 200-case stratified CL coverage measurement

**Status:** Locked 2026-05-14. Settled open questions; mining plan below.
**Goal:** A defensible coverage measurement of CourtListener across 50 each
of SCOTUS / Circuit / State COLR / State IAC cited cases.

This is the design for the actual measurement run, downstream of the
5-opinion pilot that validated the pipeline end-to-end. Pilot retrospective
in `coverage_summary.md` and `LIMITATIONS.md`; pilot scripts in 01-09.

## Pipeline (locked)

```
Mine citing opinions
  ↓
LLM-extract citations (claude -p sonnet)
  ↓
Dedup at (citing_cluster, citation_string, parenthetical)
  ↓
Pre-filter — drop short-form, foreign, non-case-citations
  ↓
Tier-classify cited cases by reporter pattern
  ↓
Cap at K=5 per (citing_cluster, cited_tier)
  ↓
Stratified sample 50 per cited tier → 200
  ↓
CL lookup via verify_batch(quick_only=True)
  ↓
Manual audit of NOT_FOUND rows → CL gap vs fabrication
  ↓
Per-tier coverage report
```

## Settled decisions

| Decision | Value | Source |
|---|---|---|
| Per-opinion cap | K=5 per (citing_opinion, cited_tier) | conversation 2026-05-13 |
| Citing source mix | Federal + state combined | conversation 2026-05-13 |
| Target tiers | SCOTUS, Circuit, State COLR, State IAC | conversation 2026-05-13 |
| Sample size | 50 per tier × 4 = 200 | original |
| Extractor | Sonnet via `claude -p`, stripped prompt (no sentence_context) | pilot |
| Validator | normalizing-aware (smart quotes / line breaks / dashes) | pilot |

## Settled (2026-05-14)

### 1. 25K opinion size cap — **KEEP** (Option B)

Reasoning: because we're stratifying 50/50/50/50 across cited tiers, the
long-opinion-exclusion bias affects which cited cases enter the per-tier
sample, not the per-tier denominator. Per-tier coverage estimates are
robust to this bias even if the within-tier sample skews toward citations
from shorter opinions. The bias should be **disclosed prominently** in any
writeup but doesn't invalidate the headline coverage numbers.

Trade-off accepted: cannot fully validate that "citations from long
opinions" have the same CL coverage as "citations from short opinions" —
this could be a follow-up question if/when we revisit the cap with an API
key or chunking approach.

### 2. Federal source — same 6 districts as v1

`dcd`, `cand`, `txsd`, `ilnd`, `nysd`, `mad`. Date range 2026-01-01 to
2026-04-30 (same as v1 for direct comparability).

### 3. State source — 5 largest states by caseload

CA, NY, TX, FL, IL. For each, mine both the COLR (state supreme) and the
IAC (state intermediate appellate court). Date range 2026-01-01 to
2026-04-30.

CL court IDs (from courts-db):
- CA: `cal` (COLR), `calctapp` (IAC)
- NY: `ny` (COLR), `nyappdiv` (IAC)
- TX: `tex` (COLR), `texapp` (IAC)
- FL: `fla` (COLR), `flaapp` (IAC)
- IL: `ill` (COLR), `illappct` (IAC)

### 4. Pre-filter for short-form cites

Pilot found ~10 of 31 NOT_FOUNDs were short-form cites the model correctly
identified (`Id., at 28-33`, `567 F.3d at 681-82`, `supra`) but the
verifier can't look up. These pollute the miss rate.

**Proposed filter (drop from lookup pool):**
- `Id.,? at \d+` patterns
- `id\.,? at \d+`
- `at \d+(-\d+)?` (bare pin cite)
- `supra`

**OPEN:** drop entirely, or keep them in the pool but mark as
`unresolvable_form` and exclude from miss-rate denominator?

### 5. Pre-filter for foreign / non-US reports

Pilot found 3 of 31 misses were English reports (1842 Winterbottom v.
Wright, etc.). Out of scope for "CL coverage."

**Proposed filter (exclude):**
- `Eng Rep`, `Eng. Rep.`
- `Mees & W`, `Mees. & W.`
- `KB`, `K.B.`
- `Ch`, `Ch. D.`
- `WLR`, `W.L.R.`
- Any reporter without US state/federal court mapping

### 6. Volume target

Pilot: 5 opinions × ~32 unique cites per opinion (after dedup) × 5 cap-
effective = ~10 usable rows per opinion contributing to a target tier.

For 200 final: need pool with ≥50 in each target tier. Given uneven cross-
tier yield:
- 70 federal × 0.7 SCOTUS/op = 49 SCOTUS (about right, cap at 5/op binds rarely)
- 70 federal × 4 Circuit/op = 280 Circuit (cap to 50 easily)
- 20 state × 3 State_COLR/op (own-state) + 70 federal × 0.1 = 67 State_COLR ✓
- 20 state × 2 State_IAC/op = 40 State_IAC — **may undershoot 50**

**OPEN:** if State_IAC undershoots, add more state citing opinions, or
accept smaller sample for that tier?

### 7. Audit protocol for NOT_FOUNDs

For each NOT_FOUND row in the final 200, decide: real CL gap or
fabrication?

**Proposed:**
- Google the `cited_case_name` + year. If a real published case shows up
  in 2-3 search results: real CL gap.
- If only one Google hit or none: likely fabrication; spot-check
  by reading the source opinion's surrounding text to see if the citation
  actually appears as written.

**OPEN:** How many auditors? (Pilot suggests ~15-30 NOT_FOUNDs across 200
rows; one auditor is fine.)

## What we learned from the pilot

- The pipeline works end-to-end on small opinions.
- Caceci v. Di Canio demonstrated K=5 cap matters — without it, one
  opinion would have contributed 66 rows to State_COLR.
- Most "miss rate" inflation comes from short-form cites the verifier
  can't resolve back to their full form. Pre-filtering will reveal a
  cleaner number.
- State tiers (esp. older state cases) are where the real CL coverage
  question lives — the federal tiers showed 2-9% miss after filtering,
  state COLR showed ~30% real-candidate gaps in the Caceci string cite.

## Concrete mining plan

### Step 1 — Fetch candidate citing opinions

For each source court, fetch all opinions with `date_filed` in
2026-01-01 to 2026-04-30 via the CL `clusters` endpoint, paginated. From
each cluster, follow `sub_opinions` to get the opinion text. Filter to
opinions with text ≤25K chars. We expect ~50% of opinions to fit.

Federal courts (6): `dcd`, `cand`, `txsd`, `ilnd`, `nysd`, `mad`.
State courts (10): `cal`, `calctapp`, `ny`, `nyappdiv`, `tex`, `texapp`,
`fla`, `flaapp`, `ill`, `illappct`.

Random-sample within each source court until we have:
- 12 citing opinions per federal district × 6 = 72 federal
- 2 citing opinions per state court × 10 = 20 state

Buffer: fetch up to 25 candidates per source to handle the size-cap
filter. Save each opinion text to `citing_opinions/<cluster_id>.txt` with
source metadata in `citing_opinions/_manifest.csv`.

### Step 2 — LLM extraction

Run the existing extractor (`extract_citations.py`) on each citing
opinion. Save outputs to `real_extractions/<cluster_id>.json` matching
the pilot schema. Total wall time at ~60-200s per opinion × 92 opinions
= 3-6 hours. Cost at ~$0.15/opinion × 92 = ~$14.

### Step 3 — Pre-filter, dedup, classify, cap

Single script `mine_stratify.py` that:
1. Loads all `real_extractions/*.json`
2. Pre-filters short-form cites and foreign reports
3. Dedups (citing_cluster, citation_string, parenthetical)
4. Tier-classifies via `tier_from_cite`
5. Caps at K=5 per (citing_cluster, cited_tier)
6. Stratified-samples 50 per cited tier
7. Writes `final_pool.csv` (post-cap, pre-sample) and `final_200.csv`
   (the actual stratified sample).

### Step 4 — CL coverage lookup

Run `verify_batch(quick_only=True)` on the 200 sampled citations. ~3 min
at the pilot's observed rate.

### Step 5 — Audit NOT_FOUNDs

For each row where lookup_status == NOT_FOUND:
- Google `cited_case_name` + year.
- If real published case → mark as `gap` (real CL coverage gap).
- If no real-case match → mark as `fabrication`.

Estimate: 200 × 15-30% miss × audit ≈ 30-60 rows × 2 min each ≈ 1-2 hours.

### Step 6 — Report

- Per-tier coverage rate (gaps / total).
- Per-tier audit notes (which gap is which).
- Method limitations (25K cap, claude -p variance, pre-filter logic).

## Open follow-ups (post-run)

- Variance check: re-run extraction on 20 of the 200 opinions to measure
  Sonnet@temp=1.0 within-model variance on extraction. Document.
- Long-opinion check: if/when we add API key, re-run a sample of long-
  opinion (>25K) extractions to see whether long-opinion citations have
  similar coverage rates to short-opinion citations.
- v2 question: if coverage gaps cluster in particular jurisdictions or
  date ranges, scoping a follow-up specifically there might be
  productive.
