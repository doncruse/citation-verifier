# WL-to-document disambiguation: a verifier limitation

## Surfaced

Phase 3 §0.3 Darensburg fixture validation (2026-05-22). User
observation during the §0.3 Westlaw lookup:

> So that WL doc is the Aug 4 opinion. But citation-verifier has no way
> to know this.

## The shape of the limitation

A WL citation like `2009 WL 2392094 (N.D. Cal. Aug. 4, 2009)` resolves
unambiguously in Westlaw — Westlaw assigned the WL number to one
specific document, and the cited date matches that document's
publication date. But CourtListener's RECAP data is the **docket**, not
Westlaw's index. The verifier has no access to the WL→document mapping.

When the cited docket has multiple substantive documents within the
relevant time window:

- **Darensburg** (cite `2009 WL 2392094 (N.D. Cal. Aug. 4, 2009)`):
  - Docket #4182878 has doc #452 (July 7, 2009 "OPINION ON DEFENDANT'S
    MOTION FOR ATTORNEYS' FEES", 10 pp) and doc #460 (Aug 4, 2009
    "ORDER GRANTING PLAINTIFFS' MOTION FOR REVIEW OF CLERK'S TAXATION
    OF COSTS", 7 pp).
  - The WL number maps to the Aug 4 order (per Westlaw lookup), but
    the verifier sees only the docket and date.
  - Under Phase 3 strict VIA_RECAP gating: doc #460 fails the
    opinion-typed test (procedural ORDER keywords); doc #452 is outside
    the ±14 day window from cited Aug 4 (28-day delta). Result:
    VERIFIED_DOCKET_ONLY.
  - This is *correct under the strict gate* but undersells what the
    verifier could in principle confirm if it had Westlaw access.

## Why we can't fix this with current data sources

CourtListener does not ingest the Westlaw WL→document index. PACER
filings don't carry the assigned WL number. To know which docket
document earned a given WL number, the verifier would need either:

1. Westlaw API access (paid, restricted).
2. A community-curated WL→docket-entry mapping (doesn't exist).
3. To download every candidate document and match the first-page text
   against the WL record's metadata (impractical and still requires
   the WL record to compare against).

So under the design v2 model, the verifier accepts the limitation and
classifies these cases as DOCKET_ONLY. The warning surface (per design
v2 §2.6) can flag this — but Phase 3 doesn't add a dedicated
`wl_ambiguous` WarningCategory; the existing
`silent_partial_verification` semantically overlaps when the docket
has multiple candidate docs and the verifier can't pin one.

## Implications

- **Fixture**: `verified-docket-only-darensburg-wl-disambiguation` pins
  this behavior so regressions don't accidentally relax the gate.

- **For future planning**: if Phase 4 or later adds a "docket has
  multiple opinion-typed docs near cited date" detector, that's the
  hook for surfacing this limitation to consumers — e.g. a new
  `recap_multiple_candidate_docs` warning naming all viable candidates.
  Captured in `scratch/ROADMAP.md` if added.

- **For verify-brief / consumers**: a DOCKET_ONLY result on a WL cite
  with date-matched-but-procedural docket entries should be read as
  "the case exists, but the verifier can't confirm the cited document
  specifically — Westlaw is the tiebreaker." Don't escalate to
  WRONG_CASE on this signal alone.

## Cross-references

- Plan: `docs/plans/2026-05-22-citation-verifier-refactor-phase-3-plan.md`
  §0.3 (Q1 Darensburg fixture validation pass).
- Survey: `tests/data/refactor_corpus_survey.md` §4 Menges entry,
  second substitution-result block.
- Fixture: `tests/data/refactor_corpus.json` — see
  `verified-docket-only-darensburg-wl-disambiguation` and
  `named-exemplar-mehar-holdings`.
