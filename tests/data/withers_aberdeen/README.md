# Withers v. City of Aberdeen — citation-audit corpus

**Source:** `exhibit1_doc112-1.pdf` — Exhibit 1 to Doc. 112-1 in *Withers v. City of
Aberdeen*, No. 1:24-cv-00218-SA-RP (N.D. Miss., filed 12/24/2025). A party-authored,
citation-by-citation audit of the plaintiff's (apparently AI-assisted) filings,
color-coded green / yellow / red. Public PACER filing.

**Built artifacts:**
- `tests/build_withers_corpus.py` → `tests/data/withers_aberdeen_corpus.csv` (54 rows).
- `tests/measure_withers_baseline.py` → `tests/data/withers_baseline_results.csv`
  (current verifier's existence-layer prediction per row; live API).

**Columns** (`withers_aberdeen_corpus.csv`): `row_id, doc_number, pleading, citation,
proposition, exists (Yes/No), label (green/yellow/red), hedged (yes/no), irregularity`.
`exists` and `label` are reliable (color + Yes/No unambiguous). `proposition` and
`irregularity` are hand-transcribed — the PDF is authoritative if a cell is in doubt.
`hedged=yes` marks rows where the author's own call is explicitly tentative
("arguable", "debatable", "seems", "appears", "I believe").

**Label distribution:** 32 green (ok), 19 yellow (real case, proposition/quote
problem), 3 red (hallucinated). 51 exist, 3 don't. 8 hedged.

**Two reds are already in `tests/data/charlotin_corpus.json`** (City of Grenada v.
Harrelson; Crittendon v. State Farm), sourced from this same case — cross-validation.

## Why this corpus: it cleanly separates the two layers

It maps 1:1 onto the verifier's two-layer architecture:
- **"Does it Exist?"** ≈ the **verifier** (NOT_FOUND / WRONG_CASE / CITE_UNCONFIRMED)
- **color + Irregularity** ≈ the **assessment** (Green / Yellow / Red proposition support)

## Baseline measurement (current verifier, existence layer only) — 2026-06-11

| | result |
|---|---|
| Reds (hallucinated) clean-verified | **0 / 3** (want 0) — 2 NOT_FOUND, 1 WRONG_CASE (Crittendon → resolves to a different case). Verifier handles the fakes perfectly. |
| Real cases located (FOUND-family or CITE_UNCONFIRMED) | **44 / 51** |
| Real-case misses | 7: 2 transient INCOMPLETE (settle on rerun), 1 correct INSUFFICIENT_DATA (ABC Supply — cite is a bare docket number), 1 malformed cite (Jones — "Document 287" PACER ref), 2 WL coverage gaps (Le, Hernandez), 1 WRONG_CASE miscall (Gen. Tel.) |
| **Yellows flagged CITE_UNCONFIRMED** | **0 / 19** |

**The headline finding for the redesign.** The verifier's *existence* layer is strong:
0 false positives on the fakes, ~46/51 reals cleanly handled. But **0 of the 19 yellows
are catchable by the verifier** — because the yellow problems are *not* citation-existence
problems. They are proposition-support and quote-accuracy problems on cases that genuinely
exist and are correctly cited:
- fabricated / inaccurate quote (Donovan, Cruz, La. Power, Anderson, Young)
- proposition overstated / holding narrower (Silvercreek, Midwest, American Auto)
- wrong court (Doe v. City of Memphis — 6th not 5th Cir; Donovan — 2d not 5th)
- wrong pincite (In re OCA — n.32 not n.2; Yilport — 89-90 not 88-89)
- unsupported / wrong holding (City of Madison, N. Cypress, Stringer, Wilkens)

That is exactly the **assessment layer** — the redesign's core value, and what the
verifier provably cannot do alone. This corpus gives 19 human-labeled examples of it,
plus the failure-mode taxonomy the redesign must handle (the fold-in items: fabricated-
quote criterion, proposition scoping, TOA/pincite cross-check, court-check).

Use this as the external **RED/acceptance baseline** for the verify-brief → pipeline
redesign, alongside the 61 existing A/B ground-truth cases.
