# Haiku Pre-Screen for Assessment Subagents

## Context

The `/verify-brief` skill dispatches Opus subagents to read full opinions and assess whether each citation supports its proposition. Long opinions (100K+ chars) are expensive: Ohio Valley took 17 tool uses, 52K tokens, 105 seconds. Off-topic opinions (Dow AgroSciences, Sierra Club) waste the most — Opus reads the whole thing just to confirm it's irrelevant.

## Rejected Approach: Grep Pre-Screen

Built and tested a grep-based pre-screen (`tests/test_prescreen.py`) that extracts term clusters from propositions and greps opinion files. Results across 4 briefs (~188 claims):

- **Zero false skips** (never incorrectly skipped a Green/Yellow)
- **Very low skip rate** (5-6% of Red cases caught)
- Only catches extreme mismatches (completely different legal domain)
- Can't detect directional mismatches (opinion discusses the topic but holds the opposite)

**Conclusion: grep is the wrong tool.** The hard cases aren't about whether a word appears — they're about whether the opinion discusses the concept in a supporting way. That requires comprehension, not pattern matching.

## Proposed Approach: Haiku Reads Every Opinion

Instead of Opus reading full opinions, have Haiku do a quick read and produce a focused summary. Opus then assesses from the summary only.

### Why Haiku beats grep AND Opus-with-grep:

- **2-3 Opus tool calls ≈ 1 Haiku full read** in wall time
- Haiku reading a 100K opinion: ~$0.03, 5-15 seconds
- Opus reading the same opinion: ~$0.50+, 40-105 seconds
- Haiku understands context; grep only matches strings

### Architecture

```
For each opinion file:
  if opinion < 20K chars:
    Opus reads directly (current behavior, fast enough)
  else:
    Haiku reads opinion → structured summary
    Opus assesses from summary + key excerpts
```

### Haiku Summary Format (tested on Ohio Valley)

```
CASE SUMMARY:
[1-2 sentences: what this case is actually about]

KEY HOLDINGS:
[Bullet list of actual holdings]

RELEVANT PASSAGES (for the topics being assessed):
[Quote actual text with page numbers]

TOPICS NOT FOUND:
[List topics from the propositions that aren't discussed anywhere]
```

### Prototype Results (Ohio Valley, 169K chars)

- Haiku summary: 12 tool uses, 30K tokens, 72 seconds (reading in chunks via Read tool)
- Correctly identified all 4 proposition topics as unsupported
- Correctly found the relevant passage at page 201 and noted it says the *opposite* of what the brief claims
- Summary was sufficient for assessment without reading the full opinion

### What Needs Testing

1. **Accuracy**: Does Haiku's summary preserve enough detail for Opus to correctly assess Green/Yellow/Red? Test against all ground-truth assessments across 3 briefs.
2. **Failure modes**: Does Haiku ever miss a relevant passage that would change the assessment?
3. **Cost/speed**: Measure actual Haiku token usage and wall time across different opinion sizes.
4. **Threshold**: Is 20K the right cutoff, or should Haiku summarize everything?

### Test Plan

Run Haiku summaries for all opinions across the 3 briefs with ground truth (Fivehouse, Kettering, Valve v. Rothschild). For each:
1. Haiku reads opinion, produces summary focused on the propositions citing that opinion
2. Compare summary to known assessment — would it lead to the same Green/Yellow/Red?
3. Flag any cases where the summary is missing information that would change the assessment

### Ground Truth Data

| Brief | Claims | Opinions | Assessments |
|-------|--------|----------|-------------|
| Fivehouse v. DOD | 13 | 5 | 4G, 2Y, 7R |
| Kettering v. Collier | 28 | 17 | 12G, 2Y, 10R (+ 4 skip) |
| Valve v. Rothschild | 53 | 23 | 18G, 16Y, 19R |

Files:
- `briefs/<name>/claims.csv` — ground truth assessments in `assessment` column
- `briefs/<name>/opinions/` — downloaded opinion files
- `tests/test_prescreen.py` — grep approach (can be repurposed or deleted)
