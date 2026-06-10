# Charlotin Fake-Mining — Candidate Corpus Built (547 fakes)

**Date:** 2026-06-10
**Input:** `scratch/Charlotin-hallucination_cases.csv` (manually downloaded —
the site 403s automated fetchers; 1,598 rulings worldwide, 1,115 USA)
**Builder:** `tests/build_charlotin_corpus.py` (offline, TDD —
`tests/test_build_charlotin_corpus.py`, 10 tests)
**Output:** `tests/data/charlotin_corpus.json` — **547 unique court-confirmed
fabricated citations**, each with full case name + reporter/WL cite +
provenance (source ruling, court, date, the court's finding text).

## The headline finding

The roadmap (follow-up #4) assumed mining required processing the linked
rulings ("a real sub-project"). Wrong: the CSV's `Hallucination Items` field
quotes the fabricated citation strings **verbatim** inside "Fabricated: Case
Law" findings in a large fraction of rows. Mining is mostly prose parsing.
Result: the fake corpus candidate pool grew **19 → 547+19 (29x)** in one
offline pass.

## Pipeline

1. USA rows only (CL covers US courts): 1,115 of 1,598.
2. Split `Hallucination Items` on `||` into `(category, description)`;
   keep `Fabricated: Case Law` items (1,750 items; 593 contain a cite).
3. eyecite (`AhocorasickTokenizer`) extracts `FullCaseCitation`s from each
   description; the **verbatim text span** is kept (docket numbers, pin
   cites, original parenthetical all survive for the verifier to parse).
   Two eyecite span repairs: back-extend across a quote character that
   blocks the plaintiff (`'Thornbury v. ...`), and across "United " when
   an em-dash stops the name scan at "States v.".
4. **Contrast-marker flagging** — the critical precision guard. Items often
   name BOTH the fake and the real case the court found instead
   ("...identified only an unrelated Jackson v. Lew, 242 F. Supp. 3d 850").
   Citations whose span starts after a marker (`unrelated`, `actually`,
   `corrected by/to`, `corresponds to`, ...) are flagged `real_contrast`
   and excluded — putting those REAL cases in a fake corpus would poison it.
5. Drop `incomplete_name` (case name unrecoverable) and `spans_prose`
   (eyecite name backscan swallowed surrounding prose — NY square-bracket
   cites) candidates; dedup within corpus and against
   `known_fake_citations.json`.

### Funnel (from the builder's stats)

| stage | count |
|---|---|
| extracted citation instances | 715 |
| flagged `real_contrast` | 49 |
| flagged `incomplete_name` | 55 |
| flagged `spans_prose` | 7 |
| dup within corpus | 57 |
| dup vs known_fake_citations.json | 3 |
| **corpus** | **547** |

505/547 parse with name+cite via our `parse_citation` (the rest are mostly
NY `AD3d [1st Dept 2010]` square-bracket style our parser doesn't fully
handle — kept; they're still labeled fakes).

## Pilot adjudication — 30/30 genuinely fake

Ran the first 30 candidates through CourtListener's citation-lookup (via the
CL MCP `analyze_citations`, which cross-checks case names):

- **16 NOT FOUND** in CL — consistent with pure fabrication.
- **14 resolve to a DIFFERENT case** — the real-cite-wrong-name hybrid
  (e.g. "Parris v. Pappas, 844 F.3d 172" → actually *Robert Polsky v.
  United States*; "Crittendon v. State Farm, 99 So. 3d 751" → *Watts v.
  Watts*). These are exactly the `WRONG_CASE` / Check-Cite (Tier 1 Step 3)
  pattern.
- **0 turned out to be real, correctly-cited cases** — extraction precision
  100% on the pilot.

The ~50/50 split between pure fabrications and wrong-case hybrids means this
corpus exercises both the NOT_FOUND path and the Step 3 "Check Cite"
detection — it is the natural test bed for Step 3.

## Next steps (in order)

1. **Live measurement run** (token-equipped machine):
   `python tests/record_benchmark_cassette.py --corpus-name charlotin`
   Records cassette + baseline. For a fake corpus, `found (resolved)` =
   **false positives** — that count is the headline number. Expect some
   noise: a handful of candidates may be real (Charlotin mislabels,
   ambiguous findings); inspect every resolved candidate before declaring
   it our FP.
2. Triage resolved candidates: our-bug FPs → scoring/gating fixes (same
   lever workflow as Step 2); real-case mislabels → drop from corpus with a
   note; wrong-case hybrids that score VERIFIED → Step 3 motivating cases.
3. Add an offline regression test (mirror `test_fallback_regression.py`)
   once the baseline exists: no candidate may move from rejected →
   resolved.
4. Use the 547-label set for threshold calibration (roadmap follow-up #5).
5. Unmined remainder: ~1,150 fabricated-item descriptions name a case
   without a full cite, plus all `Misrepresented`/`False Quotes` items —
   those need the linked-rulings pipeline (the original "real sub-project")
   if we ever want them.

## Notes / limitations

- Labels are Charlotin's (court-confirmed per the rulings), not ours; the
  pilot suggests high precision but the live run's resolved set must be
  hand-checked before any entry is promoted to a hard assertion.
- The corpus is biased toward citations courts *quoted verbatim* in
  sanctions rulings — likely the flagrant fakes; subtle hybrids may be
  underrepresented.
- `eyecite` here is PyPI 2.7.6 (remote container), not the local fork —
  fine for prose, but rebuild on a fork machine should be byte-identical;
  the builder is deterministic.
