# External Methodology Review — Notes for v2

Source: a planning doc written in another session that had no visibility into
this repo. The doc is broader than the benchmark — it covers institutional /
authorship / timeline considerations for a publication-track version of this
work — but the methodology sections raise four tensions with the current
direction in [`benchmark-roadmap.md`](benchmark-roadmap.md) and propose five
concrete additions worth considering for v2.

This doc captures only the technical content. Institutional / authorship /
timeline content goes in a separate publication-plan doc (see end).

---

## Alignment with current roadmap

The external doc and the existing roadmap agree on:

- Stratified sampling by tier of cited case (~33% SCOTUS / circuit / district)
  — already a v1.2 deferred item.
- Web-search and tool-augmented eval modes — already deferred to v1.2+.
- Hallucination tracked separately from end-to-end accuracy — already done.
- Multi-source existence oracle (CL + Justia + CAP) — already a v1.2
  deferred item under coverage-bias mitigation.
- Acceptable-alternatives recognition — partially subsumed by gold-DB.

These don't need new entries; they're listed here for completeness.

---

## Methodological tensions

These are the places where the external doc's posture conflicts with the
current direction. None are resolved here — they're flagged for v2 design
discussion.

### 1. Court agreement as a calibration signal

**External doc's position:** Human-coded ground truth is required. Court
agreement is *not* a valid validation signal because it confounds assessor
accuracy with court accuracy, and courts and LLMs likely share failure
modes (e.g. both can be misled by a parenthetical that overstates a holding).
Solo hand-checking is insufficient; the recommendation is a ~150-pair
double- or triple-coded validation set with κ or α reported.

**What the repo currently does:**
- v1.1 calibration (`benchmark/releases/v1/calibration.md`): scored Sonnet/Haiku
  against Opus on v1's 600 cells; Opus's labels were treated as ground
  truth. No human coding.
- Gold-pair self-score baseline (`gold_db/`, 117 props, 84G/11Y/22R):
  treats the parenthetical → cited-case pair as gold-truth. The 87.5%
  drift agreement number is assessor-vs-assessor on the same pairs, not
  assessor-vs-human.
- v2 push toward Sonnet@FT as default assessor (90.6% Green on gold
  pairs) is grounded in court agreement.

**Why this matters:** If the external doc is right, the v1.1 calibration
conclusion ("Sonnet/Haiku fail the bar") and the v2 Sonnet@FT direction
both rest on confounded ground truth. The 22 Reds in the gold-pair audit
include some real assessor errors and some real parenthetical-mis-attribution
bugs; we don't currently know the proportion because we have no independent
truth signal.

**Options:**
- A. Build a small (~50–150) human-coded validation set as the v2 calibration
  anchor. Cost: real human labor; needs the librarian co-author or equivalent.
- B. Acknowledge the limitation explicitly in v1's writeup and frame v1.1
  + gold-DB calibration as "agreement studies" rather than "validation."
- C. Cross-validate against a different model family (GPT-5 or Gemini) on
  a sample to triangulate. Cheaper than human coding but doesn't solve the
  shared-failure-mode concern; partial mitigation.

Initial lean: A is the right answer for v2; B is the v1 retrospective
correction; C is a useful cheap supplement. Decide with co-authors.

### 2. Self-preference bias (Opus judges Opus)

**External doc's position:** Be cautious if the same model is both assessor
and a model under test. Mitigations: different model family as assessor,
multiple assessors, or explicit acknowledgment with magnitude characterization.

**What the repo currently does:** v1 has Opus as both a model under test
and the assessor. The v1 README / roadmap notes this weakly ("the
closed-book test-time model answers from memory; the assessor reads the
actual opinion — different tasks, different inputs"). No quantification
of the bias magnitude.

**Why this matters:** Anthropic models scoring Anthropic models on a
benchmark Anthropic ships is a defensible critique. The "different tasks /
different inputs" defense has merit but doesn't fully retire it.

**Options:**
- A. Run a sample (~50 cells) with a different-family assessor (GPT-5 or
  Gemini) and report the agreement / disagreement pattern, broken down by
  whether the model under test was Opus.
- B. For v2, switch the primary assessor to a non-Anthropic model.
- C. Run v2 with two assessors and report both; treat disagreements as
  assessor-uncertainty signal, not noise.

Initial lean: A as a v1.2 follow-up, C for v2.

### 3. Cost optimization of the central measurement instrument

**External doc's position:** Don't optimize for assessor cost. Assessor
quality is the central measurement — pay for it.

**What the repo currently does:** v1.1 calibration's stated motivation was
finding a cheaper assessor to scale to N=500–1000. v2's leading direction
(Sonnet@FT) is explicitly a ~5× cost reduction.

**Why this matters:** This is a real philosophical disagreement, not a bug.
Sonnet@FT does appear to match Opus on gold-pair Green rate, but (a) that
finding is itself contaminated by tension #1 and (b) even if true, the
larger N it unlocks may not be the right way to spend the savings.

**Options:**
- A. Hold the line on Opus as primary assessor at v2; spend the budget on
  a smaller, more carefully validated dataset.
- B. Use Sonnet as primary but Opus as a re-check on a 10–20% sample,
  reporting agreement and using Opus to correct calibration drift.
- C. Run both assessors on every cell at v2; treat as a multi-assessor
  ensemble (combines with #2's option C).

Initial lean: B is the pragmatic compromise. Worth discussing with
co-authors before committing.

### 4. Pilot vs confirmatory separation

**External doc's position:** The pilot dataset is exploratory — used freely
to develop methodology. The confirmatory dataset is built against a
*pre-registered* protocol (sampling, rubric, assessor configuration, models,
metrics, hypotheses). Pre-registration is timestamped (OSF or public repo)
*before* any confirmatory work begins. The paper reports pilot findings as
methodology development and confirmatory results separately.

**What the repo currently does:** v1 is being treated as both an exploratory
methodology-development pilot *and* the published headline. v1.1 and v1.2
are iterating on v1's data. There's no pre-registration.

**Why this matters:** This is the biggest structural change the external
doc proposes. If accepted, v1 becomes "Section 3: Methodology Development"
in the eventual paper, not "Section 4: Results." v2 is built fresh against
a pre-registered protocol.

**Options:**
- A. Reframe v1 as exploratory pilot; build v2 fresh as the confirmatory
  dataset against a pre-registered methodology. Higher cost, cleaner story.
- B. Continue treating v1.x as the headline; pre-register v2 as a
  scope-expansion (circuits + SCOTUS) rather than a do-over. Lower cost,
  weaker against "you developed methodology against the data you're
  reporting on" critiques.

Initial lean: A. Pre-registration is cheap; running it the wrong way and
having a reviewer call it out is expensive. The cost is mostly the human
discipline of writing the protocol down before touching the new data, not
extra compute.

---

## Concrete additions worth lifting

These are roadmap items that aren't currently tracked. Each is buildable
without resolving the tensions above.

### Backfill protocol for retrieval failures

**What:** A pre-specified search ladder for distinguishing
tool-missed-real-case / model-got-cite-slightly-wrong / fabricated.

**Specification (from external doc):**
1. Try exact cite as returned by the model.
2. If miss: try party names + year.
3. If miss: try party names alone.
4. If miss: declare unfindable after N minutes (pick N — 5? 10?).
5. Backfiller is *blinded to the proposition* (retrieves cites, doesn't
   judge support).
6. Log every step: raw cite, automatic retrieval result, backfill steps,
   outcome.
7. Validate a 50-pair backfill sample with a second person; report agreement.
8. Report backfill rate per condition (foundation-only vs RAG-augmented).

**Why this matters:** v1's CL-miss cleanup was ad-hoc. Hallucination rate
is sensitive to the denominator — if some "hallucinations" are actually
real cases that CL missed, the rate is overstated. The external doc's
protocol gives a defensible, reproducible classification.

**Status:** Not currently tracked on the roadmap. Add to v1.2 or v2.

### Tiered rubric (5 tiers vs 3 buckets)

**What:** Replace Green/Yellow/Red with a 5-tier scale for the support
relation:
1. Direct holding supports the proposition
2. Holding supports a broader principle that entails the proposition
3. Dicta supports
4. Case mentions the issue but doesn't support
5. Case is irrelevant or contradicts

The "tier counts as correct" line is a separate, published methodological
choice (probably 1–2 = Green, 3 = Yellow, 4–5 = Red, but to be confirmed
with the librarian co-author).

**Why this matters:** The current Yellow bucket collapses tiers 2, 3, and
4 into one label. Most assessor disagreements (drift, cross-model) are
likely happening at the 2/3 and 3/4 boundaries. Tiering would make
disagreements legible and let calibration target the boundary that matters.

**Status:** Not currently tracked. v2-scope item; needs librarian co-author
involvement to land.

### Prompt sensitivity battery

**What:** Run the assessor with 3–4 prompt variants on a shared subset;
report robustness (agreement across variants).

**Why this matters:** The current drift probes (~10 per scoring run on a
single template) test temporal stability of one prompt, not robustness to
prompt-design choices. Reviewers will ask about the latter.

**Status:** Not tracked. Cheap to add; v1.2-scope.

### Jurisdictional matching policy

**What:** A pre-specified policy for whether a 9th Cir. case "supports"
a proposition cited in a 2nd Cir. opinion (and the SCOTUS / circuit /
district variants).

**Why this matters:** Lawyers care about this a lot. The current pipeline
silently treats them as equivalent. v1.2's "jurisdictional-appropriateness
axis" deferred item gestures at this but doesn't pin a policy.

**Status:** Mentioned in roadmap as deferred. Promote to "open question to
resolve during v1.2" rather than indefinitely deferred.

### Parenthetical-selection-as-feature framing

**What:** Reframe parenthetical selection bias from caveat to feature in
the writeup. Claim: the benchmark *deliberately* samples non-trivial,
contested, doctrinally meaningful propositions — the kind courts add
parentheticals for. Document the distribution.

**Why this matters:** The current README acknowledges the bias defensively.
The external doc's framing is stronger and easier to defend in review:
this isn't a sampling bug, it's the design.

**Status:** Documentation change only; no code or data work. Land alongside
the v1 README cleanup whenever that happens.

---

## Out of scope for this doc

The external planning doc also covers:

- Institutional / conflict-of-interest considerations (board role, employer
  dynamics with potential ML co-author, ED sign-off process)
- Authorship plan (first author, ML co-author, librarian co-author, RA)
- Pre-registration timestamps (OSF or public repo)
- Outreach sequence (ED → former group members → ML co-author → librarian)
- Document deliverables at each stage (institutional memo, methodology
  document v1/v2, codebook, pre-registration, paper draft)
- 20-week timeline from institutional groundwork to first submission
- Disclosure-anxiety / idea-scoop mitigations

These are publication-track items, not benchmark-engineering items. They
belong in a separate publication-plan doc — not in `benchmark-roadmap.md`,
which has a different audience.

There are real interlocks between the two docs:

- The librarian co-author conversation (Week 4 in the external timeline)
  is the gating event for the tiered rubric (concrete addition #2 above).
- The ML co-author conversation (Week 3) is the gating event for tensions
  #2 and #3 (assessor design, cost-vs-quality tradeoff).
- Pre-registration (Week 8) is the gating event for tension #4 (the v1
  pilot / v2 confirmatory split).

When the publication-plan doc lands, those interlocks should be cross-linked
from this file.

---

## Recommended next steps

1. Land this doc as a v1.2/v2 design input (no code changes implied).
2. Land a separate publication-plan doc covering the institutional /
   authorship / timeline content, with cross-links.
3. Surface tension #1 (court-agreement-as-ground-truth) on
   `benchmark-roadmap.md` as a v1.2 open question — it's the most material
   challenge to the current direction and the one most likely to be raised
   by a reviewer.
4. Defer tensions #2, #3, #4 to the ML co-author conversation. They're
   real but not blocking; they want a methodologically sophisticated
   second opinion before any commitment.
5. Add the five concrete additions to the roadmap as tracked items
   (backfill protocol, tiered rubric, prompt sensitivity battery,
   jurisdictional matching policy, parenthetical-selection framing).
