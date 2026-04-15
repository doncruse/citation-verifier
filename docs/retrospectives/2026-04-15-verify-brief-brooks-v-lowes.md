# verify-brief: Brooks v. Lowe's Home Centers, LLC (2026-04-15)

## Brief Details
- **Document:** Memorandum in Support of Plaintiff's Omnibus Motions in Limine
- **Case:** Herbert Brooks v. Lowe's Home Centers, LLC, No. 1:24-CV-01063 (W.D. La.)
- **Filed:** February 4, 2026
- **Source PDF:** `briefs/gov.uscourts.lawd.207038.49.1.pdf`
- **Workdir:** `briefs/gov.uscourts.lawd.207038.49.1/`

## Summary
- **16 unique case citations**, **20 proposition-case claims**
- **Results:** 9 Green, 8 Yellow, 3 Red
- **Verification:** 14 VERIFIED, 2 POSSIBLE_MATCH, 1 NOT_FOUND (Menges — WL-only)
- **Quote check:** 6 VERBATIM, 3 CLOSE, 3 FABRICATED (2 Gilliam = altered quotes, 1 Tompkins = not in opinion)

## Red Flags

### 1. Tompkins v. Cyr, 202 F.3d 770, 787 (5th Cir. 2000) — MISREPRESENTED
Cited for: "Evidence of prior settlement or verdict amounts is irrelevant to liability and damages in a subsequent, unrelated accident."

The opinion is about anti-abortion protester harassment — it never discusses prior settlement amounts or their relevance to subsequent litigation. The quoted phrase "consequential fact" does not appear in the opinion. This is a complete misapplication.

### 2. Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. June 12, 2000) — NOT FOUND
WestLaw-only citation. Not in CourtListener's database. Cannot verify. The brief cites it for "a plaintiff did not have a duty to delay his surgery." This is an E.D. La. magistrate judge opinion from 2000 — likely real but outside CL's coverage.

### 3. Old Chief v. United States, 519 U.S. 172, 180 (1997) — MISAPPLIED (2nd cite, p.8)
The brief's second citation to Old Chief applies its Rule 403 "unfair prejudice" language to support excluding "inflammatory spoliation language." Old Chief never discusses spoliation — it's about prior conviction evidence under § 922(g)(1). The quoted phrases ("unfair prejudice," "undue tendency to suggest decision on an improper basis") are real and verbatim, but the proposition the brief attributes to the case is about spoliation, which Old Chief doesn't address.

Note: Old Chief's *first* citation (p.3, defining "unfair prejudice" generally under Rule 403) is Green — it accurately cites the case for what it actually says.

## Yellow Flags (Notable)

### Collins v. Wayne Corp., 621 F.2d 777, 784 (5th Cir. 1980)
Brief cites for "excluding evidence that had no bearing on the specific issues before the jury." The opinion's actual holding on relevance favored *admission* — "strict rules of relevancy are relaxed on cross-examination." The brief implies the opposite of what the case actually did.

### Gilliam v. Uni Holdings (both cites, pp.6-7)
POSSIBLE_MATCH (NY state court, 201 A.D.3d 83 vs CL's 2021 NY Slip Op 06798). Correct case confirmed by reading the opinion. Substance correct — the opinion does hold that a plaintiff's surgery is not spoliation. But the quoted language is materially altered from the actual opinion text (different phrasing about "inanimate evidence" and medical treatment decisions). The quotes read like paraphrases presented in quotation marks.

### United States v. Abel, 469 U.S. 45, 52 (1984)
Brief says "bias evidence must demonstrate actual bias affecting the witness's testimony." Abel actually allows bias to be *inferred* from circumstantial evidence (shared gang membership). The brief overstates what the case requires.

## Performance

### API calls
- CourtListener API: ~21 calls (1 batch lookup + 14 wave1 downloads + ~6 wave2 calls + 1 wave2 download)
- LLM agents: 17 (1 extraction, 10 Haiku summaries, 6 Opus assessments)

### Timing (active, excluding approval waits)
- Phase 1a (citation extraction): ~1 min
- Phase 1b (wave1 verify + download): ~2 min
- Phase 1c (propositions + wave2, concurrent): ~2 min
- Phase 1d (quote check + Haiku summaries): ~1.5 min
- Phase 2 (Opus assessments): ~1.5 min
- Phase 4 (report generation): ~1 min
- **Total: ~9 minutes**

## Observations

### What went well
- Small brief (15 pages, 16 citations) — fast end-to-end
- Wave 1 caught 14/16 citations in a single batch call
- Haiku summaries ran concurrently and caught the key issues (Tompkins NOT FOUND for the proposition, Old Chief doesn't discuss spoliation)
- The Gilliam POSSIBLE_MATCH was correctly confirmed as the right case by the assessment agent reading the full opinion
- Quote check correctly flagged 3 FABRICATED quotes, though 2 (Gilliam) were "altered quotes" not truly fabricated

### Issues
- **Tompkins Red is significant.** This is the lead citation in Section I.B of the brief — "Courts consistently and uniformly hold that evidence of prior settlement or verdict amounts is irrelevant." The cited case has nothing to do with that proposition. Worth flagging as a potential AI-generated citation.
- **Old Chief Red (2nd cite) is a softer issue.** It's a general Rule 403 case applied to a spoliation context. The underlying legal principle (Rule 403 balancing) does apply to spoliation arguments, but the brief cites Old Chief as if it specifically addressed spoliation language, which it doesn't. This is more "inapposite authority" than "fabricated citation."
- **Menges is likely real** but unverifiable via CL. WestLaw-only E.D. La. magistrate opinions from 2000 are a known CL coverage gap.

### A/B test note
This run was part of an A/B comparison with `/proposition-verifier` (run separately on the same brief). See `scratch/TODO.md` for comparison checklist.
