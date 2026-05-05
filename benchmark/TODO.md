# Benchmark TODO

**Currently working on:** v1.3 — see [`docs/plans/2026-05-05-v1.3-design.md`](docs/plans/2026-05-05-v1.3-design.md). v1.3 work items are tracked in the design doc itself (section progress marks); only **cross-version** or **out-of-scope-of-v1.3** items live here.

For the live state of all versions, see [`ROADMAP.md`](ROADMAP.md).

---

## Mining

### Pool builder drops month/day from cited-case dates — folded into v1.3 mining overhaul

Originally fixed in `benchmark/pilot_a/build_fresh_dc_sample.py` 2026-05-03 (extract_parentheticals now persists month, day, full_citation_text). The same fix needs to land in v1.3's new mining pipeline. The existing `benchmark/releases/v1/_raw_pool.json` predates the fix and is not re-mined since v1 is sealed.

Tracked under v1.3 design §"Mining pipeline (full overhaul)" — bugfix #6.

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

- [`ROADMAP.md`](ROADMAP.md) — full roadmap with v1.x and v2 items
- [`docs/plans/2026-05-05-publication-plan.md`](docs/plans/2026-05-05-publication-plan.md) — publication-track items
