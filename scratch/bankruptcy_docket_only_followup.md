# Follow-up prompt: bankruptcy court docket-only citation coverage

Paste this prompt into a fresh session once the benchmark spinout is done.
It's self-contained — assumes the reader has no memory of the conversation
that produced it.

> **NOTE before you start:** path references below are from when this prompt
> was written (citation-verifier worktree). After the benchmark spinout,
> the `benchmark/scratch/cl-coverage-offshoot/` directory will likely have
> moved. Resolve current paths first.

---

## Prompt

I want to extend the CL coverage study (the offshoot whose memo lives at
`benchmark/scratch/cl-coverage-offshoot/coverage_memo.docx`) to test a
hypothesis: **bankruptcy court opinions cite docket-only orders (no
Westlaw/LEXIS/reporter cite, just `Case No. X (Bankr. D. Del. 2024) [Docket
No. Y]`) far more often than the federal district / state appellate
opinions the existing study sampled.**

### What's already known (from 2026-05-17 exploration)

Across the existing 82 citing opinions in
`benchmark/scratch/cl-coverage-offshoot/citing_opinions/`:

- **1,148 valid extracted citations, zero docket-only.** The Haiku
  extractor's `citation_string` field never contained a pure docket form.
- **Manual regex sweep across all 82 files: zero docket-only citations
  either.** 53 docket-number references appeared outside the caption
  header, and all 53 were paired with a WL cite (the standard `No. 2:24-
  cv-00563-KJM-DB, 2024 WL 3357004, at *2 (E.D. Cal. July 9, 2024)`
  form). The investigation scripts are at:
  - `scratch/find_docket_only_v2.py` (the working version)
  - `scratch/find_docket_only_cites.py` (an earlier broader attempt)
  - `scratch/check_docket_only.py` (initial spot-check)
  - `scratch/docket_only_v2.csv` (empty result CSV — preserved as
    evidence of the negative finding)
- **The corpus excludes bankruptcy entirely.** Per the manifest at
  `benchmark/scratch/cl-coverage-offshoot/citing_opinions/_manifest.csv`,
  the 82 opinions are 60 federal district (cand / dcd / ilnd / mad / txsd
  — 12 each) plus 22 state opinions (NY App. Div., CA Ct. App., FL DCA,
  IL App. Ct., a few supreme courts). No `bankr` court_id, no `bk`.

### Why bankruptcy is the natural place to look

1. **Mega-case docket volume.** Chapter 11 dockets routinely run to
   thousands of entries; many cited orders never get WL-indexed.
2. **Citation form norm.** Bluebook 10.8.3 and bankruptcy practice
   commonly use `[Docket No. X]` / `[ECF No. X]` cites without any
   Westlaw parallel — much rarer in other federal practice.
3. **Cross-case sister-precedent citation.** Bankruptcy opinions cite
   orders from *other* bankruptcies (first-day orders, cash management,
   DIP financing) far more than civil opinions cite orders from other
   civil cases.

### Suggested test

Mine ~10-15 recent opinions from `deb` (D. Del. Bankr.), `nysb` (S.D.N.Y.
Bankr.), and `txsb` (S.D. Tex. Bankr.) — these three handle most mega-
cases — then run the same docket-reference sweep that
`scratch/find_docket_only_v2.py` runs. Compare docket-only rate to the
existing 0/53 figure from the federal-district sample.

The mining pattern to mirror is in
`benchmark/scratch/cl-coverage-offshoot/10_mine_citing_opinions.py` —
same shape, just swap the `court_id` filter.

### Decisions I'll want to make before you start

- **Scope.** Just the regex sweep (cheapest, ~1 hr) to confirm or refute
  the hypothesis? Or all the way through `/citation-lookup/` + RECAP
  fallback + audit, like the original 5-tier study (~half a day)?
- **Where the output lives.** New offshoot directory, or a sub-study
  inside the existing one?
- **Memo update.** If the hypothesis confirms, do we revise the existing
  memo with a bankruptcy section, or write a separate addendum?

Ask me these before you start mining.
