# Refactor Design — Review Pass

**Reviews:** `2026-05-20-citation-verifier-refactor-design.md`
**Reviewer:** Claude (brainstorming/critique pass, 2026-05-20)
**Purpose:** Capture the issues to address in follow-up revisions to the design. The design was committed as-is; this file is the working list of things to change or push back on.

---

## What's working — keep this load-bearing

The animating principle ("Code owns procedure. The model owns judgment. The schema is the contract.") is the right insight for this category of problem. Three places it pays off concretely:

- **`VERIFICATION_INCOMPLETE` vs `NOT_FOUND` split.** This is the malpractice-shaped failure mode and §2.2 + §2.8 isolate it correctly as the one internal gate. Don't let this erode in implementation; it's the safety property the verifier exists to provide.
- **Explicit non-inclusion of `FABRICATED_LIKELY` in §2.3.** The epistemic discipline of "from inside CL, we can't honestly distinguish fabricated from coverage-gap from query-malformed" is exactly right. This will be tempting to violate during Phase 3 ("the verifier could be more useful if it just said when something looks fake") — don't.
- **Cross-repo discipline in §5 (tag-pin staging + editable-install dev loop).** Standard and well-articulated. Principle 1.6 is genuinely doing work, not theater.

---

## Top concerns — to address before implementation starts

### 1. `VERIFIED_DISPLAY_NAME_MISMATCH` probably shouldn't be a status

It's a CL data-quality fact that §2.6's `cl_display_name_data_bug` warning already covers. The citation *is* verified; CL's metadata is the issue. Right now the same information is encoded in both `status` and `warnings`, which forces consumers to reason about both.

**Proposed fix:** drop to warnings-only. `status: VERIFIED` with `warnings: [cl_display_name_data_bug]`. Drops the status taxonomy from seven to six.

**Underlying gap:** the doc doesn't articulate the rule for when a thing belongs in `status` vs. `warnings`. Suggested rule, worth adding to §2:

> `status` answers "what's the relationship between this citation and reality?" `warnings` are facts about *how the verifier reached its answer* or *quirks the consumer should know about the underlying data*.

By that rule, the display-name mismatch is a warning. Apply the rule and the six-status taxonomy falls out cleanly.

### 2. `confidence: float | null` — what does it mean now?

In the old taxonomy, confidence distinguished `LIKELY_REAL` from `POSSIBLE_MATCH` from `VERIFIED`. In the new taxonomy, those distinctions live in the granular `VERIFIED_*` states.

So: is `confidence` vestigial? The current shape ("0.0–1.0, null for resolved-clean statuses") suggests yes, which means the field will rot. If it has independent meaning, the doc should specify:
- What produces the score
- On which states it's populated
- What consumers are meant to do with it

If it doesn't have independent meaning, remove it from the schema. Vestigial nullable fields are a maintenance trap.

### 3. Scope honesty — separate "the refactor" from "the program built on top"

Nine phases. Phases 1–4 are a refactor (schema, instrumentation, classification, gates). Phases 5–9 are a multi-quarter program built on top (MCP server, skill rewrite + lq-skills submission, evaluator + benchmark flywheel, verify-proposition).

Presenting them as one thing conflates "is the refactor done?" with "is the program done?". The first should have a real answer (yes, after Phase 4); the second is open-ended.

**Proposed fix:** name where the refactor ends in §3. Phases 5–9 are roadmap, not refactor. Reframe the doc as "refactor (Phases 1–4) + roadmap for what builds on it (Phases 5+)." Phase 4 acceptance then becomes a real milestone.

### 4. Phase 7 is doing too much as a single phase

Currently bundles: regression corpus runner, model-driven diagnostic step, dedup cache, issue-drafter, its own MCP surface, and the benchmark flywheel. Each is its own design conversation. Listing as one phase produces design debt — the architecture gets made on the fly during implementation.

**Proposed fix:** split into 7a (corpus runner) / 7b (model-driven diagnostic) / 7c (evaluator MCP + benchmark integration). Or scope this doc to 7a only and treat 7b/7c as later design docs.

### 5. Phase 5 (MCP server) is one paragraph; needs its own design doc

Questions not addressed in the current Phase 5 spec:

- Which Python MCP framework? (FastMCP, official Python SDK, roll your own?)
- Transport (stdio for Claude Desktop? SSE/HTTP for hosted clients?)
- Does the CLI shell out through the MCP, or do both CLI and MCP wrap the same library?
- Is the result schema discoverable as an MCP resource, or only documented out-of-band?
- Versioning — the schema will evolve; how do clients handle that?

**Proposed fix:** don't answer all of these in the refactor design. Acknowledge Phase 5 needs its own design doc once Phases 1–4 land, and move on.

---

## Smaller observations — notes, not blockers

### A. §2.5 `raw_response_summary: dict` shape is unspecified

Across stage implementations this will diverge. Either commit to a per-stage summary schema spec, or explicitly say "free-form, consumers can't rely on shape." Right now consumers can't rely on it but won't know that.

### B. §2.6 closed warning set will need amendments

Phase 3 will surface warning categories not anticipated yet. Plan for the amendment workflow up front (probably: "additions are minor version bumps; removals are major"). Mention this in §2 or §8.

### C. §4 fixture inventory is too small to anchor Phase 3 acceptance

Five existing test fixtures + five proposed exemplars = ten. For six-or-seven statuses with edge cases per status, you'd want 30–50 fixtures. Phase 3's acceptance criterion ("a regression corpus produces the expected status") implies a corpus that doesn't exist yet.

**Proposed fix:** add a sub-phase (Phase 2.5 or a Phase 3 prerequisite) committing to building the fixture corpus *before* Phase 3 implementation, not during. This is where the skill's edge-case discoveries get turned into structured fixtures.

### D. "Evaluator" terminology collision

Lavern uses "evaluator gate" for something architecturally specific (a gate that runs on agent output). The broader AI-evals world also uses "evaluator" with its own meaning. This doc uses "evaluator" for a regression-test-runner + diagnostic + issue-drafter, which is different from both.

**Proposed fix:** rename. "Diagnostic runner" or "regression harness with diagnostic step." Whatever — just don't collide with Lavern's term in a doc that explicitly borrows Lavern's architecture.

### E. Lavern framing is good rhetoric but the implementation isn't deeply Lavern-shaped

Lavern has many gates running on agent output. This doc has gates as optional caller policy plus one internal gate. That's narrower than Lavern's pattern.

**Proposed fix:** in §1.3 ("Lavern-shaped reorganization"), be honest about what's borrowed (the principle: code owns procedure, model owns judgment) vs. what's not (Lavern's gate-heavy implementation). The current framing suggests deeper structural alignment than the architecture actually delivers.

### F. Phase 6 conflates the skill rewrite with the lq-skills submission

The skill rewrite (strip procedural logic; keep ingestion + presentation) is one task. The lq-skills submission is a separate decision that requires:

- The verifier MCP being independently installable
- The skill's frontmatter clearly documenting the MCP dependency
- Handling user friction around "you need to set up a CourtListener API token"
- Reviewing lq-skills' contribution conventions

**Proposed fix:** split Phase 6 into 6a (skill rewrite, lands locally) and 6b (lq-skills submission, gated on the MCP being shippable + acceptable token-setup friction). 6b might not happen on the same timeline as 6a.

---

## Resolution log

Use this section to track decisions as the design is revised. Entry format: `[YYYY-MM-DD] §<section> — <decision> (closes top concern #N / smaller observation #X)`

- _(empty)_
