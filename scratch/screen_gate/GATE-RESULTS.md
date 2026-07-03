# Tier-0 screening gate — first full run (2026-07-03)

Reproduce: `python run_gate.py` (reads the corpus in place from us-legal-research
via `SCREEN_GATE_CORPUS`; see `run_gate.py` header). `--json` for machine output.

## Corpus as run

11 bad (7 attorney, 4 pro se), 7 control (4 attorney, 3 pro se). **Small n —
every number below is directional, not a final verdict.**

Two data-quality caveats that cap what this run can show:

1. **`burnside-verdick.txt` is an un-OCR'd scan stub** — the file is only the
   manifest header + 74 PACER page-stamp footers, **0 body text, 0 cites
   extracted**. It contributes nothing until OCR'd (PROJECT.md §7 "OCR the
   Burnside scan"). Effectively bad-pro_se n=3, not 4.
2. **The two pro se / short-attorney workhorse signals are not implemented yet**
   (`chatbot_preamble`, `pdf_metadata`, PROJECT.md §3). So recall on short and
   pro se filings is structurally floored near zero in this run — the absence is
   expected, not a finding against the approach.

## Per-document flags

| slug | label | filer | cites | flags | signals fired |
|---|---|---|---|---|---|
| support-community-mph | bad | attorney | 111 | 8 | arithmetic, authority_drift, court_contradiction, statute_grammar, style_variance |
| tantaros-fox-news | bad | attorney | 31 | 1 | toa_body_diff |
| tantaros-fox-news-surreply | bad | attorney | 16 | 0 | — |
| withers-aberdeen | bad | attorney | 16 | 0 | — |
| villalovos-vandepol | bad | attorney | 39 | 4 | authority_drift |
| johnson-dunn | bad | attorney | 4 | 0 | — |
| braun-day | bad | attorney | 11 | 0 | — (has the chatbot preamble — signal not built) |
| reed-community-health | bad | pro_se | 10 | 0 | — (PDF Title "Creates a legal pleading" — signal not built) |
| stafford-taffet | bad | pro_se | 42 | 0 | — |
| sherwood-botetourt | bad | pro_se | 116 | 2 | authority_drift |
| burnside-verdick | bad | pro_se | 0 | 0 | — (un-OCR'd stub) |
| ctrl-cand-msj | control | attorney | 258 | 10 | authority_drift, style_variance, toa_body_diff |
| ctrl-nysd-mtd-opp | control | attorney | 83 | 2 | style_variance, toa_body_diff |
| ctrl-nysd-reply | control | attorney | 55 | 1 | toa_body_diff |
| ctrl-msnd-msj | control | attorney | 116 | 0 | — |
| ctrl-wawd-prose-resp | control | pro_se | 45 | 0 | — |
| ctrl-ord-prose-resp | control | pro_se | 26 | 0 | — |
| ctrl-vawd-prose-compl | control | pro_se | 2 | 0 | — |

## Per-signal separation

### Attorney stratum (bad=7, control=4) — where Tier-0 shape signals are defined

| signal | recall (bad) | FP (control) | directional verdict |
|---|---|---|---|
| court_contradiction | 1/7 | 0/4 | **clean separator**, low recall |
| statute_grammar | 1/7 | 0/4 | **clean separator**, low recall |
| arithmetic | 1/7 | 0/4 | **clean separator**, low recall |
| authority_drift | 2/7 | 1/4 | separates but has the government-litigant FP (ctrl-cand-msj) |
| style_variance | 1/7 | 2/4 | **NOISE** — fires on 50% of controls |
| toa_body_diff | 1/7 | 3/4 | **NOISE (worst)** — fires on 75% of controls |

Caveat: the three "clean separators" **all fired only on the single MPH
fixture.** Zero control FP is real and good, but their recall is measured off one
richly-bad brief — treat "low recall" as "unknown recall."

### Pro se stratum (bad=3 usable, control=3)

Every Tier-0 shape signal is **silent on both sides** except `authority_drift`
(1/3 bad — sherwood, the 133-page one — vs 0/3 control). This confirms
PROJECT.md §5 finding #1 directly: **Tier-0 citation-shape signals do not detect
short / pro se fabrication.** The tells for that stratum are metadata and chatbot
preamble, which aren't built.

## Directional verdict (six implemented signals)

- **Keep, provisionally: `court_contradiction`, `statute_grammar`, `arithmetic`.**
  Zero control FP, fully explainable as facts-about-text. Low/unknown recall is
  acceptable for a high-precision tell. All three need more bad-brief firings
  before recall is meaningful.
- **`authority_drift`: keep but fix the FP.** Best recall (3 firings incl. one
  pro se), but the government-litigant caption collision (PROJECT.md §5 #4, open
  decision #3) tripped it on ctrl-cand-msj. Needs the disambiguation carve-out.
- **`style_variance`: on the bubble.** 50% control FP as written fails the ship
  rule. Tighten or drop — judgment call (PROJECT.md §7 reserves style-variance
  thresholds for the reasoning-model session).
- **`toa_body_diff`: closest to dead.** 75% control FP — it is catching benign
  TOA-vs-body extraction differences in legitimate briefs, not fabrication. Needs
  a materiality threshold to survive, or it dies at the gate.

## Texture / tell-signal probe (2026-07-03, `probe_texture.py`)

A throwaway diagnostic run to pressure-test two design assumptions before
building. **Negative results — worth not re-discovering.**

**Tell signals (preamble / metadata) are lottery tickets, not workhorses:**
- `chatbot_preamble` recall = **1/11** (braun-day only). A loose phrase bank
  ("here is a") false-fires on all 4 attorney controls; only tight phrases
  ("court-ready", "you can insert", "calibrated for") isolate braun-day at 0 FP.
- `pdf_metadata`: of 4 bad docs with captured metadata, only Reed
  ("Creates a legal pleading") is an AI tell; Burnside = scanner string,
  Sherwood/Stafford = normal Word. Realistic recall ~1–2/11, and **zero control
  metadata exists** so its FP rate is unmeasurable. PROJECT.md §5 #3's framing of
  these as "pro se workhorses" is **not supported** — they're rare smoking guns.

**Cheap texture proxies do NOT separate — they anti-separate.** Group means
(docs ≥5 cites): gerund-paren/cite bad-att 0.084 vs control-att 0.107;
any-paren/cite bad 0.179 vs control 0.197; cite-density bad-att 6.9 vs
control-att 14.0. On every proxy the **controls look more AI-textured**, because
these metrics measure *professionalism* and the controls are best-in-class briefs
(Earthjustice, AG coalitions) while the fabricated briefs are sparser/shorter.
Texture separates quality, not AI-ness, and quality is confounded with the label.
This is PROJECT.md's "likeliest to die at the gate" prediction arriving early.

Caveats: tiny n (2–6/cell); and only the *easy* proxies were tested. The actual
Tier-0.5 hypotheses (**proposition repetition with reshuffled cites**,
**citation-to-proposition uniformity**) target the generation fingerprint rather
than professionalism and remain **untested** — test those before retiring
Tier 0.5. Also surfaced: the pro se bad briefs fire zero Tier-0 signals despite
fake cites; only Tier-1 existence lookup catches them. There may be no zero-cost
rung-0 detector for well-formed fabrication.

## Tier-0.5 probe #2 — the real hypotheses (2026-07-03, `probe_repetition.py`)

Tested the two hypotheses that target the *generation fingerprint* rather than
professionalism: **proposition repeat** (same point restated with different
cites) and **cite-per-proposition uniformity** (CV). Verdict: **Tier 0.5 does
not clear the gate on this corpus.**

- **proposition_repeat — weak, confounded, pro-se-silent.** Normalized rate
  leans right (bad-att 0.066 vs control-att 0.014) but a legit brief
  (ctrl-cand-msj, 6 pairs, rate 0.039) lands inside the bad range; the bad mean
  is inflated by braun-day (1 pair / 5 props = 0.200, n-noise) and the MPH
  fixture. Zero firing across the entire pro se stratum. The one genuinely odd
  datum is MPH's cluster of 4 reshuffled-cite propositions.
- **cite_prop_uniformity (CV) — separates for the wrong reason.** bad-att CV
  0.101 vs control-att 0.314 (bad more uniform, as hypothesized) — but only
  because bad briefs cite one case per point while controls **string-cite**.
  CV measures string-citation sophistication (professionalism), can't distinguish
  "uniform because AI" from "uniform because unsophisticated filer," and would
  flag honest pro se briefs.

**Structural conclusion (both probes).** Our controls are best-in-class briefs,
so every document-internal statistic — parenthetical rate, density, repetition,
uniformity — ends up measuring **professionalism**, which is confounded with the
label. There is no free-lunch zero-network statistical detector at rung 0 in this
data. The signal that generalizes across all fabrication (including the pro se
briefs that fire nothing on Tier 0/0.5) is **Tier-1 existence checking**.

**One ember worth re-testing at 2x corpus:** proposition-repeat-with-different-
cites (rate + max_cluster) is the only structural metric that leaned right
without a pure professionalism confound — repeating a point with *different*
authorities is genuinely unusual for a human. Re-test it, not the others, if the
corpus doubles. Everything else in Tier 0.5 is retired.

## Immediate next (unblocked, mostly mechanical)

1. **Implement `chatbot_preamble`** — pure text, near-zero FP; braun-day is a
   known positive that currently fires nothing. Highest recall/cost ratio left.
2. **Implement `pdf_metadata`** — BUT metadata is captured for only 4 purchased
   *bad* docs and **zero controls**, so it cannot be FP-gated yet. Need control
   PDF metadata (capture at purchase / re-pull). Reed's Title "Creates a legal
   pleading" is the single strongest tell in the whole corpus.
3. **OCR `burnside-verdick`** or drop it from the gate.
4. **Rework or retire `style_variance` + `toa_body_diff`** — the reasoning-model
   FP-adjudication step (PROJECT.md §7).
