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

### Targeted reading for long opinions
When all pinpoints cite the same page, read that section first before committing to a full opinion read. For very long opinions (100K+), use keyword search to locate relevant passages before dispatching a subagent. Reduces cost even for *correct* citations — Ohio Valley (114K chars) required 17 tool uses and 52K tokens to assess 4 claims all citing the same page.

## Verification Quality

### Semantic search fallback (CourtListener Citegeist)
CL supports `semantic=true` for `type=o` searches. Could help with abbreviation mismatches, name variations, multi-defendant cases. Best fit: new step between opinion search (Step 2) and RECAP search (Step 3), triggered only on failures. See: https://www.courtlistener.com/help/api/rest/search/#semantic-search

### Justia cross-reference diagnostic
One-off script to compare NOT_FOUND citations against Justia to distinguish: real hallucinations, CL data gaps, our search bugs. Diagnostic only — helps prioritize what to fix.

## Scale & Distribution

### Package for other legal tech tools
If verification quality stabilizes, consider packaging the core library for use by other tools (brief-drafting AI, document review platforms, etc.). The `pip install -e .` editable package structure is already in place.
