# Benchmark Spin-out Preparation

**Goal:** Get `citation-verifier` to a state where the benchmark can move to its own repo cleanly. Don't spin out yet — these prep tasks land in `citation-verifier` first.

**Spin-out criteria** (from `../../ROADMAP.md`): forkable kit ships, citation-verifier has stable public API, ≥2-3 external forkers, clean release story. We're at zero of those today; this doc handles the API-stability piece.

---

## 2026-05-02 status update

After scoping this, we walked back the original "do all five tasks now" framing. Three of four spin-out criteria (kit / forkers / release story) aren't met, and v1.1 has concrete work queued that's a better next mile. Doing API-stability prep months ahead of the other three criteria locks API choices before we know what v1.1 needs from the verifier.

Current decisions:

| Task | Status | Notes |
|---|---|---|
| 1. `verify-batch` CLI | **shipped, reframed** | Built and tested ([`tests/test_cli_verify_batch.py`](../../tests/test_cli_verify_batch.py)). Originally pitched as "removes 50 lines of imports from benchmark." Reality is closer to ~5 lines, AND the wire format doesn't carry eyecite FCC-flavored parses (volume/reporter/page) that benchmark currently passes via `parsed_citation_from_eyecite`. Net: the CLI is a real user-facing convenience for ad-hoc CSVs and briefs work, but it is **not** the canonical replacement for benchmark's import surface. Don't lock the wire format until v1.1 tells us what it actually needs. |
| 2. `verify --json` | **shipped, with `candidates`/`error` retained** | The required fields from the plan are present ([`tests/test_cli_verify_json.py`](../../tests/test_cli_verify_json.py)). Walked back an earlier choice to drop `candidates`/`error` for strict CSV-symmetry — those stayed useful for single-citation debugging, and the symmetry argument weakens once Task 1 isn't load-bearing. |
| 3. API.md | **deferred** | API.md is most useful paired with a publish step. Standalone, it duplicates `__init__.py` and `CLAUDE.md`. Revisit when Task 5 is imminent. |
| 4. `audit-misses` CLI | **next** | Most concrete ROI: the workflow has been hand-built twice this session (`benchmark/releases/v1/_all_cl_misses.csv` is the artifact) and the audit feeds the FLP-findings HTML, so it has a second use beyond benchmark-internal scoring. Promoted ahead of 1/3/5. |
| 5. PyPI publish | **deferred** | Without v1.1 in flight or a forker on the horizon, publishing 0.1.0 means every change to citation-verifier between now and the actual spin-out either honors a published API (paying stability cost without spin-out benefit) or drifts from it (paying publish cost without stability benefit). Revisit when v1.1 is in flight or a forker shows up. |
| 6. `citation_verifier.benchmark` helpers | **deferred** | Lower priority even in the original plan. No change. |

What changes about the spin-out plan as a whole: the gating criterion is now **v1.1 progress**, not "land 1/2/3/5 in citation-verifier." When v1.1's call patterns are known we'll know what API surface to commit to. Until then, prefer concrete pull (Task 4) and v1.1 work over speculative API stabilization.

The original task descriptions below are kept as-is for the eventual revisit.

---

## Where things stand (May 2026)

- Benchmark v1 is shipped: `benchmark/releases/v1/{report.html, courtlistener-findings.html, scorecards-deduped.md, README.md}` plus the data files. All on `main`.
- v1.1 work is queued in `../../ROADMAP.md` — mining-stage dedup, verified-citations cache, stratified sampling by tier, per-case metadata extraction, multi-source existence oracle, etc.
- Citation-verifier is not on PyPI, has no stable API doc, and the benchmark imports ~6 internal modules (parser, models, verifier, court_map, client, court_abbrev).
- This session built up substantial audit infrastructure (`benchmark/releases/v1/_all_cl_misses.csv` with 94 hand-verified rows, fallback path attribution, etc.) — those workflows are good candidates for promoting into citation-verifier as CLI commands.

---

## Tasks, priority order

The first three (#1, #2, #5) are the spin-out blockers. The rest are conveniences.

### 1. `citation-verifier verify-batch` CLI subcommand

**What:** A subcommand that takes a CSV of citations and outputs a CSV with verification results. Mirrors what `benchmark/runners/score.py` does internally today, exposed as a tool benchmark can call without importing.

**Interface:**
```bash
citation-verifier verify-batch input.csv \
    --column citation \
    [--name-column case_name --court-column court --year-column year] \
    --output verified.csv \
    [--quick-only]
```

**Output columns:** `citation` (original), `status`, `matched_cluster_id`, `matched_url`, `matched_case_name`, `matched_court_id`, `matched_date_filed`, `confidence`, `diagnostics_json`.

**Why first:** Removes the most-imported internal module (`CitationVerifier.verify_batch`) from benchmark's call surface. Replaces ~50 lines of import + scaffolding with a shell-out.

**Files to touch:** `src/citation_verifier/__main__.py` (add subcommand), tests in `tests/test_cli_verify_batch.py`.

**Acceptance:** the test should construct a 10-row input CSV, run the subcommand via subprocess, and assert the output CSV has the expected columns + correct verification statuses for known-real and known-fake citations.

---

### 2. `citation-verifier verify --json` output mode

**What:** `citation-verifier "Smith v. Jones, 100 F.3d 1 (2d Cir. 2020)" --json` prints a JSON line with the same fields as the verify-batch CSV.

**Why:** Lets downstream tools shell out for one-off verification without parsing prose stdout.

**Acceptance:** `--json` output is valid JSON with `status`, `matched_cluster_id`, `matched_url`, `matched_case_name`, `confidence`, `diagnostics` (array of `{category, message}`).

---

### 3. Document the stable public API

**What:** Add a top-level `API.md` (or section in README.md) listing what's stable vs internal.

**Stable surface (proposed):**
- `CitationVerifier` class — `verify()`, `verify_async()`, `verify_batch()`
- `parse_citation()` from `parser` (top-level convenience)
- `lookup_court_abbrev()` from `court_map`
- Models: `VerificationResult`, `VerificationStatus`, `Diagnostic`, `ParsedCitation`

**Internal (subject to change):**
- `_batch_citation_lookup`, `_opinion_search_async`, `_recap_search_async` (private methods)
- `parsed_citation_from_eyecite` (parser internals — may be replaced by `parse_citation` + extension)
- `CourtListenerClient._request_with_retry` (HTTP plumbing)
- The court_map dict structure (use `lookup_*` helpers, not the dict directly)

**Why:** Cheap doc-only change. Lets benchmark commit to a small import surface and lets future refactors break internal-only code without affecting downstream.

**Acceptance:** `API.md` exists at repo root with the two lists and a note that the public surface follows semver after the next release.

---

### 5. Publish to PyPI as `citation-verifier` (or similar)

**Why this is the spin-out unlock:** without a published package, "benchmark in its own repo" means `pip install git+https://github.com/rlfordon/citation-verifier.git@<sha>` — which breaks every time citation-verifier's `main` moves. PyPI gives benchmark a `>=X.Y` pin that's stable.

**What:**
- Pick a version (`v0.1.0` is fine — signals pre-1.0, public API may change)
- Update `pyproject.toml` with proper metadata (description, license, homepage, classifiers)
- Add a release workflow (GitHub Actions: on tag, build sdist + wheel, publish to PyPI via `pypa/gh-action-pypi-publish`)
- Test locally with `pip install -e .` then `pip install citation-verifier` in a clean venv
- Tag `v0.1.0` and publish

**Acceptance:** `pip install citation-verifier` works in a fresh venv. `python -c "from citation_verifier import CitationVerifier"` succeeds.

**Caveat:** the package name on PyPI may already be taken — check before committing to a name. If `citation-verifier` is taken, alternatives: `citation-verifier-fordon`, `cv-legal`, or rename the package internally.

---

### 4. `citation-verifier audit-misses` subcommand

**What:** Takes a CSV of NOT_FOUND citations and runs the full production fallback path (citation-lookup with chunking → opinion-search with court hint → RECAP for federal). Outputs the audit shape we hand-built in this session: `fallback_path` (opinion-search / RECAP / no_match), `matched_url`, `matched_court_id`, `matched_date_filed`.

**Why:** This is the workflow we've now done twice manually — once for the 7 pre-cliff misses, once for all 94. Both runs ate ~30 minutes of bespoke scripting. Belongs as a builtin.

**Acceptance:** `citation-verifier audit-misses _all_cl_misses.csv --output audited.csv` reproduces the relayer columns of our existing CSV.

**Lower priority because:** benchmark-specific; not a spin-out blocker. Useful for FLP-bug-report-style work generally.

---

### 6. `citation_verifier.benchmark` helper module (optional)

**What:** A small module exposing benchmark-flavored utilities:
- `classify_reporter_tier(citation_text) -> str` — returns `"SCOTUS" | "Circuit" | "District" | "WL" | "LEXIS" | "Other"`. Replaces ~30 lines of regex bucketing we re-implemented in benchmark code.
- `extract_court_abbrev(parsed) -> str | None` — friendly wrapper.
- Maybe `bucket_year(parsed) -> str` for the by-year analysis.

**Why:** Reduces coupling. Currently benchmark re-implements reporter classification regex 3-4 times across different scripts.

**Lower priority because:** convenience, not blocker. Could be deferred to v1.1.

---

## Sequence to follow

Suggested order in a session that picks this up:

1. Read this doc + `../../ROADMAP.md` + `benchmark/releases/v1/courtlistener-findings.html` (the audit shape informs the CLI design)
2. Implement Task 1 (`verify-batch` CLI) with tests — biggest unlock, ~half a day
3. Implement Task 2 (`--json` for single verify) — quick, ~hour
4. Write Task 3 (API.md) — docs only, ~hour
5. Land Task 5 (PyPI publish) — name resolution + workflow + first release, ~half a day
6. Then Task 4 + Task 6 as time permits, or defer to v1.1

After Tasks 1-3-5 land, the benchmark can plausibly move:
- `benchmark/releases/v1/` → new `case-law-retrieval-benchmark` repo
- `requirements.txt` pins `citation-verifier>=0.1`
- Audit scripts (`_relayer_fallback.py`-style work) become `citation-verifier audit-misses` shell-outs

---

## What to NOT do in the spin-out prep

- **Don't redesign the verifier.** The chunking fix and the opinion-search behavior are stable enough; touching them risks v1.1 breakage.
- **Don't pre-build the v1.1 forkable kit.** That's a separate scope item (`../../ROADMAP.md` v1.1 row).
- **Don't break existing CLI commands** (`verify-brief`, single-citation verify). The new subcommands are additive.
- **Don't move the benchmark out yet.** Land tasks 1-3-5 first.

---

## Pointers for a fresh session

If you're starting cold:

```bash
cd C:\Users\Rebecca Fordon\Projects\citation-verifier

# Existing CLI entry point (where verify-batch should be added):
src/citation_verifier/__main__.py

# Existing tests for the CLI:
tests/test_verifier.py        # core unit tests
tests/test_brief_pipeline.py  # verify-brief subcommand
# (no existing test for the verify-batch CLI subcommand because it doesn't exist yet)

# Reference for what verify-batch should do internally:
benchmark/runners/score.py   # batch-verifies 600 cells; the canonical usage pattern

# Audit scripts that motivated task 4:
benchmark/releases/v1/_all_cl_misses.csv  # the data shape audit-misses should produce

# Don't forget Windows env:
venv/Scripts/python.exe -m pytest tests/test_verifier.py -v
```

CLAUDE.md has the project conventions (Windows paths, eyecite Aho-Corasick on Windows, etc.).
