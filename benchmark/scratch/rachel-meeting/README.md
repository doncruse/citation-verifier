# Rachel meeting — chart walkthrough

Five charts that walk the v1 → recent findings → v1.3 plan arc. Generated
by [`generate_charts.py`](generate_charts.py); regenerate with
`python benchmark/scratch/rachel-meeting/generate_charts.py`.

## Suggested narrative (5–10 min walk-through)

### 1. v1 scorecard — `01_v1_scorecard.png`

> "v1 was a 130-prop benchmark on three frontier models, closed-book.
> GPT-5 leads on Green; Sonnet has the lowest hallucination rate but
> that's mostly a denominator effect — half its responses are UNKNOWN.
> The hallucination/UNKNOWN tradeoff is the real shape of the leaderboard."

**Caveats to surface:** 35% of the original 200-row sample turned out to
be intra-opinion duplicates from an eyecite quirk; 130 is the deduped N.
Tier distribution was accidental (chart 5 covers this).

### 2. v1.1 calibration — `02_v1_1_calibration.png`

> "First instinct after v1 was: can we use Sonnet or Haiku as assessor
> instead of Opus? 5–10× cost reduction would unlock N=500–1000.
> Answer at the time: no — both miss the bar, especially on Red recall.
> But this was measured at 20K-truncated input."

**Where it points:** if the failure was actually a truncation artifact
rather than a model-capability ceiling, the conclusion is reversible.
That's where the truncation experiment comes in.

### 3. Truncation experiment — `03_truncation_experiment.png`

> "Re-assessed every v1 Red at 60K instead of 20K. 22 of 59 Reds
> (37%) flipped to Green or Yellow. SCOTUS and Circuit Reds flip at
> the same rate (43% / 41%) — so the SCOTUS-leans-easy pattern in
> v1's results was a knowledge effect, not a syllabus artifact.
> District Reds didn't flip at all (0/8) — they're genuinely harder."

**Implication:** the 20K window was hiding supporting passages in long
opinions. v1's assessor calibration is now provisional — we don't know
whether Sonnet would pass at full text.

### 4. Sonnet@FT gold-pair finding — `04_sonnet_ft_gold_pairs.png`

> "Re-scored v1's 117 gold pairs at full opinion text, with three
> assessors. Sonnet at full text hits 90.6% Green — matches what we'd
> expect from Opus at full text, and is ~5× cheaper. Haiku at full
> text is 41.9% Green / 54.7% Red — disagrees with Sonnet on 60+
> Greens. Haiku ruled out; Sonnet@FT is the leading v2 assessor
> candidate."

**Caveat:** this is gold-pair self-score, which uses court-supplied
(proposition, case) pairs as the truth signal. That's confounded —
courts and LLMs may share failure modes. v1.3 fixes this by adding
human-coded validation.

### 5. Stratification fix — `05_stratification.png`

> "v1's cited cases were 60% Federal COA, 19% SCOTUS, 9% Federal
> District by accident — that's just what federal districts cite.
> v1.3 stratifies 25/25/25/25 by design (state contingent on a
> smoke-test gate). That lets us make a real claim about
> district-case retrieval being harder, instead of the buried
> hint v1 has."

**Where v1.3 goes from here:** 200-pair stratified dataset, full-text
Sonnet validated against human-coded gold labels (lead + librarian
co-author), 5-tier substance rubric. Internal methodology test bed —
not pre-registered, not for publication. v2 (post-v1.3) is the
pre-registered confirmatory paper.

## Source data

| Chart | Data source |
|---|---|
| 1 | `benchmark/releases/v1/scorecards-deduped.md` |
| 2 | `benchmark/releases/v1/calibration.md`, `calibration_results.csv` |
| 3 | `benchmark/releases/v1/truncation_experiment_60k.csv` (raw flip data) |
| 4 | `benchmark/gold_db/exports/assessor_verdicts.csv` filtered to `source='gold_pair'` |
| 5 | v1 distribution from `releases/v1/dataset.csv` analysis (in roadmap); v1.3 target from `docs/plans/2026-05-05-v1.3-design.md` |
