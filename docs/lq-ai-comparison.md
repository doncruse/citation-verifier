# LQ.AI vs. citation-verifier — capability comparison & contribution map

**Date:** 2026-06-18 · **Author:** analysis run (Claude Opus 4.8)
**Subject repo:** [`LegalQuants/lq-ai`](https://github.com/LegalQuants/lq-ai) (mirrored to `Tucuxi-Inc/lq-ai`)
**Snapshot basis:** lq-ai `main` HEAD `dac1f3f`, migration head `0049`, `EXPECTED_PATHS=123` (per their 2026-06-17 legal-research handoff). *This is a point-in-time snapshot; re-verify before acting — the legal-research milestone is actively moving.*

> Companion artifact: [docs/plans/2026-06-18-de279-lq-ai-case-resolver-port.md](plans/2026-06-18-de279-lq-ai-case-resolver-port.md) — the concrete PR plan for the top opportunity below.

---

## 1. What LQ.AI is

A **self-hosted, open-source AI platform for legal teams** ("bring your own keys, run it where you want, own your data"). Apache-2.0. The product is much bigger than citation work: conversational chat with matter-scoped Projects, an open Skill Library (Anthropic Claude Skills format), a privacy-preserving **anonymization layer**, an **inference gateway** with tier-floor enforcement, an append-only **audit log**, playbooks, tabular/multi-document review, a Word add-in, and Slack/Teams intake bridges. Milestones M1–M4 shipped; the Autonomous Layer shipped in M4.

Their differentiator is **transparency**: every artifact that shapes output (skills, playbooks, citation logic) is open and inspectable. That posture is what makes a code contribution from us land cleanly — the verification logic is *supposed* to be readable.

## 2. The three-type citation taxonomy (the key framing)

LQ.AI explicitly splits "citation checking" into three architecturally distinct surfaces ([docs/citation-engine.md §Scope](https://github.com/LegalQuants/lq-ai/blob/main/docs/citation-engine.md)):

| Type | What it verifies | LQ.AI status | Our tool |
|---|---|---|---|
| **1 — KB-quote accuracy** | Does the model's quote/meaning faithfully represent an *operator-uploaded* document, at character precision? | ✅ **Shipped (M2)** | ❌ Not our domain |
| **2 — Case citation validation** | Does `Smith v. Jones, 123 U.S. 456` resolve to a real opinion? (catch fabrication) | ❌ **Not built** — [DE-279](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md), P1/M | ✅ **Our core** |
| **3 — Case-content accuracy** | Does the cited case actually *support the proposition* it's cited for? | ❌ **Not built** — [DE-280](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md), P1/L | ✅ **Our proposition pipeline** |

The headline: their *shipped* "Citation Engine" is **type 1 only** — it verifies quotes against uploaded KB docs, **not** case law. The two surfaces that *are* our project (types 2 & 3) are scoped-but-unbuilt deferred-enhancement tickets — and **DE-279 names `Tucuxi-Inc/Legal-Week-Cite-Checker` as the reference implementation to port.** The contribution door is explicitly open.

## 3. What LQ.AI has actually shipped for case law

A **thin, model-callable CourtListener tool**, brokered through a governed gateway egress boundary (PRs #158–161, June 16–17 2026; ADR 0014 / ADR 0015):

- Gateway tool provider [`gateway/app/providers/tool/courtlistener.py`](https://github.com/LegalQuants/lq-ai/blob/main/gateway/app/providers/tool/courtlistener.py) — 3 read tools: `verify_citations`, `search_case_law`, `get_cases`.
- api research subsystem [`api/app/research/service.py`](https://github.com/LegalQuants/lq-ai/blob/main/api/app/research/service.py) — read-through opinion caching (plaintext → object storage, metadata → DB), plus `find_in_case` / `read_opinion`.
- REST surface `/api/v1/research/*`. Egress is SSRF-guarded, tier-checked, and written to `tool_egress_log`. The backend **never** calls CourtListener directly (ADR 0014).

**Their design philosophy:** thin tools, the model reasons over the results, and quotes get verified against fetched text via the type-1 cascade. Their strength here is the **boundary** (egress control, audit, operator-owned credentials), not the verification *logic*.

**The critical gap:** `verify_citations` returns whatever `/citation-lookup/` resolves with **zero check that the cited case *name* matches the cluster**. It catches a non-resolving reporter, but not the #1 AI hallucination — a real reporter slot with a fabricated/swapped name. DE-279 *claims* "catches fabricated citations"; the shipped tool does not fully.

## 4. Side-by-side

**Where we are ahead of their shipped case-law surface:**

1. **Name-match verification** — they have none; we have multi-factor matching + a status taxonomy (`VERIFIED` / `POSSIBLE_MATCH` / `WRONG_CASE` / `VERIFIED_PARTIAL` / `CITE_UNCONFIRMED`) built around exactly this (Charlotin Bug 1/3 policies).
2. **Fallback resolution** — we retry by name+court+date opinion search, then RECAP docket-entries; reporter-family logic (`N.E.2d ≡ N.E.3d`), parallel cites. They do a single reporter lookup.
3. **Proposition verification (type 3)** — entirely unbuilt for them; our assess-v1/v2 prompts, quote-floor, two-axis `derive_color`, frozen gold-set + `RecordedExecutor` replay + A/B harness are the DE-280 spec.
4. **Parsing robustness** — eyecite + regex fallbacks (WestLaw, California style, reversed parentheticals), slip-opinion stripping, 47-term abbreviation normalization, smart-apostrophe folding.
5. **Operational** — 429 `wait_until` retry, `verify_batch` single-call efficiency, state-reporter→court inference, sibling-cluster swap (short-order vs merits opinion).

**Where they are ahead of us:**

- The whole **platform**: inference gateway, anonymization layer, tier enforcement, audit log, MCP client (in progress), open skills, playbooks, tabular review, Word add-in.
- **Type-1 KB-quote verification** — a 4-stage cascade (exact → tolerant `rapidfuzz≥95` → paraphrase judge → N-model ensemble) with a per-row privacy envelope. A surface we don't cover at all.
- **Production security infra** around any external call (SSRF hardening, egress tiering, credential ownership, append-only audit).

**Independently converged:** their opinion-text fallback chain (`html_with_citations → … → plain_text` in `courtlistener.py`) solves the same empty-`plain_text` state-court problem our `_extract_opinion_text` does — but ordered opposite to ours (they prefer HTML-with-citation-markup first; we prefer clean `plain_text` first). Worth a conversation, not a clear bug on either side.

## 5. Roadmap tickets we map onto

DE-numbers are **Deferred Enhancements** in [`docs/PRD.md` §9](https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md) (197 entries; non-sequential stable IDs; CONTRIBUTING points contributors here and flags P1 as "particularly welcome").

- **DE-279** (PRD.md ~L2895, P1/M) — case citation validation. Scopes `api/app/citation/case_resolver.py`: Bluebook detector + CourtListener client + resolution. Names our lineage as the port reference.
- **DE-280** (PRD.md ~L2918, P1/L) — case-content accuracy. Scopes `api/app/citation/case_content_judge.py`: fidelity+completeness judge over full opinion text, calibrated gold set at `eval/case-content-accuracy/` (~50 attorney-reviewed pairs, ≥0.85 precision @ ≥0.70 recall). Depends on DE-279.
- **DE-281** (PRD.md ~L2942, P2/S) — Citation-Engine telemetry calibration (type-1 thresholds). Not ours.

## 6. Contribution opportunities (ranked)

1. **DE-279 name-match layer — highest ROI, lightest review.** ⭐ Port our `name_matcher` + status taxonomy as an api-side verification layer over their existing gateway `verify_citations`. `name_matcher.py` imports only `re`+`difflib` (zero new deps). api-only → self-merge after CI (no `gateway/**` security gate). Fixes the real correctness hole they advertised. **→ Plan written: [docs/plans/2026-06-18-de279-lq-ai-case-resolver-port.md](plans/2026-06-18-de279-lq-ai-case-resolver-port.md).**
2. **DE-280 proposition/case-content judge — deepest fit, larger.** Our proposition pipeline *is* this. Lead with the judge rubric (fidelity + cherry-pick) + the calibrated gold set, where attorney attestation is load-bearing (their `skills/CONTRIBUTING.md` path). Multi-week; gated on DE-279.
3. **CourtListener adapter robustness — small (but `gateway/**` review).** 429 `wait_until` retry, slip-opinion placeholder stripping, state-court field-ordering evidence (our 86%→9% smoke test), and a one-line doc fix (DE-279 text says CL `v3`; the code is `v4`).

## 7. Why NOT a skill, and why MCP isn't the lq-ai on-ramp

- **A "verify→name-check→proposition" skill is useless as an engine.** LQ.AI skills are pure prompt artifacts — their `lq_ai:` frontmatter has no `tools`/`allowed-tools` field, and the governed model-tool-calling loop (ADR 0015 / WS4 / PR5) is **unbuilt**. A skill can't drive tools; it can only describe a workflow. The value has to be **backend capability** (DE-279/280 modules); a skill is at most thin shrink-wrap once the tool-loop exists.
- **Exposing this repo's verbs as an MCP server is great for us, but not the lq-ai path.** (a) Their MCP client (WS2/PR4) *and* the chat tool-loop (PR5) are both unbuilt follow-ons — nothing in lq-ai can consume an MCP server today. (b) A verdict-producing MCP server calls CourtListener and an LLM judge itself, *outside* lq-ai's gateway/tiering/anonymization — which breaks the data-sovereignty story lq-ai exists for (especially for privileged matters). Their model wants the *code inside the boundary*, not a fat external tool. Also note: our verbs are a stateful workdir+jobs pipeline, not stateless RPCs; only `verify`/`verify_batch` wrap cleanly, while `AgentSDKExecutor` can't run inside an MCP server's event loop. MCP is worth doing for our own use (Claude Code/Desktop, the CL MCP ecosystem) — just not as lq-ai integration.

## 8. Bottom line

Our tool is a mature, battle-tested implementation of exactly the two case-law surfaces (DE-279, DE-280) that LQ.AI has scoped, prioritized P1, and explicitly invited a port for — and that their shipped thin tool does naively or not at all. The cleanest first contribution is the DE-279 name-match layer (plan ready). DE-280 is the bigger, deeper play to follow. Skills and an MCP server are adjacent goods, not the on-ramp.
