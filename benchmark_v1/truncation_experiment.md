# Opinion truncation experiment — v1 follow-up

Re-assesses every v1 Red verdict with a 60K-character opinion window (vs. v1's default 20K) to measure how much the truncation biases Green rates downward. Same Opus 4.7 assessor, same prompt, same proposition — only the truncation length changes.

## Hypothesis

Original speculation: SCOTUS opinions almost always have a syllabus near the front, circuit opinions sometimes have headnotes (often stripped in CL text), and district opinions essentially never. If support tends to live in the syllabus and the v1 truncation cuts off everything past page ~7, then the SCOTUS-leans-easy pattern in Table 4 (74–80% Green vs. 0–25% for district) might be a truncation artifact rather than a genuine knowledge effect.

## Method

1. Load all v1 Red verdicts from `results.csv` and dedup on `(proposition, gold_cite)` to match the report's deduped-130 denominator. → 69 deduped Reds.
2. For each Red, load the cached opinion from `scratch/pilot_a/opinion_cache/<cluster_id>.txt`. Re-slice to 60K chars (vs. v1's 20K).
3. If the full cached opinion was already ≤ 20K chars, mark SKIP — re-running would expose no new text. (10 of 69 Reds.)
4. For the remaining 59, call the same Opus 4.7 assessor via `claude -p` (prompt piped to stdin to avoid Windows' ~32K CreateProcess limit at 60K-char prompts).
5. Record new verdict + rationale + cost. Resume-safe.

Code: `tests/benchmark_v1/truncation_experiment.py`. Output: `benchmark_v1/truncation_experiment_60k.csv`.

## Results

**59 Reds re-assessed; 22 flipped to Green or Yellow (37%):** 12 → Green, 10 → Yellow, 37 stayed Red. Cost: $12.02 (Opus, ~$0.20/call).

### By tier of cited case

| Tier | n | →Green | →Yellow | →Red | flip% |
|---|---:|---:|---:|---:|---:|
| SCOTUS | 7 | 0 | 3 | 4 | 43% |
| Circuit | 39 | 11 | 5 | 23 | 41% |
| District | 8 | 0 | 0 | 8 | **0%** |
| Other (state / unpublished) | 5 | 1 | 2 | 2 | 60% |

### By model

| Model | Reds re-assessed | →Green | →Yellow | Still Red | Green-rate boost (out of 130 cells) |
|---|---:|---:|---:|---:|---:|
| Sonnet 4.6 | 7 | 0 | 3 | 4 | +0.0pp |
| Opus 4.7 | 20 | 4 | 5 | 11 | +3.1pp |
| GPT-5 | 32 | 8 | 2 | 22 | +6.2pp |

### Headline impact

If 60K had been v1's default truncation:

| Model | v1 Green | Corrected | Δ |
|---|---:|---:|---:|
| Sonnet 4.6 | 31.5% | 31.5% | +0.0pp |
| Opus 4.7 | 36.2% | 39.3% | +3.1pp |
| GPT-5 | 46.2% | 52.4% | +6.2pp |

The correction *widens* rather than narrows the GPT-5 lead. The model with the most original Reds had the most cells to convert, and a similar per-Red flip rate (31%) applied to a much larger Red pool (32 cells) yields the biggest absolute gain.

## Findings

1. **Truncation bias is real and meaningful.** 37% of v1 Reds whose opinions exceeded 20K were artifacts of the truncation. Big enough to call out as a methodology caveat; not big enough to reorder the leaderboard.

2. **Original syllabus-presence hypothesis was wrong.** SCOTUS Reds flipped at 43%, circuit Reds at 41% — basically identical. So the SCOTUS-leans-easy pattern in Table 4 is genuinely a knowledge effect (models know SCOTUS better), not a syllabus-protection artifact.

3. **District-case finding is reinforced.** All 8 district Reds stayed Red even at 3× the context. Adding text did not surface support that wasn't there. This strengthens — rather than undercuts — the v1 finding that models don't really know district cases.

4. **Sonnet's flips were all to Yellow, none to Green.** A reading: Sonnet's small Red pool (only 7, due to its high UNKNOWN rate) skews toward genuinely-bad picks rather than near-misses that just needed more context.

5. **GPT-5 benefited the most despite the lowest per-Red flip rate.** 31% × 32 Reds > 45% × 20 Reds. Cell volume matters more than per-Red flip rate at this scale.

## Limitations

- **One-directional check.** Only Reds were re-assessed. We don't know whether any v1 Greens or Yellows would *downgrade* under more context (e.g., Opus initially saw a clean syllabus statement but additional pages reveal qualifications). The asymmetry biases the impact estimate upward; a balanced check would re-assess all 390 cells.
- **60K isn't the ceiling.** 13 of the 86 unique cited opinions were ≥ 60K full size; their full text would still be truncated at 60K. A grep tool or a 100K window would catch those, at higher cost.
- **Single re-run per cell.** Same nondeterminism story as v1 — a flip might not replicate on a re-run.
- **Assessor identity preserved.** Used the same Opus 4.7 model so we're not confounding window-size with assessor-choice. v1.2 calibration on cheaper assessors (`calibration.md`) is independent.

## Per-row data

`benchmark_v1/truncation_experiment_60k.csv` — columns: `model, id, court, tier, matched_cluster_id, matched_cl_name, extracted_citation, gold_name, gold_cite, proposition, opinion_chars_full, truncated_in_v1, original_supports, original_rationale, new_supports, new_rationale, flipped, cost_usd`.
