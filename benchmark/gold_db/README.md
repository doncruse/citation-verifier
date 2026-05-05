# Gold-DB

Cumulative knowledge corpus for the case-law benchmark. See
[../docs/plans/2026-05-03-gold-db-design.md](../docs/plans/2026-05-03-gold-db-design.md).

## Files

- `gold.db` — SQLite source of truth (committed)
- `migrations/001_initial.sql` — canonical schema
- `exports/*.csv` — periodic CSV snapshots (committed for diffability)

## Schema (7 tables)

- `cases` — every CL cluster_id seen, with court / system / level / canonical_name
- `propositions` — every unique proposition (sha256-normalized text as key)
- `datasets` — versioned benchmark datasets (e.g. `v1`, `v2`)
- `citation_rows` — (citing_cluster_id, cited_cluster_id, proposition_id) tuples mined from opinions
- `assessor_verdicts` — polymorphic verdicts: gold-pair self-scores, model-answer scores, drift probes
- `model_answers` — model responses to propositions, append-only across runs
- `runs` — run metadata (started_at, ended_at, kind, git_commit)

## Current counts (as of end-to-end validation, 2026-05-04)

| Metric | Count |
|--------|-------|
| propositions | 127 |
| citation_rows | 128 |
| model_answers | 381 |
| assessor_verdicts (total) | 814 |
| — v1 canonical | 804 |
| — gold_pair self-scores | 117 |
| — drift probes | 10 |

## Querying

```bash
# Distribution of gold-pair self-scores (calibration baseline)
sqlite3 benchmark/gold_db/gold.db "
  SELECT verdict, COUNT(*) FROM assessor_verdicts
   WHERE source='gold_pair' GROUP BY verdict
"
```

```bash
# Drift agreement: canonical vs drift verdicts on the same pair
sqlite3 benchmark/gold_db/gold.db "
  SELECT canonical.verdict, drift.verdict, COUNT(*)
    FROM assessor_verdicts canonical
    JOIN assessor_verdicts drift
      ON canonical.proposition_id = drift.proposition_id
     AND canonical.candidate_cluster_id = drift.candidate_cluster_id
   WHERE canonical.assessor_prompt_version = 'v1'
     AND drift.assessor_prompt_version LIKE 'v1-drift%'
   GROUP BY 1, 2
"
```

```bash
# All cached verdicts for a specific proposition (by text fragment)
sqlite3 benchmark/gold_db/gold.db "
  SELECT v.verdict, v.assessor_prompt_version, v.created_at, c.canonical_name
    FROM assessor_verdicts v
    JOIN propositions p ON p.proposition_id = v.proposition_id
    JOIN cases c        ON c.cluster_id     = v.candidate_cluster_id
   WHERE p.text LIKE '%<fragment>%'
   ORDER BY v.created_at
"
```

## CSV exports

CSVs in `benchmark/gold_db/exports/` are diff-able snapshots — one file per table.
Refresh after writes:

```bash
venv/Scripts/python.exe -c "from citation_verifier.gold_db import GoldDB; GoldDB('benchmark/gold_db/gold.db').export_csvs('benchmark/gold_db/exports')"
```

**Bool encoding in CSVs:** SQLite stores Python `bool` as `INTEGER 1/0`.
Downstream consumers reading `cite_resolved_real` from CSV will see `1`,
`0`, or empty (NULL).

## Re-running scoring

The score-side cache (Task 12) means re-running `score.py` against
unchanged data produces zero new canonical verdicts; only ~10 rolling
drift samples are added per run for stability monitoring. Drift samples
use `assessor_prompt_version=f'v1-drift-<run_id>'` and live in the same
table without colliding with canonical entries.

Drift agreement observed on first validation run (2026-05-04): 87.5%
(7/8 overlapping pairs agreed), with the single disagreement being
yellow -> green (a borderline case shifting to a more favorable verdict).

## Score.py invocation

```bash
# Full run (exercises cache + adds ~10 drift samples)
venv/Scripts/python.exe -m benchmark.runners.score

# Axes 1+2 only (no Opus calls, no drift)
venv/Scripts/python.exe -m benchmark.runners.score --skip-substance --skip-drift

# Custom run-id (useful for reproducible logs)
venv/Scripts/python.exe -m benchmark.runners.score --run-id my-run-label
```
