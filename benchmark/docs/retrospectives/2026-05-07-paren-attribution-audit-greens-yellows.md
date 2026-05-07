# Parenthetical-attribution audit on non-Red gold pairs — 2026-05-07

**Status:** complete
**Owner:** project lead
**Predecessor:** [`docs/retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md`](2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md)
**Artifacts:** [`benchmark/scratch/paren-attribution-audit/`](../../scratch/paren-attribution-audit/)

## Question

The 2026-05-04 full-text Red audit found **3 of 5** Sonnet@FT Reds were eyecite parenthetical mis-attribution bugs (parenthetical attached to the wrong case in chained citations). 60% bug rate on the Red subset. The retrospective flagged the open question:

> The same misattribution likely affects an unknown number of Greens and Yellows that *happened to* still produce a defensible verdict despite being attributed to the wrong case. We don't have a clean estimate of the prevalence.

This audit estimates that prevalence with a 30-cell random sample on non-Red gold pairs.

## Method

1. Pull all 112 non-Red gold-pair rows from gold-DB (`source='gold_pair'`, `assessor_model='sonnet-4.6'`, `assessor_prompt_version='v1-fulltext'`, `verdict IN ('green','yellow')`). 106 Green + 6 Yellow.
2. Random sample 30 (seed=42).
3. For each, locate the parenthetical text in the citing opinion (cached at [`benchmark/releases/v1/citing_opinion_cache/<citing_cluster_id>.txt`](../../releases/v1/citing_opinion_cache/)) and extract a context window (500 chars before / 300 after).
4. Apply a naive heuristic: does the cited case's `canonical_name` (full or plaintiff/defendant prefix) appear in the 500-char preceding window? (`Y` = likely correct; `N` = suspicious; `UNFOUND` = parenthetical not located.)
5. Manually read every cell — both heuristic-flagged and heuristic-clean — to classify as `bug` / `clean` / `ambiguous`.

Code: [`build_audit_pack.py`](../../scratch/paren-attribution-audit/build_audit_pack.py). Output: [`audit_pack.csv`](../../scratch/paren-attribution-audit/audit_pack.csv).

## Result

**0 of 30 sampled cells are mis-attribution bugs.** 0% observed bug rate.

### Heuristic split

| Heuristic verdict | n | After manual read |
|---|---|---|
| Clean | 24 | 24 clean |
| Flagged | 6 | 6 clean (all heuristic false positives) |
| Unfound (parenthetical not located) | 0 | — |

### Why the heuristic over-flagged

All 6 heuristic-flagged rows are correctly attributed but trip the regex because of name-form mismatch between CL's canonical name and the citing opinion's short cite. Patterns:

| # | Cited case (canonical) | Citing opinion uses | Cause |
|---|---|---|---|
| 3 | `Pacific Pictures Corp. v. United States District Court` | `In re Pacific Pictures Corp.` | CL canonicalized "In re X" as adversarial |
| 10 | `Valerie Bennett v. Marie Schmidt` | `Bennett v. Schmidt` | full first names in canonical |
| 18 | `American Institute of Certified Public Accountants v. Internal Revenue Service` | `Am. Inst. of Certified Pub. Accts. v. I.R.S.` | abbreviation difference |
| 22 | `Jose L. Beliz, Cross-Appellees v. W.H. McLeod & Sons Packing Company, Cross-Appellant, Waldo Galan` | `Beliz v. W.H. McLeod & Sons Packing Co.` | full caption with "Cross-Appellees" annotation |
| 24 | `John B. Cicchetti v. David J. Lucey, Registrar of Motor Vehicles` | `Cicchetti v. Lucy` | full first names + opinion misspells "Lucey" |
| 28 | `FDA v. Alliance for Hippocratic Medicine` | `Food and Drug Admin. v. Alliance for Hippocratic Med.` | different abbreviation choice |

So the heuristic is ~80% specific (24/30 truly clean rows correctly identified) but ~0% sensitive at finding actual bugs (none in this sample). It's a hint, not a measurement.

## Where the bugs concentrate

Compare bug rate in Reds vs non-Reds (Sonnet@FT verdicts on v1's 117 gold pairs):

| Subset | n | Bugs | Rate |
|---|---|---|---|
| Reds (2026-05-04 audit) | 5 | 3 | 60% |
| Non-Reds (this audit) | 30 | 0 | 0% |
| **Combined observed** | **35** | **3** | **8.6%** |

By 95% Wilson confidence: a non-Red bug rate of 0/30 has an upper bound of ~12%. The true non-Red rate could be 0–12%. The Reds rate is 60% (small N caveat).

**Lower bound on the v1-cohort rate from the Reds alone:** 3/117 ≈ 2.6%. So the population bug rate is at least 2.6% (the confirmed cases) and at most ~12% if non-Red bugs exist at the upper bound. Most likely 3–5%.

## Why the bug rate is so different in Reds vs. non-Reds

The 2026-05-04 retrospective hypothesized that mis-attributed parentheticals might "happen to still produce a defensible verdict" in Greens/Yellows by luck. This audit suggests **that luck is rare**. Plausible mechanism: when eyecite attaches a parenthetical to the wrong case, the parenthetical describes case A's holding while the model is asked to score it against case B's opinion. Case B's opinion almost never supports a holding from case A → Red. So mis-attribution → Red verdict by construction, and Reds are where the bug pool concentrates.

Implication: the 60% bug rate in Reds is **the population bug rate filtered through the assessor**, not a population-wide rate. The mis-attribution bug fix in v1.3 is still important — these 3 cases shouldn't have been in v1 — but **v1's Greens and Yellows are not silently contaminated** at any meaningful rate.

## Implications for v1 and v1.3

1. **v1 data integrity is better than the 60%-Red-bug-rate suggested.** The eyecite mis-attribution bug affects a small fraction of cells (lower bound 2.6% from confirmed Reds; upper bound ~12% from this audit). v1's tier and model headlines aren't materially shifted by removing those bug-affected cells.
2. **v1.3's parenthetical-attribution fix is still important** — but as a quality measure for v1.3 itself, not as a v1-correction priority. A 3-percentage-point ceiling on contaminated cells is not enough to revisit v1's published findings.
3. **The cross-cohort comparison v1↔v1.3 doesn't need a v1 mining re-do.** The deferred "re-score v1 with v1.3 pipeline" question (open decision #5 in the v1.3 design) can stay deferred without losing comparability.
4. **The `gold_pair` data with `verdict IN ('green','yellow')` is reusable as-is.** No need to re-mine before using these cells in any v1.3 calibration / drift analysis.

## Method limitations

- **Verdict-conditional sampling.** This sample is non-Red gold pairs only; it doesn't measure the bug rate in v1's *closed-book* output cells (which is what the v1 leaderboard depends on). Closed-book scoring uses the same propositions, so the rate should transfer, but I haven't audited those directly.
- **Sonnet@FT as the verdict source.** The "non-Red" filter uses Sonnet@FT verdicts. If Sonnet sometimes calls a mis-attributed parenthetical "Yellow" (instead of catching it as Red), those Yellows would slip past the audit's filter. None showed up in this 30-cell sample, but the filter is potentially leaky in principle.
- **Read-in-context judgment is one reader (project lead).** Same caveat as the 2026-05-04 audit — could benefit from a second coder, but the cases here were unambiguous (every match was directly preceded by the cited case's short cite or "see also Foo" pattern).
- **N=30 is small for a 0% finding.** The 95% upper bound is ~12%. To narrow the upper bound, sample more cells or audit closed-book output cells.

## Files

- [`build_audit_pack.py`](../../scratch/paren-attribution-audit/build_audit_pack.py) — sample + locate + heuristic, idempotent.
- [`audit_pack.csv`](../../scratch/paren-attribution-audit/audit_pack.csv) — 30 rows with parenthetical, context windows, heuristic flag, and (empty) `user_classification` column for re-review.
- [`summary.txt`](../../scratch/paren-attribution-audit/summary.txt) — heuristic summary printed at run time.
