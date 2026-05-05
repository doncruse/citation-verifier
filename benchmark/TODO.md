# Benchmark TODO

## Mining

### ~~Pool builder drops month/day from cited-case dates~~ FIXED 2026-05-03
`extract_parentheticals()` in `benchmark/pilot_a/build_fresh_dc_sample.py` (also used by `benchmark/runners/build_dataset.py`) was persisting only `meta.year`, dropping `meta.month` and `meta.day` that eyecite already extracts. Now persists `month`, `day`, plus a new `full_citation_text` field (eyecite `c.full_span()` slice — case name + reporter + court + date + parenthetical) so downstream consumers can re-parse if eyecite metadata extraction drops a field in the future. Existing `benchmark/releases/v1/_raw_pool.json` predates the fix; re-mine to backfill.

Discovered via `_all_cl_misses.csv` analysis: only `year` was available for cited cases, so date filtering in the verifier was year-wide and the misses CSV had no full-date column for the cited case. Relevant for the v1.1 "real-but-CL-missed" audit since narrower date filters should reduce miscoded misses.

## Code cleanup

### Extract shared hermetic-CLI helper for `claude -p` callers

Three runners independently maintain their own workaround for the
`claude -p` + `CLAUDE.md` role-confusion leak:

- `pilot_a/score.py` — `_HERMETIC_DIR = tempfile.mkdtemp(prefix="pilot_a_score_")`, used as `cwd=` in `subprocess.run(["claude", "-p", ...])`
- `runners/model_adapter.py` — same pattern, `prefix="benchmark_v1_"`
- `runners/red_audit_fulltext.py` — variant that pipes prompt via stdin instead of CLI args, to avoid Windows `CreateProcess` arg-length limits

DRY these into a shared `runners/_hermetic.py` (or similar) exporting
something like `invoke_claude_cli(prompt, model, timeout, ...)` that
handles hermetic cwd + stdin piping uniformly. Update the three call
sites.

This is a behavior-touching cleanup, not just a move — split out from
the 2026-05-05 consolidation refactor. Touch it after the consolidation
lands so the three call sites are at predictable paths.

### Audit cache fallback list semantics in `red_audit_fulltext.py` and `score_gold_pairs_fulltext.py`

The `OPINION_CACHE_DIRS` fallback lists in these scripts now mix two
semantically distinct cache types: `cited_opinion_cache` (cited-case text)
and `citing_opinion_cache` (citing-court text). The 2026-05-05 cache
rename was a faithful mechanical translation of pre-existing paths, but
the original mix of cited+citing in one fallback list may itself have
been a bug. Audit whether each fallback entry is actually used and makes
sense for the calling script.

## See also

- [`docs/plans/benchmark-roadmap.md`](docs/plans/benchmark-roadmap.md) — full roadmap with v1.x and v2 items
- [`docs/plans/2026-05-05-publication-plan.md`](docs/plans/2026-05-05-publication-plan.md) — publication-track items
