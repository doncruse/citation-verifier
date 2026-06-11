# Tier 1 Step 3 — "Check Cite" (CITE_UNCONFIRMED) — DONE

**Date:** 2026-06-11
**Design:** `docs/plans/2026-06-11-check-cite-design.md` (signed off in session)
**Branch:** `check-cite` (off `main` @ 5ccf8ca)
**Scope:** the last big FP class — real/common case name welded to a fabricated
reporter/WL cite (Charlotin buckets B + C, ~54 of the 65 remaining fake FPs), plus a
ruling on the June-9 Lever-2 false negatives (Sundown + Viken).

## Headline

The verifier now has a seventh status, **`CITE_UNCONFIRMED`** (UI label "Check Cite"):
a fallback name-search found a real case, but the cited location is either *contradicted*
by CL's same-reporter-family records or backed by *no text at all* (a bare docket). It is
a post-threshold **classification** — scoring, the 0.40 threshold, the party penalty, the
no-corroboration cap, and the RECAP gates are all untouched (the Muldrow lesson: reporter
mismatches must never move scores).

**Charlotin fake corpus (offline replay):**

| | pre-session | post |
|---|---|---|
| found (FPs) | 67/511 (12.7%) | **33/511 (6.5%)** |
| CITE_UNCONFIRMED (check cite) | — | **34** |
| rejected→found regressions | — | **0** |

The 34 demotions = 20 bare-docket RECAP + 14 same-family opinion-search contradictions.
The 33 still "found" all carry a `cite_not_on_record` warning (no same-family witness, or
VIA_RECAP gate-passers) — the accepted cost, and exactly the CL-reporter-gap compensation
the user asked for ("verify the case exists and says what it should, don't nag about the
specific reporter address"). Benchmark unchanged (203/204, citation-anchored). Fallback:
0 real cases lost; **Viken FN fixed** + Kalu v. IRS improved; 8 honest demotions. Full
offline suite **600 passed**.

## The design, in one paragraph

Same-family witness rule (the load-bearing idea, from user review): a cite is
*contradicted* only when CL lists a citation in the **same reporter family** (N.E.2d ≡
N.E.3d; So. ≡ So. 3d; U.S. and S. Ct. are *different* families) as the cited one, and the
cited address isn't among them. This (a) catches the fakes — they fabricate an address in
the family CL actually uses for that court, so the real same-named case carries a
contradicting witness; (b) spares real cases CL indexes under only one of their parallel
reporters (the Alabama So.3d-vs-Ala.App. case the user raised), which become
`cite_not_on_record` warnings, not demotions; (c) makes the Muldrow SCOTUS parallel fall
out for free (no S. Ct.-family witness → not contradicted → stays found). RECAP: dockets
carry no reporter cites, so a WL-cited RECAP win is unverifiable by construction — a
date-corroborated document (Oracle/Abbott) keeps VERIFIED_VIA_RECAP + warning, a bare
docket (no text to check anything) demotes.

## What the user decided (the scope narrowed twice during review)

1. **New status, not VERIFIED_PARTIAL reuse** — name-anchored ≠ citation-anchored; badge
   must change; coverage tests force every consumer to render it consciously.
2. **Same-family contradiction rule** (user raised the So.3d/Ala.App. parallel-reporter
   trap) — replaced the draft's "demote everything uncorroborated" and a SCOTUS-only
   exemption table.
3. **RECAP**: VIA_RECAP gate-passers keep status + warning (the docket/date/name
   corroboration is what matters; the WL number is unknowable); bare dockets demote
   ("no way to check from the documents we have").
4. **Keep-and-warn for no-witness opinion matches** — the reporter-gap compensation.

Accepted, quantified cost: ~15 of 54 Charlotin FPs stay found-with-warning (WL-cited
opinion matches + date-gate VIA_RECAP fakes) because they are *indistinguishable from
reals inside CL*. The verify-brief proposition check is the backstop.

## The Lever-2 FN ruling: refine, and what actually happened

Ruling: **refine via levers (a) + (b); reject (c)**. Implementation surfaced two
surprises (full detail in design §6.1):

- **Viken needed a different lever than the design named.** Lever (a1) — exact cite/docket
  match skips the party penalty — can't reach Viken (its CL record is a caption with no
  matching cite). The fix is **lever (a2)**, a placeholder-party waiver (cited `Doe`
  carries no identity). **Live-confirmed VERIFIED 0.58** → `Viken Detection Corp. v.
  Bradshaw` + `cite_not_on_record`.
- **The Charlotin replay tripped the zero-new-found guard twice**, both from over-broad
  levers — caught exactly because the design made zero-new-found a hard gate:
  - `Lee v. United States, No. 1:23-cv-84` → `MOTE v. United States` (same docket number,
    different district). **Fix:** narrow (a1) to **cite-only** — docket numbers aren't
    unique, and `recap_document_search` searches *by* docket number (circular).
  - `Doe v. Northrop Grumman` → `Barker v. Northrop Grumman`. **Fix:** narrow (a2) to
    **defendant-position placeholders only** — an anonymous *plaintiff* would match a
    frequently-sued defendant alone; an anonymous *defendant* leaves the distinctive named
    plaintiff to anchor.
- **Sundown: lever (b) necessary but not sufficient.** It fixed the docket-junk parse bug
  (`"HJSA No. 3, L.P."` keeps its name, no phantom `docket_number=3` — verified by
  parse + `tests/test_parser_docket_shape.py`). But Sundown is **still NOT_FOUND** for two
  independent, out-of-scope causes: CL opinion search returns **0** for the full punctuated
  query `"Sundown Energy LP v. HJSA No. 3, L.P."` (vs 62 for `"Sundown Energy HJSA"`), and
  the real cluster (4872528, Tex. 2021) has an **empty CL citation list** + a 14-party
  caption. The original Lever-2 diagnosis ("fix the parse → resolves") was incomplete.
  Fixture stays **red** (expected VERIFIED, the honest ideal) per the scope guard; logged
  as a follow-up.

## TDD trail (all offline, cassette-replayable)

1. Lever (b) docket-shape guard — `tests/test_parser_docket_shape.py` (RED→GREEN).
2. `CiteCheck` from `_score_match` + `_reporter_family` same-family rule —
   `tests/test_cite_check.py`.
3. Lever (a1)+(a2) — `tests/test_verifier.py::TestCorroborationSkipsPartyPenalty` +
   `TestPlaceholderPartyWaiver` (incl. the two narrowing-guard tests).
4. `CITE_UNCONFIRMED` end-to-end (sync + async parity) —
   `tests/test_check_cite_status.py`.
5. Consumer sweep with coverage tests (`test_frontend_status_coverage.py`,
   `test_models.py`).
6. Offline validation: charlotin recompute + per-citation zero-new-found diff; benchmark +
   fallback recomputed baselines reviewed; 600 passed.

## Files

- `models.py`: `Status.CITE_UNCONFIRMED`; `WarningCategory.cite_contradicted` /
  `.cite_not_on_record`; `GateName.no_cite_unconfirmed`; `CiteCheck` enum;
  `CandidateMatch.cite_check` / `record_citations` / `docket_corroborated`.
- `verifier.py`: `_reporter_family`; `CiteCheck` from `_score_match`;
  `_classify_cite_unconfirmed` (shared sync/async, wired into both `_build_fallback_result`
  variants); levers (a1) cite-only + (a2) defendant-position; `_docket_number_matches`.
- `parser.py`: `_docket_shaped` / `_strip_docket_junk` (lever b).
- Consumers: `__main__.py` label; `brief_pipeline.py` downloadable + badge fallback;
  `web/static/{get,index,qc}.html` badges + contradicted tooltip (names CL's cites) + qc
  chip; `tests/verify_from_csv.py` needs-QC; `tests/record_benchmark_cassette.py`
  check_cite bucket; benchmark/fallback `_FOUND` sets.

## Still needs a live run (token machine, one consumer at a time)

- Done in-session (targeted, 2 citations): Viken VERIFIED, Sundown NOT_FOUND — pins set.
- **Not run:** the full `-m live_api` acceptance suite (141 fixtures, ~19 min) and the
  fake/real corpora live re-record, to confirm no live-only drift from the name-matcher
  changes (a2 placeholder waiver, same-family classification). Recommend one pass before
  merging the branch to main if a longer live window is available; the offline guards
  (charlotin/benchmark/fallback replays) cover the regression surface in the meantime.

## Follow-ups logged

- **Multi-party-caption + punctuated-query opinion-search gap** (Sundown): CL search
  returns nothing for heavily-punctuated full-party queries, and 10+-party captions defeat
  name-match scoring even when returned. Name-search/query-construction work, beyond Check
  Cite. → `scratch/TODO.md` Priority 2.
- **State parallel-reporter families** (§4.3): same-family rule is conservative for state
  official/regional pairs; revisit with threshold calibration if live use shows noise.
- **WRONG_CASE / CITE_UNCONFIRMED exit-code** in `__main__.py` currently 0 (pre-existing
  WRONG_CASE gap); flagged, out of scope.
