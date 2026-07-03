# screen_gate — Tier-0 deterministic brief-screening signals (gate experiment)

A document-internal, no-network battery that flags a legal brief as *suspect*
using six deterministic tells. Ported from us-legal-research's suspect-brief
prototype, rebased onto citation-verifier's own citation spine
(`eyecite.get_citations` + `parser.parsed_citation_from_eyecite` +
`text_cleaner.clean_case_name`) in place of the prototype's bespoke citation
regex + party-trimming stack.

This lives under `scratch/` on purpose: it is an **experiment**, not shipped
code. The `screen` verb graduates into `src/citation_verifier/` only if the gate
below passes.

## The six signals

- **court_contradiction** (s1) — prose names circuit X, but a citation
  parenthetical within reach says circuit Y (e.g. "Ninth Circuit" prose over an
  Intel v. VIA cite marked `(Fed. Cir. 2003)`).
- **authority_drift** (s2) — one case name carries two materially different full
  citations in the same document (two print reporters, or a print cite plus a WL
  cite — the multi-pass-generation fingerprint). Short forms are excluded.
- **statute_grammar** (s3) — statutory citation forms that don't exist as
  written (e.g. "Cal. UCC", which California codified as Cal. Com. Code).
- **arithmetic** (s4) — a stated per-month rate times a stated period doesn't
  reconcile with the stated total (±1 month / ±5% tolerance).
- **style_variance** (s5) — mixed citation-style error profile: "v" without a
  period in some case names while others use "v.", plus comma-in-court-
  parenthetical WL forms like "(Cal., 2025)".
- **toa_body_diff** (s6) — authorities in the Table of Authorities that never
  appear in the body, or vice versa (squash-anchor matching defeats PDF
  intra-word splits and party-1 over-capture).

Signals s3/s4/s5 are citation-independent and ported unchanged. s1/s2/s6 use the
citation-verifier spine.

## The gate rule

These signals ship into a `screen` verb under `src/citation_verifier/` **only if
they separate a real bad-brief corpus from matched controls** — i.e. they fire
on genuinely suspect briefs and stay quiet on clean ones of comparable shape.
Firing correctly on one known-bad fixture is necessary but not sufficient; the
corpus separation is the actual promotion gate. Corpora arrive separately (see
below).

## Running

```
python signal_battery.py fixtures/support-community-mph--cand-63.md
pytest test_signal_battery.py        # offline; no network / no CourtListener
```

The fixture emits exactly: court_contradiction 1, authority_drift 1 (New England
Country Foods v. VanLaw, print + WL), statute_grammar 1 (Cal. UCC), arithmetic 1,
style_variance 4 (1 v_period_mixed + 3 comma_court_paren), toa_body_diff none.
The eyecite spine extracts materially more citations than the prototype's regex
spine (111 vs 65), so recall is not a concern.

## Provenance

- Source prototype + tests: us-legal-research
  `evals/corpora/suspect-briefs/{signal_battery,test_signal_battery}.py`
- Seed analysis: us-legal-research
  `docs/research-notes/2026-07-03-suspect-brief-deterministic-tells.md`

## Next

See **`PROJECT.md`** for the full project scope: what `screen` is (CV's rung-0
document-level triage), why it lives here, the complete signal catalog (Tiers
0–2), the stratified bad/control corpus, the SRL-vs-attorney finding, the gate
methodology, and the ordered work plan with per-step model tiering.

Immediate next steps: finish the matched-control pull, OCR the one scanned bad
brief, migrate the corpus into `corpus/{bad,control}/`, implement the two
remaining Tier-0 signals (`chatbot_preamble`, `pdf_metadata`), then run the gate
and record which signals graduate to `src/`.
