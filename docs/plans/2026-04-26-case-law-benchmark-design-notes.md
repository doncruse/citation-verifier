# Case Law Benchmark — Design Notes & Open Questions

**Status:** Brainstorming snapshot. Captures everything discussed before any testing. Not all decisions here are committed.
**Date:** 2026-04-26
**Companion docs:**
- [Original design (committed v1)](2026-04-26-case-law-benchmark-design.md)
- [Pilot A plan (committed)](2026-04-26-benchmark-pilot-a.md)

This doc exists because the brainstorming kept generating useful structure that doesn't fit cleanly back into the original spec yet. After Pilot A runs (and possibly Pilot B), the spec gets revised to fold in whatever's validated. Until then, this is the working memory.

---

## What we're building

An **open evaluation instrument** — code, dataset recipe, scoring methodology — that anyone can run locally to measure how well any model (raw foundation model or commercial legal RAG product) finds supporting US case law for a given proposition.

Key framing decisions, in priority order:

1. **Instrument, not leaderboard.** No central referee. The repo *is* the spec; submissions are scorecards posted by anyone running the harness.
2. **Multi-axis scoring, not single accuracy number.** Real / name-matches / supports-proposition / good-law / jurisdictionally-appropriate. Raw and RAG models fail in opposite ways on these axes; collapsing them hides the most interesting comparisons.
3. **Federated kit.** Federal layer maintained here; the schema, mining playbook, and scoring code are designed to be forked by states or other jurisdictions without us building those forks.
4. **Continuous-corpus, procedurally-generated benchmark instances** (not fixed test sets — see "Contamination resistance" below).

## The gap this fills (versus existing work)

| Existing | What it does | Why it's not this |
|---|---|---|
| [LegalBench](https://hazyresearch.stanford.edu/legalbench/), [LawBench](https://arxiv.org/pdf/2309.16289), [LEXam](https://arxiv.org/html/2505.12864v1) | Legal reasoning tasks (rule application, classification, MCQ) | Not retrieval over a real corpus |
| [CaseHOLD](https://reglab.stanford.edu/data/casehold-benchmark/) | Pick correct holding from 5 candidates | Closed-form; not open-corpus retrieval |
| [Dahl et al. 2024](https://arxiv.org/abs/2401.01301), [Magesh et al. 2025](https://onlinelibrary.wiley.com/doi/full/10.1111/jels.12413) | Hallucination rate audits | Don't evaluate retrieval *quality* against propositions |
| [CLERC](https://aclanthology.org/2025.findings-naacl.441/) | Retrieve case originally cited | Single right answer; doesn't model real research |
| [RegLab Bar Exam QA / Housing Statute QA](https://reglab.github.io/legal-rag-benchmarks/), [Isaacus Legal RAG Bench](https://huggingface.co/datasets/isaacus/legal-rag-bench) | RAG over statutes / single authoritative source | Works because statutes have one canonical form. Case law doesn't. |
| [Vals VLAIR](https://www.vals.ai/vlair) | Vendor leaderboard for legal AI | Methodology disputed; gold-answer quality contested by participating attorneys; vendor-cooperation model fragile |

**Where the user's instinct landed**: there's no open benchmark for *finding US case law* — i.e., open-corpus retrieval where the model produces a citation, scored against multiple acceptable cases, with both raw chat models and commercial tools as in-scope evaluation targets.

## Vendor landscape — relevant context, not collaborators

Three vendors are explicitly building proposition-citation knowledge graphs as proprietary infrastructure:

- **[Descrybe](https://descrybe.ai/)** — 3.6M opinions from CAP summarized into structured "primary law"; closed citator
- **[Counsel Stack](https://www.counselstack.com/)** — 99%+ federal precedential coverage; sells managed service or containerized image; topped VLAIR authoritativeness
- **[Midpage](https://www.midpage.ai/)** — explicitly built around "legal propositions" (their term, same as ours); now [a native connector inside Claude and ChatGPT](https://www.geeklawblog.com/2026/02/midpage-goes-native-legal-research-inside-claude-and-chatgpt-with-otto-von-zastrow.html) (Feb 2026)

Implications:
- The proposition-citation graph is now a commercial moat. Multiple well-funded vendors are racing.
- None of it is open. An open evaluation layer is genuinely a public good.
- We are **not** building a competing graph. We measure outputs. Vendors keep their graphs; the harness scores whatever raw text any system produces.
- Midpage's Claude/ChatGPT connector means the eval-mode space sprouted a new branch — "chat model + vendor RAG tool" is now distinct from generic web search and from standalone vendor tool.

## Decisions confirmed (in committed spec)

- Open dataset, open code, open scoring; deterministic where possible (LLM-judge prompts pinned)
- Multi-axis rubric using existing `/verify-brief` Phase 2 substance assessor as equivalence oracle
- Eval modes: parametric / web search / vendor RAG / DIY RAG (now plus chat-model+vendor-tool)
- Federal-only v1; state forks enabled via the kit, not built
- PACER briefs deferred to v2

## Decisions still open (this is the new material)

### 1. Substrate source — fresh mining vs. existing public datasets

Two viable sources of `(proposition, citation)` pairs:

- **[CourtListener parentheticals](https://www.courtlistener.com/help/api/bulk-data/)** — explanatory parentheticals from citations, extracted at scale by FLP. Literal proposition-case pairs written by judges. High precision; relatively narrow.
- **[LePaRD](https://arxiv.org/abs/2311.09356)** — 3.9M target passages × 14M citation contexts from all 1.7M federal opinions. Looser semantics; much higher volume.

Versus building our own from federal district court opinions (the original design's plan).

**Trade-off**:
- Existing data: weeks-not-months of v1 work; provenance argument is even cleaner ("the proposition was written by the judge in the same sentence as the citation")
- Fresh mining of district court opinions filed 2025-2026: postdates training cutoffs; potentially much harder benchmark; user's strong instinct that this is meaningfully different

**Concerns about existing data**:
- Both LePaRD and CL parentheticals are likely in frontier model training corpora — parametric mode tests memorization rather than retrieval
- LePaRD has long-tailed distribution; top-1% of cases account for 24% of citations
- Naive sampling is famous-case-heavy → tests memorization, not research

**This is exactly what Pilot A measures**: does fresh-mined district court data produce ≥15 pp lower model accuracy than LePaRD-sampled data, holding everything else constant? See [Pilot A plan](2026-04-26-benchmark-pilot-a.md). Decision waits on results.

### 2. Query phrasing — propositions vs. research questions

A judge writes: *"An agency action is arbitrary and capricious if the agency entirely failed to consider an important aspect of the problem."* A researcher asks: *"What's the standard for finding agency action arbitrary and capricious — specifically when the agency overlooks a key factor?"*

The first is a **statement of law**. The second is how a lawyer actually queries a model. Real research starts from the question, not the proposition. Three ways to bridge:

| Approach | Cost | Quality | Scales? |
|---|---|---|---|
| LLM-generated rephrasing | cheap | leaks proposition vocabulary | yes |
| LLM-drafted, human-edited | moderate ($) | high | partial |
| Fully human-written | expensive | highest | no |

Likely v1: **LLM-drafted + human-edited** for a flagship slice of 200-500 questions; LLM-only for the long tail. State forks adopt the same pattern.

### 3. Query variant layer — the architectural insight

The current spec couples the *substrate* (proposition + gold case) with the *query sent to the model*. Decoupling them makes the benchmark dramatically more useful:

```
SUBSTRATE (the hard part — built once, reused)
    proposition + gold case + alternatives oracle
                    │
                    ▼
QUERY VARIANT LAYER (cheap, extensible)
    • verbatim proposition
    • neutral research question
    • leading / false-premise
    • counterfactual / negation
    • adversarial overload
    • [community contributions]
                    │
                    ▼
            evaluation harness
```

**Concrete example** (user's): substrate is `proposition = "elements of negligence are duty, breach, causation, harm" | gold = Palsgraf`. Query variants:

| Variant | Query | What it tests |
|---|---|---|
| Verbatim | "Find a case supporting [proposition]" | baseline |
| Neutral | "What are the elements of negligence?" | real-world framing |
| **False-premise** | **"What are the *five* elements of negligence?"** | **sycophancy / fabrication under pressure** |
| Counterfactual | "Cite a case holding negligence has only three elements" | does it fabricate to satisfy the question? |
| Loaded | "Everyone knows negligence requires intent — what case establishes that?" | does it accept legal misinformation? |

A model passes the false-premise variant by **pushing back on the premise**, not by inventing a fifth element.

**Why this is unusually well-suited to this benchmark**:
- New scoring axes plug in (premise pushback, fabrication) without changing substrate or existing axes
- Researchers can add their own variants without touching substrate
- Variants are corpus-agnostic, so they work across all federated forks for free
- Memorizing `proposition X → case Y` doesn't help against false-premise variants — they're harder to game

**Why this isn't scope creep**: the benchmark becomes a *research instrument for studying prompting+retrieval interactions in legal AI*, not just a model leaderboard. That positioning is what justifies the open-source-eval-framework framing in the first place.

### 4. Contamination resistance — the longevity question

Worry: vendors train on the published benchmark and "master" it; the score becomes meaningless.

Standard defenses, in rough order of effectiveness:

1. Hidden test sets (rejected — requires central referee)
2. Periodic question rotation (works; needs maintenance budget)
3. **Held-out-by-date** (strong fit here — case law continuously grows)
4. **Procedural generation** (don't ship fixed questions; ship a recipe + corpus + sampling code)
5. Adversarial query variants (item 3 above) — robustness tests can't be memorized away
6. Federated jurisdictions — if all federal data ever gets compromised, fork to a state

**The architectural advantage we get nearly for free**:

The substrate isn't a fixed dataset; it's *a function over a continuously-growing corpus*. CourtListener adds federal opinions daily. LePaRD-style mining can be re-run on any time window. So:

- Continuous freshness: "evaluate on parentheticals from federal opinions filed in last 6 months" is, by definition, uncontaminated by any model whose training cutoff predates the window. Window slides forward as corpora grow.
- Procedural generation: instead of `benchmark.csv`, we ship `benchmark draw --since 2026-04-01 --n 500 --seed 42`. Two users with different seeds get different samples but statistically comparable scores. Vendors can't train on "the benchmark" because no canonical instance exists.
- A small reference run is published for reproducibility but explicitly labeled "for sanity checks; not a real measurement."

**Honest about what still leaks**:
- Bulk corpora (CAP, RECAP) are likely in training data → parametric mode is hard to fully de-contaminate. Web/RAG modes less affected.
- A vendor could reverse-engineer our sampling code and flood training corpus with matching parentheticals. Mitigations: randomize quality-gate parameters per draw; rotate lexical-dissimilarity threshold.
- Vendors with proprietary citators (Westlaw, Lexis, Counsel Stack) trivially top a leaderboard whose questions come from public parentheticals — their graphs *include* those parentheticals. Disclosure norm: label submissions with what data the system has access to.

**Existing models for this architecture**:
- [LiveCodeBench](https://livecodebench.github.io/) — continuously adds new coding problems from recent contests; reports scores stratified by date so contamination is visible
- [LiveBench](https://livebench.ai/) — releases new questions monthly to stay ahead of cutoffs
- [Dynabench](https://dynabench.org/) — adversarial human-in-the-loop rotation

**The pitch this enables**: not *a* benchmark, but **a continuously-refreshing evaluation framework for legal retrieval AI**. Reports cite specific draws (`evaluated on the 2026-Q3 federal-DC sample, n=500, seed published`). Stale leaderboard entries get clearly marked as "evaluated on dataset older than [model's training cutoff]." The benchmark is a measurement *tool*, not a static measurement *artifact*.

## Pilots planned

- **[Pilot A](2026-04-26-benchmark-pilot-a.md) — committed, ready to run.** 50 LePaRD samples vs. 50 fresh-mined district court parentheticals; one frontier model; closed-book; multi-axis scoring on three of five axes. Decides whether substrate must be fresh-mined.
- **Pilot B (planned, conditional)** — if Pilot A is inconclusive (5–15 pp gap), stratify LePaRD by citing-opinion year (pre-2020 / 2020-2023 / 2024+). Tells us whether *just-recent* LePaRD beats fresh-mining without the mining cost.
- **Pilot C (planned, conditional)** — long-tail vs. famous-case stratification within each source. Tests whether obscurity drives difficulty more than freshness does.
- **Future pilot — query variants**: do false-premise variants meaningfully separate models that look identical on verbatim queries? Validates whether variant layer is worth shipping in v1.
- **Future pilot — research-question rephrasing**: does LLM rephrasing degrade benchmark validity vs. human-edited rephrasing? Sets the cost/quality ratio for the variant generation pipeline.

## What this is *not*

- Not a leaderboard with a central referee
- Not a vendor compliance audit (no vendor cooperation needed; we score raw outputs)
- Not a measurement of "lawyer accuracy" (gold is what was cited in published opinions; not "what a careful lawyer would conclude is right")
- Not a competing knowledge graph (vendors keep theirs; we evaluate outputs)
- Not a replacement for LegalBench/CLERC/CaseHOLD — complements them

## Status of the conversation

Where we are right now: design is in flux; original spec captures v1 framing; this doc captures everything since; Pilot A is the next executable step. After Pilot A, the spec should get a real revision that folds in:
- Substrate decision (existing data vs. fresh mining vs. hybrid)
- Substrate/query-layer architectural separation
- Continuous-corpus procedural-generation framing
- Query variants as first-class
- Vendor landscape positioning ("not a competing graph")

Decision deferred until Pilot A: whether the v1 substrate is LePaRD+CL parentheticals, fresh-mined district court parentheticals, or both. Everything else can probably go into a spec revision before Pilot A runs, if there's appetite.

## References

- [Original design doc (committed v1)](2026-04-26-case-law-benchmark-design.md)
- [Pilot A plan (committed)](2026-04-26-benchmark-pilot-a.md)
- [LegalBench](https://hazyresearch.stanford.edu/legalbench/)
- [CaseHOLD](https://reglab.stanford.edu/data/casehold-benchmark/)
- [Large Legal Fictions (Dahl et al. 2024)](https://arxiv.org/abs/2401.01301)
- [Hallucination-Free? (Magesh et al. 2025)](https://onlinelibrary.wiley.com/doi/full/10.1111/jels.12413)
- [CLERC (NAACL 2025)](https://aclanthology.org/2025.findings-naacl.441/)
- [LePaRD](https://arxiv.org/abs/2311.09356)
- [A Reasoning-Focused Legal Retrieval Benchmark](https://reglab.github.io/legal-rag-benchmarks/)
- [Isaacus Legal RAG Bench](https://huggingface.co/datasets/isaacus/legal-rag-bench)
- [CaseFacts (2026)](https://arxiv.org/abs/2601.17230)
- [Vals VLAIR](https://www.vals.ai/vlair)
- [Free Law Project Citator progress report](https://free.law/2025/05/01/citator/)
- [The AI Benchmarking Tightrope (Artificial Lawyer)](https://www.artificiallawyer.com/2025/05/15/the-ai-benchmarking-tightrope-moving-from-good-intentions-to-gold-standards/)
- [Vals Legal AI Eval — The Aftermath (Artificial Lawyer)](https://www.artificiallawyer.com/2025/10/20/vals-legal-ai-research-eval-the-aftermath/)
- [Descrybe](https://descrybe.ai/) | [Counsel Stack](https://www.counselstack.com/) | [Midpage](https://www.midpage.ai/)
- [LiveCodeBench](https://livecodebench.github.io/) | [LiveBench](https://livebench.ai/) | [Dynabench](https://dynabench.org/)
