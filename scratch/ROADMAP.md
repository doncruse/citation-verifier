# Roadmap

Long-term direction and feature ideas. For bugs and near-term improvements, see `TODO.md`.

## Security & Trust

### Client-side BYOK (eliminate server proxy for API keys)
CourtListener's API supports full CORS (`access-control-allow-origin` reflects requesting origin, `access-control-allow-credentials: true`, allows `authorization` header). This means we can make CL API calls directly from the browser — the user's token never needs to touch our server.

**Current architecture**: Browser -> our server (token in `X-CL-API-Token` header) -> CL API. User must trust our server.

**Target architecture (hybrid)**: Browser calls CL API directly with user's token, sends back the *response data* (not the token) to our server for name-matching/scoring logic. Token never leaves the browser except to CL.

Benefits:
- Eliminates "trust the server" concern entirely
- Users can verify in DevTools that their token only goes to `courtlistener.com`
- Stronger pitch to security-conscious legal users

Trade-offs:
- Significant JS rework for the API call layer on the Retrieve page
- Need to handle CL rate limiting (429s) client-side
- Verification logic stays server-side (Python) — only the raw API calls move to the browser

**Quick wins (independent of hybrid rewrite)**:
- Switch from `localStorage` to `sessionStorage` (token dies when tab closes)
- Add CSP headers to block inline script injection (XSS mitigation)
- Add Subresource Integrity on any CDN scripts

## Data Contributions

### Contribute WL/Lexis citation strings to FLP
When our tool confirms a citation is real, we know the WL/Lexis citation string maps to a specific CL cluster/docket. CL often doesn't have these proprietary citations on file. We could collect confirmed strings and contribute them as metadata.

Open questions: whether FLP wants this, submission format, batching strategy, IP concerns around WL/Lexis citation strings.

## Brief Verification (`/verify-brief`)

### Grep pre-screen for assessment subagents
Before dispatching an Opus subagent to read a full opinion, grep for a broad term cluster (~10-15 terms spanning the proposition's topic). If zero hits in a 35K+ opinion, skip the subagent and auto-mark Yellow ("Could not locate relevant passages — manual review recommended"). Saves significant time and tokens on fabricated-holding citations (e.g., Dow AgroSciences and Sierra Club in the Fivehouse run burned ~80 sec and ~70K tokens to confirm irrelevance).

Design questions: How to generate the term cluster (static per-topic vs. LLM-generated)? Zero hits vs. fewer-than-N threshold? Search full opinion or just cited page range? See `docs/retrospectives/2026-03-09-verify-brief-pipeline-fivehouse-v-dod.md` §A.

### Haiku prescreen for assessment (ready to ship)
Haiku reads opinions and produces structured summaries; Opus assesses from summaries instead of full text. Tested across 3 briefs (102 claims): 76% exact match, 21% conservative (safe), 3% false upgrade (all one-step). ~15x cheaper per opinion read. Ship with conservative bias. Tune Haiku prompt to include "partially related" passages to reduce Yellow→Red over-strictness. See `docs/retrospectives/2026-03-10-haiku-prescreen-test.md`.

### Fabricated quote detection (separate criterion)
The Fletcher v. Experian run exposed our biggest blind spot: we rated 5 claims Green (substantive accuracy) where the court called them fabricated quotes because the exact words in quotation marks weren't the opinion's actual words. Assessment should split into two axes: (a) does the case support the proposition? and (b) does the quoted language appear verbatim? A claim can be Green-substance + Red-quote. This is what BriefCatch's "FABRICATED QUOTE" tag does. See `docs/retrospectives/2026-03-10-verify-brief-fletcher-v-experian.md`.

### TOA vs body citation cross-check
Phase 1a should extract citations from both the Table of Authorities and the brief body independently, then flag discrepancies in reporter volume, page, or year. The Fletcher brief cited "97 F.3d 678" in the body (resolves to *US v. NYC Transit Authority*, 2d Cir.) but "597 F.3d 678" in the TOA (the correct Bryant case). BriefCatch caught this deterministically; we missed it because we only used the TOA version. This is a Layer 1 check that should be free.

### Statute and rule verification (scope expansion)
Currently we only verify case citations. BriefCatch flagged 28 U.S.C. § 1927 for "wrong statutory standard" — the brief attributes procedural requirements (notice, briefing, evidentiary hearing) to § 1927 that aren't in the statute text. This is a real category of error in AI-generated briefs. Could add a lightweight statutory-text check: extract the brief's characterization of the statute, compare to actual statutory language. Lower priority than case-citation work but worth tracking.

### Targeted reading for long opinions
When all pinpoints cite the same page, read that section first before committing to a full opinion read. For very long opinions (100K+), use keyword search to locate relevant passages before dispatching a subagent. Reduces cost even for *correct* citations — Ohio Valley (114K chars) required 17 tool uses and 52K tokens to assess 4 claims all citing the same page.

## Verification Quality

### Semantic search fallback (CourtListener Citegeist)
CL supports `semantic=true` for `type=o` searches. Could help with abbreviation mismatches, name variations, multi-defendant cases. Best fit: new step between opinion search (Step 2) and RECAP search (Step 3), triggered only on failures. See: https://www.courtlistener.com/help/api/rest/search/#semantic-search

### Justia cross-reference diagnostic
One-off script to compare NOT_FOUND citations against Justia to distinguish: real hallucinations, CL data gaps, our search bugs. Diagnostic only — helps prioritize what to fix.

### Surface multiple candidates when the verifier has uncertainty
Today `VerificationResult.final_ids` carries one cluster_id / docket_id / recap_document_id — the verifier picks the single best match and (when uncertain) flags concerns via warnings. Per design v2 §1.2 ("Anything in between — heuristic guesses, probabilistic classifications, vibes — gets pushed up to the consumer"), warnings push uncertainty up *qualitatively* but the schema has no way to push it up *concretely*. Add an optional `candidates: list[CandidateMatch]` field (or similar) on `VerificationResult` that carries the runners-up the verifier considered, ranked, so a consumer can second-guess the pick without having to re-run the pipeline.

Motivating cases:
- CL has duplicate clusters for the same opinion and the verifier scored a non-canonical one higher (Anderson v. Furst class of bug). Today: VERIFIED with a `cl_duplicate_clusters` warning. With candidates: VERIFIED + warning + both cluster IDs listed, so a downstream QC tool or skill can show the alternatives.
- Opinion search returns two real cases with similar scores against an ambiguous brief name. Today: pick the higher score, possibly warn. With candidates: pick + show the runner-up so the consumer can spot when the pick was a coin flip.
- VIA_RECAP vs DOCKET_ONLY borderline cases where two RECAP documents on the docket could each plausibly be the cited opinion.

Design questions (non-trivial, do not fold into the in-progress refactor):
- Is the candidates list always populated, or only when uncertainty crosses a threshold?
- Ranked by confidence, or flat with per-candidate confidence?
- Does adding the list make Status harder to use (every VERIFIED might still have alternatives)?
- How does it interact with the `cl_duplicate_clusters` / `cl_display_name_data_bug` warnings — are they redundant once candidates is populated, or complementary (warnings carry the *reason*, candidates carry the *evidence*)?
- The pre-refactor `VerificationResult` had a `candidates: list[CandidateMatch]` field that was dropped during Phase 1; does the v0.3 version inherit that shape or design something different?

Should be its own post-Phase-4 design conversation, not absorbed into Phase 3 (whose scope is status taxonomy + caption_investigation, not schema additions). Surfaced 2026-05-22 conversation; relates to the same "push uncertainty up to the consumer" principle that motivates the warnings system. Schema change would be additive per §1.6 (minor-version bump, CHANGELOG entry).

### Configurable verification depth (generalize `quick_only`)
`verify_batch()` already accepts `quick_only=True` to stop after stage 1 (citation lookup). Generalize to `max_depth: StageName` (or similar) so callers can choose to run stage 1+2 but skip RECAP, or stop wherever else along the ladder. Useful when the caller knows they only care about high-confidence hits, or wants a fast first pass before deciding whether to invest in deeper fallback (e.g., a batch job that processes 10K citations and is fine accepting NOT_FOUND for whatever doesn't resolve in the first two stages).

Implementation note: this is a flag on the existing per-citation iteration, not a pipeline-by-stage restructure. The batch-by-stage version was considered (run all stage-2 calls before any stage-3 calls, etc.) but only the citation-lookup endpoint is a true wire-level batch; opinion search and RECAP are one-call-per-citation, so reordering by stage trades real costs (more in-flight state, a slow stage-2 call blocking the whole stage-3 wave, `resolution_path` entry ordering decoupling from wall-clock ordering) for orchestration-only benefit. Depth control is the actual user-facing value; achieve it with the smaller change.

Open questions: stage-name vs. integer-depth parameter shape (stage names are semantic but brittle to future stage additions; integers are opaque); whether depth-capped results stay `NOT_FOUND` with a warning or get a distinct status like `VERIFICATION_TRUNCATED`. Surfaced 2026-05-21 conversation while mid-refactor; deliberately deferred to keep refactor scope clean.

## Scale & Distribution

### Package for other legal tech tools
If verification quality stabilizes, consider packaging the core library for use by other tools (brief-drafting AI, document review platforms, etc.). The `pip install -e .` editable package structure is already in place.
