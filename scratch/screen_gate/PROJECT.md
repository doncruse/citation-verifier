# `screen` — document-level suspicion triage for citation-verifier

**Status:** gate experiment (branch `screen-signals-gate`, `scratch/screen_gate/`).
Not shipped. Graduates to `src/citation_verifier/` only if the corpus gate passes.
**Reasoning-of-record:** us-legal-research
`docs/research-notes/2026-07-03-suspect-brief-deterministic-tells.md` (the seed
analysis and all cross-repo decisions). This file is the CV-side project scope.
**Last worked:** 2026-07-03 (thinking done on Fable; from here mostly mechanical).

---

## 1. What this is

A **fourth, cheapest rung** below citation-verifier's existing ladder. CV today
answers citation-level questions at rising cost:

1. **exists?** — does the cite resolve to a real case (verifier)
2. **quote real?** — is the quoted language actually in the opinion (quote_matcher)
3. **proposition supported?** — does the case support what it's cited for (assessment)

`screen` is **rung 0**: a zero-cost, no-network, no-LLM pass over the *whole
document* that answers "should anyone spend rungs 1–3 on this filing, and where?"
It emits a list of deterministic **flags** (mechanical facts about the document),
not a score, not a verdict. Every flag is explainable in a sanctions-adjacent
conversation because it is a fact about the text, not a model judgment.

The unit of analysis is the **document**, which is what makes it new — the other
three rungs operate per-citation. `screen` sees things no per-cite check can:
a Table of Authorities that disagrees with the body, a case cited two ways, a
prose sentence that contradicts its own citation's court, arithmetic that doesn't
add up, a chatbot preamble left in the text.

## 2. Why it lives in citation-verifier (not us-legal-research)

Decided 2026-07-03. Full argument in the seed note §"Where it lives"; summary:

- **The dependency arrow points into CV.** Every citation-derived signal rides on
  extraction, reporter normalization, court maps, and name matching — CV
  internals. Hosting the battery elsewhere means either importing CV's guts
  across the repo seam (violates the single-seam rule) or reimplementing them
  (the mistake caught mid-session: the us-legal-research prototype's bespoke regex
  spine extracted 65 citations from the reference brief; the CV-rebased spine
  extracts 111 — same document).
- **CV was already heading here.** The Withers redesign notes already list
  court-check and TOA/pincite cross-check as fold-in items; the Charlotin corpus,
  Withers labels, and offline-cassette eval pattern are the exact measurement
  infrastructure this gate needs.
- **The consumers are wider than the plugin.** As a CV verb, `screen` is callable
  by import-memo's preflight, the CLI, a future MCP surface, the lq-ai
  projection, or a librarian with a suspect filing and no Cabinet. This session
  screened purchased PACER PDFs directly, with no research workflow involved —
  evidence for the standalone shape.
- **Identity holds.** The non-citation signals (arithmetic, metadata, style)
  aren't "citation verification," but "does this document warrant verification"
  is a question a citation verifier is entitled to answer — and the SRL finding
  (below) shows the tiers *cover for each other*, so splitting them across repos
  would split one detector.

**What stays in us-legal-research:** the consumption policy — how import-memo maps
flags to its reading/review preset recommendation, how flags render in a research
log, any future "screen this opposing brief" skill wrapper. Tier-2 docket-context
tells (below) are undecided and may end up a skill rather than a CV verb.

## 3. Signal catalog (by cost)

The six shipped-in-`scratch` signals are all Tier 0. The catalog is larger; the
gate decides which graduate.

**Tier 0 — document-internal, deterministic, zero network** (implemented):
- `court_contradiction` (s1) — prose circuit vs. citation parenthetical circuit
- `authority_drift` (s2) — one case, two materially different full cites
- `statute_grammar` (s3) — nonexistent statutory citation forms ("Cal. UCC")
- `arithmetic` (s4) — rate × period ≠ stated total
- `style_variance` (s5) — mixed citation-style error profile
- `toa_body_diff` (s6) — TOA authorities absent from body or vice versa

**Tier 0 — not yet implemented, high prior:**
- `chatbot_preamble` — leaked AI-assistant framing text ("Here is a court-ready
  section you can insert into your motion…"). Found verbatim in `braun-day`.
  Near-zero false-positive expectation; regex over a small phrase bank.
- `pdf_metadata` — Title/Author/Creator/Producer forensics. Confirmed live: the
  Reed filing's PDF Title is literally "Creates a legal pleading" (an AI tool's
  task name). The court's PACER stamp is a *uniform* iText/AOUSC modification that
  leaves the original producer chain readable, so this works on purchased RECAP
  PDFs, not just the docx import seam. Sub-case: `Creator: RICOH …` = a paper scan
  (Burnside) needing OCR before text signals apply.

**Tier 0.5 — statistical texture** (deterministic to compute, thresholds need the
control corpus; likeliest to die at the gate):
- citation-to-proposition uniformity; gerund-template parenthetical rate
- proposition repetition with reshuffled string cites

**Tier 1 — deterministic with CourtListener, no LLM** (the natural first
post-graduation expansion; CV already owns the lookups):
- parenthetical **year-match** and **court-match** vs. cluster metadata (would
  catch *Lewis v. YouTube* miscited as 197 Cal.App.4th 1387 and *Menominee* as
  9th Cir.)
- pincite-in-range; quote-grep (existing quote_matcher)
- doctrine-keyword grep as a cheap real-case-fake-proposition proxy

**Tier 2 — docket-context tells** (needs RECAP docket state; may be a skill, not a
CV verb):
- "CORRECTED"/amended refiling shortly after the original
- cite-list shrinkage between versions of one filing

## 4. Corpus (the actual gate)

Physical location today: us-legal-research
`evals/corpora/suspect-briefs/{bad,control}/` with per-batch `manifest-*.jsonl`.
**Migration decision (open):** move to `scratch/screen_gate/corpus/` here, or have
CV consume the us-legal-research path. Recommend migrating the final corpus into
CV so the gate is self-contained and offline-replayable like CV's other evals.

**Bad corpus — 11 documents, court-confirmed fabrications** (from Charlotin →
RECAP; the offending filings are rarely free, so most were user-purchased):

| Filer stratum | documents |
|---|---|
| Attorney | support-community-mph (Russo), tantaros-fox-news + surreply, withers-aberdeen, villalovos-vandepol (Gordon Rees, *defendant* side), johnson-dunn (defendant counsel), braun-day (has the chatbot preamble) |
| Pro se | reed-community-health, stafford-taffet, sherwood-botetourt, burnside-verdick (scan — OCR pending) |

**Control corpus — complete, 10 documents** (non-sanctioned filings matched on
court + document type + **filer stratum**; screened for no sanction/show-cause
history and minimum citation count): 6 attorney (cand-msj, msnd-msj, nysd-mtd-opp,
nysd-reply, caed-discovery, alnd-motion), 4 pro se (wawd-prose-resp,
ord-prose-resp, vawd-prose-compl, iasd-prose-compl).

**Provenance safety:** Charlotin rows are "court-confirmed per Charlotin, not
independently re-verified" — two known rows resolve to real clusters. Re-screen
any citation through the live verifier before treating it as a labeled fake.
`villalovos` is a useful reminder: the fabrications are in the *defendant's*
sections, not the pro se plaintiff's — filer attribution must be checked per
document, not assumed from the case caption.

## 5. Key empirical findings (drive the design)

1. **Signal firing is document-shape-dependent — the SRL vs. attorney split is
   real.** On first battery runs: the MPH *attorney* brief fired 5 signal
   families; the two short *pro se* filings (Reed 7pp, Stafford 17pp) fired
   **zero** — their fabricated cites are internally *consistent* (no TOA to diff,
   nothing long enough to drift, no court contradictions). Only Tier-1 existence
   lookup or Tier-0 metadata catches those. The long pro se filing (Sherwood
   133pp) fired drift, including on a court-confirmed fake.
2. **Consequence for the gate: controls MUST be matched on filer type,** or the
   experiment measures SRL-ness instead of AI-ness. Manifests carry `filer_type`;
   precision/recall is reported **per stratum**. This is not "separate criteria
   for SRLs" — it's one battery, stratified measurement, and honesty about which
   signals are even *defined* for a given document shape.
3. **Metadata and preamble are the pro se workhorses** — where the citation-shape
   signals go quiet, "Creates a legal pleading" and leaked chatbot framing fire
   loudest. This is why the tiers must stay in one detector.
4. **Known false-positive class:** government-litigant captions
   ("X v. Commonwealth/State/People/United States") collide on common surnames and
   can trip `authority_drift` on two genuinely different cases. Needs
   disambiguation or a documented FP carve-out; let the control corpus quantify
   it.
5. **Document type is a second stratification axis, orthogonal to filer type.**
   Building the pro se controls surfaced it: AO form **complaints** instruct filers
   "do not cite any cases," so pro se complaints structurally carry ~0 citations —
   the citation-shape signals (drift, TOA diff, court contradiction) are *undefined*
   for that whole document class, pro se or attorney. A bad pro se complaint
   (Burnside, and Sherwood as an unusually long non-form amended complaint) can only
   be matched against a control **complaint**, and on that pairing only metadata +
   preamble + arithmetic apply. Stratify the gate by (filer_type × doc_class), where
   doc_class ∈ {complaint, brief/response, motion}. Practically: complaint-class
   detection leans almost entirely on Tier-0 metadata/preamble + Tier-1 existence,
   not the citation-shape battery.

## 6. Gate methodology + ship rule

1. Run the battery over bad + control corpora.
2. Report **per-signal precision/recall, per filer stratum.**
3. **Ship rule:** a signal graduates to `src/` only if it *separates* the corpora
   within a stratum. A signal that fires on half the human control briefs is
   noise regardless of story quality — the detection analog of the plugin's
   fail-naive-baseline rule.
4. The labeled corpus becomes a permanent CV regression fixture (EVALS.md family),
   offline-replayable.

## 7. Work plan for later — with model tiering

Ordered; **model annotations are the point** given the Fable-budget lesson. Most
of what remains is mechanical or deterministic and should never touch Fable.

- **[mechanical / no model]** Finish the corpus: let control pulls complete; OCR
  the Burnside scan; migrate `corpus/` into CV; add `filer_type` to every manifest
  row. Retrieval agents run on **sonnet**.
- **[user action]** Purchase the pinned unavailable offending filings
  (us-legal-research `evals/corpora/suspect-briefs/PURCHASE-LIST.md`: 11 matters /
  ~16 docs; Virgil's four $10k-sanction briefs are the prize). Purchased docs drop
  into `bad/` and become free RECAP text for everyone.
- **[deterministic / no model]** Implement `chatbot_preamble` + `pdf_metadata`
  (Tier 0). Wire the battery to emit per-document `filer_type` + `signals_fired`.
- **[deterministic / no model]** Run the gate; compute per-stratum precision/recall;
  write the verdict (which signals graduate).
- **[small Fable/Opus run — reasoning-bearing, budget-limited]** Only two steps
  genuinely want a strong model, and both are cheap and bounded:
  (a) **adjudicate the ambiguous FP classes** (government-litigant caption
  collisions; style-variance thresholds) — judgment calls the corpus surfaces but
  can't settle mechanically;
  (b) **final graduation decision + `screen` verb API shape** (flag schema, how
  import-memo consumes it). Do these as one focused session, not an agent swarm.
- **[deterministic / no model]** Graduate survivors into
  `src/citation_verifier/screen.py` + tests + EVALS.md entry; expose the verb.
- **[later, separate]** Tier-1 CL-backed signals (year/court-match) as the first
  post-graduation expansion; Tier-2 docket tells as a possible us-legal-research
  skill.

## 8. Open decisions

1. **Corpus home** — migrate into CV (recommended) vs. consume us-legal-research
   path.
2. **Flags vs. score** — current design emits flags only; import-memo applies one
   hard rule (any Tier-0 flag → recommend review preset). Revisit only if a
   consumer wants a banded badge.
3. **Government-litigant drift FP** — disambiguate vs. documented carve-out.
4. **Tier-2 tells** — CV verb vs. plugin skill (leans skill; needs docket state).
