# Pilot A -- Results Summary

**Goal:** Detect whether sampling proposition-citation pairs from LePaRD produces a meaningfully easier benchmark than freshly mining them from post-training-cutoff federal district opinions.

**N (LePaRD):** 50  
**N (fresh D.D.C.):** 50

## Headline numbers (per axis)

| Metric | LePaRD | Fresh D.D.C. | Diff (LP - FD) |
|---|---:|---:|---:|
| % Green (supports proposition) | 48.0% | 16.0% | +32.0pp |
| Hallucination rate (of answered) | 11.8% | 19.2% | -7.5pp |
| Strict 'right case' rate | 12.0% | 6.0% | +6.0pp |
| UNKNOWN rate | 32.0% | 48.0% | -- |

## Bootstrap 95% CI on the difference

- Headline accuracy diff (LePaRD - Fresh): +32.0pp [+14.0, +50.0]
- Hallucination rate diff: -7.5pp [-27.0, +11.1]

## Decision

**Decision: PIVOT TO FRESH MINING.** Fresh-DC scored 32.0pp lower than LePaRD; the contamination concern is validated. The parent spec should mine fresh post-cutoff opinions as its primary data source.

## Coverage finding (independent of contamination outcome)

**Fresh district-court mining at scale is viable on CourtListener,**
provided the search query lifts the default precedential-status filter.

Initial probing for this pilot suggested D.D.C. was the only federal
district with 2026 opinion ingest. That was an artifact of CourtListener's
`/api/rest/v4/search/?type=o` endpoint, which defaults to
`stat_Published=on` only. PACER-flagged district opinions arrive on CL with
`precedential_status=Unknown`, so they are silently filtered out under the
default. Probing with `stat_Published=on&stat_Unknown=on` (verified
2026-04-26):

| District | Default count | + Unknown |
|---|---:|---:|
| C.D. Cal. | 0 | 185 |
| S.D. Tex. | 0 | 357 |
| N.D. Ill. | 0 | 327 |
| D.D.C. | 598 | 598 (unchanged) |

**Implication for the parent spec:** `MINING_PLAYBOOK.md` should specify
`stat_Published=on&stat_Unknown=on` (or document the equivalent for
non-search-API ingest paths). Without it, the playbook silently constrains
forks to ~1 district's worth of fresh data and the contamination story
looks infrastructure-blocked when it isn't.

## Pilot caveats

Documented for the parent design notes:

- **Single citing court (D.D.C.) for the fresh sample.** Pilot ran before
  the precedential-status finding above. Per side discussion: the
  contamination signal works in any docket, so a single-district pilot is
  fine; broaden in the actual benchmark.
- **LePaRD `destination_context` is noisier than expected as a
  proposition source.** A non-trivial fraction of LePaRD propositions are
  fragments of preceding paragraph rather than coherent legal claims.
  Some confused the closed-book model into refusing or flagging the
  prompt as an injection attempt. The parent spec should either
  (a) extract a single clean sentence, or (b) prefer parentheticals
  over preceding-context as the proposition source.
- **Sonnet substance assessor (not Opus).** Plan called for the existing
  /verify-brief Phase 2 Opus assessor; pilot used a single Sonnet call to
  bound cost. Contamination signal should be robust to assessor choice;
  full-benchmark scorecards should use Opus per the parent spec.
- **eyecite parenthetical extraction broke on D.D.C. plain_text** until
  whitespace was aggressively normalized (every line in CL's
  D.D.C. plain_text is `\n\n`-separated, defeating the default tokenizer).
  Filed under known infrastructure issues for the mining playbook.
