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

### v1.3 prep — when ready to start

> v1.3 is in design but implementation hasn't started. These items kick off when you're ready.

**Setup**

- [ ] (me) Set up OSF entry for public timestamp; tag a GitHub release pointing at the v1.3 design doc for prior-art coverage
- [ ] (me) Confirm librarian timeline; send authorship-memo draft; pin student-RA backup plan
- [ ] (CC) Run state-court mining smoke test per v1.3 design §"State-court contingency rule" — ~1 day investigation
- [ ] (me) After smoke: decide 25/25/25/25 vs federal-only 33/33/33 fallback

**Mining pipeline**

- [ ] (CC) One-shot CL metadata fetch to populate v1's 130 cases with `court_id` + `year` (~30 min; enables v1↔v1.3 tier-by-tier comparison post-v1.3)
- [ ] (CC) Implement v1.3 mining pipeline overhaul: parenthetical-attribution fix + intra-opinion dedup + no-CL-prefilter + full-text fetcher
- [ ] (CC) Build pool at scale (target 1,000–3,000 candidates across source districts)
- [ ] (CC) Stratified sampling to v1.3 dataset (200 pairs)

**Model runs + assessor**

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
