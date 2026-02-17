# Comment on #6040: API docs blocked by bot protection

## Target

CourtListener issue [#6040](https://github.com/freelawproject/courtlistener/issues/6040) — "Create an `/llms.txt` file"

## Context

Issue #6040 was filed by mlissner in July 2025 with the framing: "It would appear LLMs are reading our documentation but doing a bad job. Perhaps if we give them better pointers, they'll do a better job."

Our finding: The API documentation pages return HTTP 403 to all programmatic (non-browser) requests. LLMs aren't reading the docs badly — they can't read them at all. They fall back on blog posts, GitHub discussions, and cached training data, which explains the bad API usage.

## Evidence

Tested 2026-02-17 using Claude Code's `WebFetch` tool (sends standard HTTP requests):

- `courtlistener.com/help/api/` → **403 Forbidden**
- `courtlistener.com/help/api/rest/` → **403 Forbidden**

Likely caused by blanket bot protection (Cloudflare or similar) across the entire `courtlistener.com` domain. The API endpoints themselves (`/api/rest/v4/`) are accessible with proper authentication — only the human-readable documentation about the API is blocked.

## Draft Comment

Wanted to add some concrete context on this... I think the problem may be more fundamental than LLMs misreading the docs.

The API documentation pages actively block programmatic access. Fetching courtlistener.com/help/api/rest/ from any non-browser client returns 403. This means LLM agents and developer tools aren't just reading the docs badly; they can't read them at all. They fall back on whatever they can find: old blog posts, GitHub discussions, cached training data. This could explain the bad API usage we're seeing, where people are using old API versions.

I hit this while working on my own project. My LLM coding assistant tried to fetch the API docs to help with integration and got 403'd on every /help/api/ page. It ended up relying on GitHub discussions and blog posts instead, which weren't quite right.  I went and looked at the API docs myself and that helped, but not everyone would know to do that. 

An llms.txt file would help, but only if it's served without the same bot protection. A potentially quicker complementary fix could be to exempt the /help/ paths from whatever bot filtering is in place. Those pages are static documentation and probably carry low abuse risk, and making them accessible would immediately improve the quality of every LLM-assisted integration being built against the API.

## Submission Checklist

- [x] Verify #6040 is still open — confirmed OPEN 2026-02-17
- [x] Verify repo link works (ensure citation-verifier is public) — confirmed PUBLIC 2026-02-17 (note: repo link removed from draft)
- [x] Test the 403 one more time to confirm it's still happening — confirmed 403 on 2026-02-17
- [x] Review tone — constructive, not complaining — revised 2026-02-17
- [x] Post comment — https://github.com/freelawproject/courtlistener/issues/6040#issuecomment-3917584540
- [x] Update `flp_contributions.md` with link to comment
