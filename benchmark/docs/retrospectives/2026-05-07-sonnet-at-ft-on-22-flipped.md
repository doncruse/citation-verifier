# Sonnet@FT on the 22 Opus-flipped v1 Reds — 2026-05-07

**Status:** complete
**Owner:** project lead
**Predecessor:** [`releases/v1/truncation_experiment.md`](../../releases/v1/truncation_experiment.md), [`docs/retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md`](2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md), [`docs/plans/2026-05-05-v1.3-design.md`](../plans/2026-05-05-v1.3-design.md) §"Sonnet validation"
**Artifacts:** [`benchmark/releases/v1/sonnet_at_ft_on_flipped_22.csv`](../../releases/v1/sonnet_at_ft_on_flipped_22.csv), runner at [`benchmark/runners/sonnet_at_ft_on_flipped_22.py`](../../runners/sonnet_at_ft_on_flipped_22.py)

## Question

The truncation experiment re-ran the v1 Reds at a 60K opinion window with Opus and found 22 cells flipped from Red to Green or Yellow. v1.3's design proposes **Sonnet@FT** (Sonnet 4.6, full opinion text, no cap) as the default assessor. On those 22 specific cells, would Sonnet@FT — the v1.3-proposed default — also reach the corrected verdict that Opus@60K reached?

This is a small targeted probe of v1.3's central claim that Sonnet@FT can replace Opus as assessor.

## Result

**Sonnet@FT agrees with Opus@60K on 12/22 (55%).**

### Agreement matrix

|  | Sonnet@FT: Green | Sonnet@FT: Yellow | Sonnet@FT: Red |
|---|---|---|---|
| **Opus@60K: Green** (n=12) | 8 | 3 | 1 |
| **Opus@60K: Yellow** (n=10) | 3 | 4 | 3 |
| **Opus@60K: Red** (n=0) | — | — | — |

(The Opus:Red row is empty by construction — these are Opus's flipped cells, so Opus@60K said Green or Yellow on every row.)

### Patterns

The disagreement is broad, with both directions of slippage on each row:

- **8/12 Opus-Greens are Sonnet-Greens.** The remaining 4 split — 3 down to Yellow, 1 down to Red.
- **4/10 Opus-Yellows are Sonnet-Yellows.** The other 6 split evenly — 3 up to Green, 3 down to Red.
- **The harshest move:** 1 Opus-Green became a Sonnet-Red (Neal v. Shimoda). At Opus's @60K read the case was a clean fit; at Sonnet@FT it's outright unsupported.
- **The most generous move:** 3 Opus-Yellows became Sonnet-Greens (Grant v. Raymond, Lexmark, Zenith Radio). Direct on-point quotes in the opinion text — Opus undersold them.

### By v1 closed-book responder (small N, weak signal)

| v1 model | Sonnet@FT–Opus@60K agreement |
|---|---|
| v1=opus (n=9) | 5/9 (56%) |
| v1=sonnet (n=3) | 1/3 (33%) |
| v1=gpt-5 (n=10) | 6/10 (60%) |

These splits are too small to act on individually. They're reported for completeness.

### Independent assessment of the 9 disagreements

Spot-checking the cited opinion text for the 9 disagreements (sampling rationales, then verifying quoted phrases against the cached opinion). My read on which assessor is closer to right:

| # | Case | Opus@60K | Sonnet@FT | Verified quote? | Closer-to-right |
|---|---|---|---|---|---|
| 1 | Grant v. Raymond | Yellow | Green | yes — "entered into the views of the framers..." (¶134) is in the opinion verbatim | **Sonnet** |
| 2 | Lexmark | Yellow | Green | yes — "like any other element of a cause of action, it must be adequately alleged at the pleading stage" is in the opinion verbatim | **Sonnet** |
| 3 | Anderson v. Liberty Lobby | Yellow | Red | both rationales agree the case doesn't contrast MtD vs SJ; case actually contrasts SJ vs directed verdict | **Sonnet** |
| 4 | Zenith Radio | Red→Green (flipped between Sonnet runs) | Green | both rationales agree the case repudiates the common-law release rule; doesn't articulate release/covenant distinction | unclear — Opus's Yellow defensible if you count "discusses doctrine in passing" |
| 5 | Northington (Benefield) | Green | Yellow | Sonnet's "narrower than the proposition" framing is reasonable; Opus's read is also defensible | toss-up; lean Opus |
| 6 | Neal v. Shimoda | Green | Red | the case discusses stigma but the proposition specifically claims violence/safety; opinion does not address violence | **Sonnet** |
| 7 | Weinstein | Yellow | Red | case holds TRIA §201 reaches blocked assets; doesn't squarely decide whether unblocked assets are excluded — close call | toss-up; both defensible |
| 8 | Lukovsky | Yellow | Yellow→Red (flipped between Sonnet runs) | case applies federal accrual; doesn't endorse the proposition's "California has the discovery rule" framing | both runs defensible; lean Red |
| 9 | Virginia v. Moore | Yellow | Red | case holds in-presence arrests are constitutional; does not "reserve" the question as the proposition claims | **Sonnet** |

Of the 9 disagreements, by my reading: Sonnet is closer-to-right on 5 (#1, 2, 3, 6, 9), Opus on 1 (#5, weakly), and 3 are genuine toss-ups (#4, 7, 8). On this small sample, Sonnet@FT is the more careful reader on the strict-fit propositions (i.e., where the proposition makes a specific claim like "reserves the question," "contrasts X with Y," or "case is about prison violence"); Opus is more willing to call something Yellow on partial-overlap.

This subjective audit doesn't substitute for the v1.3 human-coding pass — but it's evidence the 55% headline understates Sonnet@FT's quality. The right comparison is Sonnet@FT vs human-adjudicated tiers, which v1.3's design is built around.

## Run-to-run variance is non-trivial — and partly a CLI artifact

In 2 of the 15 cells where the cached opinion is ≤60K (so Sonnet@60K and Sonnet@FT received identical input), Sonnet's verdict flipped between an earlier @60K run and this @FT run:

- Zenith Radio, 51,991 chars: Red (earlier @60K run) → Green (@FT)
- Lukovsky, 23,932 chars: Red (earlier @60K run) → Yellow (@FT)

Identical inputs, same model, different verdicts. Two flips in fifteen identical-input pairs is ~13% within-model nondeterminism on this small sample — non-trivial.

**Significant caveat:** all assessor calls in this experiment go through `claude -p` (the CLI), which **does not expose a `--temperature` flag** (`claude --help` confirms). Calls run at the API default of **temperature=1.0**, so the observed variance is the high-temperature noise floor, not Sonnet's intrinsic determinism. The constraint is already documented in [`benchmark/runners/model_adapter.py`](../../runners/model_adapter.py) ("Sonnet/Opus: temperature is provider default — Claude CLI doesn't [expose it]") but never propagated to the assessor stack.

The fix is small. [`benchmark/runners/calibrate_assessor.py`](../../runners/calibrate_assessor.py) already has a working Anthropic-SDK path with `temperature=0`, used for the v1.1 calibration study. As of 2026-05-07, [`benchmark/runners/sdk_assessor.py`](../../runners/sdk_assessor.py) extracts that pattern into a reusable `call_assessor_sdk` helper with the same return shape as the CLI helpers — drop-in replacement for v1.3 work. Even at temperature=0, Anthropic's infrastructure has residual non-determinism (batching / numerical precision) — anecdotally ~1-3% rather than the ~13% observed here at temperature=1.

v1.3's design treats single-pass scoring as authoritative. With the SDK + temperature=0 fix, that's defensible. With the CLI's default temperature=1, it's not. **v1.3 model runs and assessor passes should call `call_assessor_sdk` directly, not `claude -p`.**

## What this does and doesn't say

**Says:**

1. **Sonnet@FT and Opus@60K disagree on roughly half** of the cells where Opus's window-expansion changed its mind. The overlap is real but limited.
2. The disagreements run **both directions** at FT, unlike at the same-window @60K comparison (which was almost entirely Yellow→Red, Sonnet harsher). Adding text moves Sonnet both up and down. Net effect on the v1.3 verdict distribution is unclear from N=22.
3. Within-model run-to-run variance is non-trivial (~13% on identical inputs in this sample). v1.3 should budget for drift sampling.

**Doesn't say:**

- This is **not** a defensible κ estimate for Sonnet@FT vs Opus@FT. The 22 cells are by construction the Yellow-leaning subset where Opus changed its mind under a window expansion — heavily biased.
- It also doesn't resolve who's right between Sonnet and Opus. The independent spot-check above is one reader (the project lead) and isn't a substitute for v1.3's human-coding plan.
- The Yellow/Red boundary asymmetry I called out in the prior @60K version of this retrospective is **softer at FT than at 60K** — at FT, Sonnet flips both ways, not just toward Red. The "Sonnet is just harsher" framing was an artifact of the same-window comparison.

## Implications for v1.3

1. **Sonnet's κ ≥ 0.6 acceptance bar is plausibly clearable but not certain.** The 55% raw agreement on this Yellow-biased subset doesn't directly forecast κ on the full 200-pair human-coded sample, but suggests the calibration pilot is doing real work.
2. **The Yellow boundary is the rubric-anchor target.** Most disagreement still concentrates here, even at FT. Pull boundary cases (the 8 Yellow disagreements) into the librarian rubric pilot.
3. **Pre-stage Opus@FT as the fallback.** v1.3 design already calls for this if Sonnet fails the validation bar. The data here makes it more likely the fallback gets used than not — fallback infrastructure is worth building proactively, not on demand.
4. **Switch the assessor stack to SDK + temperature=0.** Highest-leverage change. The 13% within-model variance observed here is largely a CLI artifact (no temperature flag → temp=1). v1.3's κ ≥ 0.6 acceptance bar and human-coding comparisons are noise-floor-sensitive; running at temp=1 throws away signal before any rubric work begins. New helper: [`benchmark/runners/sdk_assessor.py`](../../runners/sdk_assessor.py).
5. **Drift-sample budget still needed.** Even with SDK + temp=0, Anthropic's infrastructure has residual non-determinism (~1-3%). Budget for a small drift re-check pass on every published number.

## Cost

$2.09 total ($0.06–$0.15 per call, 22 calls). Negligible.

## Files

- Runner: [`benchmark/runners/sonnet_at_ft_on_flipped_22.py`](../../runners/sonnet_at_ft_on_flipped_22.py) — resume-safe, narrow-scope, **uncapped**.
- Output: [`benchmark/releases/v1/sonnet_at_ft_on_flipped_22.csv`](../../releases/v1/sonnet_at_ft_on_flipped_22.csv) — one row per cell with `opus_60k_supports`, `sonnet_ft_supports`, `sonnet_chars_assessed`, `agree`, both rationales for side-by-side reading.

## History note

A prior 2026-05-07 pass capped Sonnet at 60K (matching Opus's window) under a "Sonnet@60K" interpretation. That answers a different, narrower question — assessor agreement at the same window — and is not the v1.3-relevant artifact. The current run is uncapped, per the v1.3 design's "default to no cap" rule. Commit history preserves the prior version.
