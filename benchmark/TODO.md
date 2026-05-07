# Benchmark TODO

Hands-on task tracker — pure-human, pure-CC, and joint tasks. Complements the [v1.3 design doc](docs/plans/2026-05-05-v1.3-design.md) (the contract for what we're building) and the eventual v1.3 implementation plan (which will cover CC-executable steps in TDD-style depth). For strategic state across versions, see [`ROADMAP.md`](ROADMAP.md).

**Owner tags:** `(me)` = pure-human; `(CC)` = pure-CC; `(me + X)` = joint with named collaborator.

**Currently working on:** non-benchmark work; v1.3 implementation on hold.

---

## Up next

### Cleanup (anytime, not blocking anything)

- [ ] **(CC) Patch `pilot_a/score.py:fetch_opinion_text` to make truncation explicit-by-caller** (default no cap). Removes a known footgun before any v1.3 assessor work touches it. ~30 min.
- [ ] **(CC) Extract shared hermetic-CLI helper for `claude -p` callers.** Three sites: `pilot_a/score.py`, `runners/model_adapter.py`, `runners/red_audit_fulltext.py` — DRY up the `_HERMETIC_DIR` pattern. ~1–2 hours.
- [ ] **(CC) Audit cache fallback list semantics** in `red_audit_fulltext.py` + `score_gold_pairs_fulltext.py`. The v1.3 cache rename was mechanical; the original cited+citing mix may itself have been a bug. Investigation, then fix or document.
- [ ] **(CC) Patch `gold_db.lookup_court()` for courts-db data quirks surfaced by v1 backfill (2026-05-06).** `dcd` (D.D.C., 7 v1 cases) is tagged `type='appellate'` in courts-db — wrong; it's federal trial. `tax`, `ncwd`, `ilsd` similarly fall through. Add a per-court override list, OR fall back to court_id-prefix heuristics for districts. Also add state-side normalization: `massappct` → `iac`, `tex` / `mont` → `colr` (courts-db has `level=''` for these). Smoke test (2026-05-06) and v1 backfill both hit this. ~1 hour.

### v1.3 prep — when ready to start

> v1.3 is in design but implementation hasn't started. These items kick off when you're ready.

**Setup**

- [ ] (me) Set up OSF entry for public timestamp; tag a GitHub release pointing at the v1.3 design doc for prior-art coverage
- [ ] (me) Confirm librarian timeline; send authorship-memo draft; pin student-RA backup plan
- [x] (CC) Run state-court mining smoke test per v1.3 design §"State-court contingency rule" — Done 2026-05-06; retrospective at `docs/retrospectives/2026-05-06-state-court-smoke-test.md`. Result: name-match 86%, courts-db resolvable 86%, full-text coverage 86%. **Go for 25/25/25/25.** Conditional on broadened HTML fallback (landed in `client.py` 2026-05-06) and state-side `lookup_court()` normalization (open).
- [x] (CC) Sonnet@FT on the 22 v1 Reds that flipped at 60K with Opus — Done 2026-05-07; retrospective at `docs/retrospectives/2026-05-07-sonnet-at-ft-on-22-flipped.md`. **12/22 (55%) agreement** at FT (Sonnet uncapped, Opus's verdict from the 60K truncation experiment). Disagreement runs both directions (Greens to Yellow/Red; Yellows to Green/Red) — softer than the same-window comparison suggested. Independent spot-check of the 9 disagreements: Sonnet closer-to-right on 5, Opus on 1, 3 toss-ups. Within-model variance ~13% on identical inputs (drift budget needed). **Calibration pilot priority: Yellow boundary; pre-stage Opus@FT fallback.**
- [x] (CC) Random Green/Yellow gold-pair audit — Done 2026-05-07; retrospective at `docs/retrospectives/2026-05-07-paren-attribution-audit-greens-yellows.md`. 30 random non-Red Sonnet@FT gold pairs read in citing context. **0/30 mis-attribution bugs.** Combined with the 2026-05-04 Red audit (3/5 bugs in Reds), v1's eyecite parenthetical-mis-attribution rate is bounded between 2.6% (confirmed cases) and ~12% (Wilson 95% upper). Most likely 3–5%. The bug concentrates in Reds because mis-attribution mechanically produces Red verdicts; Greens/Yellows are not silently contaminated. v1.3 mining fix still important; v1 cross-cohort comparison doesn't need a re-do.
- [ ] (me) After smoke: decide 25/25/25/25 vs federal-only 33/33/33 fallback

**Mining pipeline**

- [x] (CC) One-shot CL metadata fetch to populate v1's 127 cases with `court_id` (`year` was already filled). Done 2026-05-06; `runners/backfill_v1_court_metadata.py`. v1 tier distribution: federal-iac 79, federal-colr 18, federal-trial 10, federal-(none) 9, state-(any) 11.
- [ ] (CC) Implement v1.3 mining pipeline overhaul: parenthetical-attribution fix + intra-opinion dedup + no-CL-prefilter + full-text fetcher
- [ ] (CC) Build pool at scale (target 1,000–3,000 candidates across source districts)
- [ ] (CC) Stratified sampling to v1.3 dataset (200 pairs)

**Model runs + assessor**

- [ ] (CC) **Adopt SDK + temperature=0 for v1.3 assessor stack.** The CLI (`claude -p`) doesn't expose a temperature flag — v1's assessor calls run at temp=1.0, which produced ~13% within-model variance on identical inputs in the 2026-05-07 Sonnet@FT spin-off. Helper landed at `benchmark/runners/sdk_assessor.py` (drop-in replacement for `pilot_a/score.py:call_assessor`). v1.3 model runs, gold-pair scoring, sonnet-on-200, and calibration-pilot work should all call `call_assessor_sdk` directly, not `claude -p`. Sealed v1 code stays on the CLI for reproducibility.
- [ ] (CC) Run all three model conditions (Sonnet 4.6, Opus 4.7, GPT-5) on the 200
- [ ] (CC) Run Sonnet@FT assessor on all 200 cells
- [ ] (CC, optional) Cross-family probe: GPT-5/Gemini on 50-pair sample (out-of-pocket cost ~$10–30)

**Human coding**

- [ ] (me + librarian) Calibration pilot on 10–20 pairs; iterate rubric until disagreement-rate < 20%
- [ ] (me + librarian) Independent coding pass on all 200 pairs
- [ ] (me + librarian) Adjudication of disagreements; record adjudication notes
- [ ] (CC + me) Compute Sonnet validation: Cohen's κ vs human, Red precision/recall

**Checkpoint**

- [ ] (me + co-authors) Week 8 proceed/modify/rethink decision before any v2 pre-reg work

---

## Recently done

Compact trail of recent landings. Older items collapse to [`ROADMAP.md`](ROADMAP.md)'s History zone.

- [x] (CC) ROADMAP.md restructure + top-level promotion (2026-05-05)
- [x] (CC) v1.3 design doc (2026-05-05)
- [x] (CC) README/TODO/ROADMAP state-tracking convention (2026-05-05)
- [x] (CC) Benchmark consolidation refactor — `benchmark/` top-level dir, gold-DB move, runners move, pilot_a coupling cleanup (2026-05-05)
