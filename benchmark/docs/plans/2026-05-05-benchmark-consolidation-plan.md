# Benchmark Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all benchmark-related files in citation-verifier into a single top-level `benchmark/` directory, so the project has one coherent home and the eventual spinout becomes a `git mv benchmark/ ../new-repo/` operation rather than a hunt-and-gather across the repo.

**Architecture:** Single `benchmark/` directory containing five sub-areas — `releases/` (frozen per-version artifacts), `runners/` (latest runner code + tests, evolves across versions), `pilot_a/` (predecessor pilot code + data, frozen), `gold_db/` (cumulative SQLite + migrations + exports), `docs/` (plans + retrospectives), plus a `scratch/` and `TODO.md` at the benchmark level. The `gold_db.py` Python module stays under `src/citation_verifier/` per prior decision (importable from the verifier package); only the SQLite file and schema move under `benchmark/gold_db/`. Renames done with `git mv` to preserve history. Each task ends with a commit; tests run after every move that touches importable code.

**Tech Stack:** No new dependencies. Existing: Python 3.10+, pytest, sqlite3 stdlib. Refactor only — zero functional changes to mining, scoring, or assessor logic.

**Environment:** Windows + Git Bash. Python is `venv/Scripts/python.exe`. No `head`/`tail`/`grep` available — use Python or dedicated tools. `git mv` works fine in Git Bash.

**Spinout note:** This refactor is internal consolidation, NOT spinout. Per [`benchmark-spinout-prep.md`](benchmark-spinout-prep.md), three of four spinout criteria (forkable kit, ≥2-3 forkers, clean release story) are still unmet. Spinout deferred until v1.2 / publication track land.

---

## Target structure

```
benchmark/
├── README.md                       # NEW — orientation: where to find what + how to reproduce v1
├── TODO.md                         # NEW — benchmark-only TODOs (extracted from scratch/TODO.md)
├── docs/
│   ├── plans/                      # 11 files (was docs/plans/{benchmark,pilot,gold-db,publication}*.md)
│   └── retrospectives/             # 3 files (was docs/retrospectives/*calibration*, *truncation*, *fulltext-assessor*)
├── runners/                        # was benchmark/runners/
│   ├── __init__.py
│   ├── build_dataset.py
│   ├── run_model.py
│   ├── score.py
│   ├── score_gold_pairs.py
│   ├── score_gold_pairs_fulltext.py
│   ├── red_audit_fulltext.py
│   ├── scorecard.py
│   ├── calibrate_assessor.py
│   ├── calibrate_assessor_report.py
│   ├── _migrate_calibration_csv.py
│   ├── truncation_experiment.py
│   ├── model_adapter.py
│   ├── backfill_gold_db.py
│   └── tests/
│       ├── __init__.py
│       ├── test_backfill.py
│       ├── test_build_cache_wiring.py
│       ├── test_model_adapter.py
│       ├── test_score_gold_pairs.py
│       ├── test_score_integration.py
│       └── test_scorecard.py
├── pilot_a/                        # was benchmark/pilot_a/ (code) + benchmark/pilot_a/ (data)
│   ├── __init__.py
│   ├── build_fresh_dc_sample.py
│   ├── build_lepard_sample.py
│   ├── run_model.py
│   ├── score.py
│   ├── summarize.py
│   ├── fresh_dc_parens_raw.json
│   ├── fresh_dc_sample.csv
│   ├── lepard_sample.csv
│   ├── model_outputs.csv
│   ├── results.csv
│   ├── summary.md
│   ├── _opinion_cache/              # gitignored (was benchmark/pilot_a/cited_opinion_cache/)
│   ├── _dcd_opinion_cache/          # gitignored (was benchmark/pilot_a/dcd_citing_opinion_cache/)
│   ├── _*.txt                       # gitignored (was benchmark/pilot_a/_*.txt)
│   └── _smoke_*.csv                 # gitignored (was benchmark/pilot_a/_smoke_*.csv)
├── gold_db/                        # was gold_db/ at repo root
│   ├── README.md
│   ├── gold.db
│   ├── migrations/
│   │   └── 001_initial.sql
│   └── exports/
│       └── *.csv
├── releases/
│   └── v1/                         # was benchmark/releases/v1/
│       ├── README.md
│       ├── dataset.csv
│       ├── _raw_pool.json
│       ├── results.csv
│       ├── outputs_*.csv
│       ├── scorecards.md
│       ├── scorecards-deduped.md
│       ├── calibration.md
│       ├── calibration_results*.csv
│       ├── truncation_experiment.md
│       ├── truncation_experiment_60k.csv
│       ├── courtlistener-findings.html
│       ├── report.html
│       ├── _all_cl_misses*.csv
│       ├── _audit_smoke_*.csv
│       ├── _build_smoke.txt
│       ├── _calibration_fillin_log.txt  # already gitignored
│       ├── _opinion_cache/              # gitignored
│       └── (other diagnostic files)
└── scratch/                        # benchmark-specific scratch (was scratch/*red*, *score_fulltext*, *score_gold_pairs*, find_red_context, join_misses, red_context, red_audit_input)
    ├── find_red_context.py
    ├── join_misses_citation_court.py
    ├── red_context.md
    ├── red_audit_input.txt
    ├── red_audit_sonnet.log
    ├── red_audit_sonnet_fulltext.log
    ├── red_audit_sonnet_fulltext_v2.log
    ├── score_fulltext_haiku.log
    ├── score_fulltext_sonnet.log
    ├── score_gold_pairs.log
    └── score_validation.log
```

**What does NOT move:**
- `src/citation_verifier/gold_db.py` — stays put per prior decision (reusable infrastructure, importable from `citation_verifier` package). Only its `SCHEMA_PATH` constant updates.
- `tests/test_gold_db.py` — stays put (unit test of `citation_verifier.gold_db` module, lives with other top-level tests).
- All non-benchmark docs in `docs/plans/` and `docs/retrospectives/` (verify-brief, etc.).
- All non-benchmark scratch items (`citations_for_review.csv`, `flp_contributions.md`, etc.).
- `scratch/TODO.md` — keeps everything except the "Benchmark Mining" section.
- `CLAUDE.md` — modified, not moved (gets a benchmark-orientation pointer).

---

## Conventions

- **Use `git mv` for tracked files** to preserve history. Untracked items (gitignored caches, logs) move via OS `mv`.
- **One commit per task** so we can bisect later if something breaks.
- **Run pytest after each task that moves importable code** — the bar is "no NEW failures introduced by this task." Pre-existing failures (live_api tests, etc.) are fine.
- **Never run `git add -A` or `git add .`** — stage specific files. The repo has uncommitted untracked items (e.g. `tests/ab_test_single.json`) that aren't part of this refactor.
- **Path updates use Edit tool** (not sed). Each path change is reviewed.
- **No new tests written.** This is a pure refactor; existing tests are the verification mechanism.
- **Use the `Edit` tool's `replace_all=True`** carefully — only when the old path appears verbatim and only as a path. For mixed contexts (paths in markdown prose), use targeted edits.

---

## Pre-flight: stash uncommitted work

The working tree currently has 3 modified tracked files and 3 untracked items unrelated to this refactor that we don't want sweeping into commits:

- `M .claude/settings.json` — leave alone
- `M scratch/TODO.md` — keep as-is (will be touched by Task 9)
- `M benchmark/pilot_a/build_fresh_dc_sample.py` — already part of pilot_a, will move with it (Task 4)
- `?? .claude/scheduled_tasks.lock` — gitignored junk, leave
- `?? .claude/skills/pdf-processing-anthropic/` — leave
- `?? .claude/worktrees/` — leave
- `?? benchmark/releases/v1/_all_cl_misses_with_citation_court.csv` — needs to move with benchmark/releases/v1/ (Task 3)
- `?? scratch/join_misses_citation_court.py` — needs to move with scratch benchmark items (Task 6)
- `?? tests/ab_test_single.json` — verify-brief AB testing, NOT this refactor — leave alone

- [ ] **Step 0.1: Confirm baseline test status**

```bash
venv/Scripts/python.exe -m pytest tests/ -v --tb=no -q 2>&1 | tail -20
```

Record the count of passing / failing / skipped tests. This is the baseline. Subsequent task verifications must match (or improve).

- [ ] **Step 0.2: Confirm we're on `main`, up to date with origin**

```bash
git fetch origin && git status -sb
```

Expected: `## main...origin/main` (no `[ahead N]` or `[behind N]`).

---

## Task 1: Create `benchmark/` skeleton

**Goal:** Set up the empty directory structure and a placeholder README so subsequent tasks have a target. Trivial commit, no functional impact.

**Files:**
- Create: `benchmark/README.md`
- Create: `benchmark/__init__.py` (empty)
- Create: `benchmark/runners/__init__.py` (empty)
- Create: `benchmark/runners/tests/__init__.py` (empty)
- Create: `benchmark/pilot_a/__init__.py` (empty)
- Create: `benchmark/docs/plans/.gitkeep`
- Create: `benchmark/docs/retrospectives/.gitkeep`
- Create: `benchmark/releases/v1/.gitkeep`
- Create: `benchmark/scratch/.gitkeep`

- [ ] **Step 1.1: Create empty `__init__.py` files**

```bash
mkdir -p benchmark/runners/tests benchmark/pilot_a benchmark/docs/plans benchmark/docs/retrospectives benchmark/releases/v1 benchmark/scratch benchmark/gold_db
```

Then write each `__init__.py` (empty file via `Write`):

- `benchmark/__init__.py`
- `benchmark/runners/__init__.py`
- `benchmark/runners/tests/__init__.py`
- `benchmark/pilot_a/__init__.py`

- [ ] **Step 1.2: Create `.gitkeep` files for empty leaf directories**

For each of these (touch — empty file via `Write` with empty content):
- `benchmark/docs/plans/.gitkeep`
- `benchmark/docs/retrospectives/.gitkeep`
- `benchmark/releases/v1/.gitkeep`
- `benchmark/scratch/.gitkeep`

- [ ] **Step 1.3: Write `benchmark/README.md`**

```markdown
# Case Law Retrieval Benchmark

A 3-axis benchmark for evaluating legal research AI on the task of finding cases that
support a given proposition. Source data: parentheticals mined from recent legal
opinions, yielding (proposition, case) pairs. Models attempt to find a supporting case
for each proposition; an assessor judges whether the returned case actually supports
the proposition.

## Where to find what

| Path | Purpose |
|------|---------|
| `releases/v1/` | Frozen v1 artifacts (dataset, model outputs, scorecards, calibration, truncation experiment, audit CSVs) — the publishable v1 deliverable |
| `runners/` | Runner code that built v1 and will build v2 (build_dataset, run_model, score, scorecard, calibrate_assessor, etc.) plus their unit tests |
| `pilot_a/` | Predecessor pilot — code + data + summary. Frozen; superseded by v1 but preserved for the methodology trail |
| `gold_db/` | Cumulative SQLite knowledge corpus (`gold.db`), schema migrations, CSV exports. The Python module that drives this lives at `src/citation_verifier/gold_db.py` |
| `docs/plans/` | Design docs, implementation plans, roadmap, publication plan |
| `docs/retrospectives/` | Run retrospectives — what we learned from each major pass |
| `scratch/` | One-off scripts and logs from benchmark work |
| `TODO.md` | Benchmark-only TODOs (separate from the citation-verifier `scratch/TODO.md`) |

## Status (as of 2026-05-05)

- v1 shipped May 2026 — see [`releases/v1/README.md`](releases/v1/README.md)
- v1.1 validation studies done (calibration + truncation experiment)
- v1.2 methodology hardening — gold-DB infrastructure landed
- v1.3, v1.4 — additional analyses on v1's 130-prop dataset (truncation re-test, parenthetical-mis-attribution audit, etc.). Artifacts go in `releases/v1/`; runner code evolves in `runners/` in place
- v2 in design — when v2 mining produces a fresh dataset, it lands in `releases/v2/`. See [`docs/plans/2026-05-05-publication-plan.md`](docs/plans/2026-05-05-publication-plan.md) and [`../../ROADMAP.md`](../../ROADMAP.md)

## Convention: per-version vs evolving

- `releases/vN/` — **frozen artifacts per dataset version.** v1.x iterations
  (additional scoring passes, audits, calibration studies) write into
  `releases/v1/` because they're additive analyses on the same 130-prop
  dataset. To reproduce a specific point-in-time view, `git checkout` the
  matching tag.
- `runners/` — **evolves in place.** No `runners/v1/` vs `runners/v2/` split;
  scripts get bumped as we learn. When v2 mining lands and the runner code
  diverges enough to make in-place evolution awkward, we'll consider
  branching, but not before.

## Opinion caches — naming convention

Two roles, named explicitly so it's never ambiguous which one a script
should read:

| Path | Holds | Used by |
|---|---|---|
| `pilot_a/cited_opinion_cache/` | Cited-case opinion text (e.g. Smith v Jones's text when a parenthetical cites Smith v Jones) | `pilot_a/score.py`, `runners/calibrate_assessor.py`, `runners/red_audit_fulltext.py` (cached read), `runners/score_gold_pairs.py` (transitively) |
| `pilot_a/dcd_citing_opinion_cache/` | Citing-court opinion text (D.D.C. opinions that pilot mined parentheticals FROM) | `pilot_a/build_fresh_dc_sample.py`, `runners/build_dataset.py` (fallback) |
| `releases/v1/citing_opinion_cache/` | Citing-court opinion text for v1's 5 districts | `runners/build_dataset.py` (primary) |

**Rule of thumb:** if you're writing a script that needs the text of a
case named in a parenthetical, you want `cited_opinion_cache`. If you're
mining parentheticals OUT of an opinion, you want `citing_opinion_cache`.

## Calling `claude -p` from runners — bypass CLAUDE.md

Any benchmark script that invokes `claude -p` (the Claude Code CLI in
non-interactive mode) needs to **bypass the repo's `CLAUDE.md`** —
otherwise the project context leaks into the prompt and biases assessor
or model-under-test responses.

Two scripts already do this independently:

- [`pilot_a/score.py`](pilot_a/score.py) line ~34 —
  `_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="pilot_a_score_"))`,
  used as `cwd=_HERMETIC_DIR` in the `subprocess.run(["claude", "-p", ...])` call.
- [`runners/model_adapter.py`](runners/model_adapter.py) line ~31 —
  `_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="benchmark_v1_"))`, same idea.

When adding a new runner that calls `claude -p`, follow the same pattern.
**Planned follow-up:** extract a shared `hermetic_cwd()` helper so the
three current call sites (the two above plus `red_audit_fulltext.py`'s
own variant) DRY up. Tracked in [`TODO.md`](TODO.md).

## Reproducing v1

See [`releases/v1/README.md`](releases/v1/README.md) for the full reproduce instructions. Quick form:

```bash
venv/Scripts/python.exe -m benchmark.runners.build_dataset
venv/Scripts/python.exe -m benchmark.runners.run_model --model sonnet
venv/Scripts/python.exe -m benchmark.runners.run_model --model opus
venv/Scripts/python.exe -m benchmark.runners.run_model --model gpt-5
venv/Scripts/python.exe -m benchmark.runners.score
venv/Scripts/python.exe -m benchmark.runners.scorecard --dedupe
```

## Spinout status

Internal consolidation only — citation-verifier benchmark code lives here today, but the package depends on `citation_verifier` internals. Eventual standalone-repo spinout is gated on v1.2 forkable kit + publication track + ≥2-3 external forkers. See [`docs/plans/benchmark-spinout-prep.md`](docs/plans/benchmark-spinout-prep.md).
```

- [ ] **Step 1.4: Stage and commit the skeleton**

```bash
git add benchmark/
git commit -m "benchmark: create top-level directory skeleton + README

Empty placeholder structure. Subsequent commits move existing
benchmark/releases/v1/, gold_db/, benchmark/runners/, benchmark/pilot_a/,
benchmark/pilot_a/, and benchmark docs into this tree.

See docs/plans/2026-05-05-benchmark-consolidation-plan.md."
```

- [ ] **Step 1.5: Verify commit landed**

```bash
git log -1 --stat
```

Expected: lists `benchmark/__init__.py`, `benchmark/README.md`, etc.

---

## Task 2: Move `gold_db/` → `benchmark/gold_db/`

**Goal:** Move the SQLite file, migrations, exports, and README into the new location. Update the one Python constant that hardcodes the path.

**Files:**
- Move (git mv): `gold_db/README.md` → `benchmark/gold_db/README.md`
- Move (git mv): `benchmark/gold_db/gold.db` → `benchmark/benchmark/gold_db/gold.db`
- Move (git mv): `benchmark/gold_db/migrations/001_initial.sql` → `benchmark/benchmark/gold_db/migrations/001_initial.sql`
- Move (git mv): `benchmark/gold_db/exports/*.csv` (7 files) → `benchmark/benchmark/gold_db/exports/`
- Modify: `src/citation_verifier/gold_db.py` (line 21 — `SCHEMA_PATH`)
- Modify: `benchmark/gold_db/README.md` (path examples in sqlite3 commands)

- [ ] **Step 2.1: Move files via `git mv`**

```bash
git mv gold_db/README.md benchmark/gold_db/README.md
git mv benchmark/gold_db/gold.db benchmark/benchmark/gold_db/gold.db
mkdir -p benchmark/benchmark/gold_db/migrations benchmark/benchmark/gold_db/exports
git mv benchmark/gold_db/migrations/001_initial.sql benchmark/benchmark/gold_db/migrations/001_initial.sql
git mv benchmark/gold_db/exports/assessor_verdicts.csv benchmark/benchmark/gold_db/exports/assessor_verdicts.csv
git mv benchmark/gold_db/exports/cases.csv benchmark/benchmark/gold_db/exports/cases.csv
git mv benchmark/gold_db/exports/citation_rows.csv benchmark/benchmark/gold_db/exports/citation_rows.csv
git mv benchmark/gold_db/exports/datasets.csv benchmark/benchmark/gold_db/exports/datasets.csv
git mv benchmark/gold_db/exports/model_answers.csv benchmark/benchmark/gold_db/exports/model_answers.csv
git mv benchmark/gold_db/exports/propositions.csv benchmark/benchmark/gold_db/exports/propositions.csv
git mv benchmark/gold_db/exports/runs.csv benchmark/benchmark/gold_db/exports/runs.csv
```

Verify the source `gold_db/` directory is now empty:

```bash
ls gold_db/ 2>/dev/null
```

Expected: empty (or "No such file or directory" — git removes empty dirs).

- [ ] **Step 2.2: Update `SCHEMA_PATH` in `src/citation_verifier/gold_db.py`**

Edit `src/citation_verifier/gold_db.py` line 21:

Old:
```python
SCHEMA_PATH = REPO_ROOT / "gold_db" / "migrations" / "001_initial.sql"
```

New:
```python
SCHEMA_PATH = REPO_ROOT / "benchmark" / "gold_db" / "migrations" / "001_initial.sql"
```

- [ ] **Step 2.3: Update path examples in `benchmark/gold_db/README.md`**

Find every `sqlite3 benchmark/gold_db/gold.db` and replace with `sqlite3 benchmark/benchmark/gold_db/gold.db`. Same for `benchmark/gold_db/exports`.

Specifically, in `benchmark/gold_db/README.md`:
- `sqlite3 benchmark/gold_db/gold.db "..."` (3 occurrences) → `sqlite3 benchmark/benchmark/gold_db/gold.db "..."`
- `GoldDB('benchmark/gold_db/gold.db').export_csvs('benchmark/gold_db/exports')` → `GoldDB('benchmark/benchmark/gold_db/gold.db').export_csvs('benchmark/benchmark/gold_db/exports')`
- `benchmark/gold_db/exports/` (in prose) → `benchmark/benchmark/gold_db/exports/`
- `benchmark/runners/score.py` (in §Score.py invocation) → `benchmark/runners/score.py` AND `python benchmark/runners/score.py` → `python -m benchmark.runners.score` (account for the import-path change in Task 5)

- [ ] **Step 2.4: Run gold-db tests to verify SCHEMA_PATH update works**

```bash
venv/Scripts/python.exe -m pytest tests/test_gold_db.py -v
```

Expected: PASS (same as baseline). The test creates a fresh DB at tmp_path and applies SCHEMA_PATH — if the schema file is missing or unreachable, this fails immediately.

- [ ] **Step 2.5: Smoke-check gold.db is still readable from new location**

```bash
venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('benchmark/benchmark/gold_db/gold.db')
n = conn.execute('SELECT COUNT(*) FROM assessor_verdicts').fetchone()[0]
print(f'verdicts: {n}')
"
```

Expected: prints `verdicts: 814` (or current value — should match the README's "as of 2026-05-04" count of ≥814).

- [ ] **Step 2.6: Commit**

```bash
git add benchmark/gold_db/ src/citation_verifier/gold_db.py
git commit -m "benchmark: move gold_db/ → benchmark/gold_db/

Updates SCHEMA_PATH in citation_verifier.gold_db and the path examples
in gold_db/README.md. The gold_db.py module itself stays at
src/citation_verifier/ — only the SQLite file, migrations, exports,
and README move."
```

---

## Task 3: Move `benchmark/releases/v1/` → `benchmark/releases/v1/`

**Goal:** Move v1 release artifacts. Update gitignore, update path references in committed runner scripts (still under `benchmark/runners/` at this point — we'll move them in Task 5).

**Files affected:**
- Move (git mv): all tracked files in `benchmark/releases/v1/` (~30 files)
- Move (fs mv): `benchmark/releases/v1/citing_opinion_cache/` (gitignored, regenerable but expensive to re-fetch)
- Move (fs mv): any `benchmark/releases/v1/_*.txt` log files (gitignored)
- Modify: `.gitignore` (paths)
- Modify: `benchmark/runners/build_dataset.py` (paths)
- Modify: `benchmark/runners/run_model.py` (paths)
- Modify: `benchmark/runners/score.py` (paths)
- Modify: `benchmark/runners/scorecard.py` (paths)
- Modify: `benchmark/runners/calibrate_assessor.py` (paths + docstring)
- Modify: `benchmark/runners/calibrate_assessor_report.py` (paths + comment)
- Modify: `benchmark/runners/red_audit_fulltext.py` (paths)
- Modify: `benchmark/runners/backfill_gold_db.py` (CLI defaults)
- Modify: `benchmark/runners/test_backfill.py` (no path update needed — uses tmp_path/"benchmark_v1" which is just a fixture name)

- [ ] **Step 3.1: Move untracked file (uncommitted CSV) into the new location**

```bash
mkdir -p benchmark/releases/v1
mv benchmark/releases/v1/_all_cl_misses_with_citation_court.csv benchmark/releases/v1/_all_cl_misses_with_citation_court.csv
```

- [ ] **Step 3.2: Move tracked files via `git mv`**

The `.gitkeep` placeholder in `benchmark/releases/v1/` was created in Task 1 — remove it first:

```bash
git rm benchmark/releases/v1/.gitkeep
```

Then move all v1 files. Use a Python one-liner to enumerate tracked files and `git mv` each:

```bash
venv/Scripts/python.exe -c "
import subprocess
out = subprocess.check_output(['git', 'ls-files', 'benchmark/releases/v1/'], text=True)
for f in out.strip().split('\n'):
    if not f:
        continue
    new = f.replace('benchmark/releases/v1/', 'benchmark/releases/v1/', 1)
    subprocess.check_call(['git', 'mv', f, new])
"
```

Expected: ~28-30 files moved. Verify with:

```bash
git status -s | grep -c "^R"
```

Should print a count matching the move count.

- [ ] **Step 3.3: Move gitignored caches and logs via filesystem `mv` — and rename the cache for clarity**

The cache `benchmark/releases/v1/citing_opinion_cache/` holds **citing-court** opinions (the courts that did the citing — these are what we mine parentheticals from). Renaming to `citing_opinion_cache/` distinguishes it from pilot_a's CITED-opinions cache. Past sessions hit this confusion twice ("wait, which cache?").

```bash
# Opinion cache (regenerable but costly to re-fetch) — also renamed for clarity
[ -d benchmark/releases/v1/citing_opinion_cache ] && mv benchmark/releases/v1/citing_opinion_cache benchmark/releases/v1/citing_opinion_cache

# Any remaining log files (gitignored)
for f in benchmark/releases/v1/_*.txt; do
  [ -f "$f" ] && mv "$f" "benchmark/releases/v1/$(basename "$f")"
done
```

Verify `benchmark/releases/v1/` is empty:

```bash
ls benchmark/releases/v1/ 2>/dev/null
```

Expected: empty or "No such file or directory."

- [ ] **Step 3.4: Update `.gitignore`**

Edit `.gitignore`:

Old:
```
# Benchmark v1 — opinion-text caches (regenerable)
benchmark/releases/v1/citing_opinion_cache/

# Benchmark v1 — chatty run logs (regenerable; keep CSVs and markdown)
benchmark/releases/v1/_*.txt
```

New:
```
# Benchmark v1 — citing-court opinion cache (regenerable)
benchmark/releases/v1/citing_opinion_cache/

# Benchmark v1 — chatty run logs (regenerable; keep CSVs and markdown)
benchmark/releases/v1/_*.txt
```

- [ ] **Step 3.5: Update `benchmark/runners/build_dataset.py` paths**

Edit lines 43-46:

Old:
```python
OUT = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
OPINION_TEXT_CACHE = PROJECT_ROOT / "benchmark_v1" / "_opinion_cache"
RAW_POOL = PROJECT_ROOT / "benchmark_v1" / "_raw_pool.json"
GOLD_DB_PATH = PROJECT_ROOT / "gold_db" / "gold.db"
```

New:
```python
OUT = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "dataset.csv"
OPINION_TEXT_CACHE = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "citing_opinion_cache"
RAW_POOL = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "_raw_pool.json"
GOLD_DB_PATH = PROJECT_ROOT / "benchmark" / "gold_db" / "gold.db"
```

(Note: cache rename `_opinion_cache` → `citing_opinion_cache`. This is the **citing-court** opinion cache. The variable name `OPINION_TEXT_CACHE` could also be renamed to `CITING_OPINION_TEXT_CACHE` for clarity if grep shows few callers — verify with `git grep -n OPINION_TEXT_CACHE benchmark/runners/`.)

- [ ] **Step 3.6: Update `benchmark/runners/run_model.py` paths**

Edit lines 19, 31, 34:

Old:
```python
DATASET = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
```

New:
```python
DATASET = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "dataset.csv"
```

Old:
```python
                    help="output CSV; defaults to benchmark/releases/v1/outputs_{model}.csv")
```

New:
```python
                    help="output CSV; defaults to benchmark/releases/v1/outputs_{model}.csv")
```

Old:
```python
    out = args.out or PROJECT_ROOT / "benchmark_v1" / f"outputs_{args.model.replace('-', '')}.csv"
```

New:
```python
    out = args.out or PROJECT_ROOT / "benchmark" / "releases" / "v1" / f"outputs_{args.model.replace('-', '')}.csv"
```

- [ ] **Step 3.7: Update `benchmark/runners/score.py`, `scorecard.py`, `calibrate_assessor*.py`, `red_audit_fulltext.py`, `backfill_gold_db.py` paths**

Apply the same pattern (`benchmark_v1` → `benchmark/releases/v1`, `benchmark/gold_db/gold.db` → `benchmark/benchmark/gold_db/gold.db`) in each file. Specific line numbers:

- `scorecard.py` lines 19-22 (RESULTS, DATASET, OUT, OUT_DEDUPED)
- `calibrate_assessor.py` line 55 (`BENCH = PROJECT_ROOT / "benchmark_v1"`) and lines 8-13, 17 in the docstring (paths in the usage example)
- `calibrate_assessor_report.py` line 30 (`BENCH = PROJECT_ROOT / "benchmark_v1"`) and line 205 (the "Generated by `benchmark/runners/calibrate_assessor_report.py`" string — update to `benchmark/runners/calibrate_assessor_report.py` since that's where it lands after Task 5)
- `red_audit_fulltext.py` line 149 only (`--db-path` default `benchmark/gold_db/gold.db` → `benchmark/benchmark/gold_db/gold.db`). Lines 30-31 are a 2-line array of opinion-cache paths AND need rename `_opinion_cache` → `citing_opinion_cache` and `opinion_cache` → `cited_opinion_cache` (see Task 4) — defer the whole array to Task 4 step 4.4 so the edit is atomic. Line 38 (`PROJECT_ROOT / "tests" / "pilot_a" / "score.py"`) — defer to Task 4. Line 11 (docstring `benchmark.runners.red_audit_fulltext`) — defer to Task 5.

- `calibrate_assessor.py` lines 57-58 (the comment block describing what `OPINION_CACHE` and `_opinion_cache` hold — verify the comment text references `benchmark/releases/v1/citing_opinion_cache` and update to `benchmark/releases/v1/citing_opinion_cache`).
- `backfill_gold_db.py` line 390 (`--bench-dir default="benchmark_v1"` → `--bench-dir default="benchmark/releases/v1"`) and line 391 (`--db-path default="benchmark/gold_db/gold.db"` → `--db-path default="benchmark/benchmark/gold_db/gold.db"`)
- `score.py` — has imports (Task 5) but no benchmark/releases/v1/ paths beyond what `model_adapter` etc. handle. Confirm by grep and skip if none.

For each: use Edit with the old/new strings shown above.

- [ ] **Step 3.8: Run tests to verify path updates work**

```bash
venv/Scripts/python.exe -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

Expected: same pass/fail count as baseline (pre-existing live_api skips OK; no new failures).

If tests fail with paths like `benchmark/runners/...benchmark/releases/v1/...` — likely a missed path. Grep for `"benchmark_v1"` (with quotes, indicating string literal) and re-check:

```bash
venv/Scripts/python.exe -c "
import subprocess
out = subprocess.check_output(['git', 'grep', '-l', 'benchmark_v1'], text=True, cwd='.')
print(out)
"
```

Note: hits inside `benchmark/runners/` directory NAMES are expected (the directory name change happens in Task 5). Hits inside file CONTENTS that aren't covered above are bugs.

- [ ] **Step 3.9: Commit**

```bash
git add -u  # stages all the renames AND the path-update edits
git add benchmark/releases/v1/_all_cl_misses_with_citation_court.csv  # the previously-untracked file
git add .gitignore
git commit -m "benchmark: move benchmark/releases/v1/ → benchmark/releases/v1/

Renames the 28-file release artifact directory and updates path
references in benchmark/runners/ runner scripts. Caches and log
files (gitignored) moved via filesystem mv.

Runner scripts still live at benchmark/runners/ at this point
(they move in Task 5); only their internal paths are updated."
```

---

## Task 4: Move `benchmark/pilot_a/` + `benchmark/pilot_a/` → `benchmark/pilot_a/`

**Goal:** Combine pilot_a code (was under tests/) and pilot_a artifacts (was under scratch/) into one location. This is a frozen pilot — code stays runnable but not actively iterated.

**Files affected:**
- Move (git mv): `benchmark/pilot_a/{build_fresh_dc_sample.py, build_lepard_sample.py, run_model.py, score.py, summarize.py}` (5 files) → `benchmark/pilot_a/`
- Move (git mv): `benchmark/pilot_a/{fresh_dc_parens_raw.json, fresh_dc_sample.csv, lepard_sample.csv, model_outputs.csv, results.csv, summary.md}` (6 tracked files) → `benchmark/pilot_a/`
- Move (fs mv): `benchmark/pilot_a/dcd_citing_opinion_cache/`, `benchmark/pilot_a/cited_opinion_cache/`, `benchmark/pilot_a/_*.txt`, `benchmark/pilot_a/_smoke_*.csv` (gitignored)
- Modify: `.gitignore`
- Modify: `benchmark/runners/build_dataset.py:26` (sys.path.insert) and line 105 (cache path)
- Modify: `benchmark/runners/calibrate_assessor.py:60` (`OPINION_CACHE = PROJECT_ROOT / "scratch" / "pilot_a" / "opinion_cache"`)
- Modify: `benchmark/runners/red_audit_fulltext.py` lines 30, 38 (cache + score.py paths)
- Modify: `benchmark/runners/score_gold_pairs.py:38` (`PROJECT_ROOT / "tests" / "pilot_a" / "score.py"`)
- Modify: `benchmark/runners/score_gold_pairs_fulltext.py` (similar paths — confirm via grep)

- [ ] **Step 4.1: Move tracked files via `git mv`**

```bash
git mv benchmark/pilot_a/build_fresh_dc_sample.py benchmark/pilot_a/build_fresh_dc_sample.py
git mv benchmark/pilot_a/build_lepard_sample.py benchmark/pilot_a/build_lepard_sample.py
git mv benchmark/pilot_a/run_model.py benchmark/pilot_a/run_model.py
git mv benchmark/pilot_a/score.py benchmark/pilot_a/score.py
git mv benchmark/pilot_a/summarize.py benchmark/pilot_a/summarize.py

git mv benchmark/pilot_a/fresh_dc_parens_raw.json benchmark/pilot_a/fresh_dc_parens_raw.json
git mv benchmark/pilot_a/fresh_dc_sample.csv benchmark/pilot_a/fresh_dc_sample.csv
git mv benchmark/pilot_a/lepard_sample.csv benchmark/pilot_a/lepard_sample.csv
git mv benchmark/pilot_a/model_outputs.csv benchmark/pilot_a/model_outputs.csv
git mv benchmark/pilot_a/results.csv benchmark/pilot_a/results.csv
git mv benchmark/pilot_a/summary.md benchmark/pilot_a/summary.md
```

Note: `benchmark/pilot_a/` may not have an `__init__.py` (let me confirm during execution; if there was one, `git mv` it too).

Verify directories empty:

```bash
ls benchmark/pilot_a/ 2>/dev/null
ls benchmark/pilot_a/ 2>/dev/null
```

Expected for both: only `__pycache__/`, `_dcd_opinion_cache/`, `opinion_cache/`, `_*.txt`, `_smoke_*.csv` may remain (all gitignored or auto-generated).

- [ ] **Step 4.2: Move gitignored items via filesystem `mv` — and rename caches for role clarity**

Pilot_a has TWO gitignored opinion caches today, with role-opaque names:

| Old path | Holds | New path |
|---|---|---|
| `benchmark/pilot_a/cited_opinion_cache/` (no underscore prefix) | **Cited** opinions (text of cases that pilot's mined parentheticals reference) | `benchmark/pilot_a/cited_opinion_cache/` |
| `benchmark/pilot_a/dcd_citing_opinion_cache/` (underscore prefix, `_dcd_` infix) | **Citing** D.D.C. opinions (the District of Columbia District court opinions pilot mined parens FROM) | `benchmark/pilot_a/dcd_citing_opinion_cache/` |

The rename eliminates the role confusion that bit past sessions twice (May 3 + May 4) — "wait, which cache?". Symmetric naming with `benchmark/releases/v1/citing_opinion_cache/` from Task 3.

```bash
# Cited-opinions cache (used by pilot_a/score.py and reused by calibrate_assessor)
[ -d benchmark/pilot_a/cited_opinion_cache ] && mv benchmark/pilot_a/cited_opinion_cache benchmark/pilot_a/cited_opinion_cache

# Citing D.D.C. opinions cache (used by pilot_a/build_fresh_dc_sample and v1's build_dataset fallback)
[ -d benchmark/pilot_a/dcd_citing_opinion_cache ] && mv benchmark/pilot_a/dcd_citing_opinion_cache benchmark/pilot_a/dcd_citing_opinion_cache

# Log files
for f in benchmark/pilot_a/_*.txt benchmark/pilot_a/_smoke_*.csv; do
  [ -f "$f" ] && mv "$f" "benchmark/pilot_a/$(basename "$f")"
done

# __pycache__ if any
rm -rf benchmark/pilot_a/__pycache__ benchmark/pilot_a/__pycache__ 2>/dev/null
```

After this step, every place that referenced these caches by name needs an update — Step 4.4 below sweeps the runner scripts; pilot_a's own `score.py` and `build_fresh_dc_sample.py` need the same treatment.

- [ ] **Step 4.3: Update `.gitignore`**

Edit `.gitignore`:

Old:
```
# Pilot A opinion-text caches (regenerable, ~5-25 MB each)
benchmark/pilot_a/dcd_citing_opinion_cache/
benchmark/pilot_a/cited_opinion_cache/

# Pilot A run logs (chatty eyecite warnings, regenerable)
benchmark/pilot_a/_*.txt
benchmark/pilot_a/_smoke_*.csv
```

New:
```
# Pilot A opinion-text caches (regenerable, ~5-25 MB each)
benchmark/pilot_a/cited_opinion_cache/
benchmark/pilot_a/dcd_citing_opinion_cache/

# Pilot A run logs (chatty eyecite warnings, regenerable)
benchmark/pilot_a/_*.txt
benchmark/pilot_a/_smoke_*.csv
```

- [ ] **Step 4.4: Update path references in runner scripts AND in pilot_a's own scripts**

The cache renames in Step 4.2 mean every reader/writer of the old names needs updating. The path-prefix change (`benchmark/pilot_a/` → `benchmark/pilot_a/`, `benchmark/pilot_a/` → `benchmark/pilot_a/`) is also bundled here.

**Pilot_a's own scripts** — read these first to find the cache constants, then update:

`benchmark/pilot_a/score.py` — search for `opinion_cache` (the cited-cases cache constant `OPINIONS_CACHE` typically references it):

Old (e.g. line 51):
```python
OPINIONS_CACHE = PROJECT_ROOT / "scratch" / "pilot_a" / "opinion_cache"
```

New:
```python
OPINIONS_CACHE = PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache"
```

`benchmark/pilot_a/build_fresh_dc_sample.py` — search for `_dcd_opinion_cache` (the citing-D.D.C. cache constant):

Old (per the constant definition for D.D.C. citing-court text):
```python
... / "scratch" / "pilot_a" / "_dcd_opinion_cache"
```

New:
```python
... / "benchmark" / "pilot_a" / "dcd_citing_opinion_cache"
```

(Verify constant names by `git grep -n opinion_cache benchmark/pilot_a/` — they may be `DCD_OPINION_CACHE`, `OPINION_CACHE`, or similar.)

**Runner scripts** (still under `benchmark/runners/` at this point; they move in Task 5):

`benchmark/runners/build_dataset.py:26`:

Old: `sys.path.insert(0, str(PROJECT_ROOT / "tests" / "pilot_a"))`
New: `sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "pilot_a"))`

`benchmark/runners/build_dataset.py:105`:

Old:
```python
    pilot_cache = (PROJECT_ROOT / "scratch" / "pilot_a" / "_dcd_opinion_cache"
```

New:
```python
    pilot_cache = (PROJECT_ROOT / "benchmark" / "pilot_a" / "dcd_citing_opinion_cache"
```

`benchmark/runners/calibrate_assessor.py:60`:

Old: `OPINION_CACHE = PROJECT_ROOT / "scratch" / "pilot_a" / "opinion_cache"`
New: `OPINION_CACHE = PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache"`

`benchmark/runners/red_audit_fulltext.py:30-31`:

Old:
```python
    PROJECT_ROOT / "scratch" / "pilot_a" / "opinion_cache",
    PROJECT_ROOT / "benchmark_v1" / "_opinion_cache",
```

New:
```python
    PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache",
    PROJECT_ROOT / "benchmark" / "releases" / "v1" / "citing_opinion_cache",
```

(Both lines deferred from Task 3 — handled here to avoid a partial edit. Note the array semantics: `red_audit_fulltext.py` searches multiple cache locations in fallback order to find a cited opinion's text. Both entries are CITED-cases caches despite different names — `releases/v1/citing_opinion_cache/` was originally `_opinion_cache/`, which Task 3 renamed.)

**WARNING:** The previous line is wrong. `releases/v1/citing_opinion_cache/` is for CITING courts (the courts that mined parens from). Lines 30-31 of red_audit_fulltext.py search for **cited** opinion text. Re-read the original code to confirm what each path holds, then either:
- (a) Drop `releases/v1/citing_opinion_cache/` from the fallback list (it's the wrong cache for this purpose), OR
- (b) Keep it because the runner ALSO needs citing-court text in some code path.

Determine the intent with `git log` or by reading the surrounding function. **If unsure, default to (a)** and verify with a smoke run.

`benchmark/runners/red_audit_fulltext.py:38`:

Old: `p = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"`
New: `p = PROJECT_ROOT / "benchmark" / "pilot_a" / "score.py"`

`benchmark/runners/score_gold_pairs.py:38`:

Old: `p = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"`
New: `p = PROJECT_ROOT / "benchmark" / "pilot_a" / "score.py"`

`benchmark/runners/score_gold_pairs_fulltext.py`: grep for `tests/pilot_a` and `scratch/pilot_a` and update analogously. Most likely line will be near the top, similar pattern.

```bash
venv/Scripts/python.exe -c "
import subprocess
out = subprocess.check_output(['git', 'grep', '-n', 'pilot_a', 'benchmark/runners/'], text=True)
print(out)
"
```

Review output and update any remaining lines.

- [ ] **Step 4.5: Run tests**

```bash
venv/Scripts/python.exe -m pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

Expected: same pass/fail count as baseline. If tests that exercise build_dataset, score_gold_pairs, or calibrate_assessor fail with FileNotFoundError, the path fix missed something — re-grep.

- [ ] **Step 4.6: Commit**

```bash
git add -u
git add .gitignore
git commit -m "benchmark: move benchmark/pilot_a/ + benchmark/pilot_a/ → benchmark/pilot_a/

Combines pilot_a code (was under tests/) with pilot_a data and
artifacts (was under scratch/) into one location. Updates the
five benchmark/runners/ runner scripts that referenced the old
paths (build_dataset, calibrate_assessor, red_audit_fulltext,
score_gold_pairs, score_gold_pairs_fulltext).

Pilot A is frozen — superseded by v1, preserved for the
methodology trail."
```

---

## Task 5: Move `benchmark/runners/` → `benchmark/runners/`

**Goal:** Move the runner code and its tests. Update absolute imports (`from benchmark.runners.X` → `from benchmark.runners.X`) and add `benchmark/runners/tests/` to pytest's testpaths.

**Files affected:**
- Move (git mv): all 14 runner scripts + 6 test files + `__init__.py` from `benchmark/runners/` (existing tasks 5 had moved it from `benchmark/runners/__init__.py` if present)
- Modify: `pyproject.toml` (add `testpaths`)
- Modify: 5+ files with `from benchmark.runners.X` absolute imports
- Modify: 2 files with `sys.path.insert(0, str(Path(__file__).resolve().parent))` — these become unnecessary once the package is properly installable, but keep them for now to minimize churn (they're harmless when the dir is also on sys.path via testpaths)

- [ ] **Step 5.1: Move runner scripts and test files via `git mv`**

```bash
# 14 runner scripts
git mv benchmark/runners/__init__.py benchmark/runners/__init__.py
# (overwrites the empty __init__.py created in Task 1 — git mv handles this; if not, rm the placeholder first)
git mv benchmark/runners/_migrate_calibration_csv.py benchmark/runners/_migrate_calibration_csv.py
git mv benchmark/runners/backfill_gold_db.py benchmark/runners/backfill_gold_db.py
git mv benchmark/runners/build_dataset.py benchmark/runners/build_dataset.py
git mv benchmark/runners/calibrate_assessor.py benchmark/runners/calibrate_assessor.py
git mv benchmark/runners/calibrate_assessor_report.py benchmark/runners/calibrate_assessor_report.py
git mv benchmark/runners/model_adapter.py benchmark/runners/model_adapter.py
git mv benchmark/runners/red_audit_fulltext.py benchmark/runners/red_audit_fulltext.py
git mv benchmark/runners/run_model.py benchmark/runners/run_model.py
git mv benchmark/runners/score.py benchmark/runners/score.py
git mv benchmark/runners/score_gold_pairs.py benchmark/runners/score_gold_pairs.py
git mv benchmark/runners/score_gold_pairs_fulltext.py benchmark/runners/score_gold_pairs_fulltext.py
git mv benchmark/runners/scorecard.py benchmark/runners/scorecard.py
git mv benchmark/runners/truncation_experiment.py benchmark/runners/truncation_experiment.py

# 6 test files → benchmark/runners/tests/
git mv benchmark/runners/test_backfill.py benchmark/runners/tests/test_backfill.py
git mv benchmark/runners/test_build_cache_wiring.py benchmark/runners/tests/test_build_cache_wiring.py
git mv benchmark/runners/test_model_adapter.py benchmark/runners/tests/test_model_adapter.py
git mv benchmark/runners/test_score_gold_pairs.py benchmark/runners/tests/test_score_gold_pairs.py
git mv benchmark/runners/test_score_integration.py benchmark/runners/tests/test_score_integration.py
git mv benchmark/runners/test_scorecard.py benchmark/runners/tests/test_scorecard.py
```

If `git mv` complains about overwriting the placeholder `__init__.py` from Task 1, run instead:

```bash
rm benchmark/runners/__init__.py
git mv benchmark/runners/__init__.py benchmark/runners/__init__.py
```

Verify `benchmark/runners/` is empty:

```bash
ls benchmark/runners/ 2>/dev/null
```

Expected: empty or only `__pycache__/`.

```bash
rm -rf benchmark/runners/__pycache__ 2>/dev/null
```

- [ ] **Step 5.2: Update absolute imports**

The pattern `from benchmark.runners.X` becomes `from benchmark.runners.X`.

Files affected (per earlier grep):

`benchmark/runners/tests/test_backfill.py:6`:

Old: `from benchmark.runners.backfill_gold_db import backfill_v1, _cluster_id_from_url`
New: `from benchmark.runners.backfill_gold_db import backfill_v1, _cluster_id_from_url`

`benchmark/runners/tests/test_score_gold_pairs.py:6`:

Old: `from benchmark.runners.score_gold_pairs import score_gold_pairs`
New: `from benchmark.runners.score_gold_pairs import score_gold_pairs`

`benchmark/runners/calibrate_assessor.py:50`:

Old: `sys.path.insert(0, str(PROJECT_ROOT / "tests" / "benchmark_v1"))`
New: `sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "runners"))`

`benchmark/runners/_migrate_calibration_csv.py:35`:

Old: `sys.path.insert(0, str(PROJECT_ROOT / "tests" / "benchmark_v1"))`
New: `sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "runners"))`

`benchmark/runners/calibrate_assessor.py` docstring (line 17): `benchmark/runners/calibrate_assessor.py` → `benchmark/runners/calibrate_assessor.py`

`benchmark/runners/calibrate_assessor_report.py:205`: `benchmark/runners/calibrate_assessor_report.py` → `benchmark/runners/calibrate_assessor_report.py` (deferred from Task 3 step 3.7)

`benchmark/runners/red_audit_fulltext.py:11` (docstring): `benchmark.runners.red_audit_fulltext` → `benchmark.runners.red_audit_fulltext`

After updates, verify no stale `benchmark.runners` imports remain:

```bash
venv/Scripts/python.exe -c "
import subprocess
out = subprocess.check_output(['git', 'grep', '-n', 'benchmark.runners\\|tests/benchmark_v1'], text=True)
print(out)
"
```

Expected: empty output, OR only hits inside docs (docs/plans/, docs/retrospectives/) which are addressed in Task 7 and Task 10.

- [ ] **Step 5.3: Configure pytest to discover `benchmark/runners/tests/`**

Edit `pyproject.toml`:

Old:
```toml
[tool.pytest.ini_options]
markers = [
    "live_api: tests that hit the real CourtListener API (deselect with -m 'not live_api')",
]
addopts = "-m 'not live_api'"
```

New:
```toml
[tool.pytest.ini_options]
markers = [
    "live_api: tests that hit the real CourtListener API (deselect with -m 'not live_api')",
]
addopts = "-m 'not live_api'"
testpaths = ["tests", "benchmark/runners/tests"]
```

- [ ] **Step 5.4: Verify pytest discovers tests in both locations**

```bash
venv/Scripts/python.exe -m pytest --collect-only -q 2>&1 | tail -20
```

Expected output should show test files from both `tests/` and `benchmark/runners/tests/`.

- [ ] **Step 5.5: Run full test suite**

```bash
venv/Scripts/python.exe -m pytest -v --tb=short -q 2>&1 | tail -30
```

Expected: same pass/fail count as baseline (after accounting for tests that previously lived in `benchmark/runners/` and are now in `benchmark/runners/tests/` — net count unchanged).

If imports fail with `ModuleNotFoundError: No module named 'benchmark.runners.X'`, the `benchmark/__init__.py` may be missing or the test invocation may need to be from the repo root. Confirm `benchmark/__init__.py` and `benchmark/runners/__init__.py` exist.

- [ ] **Step 5.6: Smoke-test a runner script**

```bash
venv/Scripts/python.exe -m benchmark.runners.scorecard --help
```

Expected: argparse help text prints. (Validates that the package is importable end-to-end.)

```bash
venv/Scripts/python.exe -m benchmark.runners.scorecard --dedupe
```

Expected: regenerates `benchmark/releases/v1/scorecards-deduped.md` from `benchmark/releases/v1/results.csv`. Should run quickly (< 5s) and produce the same content as before. If it produces a diff, that's a real bug — investigate before committing.

- [ ] **Step 5.7: Commit**

```bash
git add -u
git add pyproject.toml
git commit -m "benchmark: move benchmark/runners/ → benchmark/runners/

Renames the runner directory and updates absolute imports
(from benchmark.runners.X → from benchmark.runners.X). Adds
benchmark/runners/tests/ to pytest's testpaths.

Test files for runners now live under benchmark/runners/tests/;
unit tests for citation_verifier itself remain under tests/."
```

---

## Task 6: Clean up pilot_a coupling

**Goal:** Replace the dynamic `importlib.util.spec_from_file_location` and `sys.path.insert(0, "...pilot_a")` patterns with plain `from benchmark.pilot_a.score import ...`. Now that pilot_a is a proper package with `__init__.py`, the dynamic-loading hack is unnecessary and the cause of the "where does this code come from?" friction.

**Why this is in scope:** The user noted that v1 runners reaching into pilot_a was confusing. The move alone doesn't fix this — `red_audit_fulltext.py` would still do `importlib.util.spec_from_file_location("pilot_a_score", PROJECT_ROOT / "benchmark" / "pilot_a" / "score.py")`, just with a different path. Cleaning up the import mechanism is the actual fix.

**Why now:** these are the only callers; the change is small (3 files); doing it during the consolidation is cheaper than another round-trip later.

**What stays the same:** pilot_a's `score.py` keeps its own runnable-as-script structure (the `if __name__ == "__main__":` block at the bottom, the module-level `_HERMETIC_DIR` setup). We're only changing how OTHER files import its functions.

**Files affected:**
- Modify: `benchmark/runners/build_dataset.py:26` — drop the `sys.path.insert`; replace any direct `import` of pilot_a names with `from benchmark.pilot_a.score import ...`
- Modify: `benchmark/runners/red_audit_fulltext.py` lines ~36-44 — replace `_load_pilot_assessor` helper with `from benchmark.pilot_a import score as pilot_score`
- Modify: `benchmark/runners/score_gold_pairs.py` lines ~29-44 — same pattern as red_audit_fulltext.py
- Possibly modify: `benchmark/pilot_a/score.py:41` — drop the `sys.path.insert(0, str(PROJECT_ROOT / "src"))` since `citation_verifier` is pip-installed editable. Verify by trying both ways before committing.

- [ ] **Step 6.1: Inspect what's actually imported from pilot_a**

```bash
venv/Scripts/python.exe -c "
import subprocess
for f in ['benchmark/runners/build_dataset.py',
         'benchmark/runners/red_audit_fulltext.py',
         'benchmark/runners/score_gold_pairs.py']:
    print(f'=== {f} ===')
    out = subprocess.run(['git', 'grep', '-n', '-E', 'pilot_a|_load_pilot_assessor|spec_from_file_location|sys.path.insert', f], capture_output=True, text=True)
    print(out.stdout or '(no hits)')
"
```

Capture each function/symbol that's imported. Expected: `call_assessor` and `fetch_opinion_text` from `score.py`, possibly `MAX_OPINION_CHARS` constant.

- [ ] **Step 6.2: Update `benchmark/runners/build_dataset.py`**

Find the existing `sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "pilot_a"))` (line 26 after Task 4's path update) and the subsequent imports of pilot_a names.

Old:
```python
sys.path.insert(0, str(PROJECT_ROOT / "benchmark" / "pilot_a"))
```

Plus whichever line follows (the actual `import` of pilot_a):

```python
import build_fresh_dc_sample as fresh
```

(or similar — verify with a quick read of build_dataset.py around line 26-40)

New:
```python
from benchmark.pilot_a import build_fresh_dc_sample as fresh
```

(no `sys.path.insert` needed)

If the import is `from build_fresh_dc_sample import some_function`, change it to `from benchmark.pilot_a.build_fresh_dc_sample import some_function`.

- [ ] **Step 6.3: Update `benchmark/runners/red_audit_fulltext.py`**

The current `_load_pilot_assessor` helper (after Task 4 path updates):

Old (lines ~33-44, approximately):
```python
def _load_pilot_assessor():
    if "pilot_a_score" in sys.modules:
        return sys.modules["pilot_a_score"]
    p = PROJECT_ROOT / "benchmark" / "pilot_a" / "score.py"
    spec = importlib.util.spec_from_file_location("pilot_a_score", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pilot_a_score"] = mod
    spec.loader.exec_module(mod)
    return mod
```

And later usage like `pilot = _load_pilot_assessor(); pilot.call_assessor(...)`.

New: delete the helper entirely. At the top of the file (after the existing `from citation_verifier...` imports), add:

```python
from benchmark.pilot_a import score as pilot_score
```

Then replace each `pilot = _load_pilot_assessor()` (and subsequent `pilot.X`) with direct calls: `pilot_score.call_assessor(...)`, `pilot_score.fetch_opinion_text(...)`, etc.

Also remove the `import importlib.util` line near the top of the file if it's no longer needed.

- [ ] **Step 6.4: Update `benchmark/runners/score_gold_pairs.py`**

Same pattern as 6.3. Delete `_load_pilot_assessor`. Replace with `from benchmark.pilot_a import score as pilot_score`. Update call sites.

- [ ] **Step 6.5: Try dropping `sys.path.insert` from `benchmark/pilot_a/score.py`**

`benchmark/pilot_a/score.py:41` has:

```python
sys.path.insert(0, str(PROJECT_ROOT / "src"))
```

This is now redundant — `citation_verifier` is pip-installed editable. Test by running the file directly with the line removed:

```bash
# Edit the file to comment the line out, then:
venv/Scripts/python.exe -c "from benchmark.pilot_a.score import call_assessor, fetch_opinion_text; print('imports OK')"
```

Expected: `imports OK`. If it instead errors with `ModuleNotFoundError: No module named 'citation_verifier'`, the editable install isn't picking up — leave the `sys.path.insert` in place.

If imports work, remove the line entirely (don't just comment) and the now-unused `PROJECT_ROOT` (line 40) if it's only used for that.

- [ ] **Step 6.6: Run tests**

```bash
venv/Scripts/python.exe -m pytest -v --tb=short -q 2>&1 | tail -20
```

Expected: same pass/fail count as baseline.

- [ ] **Step 6.7: Smoke-test a runner that uses pilot_a**

```bash
venv/Scripts/python.exe -m benchmark.runners.red_audit_fulltext --help
```

Expected: argparse help text. If you get `ImportError`, debug.

- [ ] **Step 6.8: Commit**

```bash
git add -u
git commit -m "benchmark: clean up pilot_a coupling

Replaces importlib.util.spec_from_file_location and sys.path.insert
hacks in build_dataset.py, red_audit_fulltext.py, and score_gold_pairs.py
with plain 'from benchmark.pilot_a.score import ...'. Now that pilot_a
is a proper package, the dynamic-loading workaround is unnecessary.

Also drops the redundant sys.path.insert(... 'src') from
benchmark/pilot_a/score.py — citation_verifier is pip-installed."
```

---

## Task 7: Move benchmark scratch items → `benchmark/scratch/`

**Goal:** Sweep up the scratch files that are clearly benchmark-related into `benchmark/scratch/`. Move general scratch (`citations_for_review.csv`, `flp_contributions.md`, etc.) stays where it is.

**Files affected:**
- Move (git mv): `scratch/find_red_context.py`, `scratch/red_context.md`, `scratch/red_audit_input.txt`, `scratch/red_audit_sonnet.log`, `scratch/red_audit_sonnet_fulltext.log`, `scratch/red_audit_sonnet_fulltext_v2.log`, `scratch/score_fulltext_haiku.log`, `scratch/score_fulltext_sonnet.log`, `scratch/score_gold_pairs.log`, `scratch/score_validation.log`
- Move (fs mv, untracked): `scratch/join_misses_citation_court.py`
- Modify: `scratch/join_misses_citation_court.py:11` (path constant)
- Modify: `scratch/find_red_context.py` (any internal paths — verify by reading the file)

- [ ] **Step 7.1: Check whether the `.log` files are tracked**

```bash
venv/Scripts/python.exe -c "
import subprocess
for f in ['scratch/red_audit_sonnet.log',
         'scratch/red_audit_sonnet_fulltext.log',
         'scratch/red_audit_sonnet_fulltext_v2.log',
         'scratch/score_fulltext_haiku.log',
         'scratch/score_fulltext_sonnet.log',
         'scratch/score_gold_pairs.log',
         'scratch/score_validation.log']:
    rc = subprocess.call(['git', 'ls-files', '--error-unmatch', f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f, 'tracked' if rc == 0 else 'UNtracked')
"
```

Note which are tracked (use `git mv`) vs untracked (use `mv`).

- [ ] **Step 7.2: Move tracked files via `git mv`, untracked via `mv`**

```bash
# Always tracked
git mv scratch/find_red_context.py benchmark/scratch/find_red_context.py
git mv scratch/red_context.md benchmark/scratch/red_context.md
git mv scratch/red_audit_input.txt benchmark/scratch/red_audit_input.txt

# Untracked (uncommitted)
mv scratch/join_misses_citation_court.py benchmark/scratch/join_misses_citation_court.py

# Logs — use git mv for tracked, mv for untracked based on Step 6.1 output
# (Apply per-file based on the tracked/untracked output from 6.1)
```

Remove the placeholder created in Task 1:

```bash
git rm benchmark/scratch/.gitkeep 2>/dev/null
# (.gitkeep may already have been removed by git when the dir got real content; if so, this is a no-op)
```

- [ ] **Step 7.3: Update path constant in `benchmark/scratch/join_misses_citation_court.py`**

The script has `BENCH = Path(__file__).resolve().parent.parent / "benchmark_v1"` (computed from `scratch/`'s parent). After move to `benchmark/scratch/`, `parent.parent` is the repo root, and we want `benchmark/releases/v1`. Update line 11:

Old:
```python
BENCH = Path(__file__).resolve().parent.parent / "benchmark_v1"
```

New:
```python
BENCH = Path(__file__).resolve().parent.parent / "releases" / "v1"
```

(`parent` is `benchmark/scratch/`, `parent.parent` is `benchmark/`, then we append `releases/v1`.)

- [ ] **Step 7.4: Check `find_red_context.py` for path references**

```bash
venv/Scripts/python.exe -c "
print(open('benchmark/scratch/find_red_context.py').read())
" | head -30
```

If the script references `benchmark/releases/v1/`, `benchmark/gold_db/gold.db`, `benchmark/pilot_a/`, or `benchmark/pilot_a/`, update analogously to step 6.3 and the patterns from earlier tasks.

- [ ] **Step 7.5: Smoke-test the moved scripts**

```bash
venv/Scripts/python.exe benchmark/scratch/join_misses_citation_court.py
```

Expected: prints "Wrote benchmark/releases/v1/_all_cl_misses_with_citation_court.csv" and counts. Compare the output CSV's first few rows against the previously-committed version to confirm parity.

- [ ] **Step 7.6: Commit**

```bash
git add -u
git add benchmark/scratch/join_misses_citation_court.py
git commit -m "benchmark: move benchmark-related scratch files → benchmark/scratch/

Moves find_red_context.py, join_misses_citation_court.py, red_context.md,
red_audit_input.txt, and 7 .log files from scratch/ to benchmark/scratch/.
Updates path constant in join_misses_citation_court.py.

scratch/ continues to hold non-benchmark items (citations_for_review.csv,
flp_contributions.md, drafts/, etc.)."
```

---

## Task 8: Move benchmark docs → `benchmark/docs/`

**Goal:** Move 11 plans + 3 retrospectives from `docs/plans/` and `docs/retrospectives/` to `benchmark/docs/{plans,retrospectives}/`. This includes the consolidation plan itself (this file).

**Files affected (move via git mv):**

Plans (11 — `docs/plans/` → `benchmark/docs/plans/`):
- `2026-04-26-benchmark-pilot-a.md`
- `2026-04-26-case-law-benchmark-design.md`
- `2026-04-26-case-law-benchmark-design-notes.md`
- `2026-04-30-benchmark-v1-design.md`
- `2026-04-30-benchmark-v1-plan.md`
- `2026-05-03-gold-db-design.md`
- `2026-05-03-gold-db-plan.md`
- `2026-05-05-benchmark-consolidation-plan.md` (this file)
- `2026-05-05-external-methodology-review.md`
- `2026-05-05-publication-plan.md`
- `../../ROADMAP.md`
- `benchmark-spinout-prep.md`

(That's 12 actually. Both `../../ROADMAP.md` and `benchmark-spinout-prep.md` are unscoped-by-date.)

Retrospectives (3 — `docs/retrospectives/` → `benchmark/docs/retrospectives/`):
- `2026-05-02-v1.2-assessor-calibration.md`
- `2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md`
- `2026-05-04-truncation-bug-and-red-audit.md`

- [ ] **Step 8.1: Remove the placeholders from Task 1**

```bash
git rm benchmark/docs/plans/.gitkeep benchmark/docs/retrospectives/.gitkeep 2>/dev/null
```

- [ ] **Step 8.2: Move plans**

```bash
git mv docs/plans/2026-04-26-benchmark-pilot-a.md benchmark/docs/plans/2026-04-26-benchmark-pilot-a.md
git mv docs/plans/2026-04-26-case-law-benchmark-design.md benchmark/docs/plans/2026-04-26-case-law-benchmark-design.md
git mv docs/plans/2026-04-26-case-law-benchmark-design-notes.md benchmark/docs/plans/2026-04-26-case-law-benchmark-design-notes.md
git mv docs/plans/2026-04-30-benchmark-v1-design.md benchmark/docs/plans/2026-04-30-benchmark-v1-design.md
git mv docs/plans/2026-04-30-benchmark-v1-plan.md benchmark/docs/plans/2026-04-30-benchmark-v1-plan.md
git mv docs/plans/2026-05-03-gold-db-design.md benchmark/docs/plans/2026-05-03-gold-db-design.md
git mv docs/plans/2026-05-03-gold-db-plan.md benchmark/docs/plans/2026-05-03-gold-db-plan.md
git mv docs/plans/2026-05-05-benchmark-consolidation-plan.md benchmark/docs/plans/2026-05-05-benchmark-consolidation-plan.md
git mv docs/plans/2026-05-05-external-methodology-review.md benchmark/docs/plans/2026-05-05-external-methodology-review.md
git mv docs/plans/2026-05-05-publication-plan.md benchmark/docs/plans/2026-05-05-publication-plan.md
git mv ../../ROADMAP.md benchmark/../../ROADMAP.md
git mv docs/plans/benchmark-spinout-prep.md benchmark/docs/plans/benchmark-spinout-prep.md
```

- [ ] **Step 8.3: Move retrospectives**

```bash
git mv docs/retrospectives/2026-05-02-v1.2-assessor-calibration.md benchmark/docs/retrospectives/2026-05-02-v1.2-assessor-calibration.md
git mv docs/retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md benchmark/docs/retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md
git mv docs/retrospectives/2026-05-04-truncation-bug-and-red-audit.md benchmark/docs/retrospectives/2026-05-04-truncation-bug-and-red-audit.md
```

- [ ] **Step 8.4: Verify `docs/plans/` still has non-benchmark plans**

```bash
ls docs/plans/
```

Expected: still contains verify-brief plans (2026-03-*, 2026-04-15-unified-brief-*, etc.). If `docs/plans/` is empty or only contains benchmark stuff, you missed a file or moved one wrongly — investigate.

- [ ] **Step 8.5: Commit (just the moves — path updates in moved docs come in Task 10)**

```bash
git add -u
git commit -m "benchmark: move 12 plan docs + 3 retro docs → benchmark/docs/

Internal cross-links between moved docs still work (relative paths
within benchmark/docs/). Path references TO repo files (e.g.
'benchmark/releases/v1/', 'benchmark/runners/') in the moved docs are
stale and will be corrected in Task 10 of the consolidation plan.

Non-benchmark plans (verify-brief, etc.) remain at docs/plans/."
```

---

## Task 9: Extract `## Benchmark Mining` section from `scratch/TODO.md` → `benchmark/TODO.md`

**Goal:** Pull the benchmark-specific TODOs into a dedicated file.

**Files affected:**
- Modify: `scratch/TODO.md` (remove the Benchmark Mining section + the "Benchmark Mining (for v1.1+ runs)" header)
- Create: `benchmark/TODO.md`

The relevant section (per current `scratch/TODO.md`) is the one starting at `## Benchmark Mining (for v1.1+ runs)` and ending before `## Future Ideas`. Per the working-tree diff this is a recently-added section (~7 lines).

- [ ] **Step 9.1: Read the current section content from `scratch/TODO.md`**

```bash
venv/Scripts/python.exe -c "
text = open('scratch/TODO.md', encoding='utf-8').read()
start = text.find('## Benchmark Mining')
end = text.find('## Future Ideas')
assert start != -1 and end != -1, 'section markers not found'
print(text[start:end])
"
```

Capture the output for the next step.

- [ ] **Step 9.2: Write `benchmark/TODO.md`**

Create `benchmark/TODO.md` with structure:

```markdown
# Benchmark TODO

## Mining

(content from `## Benchmark Mining (for v1.1+ runs)` section in `scratch/TODO.md`, minus that header — paste the captured content here, removing the redundant `## Benchmark Mining (for v1.1+ runs)` header since this file is benchmark-only)

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
the consolidation refactor. Touch it after the consolidation lands so
the three call sites are at predictable paths.

## See also

- [`../../ROADMAP.md`](../../ROADMAP.md) — full roadmap with v1.x and v2 items
- [`docs/plans/2026-05-05-publication-plan.md`](docs/plans/2026-05-05-publication-plan.md) — publication-track items
```

The "See also" pointers help future-you find the bigger TODO context without trawling the index.

- [ ] **Step 9.3: Remove the section from `scratch/TODO.md`**

Use Edit on `scratch/TODO.md`:

Old (the entire section starting `## Benchmark Mining` and ending right before `## Future Ideas`):

```
## Benchmark Mining (for v1.1+ runs)

### ~~Pool builder drops month/day from cited-case dates~~ FIXED 2026-05-03
`extract_parentheticals()` in `benchmark/pilot_a/build_fresh_dc_sample.py` (also used by `benchmark/runners/build_dataset.py`) was persisting only `meta.year`, dropping `meta.month` and `meta.day` that eyecite already extracts. Now persists `month`, `day`, plus a new `full_citation_text` field (eyecite `c.full_span()` slice — case name + reporter + court + date + parenthetical) so downstream consumers can re-parse if eyecite metadata extraction drops a field in the future. Existing `_raw_pool.json` files predate the fix; re-mine to backfill.

Discovered via `_all_cl_misses.csv` analysis: only `year` was available for cited cases, so date filtering in the verifier was year-wide and the misses CSV had no full-date column for the cited case. Relevant for the v1.1 "real-but-CL-missed" audit since narrower date filters should reduce miscoded misses.

```

(Note the trailing blank line — preserve the gap before `## Future Ideas`.)

New (replace with empty string — i.e. delete entirely):

```

```

(Keep one blank line before `## Future Ideas` for spacing.)

- [ ] **Step 9.4: Update path references in `benchmark/TODO.md`**

The captured section refers to `benchmark/pilot_a/build_fresh_dc_sample.py` and `benchmark/runners/build_dataset.py`. Update to:
- `benchmark/pilot_a/build_fresh_dc_sample.py`
- `benchmark/runners/build_dataset.py`

And `_raw_pool.json` should be `benchmark/releases/v1/_raw_pool.json`.

- [ ] **Step 9.5: Commit**

```bash
git add benchmark/TODO.md scratch/TODO.md
git commit -m "benchmark: extract Benchmark Mining section to benchmark/TODO.md

scratch/TODO.md keeps verifier and verify-brief items; benchmark
TODOs now live with the rest of the benchmark project."
```

---

## Task 10: Update path references inside moved docs

**Goal:** Sweep through `benchmark/docs/` and update stale path references (`benchmark/releases/v1/`, `benchmark/runners/`, `benchmark/pilot_a/`, `benchmark/pilot_a/`, `benchmark/gold_db/gold.db`) to the new locations. The cross-references between docs already work (relative paths inside `benchmark/docs/`), but references to repo files are stale.

**Files affected:** all 14 docs under `benchmark/docs/plans/` and `benchmark/docs/retrospectives/`.

- [ ] **Step 10.1: Inventory stale references**

```bash
venv/Scripts/python.exe -c "
import subprocess
patterns = ['benchmark/releases/v1/', 'benchmark/runners/', 'benchmark.runners', 'benchmark/pilot_a/', 'benchmark/pilot_a/', 'benchmark/gold_db/gold.db']
for p in patterns:
    print(f'=== {p} ===')
    out = subprocess.run(['git', 'grep', '-l', p, 'benchmark/docs/'], capture_output=True, text=True)
    print(out.stdout or '(none)')
"
```

This shows which docs need editing and for which patterns.

- [ ] **Step 10.2: Apply replacements per file**

For each file from Step 10.1, use `Edit` with `replace_all=True` for each path pattern:

| Old | New |
|-----|-----|
| `benchmark/releases/v1/` | `benchmark/releases/v1/` |
| `benchmark/runners/` | `benchmark/runners/` |
| `benchmark.runners` | `benchmark.runners` |
| `benchmark/pilot_a/` | `benchmark/pilot_a/` |
| `benchmark/pilot_a/` | `benchmark/pilot_a/` |
| `benchmark/gold_db/gold.db` | `benchmark/benchmark/gold_db/gold.db` |
| `benchmark/gold_db/exports` | `benchmark/benchmark/gold_db/exports` |
| `benchmark/gold_db/migrations` | `benchmark/benchmark/gold_db/migrations` |

**Caution:** the `replace_all=True` will hit prose AND code blocks. That's the intent — both should reflect new paths.

**Caution:** `benchmark/runners/` substring also appears inside `benchmark.runners` (no it doesn't — the punctuation differs). But `benchmark/releases/v1/` is a substring of `benchmark/releases/v1/_raw_pool.json` etc. — that's fine, replacement still works.

For each file, run:

```bash
venv/Scripts/python.exe -c "
import re
from pathlib import Path
for f in Path('benchmark/docs').rglob('*.md'):
    text = f.read_text(encoding='utf-8')
    orig = text
    repls = [
        ('benchmark/runners/', 'benchmark/runners/'),
        ('benchmark.runners', 'benchmark.runners'),
        ('benchmark/releases/v1/', 'benchmark/releases/v1/'),
        ('benchmark/pilot_a/', 'benchmark/pilot_a/'),
        ('benchmark/pilot_a/', 'benchmark/pilot_a/'),
        ('benchmark/gold_db/gold.db', 'benchmark/benchmark/gold_db/gold.db'),
        ('benchmark/gold_db/exports', 'benchmark/benchmark/gold_db/exports'),
        ('benchmark/gold_db/migrations', 'benchmark/benchmark/gold_db/migrations'),
    ]
    for old, new in repls:
        text = text.replace(old, new)
    if text != orig:
        f.write_text(text, encoding='utf-8')
        print(f'updated {f}')
"
```

**Note on order:** `benchmark/runners/` must be replaced BEFORE `benchmark/releases/v1/` to avoid the longer pattern's prefix being consumed by the shorter one.

- [ ] **Step 10.3: Visual review of diffs**

```bash
git diff --stat benchmark/docs/
```

Expected: each updated file shows a few lines changed.

```bash
git diff benchmark/../../ROADMAP.md | head -40
```

Spot-check that the diff looks right — no double-replacements (e.g. `benchmark/releases/v1/releases/v1/`), no off-by-one issues.

- [ ] **Step 10.4: Re-grep to confirm no stale references remain**

```bash
venv/Scripts/python.exe -c "
import subprocess
patterns = ['benchmark/releases/v1/', 'benchmark/runners/', 'benchmark.runners', 'benchmark/pilot_a/', 'benchmark/pilot_a/']
for p in patterns:
    out = subprocess.run(['git', 'grep', '-l', p, 'benchmark/docs/'], capture_output=True, text=True)
    if out.stdout.strip():
        print(f'STALE: {p}')
        print(out.stdout)
"
```

Expected: no output.

- [ ] **Step 10.5: Commit**

```bash
git add benchmark/docs/
git commit -m "benchmark: update stale path refs in moved docs

Sweeps benchmark/releases/v1/ → benchmark/releases/v1/, benchmark/runners/ →
benchmark/runners/, benchmark/pilot_a/ + benchmark/pilot_a/ → benchmark/pilot_a/,
gold_db/* → benchmark/gold_db/* across all 14 plan + retro docs."
```

---

## Task 11: Update `CLAUDE.md`

**Goal:** Add a benchmark-orientation pointer near the top of `CLAUDE.md`, and update any path references to benchmark items.

**Files affected:** `CLAUDE.md`

- [ ] **Step 11.1: Inventory benchmark references in CLAUDE.md**

```bash
venv/Scripts/python.exe -c "
import subprocess
patterns = ['benchmark_v1', 'tests/benchmark', 'tests/pilot_a', 'scratch/pilot_a', 'gold_db']
for p in patterns:
    print(f'=== {p} ===')
    out = subprocess.run(['git', 'grep', '-n', p, 'CLAUDE.md'], capture_output=True, text=True)
    print(out.stdout or '(none)')
"
```

- [ ] **Step 11.2: Apply path updates**

For each hit from Step 11.1, use `Edit` with the same `old → new` mapping as Task 10.

- [ ] **Step 11.3: Add benchmark orientation note**

Find the existing "## Project Overview" section in CLAUDE.md. After it (before "## Workflow Preferences"), add:

```markdown
## Benchmark sub-project

A separate effort lives at [`benchmark/`](benchmark/) — a case-law retrieval benchmark
that depends on this verifier but is otherwise self-contained. See
[`benchmark/README.md`](benchmark/README.md) for orientation, [`benchmark/../../ROADMAP.md`](benchmark/../../ROADMAP.md)
for the engineering roadmap, and [`benchmark/docs/plans/2026-05-05-publication-plan.md`](benchmark/docs/plans/2026-05-05-publication-plan.md)
for the publication track.

The `gold_db.py` module under `src/citation_verifier/gold_db.py` is the
benchmark's persistence layer but ships in this package because it's
reusable infrastructure. The SQLite database, schema, and exports live
under `benchmark/gold_db/`.

```

- [ ] **Step 11.4: Run pytest and a smoke benchmark command**

```bash
venv/Scripts/python.exe -m pytest -v --tb=short -q 2>&1 | tail -15
venv/Scripts/python.exe -m benchmark.runners.scorecard --dedupe
```

Expected: tests still pass, scorecard still regenerates.

- [ ] **Step 11.5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add benchmark orientation pointer to CLAUDE.md

Updates path references and adds a 'Benchmark sub-project' section
that points at benchmark/README.md and the roadmap + publication plan."
```

---

## Task 12: Final validation + push

**Goal:** Confirm everything works end-to-end. Push to remote.

- [ ] **Step 12.1: Run full pytest suite**

```bash
venv/Scripts/python.exe -m pytest -v --tb=short 2>&1 | tail -30
```

Compare the totals to the baseline from Step 0.1. Any deltas?

- [ ] **Step 12.2: Run a representative benchmark command end-to-end**

```bash
venv/Scripts/python.exe -m benchmark.runners.scorecard --dedupe
```

Then check the regenerated `benchmark/releases/v1/scorecards-deduped.md` matches what was committed (`git diff benchmark/releases/v1/scorecards-deduped.md` should show no changes, or only timestamp changes if any).

- [ ] **Step 12.3: Run the gold-db sanity check**

```bash
venv/Scripts/python.exe -c "
from citation_verifier.gold_db import GoldDB
db = GoldDB('benchmark/benchmark/gold_db/gold.db')
print('verdicts:', db.conn.execute('SELECT COUNT(*) FROM assessor_verdicts').fetchone()[0])
print('propositions:', db.conn.execute('SELECT COUNT(*) FROM propositions').fetchone()[0])
print('drift samples:', db.conn.execute(\"SELECT COUNT(*) FROM assessor_verdicts WHERE assessor_prompt_version LIKE 'v1-drift%'\").fetchone()[0])
"
```

Expected: matches the README's stated counts (verdicts: 814+, propositions: 127, drift samples: 10+).

- [ ] **Step 12.4: List the final structure**

```bash
ls benchmark/
ls benchmark/runners/ benchmark/runners/tests/ benchmark/pilot_a/ benchmark/gold_db/ benchmark/releases/v1/ benchmark/docs/plans/ benchmark/docs/retrospectives/ benchmark/scratch/
```

Visual check: matches the target structure from the top of this plan.

- [ ] **Step 12.5: Confirm no benchmark items remain in the old locations + no stale cache names**

```bash
ls benchmark/releases/v1/ 2>/dev/null
ls gold_db/ 2>/dev/null
ls benchmark/runners/ 2>/dev/null
ls benchmark/pilot_a/ 2>/dev/null
ls benchmark/pilot_a/ 2>/dev/null
```

Expected: all should report empty or "No such file or directory."

Also confirm no stale cache references survive in the codebase:

```bash
venv/Scripts/python.exe -c "
import subprocess
for pat in ['_opinion_cache', '/opinion_cache', '_dcd_opinion_cache']:
    out = subprocess.run(['git', 'grep', '-l', pat], capture_output=True, text=True)
    if out.stdout.strip():
        print(f'STALE references to {pat}:')
        print(out.stdout)
"
```

Expected: no output. Any hits represent code or docs still pointing at the old cache names.

- [ ] **Step 12.6: Push the branch**

```bash
git log --oneline origin/main..HEAD
```

Should show ~12 commits (one per task).

```bash
git push origin main
```

---

## Self-review checklist

- [ ] All `benchmark/releases/v1/` paths in scripts and docs now point to `benchmark/releases/v1/`
- [ ] All `benchmark/runners/` references → `benchmark/runners/` (paths) or `benchmark.runners` (imports)
- [ ] All `benchmark/pilot_a/` and `benchmark/pilot_a/` references → `benchmark/pilot_a/`
- [ ] `benchmark/gold_db/gold.db` → `benchmark/benchmark/gold_db/gold.db`
- [ ] `gold_db.py` SCHEMA_PATH points to `benchmark/benchmark/gold_db/migrations/...`
- [ ] `pyproject.toml` testpaths includes `benchmark/runners/tests`
- [ ] `.gitignore` updated for new cache locations
- [ ] `tests/test_gold_db.py` still passes
- [ ] All `benchmark/runners/tests/test_*.py` still pass
- [ ] `benchmark/runners/scorecard.py --dedupe` regenerates the same scorecard
- [ ] No `importlib.util.spec_from_file_location` or `sys.path.insert(... pilot_a)` remains in `benchmark/runners/` — pilot_a imports are plain `from benchmark.pilot_a.score import ...`
- [ ] Opinion caches are renamed: `cited_opinion_cache/`, `dcd_citing_opinion_cache/`, `citing_opinion_cache/` (per the naming convention in `benchmark/README.md`); no `_opinion_cache` or `opinion_cache` (un-prefixed) directories remain
- [ ] `benchmark/README.md` exists, describes the layout, AND notes that v1.x iterations write into `releases/v1/` (no v1.1, v1.2, etc. subdirs)
- [ ] `benchmark/TODO.md` exists with the Benchmark Mining content
- [ ] `CLAUDE.md` has the benchmark-orientation pointer
- [ ] All ~12 commits land on `main`; remote is up to date
- [ ] No tracked files remain in `benchmark/releases/v1/`, `gold_db/`, `benchmark/runners/`, `benchmark/pilot_a/`, or `benchmark/pilot_a/`

---

## Things explicitly NOT in this plan

- **Spinout to a new repo.** Hold per `benchmark-spinout-prep.md` until v1.2 / kit / publication land.
- **gold_db.py module relocation.** Stays at `src/citation_verifier/gold_db.py` per prior decision (importable from `citation_verifier`).
- **Functional changes** to mining, scoring, or assessor logic. This is a pure refactor.
- **New tests.** This is a refactor; existing tests are the verification.
- **API doc / API.md.** Deferred per `benchmark-spinout-prep.md`.
- **Renaming `benchmark/` to anything else.** `benchmark/` is the working name; if a future paper uses a different name (`claire-bench`, etc.), rename then.
- **Versioning the `runners/` directory.** v2 runners evolve in-place; reproduce v1 via git tags, not by frozen-runner copies.
- **Removing `_*.txt` log files from `benchmark/releases/v1/`** even though they're gitignored. They sit alongside the release artifacts; if they're not present in the repo, they're not present, that's fine.
- **Extracting a shared `claude -p` hermetic-CLI helper** to DRY up `_HERMETIC_DIR` across `pilot_a/score.py`, `runners/model_adapter.py`, and `runners/red_audit_fulltext.py`. This is a behavior-touching cleanup, not just a move. Tracked in `benchmark/TODO.md` as a follow-up; touched after this consolidation lands so the call sites are at predictable paths. The README documents the pattern so new runners don't inadvertently skip the bypass in the meantime.

## Cost / risk

- Time: estimated 4–6 hours of focused work for a careful operator. Subagent-driven could be 2–3 hours wall.
- Reversibility: each task is a separate commit. Bisect lands you on the breaking task. Revert is `git revert <task-commit>` for any single task.
- Blast radius: medium. The repo is single-author and single-machine-active — no PR review queue, no parallel branches that need to rebase. CI doesn't exist for this repo. The biggest risk is silently breaking a runner that we don't notice because we don't run it often.
- Mitigation: full pytest after each path-touching task; a manual smoke run of `scorecard.py --dedupe` after Tasks 5 and 11.
