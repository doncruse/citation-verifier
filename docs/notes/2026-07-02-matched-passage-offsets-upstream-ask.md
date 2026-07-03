# Upstream ask: persist matched-passage locations for verified quotes

**Date:** 2026-07-02
**From:** us-legal-research-frontend (Cabinet) / import-memo consumers
**Status:** Draft ask — not yet triaged
**Sibling:** `us-legal-research-frontend/docs/superpowers/2026-07-02-passage-jump-note.md`
(the feature this enables)

## The ask

`verify_quote` (`src/citation_verifier/quote_matcher.py`) already computes the
matched span — `QuoteMatch` carries `matched_passage`, `similarity`, `was_ocrd`.
That data currently informs the lane/quote-floor verdict and is dropped. The ask:
persist **where** the match landed, so downstream readers can deep-link into the
opinion text:

1. Per verified/close quote, record the matched passage's **character offsets into
   the opinion text as filed** (the `opinions/` copy the pipeline downloaded), or at
   minimum the matched span text as a search anchor.
2. Surface it in `findings.json` per claim (e.g.
   `quote_matches: [{quote, result, similarity, opinion_file, start, end}]`) —
   and/or as anchors the memo-import step can carry into the filed opinion files.

## Consumer

The Cabinet renders imported memos with ✓/~ quote markers; with offsets it can make
those spans clickable — opinion panel opens scrolled to the highlighted passage
(donna-style grounding UX). Without offsets it can only re-run fuzzy matching
client-side, duplicating this repo's matcher (including the OCR-normalization rules,
which are a locked cross-repo contract — duplicating them would fork that).

## Notes for triage

- Offsets are against the filed opinion text at verification time; if the opinion is
  re-fetched, offsets can drift — consumers are expected to fall back to
  text-search on the anchor span. So the anchor text matters more than the ints.
- Natural home once accepted: add to `docs/consumer-surface-manifest.md` and the
  `findings.json` section of the report contract; bump whatever version governs
  `findings.json` consumers.
- No behavior change to lanes/scoring — this is pass-through of data already
  computed.
