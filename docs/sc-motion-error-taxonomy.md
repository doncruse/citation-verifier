# Taxonomy of citation errors in the Sullivan & Cromwell motion (S.D.N.Y. Bankr. 26-10769, *In re Prince Global Holdings*)

The Joint Provisional Liquidators' April 9, 2026 Emergency Motion for Provisional Relief was filed by Sullivan & Cromwell. On April 18, 2026, the Firm filed a [Schedule A correction letter](https://www.courtlistener.com/docket/...) admitting AI-assisted errors. Schedule A lists 14 corrected citations across 13 paragraphs.

Reading those corrections carefully, the errors fall into four distinct categories — only one of which is "AI fabrication" in the headline sense. A verifier that only catches that category misses the majority.

## Category 1: True fabrication (case does not exist)

The case has no real-world referent at the cited reporter, by the cited name, or anywhere CourtListener / Westlaw / Lexis can find it.

- **`In re Three Arrows Cap., Ltd., 2022 WL 17985951`** (¶¶ 27, 34) — struck through entirely in Schedule A; no Westlaw document at that number; no opinion of that name in 2022. The closest real referent is the Three Arrows recognition opinion at 647 B.R. 440 (different proposition, different date).

## Category 2: Wrong reporter for a real case

The case exists, but the cited volume/page/year points to a different (or non-existent) opinion. Often the brief author had the right case in mind and pulled the wrong cite from somewhere.

- **`In re Soundview Elite Ltd., 503 B.R. 571, 588–90`** (¶¶ 26, 33) — corrected to **543 B.R. 78** (Bankr. S.D.N.Y. 2016). 503 B.R. 571 is a real Soundview opinion from 2014, but it's the wrong one for the proposition cited.
- **`Calderon-Cardona v. Bank of N.Y. Mellon, 821 F.3d 161` (2d Cir. 2016)** (¶ 47) — 821 F.3d 161 resolves to *Walsh v. Teltech Systems* on CourtListener. The real *Calderon-Cardona v. BNY Mellon* is at **770 F.3d 651** (2d Cir. 2014). Right case, wrong volume/page/year.

## Category 3: Real document on a real docket, but mischaracterized

The cited identifier (WL number, docket entry) exists, but it is not the document the brief claims it is — e.g. cited as an affirmance when it isn't.

- **`In re BYJU's Alpha, Inc., 2024 WL 3474561 (D. Del. July 18, 2024) (aff'g 2024 WL 1455586)`** (¶¶ 27, 33) — struck through in Schedule A. There is a 2024 WL 3474561 in the BYJU's appellate posture, but it is not the affirmance the brief described.

## Category 4: Real case at the right cite, but it doesn't stand for the proposition

The cite resolves correctly — the case exists at that reporter — but the holding does not say what the brief says it says, or the parenthetical quote isn't in the opinion.

- **`In re Three Arrows Cap. Ltd., 647 B.R. 440, 451`** (¶ 34) — real recognition opinion, but the quoted parenthetical about "estate property" and "provisional relief" does not appear in the opinion.
- Multiple other ¶¶ in Schedule A correct page pincites or parenthetical quotes that don't appear at the cited page.

## Why this matters for verifier design

Most public discussion of AI hallucinations in legal briefs focuses on Category 1. The S&C motion suggests Category 1 is the *minority* — 1 out of 14 errors here. The other 13 are real cases that a verifier that returns "exists / doesn't exist" will silently pass.

A verifier earns its keep by surfacing:
- **What CourtListener actually returned for that cite** (catches Category 2 — the user sees "you cited 821 F.3d 161, but that's *Walsh v. Teltech*").
- **The case name on the matched cluster vs. the cited name** (catches Category 2 in the other direction).
- **The actual opinion text alongside the brief's parenthetical** (catches Categories 3 and 4 — needs proposition-checking, but the foundation is the right document being retrieved).

The sloppy-human-associate baseline matters too: most of these errors look identical to errors a careless reviewer has been making for fifty years. AI didn't invent them; it scaled them. So the verifier's job isn't "catch AI" — it's "catch citation errors, regardless of source," and *that* framing is what the public story should lead with.

## See also

- [`docs/retrospectives/`](retrospectives/) for per-brief verifier post-mortems.
- The S&C correction letter itself: 26-10769-mg, Doc 25 (filed April 18, 2026), ECF.
