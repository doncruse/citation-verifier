# Full-text assessor comparison + parenthetical mis-attribution bug

**Date:** 2026-05-04
**Predecessor:** [2026-05-04-truncation-bug-and-red-audit.md](2026-05-04-truncation-bug-and-red-audit.md) (the earlier audit that surfaced the 20K-truncation bug)

After the audit established that 60K → full text would flip most Reds to Green, we ran the full v1 gold-pair set (117 pairs) through Sonnet and Haiku at full opinion text to (a) confirm the audit's truth estimate held across the entire dataset, (b) test whether either of the cheaper models can replace Opus as assessor going forward.

## Headline

| Assessor | Window | Green | Yellow | Red | Verdict |
|---|---|---:|---:|---:|---|
| Opus 4.7 | 20K (canonical, mis-labeled 60K) | 71.8% | 9.4% | 18.8% | Truncation-poisoned baseline |
| **Sonnet 4.6** | **full text** | **90.6%** | **5.1%** | **4.3%** | **Reliable. Promote to v2 assessor.** |
| Haiku 4.5 | full text | 41.9% | 3.4% | 54.7% | Broken on this task. Don't use. |

**Sonnet 4.6 at full text is a viable Opus replacement.** Its distribution matches the audit's truth estimate (~95% Green ceiling on v1) and its Reds, when read in context, identify a credible miscitation set. Sonnet is ~5x cheaper per call than Opus on the subscription quota.

**Haiku 4.5 at full text fails badly.** 64 of 117 pairs marked Red, including 59 cases where Sonnet (correctly) said Green. Haiku appears unable to reliably perform "does this case support this proposition" reading-comprehension on dense legal opinions, even with full text and 200K context window. Possible failure modes: lower threshold for "no support," reading-comprehension drop on long inputs, prompt-sensitivity differences. Whatever the cause, the agreement matrix is unambiguous.

## Sonnet vs Haiku agreement

Pairwise verdicts on the same 117 pairs:

| Sonnet | Haiku | n |
|---|---|---:|
| Green | Red | **59** |
| Green | Green | 47 |
| Red | Red | 4 |
| Yellow | Yellow | 3 |
| Yellow | Green | 2 |
| Yellow | Red | 1 |
| Red | Yellow | 1 |

Sonnet says Green, Haiku says Red on 59 cases — and the audit work confirmed Sonnet is correct on these. The 4 cases where both say Red are a useful filter: when both models agree Red, that's a stronger signal than either alone.

## The 5 Sonnet Reds — re-classified after reading parentheticals in context

Sonnet's 5 Reds at full text initially looked like the genuine-miscitation list. Reading each parenthetical in its citing-opinion context revealed three of the five are **mining bugs**, not court errors. The eyecite/build_dataset pipeline incorrectly attached parentheticals to the wrong case in chained citations.

| # | Case | Original verdict | Real bucket | Source of the Red |
|---|---|---|---|---|
| 1 | United States v. Moore | Red→Red | Ambiguous | Truncation may still bite (cache file is 23K, opinion is longer); Sonnet says Moore is about Batson, not 404(b) |
| 2 | Festo Corp. v. Shoketsu | Red→Red | **Mining bug** | Parenthetical "(definiteness requirement is not a demand for unreasonable precision)" was for **In re Packard**, not Festo. The two cases appeared in a citation chain; eyecite mis-attached. The proposition itself is correct — Packard does say this. |
| 3 | Irwin v. Dept of VA | Red→Red | **Mining bug + footnote fusion** | Parenthetical "(finding that equitable...)" was for **McAlister v. Potter**, not Irwin. Worse, footnote 3 ("The DCHRA was recently amended...") got concatenated to the parenthetical fragment by the parser. Two parser bugs in one row. |
| 4 | Maleng v. Cook | Yellow→Red | **Mining bug** | Parenthetical "(usually 'custody' signifies...)" was for **Cady v. Thaler**, not Maleng. Maleng is cited bare; Cady follows in the chain with the substantive parenthetical (which itself is "(quoting Pack v. Yusuff)"). |
| 5 | Omosegbon v. Wells | Yellow→Red | **Real miscitation** | Parenthetical IS for Omosegbon — directly attached. Sonnet says the case dismissed on the merits (lack of cognizable property/liberty interest, failure to state First Amendment violation), with sovereign immunity barring only money damages — not the dispositive holding. The citing court mis-stated Omosegbon's basis. |

**Revised real miscitation rate: ~1/117 ≈ 0.85%** (Omosegbon clean, Moore ambiguous, all others mining issues).

## What kind of mining bug is this?

The eyecite/build_dataset pipeline attaches "the parenthetical that follows" to "the citation that just appeared." That works for `Case_X (substantive parenthetical)`. It breaks down on chains like:

- `Case_A; Case_B (substantive parenthetical)` — parenthetical belongs to B but the parser sometimes attaches to A
- `Case_A (quoting Z); see Case_B (substantive parenthetical)` — Festo example. The "(quoting Z)" is a citation-marker parenthetical; the substantive parenthetical is for B.
- `Case_A, citation. And, [text]. See Case_B (parenthetical)` — Irwin example. Sentences and intervening citations don't reset the parenthetical's owner correctly.
- Footnote text wrapping past the parenthetical close-paren can leak into the captured text (Irwin's "(finding that equitable [footnote] The DCHRA was recently amended...").

This is a **substantial v2 issue**: 3/5 of v1's "Reds" came from it, and the same misattribution pattern likely affects an unknown number of Greens and Yellows that *happened to* still produce a defensible verdict despite being attributed to the wrong case. We don't have a clean estimate of the prevalence. Auditing 50-100 random Greens with the same in-context check would give a baseline rate of mis-attribution.

## Implications for v1.1 calibration study

The v1.1 calibration study (`benchmark_v1/calibration.md`) concluded "Opus stays as primary; Sonnet/Haiku fail the 90% agreement bar; cheaper-frontier-model substitution is closed." That conclusion was measured on 20K-truncated input for all three models.

The full-text data here (gold pairs, n=117) suggests a different shape:

- **Sonnet at full text agrees with the audit's truth estimate at ~91% Green** — comparable to what we'd expect Opus@full-text to show. Sonnet's 5 Reds reclassify to 1 real miscitation + 3 mining bugs + 1 ambiguous.
- **Haiku at full text is a clear fail** — and would fail the calibration bar at any input window.

So the v1.1 conclusion holds for Haiku but is **likely wrong for Sonnet**. A definitive answer requires re-running the full 514-cell calibration study at full text, scoring with both Sonnet and Opus, and computing agreement. That's a v1.4 candidate (~1000 calls, all subscription quota). We can ship v2 with Sonnet-as-assessor on the strength of the gold-pair data alone if cost is the priority; the formal calibration re-run becomes a "validation we can do later" rather than a gate.

## Implications for v2 design

1. **Promote Sonnet 4.6 to default assessor.** ~5x cheaper than Opus per call. Distribution at full text on v1 matches expectations. Subscription-only spend.
2. **Mining pipeline needs a parenthetical-attribution audit.** Before v2 mining ships, verify eyecite's parenthetical attachment behavior on chained citations and patch as needed. The 3-bugs-out-of-5 rate in v1's Reds is a serious quality signal — the same misattribution likely affects propositions that survived assessor review purely by luck.
3. **Use the full opinion text by default.** No more `MAX_OPINION_CHARS = 20000` baked into shared utilities. Either remove the cap entirely or make it an explicit caller-side parameter.
4. **The 4 Sonnet+Haiku-both-Red cases are a high-precision miscitation filter.** Useful for triaging future datasets — start with cases where multiple assessors agree Red, those are the highest-confidence problems.

## Cost summary for this work

All on Claude CLI subscription quota — no out-of-pocket spend.

| Run | Calls | Wall time | Notional quota cost |
|---|---:|---:|---:|
| Sonnet @ full text (117 pairs, 23 cached from audit) | 94 | ~30 min | ~$15-25 |
| Haiku @ full text (117 pairs) | 117 | ~15-20 min | ~$3-6 |
| **Total** | 211 | ~50 min wall (parallel) | **~$18-30** |

## Artifacts

- [`tests/benchmark_v1/score_gold_pairs_fulltext.py`](../../tests/benchmark_v1/score_gold_pairs_fulltext.py) — the methodologically-correct successor to score_gold_pairs.py, uses CourtListenerClient directly, hard-fails on no-text rather than silently writing Reds
- [`scratch/find_red_context.py`](../../scratch/find_red_context.py) — extracts each Red's parenthetical-in-context from the citing opinion
- [`scratch/red_context.md`](../../scratch/red_context.md) — output of the above; the 5 Reds with citing/cited URLs and surrounding text
- `gold_db/gold.db` — 117 Sonnet@FT verdicts + 117 Haiku@FT verdicts under `assessor_prompt_version='v1-fulltext'`
- [`scratch/score_fulltext_sonnet.log`](../../scratch/score_fulltext_sonnet.log), [`scratch/score_fulltext_haiku.log`](../../scratch/score_fulltext_haiku.log) — run logs

## v1.4 follow-up items

- [ ] **Patch `pilot_a/score.py:fetch_opinion_text`** — make truncation explicit-by-caller, default to no-cap. Or deprecate in favor of citation-verifier's `CourtListenerClient.get_opinion_text_with_metadata`.
- [ ] **Audit eyecite's parenthetical-attribution logic.** Replicate the chained-citation patterns from Festo / Irwin / Maleng in unit tests; characterize the bug; either fix in eyecite (upstream PR) or add post-processing in `build_dataset.py` to re-attach parentheticals correctly.
- [ ] **Random-sample Green / Yellow audit.** 50-100 random non-Red gold pairs read in context to estimate the parenthetical-mis-attribution rate across the whole v1 dataset, not just the Reds.
- [ ] **Re-run v1.1 calibration at full text** *(optional)*. ~514 cells × 2 candidate models = ~1000 Sonnet + Haiku calls. Would give a definitive "Sonnet vs Opus at full text" agreement number. **Not blocking v2** — the gold-pair full-text data already validates Sonnet enough to ship as v2 assessor; the calibration re-run is academic confirmation.
- [x] ~~**Re-run gold-pair Opus at full text.**~~ **Dropped 2026-05-04.** Sonnet@FT supersedes the need for an Opus@FT canonical baseline — Sonnet IS the v2 assessor. Task 10's 117 mis-labeled rows were relabeled to `(prompt_version='v1-task10', opinion_window_chars=20000)` to reflect actual scoring conditions; the Opus@20K data is preserved with honest metadata, and we don't re-pay for Opus.
- [ ] **Audit Yellow gold-pair verdicts at full text.** 11 Yellows in the canonical run — same script, different filter. Probably mostly truncation-affected.
- [ ] **Investigate Moore (cluster 222130).** Cache file is 23K; opinion at `651 F.3d 30, 63` is likely longer. Either pull fresh full text or accept that this one Red is genuinely indeterminate from our data.
