# Benchmark Spin-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `benchmark/` sub-project from public `citation-verifier` to a new private repo `case-law-proposition-benchmark`. Keep both repos functional throughout.

**Architecture:** Library-import consumption: new repo's `requirements.txt` pins `citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@<tag>`. Fresh-start history (no `git filter-repo`). Editable install on top for local dev. `gold_db.py` moves to new repo as `gold_db/` package.

**Tech Stack:** Python 3.10+, setuptools, pytest, git. Existing tech stack of both projects unchanged.

**Spec:** [`docs/plans/2026-05-17-benchmark-spinout-design.md`](2026-05-17-benchmark-spinout-design.md)

---

## Refactoring scope (read this before starting)

Three categories of mechanical changes happen during the move:

### Change A: cross-repo gold_db import
- **Before:** `from citation_verifier.gold_db import GoldDB, get_or_score_verdict, ...`
- **After:** `from gold_db import GoldDB, get_or_score_verdict, ...`
- **Affects:** ~20 files in benchmark (and one test file moving from citation-verifier)

### Change B: intra-benchmark package imports
- **Before:** `from benchmark.pilot_a.score import ...`, `from benchmark.runners.X import ...`
- **After:** `from pilot_a.score import ...`, `from runners.X import ...`
- **Affects:** ~10 code files in `benchmark/runners/` and `benchmark/runners/tests/`

### Change C: PROJECT_ROOT path calculation and `/benchmark/` path segments
- **Before (in benchmark/runners/X.py):**
  ```python
  PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # 3 levels up
  OUT = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "results.csv"
  ```
- **After (in runners/X.py):**
  ```python
  PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 2 levels up
  OUT = PROJECT_ROOT / "releases" / "v1" / "results.csv"
  ```
- **Affects:** ~10 files using `PROJECT_ROOT` constants

The three changes are independent and can be done in one pass per file.

---

## File structure changes

### citation-verifier after move

```
DELETED:
  benchmark/                                  (entire directory)
  src/citation_verifier/gold_db.py
  tests/test_gold_db.py

MODIFIED:
  CLAUDE.md                                   (remove benchmark section, gold_db row)
  pyproject.toml                              (remove benchmark/runners/tests from testpaths, bump version)
  src/citation_verifier/client.py             (fix stale comment at line 28)
```

### case-law-proposition-benchmark (new repo)

```
CREATED (all files):
  gold_db/__init__.py                          # was src/citation_verifier/gold_db.py
  gold_db/migrations/                          # was benchmark/gold_db/migrations/
  gold_db/gold.db                              # was benchmark/gold_db/gold.db
  gold_db/exports/                             # was benchmark/gold_db/exports/
  gold_db/README.md                            # was benchmark/gold_db/README.md
  runners/                                     # was benchmark/runners/ (imports updated)
  pilot_a/                                     # was benchmark/pilot_a/ (imports updated)
  releases/                                    # was benchmark/releases/
  docs/                                        # was benchmark/docs/
  scratch/                                     # was benchmark/scratch/
  tests/test_gold_db.py                        # was citation-verifier/tests/test_gold_db.py
  __init__.py                                  # was benchmark/__init__.py
  README.md                                    # adapted from benchmark/README.md
  ROADMAP.md                                   # was benchmark/ROADMAP.md
  TODO.md                                      # was benchmark/TODO.md
  CLAUDE.md                                    # new
  pyproject.toml                               # new
  requirements.txt                             # new
  .gitignore                                   # copied from citation-verifier
  .env.example                                 # new
```

---

## Phase 1: Prep citation-verifier

### Task 1: Verify citation-verifier installs cleanly from current HEAD

**Files:** none modified

This task confirms the current state is a clean install starting point before we tag a release.

- [ ] **Step 1: Create a throwaway venv outside the repo**

```bash
cd /tmp  # or any path outside the citation-verifier worktree
python -m venv test-install-venv
source test-install-venv/Scripts/activate  # Windows Git Bash
```

- [ ] **Step 2: Install citation-verifier from local git**

```bash
pip install git+file://C:/Users/Rebecca\ Fordon/Projects/citation-verifier@HEAD
```

Expected: install completes without errors. Dependencies (requests, aiohttp, eyecite, etc.) get pulled.

- [ ] **Step 3: Verify import works**

```bash
python -c "from citation_verifier import CitationVerifier; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Deactivate and remove throwaway venv**

```bash
deactivate
rm -rf /tmp/test-install-venv
```

If Step 2 or Step 3 fails, stop the plan and fix install issues before proceeding (likely missing `__init__.py` or missing files in `MANIFEST.in`). Do NOT proceed to tag a broken version.

### Task 2: Tag v0.1.0 in citation-verifier

**Files:** none modified (git only)

- [ ] **Step 1: Confirm you're on main branch with no uncommitted changes**

```bash
git status
```

Expected: "On branch main", "nothing to commit, working tree clean".

If you're on a worktree branch (like `claude/dreamy-roentgen-25df66`), merge that branch into main first or commit/push from the worktree's branch before tagging.

- [ ] **Step 2: Tag the current HEAD**

```bash
git tag v0.1.0
```

- [ ] **Step 3: Push tag to origin**

```bash
git push origin v0.1.0
```

Expected output: `* [new tag] v0.1.0 -> v0.1.0`

- [ ] **Step 4: Verify tag on GitHub**

Open https://github.com/rlfordon/citation-verifier/tags in browser. Confirm `v0.1.0` appears.

This is the version that benchmark will pin initially. After Phase 4, we'll bump to `v0.2.0`.

---

## Phase 2: Create and populate new repo

### Task 3: Create private GitHub repo

**Files:** none

**This task requires the user to interact with GitHub.** An agent cannot do this without GitHub credentials.

- [ ] **Step 1: Create repo on GitHub**

Go to https://github.com/new and create a new repo:
- Name: `case-law-proposition-benchmark`
- Visibility: **Private**
- **Do NOT initialize** with README, .gitignore, or license (we'll push initial commit from local)

- [ ] **Step 2: Clone the empty repo locally, next to citation-verifier**

```bash
cd C:/Users/Rebecca\ Fordon/Projects
git clone https://github.com/rlfordon/case-law-proposition-benchmark.git
cd case-law-proposition-benchmark
```

Expected: empty directory (just `.git/`).

### Task 4: Copy benchmark contents (no history)

**Files in new repo:**
- Create: all files from `citation-verifier/benchmark/` (without the `benchmark/` prefix)

- [ ] **Step 1: Copy benchmark/ contents to new repo root**

From inside `case-law-proposition-benchmark/`:

```bash
# Use a recursive copy that includes hidden files
cp -r ../citation-verifier/benchmark/. .
```

The trailing `/.` ensures contents (not the `benchmark/` directory itself) are copied to the current directory.

- [ ] **Step 2: Verify expected directories exist**

```bash
ls
```

Expected to see at least: `__init__.py`, `README.md`, `ROADMAP.md`, `TODO.md`, `gold_db/`, `runners/`, `pilot_a/`, `releases/`, `docs/`, `scratch/`.

- [ ] **Step 3: Verify the gold_db/ directory has migrations and gold.db but no module yet**

```bash
ls gold_db/
```

Expected: `migrations/`, `gold.db`, `exports/`, `README.md`. No `__init__.py` yet — that's Task 5.

### Task 5: Move gold_db.py from citation-verifier to new gold_db/__init__.py

**Files:**
- Create: `case-law-proposition-benchmark/gold_db/__init__.py`
- Source: `citation-verifier/src/citation_verifier/gold_db.py`

Note: We're NOT deleting from citation-verifier yet. Phase 4 handles that.

- [ ] **Step 1: Copy gold_db.py to new repo as the package init**

```bash
cp ../citation-verifier/src/citation_verifier/gold_db.py gold_db/__init__.py
```

- [ ] **Step 2: Verify file exists and has expected size**

```bash
ls -la gold_db/__init__.py
```

Expected: ~16K bytes (matches original `gold_db.py`).

- [ ] **Step 3: Verify the module can be imported (smoke test, no install)**

```bash
python -c "import sys; sys.path.insert(0, '.'); from gold_db import GoldDB; print('OK')"
```

Expected: `OK`. If it fails with `ImportError`, the module has a dependency that isn't on Python's path — that's expected at this point. Just confirm the file is syntactically valid:

```bash
python -c "import ast; ast.parse(open('gold_db/__init__.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`.

### Task 6: Move test_gold_db.py to new repo

**Files:**
- Create: `case-law-proposition-benchmark/tests/test_gold_db.py`
- Source: `citation-verifier/tests/test_gold_db.py`

- [ ] **Step 1: Create tests/ directory if it doesn't already exist**

```bash
mkdir -p tests
```

- [ ] **Step 2: Copy test_gold_db.py from citation-verifier**

```bash
cp ../citation-verifier/tests/test_gold_db.py tests/test_gold_db.py
```

- [ ] **Step 3: Verify test file exists**

```bash
ls -la tests/test_gold_db.py
```

### Task 7: Update gold_db imports in test_gold_db.py

**Files:**
- Modify: `case-law-proposition-benchmark/tests/test_gold_db.py`

This is the first of several import-update tasks. We're applying Change A from the refactoring scope.

- [ ] **Step 1: Find the gold_db imports in the test file**

```bash
grep -n "citation_verifier.gold_db\|from citation_verifier import gold_db" tests/test_gold_db.py
```

Note the line numbers and exact import statements.

- [ ] **Step 2: Replace with `from gold_db import ...`**

For each line found, update:
- `from citation_verifier.gold_db import X, Y, Z` → `from gold_db import X, Y, Z`
- `from citation_verifier import gold_db` → `import gold_db` (only if used as `gold_db.X` rather than direct names)

Use the Edit tool or sed:
```bash
sed -i 's|from citation_verifier\.gold_db|from gold_db|g; s|from citation_verifier import gold_db|import gold_db|g' tests/test_gold_db.py
```

- [ ] **Step 3: Verify all citation_verifier.gold_db references are gone**

```bash
grep -n "citation_verifier.gold_db\|from citation_verifier import gold_db" tests/test_gold_db.py
```

Expected: no output (no matches).

### Task 8: Update gold_db imports across runners/ and scratch/

**Files:** All files under `runners/` and `scratch/` that import `citation_verifier.gold_db`.

Per the spec, these files are: `runners/score.py`, `runners/score_gold_pairs.py`, `runners/score_gold_pairs_fulltext.py`, `runners/red_audit_fulltext.py`, `runners/build_dataset.py`, `runners/backfill_gold_db.py`, `runners/backfill_v1_court_metadata.py`, `runners/tests/test_score_gold_pairs.py`, `runners/tests/test_score_integration.py`, `runners/tests/test_backfill.py`, `runners/tests/test_build_cache_wiring.py`, plus four files under `scratch/`.

- [ ] **Step 1: List all files with the import**

```bash
grep -rln "citation_verifier\.gold_db\|from citation_verifier import gold_db" runners/ scratch/
```

Expected output: ~16 files. Compare against the list in the spec to confirm completeness.

- [ ] **Step 2: Replace imports in each file**

For each file found:
```bash
sed -i 's|from citation_verifier\.gold_db|from gold_db|g; s|from citation_verifier import gold_db|import gold_db|g' <file>
```

Or apply across all matched files at once:
```bash
grep -rl "citation_verifier\.gold_db\|from citation_verifier import gold_db" runners/ scratch/ | xargs sed -i 's|from citation_verifier\.gold_db|from gold_db|g; s|from citation_verifier import gold_db|import gold_db|g'
```

- [ ] **Step 3: Verify no remaining references**

```bash
grep -rn "citation_verifier\.gold_db\|from citation_verifier import gold_db" runners/ scratch/
```

Expected: no output.

### Task 9: Update intra-benchmark imports (`from benchmark.X` → `from X`)

**Files:** All files in `runners/`, `pilot_a/`, and `scratch/` that import from the old `benchmark.` package prefix.

This applies Change B from the refactoring scope.

- [ ] **Step 1: List all files with `from benchmark.` or `import benchmark.` imports**

```bash
grep -rln "from benchmark\.\|import benchmark\." runners/ pilot_a/ scratch/
```

Expected: ~10-12 code files (see the spec for the specific list).

- [ ] **Step 2: Replace `from benchmark.pilot_a` → `from pilot_a` and `from benchmark.runners` → `from runners`**

```bash
grep -rl "from benchmark\.\|import benchmark\." runners/ pilot_a/ scratch/ | xargs sed -i \
  -e 's|from benchmark\.pilot_a|from pilot_a|g' \
  -e 's|from benchmark\.runners|from runners|g' \
  -e 's|import benchmark\.pilot_a|import pilot_a|g' \
  -e 's|import benchmark\.runners|import runners|g'
```

- [ ] **Step 3: Verify no remaining `benchmark.` package references in code**

```bash
grep -rn "from benchmark\.\|import benchmark\." runners/ pilot_a/ scratch/
```

Expected: no output.

If output remains, manually inspect those files — they may use unusual import forms (e.g., `__import__('benchmark.X')`) that need hand-fixing.

### Task 10: Update PROJECT_ROOT calculations and `/benchmark/` path segments

**Files:** All files using `PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent` or `PROJECT_ROOT / "benchmark" / ...`.

This applies Change C from the refactoring scope.

- [ ] **Step 1: List all files using PROJECT_ROOT**

```bash
grep -rln "PROJECT_ROOT" runners/ pilot_a/ scratch/
```

Expected: ~10 files (mostly in `runners/`).

- [ ] **Step 2: Fix PROJECT_ROOT calculation (one fewer `.parent`)**

For each file under `runners/`, `pilot_a/`, or one-level-deep:

```python
# Before (in benchmark/runners/X.py, 3 levels up to repo root):
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# After (in runners/X.py, 2 levels up to repo root):
PROJECT_ROOT = Path(__file__).resolve().parent.parent
```

Use sed if you're sure all are exactly one level deeper than they should be (i.e., were 3-parent and should be 2-parent):

```bash
grep -rl "PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent" runners/ pilot_a/ scratch/ | xargs sed -i 's|PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent|PROJECT_ROOT = Path(__file__).resolve().parent.parent|g'
```

**Caveat:** If any file is nested deeper (e.g., `runners/tests/test_X.py`), it'll need `.parent.parent.parent` (3 levels) in the new repo — same as before but pointing to new root. Check each file's directory depth after the sed.

- [ ] **Step 3: Drop the `/benchmark/` path segment**

```bash
grep -rl 'PROJECT_ROOT / "benchmark"' runners/ pilot_a/ scratch/ | xargs sed -i 's|PROJECT_ROOT / "benchmark" / |PROJECT_ROOT / |g'
```

- [ ] **Step 4: Verify path constants resolve to expected absolute paths**

Pick one file and print the resolved paths:

```bash
python -c "
import sys
sys.path.insert(0, '.')
from runners.scorecard import PROJECT_ROOT, RESULTS
print('PROJECT_ROOT:', PROJECT_ROOT)
print('RESULTS:', RESULTS)
print('Exists?', RESULTS.exists())
"
```

Expected: PROJECT_ROOT points to the new repo root (`.../case-law-proposition-benchmark`), and RESULTS points to `releases/v1/results.csv` which should exist.

- [ ] **Step 5: Verify no `/benchmark/` references remain in code**

```bash
grep -rn '"benchmark"' runners/ pilot_a/ scratch/
```

Expected: no output, OR matches are clearly in comments/docstrings (review case-by-case).

### Task 11: Write pyproject.toml for new repo

**Files:**
- Create: `case-law-proposition-benchmark/pyproject.toml`

- [ ] **Step 1: Identify benchmark's non-stdlib dependencies**

```bash
grep -rh "^import \|^from " runners/ pilot_a/ gold_db/__init__.py tests/ | grep -v "^from \.\|^import \." | sort -u | head -50
```

Note packages NOT in Python stdlib and NOT in citation-verifier's deps. Common ones to expect: `pandas`, `scikit-learn` (if used), `tqdm`, `tenacity`. Most deps come transitively via citation-verifier.

- [ ] **Step 2: Write `pyproject.toml`**

Create `pyproject.toml` with this content (adjust dependency list based on Step 1 findings):

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "case-law-proposition-benchmark"
version = "0.1.0"
description = "Case-law retrieval / proposition support benchmark (private)"
requires-python = ">=3.10"
dependencies = [
    # Pinned via requirements.txt for reproducibility:
    # citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.1.0
    # (Listed in requirements.txt rather than here so git URL doesn't appear in package metadata)
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["gold_db*", "runners*", "pilot_a*"]
exclude = ["scratch*", "releases*", "docs*", "tests*"]

[tool.pytest.ini_options]
testpaths = ["tests", "runners/tests"]
```

Note: dependencies are deliberately empty in `[project]` because `citation-verifier @ git+...` cannot appear in `[project.dependencies]` for PyPI-compatibility reasons. It goes in `requirements.txt` instead.

- [ ] **Step 3: Verify pyproject.toml parses**

```bash
python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['name'])"
```

Expected: `case-law-proposition-benchmark`

### Task 12: Write requirements.txt for new repo

**Files:**
- Create: `case-law-proposition-benchmark/requirements.txt`

- [ ] **Step 1: Write `requirements.txt`**

```
# Citation-verifier provides the core verification library.
# Pinned to a tag for reproducible installs.
citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.1.0

# Any benchmark-specific dependencies that aren't transitively pulled by citation-verifier
# Add as discovered. Common candidates:
# pandas>=2.0
# tqdm>=4.0
```

- [ ] **Step 2: Identify additional deps from Task 11 Step 1 findings**

If benchmark imports any packages not in citation-verifier's dependency tree, add them to `requirements.txt`. To check what citation-verifier transitively provides, install citation-verifier in a venv and run `pip list`.

- [ ] **Step 3: Verify file exists**

```bash
cat requirements.txt
```

### Task 13: Write README.md, CLAUDE.md, .gitignore, .env.example for new repo

**Files:**
- Create: `case-law-proposition-benchmark/README.md`
- Create: `case-law-proposition-benchmark/CLAUDE.md`
- Create: `case-law-proposition-benchmark/.gitignore`
- Create: `case-law-proposition-benchmark/.env.example`

- [ ] **Step 1: Adapt README.md from benchmark/README.md**

```bash
# README.md already exists from the copy in Task 4. Edit it to:
# - Update repo references (no longer "benchmark sub-project of citation-verifier")
# - Mention the citation-verifier dependency
# - Document the dev-loop setup (editable install pattern)
```

Use the Edit tool to replace the framing sentences. The substantive content (what the benchmark is, what it measures) stays.

- [ ] **Step 2: Write CLAUDE.md**

Create `CLAUDE.md` with the sections below. Source material to crib from:
- **Project overview:** Read `README.md` and `ROADMAP.md` (both copied in Task 4); summarize what the benchmark measures and what stage it's at.
- **Architecture:** Read `ROADMAP.md` and `docs/plans/benchmark-roadmap.md` (if it exists); 2-3 paragraph summary of the v1 pipeline shape (build_dataset → run_model → score → scorecard).
- **Windows env + workflow preferences:** copy from citation-verifier's CLAUDE.md (sections "Windows Environment", "Workflow Preferences").

Template structure:

```markdown
# Case-Law Proposition Benchmark - Development Guide

## Project Overview

(Write a 1-paragraph summary based on README.md + ROADMAP.md. Mention this is private during development; some portion may eventually go public after publication. Link to the citation-verifier dependency.)

## Dependency on citation-verifier

This benchmark depends on the `citation-verifier` library (https://github.com/rlfordon/citation-verifier). The `requirements.txt` pins a specific tagged version for reproducibility.

**For local development:** install citation-verifier as editable to pick up local changes immediately:
```bash
pip install -e ../citation-verifier
```

**For fresh-machine setup or CI:** `pip install -r requirements.txt` pulls the pinned tagged version from GitHub.

When citation-verifier changes in a way benchmark depends on:
1. Commit + push citation-verifier
2. Tag a new version (e.g., `v0.x.y`)
3. Bump `requirements.txt` here when ready to commit benchmark to the new version

## Workflow Preferences

- **Always commit and push all changes** (not just code). Working data, CSV files, etc. should all be committed and pushed unless gitignored. Sync across multiple computers happens via git.
- **Never write important information only to Claude memory.** Memory files are per-machine and per-project-path — they don't sync. Anything that should persist must be written to a file in the repo.

## Windows Environment

- Python: `venv/Scripts/python.exe` (NOT `python` or `python3`)
- No `head`, `tail`, `grep`, `cut`, `which` in Git Bash — use Python one-liners or dedicated tools
- `taskkill` needs `//` prefix for flags

## Architecture

(Write 2-3 paragraphs based on ROADMAP.md: pipeline shape — build_dataset → run_model → score → scorecard. Mention the gold-DB cache, the assessor model, the three axes Real/Name/Supports.)

## Testing

```bash
venv/Scripts/python.exe -m pytest tests/ runners/tests/ -v
```
```

- [ ] **Step 3: Copy .gitignore from citation-verifier**

```bash
cp ../citation-verifier/.gitignore .gitignore
```

Review and remove any patterns that don't apply to benchmark (e.g., briefs/, scratch/citations_for_review.csv — though most are generic enough to keep).

- [ ] **Step 4: Write .env.example**

```bash
cat > .env.example <<'EOF'
# Required: CourtListener API token
# Get one at: https://www.courtlistener.com/ -> Profile -> API Keys
COURTLISTENER_API_TOKEN=your_token_here

# Required for the assessor (Opus / Sonnet via Anthropic SDK)
ANTHROPIC_API_KEY=your_key_here

# Optional: OpenAI key if running comparisons against OpenAI models
OPENAI_API_KEY=your_key_here
EOF
```

- [ ] **Step 5: Verify all four files exist**

```bash
ls README.md CLAUDE.md .gitignore .env.example
```

### Task 14: Initial commit and push to new repo

**Files:** none new, just git

- [ ] **Step 1: Stage everything**

```bash
git add -A
```

- [ ] **Step 2: Review staging**

```bash
git status
```

Expected: all the files copied from benchmark, plus the newly created config files. Note any unintended `.env` or `__pycache__/` — those should be in `.gitignore` already, but verify nothing sensitive is staged.

- [ ] **Step 3: Initial commit**

```bash
git commit -m "$(cat <<'EOF'
initial commit: spin out from citation-verifier benchmark/

Moved benchmark/ contents from public citation-verifier to this
private repo. gold_db.py becomes gold_db/ package. Imports updated
to drop the `benchmark.` prefix.

Spec: see citation-verifier docs/plans/2026-05-17-benchmark-spinout-design.md
EOF
)"
```

- [ ] **Step 4: Push to origin**

```bash
git push -u origin main
```

Expected: `* [new branch] main -> main`.

- [ ] **Step 5: Verify on GitHub**

Open https://github.com/rlfordon/case-law-proposition-benchmark in browser. Confirm repo is **private** and has all expected directories.

---

## Phase 3: Verify new repo works end-to-end

### Task 15: Fresh venv install

**Files:** none modified

- [ ] **Step 1: Create venv in new repo**

```bash
cd C:/Users/Rebecca\ Fordon/Projects/case-law-proposition-benchmark
python -m venv venv
source venv/Scripts/activate
```

- [ ] **Step 2: Install from requirements.txt**

```bash
pip install -r requirements.txt
```

Expected: pulls citation-verifier from `git+https://github.com/rlfordon/citation-verifier.git@v0.1.0`. Then resolves transitive deps.

- [ ] **Step 3: Install benchmark as editable (so `from runners import X` works)**

```bash
pip install -e .
```

Expected: installs benchmark in editable mode using `pyproject.toml`.

- [ ] **Step 4: Verify both libraries import**

```bash
python -c "from citation_verifier import CitationVerifier; from gold_db import GoldDB; print('OK')"
```

Expected output: `OK`.

If `GoldDB` import fails, check that `gold_db/__init__.py` exists and was correctly copied in Task 5.

### Task 16: Layer editable citation-verifier install on top

**Files:** none modified

- [ ] **Step 1: Replace the git-installed citation-verifier with editable**

```bash
pip install -e ../citation-verifier
```

Expected: replaces the git-URL version with the local editable copy. Any subsequent edits in `../citation-verifier/src/` are immediately visible.

- [ ] **Step 2: Verify editable install took effect**

```bash
pip show citation-verifier | grep "Location\|Editable"
```

Expected: Location points to `.../citation-verifier/src` and `Editable project location` shows.

### Task 17: Set up .env

**Files:**
- Create: `case-law-proposition-benchmark/.env`

- [ ] **Step 1: Copy .env from citation-verifier (same API tokens apply)**

```bash
cp ../citation-verifier/.env .env
```

OR copy from .env.example and fill in tokens manually if you prefer to keep them separate.

- [ ] **Step 2: Verify .env is gitignored**

```bash
git status --ignored | grep .env
```

Expected: `.env` appears as ignored.

### Task 18: Run benchmark test suite

**Files:** none modified

- [ ] **Step 1: Run pytest**

```bash
venv/Scripts/python.exe -m pytest tests/ runners/tests/ -v
```

Expected: tests pass. Some tests may hit live APIs and skip if no credentials — that's fine.

- [ ] **Step 2: Diagnose any failures**

If tests fail with `ImportError` or `ModuleNotFoundError`:
- Check that the failing import was updated in Tasks 7, 8, or 9
- Re-run the grep commands from those tasks to confirm no stale imports

If tests fail with `FileNotFoundError`:
- Likely a `PROJECT_ROOT / "benchmark" / ...` path that Task 10 missed
- Search the failing test and the production code it exercises

If tests fail with `AssertionError`:
- Genuine test failure, not a refactoring issue. Investigate and fix.

Do NOT proceed to Phase 4 until tests pass.

### Task 19: Run a small end-to-end smoke test

**Files:** none modified

The goal here is to confirm a real benchmark command works against the new repo structure.

- [ ] **Step 1: Identify a runnable command that can be exercised quickly**

Candidate: `runners/scorecard.py` reads `releases/v1/results.csv` and `releases/v1/dataset.csv`, which were copied during Task 4. It produces a scorecard markdown — no API calls needed, just file I/O and computation.

- [ ] **Step 2: Run it**

```bash
venv/Scripts/python.exe -m runners.scorecard
```

Expected: produces `releases/v1/scorecards.md` (or matches existing output). No errors.

- [ ] **Step 3: If a different smoke test is more representative, run that instead**

Examples:
- `python -c "from gold_db import GoldDB; db = GoldDB('gold_db/gold.db'); print(db.fetch_stats())"` — confirms gold_db reads existing data
- Any small unit-test-runnable script in `runners/`

The key requirement: confirms the new repo is functional with the new import paths and the citation-verifier dependency.

---

## Phase 4: Clean up citation-verifier

Only proceed here after Phase 3 passes. If Phase 3 has any failures, fix them in the new repo first.

### Task 20: Delete benchmark/ from citation-verifier

**Files in citation-verifier:**
- Delete: entire `benchmark/` directory

- [ ] **Step 1: Switch to citation-verifier**

```bash
cd ../citation-verifier
```

- [ ] **Step 2: Confirm you're on a clean branch (worktree or main, your choice)**

```bash
git status
```

If you're working from the same worktree branch (`claude/dreamy-roentgen-25df66`) where the spec lives, that's fine. Or create a new branch for the cleanup:

```bash
git checkout -b benchmark-spinout-cleanup
```

- [ ] **Step 3: Delete benchmark/**

```bash
rm -rf benchmark/
```

- [ ] **Step 4: Verify deletion**

```bash
ls benchmark/ 2>&1
```

Expected: `No such file or directory`.

### Task 21: Delete gold_db.py and test_gold_db.py from citation-verifier

**Files in citation-verifier:**
- Delete: `src/citation_verifier/gold_db.py`
- Delete: `tests/test_gold_db.py`

- [ ] **Step 1: Delete the module**

```bash
rm src/citation_verifier/gold_db.py
```

- [ ] **Step 2: Delete the test**

```bash
rm tests/test_gold_db.py
```

- [ ] **Step 3: Verify**

```bash
ls src/citation_verifier/gold_db.py 2>&1
ls tests/test_gold_db.py 2>&1
```

Expected: both report "No such file or directory".

### Task 22a: Fix the dangling supersedes reference in the design doc

**Files in citation-verifier:**
- Modify: `docs/plans/2026-05-17-benchmark-spinout-design.md`

The design doc has a header line:
```markdown
**Supersedes:** [`benchmark/docs/plans/benchmark-spinout-prep.md`](../../benchmark/docs/plans/benchmark-spinout-prep.md) (...)
```

After Phase 4 deletes `benchmark/`, the linked path no longer exists in this repo. Fix the reference so the historical context is preserved without a broken link.

- [ ] **Step 1: Edit the supersedes line**

Replace the line with a non-linked reference:

```markdown
**Supersedes:** `benchmark/docs/plans/benchmark-spinout-prep.md` (preserved in git history before commit that deleted `benchmark/` — the earlier "API-stability prep" framing, walked back in favor of moving benchmark out now)
```

The history is still browsable via `git log -- benchmark/docs/plans/benchmark-spinout-prep.md` on this repo.

### Task 22: Update citation-verifier's CLAUDE.md

**Files in citation-verifier:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Remove the "Benchmark sub-project" section**

Find this block in CLAUDE.md (around line 9-19, between "## Project Overview" and "## Workflow Preferences"):

```markdown
## Benchmark sub-project

A separate effort lives at [`benchmark/`](benchmark/) — a case-law retrieval benchmark
that depends on this verifier but is otherwise self-contained. See
[`benchmark/README.md`](benchmark/README.md) for orientation, [`benchmark/docs/plans/benchmark-roadmap.md`](benchmark/docs/plans/benchmark-roadmap.md)
for the engineering roadmap, and [`benchmark/docs/plans/2026-05-05-publication-plan.md`](benchmark/docs/plans/2026-05-05-publication-plan.md)
for the publication track.

The `gold_db.py` module under `src/citation_verifier/gold_db.py` is the
benchmark's persistence layer but ships in this package because it's
reusable infrastructure. The SQLite database, schema, and exports live
under `benchmark/gold_db/`.
```

Delete the entire section.

- [ ] **Step 2: Remove the `gold_db.py` row from the Files table**

Find this row in the "## Files / Core library" table and delete it. There may be other references — search for `gold_db` and remove or update them.

```bash
grep -n "gold_db" CLAUDE.md
```

Expected after edits: no matches, or only matches that explicitly note the file has been removed.

- [ ] **Step 3: Save and verify**

```bash
grep -n "benchmark\|gold_db" CLAUDE.md
```

Expected: no remaining references to either.

### Task 23: Fix stale comment in client.py

**Files in citation-verifier:**
- Modify: `src/citation_verifier/client.py`

- [ ] **Step 1: Locate the stale comment**

Open `src/citation_verifier/client.py` and find line 28:

```python
# fallback chains in benchmark/pilot_a/score.py.
```

- [ ] **Step 2: Remove or rewrite**

The simplest fix is to delete the comment. If it provides useful context, rewrite it without the broken cross-reference:

Before:
```python
# fallback chains in benchmark/pilot_a/score.py.
```

After (option 1, delete):
```python
(removed)
```

After (option 2, rewrite without cross-ref):
```python
# (Historical note: this opinion-text fallback chain mirrors the one used in
# the prior case-law benchmark project.)
```

Use the Edit tool. If only one of these patterns is being applied, the simpler delete is preferable.

### Task 24: Update citation-verifier's pyproject.toml

**Files in citation-verifier:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Remove `benchmark/runners/tests` from testpaths**

Open `pyproject.toml`. Find:

```toml
testpaths = ["tests", "benchmark/runners/tests"]
```

Change to:

```toml
testpaths = ["tests"]
```

- [ ] **Step 2: Bump version**

Find:
```toml
version = "0.1.0"
```

Change to:
```toml
version = "0.2.0"
```

- [ ] **Step 3: Verify pyproject.toml still parses**

```bash
python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb')); print(d['project']['version']); print(d['tool']['pytest']['ini_options']['testpaths'])"
```

Expected:
```
0.2.0
['tests']
```

### Task 25: Run citation-verifier's tests to confirm cleanup is clean

**Files:** none modified

- [ ] **Step 1: Activate citation-verifier's venv**

```bash
source venv/Scripts/activate
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/ -v
```

Expected: all tests pass. There should be no `ImportError` for `gold_db` (since `test_gold_db.py` was deleted). Tests that exercised benchmark are now gone.

- [ ] **Step 3: Diagnose any failures**

If any test fails with `ModuleNotFoundError: No module named 'citation_verifier.gold_db'`:
- A test file is still trying to import gold_db. Either delete the import (if dead code) or the test (if benchmark-specific).

If any test fails with import error for `benchmark.*`:
- Same as above. Citation-verifier should not import from `benchmark.*` anywhere — the design doc confirmed only `gold_db.py` and a comment in `client.py` had cross-references.

Do NOT proceed to commit until tests pass.

### Task 26: Commit cleanup and tag v0.2.0

**Files:** none new; staging existing changes

- [ ] **Step 1: Stage changes**

```bash
git add -A
```

- [ ] **Step 2: Review staging**

```bash
git status
```

Expected staged changes:
- Deleted: `benchmark/` (entire tree)
- Deleted: `src/citation_verifier/gold_db.py`
- Deleted: `tests/test_gold_db.py`
- Modified: `CLAUDE.md`
- Modified: `pyproject.toml`
- Modified: `src/citation_verifier/client.py`

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
cleanup: remove benchmark/ and gold_db (moved to private repo)

The benchmark sub-project moved to a private repo
case-law-proposition-benchmark. This commit removes:

- benchmark/ (entire directory)
- src/citation_verifier/gold_db.py (moved to new repo as gold_db/ package)
- tests/test_gold_db.py (moved with the module)

Also: drops benchmark/runners/tests from pyproject.toml's testpaths,
bumps version to 0.2.0, and fixes a stale cross-reference comment in
client.py.

Spec: docs/plans/2026-05-17-benchmark-spinout-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push**

If you're on main: `git push`. If you're on a branch, push that branch and merge to main via PR or directly.

- [ ] **Step 5: Tag v0.2.0**

```bash
git tag v0.2.0
git push origin v0.2.0
```

- [ ] **Step 6: Verify tag on GitHub**

Open https://github.com/rlfordon/citation-verifier/tags. Confirm `v0.2.0` appears.

---

## Phase 5: Repin new repo to v0.2.0

### Task 27: Update requirements.txt to v0.2.0

**Files in new repo:**
- Modify: `case-law-proposition-benchmark/requirements.txt`

- [ ] **Step 1: Switch back to new repo**

```bash
cd ../case-law-proposition-benchmark
```

- [ ] **Step 2: Edit requirements.txt**

Change:
```
citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.1.0
```

To:
```
citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.2.0
```

### Task 28: Reinstall and verify

**Files:** none modified

- [ ] **Step 1: Switch back to the git-pinned install (not editable)**

```bash
pip install -r requirements.txt --force-reinstall --no-deps
```

The `--no-deps` avoids reinstalling unrelated packages; `--force-reinstall` ensures the citation-verifier package is replaced with the v0.2.0 version.

- [ ] **Step 2: Verify import still works**

```bash
python -c "from citation_verifier import CitationVerifier; print('OK')"
```

Expected: `OK`. No references to `gold_db` in citation-verifier now (it lives in the benchmark repo).

- [ ] **Step 3: Re-run the smoke test from Task 19**

```bash
venv/Scripts/python.exe -m runners.scorecard  # or your chosen smoke test
```

Expected: same output as Task 19 (no breakage from the v0.2.0 bump).

- [ ] **Step 4: (Optional) re-layer editable install for ongoing dev**

```bash
pip install -e ../citation-verifier
```

This restores the editable workflow for day-to-day dev.

### Task 29: Commit the version bump in new repo

**Files:** version bump in requirements.txt is staged

- [ ] **Step 1: Stage**

```bash
git add requirements.txt
```

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
bump: citation-verifier@v0.2.0

citation-verifier@v0.2.0 is the post-spinout cleanup release
(benchmark/ removed, gold_db moved here). Verified smoke test
still passes against the new version.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push**

```bash
git push
```

---

## Success criteria checklist

Run through this after Phase 5 completes:

- [ ] New private repo `case-law-proposition-benchmark` exists and is **private** on GitHub
- [ ] `pip install -r requirements.txt` in a fresh venv installs citation-verifier@v0.2.0 from GitHub
- [ ] `python -c "from gold_db import GoldDB; from citation_verifier import CitationVerifier; print('OK')"` works
- [ ] Benchmark's test suite passes: `pytest tests/ runners/tests/ -v`
- [ ] A representative benchmark command (e.g., `runners/scorecard.py`) runs end-to-end
- [ ] Citation-verifier no longer contains `benchmark/`, `gold_db.py`, or `test_gold_db.py`
- [ ] Citation-verifier's tests pass: `pytest tests/ -v`
- [ ] Citation-verifier has `v0.2.0` tag pushed to GitHub
- [ ] Benchmark's `requirements.txt` pins `citation-verifier@v0.2.0`
- [ ] Both repos have all changes committed and pushed
- [ ] Editable install workflow (`pip install -e ../citation-verifier`) is documented in benchmark's CLAUDE.md

---

## Rollback plan

If something goes badly wrong between phases, recovery paths:

**During Phase 2 (new repo not yet pushed):** Delete the new local clone. Nothing in citation-verifier has changed yet.

**During Phase 3 (new repo pushed but verification fails):** The issue is in the new repo. Fix imports/paths there. Citation-verifier is untouched.

**During Phase 4 (citation-verifier cleanup in progress):** All changes are local. `git reset --hard HEAD` (BEFORE committing) restores the deleted files. AFTER committing, `git reset --hard HEAD~1` undoes the commit.

**After Phase 4 push but before Phase 5:** Citation-verifier is now without `benchmark/`. The new repo still has `requirements.txt` pinning `v0.1.0`, which is still a valid tag — benchmark still works. So nothing is broken; you can finish Phase 5 later.

The plan is designed so each phase is recoverable on its own.
