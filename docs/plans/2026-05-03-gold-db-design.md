# Gold-DB — Cumulative knowledge corpus for case-law benchmark

**Status:** Design, ready for implementation plan.
**Date:** 2026-05-03
**Predecessors:** [2026-04-30-benchmark-v1-design.md](2026-04-30-benchmark-v1-design.md), [benchmark-roadmap.md](benchmark-roadmap.md), [2026-05-02-v1.2-assessor-calibration.md](../retrospectives/2026-05-02-v1.2-assessor-calibration.md)
**Related roadmap items (subsumed):** verified-citations cache (v1.1), acceptable-alternatives caching (v1.1), per-case metadata extraction (v1.1)

## Motivation

Each benchmark run currently does redundant work: re-verifying gold cases via CourtListener, re-assessing (proposition, case) pairs we've already scored, re-mining metadata for cases we've already seen. More fundamentally, the **dataset** is single-use across major versions (contamination after publication, scope changes between v1 → v2), but the **pair-level knowledge** it surfaces — "this case supports this proposition with verdict V" — survives indefinitely.

The gold-DB is the artifact that captures that durable knowledge. It serves four roles in one structure:

1. **Build-side cache** — known cases skip CourtListener resolution
2. **Score-side cache** — known (proposition, case) verdicts skip Opus assessor calls
3. **Calibration corpus** — gold-pair self-scores are first-class data, not a noisy validation step
4. **Cumulative research artifact** — grows monotonically across v1, v2, v3 datasets; long-term, publishable on its own

## Asset hierarchy

This separation is the core conceptual move:

| Artifact | Lifetime | Role |
|---|---|---|
| **Dataset** (v1, v2, v3...) | Single major version, single mining window | Frozen test instrument — what models are graded against |
| **Gold-DB** | Cumulative across all dataset versions | Pair-keyed knowledge corpus — outlives any one dataset |
| **Score-side cache** (acceptable alternatives) | Lives inside the gold-DB | Per-(proposition, candidate-case) verdicts that any future dataset with overlapping propositions can reuse |

The dataset is single-use because publishing it contaminates it for any model trained after publication, and v2's scope expansion (circuits, SCOTUS, state courts, larger N) requires fresh content anyway. Pre-publication models can still be tested against a prior dataset as long as their training cutoff predates publication.

The gold-DB has no such expiry — every (proposition, case, verdict) tuple it accumulates remains valid as a cache hit and as research data, regardless of which dataset originally surfaced it.

## On "court-blessed" vs "actually correct"

The gold pair — citing court asserts case X supports proposition P — is a **proxy for quality**, not ground truth. Courts misrepresent cases, string-cite, and overstate holdings. When the assessor returns non-Green on a gold pair, that disagreement is itself a measurement: it's the rate at which citing courts overstate (or our retrieval misses) what cited cases really say.

**Design implication:** the gold-pair self-score is a **first-class column** in the gold-DB, not a validation gate. A gold pair where Opus says Yellow is a research datum ("citing court overstated the holding here"), not a row to discard. This baseline rate is the right comparison floor for any model's Green rate — a model at 75% isn't obviously worse than the human (judge-and-clerk) baseline of 85%.

Court tier matters too: SCOTUS clerks edit citations harder than district-court clerks, so the proxy tightens at the top of the hierarchy. The schema records `court_id` and `tier` on every case so we can break this down post-hoc.

## Entity model (graph-shaped)

The conceptual model is a small typed graph:

**Entities**
- `Case` (pk: CourtListener cluster_id; attrs: canonical_name, court, year, tier, jurisdiction)
- `Proposition` (pk: hash of normalized text; attrs: text, holding_verb, source mining run)
- `Dataset` (pk: name e.g. `v1`, `v2`; attrs: mining window, courts, frozen_at)

**Relationships**
- `Case` ──*cites*──▶ `Case`, with `parenthetical` and `proposition` as edge attributes (= `citation_rows`)
- `Proposition` ──*supported_by*──▶ `Case`, with `verdict`, `assessor_model`, `confidence` as edge attributes (= `assessor_verdicts`)
- `Proposition` ──*answered_with*──▶ `Case`, with `model`, `run_id` as edge attributes (= `model_answers`)
- `citation_rows` ──*belongs_to*──▶ `Dataset`

The unification that matters: `assessor_verdicts` is **polymorphic**. The same edge type — "assessor M says case C supports proposition P with verdict V" — covers gold-pair self-scores, model-answer scores, and ad-hoc probes. An Opus verdict scored once is reusable wherever the same (proposition, case) pair recurs, regardless of how it was originally surfaced.

## Storage choice

Conceptually graph-shaped, but **not** an actual graph DB. At our scale (low thousands of pairs growing slowly) Neo4j or RDF triplestores are operational baggage with little payoff. SQLite is the right call:

| Option | Verdict |
|---|---|
| **SQLite** with relational tables, FKs, JOINs simulating traversal | **Use this.** One file, in-repo, diffable, queryable from Python/CLI/SQL, scales to millions of rows. |
| Parquet / CSV per entity, append-only | Use **alongside** SQLite as snapshot/export format for diffability and external consumption. Not the source of truth. |
| Neo4j or RDF triplestore | Defer until we hit a real query that's painful in SQL. None on the horizon. |

**Layout:** SQLite (`gold.db`) is source of truth; CSV exports are committed alongside for diffability and external researcher access.

## Schema

```sql
-- ============ Entities ============

CREATE TABLE cases (
    cluster_id          INTEGER PRIMARY KEY,         -- CourtListener cluster ID
    canonical_name      TEXT NOT NULL,
    court_id            TEXT,                        -- CL court abbrev (e.g. 'scotus', 'ca9', 'almd')
    year                INTEGER,
    tier                TEXT,                        -- 'scotus' | 'circuit' | 'district' | 'state' | 'other'
    jurisdiction        TEXT,                        -- 'federal' | 'state' | 'tribal' | ...
    cite_string         TEXT,                        -- canonical reporter citation
    first_seen_run_id   TEXT,
    first_seen_at       TEXT NOT NULL                -- ISO 8601
);
CREATE INDEX idx_cases_court ON cases(court_id);
CREATE INDEX idx_cases_tier  ON cases(tier);

CREATE TABLE propositions (
    proposition_id      TEXT PRIMARY KEY,            -- sha256(normalized_text)
    text                TEXT NOT NULL,               -- raw text as mined
    normalized_text     TEXT NOT NULL,               -- whitespace-collapsed, lowercased
    holding_verb        TEXT,                        -- 'holding' | 'finding' | ...
    first_seen_run_id   TEXT,
    first_seen_at       TEXT NOT NULL
);
-- Note: "first row that surfaced this proposition" is derivable as
-- SELECT id FROM citation_rows WHERE proposition_id=? ORDER BY mined_at LIMIT 1
-- so we don't denormalize it on propositions (avoids chicken-and-egg insert order).

CREATE TABLE datasets (
    name                  TEXT PRIMARY KEY,          -- 'v1', 'v2', ...
    mining_window_start   DATE,
    mining_window_end     DATE,
    mined_courts          TEXT,                      -- JSON array of court IDs
    n_rows                INTEGER,
    frozen_at             TEXT,                      -- ISO 8601 when sealed
    git_commit            TEXT,                      -- citation-verifier commit at freeze
    notes                 TEXT
);

-- ============ Edges ============

-- A row from a real opinion: citing case cites cited case for a proposition.
CREATE TABLE citation_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_cluster_id   INTEGER NOT NULL REFERENCES cases(cluster_id),
    cited_cluster_id    INTEGER NOT NULL REFERENCES cases(cluster_id),
    proposition_id      TEXT    NOT NULL REFERENCES propositions(proposition_id),
    parenthetical       TEXT    NOT NULL,            -- raw parenthetical from citing opinion
    dataset_name        TEXT             REFERENCES datasets(name),  -- nullable
    mined_at            TEXT    NOT NULL,
    UNIQUE (citing_cluster_id, cited_cluster_id, proposition_id)
);
CREATE INDEX idx_citation_rows_proposition ON citation_rows(proposition_id);
CREATE INDEX idx_citation_rows_dataset     ON citation_rows(dataset_name);

-- Verdict: does this case support this proposition?
-- Polymorphic across gold-pair self-scores, model-answer scores, and probes.
CREATE TABLE assessor_verdicts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    proposition_id           TEXT    NOT NULL REFERENCES propositions(proposition_id),
    candidate_cluster_id     INTEGER NOT NULL REFERENCES cases(cluster_id),
    verdict                  TEXT    NOT NULL,      -- 'green' | 'yellow' | 'red'
    assessor_model           TEXT    NOT NULL,      -- 'opus-4.7' | ...
    assessor_prompt_version  TEXT    NOT NULL,      -- 'v1' (changing invalidates cache)
    opinion_window_chars     INTEGER,               -- 20000 | 60000 | NULL (NULL = N/A, e.g. probe without opinion text)
    confidence               REAL,                  -- 0.0–1.0 if returned, else NULL
    reasoning_excerpt        TEXT,                  -- first ~500 chars of stated reasoning
    source                   TEXT    NOT NULL,      -- 'gold_pair' | 'model_answer' | 'probe'
    run_id                   TEXT,
    assessed_at              TEXT    NOT NULL,
    UNIQUE (proposition_id, candidate_cluster_id, assessor_model, assessor_prompt_version, opinion_window_chars)
);
CREATE INDEX idx_verdicts_prop_case ON assessor_verdicts(proposition_id, candidate_cluster_id);

-- A model's answer to a proposition during a specific run.
CREATE TABLE model_answers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    proposition_id        TEXT    NOT NULL REFERENCES propositions(proposition_id),
    answer_cluster_id     INTEGER          REFERENCES cases(cluster_id),  -- NULL for UNKNOWN/unparseable
    model_name            TEXT    NOT NULL,        -- 'sonnet-4.6' | 'opus-4.7' | 'gpt-5'
    raw_response          TEXT    NOT NULL,
    parse_status          TEXT    NOT NULL,        -- 'parsed' | 'unknown' | 'unparseable' | 'hallucinated_cite'
    answered_cite_string  TEXT,                    -- model's citation string before resolution
    cite_resolved_real    BOOLEAN,
    name_match_score      REAL,
    run_id                TEXT    NOT NULL,
    answered_at           TEXT    NOT NULL
);
CREATE INDEX idx_answers_prop ON model_answers(proposition_id);
CREATE INDEX idx_answers_run  ON model_answers(run_id);

-- ============ Run metadata ============

CREATE TABLE runs (
    run_id      TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,                     -- 'mining' | 'model_eval' | 'assessor' | 'calibration'
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    git_commit  TEXT,
    notes       TEXT
);
```

## Cache hit behavior

**Build-side cache (mining).** Before calling CL citation-lookup for a citation, query `cases` by reporter cite or canonical name + year. On hit, skip CL and reuse cluster_id, canonical_name, court_id, tier.

**Score-side cache (assessing).** Before calling Opus assessor for `(proposition_id, candidate_cluster_id)`, query `assessor_verdicts` for a row matching the current `assessor_model`, `assessor_prompt_version`, and `opinion_window_chars`. On hit, reuse verdict; skip the call.

The UNIQUE constraint on `assessor_verdicts` cleanly invalidates the cache when methodology changes: switch from Opus 4.7 → 4.8, or from prompt v1 → v2, or from 20K → 60K window — and the row no longer matches, so the assessor runs again. Old verdicts persist for longitudinal analysis.

## Calibration as first-class data

The gold-pair self-score is the row in `assessor_verdicts` where:
- `proposition_id = citation_row.proposition_id`
- `candidate_cluster_id = citation_row.cited_cluster_id`
- `source = 'gold_pair'`

It's a JOIN, not a column on `citation_rows`. This is intentional: a gold pair scored once benefits **every** citation_rows row that references it (across all datasets, across all citing opinions that cite the same case for the same proposition). The polymorphism lets us compute "human/court baseline Green rate" with a one-liner: `SELECT verdict, COUNT(*) FROM assessor_verdicts WHERE source='gold_pair' GROUP BY verdict`.

## Re-checking strategy (calibration drift)

Two rules together:

1. **Methodology-change re-check:** when assessor model, prompt version, or opinion window changes, the UNIQUE constraint mechanically invalidates affected cache entries. The assessor runs again on next access. Old rows stay for longitudinal analysis.

2. **Rolling-sample re-check:** each run randomly re-checks ~10 already-cached pairs to detect silent drift. New verdict rows accumulate; if they disagree with prior rows for the same (assessor_model, prompt_version, window) tuple — that's a signal worth investigating (model API behavior changed, opinion text changed, etc.).

Skipping bulk re-check on routine runs is the right move. Cost: ~10 extra Opus calls per run; payoff: longitudinal stability time series essentially free.

## Integration with existing code

Thin Python module `src/citation_verifier/gold_db.py` (or `tests/benchmark_v1/gold_db.py` if benchmark-only is preferred — see open question below):

```python
class GoldDB:
    def __init__(self, path: str = "gold_db/gold.db"): ...

    # Idempotent upserts
    def upsert_case(self, cluster_id: int, **attrs) -> None: ...
    def upsert_proposition(self, text: str, **attrs) -> str: ...  # returns proposition_id
    def add_citation_row(self, citing, cited, proposition_id, parenthetical, dataset) -> int: ...

    # Cache-aware accessors
    def get_or_score_verdict(
        self, proposition_id: str, candidate_cluster_id: int,
        score_fn: Callable[[], VerdictResult],
        assessor_model: str, prompt_version: str, opinion_window_chars: int,
        source: str, run_id: str,
    ) -> VerdictResult: ...

    def record_model_answer(self, **fields) -> None: ...

    # Export
    def export_csvs(self, out_dir: str) -> None: ...
```

Wires into existing benchmark scripts:
- `tests/benchmark_v1/build_dataset.py` — uses `upsert_case` / `upsert_proposition` / `add_citation_row`; consults `cases` before calling CL
- `tests/benchmark_v1/run_model.py` — calls `record_model_answer` (does not score)
- `tests/benchmark_v1/score.py` — uses `get_or_score_verdict` (cache-or-call wrapper around the existing Opus assessor)

## File layout

```
gold_db/
├── gold.db                   # SQLite source of truth (committed; small for now)
├── exports/                  # Periodic CSV snapshots (committed; diffable)
│   ├── cases.csv
│   ├── propositions.csv
│   ├── citation_rows.csv
│   ├── assessor_verdicts.csv
│   └── model_answers.csv
├── schema.sql                # CREATE TABLE statements (canonical schema)
├── migrations/               # Versioned ALTER TABLE if schema changes
│   └── 001_initial.sql
└── README.md                 # Querying examples + how to consume the CSV exports
```

`gold.db` itself is committed at this scale (KB → low MB). If it grows past ~50 MB we revisit (DVC, LFS, or split the table that's blowing up).

## In scope for first cut

- Schema applied in `gold.db`
- `GoldDB` Python module with the API above
- `build_dataset.py` consults `cases` before calling CL (build-side cache)
- `score.py` uses `get_or_score_verdict` (score-side cache)
- CSV export script
- Backfill v1's existing data into the gold-DB (200 cases, ~200 propositions, ~600 model_answers, ~300 assessor_verdicts from v1's `dataset.csv` + `outputs_*.csv` + `results.csv`)
- Add gold-pair self-score pass: for every v1 citation_row, score `(proposition, gold-case)` with Opus and store as `source='gold_pair'`. ~200 calls; gives us the first calibration baseline.
- Rolling-sample re-check (~10 random pairs per run)

## Out of scope (deferred)

- Public release / DOI / external schema documentation — post v2
- Multi-hop graph queries that aren't expressible as straightforward SQL JOINs
- Migration to a graph DB
- Dedicated query CLI (use `sqlite3` + pandas for now)
- Stratified sampling tooling for v1.1 (separate work item; will *consume* the gold-DB)
- Migration plan if `gold.db` outgrows in-repo storage

## Open questions

1. **Module location:** `src/citation_verifier/gold_db.py` (treat as core library) or `tests/benchmark_v1/gold_db.py` (treat as benchmark-only)? Leaning core library since the cache logic is reusable beyond benchmarking, but the audience for v1 is benchmark scripts only.

2. **Backfill granularity:** rebuild from v1's CSVs (`benchmark_v1/dataset.csv`, `outputs_*.csv`, `results.csv`) wholesale, or only forward-fill from v2 onward and treat v1 as an external archive? **Leaning backfill** — v1's 200 rows + 600 model answers + 300 verdicts are the seed corpus, and not having them in the gold-DB defeats the cache for v1 reruns.

3. **Tier taxonomy:** `scotus | circuit | district | state | bia | tax | other`? Want to settle this before backfill so v1 cases get a tier on first insert. Defer to first implementation; revise as edge cases surface.

4. **Prompt versioning:** manual `assessor_prompt_version` string for v1. Should we hash the prompt template for automatic invalidation? Defer to v2; manual is fine while we're the only ones changing prompts.

5. **Score-side cache hit on different assessor:** if a (prop, case) pair has a `verdict='green'` from Opus 4.7 but the current run uses Opus 5.0, do we treat the Opus 4.7 verdict as a "hint" (skip with warning) or fully invalidate (rerun)? The schema fully invalidates per UNIQUE constraint — but a `--reuse-prior-assessor` flag could be useful. Defer to v2; correctness > convenience for v1.

## Success criteria

- [ ] `gold.db` exists at repo root with schema applied
- [ ] v1's data backfilled (200 cases / propositions, ~600 model_answers, ~300 assessor_verdicts, plus the new ~200 gold-pair self-scores)
- [ ] Re-running v1 with no methodology changes produces **zero** new assessor calls
- [ ] Build-side cache: `build_dataset.py` for any future dataset hits the cache for any case already in `cases`
- [ ] CSV exports diff cleanly across runs (no spurious row reordering)
- [ ] Gold-pair self-score baseline computed: distribution of Green/Yellow/Red across v1's 200 gold pairs, broken down by tier — this is the first publishable calibration result and v1.3's deliverable
