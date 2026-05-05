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
- v2 in design — when v2 mining produces a fresh dataset, it lands in `releases/v2/`. See [`docs/plans/2026-05-05-publication-plan.md`](docs/plans/2026-05-05-publication-plan.md) and [`docs/plans/benchmark-roadmap.md`](docs/plans/benchmark-roadmap.md)

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
