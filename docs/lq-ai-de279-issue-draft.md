# DE-279 issue draft (for LegalQuants/lq-ai) — NOT FILED

> **Status:** draft for review — not filed. When approved, file with:
> `gh issue create -R legalquants/lq-ai --title "<title below>" --body-file <this section>`
> (or paste into the web "Feature Request" form — blank issues are disabled there).
>
> **Target:** `LegalQuants/lq-ai` · **Template:** `feature-request.yml` · **Labels (auto):** `enhancement`, `needs-triage`
> **Companion artifacts:** [`docs/lq-ai-comparison.md`](lq-ai-comparison.md) · [`docs/plans/2026-06-18-de279-lq-ai-case-resolver-port.md`](plans/2026-06-18-de279-lq-ai-case-resolver-port.md)

**Title:** `[Feature] DE-279: name-match verification to catch fabricated case citations`

---

## Prerequisites
- [x] I have searched existing issues and the PRD §9 deferred-enhancements list.

## Use case
DE-279 already commits to this capability — catching the "model fabricated a case"
failure mode, citing the *Mata v. Avianca* sanctions. This issue is an **offer to
implement DE-279** (an api-side first slice), plus one finding worth recording: the
gap DE-279 anticipated is now **live in shipped code**.

In practice the failure is rarely an invented reporter slot (those simply fail to
resolve) — it's a **real reporter slot under a wrong or invented case name**, e.g. a
model emits `Smith v. Jones, 576 U.S. 644 (2015)` when `576 U.S. 644` is actually
*Obergefell v. Hodges*. That should be caught; today it passes as "resolved."

## Why this can't be met today
DE-279 was written before the CourtListener lookup tool shipped (PRs
[#159](https://github.com/LegalQuants/lq-ai/pull/159)–[#161](https://github.com/LegalQuants/lq-ai/pull/161)).
Now that it has, the anticipated gap is concrete: the tool **resolves** reporter
citations but never checks the cited **name**. Confirmed in current `main` —
`verify_citations`
([`gateway/app/providers/tool/courtlistener.py`](https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/providers/tool/courtlistener.py))
and [`api/app/research/service.verify_citations`](https://github.com/LegalQuants/lq-ai/blob/main/api/app/research/service.py)
return the resolved cluster's `case_name`, but nothing compares it to the asserted name:

| Asserted in text | `/citation-lookup/` resolves | Today | Should be |
|---|---|---|---|
| `Smith v. Jones, 576 U.S. 644` | *Obergefell v. Hodges* | returned as resolved | flagged: resolves to a different case |
| `Fink v. Gomez, 239 F.3d 989` | *David M. Fink v. James H. Gomez…* | no check | verified (abbreviated, same case) |

## Proposed approach
DE-279 already scopes the module (`api/app/citation/case_resolver.py`). It sits
**api-side, layered over the existing gateway-brokered `verify_citations`** — no new
CourtListener egress (ADR 0014 preserved).

**What `verify_citations` already does:** sends the text to CourtListener, which
extracts each citation and resolves it, returning the matched cluster's *canonical*
case name (`case_name`), id, and url. Citation detection and resolution are done — this
proposal does not touch them.

**What it does *not* do — and all this adds:** it never compares the resolved name to
the name the author *asserted*. CL reports "`576 U.S. 644` is *Obergefell v. Hodges*";
it doesn't notice if the author called it "Smith v. Jones." `case_resolver` adds that
one missing comparison:

1. **Read the asserted name** — for each citation, pull the `Name v. Name` the author
   wrote next to it out of the source text (a small local read; the lookup returns the
   citations but not the surrounding names).
2. **Compare** it to the resolved `case_name` with a lenient surname-containment matcher.
   Lenient *by design*: the citation is already confirmed real, so the check only rejects
   clear fabrications while tolerating that briefs abbreviate — `Fink v. Gomez` still
   matches *David M. Fink v. James H. Gomez, Director…*.
3. **Verdict** — emit `verified` / `wrong_case` / `unresolved` / `unverifiable` (the last
   when the resolver is unavailable — it degrades, never blocks).

Worked example — `Smith v. Jones, 576 U.S. 644`: `verify_citations` resolves `576 U.S.
644` to *Obergefell v. Hodges*; the asserted "Smith v. Jones" doesn't match →
`wrong_case`. Today that same input just comes back "resolved."

Surface: `POST /api/v1/research/validate-citations` (stateless), one verdict per
citation:

```json
{"citation": "576 U.S. 644", "asserted_name": "Smith v. Jones",
 "resolution_status": "wrong_case", "matched_case_name": "Obergefell v. Hodges",
 "cluster_id": 1, "absolute_url": "..."}
```

The added code is a stdlib-only name matcher (`re` + `difflib`) — **no new dependency**.
I've scoped this against the `case_resolver.py` shape and current `main` and can move
quickly, but I'd rather align with you on the open questions below before locking an
approach.

*Provenance: the capability, goal, and module name above are DE-279's. What this
issue adds is (a) the live-code finding that the shipped tool does no name check,
(b) a concrete name-match implementation, (c) a bounded first-slice plan + an offer
to build it, and (d) the design reasoning below — the alternatives weighed and the
api-side-over-gateway choice — which is mine, drawing on lq-ai's documented
architecture (ADR 0014; the Citation Engine's thin-tool design). DE-279 itself
states only a chosen approach; it weighs no alternatives.*

## Related DE-### entry
DE-279 — [PRD §9](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener)

## Affected subsystem
Document Pipeline / Citation Engine; Backend (API)

## Alternatives considered
- **Let the chat model eyeball the name match** from the returned cluster metadata.
  Rejected: unreliable for exactly the adversarial case — the model that fabricated
  the cite is the one judging it. A deterministic check is also auditable: anyone can
  read exactly how the name was validated, whereas an in-model judgment is opaque.
- **Name-check inside `verify_citations` (gateway).** Rejected for this slice: it
  changes the tool's output contract and pulls the work into the `gateway/**`
  security-review surface. An api-side layer keeps the boundary clean and the review light.
- **Keep `citation-verifier` as an external MCP server and have lq-ai call it**
  (instead of porting the code in). Rejected: lq-ai's MCP client and chat tool-loop
  aren't wired up yet, so nothing could call it today; and an external server would
  reach CourtListener and make its name-match judgments *outside* lq-ai's gateway,
  tier-routing, and anonymization — defeating the self-hosting / data-sovereignty
  guarantee. Porting the logic in keeps everything inside the audited boundary.
- **Point lq-ai's (forthcoming) MCP client at the CourtListener MCP server, whose
  `analyze_citations` already name-checks** (it warns when the asserted name differs
  from the cluster's canonical name). Rejected for the citation *engine*: that match
  would run server-side inside a third-party MCP — a black box, counter to lq-ai's
  principle that verification logic is open and inspectable — and it depends on the
  unbuilt MCP client plus an external server each operator must allowlist and trust.
  Its existence does confirm the feature is worth having; the question is only whether
  lq-ai's own open, in-boundary engine does it natively (this proposal) or outsources
  it opaquely.
- **Port `Legal-Week-Cite-Checker` directly, as DE-279 suggests.** LWCC is a sound
  reference for the *approach* (extract → resolve → fall back to a name search), and is
  what DE-279 points at. But it's a Swift / iOS app, whereas DE-279's target is a Python
  module (`api/app/citation/case_resolver.py`) — so it isn't a line-for-line port; any
  implementation is a Python rewrite regardless. `citation-verifier` is already Python,
  covers the same flow with tuned name-matching and a regression corpus, so it's the
  more direct source for the logic — while LWCC remains a useful design reference.

## Additional context
**Deliberately scoped as a first slice.** Out of scope for this PR: the
chat-pipeline auto-run + `message_case_citations` persistence + web chip/Cypress
E2E that complete DE-279's own acceptance criteria (a natural second PR). Also beyond
DE-279, as possible later enhancements (none tracked yet): being more thorough when a
citation doesn't resolve by its exact reporter number — first looking the case up by
name, court, and date in CourtListener's opinion database, and, failing that, in the
free federal court-docket archive (RECAP). I'd open follow-ups as you prefer.

**Prior art / what I'd port.** The name-match logic, status taxonomy, and lenient
post-resolution comparison come from my own
[`rlfordon/citation-verifier`](https://github.com/rlfordon/citation-verifier) — a
mature CourtListener-based citation verifier with a regression corpus. DE-279
separately names
[`Tucuxi-Inc/Legal-Week-Cite-Checker`](https://github.com/Tucuxi-Inc/Legal-Week-Cite-Checker)
as its reference implementation; `citation-verifier` is an **independent** tool in
the same problem space (not derived from it).

**Open questions (happy to shape before opening a PR):**
1. **Start standalone, or go straight to chat integration?** This proposal builds the
   check as a standalone endpoint (`POST /research/validate-citations`) that's called on
   demand — the smallest first step. DE-279's end state is bigger: the check runs
   automatically on every AI chat response and shows inline. Is it OK to land the
   standalone engine first and wire it into the chat flow as a follow-up, or would you
   rather it go into chat from the start?
2. Does a deterministic name-match layer fit the thin-tool model, or would you
   prefer it shaped differently?
3. Verdict vocabulary — reuse the existing Citation Engine's chip states (the
   green / yellow / grey inline badges it already shows for document-quote
   citations), or a distinct set for case citations?

I'm a LegalQuants org member (read access on this repo) and happy to implement the
api-only first slice and iterate in review.

**References:** legal-research mini-PRD
([`docs/proposals/legal-research-and-mcp.md`](https://github.com/LegalQuants/lq-ai/blob/main/docs/proposals/legal-research-and-mcp.md)),
[ADR 0014](https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0014-gateway-egress-boundary-for-tool-providers.md),
[`docs/citation-engine.md` §Scope](https://github.com/LegalQuants/lq-ai/blob/main/docs/citation-engine.md),
CourtListener tool PRs [#159](https://github.com/LegalQuants/lq-ai/pull/159)–[#161](https://github.com/LegalQuants/lq-ai/pull/161),
my implementation: [`rlfordon/citation-verifier`](https://github.com/rlfordon/citation-verifier).

---

## Reviewer notes (NOT part of the issue body)

**Antipattern checklist (from /file-issue):**
- [x] Title declarative (no "?")
- [x] Examples with asserted-vs-resolved + expected (the table)
- [x] Methodology / "why today": exact code pointers
- [x] Cross-references: DE-279, mini-PRD, ADR 0014, citation-engine.md, PRs #159–161, both prior-art repos
- [x] Not a duplicate (searched open + closed issues and PRs; none implement DE-279 — PR #37 only *wrote* the spec)
- [x] Clean formatting (template sections, table, no emoji, no raw output)
- [x] Root-cause theory: gap is by-design (tool scoped to resolution; name-check deferred to DE-279)

**Two things still to confirm with you:**
1. **citation-verifier ↔ Legal-Week-Cite-Checker** — RESOLVED: stated as independent
   (not derived). LWCC is a Swift/iOS app, so an "Alternatives considered" bullet now
   explains why `citation-verifier` (Python) is the port source. Heads-up: LWCC's Xcode
   metadata shows author `kevinkeller` — very likely the lq-ai gateway reviewer "Kevin"
   — so the draft keeps every LWCC reference factual and respectful (the rejection is
   language/shape, never quality).
2. **Issue vs. lighter touch.** You're an org member but read-only on this repo, so a
   PR still goes via fork. This issue is courtesy + design-alignment before building;
   it's not strictly required, but recommended given the open design questions.
