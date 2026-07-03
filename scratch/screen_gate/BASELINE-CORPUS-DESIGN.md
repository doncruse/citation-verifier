# `screen` baseline corpus — design

**Status:** design approved 2026-07-03 (branch `screen-signals-gate`,
`scratch/screen_gate/`). Supersedes the AI-detection framing of the gate; see
Background. Companion to `PROJECT.md` (project scope) and `GATE-RESULTS.md`
(the four probes that motivated this pivot).

---

## Background — why the gate is being rebuilt

The original `screen` gate hunted **AI-fabrication tells** on a bad/control
corpus. Four probes (recorded in `GATE-RESULTS.md`) converged on one wall:

1. The six Tier-0 signals separate only on the single richly-bad MPH fixture;
   `style_variance` (50% control FP) and `toa_body_diff` (75%) are noise.
2. The tell signals (`chatbot_preamble`, `pdf_metadata`) are lottery tickets —
   1/11 and ~1/11 recall.
3. Both Tier-0.5 texture probes **anti-separate**: every document-internal
   statistic measures *professionalism*, which is confounded with the label
   because our controls are best-in-class briefs and our fakes are often sparse.

The reframing (this session): `screen` is not a fabrication detector — it is an
**effort-triage gate**. The question is *"is this a serious filing worth
spending the verification pipeline on, or trash to bounce back for a rewrite?"*
Existence-checking is circular (it *is* the pipeline). The signal has to be
cheap, deterministic, and — critically — read **per filer stratum**, because the
same surface metric flips meaning: dense sophisticated citation is *normal* for
an attorney and *anomalous* for a pro se litigant.

That makes the gate a **within-stratum anomaly detector**: does a document
deviate from what is *normal for its kind*? You cannot detect deviation without a
baseline, and our three heterogeneous control pro se briefs (a prisoner-with-
clerical-help at 45 cites, a sovereign-citizen at 26, a sparse complaint at 2)
are not a baseline. **The bottleneck is "what is normal?" — a data problem, not a
code problem.** This corpus supplies that missing reference distribution.

## 1. What we are building

A **reference distribution of normal filings**, stratified, against which any
document's surface-metric profile can be scored for deviation. These are NOT
"controls" in the matched-pair sense — they are a representative sample of
typical practice per stratum. The existing 11 court-confirmed bad docs remain the
**deviation test set**; this corpus is the normal they are tested against.

## 2. Stratification

**filer_type × doc-type bucket** — 6 cells:

| doc-type bucket | attorney | pro se |
|---|---|---|
| **merits brief** — MSJ/MTD memoranda, oppositions, replies (heavy citation load, argument section, often a TOA) | ✔ | ✔ |
| **pleading** — complaints, amended complaints (fact-heavy, sparser citation) | ✔ | ✔ |
| **procedural motion** — discovery/compel/remand/other procedural motions (light citation) | ✔ | ✔ |

- `merits brief` deliberately absorbs oppositions/replies to dispositive motions:
  the axis that matters is **citation load**, and an opposition to an MSJ carries
  a merits-brief load. (Revisit only if the data shows oppositions form their own
  mode.)
- Court is **recorded but not stratified** — federal citation norms are more
  circuit/nation-wide than court-specific, and adding court explodes the cells.

## 3. Selection frame

- Federal RECAP, `is_available=true` (free extracted text — normal filings are
  far more available than the rare sanctioned ones).
- Doc-type assigned from the RECAP docket-entry description.
- `filer_type` assigned from counsel-of-record presence vs. a pro se signature
  block — checked **per document**, not assumed from the caption (the
  `villalovos` lesson: fabrications sat in the *defendant's* sections).
- **Screened for a clean docket**: no sanction / show-cause / fabrication /
  hallucination history (the exact screen the existing controls used).
- **No minimum-citation floor.** We want the natural distribution, including
  genuinely sparse filings — a floor would bias every baseline upward and make
  honest sparse documents look anomalous.
- Rough randomness over cherry-picking: sample across courts and dates within a
  cell rather than taking the first N hits, so no single court/firm dominates a
  baseline.

## 4. Target size — phased

- **Phase 1: 10 per cell (~60 docs).** Enough for provisional medians/spreads;
  re-run the gate immediately to see whether deviation separates at all.
- **Phase 2: expand to 20 per cell** only if Phase 1 deviation looks real.
- **Pro se cells are the binding constraint** (clean, non-sanctioned, text-
  available pro se filings are genuinely scarce — the earlier control-pull
  needed ~9 tool calls for one near-miss). If a pro se cell lands below target,
  record the shortfall honestly rather than pad with near-misses; a thin pro se
  baseline is a documented limitation, not a silent one.

## 5. Metric schema (per-doc feature vector)

Consolidate `probe_texture.py` + `probe_repetition.py` into one shared
`metrics.py` extractor (deterministic, zero-network, already ~90% written):

| metric | meaning |
|---|---|
| `n_cites` | eyecite-spine citation count |
| `words` | normalized token count (document length proxy) |
| `cite_density` | citations per 1,000 words |
| `parenthetical_richness` | explanatory parentheticals per citation |
| `string_cite_rate` | fraction of cite-bearing sentences with ≥2 citations (marshaling) |
| `gerund_paren_rate` | gerund-led parentheticals per citation |
| `has_toa` | Table of Authorities present (bool) |
| `proposition_repeat_rate` | same-proposition/different-cite repeat pairs per proposition |
| `cite_prop_cv` | coefficient of variation of citations-per-proposition |

Every metric is a fact about the text — no model judgment — preserving the
sanctions-explainable property of the original design.

## 6. From corpus to gate

1. Per cell, compute **median + robust spread (MAD)** for each metric.
2. Score any document as a **robust-z profile** against its own cell
   (`z = (x − median) / (1.4826 · MAD)`), flagging metrics beyond a cell whisker.
3. **Gate test:** do the 11 known-bad docs land in their cells' tails more often
   than the baseline's own members do (leave-one-out on the baseline for the null
   rate)? A metric graduates only if bad-doc deviation clears the baseline's own
   tail rate **within a stratum** — the same ship rule as `PROJECT.md` §6.3,
   now measured against a real reference instead of matched pairs.

## 7. Artifacts & location

```
scratch/screen_gate/baseline/
  <cell>/<slug>.txt                      # extracted filing text
  <cell>/manifest-<cell>.jsonl           # one row per doc: slug, court,
                                         #   docket_id, document_number,
                                         #   filer_type, doc_type, recap_url,
                                         #   is_available, sanction_screen, notes
  metrics.csv                            # per-doc feature vector (metrics.py)
  baselines.json                         # per-cell median + MAD per metric
scratch/screen_gate/metrics.py           # shared deterministic extractor
scratch/screen_gate/run_gate.py          # extended to score deviation
```

Migrate the whole `screen_gate/` tree into `src/citation_verifier/` only if the
deviation gate passes (PROJECT.md open decision #1 — self-contained CV corpus).

## 8. Build mechanism

Retrieval via **sonnet** agents against CourtListener/RECAP (PROJECT.md §7 model
tiering — this is mechanical retrieval, not reasoning). Each agent: pick a cell,
find candidate docket entries by doc-type, confirm filer_type per document, run
the sanction/show-cause docket screen, save `is_available` text, append a
manifest row. The implementation plan sequences this (one agent per cell, or a
small fan-out) and is written next via the writing-plans skill.

## 9. Out of scope

- Any **LLM signal** (the rung-0.5 "is this serious?" call was considered and set
  aside — this gate stays deterministic).
- The **coherence / hollowness** axis (semantic; not visible to surface metrics).
- **Buying more bad docs** — the `PURCHASE-LIST.md` is a separate lever; this
  corpus needs *normal* documents, which we have never had, not more fakes.
- Court-level or firm-level stratification.
