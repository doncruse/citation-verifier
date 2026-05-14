# Limitations — must address before a "real" run

## 25K-char opinion size cap

**Discovered:** 2026-05-13 / 2026-05-14, while building the pilot.

**What we found:** `claude -p` (Claude Code headless mode) hangs indefinitely on extraction prompts where the citing opinion exceeds approximately 30-40K chars. Below this threshold (Wojcicki 23K → 80s, Whole Foods 27K → 58s), extraction completes normally. Above it (Knick 46K, Ram 40K, Lemcke 79K, Obergefell 207K), the subprocess produces zero output and hits whatever wall-clock timeout we set, regardless of:

- Model choice (tried sonnet, then haiku)
- Output volume (tried stripping `sentence_context` from the prompt to reduce output ~70% — no effect)
- Timeout length (tried 240s, 900s — same hang)

**Why we don't fully understand it:** With `claude -p`, the model's actual output is inaccessible to us — we kill the subprocess at timeout without seeing what it was doing. Best guesses: some internal Claude Code wrapping logic stalls on large stdin, or token-count accounting in the wrapper has an edge case at certain prompt sizes. Without instrumentation we can't tell.

**What we did about it:** Capped pilot opinions at 25K chars. This works for the pilot's narrow purpose (testing the extractor and pipeline shape) but is **not acceptable for the real coverage measurement run** because:

1. **Citation density correlates with opinion length.** A 60K-char opinion typically has 60-100 citations; a 20K opinion has 15-25. Capping at 25K shrinks the cited-case pool by roughly 3-5x per citing opinion.
2. **The longest opinions are often the most consequential.** SCOTUS majority opinions with concurrences and dissents (Obergefell-style) get cited heavily but are exactly the ones we'd exclude.
3. **The cap biases toward routine or per-curiam opinions** — different citation patterns than landmark decisions.
4. **State opinion length varies widely.** State COLR opinions especially can be long when discursive (Lemcke at 79K was a routine eyewitness ID case, not unusually elaborate). Capping disproportionately excludes state-tier source opinions.

**What to do for the real run** (must pick one before mining begins):

- **Add ANTHROPIC_API_KEY and use the SDK** (preferred). Eliminates the `claude -p` wrapping issue entirely. ~$20-50 total for 250 opinions at Sonnet pricing.
- **Investigate the `claude -p` cliff.** Run with `claude -p --verbose` to see what's hanging. Possibly file an FLP/Anthropic bug. Higher uncertainty.
- **Chunk long opinions client-side.** Split into ≤25K pieces, extract each, merge. Adds complexity (citation deduplication across chunks, sentence-boundary splitting).
- **Accept the cap as a permanent bias** and prominently disclose. Weakest option methodologically.

The pilot is the worst-case for this limitation — only 5 opinions, so a small change in size constraints shifts results substantially. The real run with ~100 citing opinions will average out somewhat, but the bias direction is fixed: we systematically under-sample citation patterns from longer (typically more impactful) opinions.
