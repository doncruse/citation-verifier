# Case Law Retrieval Benchmark — Roadmap

Living doc. Tracks active and planned work; history at the bottom.

**Current state (2026-05-05):** v1.3 design landed; implementation pending (user holding to do other work first). Recent v1.x audits (2026-05-04) closed out v1.2 and informed v1.3 design — see History below. v2 is the pre-registered confirmatory paper, planned post-v1.3.

**Update protocol:** This doc is the live state tracker. When work lands, update the relevant section here and any per-section progress marks (✅ / 🟡) on the active design contract.

---

# Forward-looking

## v1.3 — Methodology test bed 🟡 in design (2026-05-05)

**Status:** design landed 2026-05-05. Implementation not started.

**Goal:** End-to-end methodology dry-run before the pre-registered v2. Builds a fresh 200-pair benchmark stratified across four court tiers, validates the new mining pipeline and Sonnet@FT assessor against human-coded gold labels, and develops a 5-tier substance rubric collaboratively with the librarian co-author.

**Design contract:** [`2026-05-05-v1.3-design.md`](2026-05-05-v1.3-design.md). All v1.3 implementation work tracks against that doc — sections get marked ✅ / 🟡 as work lands.

**Scope (in):**

- Fresh 200-pair dataset, stratified 25/25/25/25 across SCOTUS / Fed COA / Fed District / State (COLR+COA)
- New mining pipeline (no CL pre-filter, eyecite-only metadata at pool time, parenthetical-attribution + intra-opinion dedup bugfixes, full-text fetcher)
- Three model conditions (Sonnet 4.6, Opus 4.7, GPT-5)
- Sonnet 4.6 at full text as default assessor; Cohen's κ ≥ 0.6 vs human coders as the bar
- Human-coded verdicts from project lead + librarian (with student RA backup) on all 200
- 5-tier substance rubric, refined collaboratively
- Tier-stratified comparison with v1's 130 cohort (after one-shot CL metadata backfill)
- State-court contingency rule: smoke-test gate (≥70% court_id resolution + ≥50% full-text coverage); fall back to federal-only 33/33/33 if state is too sparse

**Scope (NOT in):**

- Workshop paper or any external publication of v1.3 (no public artifact)
- Pre-registration (only v2 is pre-registered)
- Web-search modes, currency axis, jurisdictional axis (defer to v2)
- Forkable kit (defer to v2)

**Hard time budget:** Week 10 cap from start of implementation. Week 8 proceed/modify/rethink checkpoint before any v2 pre-reg work begins.

---

## v2 — Pre-registered confirmatory 📋 planned

**Status:** scoped post-v1.3. Pre-registration pending v1.3 results.

**Structural changes from v1.3:**

- **Pre-registered.** Sampling protocol, rubric, assessor configuration, models, metrics, hypotheses all locked before mining begins. Timestamped on OSF + public GitHub release. See [publication plan](2026-05-05-publication-plan.md) for the rationale and timeline.
- **Larger N** (TBD per pre-reg). Conditional on Sonnet@FT validation in v1.3 — if Sonnet passes the human-validation bar, ~5× cost reduction unlocks N ≥ 500. If not, v2 stays near v1.3's N within Opus's budget envelope.

**Scope items deferred from v1 / v1.2 / v1.3 that v2 picks up:**

| Item | Why for v2 |
|---|---|
| Forkable kit scaffolding (SCHEMA.md, MINING_PLAYBOOK.md, QUALITY_GATES.md, PROMPT_TEMPLATES/, scoring/, SUBMISSION.md) | External contributors can fork the kit and run state-court / circuit / topic-specific variants |
| Web-search and tool-augmented eval modes | Tests retrieval-augmented frontier behavior (e.g. Sonnet+web vs. Opus closed-book) |
| Currency axis (good-law check) | Catches "real case but bad law" — overruled, vacated, distinguished |
| Jurisdictional-appropriateness axis | Penalizes citing 3rd Cir. for a 5th Cir. proposition |
| Lexical-dissimilarity quality gate | Removes propositions that are near-paraphrases of the gold case name |
| Multi-source existence oracle (CL + Justia + Caselaw Access Project) | Vendor RAG benchmarks need broader-than-CL coverage to be fair (v1.3's no-CL-prefilter design partially addresses this) |
| State-law forks | Federal layer is the reference; state implementations exercise the kit and surface state-specific quirks |

---

# History

## v1.2 — Methodology hardening 🟢 closed out (2026-05-05)

**What landed:** the **gold-DB** ([design](2026-05-03-gold-db-design.md), [plan](2026-05-03-gold-db-plan.md)) — a cumulative SQLite corpus of (proposition, case, verdict) tuples with build-side cache, score-side cache, drift sampling, and CSV exports. Implementation completed 2026-05-04 via the 13-task plan.

**Ledger close-out:** the broader v1.2 backlog (originally ~15 deferred items) was dispositioned as part of the [v1.3 design](2026-05-05-v1.3-design.md). Summary:

- **Absorbed into v1.3** (4 items + 3 fixes from 2026-05-04 audits): stratified sampling, per-case metadata, default opinion full-text window, mining-stage dedup, plus the truncation + parenthetical-attribution + Green/Yellow audit items.
- **Subsumed by gold-DB** (3 items): acceptable-alternatives caching, verified-citations cache, gold-DB itself.
- **Resolved without new work** (1 item): "Re-run gold-pair Opus at full text" — relabeled Task 10 rows to honest `(v1-task10, 20000)` since Sonnet@FT became v1.3's assessor candidate.
- **Deferred to v2** (6 items): forkable kit, web-search modes, currency axis, jurisdictional-appropriateness axis, lexical-dissimilarity gate, multi-source existence oracle.
- **Parked open question** (1 item): gold-DB taxonomy / safe-query design (commit `dfe178c`) — three options A/B/C (SQL views, README docs, rename `gold.db` → `corpus.db`). Deferred for fresh-eyes review.

The v1.2 banner closes here; nothing remains under v1.2 going forward.

---

## Mid-flight findings (2026-05-04)

The gold-pair self-score pass surfaced two material methodology issues. Both are scoped into v1.3 mining and assessor work.

**(a) `pilot_a/score.py:fetch_opinion_text` silently truncates at 20K** — affected Task 10's "60K" gold-pair pass and the v1.1 calibration study. Function caps every opinion at 20K chars regardless of caller intent; bypassed only by the original truncation experiment. See [retrospective](../retrospectives/2026-05-04-truncation-bug-and-red-audit.md).

**(b) Eyecite/build_dataset mis-attaches parentheticals to the wrong case in chained citations** — 3 of 5 v1 "Reds" at full text were parser bugs, not court errors. The substantive parenthetical attaches to the wrong cited case in chains like `Case_A; Case_B (parenthetical)`. See [retrospective](../retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md).

**Assessor-candidate update:** Sonnet 4.6 at full text emerged as v1.3's default assessor candidate (90.6% Green on v1 gold pairs at full text, ~5× cheaper than Opus on subscription quota). Haiku 4.5 ruled out (54.7% Red at full text — disagrees with Sonnet on 60+ Greens). The v1.1 calibration conclusion ("Sonnet/Haiku fail the 90% bar") was measured at 20K-truncated input and is now provisional; Sonnet at full text may pass.

---

## v1.1 — Validation studies ✅ done (May 2026)

Two additive studies validating v1's methodology: assessor calibration (Sonnet/Haiku vs Opus on 514 cells) and the 20K → 60K truncation re-test on v1's Reds.

**Headline (at 20K-truncated input):**

| Model | Overall agreement | Red recall | Red precision | Cohen's κ |
|---|---:|---:|---:|---:|
| Sonnet 4.6 | 68.9% | 52.2% | 87.8% | 0.50 |
| Haiku 4.5 | 65.4% | 55.1% | 67.9% | 0.41 |
| *Bar* | ≥90% | ≥85% | — | — |

Both candidates missed the bar at 20K. Conclusion was "Opus stays as primary." **Conclusion now provisional** — see Mid-flight findings above; Sonnet at full text may pass.

**Truncation re-test:** 22 of 59 v1 Reds (37%) flipped to Green/Yellow when re-assessed at 60K chars. Per-model corrected Green rates: Sonnet 31.5% (no change), Opus 36.2% → 39.3%, GPT-5 46.2% → 52.4%.

**Artifacts:**
- [`benchmark/releases/v1/calibration.md`](../../releases/v1/calibration.md) — confusion matrices, per-class metrics
- [`benchmark/releases/v1/calibration_results.csv`](../../releases/v1/calibration_results.csv) — 514 calls, full coverage
- [`benchmark/releases/v1/truncation_experiment.md`](../../releases/v1/truncation_experiment.md) — truncation re-test writeup
- [`docs/retrospectives/2026-05-02-v1.2-assessor-calibration.md`](../retrospectives/2026-05-02-v1.2-assessor-calibration.md) — full run notes + keying-bug postmortem

---

## v1 — Initial benchmark ✅ shipped (May 2026)

130-pair effective N (after dedup from 200 raw), 3 models (Sonnet 4.6, Opus 4.7, GPT-5), Opus@20K assessor, federal-court-pleadings source, 5 districts (D.D.C., N.D. Cal., S.D. Tex., N.D. Ill., NYSD).

Headline: GPT-5 46.2% Green, Opus 36.2%, Sonnet 31.5%. See [`releases/v1/README.md`](../../releases/v1/README.md) for the full writeup, scorecards, and reproducibility instructions.

---

# Reference

## Lessons from v1 run

Factual lessons from running v1 that shouldn't be forgotten — useful when designing v1.3 / v2 runners:

| Observation | Where it shows up |
|---|---|
| GPT-5 needs `max_completion_tokens >= 8000` for closed-book legal prompts; 2000 left ~67% of responses empty (all hit the budget exactly on reasoning) | `benchmark/runners/model_adapter.py` `_call_gpt5` comment |
| Claude CLI `claude -p --model sonnet` calls can take >60s on real prompts; 120s timeout is safer; max OK call observed was 59.5s | `benchmark/runners/run_model.py` `TIMEOUT_S` comment |
| Sonnet's UNKNOWN rate is far higher than Opus or GPT-5 (53% vs 22% vs 6%) — implies hallucination rate alone misranks; pair with UNKNOWN rate or use Green-rate-of-real | `benchmark/releases/v1/scorecards.md` |
| 20K char opinion truncation hides supporting passages ~37% of the time when the cited opinion exceeds 20K. SCOTUS and circuit Reds flip at indistinguishable rates (43% vs 41%) — the SCOTUS-leans-easy pattern in Table 4 is a knowledge effect, not a syllabus artifact. District Reds did not flip at all (0/8) | `benchmark/releases/v1/truncation_experiment.md`. v1.3 defaults to full-text |
| Stdout buffering through bash redirect (`>` log file) hides progress until process exits; results.csv is the real progress signal | Future runners: tail `results.csv`, not the log |

---

## When to spin out to its own repo

**Recommendation: at v2, when the forkable kit ships.** Not before.

Today's setup (benchmark inside citation-verifier) is the right call because:

- The benchmark depends on citation-verifier *internals*: `parsed_citation_from_eyecite`, `verify_batch`, parser normalization, name matcher. These aren't a stable public API yet.
- Single venv, single .env, single dev loop — high velocity for iteration.
- v1's deliverable is a **scorecard + dataset**, not a kit. v1.3's deliverable is methodology validation, also not a kit. No external forkers are arriving for either.

Spin out when these are all true:

1. **Forkable kit lands (v2).** SCHEMA.md, MINING_PLAYBOOK.md, etc. exist. External contributors are the audience.
2. **citation-verifier exposes a stable public API** that the benchmark can pin a version of (`citation-verifier>=X.Y`). Until then, internal-API churn breaks the benchmark in a separate repo.
3. **At least 2–3 outside people have signaled they want to fork** (state-court variant, topic-specific variant, etc.). One-off curiosity isn't enough — the cost of a separate repo is real.
4. **A clean release story is needed** — DOI, arXiv companion, NeurIPS-style benchmark track submission, GitHub releases with versioned datasets. These all want a top-level repo to point at.

Practical mechanics when the time comes:

- New repo name candidates: `case-law-retrieval-benchmark`, `claire-bench`, etc.
- citation-verifier becomes a pinned pip dependency (publish to PyPI first, or git+https)
- Move `benchmark/` → top of new repo (the consolidation refactor of 2026-05-05 was specifically designed to make this a `git mv` operation)
- Roadmap, design docs, retrospectives migrate too
- Leave a stub in citation-verifier pointing at the new repo

Anti-pattern to avoid: spinning out before the kit ships just because it "feels cleaner." External contributors aren't there yet, and you'd pay the cross-repo PR / dependency-version-bump cost without a benefit.

---

## How this doc evolves

- **Forward-looking sections (v1.3, v2)** get updated as scope shifts, sub-decisions land, or new items get queued. Per-section progress marks (✅ / 🟡) live on the active design contract, not here.
- **History sections** are reverse-chronological. New entries go at the top of the History zone. Don't delete completed entries; collapse them to short summaries with pointers to artifacts.
- **Reference sections** are stable. Update only when a lesson actually changes (e.g., a runner workaround becomes obsolete) or a criterion shifts.
- When a release ships: move it from Forward to History (reverse-chronologically). Trim its forward-looking detail; keep the headline + artifact pointers.
