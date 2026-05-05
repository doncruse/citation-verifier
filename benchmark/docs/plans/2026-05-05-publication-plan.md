# Publication Plan — Legal Research Benchmark Paper

Living doc. Captures the publication-track content from the 2026-05-05
external planning session: institutional / conflicts / authorship /
timeline / outreach / document deliverables. Open tensions surfaced
during review are integrated inline rather than sectioned off.

Different audience from [`benchmark-roadmap.md`](benchmark-roadmap.md)
(engineering) and [`2026-05-05-external-methodology-review.md`](2026-05-05-external-methodology-review.md)
(methodology). Cross-links at the end.

`[Org]` placeholder used throughout — the data provider where the user
holds a board role and a potential ML co-author is employed.

---

## Project framing for publication

A benchmark for evaluating legal research AI on the task of finding
cases that support a given proposition. Source data: parentheticals
mined from recent legal opinions, yielding (proposition, case) pairs.
Models under test attempt to find a supporting case for each proposition;
an assessor (validated against human coders) judges whether the returned
case actually supports the proposition.

Under this framing:

- **v1** (the existing 130-pair dataset, plus v1.1 calibration and v1.2
  gold-DB hardening) is the **exploratory pilot**. Used freely to develop
  methodology. Reported in the paper as Section 3 (Methodology Development)
  with appendix.
- **v2** is the **pre-registered confirmatory dataset**. Built fresh
  against a methodology pinned before construction begins. Reported as
  Section 4 (Results).

**Open question — v1 infrastructure status under this framing:** what
explicitly transfers to v2 and what doesn't? Default working position:
- gold-DB transfers as cumulative corpus (grows across versions)
- verifier code transfers as infrastructure (`citation-verifier`
  improvements are version-independent)
- v1's mining pipeline transfers as infrastructure with two mining-side
  bugfixes: (a) eyecite parenthetical mis-attribution in chained
  citations, (b) intra-opinion deduplication (already a v1.2 deferred
  item in `benchmark-roadmap.md`). v2 scope expansion (circuits + SCOTUS)
  is additive plumbing, not a non-transfer. The 20K truncation lives in
  score-side code (`pilot_a/score.py:fetch_opinion_text` plus an
  `OPINION_WINDOW = 20_000` constant in `tests/benchmark_v1/score.py`)
  and is tracked separately under assessor configuration, not mining;
  `build_dataset.py` has its own non-truncating fetcher.
- v1's assessor configuration does *not* transfer until tensions in
  [methodology review](2026-05-05-external-methodology-review.md)
  are resolved (court-agreement-as-ground-truth, self-preference,
  cost-vs-quality, plus the score-side 20K truncation)

This list should be confirmed with co-authors. The risk of leaving it
implicit is that "v1 is exploratory" gets read as "v1 is disposable,"
which would devalue real infrastructure work.

---

## Conflicts of interest

### The three conflicts

1. Board member of the data provider [Org]
2. Potential ML co-author is an [Org] employee
3. The benchmark uses [Org]'s corpus and tools

### Handling principles

- Disclose everything in the paper (Conflicts of Interest section).
- Get formal ED sign-off and follow [Org]'s conflict-of-interest policy.
  Document conversations in writing.
- If [Org] makes any AI legal research tool that would be a natural
  benchmark target, **exclude it** and document why. The benchmark
  cannot evaluate a product made by the co-author's employer.
- If [Org] only provides infrastructure (corpus, retrieval, citation
  parsing), the role is analogous to using Hugging Face or AWS —
  disclosable but manageable.
- Pre-registration is the strongest defense against "methodology was
  tilted toward the institution" critiques.
- Consider non-affiliated independent verification of a sample of the
  data pipeline.
- Don't write the paper to promote [Org]. The corpus is means, not
  subject. A reader should not come away thinking the paper is an
  advertisement.

### The cleanest test

> Would the methodology and write-up be exactly the same if the data
> came from a public source or competitor? If yes, fine. If no,
> something needs to change.

Apply this rigorously at every methodology decision and every paper
section.

### Appropriate vs inappropriate institutional benefit

- ✅ "Showing we are infrastructure" via natural attribution — clean
- ✅ Exposing coverage gaps in the legal data ecosystem (frame as
  ecosystem-wide, not [Org]-specific) — clean and aligned with mission
- ❌ Comparison paper of [Org] vs. competitors with [Org]-affiliated
  authors — too many stacked conflicts; don't do this from inside [Org]

### Open tension — the foreclosed comparative result

Excluding [Org]'s tool from benchmark targets is the right call but
forecloses the most interesting comparative result (head-to-head among
the major legal RAG products). The external doc's alternative — "publish
the benchmark and methodology, let independent researchers run
comparisons" — is correct in principle but disappears in practice
unless operationalized.

Recommendation: identify a 2–3 person list of plausible independent
researchers (Stanford RegLab, university law-and-technology programs,
ML academics with legal-NLP interest) who could run the comparison
post-publication. Don't recruit them during the project — that re-creates
the conflict — but be ready to point at named candidates when reviewers
ask. Alternatively, plan a public call ("we publish the methodology
and dataset; we invite independent comparison runs") in the paper's
discussion section.

### Board membership specifics

- Fine if using publicly available [Org] infrastructure that any
  researcher could access.
- More fraught if using board role to obtain special access,
  customization, or staff time.
- If concerns arise, temporary board recusal is an option (overkill for
  the cleaner version, but exists).

### ML co-author employment dynamic

Clarify early: is this academic side-project work, or [Org]-supported
work?

- **Academic side-project:** standard dual affiliation in the paper,
  statement that work was conducted as academic research.
- **[Org]-supported:** [Org] effectively becomes a project sponsor;
  needs explicit institutional sign-off, different disclosure language.

This needs to be answered before the Week 3 ML co-author conversation
goes deep, because the ED conversation in Week 2 should already reflect
which framing applies.

---

## Authorship

### Working assumption

- **First author:** You (project lead, originator, primary executor)
- **Co-author:** ML researcher (methodology, evaluation design, statistical
  analysis)
- **Co-author:** Librarian (rubric, validation coding, legal substantive
  expertise) — leaning toward the unemployed librarian who wasn't in the
  original group
- **Possible co-author:** RA, depending on actual contribution by project end

### Open tension — first authorship as a conversation, not an assertion

ML methodology papers sometimes give first authorship to the methodology
designer rather than the project lead. The "first author = you" assumption
is defensible (ideation + leadership + execution + writing) but should be
opened explicitly with the ML co-author in Week 3, not presented as
decided. Possible outcomes:

- ML co-author agrees: have it on the record.
- ML co-author proposes co-first: legitimate request; decide based on
  actual contribution distribution.
- ML co-author proposes lead authorship: information about how she sees
  the project; renegotiate or reconsider the partnership.

Asserting it without conversation is the path that creates resentment
late in the project.

### Authorship memo, not just email

The external doc said "in writing (email is enough)." Recommend stronger:
a one-page memo agreed-to (signed or explicit-reply-assent) by all parties
before substantive work begins. Memo covers:

- Author order
- Definitions of each author's contribution scope
- Conditions for re-discussion (e.g., scope change, contribution
  asymmetry)
- What triggers an author addition (RA contribution threshold; named
  third co-author criteria)
- What triggers an author removal (non-delivery)

Email threads scatter and get lost. A memo is the artifact you point at
if things go sideways.

### Principles

- Co-authors are people who make substantive intellectual contributions
  to the published work. Not adjacency, not idea-proximity.
- Credit isn't a major personal motivation, but first authorship should
  still be claimed because you're leading. Don't undersell.
- Have authorship conversations before substantive work begins.
- For the RA: be explicit from day one that the role is research
  assistant with paid hours, but co-authorship is on the table if
  contribution warrants by end. Don't promise either way now.

### Why the unemployed librarian over original-group members

- Has time and motivation that working colleagues won't
- Existing working relationship and shared future projects (lower
  coordination cost)
- No baggage from prior failed effort
- Asymmetric career value (low cost to you, real value to her)

### Open tension — "unemployed" is a brittle attribute

The external doc names the risk ("if she takes a job mid-project, plan
for it") but doesn't specify the fallback. Recommendation: pin the
contingency before the Week 4 conversation, because it affects how the
codebook is structured.

Three options for the fallback:
- A. Continue solo with rubric work; degrade scope of validation coding.
- B. Bring in a former-group member after all (with all the attendant
  awkwardness).
- C. Pivot the librarian role to consultative — she stays as advisor,
  validation coding is done by RA + you with her review.

The fallback choice affects:
- Codebook structure (more docs + more async-friendly = more
  handoff-resilient)
- Coding interface (multi-coder UX vs solo workflow)
- Whether the librarian is positioned as primary rubric author (option A
  fragile) or co-author with shared documentation (options B and C more
  robust)

Bias toward C as the default fallback: it preserves the relationship
asymmetry the original analysis got right (low cost to you, real value
to her) while degrading gracefully if she gets a job.

### Why not the original group

- Prior project failed because of lack of driver, lack of NLP expertise,
  and infeasibly labor-intensive proposed scope. All three are now
  solved with a different team and scope.
- This is a different project, on a different idea (yours), not a
  continuation.
- A short heads-up to former group members is courteous but no
  authorship is owed.

### What you owe the prior group

A brief, individual heads-up before they hear it through the grapevine.
Suggested framing: "I've been working on a narrower benchmark idea that
came out of our discussions about how hard the dataset problem is. Going
to try to push it to publication with [ML researcher] and [librarian].
Wanted you to hear it from me. Happy to share the methodology when it's
further along." Low-key, individual, not a group announcement.

---

## Timeline

### Headline target

5–6 months from this week to first submission. The external doc explicitly
says "don't compress further; corner-cutting will show up in peer review."

### Open tension — engineer-gated work can run in parallel with calendar-bound work

The external doc's week-by-week reads as serial: institutional → ML
co-author → librarian → codebook → confirmatory dataset → analysis. But
weeks 1–4 are mostly other-people's-schedules (ED, ML, librarian). The
engineering-gated portion of the plan — what *you* are building, code-side
— is ~8 weeks of work, not 5–6 months.

A lot of v2 engineering doesn't depend on any co-author conversation:

- **Mining-pipeline overhaul.** v1's eyecite parenthetical mis-attribution
  bug and the 20K truncation bug both need fixing before v2 mining starts.
  (See `docs/retrospectives/2026-05-04-*.md`.) These are pure engineering.
- **Human-coding interface.** Whatever UI / spreadsheet / annotation tool
  the librarian and second coder use can be built in advance, parameterized
  to whatever rubric the codebook produces.
- **Backfill protocol scaffolding.** The search ladder, logging schema,
  and second-coder review tooling for the backfill protocol (see
  methodology review, concrete addition #1) are pure engineering.
- **Parenthetical distribution analysis.** Quantify what the pilot pool
  actually contains (proposition types, jurisdictional distribution,
  parenthetical structure variation) to ground the "deliberate-non-trivial-
  sampling" framing. RA work in the external doc, but you can do or
  supervise it now.
- **Mining at scale.** Building a few-thousand-parenthetical pool that
  v2 can sample from. The sampling protocol is pre-registered later, but
  the pool itself can exist now.

### Parallel-track timeline

| Weeks | Calendar-bound (other people) | Engineer-bound (you, in parallel) |
|---|---|---|
| 1 | ED memo + meeting request; former-group heads-up | Public timestamp (GitHub README + OSF entry); start mining-pipeline overhaul |
| 2 | ED meeting; methodology document v1 drafting | Mining overhaul; backfill scaffolding |
| 3 | ML co-author conversation | Coding interface; parenthetical distribution analysis |
| 4 | Librarian conversation; rubric v0 draft | Mining at scale (pool for v2 sampling) |
| 5–7 | Codebook development with librarian; assessor validation against human-coded labels | Assessor validation infrastructure; cross-family assessor pilot (see methodology review tension #2) |
| 8 | Pre-registration finalized and timestamped | (gate: confirmatory work blocked until pre-reg lands) |
| 9–10 | — | Confirmatory dataset construction (per pre-reg sampling) |
| 11–12 | — | Run all model conditions; backfill where needed |
| 12–13 | Human validation on confirmatory subset | Validation infrastructure |
| 13–16 | Analysis and writing | Same |
| 17–20 | Internal review; pre-submission feedback; submit | Same |

The external doc's week numbering and milestone dates are preserved;
only the parallelism is added. Calendar gating still applies — pre-reg
in Week 8 still gates confirmatory work, regardless of how much
engineering is ready by then.

---

## Pre-registration

### Coverage

- Sampling protocol (specific stratification proportions: ~30% SCOTUS /
  ~30% circuit / ~40% district, adjusted for what mining shows is
  feasible)
- Rubric (final from codebook work; tier definitions and the
  "tier-counts-as-correct" line)
- Assessor configuration (final, validated against human-coded labels)
- Models under test (foundation, foundation+web, dedicated legal RAG)
- Metrics (per-stage decomposition + headline)
- Hypotheses
- Sample size justification
- Analysis plan (what's primary, what's exploratory)

### Timestamping

OSF entry, public GitHub release with tag, or both. Before any confirmatory
work begins. Week 8 in the timeline.

### Reframing — pre-registration is primarily epistemic, not defensive

The external doc framed pre-registration as "the strongest defense
against 'methodology was tilted' critiques." That's true but undersells
it. The bigger benefit is that pre-registration is what stops *you* from
quietly tuning the rubric, sampling, or analysis after seeing v2 results.

Without pre-reg, the path-of-least-resistance after v2 runs is to nudge
methodology choices in the direction that makes the results look cleaner
— even with the best intentions. Pre-reg removes that degree of freedom.
The defensive-against-reviewers framing makes pre-reg feel like a tax;
the epistemic framing makes it the actual measurement instrument.

In practice: write the pre-registration document like you're writing
yourself a contract. The audience is future-you-running-the-results, not
future-reviewers.

---

## Cost vs quality (assessor) — explicit posture

Cross-link: tension #3 in [methodology review](2026-05-05-external-methodology-review.md).

The methodology-review doc raises this as a tension between the external
doc's "don't optimize for assessor cost" and the repo's recent push toward
Sonnet@FT for ~5× cost reduction. The publication-side implication:

- "Don't optimize for cost" + "don't compress timeline" jointly cap v2
  near v1's N (within Opus's budget envelope).
- That closes the N=500–1000 prize from cheaper-assessor calibration.
- Therefore v2's headline contribution is *methodology improvement*
  (rubric tiers, backfill protocol, human validation, pre-registration),
  not statistical power.

Recommended explicit posture in the paper: embrace this. v2 is *not* the
larger version of v1 — it is the *correctly designed* version of v1. The
methodology improvements are the contribution; N stays similar.

This needs to be a co-author conversation in Week 3, because the ML
co-author may have strong views on whether the methodology contribution
is publishable as headline (it depends on venue norms — NeurIPS Datasets
& Benchmarks may welcome it; ICAIL might want both).

---

## Idea-disclosure / scoop risk

### Background

Mentioned the project to:
- A stalled-project peer (former group member with related interests).
- A startup founder building in adjacent space.

### Risk assessment

- Stalled-project person has labor problems that copying the idea
  doesn't solve.
- Founders build products, not papers; even if they use parenthetical
  eval internally, that doesn't scoop a published benchmark.

### Open tension — startup-founder prior art is mild but real

The external doc's "most likely outcome: nothing happens" is broadly
right but slightly sanguine on the startup founder. He won't write a
paper, but could:
- Ship a product feature that uses parenthetical eval, with a public
  blog post describing the methodology
- Publish a blog post directly on the methodology as marketing content

Either establishes prior art that complicates the user's claim of
methodological novelty. Mitigation: prioritize the public timestamp in
**Week 1**, not "soon." A dated GitHub README + OSF entry establishes
priority cheaply.

### Protective steps

- ✅ **Week 1, Day 1:** public timestamp (GitHub README + OSF entry)
- Tell co-authors about the situation when bringing them on.
- Move at a reasonable pace (5–6 month timeline, not 12).
- Be more guarded going forward about specific methodology details, but
  don't stop talking about the project. The general idea is out;
  execution details don't have to be.
- Don't try to un-tell anyone or ask them not to use it. Counterproductive.
- The startup founder is a potential future industry collaborator if you
  want one — not now, but possibly after pilot results.

---

## Major risks and mitigations

| Risk | Mitigation |
|---|---|
| ED or board blocks project | Go to ED first, with thoughtful memo; address concerns before they become blockers. If blocked despite good-faith effort, redesign without [Org] data or step away. |
| ML co-author declines | Have a backup in mind. Pivot in Week 3 is much cheaper than pivot in Week 8. |
| Librarian co-author availability collapses mid-project | Pre-pinned fallback (option C: pivot to consultative role; RA + you absorb validation coding with her review). Decide before Week 4. |
| First-author dispute with co-author | Authorship memo before substantive work begins. Open the conversation, don't assert. |
| Assessor doesn't reach acceptable agreement with humans | Try multiple models; iterate prompt; refine rubric; in worst case narrow scope to higher-confidence judgments only and document the limitation. |
| Retrieval pipeline fails worse than expected on foundation-model condition | This may itself be a finding (foundation models hallucinate at rate X). Track it carefully via decomposed metrics. |
| Coverage gaps in [Org] data create unfindable cases | Document; potentially backfill manually with other sources; transparent reporting. Multi-source existence oracle deferred to v1.2+ but on roadmap. |
| Reviewer attacks on conflicts | Pre-registration timestamp + complete disclosure + exclusion of [Org] products from benchmark + non-affiliated verification = defensible. |
| Idea gets scooped | Public timestamp in Week 1 (not "soon"); move at reasonable pace; don't slow down for refinement that isn't needed. |
| RA's coding turns out unreliable on some categories | Triple coding (you + librarian + RA) provides redundancy; can recode problem categories if needed. |
| Self-preference bias if Claude assesses Claude | See methodology review tension #2. Different model family as cross-check; multiple assessors; or explicit acknowledgment with magnitude characterization. |
| Independent comparison of [Org] vs competitors never materializes | Named-list of plausible independent researchers identified; public call in paper's discussion section. |
| Authorship dispute with prior group | Individual heads-up communications in Week 1; clear narrative that this is a different project on a different idea. |

---

## Outreach sequence

| When | Who | What you bring | What you're asking for |
|---|---|---|---|
| Week 1, Day 2-3 | Executive Director | 1-2 page institutional memo | Meeting; guidance on conflicts process; eventual sign-off |
| Week 1, Days 3-5 | Former group members (individually) | Brief verbal/email update | Awareness, not approval — courtesy heads-up |
| Week 2 | Executive Director (follow-up) | Meeting in person | Formal sign-off; documentation of agreement; decision on board disclosure path |
| Week 2 (if directed by ED) | Board (or board chair) | Short item per ED guidance | Disclosure per conflicts policy |
| Week 3 | ML co-author | 5-10 page methodology document + authorship memo draft | Co-authorship commitment; first-authorship conversation |
| Week 4 | Librarian co-author | Methodology document + initial rubric draft + authorship memo draft | Co-authorship commitment; codebook timeline confirmation |
| Week 4 | RA (already started) | Codebook/coding plan | Clarification of role and authorship-on-merit policy |
| Week 5+ | Senior advisor / pre-submission reader (identify now, engage later) | — | Future review of draft paper |

---

## Document deliverables

### Week 1: Institutional Memo (1-2 pages, for ED)

**Audience:** ED evaluating institutional risk and benefit — NOT
methodology.

Sections:
- Project summary (one paragraph): what the benchmark is at high level
- Why [Org]'s data and tools are the right fit (one paragraph)
- Institutional dynamics: board role, potential ML co-author employment,
  any data access needs
- Conflict-handling plan: disclosure, exclusion of [Org] tools as
  benchmark targets if applicable, pre-registration, no head-to-head
  provider comparisons in this paper
- What you're asking for: formal sign-off, guidance on conflicts process,
  board disclosure path
- Honest paragraph on potential institutional benefits: visibility as
  infrastructure, useful coverage findings, research contribution to the
  field — framed as natural byproducts, not motivations

**What to leave out:** rubric details, assessor design, statistical
analysis, sample size calculations. The ED doesn't need these; including
them risks framing the conversation as a research review.

### Week 2: Methodology Document v1 (5-10 pages, for ML co-author)

**Audience:** Methodologically sophisticated researcher evaluating whether
to invest in the project.

Sections:
- Research questions and motivation
- Why parenthetical mining (vs. synthetic data, vs. existing benchmarks)
- Task framing (research task, not retrieval task) and implications
- Model conditions (foundation, foundation+web, dedicated legal RAG)
- Assessor methodology (sketch — with human validation as central concern)
- Sampling and stratification plan
- Metrics (decomposed by stage)
- Pre-registration approach
- Conflicts disclosure (yes, even in the internal doc — sets norms early)
- Open questions and design decisions still to make
- Initial pilot results (v1) and what was learned

**What to leave out:** detailed rubric (collaborative with librarian);
specific prompt language (will iterate); final stratification proportions.

### Week 4: Methodology Document v2 + Initial Rubric Draft (for librarian)

Same as v1 with ML co-author feedback incorporated, plus:
- Initial rubric with tier definitions and examples drawn from pilot pairs
- Edge cases and ambiguities flagged
- Explicit framing: rubric is starting material for collaborative
  refinement

### Week 5-7: Codebook (developed with librarian)

- Tier definitions
- Decision rules for edge cases
- Examples for each tier (positive and negative)
- Jurisdictional matching policy
- Cite-accuracy policy
- Documentation of every decision made during development
- Will become an appendix in the paper

### Week 8: Pre-registration Document

- Sampling protocol (specific stratification)
- Rubric (final from codebook work)
- Assessor configuration (final, validated)
- Models under test
- Metrics and analysis plan
- Hypotheses
- Sample size justification

Timestamp on OSF or public repo before any confirmatory work begins.

### Weeks 13-20: Paper Draft

Standard structure, with attention to:
- Conflicts of Interest section (explicit, complete)
- Methodology section reporting against pre-registration
- Decomposed per-stage results
- Honest acknowledgment of limitations (selection bias, retrieval
  failures, assessor uncertainty)
- Clean separation of pilot (exploratory) and confirmatory results

---

## Cross-links to engineering work

The publication plan and the engineering roadmap are coupled at specific
points:

| Publication plan event | Engineering work it gates / depends on |
|---|---|
| Week 3 ML co-author conversation | Tensions #2 (self-preference) and #3 (cost vs quality) in [methodology review](2026-05-05-external-methodology-review.md) |
| Week 4 librarian conversation + rubric draft | Tiered rubric (concrete addition #2 in methodology review) |
| Weeks 5–7 codebook + assessor validation | Tension #1 (court agreement as ground truth) in methodology review; human-coding interface; cross-family assessor pilot for tension #2 |
| Week 8 pre-registration | Tension #4 (pilot vs confirmatory) in methodology review; sampling protocol (stratified by tier — already a v1.2 deferred item in `benchmark-roadmap.md`); backfill protocol (concrete addition #1 in methodology review) |
| Week 9 confirmatory dataset construction | Mining bugfixes (eyecite parenthetical attribution + intra-opinion dedup — see `docs/retrospectives/2026-05-04-*.md`); pool building (parallel-track Week 4) |
| Weeks 11–12 model runs | Backfill scaffolding (parallel-track Weeks 1–2) |

If any cross-linked engineering item slips, the corresponding publication
event is at risk and the timeline needs to flex. Track both docs as
coupled.

---

## Things to read or re-read before methodology lock-in

- Magesh et al., "Hallucination-Free?" (Lexis/Westlaw/PL evaluation)
- Dahl et al., "Large Legal Fictions"
- Guha et al., LegalBench
- Zheng et al., CaseHOLD
- Zheng et al., "Judging LLM-as-a-Judge" (and follow-up work on judge bias)
- Liang et al., HELM
- BIG-bench paper
- Gebru et al., "Datasheets for Datasets"
- Bender & Friedman, "Data Statements for NLP"
- Recent Stanford RegLab work on legal AI evaluation
- Any prior work specifically on parenthetical analysis in legal NLP
  (likely sparse — confirm with literature search)

---

## Things to decide with co-authors

- Target venue (ML co-author has best instinct here): NeurIPS Datasets
  & Benchmarks, ACL/EMNLP datasets track, ICAIL, JURIX, or law-school
  journal. Each pulls the paper in a different direction.
- Whether and how to include a contrast set of "settled doctrine"
  propositions
- Final decision on which assessor model and configuration
- Final tier-counts-as-correct policy
- Final stratification proportions
- Whether to publish the dataset publicly, with what license, and with
  what access controls (privacy of parties, ethical concerns about
  specific cases, [Org] data licensing)
- v2 headline framing: methodology contribution vs scale contribution
  (see Cost vs quality section)

---

## Notes to self

- The pilot (130 pairs) is exploratory — use it freely. Don't conflate
  with confirmatory.
- Don't optimize for assessor cost. Assessor quality is the central
  measurement.
- Document everything as you go. The paper writes faster when the
  methodology has been documented in real time.
- Have authorship conversations early and explicitly. Awkwardness now
  beats disputes later.
- Disclosure beats discovery. Over-disclose conflicts; the protective
  move is always to surface them.
- Don't compress the timeline. Five to six months is fast for a
  benchmark paper.
- The ED-first principle holds even if the board would be enthusiastic.
  Don't route around the ED.
- The pilot writeup is for the ML co-author's eyes (after refinement),
  not the ED's. Keep developing it, but don't deliver it as-is to anyone.
- Pre-registration is for *you*, not for reviewers. Write it like a
  contract with future-self.
- Public timestamp in Week 1, not "soon."
