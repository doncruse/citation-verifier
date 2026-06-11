# "Check Cite" (CITE_UNCONFIRMED) — Tier 1 Step 3 design

**Date:** 2026-06-11
**Status:** APPROVED (user sign-off in session, 2026-06-11) — scope refined twice
during review; see §3 for the final rules and §12 for what changed and why.
**Motivating corpus:** `scratch/charlotin_fp_triage.csv` buckets B (25 opinion-search
FPs) and C (29 RECAP FPs) — Charlotin fakes with a real/common case name attached to a
fabricated reporter/WL cite. Plus the original spec in `scratch/TODO.md` Priority 1
("Citation mismatch detection") with its Drywall example (`742 F. Supp. 2d 672` cited;
case actually at `759 F. Supp. 2d 822`).
**Designs against:** `docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md`
§2.2 (status taxonomy), §2.3 (status-vs-warning rule), §2.4 (FinalIds contracts),
§2.6 (warning schema + amendment workflow).

---

## 1. The problem

When citation-lookup misses (the cite is not in CL's citation index) and the fallback
finds a case **by name** above threshold, the result today is a VERIFIED-family status —
even though nothing about the *citation as written* was ever confirmed. That is the
signature of the hybrid hallucination: a real or common case name (Taylor v. State,
Hall v. Hall, Kennedy v. Kennedy) welded to a fabricated volume/page or WL number.
65 fake FPs remain in the Charlotin baseline (67/511 found − 2 relabels); ~54 are this
class (25 opinion-search + 29 RECAP).

**The Muldrow constraint (why this is not a scoring lever).** Lever 3's
reporter-contradiction *scoring* arm was removed on 2026-06-10 after the benchmark
replay caught it producing a real false negative (Muldrow cited `144 S. Ct. 967`, CL
lists the parallel `601 U.S. 346`). Reporter mismatches must not move scores. Check
Cite is therefore a **post-threshold classification**: scoring, the 0.40 threshold, the
party-mismatch penalty, the no-corroboration cap, and the RECAP hard gates are all
untouched. A candidate first wins under today's rules; classification then decides
*what kind of win* it was.

**The governing principle (user, in review):** the tool's job is to verify that *the
case exists and says what the brief claims* — and to compensate for CL's known reporter
gap, not to nag about it. Demotion is reserved for situations where either CL
affirmatively contradicts the cite, or there is nothing (no text at all) backing the
match.

## 2. New status: `CITE_UNCONFIRMED`

UI label: **"Check Cite"**. Meaning: *a real case matching the cited name (and usually
court/date) was found, but the specific cited location could not be tied to it — and
the evidence situation is one a human must resolve.*

Per design §2.3's operational test (would removing the underlying fact change the
verdict? — yes: if the cite checked out, the status would be VERIFIED), this is a
status, not a warning. Reuse of `VERIFIED_PARTIAL` was considered and rejected: its
existing flavors are *citation-anchored* (the citation string itself resolved
authoritatively; the case/name side is in question), while this class is
*name-anchored* (a fuzzy name search found something; the citation side is in
question). Names are common; cites are unique. These are different trust classes, they
render differently ("Ready" vs "Check Cite" was the original UI spec), and consumers
key badges off status. A new status also fails loudly in every consumer's status-
coverage test until each surface consciously chooses a rendering. Precedent for adding
a status: `INSUFFICIENT_DATA` (minor-version bump + CHANGELOG + manifest sweep).

Taxonomy family: "resolved-but-questionable," alongside WRONG_CASE. Trust ordering:
VERIFIED family > CITE_UNCONFIRMED > WRONG_CASE > NOT_FOUND.

## 3. Classification rules (final)

Applies only to **fallback wins** (opinion_search / recap stages, score ≥ threshold).
Citation-lookup and caption-investigation paths are untouched — a lookup hit means the
cite itself resolved, which is the citation-anchored world (VERIFIED / VERIFIED_PARTIAL
/ WRONG_CASE as today). Citations that carry no reporter/WL cite (docket-number-only)
are untouched.

| Evidence situation | Example | Outcome |
|---|---|---|
| Cited vol/rep/page or WL number on the matched record | (rare in fallback — lookup parse failures) | VERIFIED (unchanged) |
| **Contradicted:** record lists ≥1 cite in the *same reporter family* as cited, and the cited address is not among the record's cites | Taylor v. State, 133 N.E.3d 708 → real Taylor with a different N.E.3d cite | **CITE_UNCONFIRMED** + `cite_contradicted` |
| **No same-family witness:** record's cites are all from other families, or record has no cites at all | cited So. 3d, record lists only Ala. App.; Muldrow (S. Ct. vs U.S.); WL cites; Shahid-class empty records | VERIFIED + `cite_not_on_record` warning |
| **RECAP, doc gate passed** (opinion-type document within the date window) | Oracle v. Google 2016 WL 3181206 (real); also U.S. v. Abbott (fake — accepted cost, see §3.3) | VERIFIED_VIA_RECAP + `cite_not_on_record` warning |
| **RECAP, bare docket** — no document, no text | Gibson v. Rosati, 2017 WL 1155765 | **CITE_UNCONFIRMED** + `cite_not_on_record` |

### 3.1 The same-family rule (replaces any parallel-reporter exemption table)

"Contradicted" requires a **same-family witness**: at least one citation on the record
whose reporter normalizes to the same base family as the cited reporter (series
collapse: N.E. ≡ N.E.2d ≡ N.E.3d; So. ≡ So. 2d ≡ So. 3d; P. ≡ P.2d ≡ P.3d; U.S. and
S. Ct. are *different* families). Rationale:

- Fakes overwhelmingly fabricate an address in the reporter family CL actually uses
  for that court (that's what plausible looks like), so the real same-named case's
  record carries a same-family witness that contradicts them. Catches Taylor (Ind.
  publishes *in* N.E. — official reporter), Kennedy (Neb. App.), Hummel (P.2d), most
  of bucket B.
- Real cases cited by a reporter CL didn't ingest (regional cited, official listed —
  the Alabama example) have **no** same-family witness → not contradicted → keep
  VERIFIED + warning. The reporter-gap compensation survives.
- Muldrow (SCOTUS parallels) falls out of the same rule — no S. Ct.-family cite on the
  record → not contradicted. No special SCOTUS table needed; benchmark stays 203/204
  with Muldrow still plain VERIFIED.

### 3.2 Accepted cost #1 — WL-cited fakes in bucket B mostly escape

A WL number is its own family; CL records rarely list WL cites for these cases, so a
fabricated WL number almost never has a same-family witness. ~7 of 25 bucket-B fakes
are WL-cited and will stay VERIFIED + `cite_not_on_record`. Accepted because a
fabricated and a real unpublished-opinion WL number are *indistinguishable from inside
CL*, and the verify-brief pipeline's proposition check (which reads the matched text)
is the backstop where WL fakes actually die.

### 3.3 Accepted cost #2 — date-gate VIA_RECAP fakes keep their badge

~8–10 bucket-C fakes passed the VIA_RECAP doc gate (real opinion-type document near
the fabricated cite's claimed date on a busy same-name docket — U.S. v. Abbott). They
keep VERIFIED_VIA_RECAP + warning. Accepted (user ruling, 2026-06-11): the gate's
date+doc-type match is genuine evidence the *case* exists and produced an opinion
then, text is available for the downstream proposition check, and we can never learn
the WL number is wrong — only that it's unconfirmable. Demoting all VIA_RECAP would
punish Oracle-class reals for CL's structural inability to index WL.

### 3.4 Bare-docket demotion

A recap_docket_search win with no qualifying document (today's VERIFIED_DOCKET_ONLY)
that was reached from a reporter/WL-cited citation demotes to CITE_UNCONFIRMED: the
match is name+court+date-window only, the cite is unverifiable, and there is **no
text** against which "says what it's supposed to say" can ever be evaluated — by us or
by downstream consumers. This is where ~21 of 29 bucket-C fakes live.
VERIFIED_DOCKET_ONLY remains reachable for docket-number-cited citations (there the
docket-number match *is* the citation check).

### 3.5 Expected movement (verified offline before merge)

≈18 of 25 bucket-B (same-family contradictions) + ≈21 of 29 bucket-C (bare dockets)
≈ **39 of 54 FPs demoted**; ~15 stay found-with-warning (WL-cited B + gate-passing C).
Exact counts come from the cassette replay and go in the retro.

## 4. New warning categories (§2.6 amendment; minor-version bump)

- `cite_contradicted` — same-family witness present, cited address absent.
  `details: {"cited": "133 N.E.3d 708", "record_citations": [...], "family": "ne"}`.
- `cite_not_on_record` — no same-family witness to compare.
  `details: {"cited": ..., "record_citations": [...], "reason":
  "no_citations_on_record" | "no_same_family_citation" | "recap_no_reporter_cites"}`.
  Attached to *both* the keep-VERIFIED cases (warning only) and the bare-docket
  demotion (with the status carrying the verdict).

New gate: `GateName.no_cite_unconfirmed` so fail-closed callers can block on it.

## 5. Mechanics

### 5.1 `CiteCheck` outcome from `_score_match`

`_score_match` already sees the record's `citation` field and computes
`cite_corroborated` — the search responses carry each cluster's citation list, so the
opinion-search variant needs **zero new API calls** (fully cassette-replayable). It
gains a structured outcome (module-level enum in `verifier.py`):

```
CiteCheck:  NO_CITE_IN_INPUT   # input had no reporter/WL cite — nothing to check
            CORROBORATED       # cited vol/rep/page or WL number on the record
            CONTRADICTED       # same-family witness present, cited address absent
            NOT_ON_RECORD      # no same-family witness (incl. empty list)
```

Returned alongside `(score, mismatches)` and carried on a new
`CandidateMatch.cite_check` field, set wherever candidates are built
(`_process_results`, `_process_recap_results`, `_build_docket_only_candidate`). RECAP
candidates: always `NOT_ON_RECORD` when the input carries a reporter/WL cite, else
`NO_CITE_IN_INPUT`. One shared scorer ⇒ sync/async/batch inherit identically.

Reporter-family normalization: strip punctuation/spacing, strip trailing series
digits (`2d`, `3d`, `4th`, `5th`), lowercase. `wl` is its own family.

### 5.2 Classification in `_build_fallback_result` (+ async twin)

A shared helper `_classify_cite_unconfirmed(parsed, best, status)` runs **after** the
existing status determination (threshold, court gate, VIA_RECAP doc gate unchanged) in
both `_build_fallback_result` and `_build_fallback_result_async`:

```
if input carried a reporter or WL cite (has_unverified_cite, already computed):
    if status == VERIFIED and best.cite_check == CONTRADICTED:
        → CITE_UNCONFIRMED + cite_contradicted
    elif status == VERIFIED and best.cite_check == NOT_ON_RECORD:
        → stays VERIFIED + cite_not_on_record warning
    elif status == VERIFIED_VIA_RECAP:
        → stays VERIFIED_VIA_RECAP + cite_not_on_record warning
    elif status == VERIFIED_DOCKET_ONLY:
        → CITE_UNCONFIRMED + cite_not_on_record
```

No score changes. `headline_confidence` still reads the winning stage's score.

### 5.3 FinalIds / text_source contract (§2.4 amendment)

`CITE_UNCONFIRMED` carries the IDs the winning stage found — same shape that stage
would have produced:

- opinion-search winner: `cluster_id`, `text_source: opinion_plain_text`
- bare-docket winner: `docket_id` only, `text_source: null`

Rationale: downstream consumers (brief_pipeline assessment) *want* the matched case's
text where it exists — reading the real Taylor v. State is how an agent shows the
brief's proposition isn't in it. Same logic as WRONG_CASE keeping its IDs.

## 6. Ruling on the Lever-2 false negatives (Sundown + Viken) — APPROVED

**Does Check Cite subsume them? No.** They are *sub-threshold false negatives* (0.29,
0.39); Check Cite only reclassifies *above-threshold wins*. Orthogonal.

**Ruling: refine — implement levers (a) and (b); reject (c).**

- **Lever (a) — corroboration skips the party penalty (Viken).** Today a positive
  WL/reporter/docket match on the record escapes the no-corroboration *cap* but the
  0.25× party-mismatch *penalty* still tanks the name component (Viken: 0.2947 <
  0.40). A unique citation match (the exact cited WL number on the matched record) is
  near-dispositive identity evidence; when present, caption divergence is substitution
  noise (Rule 25(d): Doe → Bradshaw), so the penalty is skipped (the party-mismatch
  *diagnostic* still fires for transparency). Implementation: compute cite/docket
  corroboration before the name component (reorder inside `_score_match`).
  **Guard:** the Charlotin replay must stay zero-new-found. If any fake resurfaces via
  this lever, narrow it to WL-number corroboration only and re-validate.
- **Lever (b) — docket-shape guard on `_DOCKET_JUNK` / `_DOCKET_NUMBER_PATTERN`
  (Sundown).** `,?\s*No\.\s+[^,()]+` currently eats ", No. 3" out of "HJSA No. 3,
  L.P." — corrupting the search query AND extracting `docket_number="3"`, which then
  feeds the Lever-3 docket-contradiction cap (a two-for-one bug). Fix both patterns to
  require docket-shaped content after "No.": contains a digit AND (≥4 chars or
  contains `-`/`:`//). "No. 3" survives in the party name; "No. 24 Civ. 5026",
  "No. 3:15-cv-1416", "No. 03 C 7956" still strip/extract.
- **Lever (c) — substitution-aware defendant matching: rejected.** (a) covers the
  Rule 25(d) shape without touching the matcher Bugs 2/3 just hardened.
- **Fixtures.** `verified-rule-25d-viken-detection` and
  `verified-sundown-energy-fallback` stay red until implementation lands, then are
  re-pinned per this ruling with `tier1_ruling` notes: Viken → expect VERIFIED (WL
  corroborated on the cluster). Sundown → VERIFIED if the Tex. cluster lists
  `622 S.W.3d 884` or has no S.W.-family witness; CITE_UNCONFIRMED only if a
  same-family witness contradicts. Final pin requires the one live acceptance run at
  the end of the session. Not laundering — the expectation changes because the
  taxonomy now has a state that describes these cases truthfully.

### 6.1 Implementation outcome (2026-06-11) — two surprises, both handled

The as-written §6 was half-right. What actually landed (see the retro for the full
account):

- **Lever (a) split + narrowed.** The mechanism in §6 (cite/docket corroboration skips
  the penalty) is **lever (a1)**, but it does NOT reach Viken — Viken's CL record is a
  RECAP-then-opinion **caption** (`Viken Detection Corp. v. Bradshaw`) with no matching
  WL/reporter cite, so there is nothing to corroborate. The real fix is **lever (a2)**,
  a *placeholder-party waiver* discovered during review: a cited `Doe`/`Roe` party
  carries no identity, so it is subtracted from the party-overlap check. Then the
  Charlotin replay tripped the zero-new-found guard twice, forcing two narrowings:
  - **(a1) → cite-only.** Dropped the docket-number arm. Docket numbers like
    `1:23-cv-84` are reused across districts and the `recap_document_search` path
    searches *by* docket number (circular), which resurfaced a fake (`Lee v. United
    States, No. 1:23-cv-84` → `MOTE v. United States`).
  - **(a2) → defendant-position only.** A placeholder *defendant* (`Viken … v. Doe`)
    is waived (distinctive plaintiff anchors); a placeholder *plaintiff*
    (`Doe v. Northrop Grumman`) is not (it would match a frequently-sued defendant
    alone — resurfaced `Doe v. Northrop Grumman` → `Barker v. Northrop Grumman`).
  - **Result:** Viken is **fixed and confirmed** (live: VERIFIED 0.58 →
    `Viken Detection Corp. v. Bradshaw`, with `cite_not_on_record`). Charlotin stays
    zero-new-found.
- **Lever (b) was necessary but not sufficient for Sundown.** It fixed the docket-junk
  parse bug (verified). But Sundown still NOT_FOUND for **two independent, out-of-scope
  causes**: (2) CL opinion search returns **0 results** for the full punctuated query
  `"Sundown Energy LP v. HJSA No. 3, L.P."` (vs 62 for `"Sundown Energy HJSA"`) — a
  query-construction gap; (3) the real cluster (4872528, Tex. 2021) has an **empty CL
  citation list** and a 14-party caption that defeats name-match scoring. Sundown's
  fixture stays **red** (expected VERIFIED, the honest ideal) per the scope guard; the
  residual is logged as a follow-up (multi-party-caption + punctuated-query
  opinion-search gap). The original Lever-2 diagnosis ("fix the parse → case enters the
  pool → resolves") was incomplete.

## 7. Consumer surface (per docs/consumer-surface-manifest.md)

| Consumer | Change |
|---|---|
| `models.py` | `Status.CITE_UNCONFIRMED`; `WarningCategory.cite_contradicted`, `.cite_not_on_record`; `GateName.no_cite_unconfirmed` |
| `verifier.py` | `CiteCheck` enum; `CandidateMatch.cite_check`; `_score_match` returns outcome + lever (a) reorder; shared `_classify_cite_unconfirmed` wired into both `_build_fallback_result` variants |
| `parser.py` | Lever (b) docket-shape guard |
| `brief_pipeline.py` | `_DOWNLOADABLE_STATUSES` += CITE_UNCONFIRMED (IDs present ⇒ download candidate text for assessment); `_STATUS_BADGE_FALLBACK` += "Check cite -- case found by name, cited location unconfirmed" |
| `__main__.py` | `_STATUS_LABELS` += `[!] CHECK CITE`; exit-code mapping treated like WRONG_CASE (currently 0; the WRONG_CASE-exits-0 question is a pre-existing gap, flagged as follow-up, out of scope) |
| `web/app.py` | passthrough via `_result_to_dict`; deep-search retry list: do NOT retry CITE_UNCONFIRMED (resolved-ish) |
| `web/static/get.html`, `index.html`, `qc.html` | `statusBadges` case → amber **"Check Cite"** badge; qc filter chip. Original TODO UI spec lands: Ready = VERIFIED-family, Check Cite = CITE_UNCONFIRMED, Review Name = VERIFIED_PARTIAL+`name_unverified` / WRONG_CASE as today |
| `tests/test_frontend_status_coverage.py` | enforces all three HTML files cover the new status |
| `tests/verify_from_csv.py` | "needs QC" set += CITE_UNCONFIRMED |
| `report_template.py` | no structural change (badge text flows from brief_pipeline) |
| `cache.py` | none (round-trips by enum value) |
| Manifest + CHANGELOG + CLAUDE.md | rows updated in the same commits; minor-version bump |

## 8. Regression-accounting policy

- **Recorder (`record_benchmark_cassette.py`):** new `check_cite` bucket in the
  counts, printed separately. For a fake corpus, `found` remains the FP headline;
  CITE_UNCONFIRMED on a fake is a **success** (the tool tells the user to check; the
  check reveals the fraud).
- **`test_benchmark_regression.py` / `test_fallback_regression.py` `_FOUND` sets:**
  add CITE_UNCONFIRMED. For *real-case* corpora "found" guards case-location; a real
  case moving VERIFIED → CITE_UNCONFIRMED would be visible in the recomputed-baseline
  diff, which is reviewed and documented in the retro. Under the final (same-family)
  rules the expected real-case movement is small: fallback reals are mostly
  no-witness (keep VERIFIED + warning) or VIA_RECAP (keep + warning); only
  bare-docket reals and any same-family-contradicted reals flip.
- **Charlotin baseline:** recompute offline (`--from-cassette`). Expected: ~39 of 54
  from `found` → `check_cite`; **zero new found** (the lever-(a) guard); the 3
  nameless VERIFIED_PARTIALs and 2 relabels (Holden/Bolin — out of scope) unchanged.
  New headline ≈ **26/511 found** (~5%, from 12.7%), with the demoted class
  human-review-flagged.
- **Live corpora:** `known_real_citations.json` entries mostly keep statuses under the
  final rules (Oracle stays VIA_RECAP + warning). Any flips re-pinned with notes.

## 9. Validation plan (session order)

1. TDD offline, in order: lever (b) parser guard → `CiteCheck` from `_score_match`
   (incl. family normalization) → lever (a) penalty skip → models additions →
   `_classify_cite_unconfirmed` (sync + async parity) → consumer sweeps
   (badges/chips/labels/CSV/recorder) with coverage tests.
2. Integration repros from the cassette: Taylor v. State (contradicted), an
   Alabama-shaped no-witness case (stays VERIFIED + warning), Gibson v. Rosati (bare
   docket → demoted), a docket-number-cited RECAP real staying VERIFIED_VIA_RECAP,
   Muldrow (no-witness → stays VERIFIED, benchmark cassette).
3. Recompute charlotin baseline offline; assert zero new found; review every status
   migration; record exact bucket counts for §3.5.
4. Benchmark (203/204) + fallback (32/32 located) replays with recomputed baselines;
   full offline suite green.
5. **Live (token machine, one consumer at a time):** (a) one `-m live_api` acceptance
   pass — re-pin Sundown/Viken per §6 and confirm no drift; (b) charlotin recorder
   resume ONLY if replay surfaces CassetteMiss (possible from lever-(b) query changes
   on "No. <digit>" names); skip if clean.
6. Docs: retro, roadmap status log, TODO closure, manifest, CHANGELOG, CLAUDE.md.

## 10. Out of scope (explicit)

- Holden (`wrong_pincite`) / Bolin (`wrong_court`) relabeled targets — future
  pin/court-check work.
- Cross-state opinion match (Graves) — Tier 1 Step 4 second half. (Graves is bucket B;
  if its Indiana record carries a same-family N.E. witness it flips to
  CITE_UNCONFIRMED as a side effect, but the state-disqualification mechanism is not
  built here.)
- WRONG_CASE exit-code gap in `__main__.py` (§7).
- Web app onto `verify_batch()` (Tier 1 Step 5).

## 11. Decisions log (sign-off record)

1. **New status `CITE_UNCONFIRMED`** — approved in session.
2. **Same-family contradiction rule** — emerged from review (user raised the
   So. 3d / Ala. App. parallel-reporter trap); replaces the draft's SCOTUS-only
   exemption table and the draft's "demote everything uncorroborated" scope.
3. **RECAP:** VIA_RECAP gate-passers keep status + warning (user: docket/date/court/
   name corroboration is what matters; WL number unknowable); bare dockets demote
   (user: "we have no way to check from the documents we have").
4. **Keep-VERIFIED + warning for no-witness opinion matches** — user's reporter-gap
   compensation principle ("verify the case exists and says what it's supposed to
   say," not the specific reporter address).
5. **Sundown/Viken: refine via levers (a)+(b)** — approved.
6. **No scoring changes** for Check Cite itself.

## 12. What changed during review (draft → final)

The draft demoted *every* uncorroborated fallback win (~54 of 54 caught, but it
flagged Shahid-class reals, Oracle-class reals, and any state case CL indexes under
only one of its parallel reporters). Review reshaped it around the user's principle:
CL-gap compensation must survive. The same-family witness rule keeps the affirmative
contradictions (where CL really knows better) and the zero-evidence bare dockets,
and converts the rest to warnings. Cost accepted and quantified: ~15 of 54 Charlotin
FPs stay found-with-warning because they are indistinguishable from reals inside CL.
