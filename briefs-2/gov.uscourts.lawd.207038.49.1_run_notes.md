# Proposition Verifier Run Notes

**Brief:** Memorandum in Support of Plaintiff's Omnibus Motions in Limine
**Case:** *Brooks v. Lowe's Home Centers, LLC*, No. 1:24-CV-01063 (W.D. La.)
**Date:** 2026-04-15
**Skill:** `/proposition-verifier` (first run)

## Input

- 15-page motions in limine brief (PDF)
- 16 unique case citations, 19 citation-proposition pairs
- Mix of federal circuit, SCOTUS, and Louisiana state cases

## Results

| Category | Count |
|----------|-------|
| Serious issues (Red) | 3 |
| Minor notes (Yellow) | 3 |
| Verified (Green) | 11 |
| Unable to verify (Gray) | 2 |

### Red findings

1. **Tompkins v. Cyr, 202 F.3d 770, 787 (5th Cir. 2000)** -- Cited for excluding prior settlement evidence, but the case is about abortion protesters/RICO. "Consequential fact" doesn't appear in the opinion. Complete subject matter mismatch.
2. **Collins v. Wayne Corp., 621 F.2d 777, 784 (5th Cir. 1980)** -- Cited alongside Tompkins for the same proposition. Actually a products liability bus crash case. Page 784 is about expert witness cross-examination.
3. **United States v. Abel, 469 U.S. 45, 52 (1984)** -- Brief says Abel requires bias evidence to "demonstrate actual bias." Abel actually holds bias evidence is *broadly* admissible. Mischaracterization that opposing counsel could exploit.

### Yellow findings

4. **Bankcard America, 203 F.3d 477, 484** -- Brief quotes "policy behind Rule 408" but opinion says "purpose of Rule 408." Substance correct, not verbatim.
5. **Michelson v. United States, 335 U.S. 469, 475-76** -- Arrest-specific discussion is later in the opinion, not at cited pages. Pinpoint off.
6. **Lasha v. Olin Corp., 625 So. 2d 1002, 1006** -- Brief quotes "The tortfeasor" but opinion says "a defendant." Trivial word swap.

### Unable to verify

- **Gilliam v. Uni Holdings, LLC, 201 A.D.3d 83 (1st Dep't 2021)** -- NY state case, not on CourtListener.
- **Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. 2000)** -- WestLaw-only, not on CourtListener.

## API Usage

- ~17 CourtListener MCP API calls (2 batch lookups, 1 search, ~14 get_opinion)
- 14 of 16 unique opinions retrieved from CourtListener
- 0 assessed from training knowledge

## Timing

| Phase | Duration |
|-------|----------|
| PDF read + batch lookups + first 3 opinions | ~5 min |
| Agent 1 (McRae, Bozeman, Bankcard) | 9.4 min |
| Agent 2 (Koch, Michelson, Abel, Maurer) | 15.7 min |
| Agent 3 (Tompkins, Collins, Condrey, Guzman) | 5.9 min |
| Report generation | ~1 min |
| **Estimated total compute** | **~31 min** |

Agents 2 and 3 ran in parallel. Wall clock was longer due to MCP tool approval waits at each step.

## Observations

- The two cases that were NOT SUPPORTED (Tompkins, Collins) were cited together in a string cite on p.3 for the same proposition. Both are real cases that exist at those citations -- they just don't say what the brief claims. This is a classic AI hallucination pattern: real citations attributed to fabricated propositions.
- The Abel mischaracterization is a different kind of error -- the case is real and relevant to bias evidence, but the brief inverts its holding. Abel supports admission of bias evidence, not exclusion.
- The 3 yellow findings are all minor quote accuracy issues (word substitutions in "verbatim" quotes). Common in legal writing but technically not verbatim.
- CourtListener coverage was good (14/16 cases). The two misses were a NY state appellate case and a WL-only E.D. La. opinion -- both expected gaps in CL's coverage.
- Biggest time sink was Agent 2 reading large SCOTUS opinions (Michelson, Abel). Targeted grep-based searching would be faster than full reads for future runs.