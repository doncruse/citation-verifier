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

## Live measurement run — DONE (2026-06-11)

Recorded on the token machine (cassette 81MB, 3,567 calls, committed
f142dc9). **Headline: 547 fakes → 393 rejected (72%): 210 WRONG_CASE +
183 NOT_FOUND. 122 resolved (false positives, 22%). 24 transient
INCOMPLETE (rerun the recorder to mop up — it resumes + retries), 8
INSUFFICIENT_DATA.**

Offline triage (`scratch/charlotin_fp_triage.csv`) bucketed the 122 by
winning stage; bucket A (citation-lookup, 55) was adjudicated per-entry by
reading the court findings + CL's returned cluster names + replaying the
resolution path (`scratch/charlotin_bucketA_adjudication.csv`):

| Bucket | n | What it is |
|---|---|---|
| A: lookup-resolved | 55 | 20 verifier **Bug 1**, 15 poisoned extractions, 12 corpus mislabels, 5 **Bug 3**, 3 **Bug 2** |
| B: opinion-search | 33 | the **Step 3 "Check Cite"** class — real/common case name, fabricated cite (Taylor v. State @0.9, Hall v. Hall, Kennedy v. Kennedy) |
| C: RECAP | 34 | RECAP twin of Step 3 — real docket name+court, fabricated WL cite (dockets carry no reporter cites, so Lever 3 can't contradict); a few poisoned (Curtis v. Oliver) |

### Three verifier bugs found (all reproduce offline from the cassette)

1. **Bug 1 — parser name-drop → blind VERIFIED@1.0 (20+ FPs, the #1
   mechanism).** `parse_citation` returns `case_name=None` on NY
   (`Matter of X v Y, 225 AD2d 1010`), Cal. (`Marriage of Smith, 195
   Cal. App. 4th 1007`; `Estate of Layton (1938) 29 Cal.App.2d 599`),
   paren-led, and surname-only forms. verifier.py:253 guards the
   name-mismatch check with `if parsed.case_name and case_name` — so a
   nameless parse that resolves at lookup VERIFIES at 1.0 against ANY
   cluster ("of Knapp v Knapp" → Orange Steel Erectors). Two-part fix:
   (a) parser coverage for these formats; (b) **policy** — a lookup hit
   with no comparable name must not be full VERIFIED@1.0 (design
   question: VERIFIED_PARTIAL + warning? fits v0.3 taxonomy).
2. **Bug 2 — caption_investigation generic party overlap (3).**
   `_party_overlap_ok` passes on generic tokens: "Inc. v. United States"
   ≈ Johns-Manville (shared "United States"), "State v. Nye County" ≈
   State v. Eighth Judicial District (shared "State"). The
   cl_display_name_data_bug escape hatch gets picked by fakes. One case
   (A11 Friedman, via `opinion_head_500`) may be a multi-case reporter
   page — investigate live.
3. **Bug 3 — `_names_match_citation_lookup` direct-match leniency (5).**
   Pairs like "In re SunEdison" ≈ "Wal-Mart Stores", "Kelly v. St.
   Francis" ≈ "St. Jude Medical" pass the lenient matcher. Same family
   as Bug 2 (generic/short token containment); fix together with a
   shared generic-token guard ("United States", "State", "Inc.", "Co.",
   "St.", "County", ...).

### Corpus hygiene (next rebuild)

- **Drop 15 poisoned entries** (extraction grabbed the court's named
  *real* case): unambiguous new contrast markers to add — "closest
  (possible )?match", "intended (citation was|to cite)", "citation maps
  to", "citation points to", "traced to", "falls within", "search
  retrieved", "may relate to", "nearby real citation", "the only real".
  Do NOT add bare "court found" (ambiguous: "court found the citation to
  'FAKE'" vs "court found REAL instead").
- **Drop/recategorize 12 mislabels** (real cases: Tubra, Kidd, Chambers,
  Hensley, Perez v. Zazo, Stenehjem, both ND State v. cases, Colón,
  In re D.F.; plus Holden = real case **fake pinpoint**, Bolin = real
  case **wrong court** — keep those two under new categories as future
  pin/court-check targets, not NOT_FOUND assertions).
- Bucket B/C not yet swept for poisoning (Norg v. City of Seattle in B
  is suspect); do the same finder-verb pass before promoting them.

### Revised effective numbers

After removing ~27 corpus-hygiene entries, the honest verifier FP count
is ≈ 95/520 (~18%): ~28 from Bugs 1–3 (fixable now, offline-testable)
and ~60+ from the missing Step 3 "Check Cite" (B + most of C). **Step 3
is now the single biggest lever and has a ready-made motivating corpus.**

## Fix session — DONE (2026-06-10/11 follow-up session)

All three bugs fixed (TDD, offline) + corpus hygiene executed. Corpus
**547 → 511** (509 fakes + 2 relabeled real-case targets); baseline
recomputed by cassette replay (`--from-cassette`, no API):

| | live run (pre-fix) | replay (post-fix) |
|---|---|---|
| found (FPs) | 122 | **59** (57 fakes + Holden/Bolin relabels) |
| rejected | 393 | 412 |
| INCOMPLETE | 24 | 40 (see mop-up note) |

Zero rejected→found regressions; benchmark 203/204 and fallback 32/32
held; full offline suite 527 passed.

### What landed

1. **Corpus hygiene (builder `tests/build_charlotin_corpus.py`):**
   - New contrast markers (closest match / intended to cite / citation
     maps-points to / traced to / falls within / search retrieved / may
     relate to / nearby real citation / the only real / appear-to-match /
     likely intended). Bare "court found" deliberately NOT added.
   - `_ADJUDICATED` table (keyed by normalized cite): 2 marker-proof
     poisoned drops (Lampe A2, Curtis C), 10 bucket-A mislabel drops,
     Holden→`charlotin_real_case_wrong_pincite`,
     Bolin→`charlotin_real_case_wrong_court` (future detection targets,
     not NOT_FOUND assertions).
   - **B/C sweep findings** (the "not yet swept" item above): Norg
     (intended-to-cite, caught by marker), Jones v. PNC ×2 (appear-to-
     match marker), Navient 2020 WL 1867939 (likely-intended marker),
     and explicit drops for Jones v. Jones 2019 WL 1036077 ("returns"),
     Nandigam 639 S.W.3d 651 ("There is a..."), Vargas v. Sotelo (the
     party's offered *replacement*, not a confirmed fake), Lozada 174
     DPR 650 (fabricated quote, same ruling as A5 Colón).
   - **A43 Manfer re-adjudicated**: post-fix replay showed CL resolves
     144 Cal.App.4th 925 to cluster "Manfer v. Manfer" = same case →
     mislabel, dropped (adjudication CSV updated).
2. **Bug 1 — parser (`parser.py`, `tests/test_parser_name_forms.py`):**
   "v"-without-period (NY), truncated leading "of "/paren-led repair,
   "Marriage of/Estate of" prefixes + Cal. "(year) cite" terminator in
   the non-adversarial fallback, surname-only last resort ("Waitz, 255
   Ga. 474"). Genuinely nameless forms (La. App. paren-led, "Citation
   849 F. Supp....") stay None by design.
3. **Bug 1 — policy (`verifier.py` `_process_citation_lookup_hit`,
   shared by sync/async/batch):** lookup hit with no comparable name on
   either side → **VERIFIED_PARTIAL + new `name_unverified` warning**,
   never blind VERIFIED@1.0.
4. **Bugs 2+3 — shared `_GENERIC_NAME_TOKENS` guard** consumed by
   `_party_overlap_ok` and `_names_match_citation_lookup`: generic
   tokens (United States/State/St./Inc./Co./County/medical/...) never
   establish overlap alone; a side with only generic tokens is vacuous;
   no distinctive evidence anywhere → fail. Surname matcher: all-generic
   or sub-3-char surnames → escalate to caption_investigation instead of
   blind-trust (A35 Midwest, "NY"). Generic-defendant-suffix branch same
   (A36 Co. v. United States). **A11 resolved:** not a multi-case page —
   the opinion head names the *judge* (Marcy S. Friedman) and "New York
   County"; the guard kills the "new" token, so the judge-surname hit
   dies with it. **Acronym bridge** added after the benchmark caught
   St. Louis Baptist Temple v. FDIC regressing: an all-caps cited party
   matches a caption side whose word-initials prefix-align ("fdic" ↔
   "...Federal Deposit Insurance[ Corporation, a United States ...]").

### Remaining found (59) — all expected

- 54 = Step 3 "Check Cite" class (25 opinion_search + 29 RECAP),
  untouched by design; motivating corpus for the next session.
- 3 = nameless citation-lookup hits now VERIFIED_PARTIAL +
  `name_unverified` (La. App. ×2, "Citation 849 F. Supp.") — policy-
  correct, flagged, no longer blind 1.0.
- 2 = Holden (wrong_pincite) + Bolin (wrong_court) relabeled targets.

### Needs a live run (token machine)

- **40 INCOMPLETE**: 23 pre-existing transients + 17 CassetteMiss-
  induced (parser now extracts names → new fallback/investigation calls
  not in the cassette). Run
  `python tests/record_benchmark_cassette.py --corpus-name charlotin`
  (resumes; retries transients) to mop up and confirm replay verdicts
  live.
- Live fake/real corpora (`pytest -m live_api`) should be re-run once to
  confirm no live-only drift from the name-matcher changes.

### Live mop-up — DONE (2026-06-11, token machine)

Recorder rerun resolved 36/40 INCOMPLETEs (4 transients left; cassette
now 3,779 calls): 26 → NOT_FOUND/WRONG_CASE, **10 → found**. Triage of
the 10: **9 are the Step-3 "Check Cite" class made newly *visible* by
the Bug-1 parser fixes** — names now parse (Kennedy v Kennedy AD3d, In
re Chionis, Estate of Green, In re Marriage of Mathews, US v. City of
LA, Davis v. Davis, Wing Cheung Wong, Medina, Osorio), so the fallback
search runs and a real same-name case matches the fabricated cite.
That's the honest accounting of Bug 1: it removed ~20 blind
VERIFIED@1.0s and exposed ~9 fallback FPs that belong to Step 3.

The 10th was a **new bug: NY state-RECAP leak** (Kaszovitz LLP v
Rosen, 202 AD3d 421 → matched a federal "Feder Kaszovitz" SDNY docket
at 0.57). Root cause: the `A.D.`/`N.Y.S.`/`Misc.` reporter families
were absent from `state_reporter_map.py`, so `_is_state_court_citation`
had no reporter signal (same family as the Step-4 Thompson leak). Fixed
by adding them (A.D. → nyappdiv, single-court so inference is safe;
N.Y.S./Misc. → deliberate multi-entry to gate without inferring).
Matrix rows added to `test_is_state_court_citation_classification`.

**Post-fix replay: found 66/511, zero new found.** Side effect of the
now-correct nyappdiv court inference: 6 NY entries (Kaszovitz, Kennedy,
James, Bauer, Pine, Johnson v. Stadtlander) issue court-filtered
opinion searches not in the cassette → INCOMPLETE (10 total). **One
more recorder rerun** (same resume command) settles them; expect
Kennedy/James to return as Step-3-class finds.

(Second resume run settled all 6: Kaszovitz/Bauer/Pine/Stadtlander →
NOT_FOUND, Kennedy → VERIFIED 0.825 (the predicted Step-3 find), James
→ WRONG_CASE — better than its pre-fix 0.87 FP. **Final: 67/511 found
= 65 fake FPs (12.7%) + Holden/Bolin relabels.** 4 stubborn transients
remain: Shapiro, Frey, Gonzalez/CoreCivic, Chavez — bracket/asterisk
junk in the citation strings repeatedly errors live.)

### `-m live_api` triage — DONE (2026-06-11)

Full live suite after the session's changes: **14 failures, all in the
Phase-3 acceptance corpus; the headline corpora held** (19 fakes
rejected, 14 curated reals found). Adjudication, with a worktree A/B
against pre-session code (7c0f4e0) for the persistent five — **none is
a regression from this session**:

- **Transients (2): Campbell, Hersko** — pass on a clean re-run. Cause:
  the suite ran concurrently with the charlotin recorder, and the two
  competed for the rate-limited API. Lesson: don't run two live API
  consumers at once. (Campbell now resolves at 0.9 with the exact
  pinned cluster via the new nyappdiv filter.)
- **Stale fixtures (3), updated with `tier1_ruling` notes:**
  gibbs-wright → NOT_FOUND (the Lever-1 RECAP gates delivered the
  tightening its own phase3_ruling asked for); iglesias-hialeah →
  NOT_FOUND (Step-4 state gate; restores the original benchmark
  classification); michael-b-berryhill → VIA_RECAP on docket 13436892
  (RECAP data drift, stable across three runs).
- **Real findings (2), fixtures deliberately NOT updated:**
  sundown-energy and viken-detection are REAL cases the June-9 Lever 2
  party-mismatch penalty turned into false negatives (viken is the
  Rule 25(d) fixture — the penalty is structurally blind to party
  substitution; sundown is compounded by `_DOCKET_JUNK` stripping
  ", No. 3" from the party name). Logged in `scratch/TODO.md`
  Priority 1; the acceptance suite stays red on these two until the
  accept-vs-refine decision is made.

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
