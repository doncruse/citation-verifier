# 20K-truncation bug + Red audit

**Date:** 2026-05-04
**Context:** During Task 10 of the gold-DB plan ([2026-05-03-gold-db-plan.md](../plans/2026-05-03-gold-db-plan.md)), the gold-pair self-score pass produced 22 Reds out of 117 (18.8%) — implying ~28% of district-court parentheticals are unfaithful glosses (Yellow + Red). That was alarming and threatened the benchmark's premise. A qualitative audit, then a quantitative re-score at full opinion text, showed almost all the Reds were a truncation artifact.

## Headline

| Measurement | Result |
|---|---:|
| Original Red rate (gold-pair pass, "60K" label) | 22 / 117 = **18.8%** |
| Re-score at full text with Sonnet (22 Reds) | 19 → Green, 0 → Yellow, 3 stayed Red |
| Reds flipped at full text | **86.4%** |
| Estimated real miscitation rate | **~1 / 117 ≈ 0.9%** |

The 28% Yellow+Red headline was dominated by Opus seeing only the first 20K of long opinions and missing the analysis section. At full text, the gold-pair Green ceiling is ~95%+, not ~72%.

## Root cause

`tests/pilot_a/score.py:fetch_opinion_text` silently truncates every opinion to `MAX_OPINION_CHARS = 20_000`:

```python
def fetch_opinion_text(client, cluster_id):
    cache = OPINIONS_CACHE / f"{cluster_id}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")[:MAX_OPINION_CHARS]
    # ... fresh fetch ...
    cache.write_text(text, encoding="utf-8")  # writes full text to cache
    return text[:MAX_OPINION_CHARS]            # but returns only 20K
```

Cache files contain the full opinion (some 100K+ bytes), but the function caps every read at 20K. Callers that subsequently truncate to `[:60000]` get a no-op — they're already at 20K.

## Reach of the bug

Three scripts in the benchmark stack ingested truncated opinions while believing they had longer windows:

1. **`tests/benchmark_v1/score_gold_pairs.py` (Task 10).** Set `OPINION_WINDOW = 60000`, called `pilot.fetch_opinion_text(...)`, then `truncated = opinion_text[:OPINION_WINDOW]`. Both calls return 20K. **All 117 Task 10 gold-pair verdicts in `gold.db` are labeled `opinion_window_chars=60000` but were actually scored at 20K.**

2. **`tests/benchmark_v1/calibrate_assessor.py` (v1.1 calibration study).** Has its own `MAX_OPINION_CHARS = 20000` (line 64) and applies it on cache read (line 163). All three models — Opus, Sonnet, Haiku — saw the same 20K-truncated input. **The study's headline conclusion ("Sonnet/Haiku fail the 90% agreement bar; Opus stays as primary") is unsupported by full-text data.** A re-run at full text could produce different agreement rates because Opus's verdicts (the ground truth) shift heavily when the input changes.

3. **`tests/benchmark_v1/score.py` main loop (Task 12).** Currently uses `OPINION_WINDOW = 20000` and calls `pilot.fetch_opinion_text` — internally consistent (both 20K), so its label is honest, but it's still operating at 20K when the v1 design intended ≥60K post-v1.1.

The original truncation experiment (`tests/benchmark_v1/truncation_experiment.py`) is **not affected** — line 219 reads `cache.read_text(...)` directly, bypassing pilot_a's cap, then explicitly truncates to `MAX_OPINION_CHARS_NEW = 60000`. So the v1.1 finding that "60K flips 37% of 20K Reds" is real.

## Audit method

[tests/benchmark_v1/red_audit_fulltext.py](../../tests/benchmark_v1/red_audit_fulltext.py):

1. Query the 22 Red gold-pair verdicts from `gold.db`.
2. Read the full cached opinion text directly (no truncation): try `scratch/pilot_a/opinion_cache/<cluster_id>.txt`, fall back to `benchmark_v1/_opinion_cache/<cluster_id>.txt`, fall back to a fresh CL fetch.
3. Pipe the prompt to `claude -p --model sonnet` via **stdin** (Windows `CreateProcess` rejects long CLI args — pilot_a's `claude -p <prompt>` form fails on opinions >~30K chars).
4. Store verdicts under `assessor_prompt_version='v1-fulltext'` with `opinion_window_chars=NULL` to distinguish from canonical 20K and 60K entries.

## Per-Red findings

| Cluster | Case | Chars | Verdict@FT | Notes |
|--------:|---|---:|:---:|---|
| 8723131 | United States v. Bailey | 125,341 | Green | Heavy truncation — 105K beyond cap |
| 210926 | Sanofi-Synthelabo v. Apotex | 53,504 | Green | Bond-discretion in remedies section |
| 222130 | United States v. Moore | 23,471 | **Red** | Slight truncation; ambiguous — could be real |
| 938974 | Holy Land Foundation | 43,103 | Green | TRIA discussion past first 20K |
| 118510 | Festo Corp. v. Shoketsu | 43,649 | **Red** | **Real miscitation** — quotes are from *Nautilus*, not Festo |
| 85831 | Shaw v. Cooper | 67,531 | Green | Constitutional rationale later in opinion |
| 112510 | Irwin v. Department of VA | 12,894 | **Red** | **Mining artifact** — proposition text mangled by normalizer |
| 2832658 | United States v. Straker | 190,026 | Green | Other-crimes ruling deep in opinion |
| 7904997 | United Technologies v. EPA | 37,115 | Green | RCRA classification past first 20K |
| 799675 | Pacific Pictures v. USDC | 29,860 | Green | Oral-argument-issues rule later |
| 1228180 | Bias v. Moynihan | 35,492 | Green | Judicial-notice rule later |
| 2477055 | Cline v. Astrue | 49,146 | Green | Singletary holding in merits section |
| 757343 | Bennett v. Schmidt | 11,667 | Green | Even at full text — assessor reconsidered |
| 7308280 | Instant Technology v. Defazio | 93,849 | Green | Workforce-stability discussion later |
| 1445055 | Sain v. Wood | 28,336 | Green | Medical-deference standard past 20K |
| 4669672 | Walker v. Wexford | 43,516 | Green | Eighth Amendment standard later |
| 201566 | Narragansett Electric v. EPA | 30,319 | Green | Sua-sponte transfer authority later |
| 9438433 | Wiener v. MIB Group | 39,429 | Green | Nested attribution acceptable in full context |
| 8724600 | Koufos v. U.S. Bank | 49,839 | Green | IIED discussion deep in opinion |
| 200100 | Singh v. Blue Cross | 82,373 | Green | Tortious-interference discussion later |
| 6580730 | Lipsitt v. Plaud | 37,584 | Green | M.C.K. citation earlier reads as missing at 20K |
| 6585484 | Framingham Auto Sales | 6,148 | Green | Quote was always present; 20K Opus over-rejected |

**Three remaining Reds:**
- **Festo (118510)** — clearest real miscitation in v1. District court cited Festo for §112 definiteness language that's actually from *Nautilus*. The full Festo opinion confirms — it's about prosecution-history estoppel.
- **Irwin (112510)** — proposition text "finding that equitable The DCHRA was recently amended..." is two fragments fused by the normalizer. Eyecite/parser bug, not a court issue.
- **Moore (222130)** — opinion is 23,471 chars. Could be real (Rule 404(b) discussion not in this opinion) or could be Sonnet missing a passage. Worth a re-check at Opus full-text or human review.

So the actual genuine miscitation rate in v1 is **~1 case** (Festo). Mining-artifact rate **~1 case** (Irwin). Plus 1 ambiguous (Moore). True Red rate ≈ 1-3% of v1 gold pairs, not 19%.

## Implications for v1 / v1.1 / v1.2 deliverables

1. **The benchmark's premise is fine.** "Citing courts overstate or mischaracterize ~28% of cited propositions" is wrong; reality is closer to 1-3%. The gold-DB calibration column was the right artifact for catching this; the truncation bug just meant the first measurement gave a bogus number.

2. **Task 10's 117 gold-pair verdicts were mis-labeled** — stored at `opinion_window_chars=60000` but actually scored at 20K. **Resolved 2026-05-04** by relabeling to `(assessor_prompt_version='v1-task10', opinion_window_chars=20000)`. The new prompt_version preserves provenance (these are Task 10's re-scoring run, distinct from the original v1 Pass 3 model_answer scorings at `prompt_version='v1'`) and avoids UNIQUE-constraint collisions with the 25 model_answer rows that scored the same `(prop, candidate)` tuples. See [the full-text retrospective](2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md) for the relabel decision.

3. **Calibration study (v1.1) is on shaky empirical ground.** Sonnet's 87.8% Red precision was measured against a Red set that was largely truncation artifact. With full-text input, the population of Reds shifts dramatically, and the per-class precision/recall numbers don't carry over. The conclusion ("Opus stays as primary; cheaper-model substitution is closed") may still hold — but the study has not actually demonstrated it. A re-run at full text would settle the question.

4. **Score.py's main loop runs at 20K.** Internally consistent, but if v1.1's design intent was ≥60K (per the v1 truncation finding), the current code does not implement it.

## v1.4 follow-up items (proposed)

- [ ] **Fix `pilot_a/score.py:fetch_opinion_text`** — change to `cache.read_text(...)[:max_chars]` with `max_chars` as a parameter, default to a sentinel meaning "no truncation". Or deprecate the function in favor of a new `read_full_opinion(cluster_id)` that doesn't truncate, with truncation being the caller's responsibility.
- [ ] **Re-run gold-pair Opus at full text.** ~127 Opus calls, ~$20 quota. Replaces the mis-labeled Task 10 entries; gets the real calibration baseline.
- [ ] **Re-run calibration study (v1.1) at full text.** 514 calls × 2 models = ~1000 calls. Bigger lift but settles whether Sonnet/Haiku really fail the bar or whether the failure was a 20K artifact. Mid-priority — only matters if we want to revisit cheaper-assessor substitution.
- [ ] **Re-run score.py main loop at full text** when re-scoring v1's 600 cells. Will bump Green rates for Opus/Sonnet/GPT-5; may shift the leaderboard.
- [ ] **Audit Yellow gold-pair verdicts at full text** — same script, different filter. The 11 Yellows likely have a similar truncation share; the real partial-fit rate is probably much lower than 9.4%.
- [ ] **Re-run truncation experiment at "full text" instead of 60K** to find the residual truncation bias at 60K.

## Lessons

1. **Silent truncation in shared utilities is a serious risk.** `fetch_opinion_text` looks like an opaque "give me the opinion" call; the 20K cap is invisible to callers. Future fetchers should make truncation an explicit parameter or be split into a "raw" and "truncated" pair.
2. **Test the truncation hypothesis before drawing conclusions.** The 28% headline would have been a defensible publication-worthy finding (~"district courts misrepresent 28% of cited propositions") if we'd stopped at the first measurement. The full-text re-score was a 30-minute experiment that prevented a substantive false claim.
3. **Cache file size is a trivial sanity check.** Spot-checking cache file sizes (5-100K bytes for opinions, with 20K read returns being suspicious uniform) would have surfaced this immediately.
4. **The gold-DB calibration column worked as designed.** This kind of bug would have been invisible without first-class storage of the gold-pair self-score and the ability to re-score under different (model, window) tuples and diff. The polymorphic `assessor_verdicts` schema let the audit data live alongside canonical results without collision.

## Artifacts

- `tests/benchmark_v1/red_audit_fulltext.py` — the audit script (also usable for haiku/opus re-runs)
- `gold_db/gold.db` — 22 new rows: `assessor_model='sonnet-4.6'`, `assessor_prompt_version='v1-fulltext'`, `opinion_window_chars=NULL`, `source='gold_pair'`
- `scratch/red_audit_sonnet_fulltext_v2.log` — script output of the successful audit run
- `scratch/red_audit_input.txt` — pre-audit data dump (proposition + Opus rationale per Red)
