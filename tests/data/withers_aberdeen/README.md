# Withers v. City of Aberdeen — citation-audit corpus

**Source:** `exhibit1_doc112-1.pdf` — Exhibit 1 to Doc. 112-1 in *Withers v. City of
Aberdeen*, No. 1:24-cv-00218-SA-RP (N.D. Miss., filed 12/24/2025). A party-authored,
citation-by-citation audit of the plaintiff's (apparently AI-assisted) filings,
color-coded green / yellow / red. Public PACER filing.

**Built artifacts:**
- `tests/build_withers_corpus.py` → `tests/data/withers_aberdeen_corpus.csv` (54 rows).
- `tests/measure_withers_baseline.py` → `tests/data/withers_baseline_results.csv`
  (current verifier's existence-layer prediction per row; live API).
- `tests/measure_withers_assessment.py` → `tests/data/withers_assessment_results.csv`
  (current ASSESSMENT layer's Green/Yellow/Red per row — see second baseline below;
  live API + Opus assessment agents; pipeline workdir now frozen at
  `tests/data/assessment_corpora/withers/` — see that directory's README).

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

## Assessment-layer baseline (current Phase 2 path) — 2026-06-11

Measured by `tests/measure_withers_assessment.py`: the REAL pipeline front end
(wave1+wave2 verify/download, merge, deterministic quote check on quotes
auto-extracted from the exhibit's propositions), then the established
single-claim assessment prompt (ab_test_runner criteria) run as **Opus
subagents**, one per opinion. Sample: all 19 yellows + all 3 reds + 12
hand-picked greens (34 rows; 29 agent-assessed, 5 deterministic).

| | result |
|---|---|
| **Yellows caught** (predicted Yellow or Red) | **12 / 19** (verifier alone: 0/19) — 6 exact Yellow, 6 over-shot to Red |
| Yellows missed (predicted Green) | **7**: Silvercreek (-05), Am. Auto ×2 (-09, -12), McClain (-32, hedged), Anderson (-38, qc=CLOSE), Stringer (-44), Cutrera (-49) |
| Greens (n=12) | 9 exact, 2 over-flagged to Yellow (Nix -01; Scott -26, hedged), 1 Gray (Hernandez -29, WL gap) |
| Reds (n=3) | Crittendon -43 → Red via WRONG_CASE (deterministic); Grenada -42/-54 NOT_FOUND → Gray "unable to verify" (exhibit calls them red — taxonomy gap) |
| Exact-match | 16/34 (47%) overall; 15/29 (52%) agent-assessed |

**What drove the catches:** the deterministic quote check is the single
strongest lever — 5 of the 12 catches (Midwest -04, Donovan -10, Carney -14,
Cruz -37, Young -45) carried a FABRICATED flag from quotes extracted out of
the propositions, and the prompt's "FABRICATED → at least Yellow" floor
converted them. The pure topic-mismatch yellows (Madison -41, Doe -47,
N. Cypress -48, Wilkens -06, Donovan-circuit -13) were caught by opinion
reading alone.

**What the 7 misses are made of:**
- *Mechanically catchable (~3):* Anderson -38 is qc=CLOSE but the agent kept
  Green — a "CLOSE quote inside quotation marks → Yellow floor" rule (already
  proposed in the Fletcher retro) catches it deterministically. Am. Auto
  -09/-12 hinge on the 2-word quoted term "judicial admissions" — the quote
  extractor required ≥4 words, so the checker never saw it.
- *Genuine judgment gaps (~4):* Silvercreek -05 (holding narrower than
  proposition), McClain -32 (author hedged "debatable"), Stringer -44
  (discovery-of-identity vs discovery-of-injury nuance), Cutrera -49
  ("stands for" overstatement). These are the strict-reader calls the
  redesign's prompt/calibration work has to win.
- 3 of the 7 misses are on rows the exhibit author personally hedged or
  conceded "broadly supports" — the irreducible-disagreement band.

**Scale mismatch (design input):** the exhibit's colors encode existence
(red = hallucinated), ours encode support severity (Red = not supported).
6 "yellow → Red" rows are *catches with a different severity label*, not
errors. Scoring the redesign against this corpus needs an explicit mapping:
exhibit yellow ≈ our {Yellow ∪ Red on a real case}; exhibit red ≈ our
{WRONG_CASE / NOT_FOUND / Gray}.

**Pipeline bugs surfaced by the run (design-doc inputs):**
1. `matched_name` is empty in `verification_results.csv` on the batch path
   (`resolution_path[-1].raw_response_summary` lacks `case_name`), so
   `merge_claims` opinion-file linkage silently failed for 16/29 rows; the
   measurement script works around it by token-matching the `cl_url` slug.
2. Scott v. Carpanzano (556 F. App'x 288) resolved VERIFIED@1.0 to CL's
   "Rick Scott v. Amer. Natl Trust" cluster (surname-only overlap passes the
   lenient lookup check) — though the downloaded text appears to actually be
   the Carpanzano opinion under a stale CL caption. Existence-layer FP class
   worth a follow-up.
3. Nested `claude -p` fails auth from inside a Claude Code session on this
   machine (401 even with ANTHROPIC*/CLAUDE* env stripped) — the assessment
   step had to run via Agent-tool subagents instead. Directly relevant to the
   redesign's "claude -p headless" assumption.
