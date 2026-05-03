# Gold-DB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the gold-DB SQLite cache + Python module specified in [2026-05-03-gold-db-design.md](2026-05-03-gold-db-design.md), backfill v1's data into it, score gold-pair self-scores, and wire the build-side and score-side caches into the existing benchmark_v1 scripts.

**Architecture:** Single SQLite file at `gold_db/gold.db` with 5 tables (cases, propositions, citation_rows, assessor_verdicts, model_answers) plus a runs metadata table. Thin Python wrapper class `GoldDB` in `src/citation_verifier/gold_db.py` exposing idempotent upserts and a cache-aware `get_or_score_verdict` method. CSV exports committed alongside for diffability.

**Tech Stack:** Python 3.10+ stdlib `sqlite3`, `hashlib` (sha256 proposition hashing), `csv` (export). Tests via `pytest` with `tmp_path` fixtures. One new third-party dependency: [`courts-db`](https://github.com/freelawproject/courts-db) for court-system / level lookup (replaces a home-rolled tier table).

**Environment:** Windows + Git Bash. Python is `venv/Scripts/python.exe`. Run pytest as `venv/Scripts/python.exe -m pytest ...`. No `head`/`tail`/`grep` available — use Python or dedicated tools.

**Cost note:** Task 11 (gold-pair self-score pass) makes ~130 Opus assessor calls — real money / real quota. All other tasks are free. Pause and confirm before running Task 11's "execute on real data" step.

---

## File structure

**New files:**
- `gold_db/migrations/001_initial.sql` — canonical CREATE TABLE statements
- `gold_db/README.md` — querying examples + CSV export consumption guide
- `src/citation_verifier/gold_db.py` — `GoldDB` class + `lookup_court` utility (courts-db wrapper)
- `tests/test_gold_db.py` — unit tests (in-memory SQLite via `tmp_path`)
- `tests/benchmark_v1/backfill_gold_db.py` — one-shot script to populate gold-DB from v1 CSVs
- `tests/benchmark_v1/score_gold_pairs.py` — one-shot script to compute gold-pair self-scores
- `tests/benchmark_v1/test_backfill.py` — unit tests for backfill (small CSV fixtures)
- `tests/benchmark_v1/test_score_gold_pairs.py` — unit tests for self-score script (mocked assessor)

**Modified files:**
- `tests/benchmark_v1/build_dataset.py` — consult `cases` before CL citation-lookup
- `tests/benchmark_v1/score.py` — wrap assessor in `get_or_score_verdict`, add rolling-sample re-check
- `tests/benchmark_v1/run_model.py` — call `record_model_answer` alongside CSV write

**Generated artifacts (committed, not hand-edited):**
- `gold_db/gold.db` — SQLite database (created in Task 1; populated by Task 9 backfill + Task 11 self-scores)
- `gold_db/exports/cases.csv` etc. — written by `GoldDB.export_csvs()` after Task 8

---

## Conventions

- **TDD for every code task:** failing test first, run to confirm fail, minimal implementation, run to confirm pass, commit.
- **Each task ends with a commit** so we can bisect later.
- **Test isolation:** every test uses `tmp_path` for a fresh SQLite file. No shared state.
- **Use `venv/Scripts/python.exe -m pytest` everywhere.** Never bare `pytest` (PATH may not have it).
- **Foreign keys:** SQLite requires `PRAGMA foreign_keys = ON` per connection — wired into `GoldDB.__init__`.

---

## Task 1: Schema + GoldDB skeleton

**Files:**
- Create: `gold_db/migrations/001_initial.sql`
- Create: `src/citation_verifier/gold_db.py`
- Create: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing test for schema application**

```python
# tests/test_gold_db.py
import sqlite3
from pathlib import Path
import pytest
from citation_verifier.gold_db import GoldDB


def test_init_creates_all_tables(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    cur = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = [r[0] for r in cur.fetchall()]
    assert names == [
        "assessor_verdicts",
        "cases",
        "citation_rows",
        "datasets",
        "model_answers",
        "propositions",
        "runs",
    ]


def test_foreign_keys_enabled(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    fk = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'citation_verifier.gold_db'`

- [ ] **Step 3: Write the SQL schema**

Create `gold_db/migrations/001_initial.sql` with the contents of the schema block from [2026-05-03-gold-db-design.md](2026-05-03-gold-db-design.md) §Schema. Verbatim — all 7 `CREATE TABLE` statements (cases, propositions, datasets, citation_rows, assessor_verdicts, model_answers, runs) plus the indexes. Note that `cases` has `system` + `level` columns (from courts-db) rather than `tier` + `jurisdiction`.

- [ ] **Step 3b: Add courts-db dependency**

```bash
venv/Scripts/python.exe -m pip install courts-db
```

Then update `pyproject.toml` (or `requirements.txt` / `requirements-dev.txt` — whichever the repo uses) to declare `courts-db` as a dependency.

- [ ] **Step 4: Write the GoldDB class**

```python
# src/citation_verifier/gold_db.py
"""Cumulative knowledge corpus for the case-law benchmark.

See docs/plans/2026-05-03-gold-db-design.md for the conceptual model.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "gold_db" / "migrations" / "001_initial.sql"


class GoldDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        is_new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if is_new:
            self._apply_schema()

    def _apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -v`
Expected: PASS for both tests.

- [ ] **Step 6: Commit**

```bash
git add gold_db/migrations/001_initial.sql src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: schema + GoldDB skeleton"
```

---

## Task 2: Court-system / level lookup (via courts-db)

**Files:**
- Modify: `src/citation_verifier/gold_db.py` (add `lookup_court`)
- Modify: `tests/test_gold_db.py` (add lookup tests)

**Why courts-db, not a home-rolled enum:** [courts-db](https://github.com/freelawproject/courts-db) is the Free Law Project's authoritative court taxonomy, keyed by the same `id` as CourtListener. It exposes `system` (federal | state | tribal | extraterritorial | special) and `level` (colr | iac | gjc | ljc | trial). Using it means our taxonomy stays in sync with FLP's curation as new courts are added or reclassified.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_gold_db.py`:

```python
from citation_verifier.gold_db import lookup_court


@pytest.mark.parametrize("court_id,expected_system,expected_level", [
    ("scotus", "federal", "colr"),
    ("ca9",    "federal", "iac"),
    ("cadc",   "federal", "iac"),
    ("nysd",   "federal", "gjc"),
    ("cand",   "federal", "gjc"),
])
def test_lookup_court_known_federal(court_id, expected_system, expected_level):
    system, level = lookup_court(court_id)
    assert system == expected_system
    assert level == expected_level


def test_lookup_court_unknown_returns_none(tmp_path):
    system, level = lookup_court("definitely-not-a-court-id-12345")
    assert system is None
    assert level is None


def test_lookup_court_empty_or_none():
    assert lookup_court(None) == (None, None)
    assert lookup_court("") == (None, None)
```

The expected values for the parametrized cases come from courts-db itself; if courts-db's classification differs from what's listed (e.g. it labels `cadc` differently), update the test to match courts-db rather than the other way around.

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k lookup_court -v`
Expected: FAIL with `ImportError: cannot import name 'lookup_court'`

- [ ] **Step 3: Implement `lookup_court`**

Append to `src/citation_verifier/gold_db.py`:

```python
# Lazily build the courts-db index on first use so import is cheap.
_COURT_INDEX: dict[str, dict] | None = None


def _build_court_index() -> dict[str, dict]:
    """Load courts-db data into an id -> court-record dict.

    courts-db ships its data as a JSON list. The exact import path can
    change across versions; this helper isolates that.
    """
    try:
        from courts_db import courts as courts_list  # courts-db >= 0.10
    except ImportError:
        # Older shape: top-level module exposes data via load_courts_db()
        from courts_db import load_courts_db
        courts_list = load_courts_db()
    return {c["id"]: c for c in courts_list}


def lookup_court(court_id: str | None) -> tuple[str | None, str | None]:
    """Return (system, level) for a CourtListener court_id, or (None, None)."""
    if not court_id:
        return None, None
    global _COURT_INDEX
    if _COURT_INDEX is None:
        _COURT_INDEX = _build_court_index()
    rec = _COURT_INDEX.get(court_id)
    if not rec:
        return None, None
    return rec.get("system"), rec.get("level")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k lookup_court -v`
Expected: PASS for all cases. If a parametrized case fails because courts-db labels a court differently than expected, update the expected value to match courts-db (it's the source of truth).

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: lookup_court via courts-db (system + level)"
```

---

## Task 3: Case upsert (idempotent)

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_upsert_case_inserts(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(
        cluster_id=12345,
        canonical_name="Foo v. Bar",
        court_id="scotus",
        year=2020,
        cite_string="500 U.S. 100",
        run_id="test",
    )
    row = db.conn.execute(
        "SELECT cluster_id, canonical_name, court_id, year, system, level FROM cases"
    ).fetchone()
    assert row["cluster_id"] == 12345
    assert row["canonical_name"] == "Foo v. Bar"
    assert row["court_id"] == "scotus"
    assert row["year"] == 2020
    assert row["system"] == "federal"   # auto-looked-up from courts-db
    assert row["level"] == "colr"


def test_upsert_case_idempotent(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(cluster_id=12345, canonical_name="Foo v. Bar",
                   court_id="ca9", year=2020, cite_string=None, run_id="test")
    db.upsert_case(cluster_id=12345, canonical_name="Foo v. Bar",
                   court_id="ca9", year=2020, cite_string=None, run_id="test")
    n = db.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert n == 1


def test_upsert_case_updates_metadata(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(cluster_id=12345, canonical_name="Foo", court_id=None,
                   year=None, cite_string=None, run_id="r1")
    db.upsert_case(cluster_id=12345, canonical_name="Foo v. Bar",
                   court_id="ca9", year=2020, cite_string="900 F.2d 1",
                   run_id="r2")
    row = db.conn.execute("SELECT * FROM cases").fetchone()
    # Newer richer metadata wins; first_seen_run_id stays at 'r1'.
    assert row["canonical_name"] == "Foo v. Bar"
    assert row["court_id"] == "ca9"
    assert row["system"] == "federal"
    assert row["level"] == "iac"
    assert row["first_seen_run_id"] == "r1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k upsert_case -v`
Expected: FAIL with `AttributeError: 'GoldDB' object has no attribute 'upsert_case'`

- [ ] **Step 3: Implement `upsert_case`**

```python
import datetime as dt

def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# In GoldDB class:
def upsert_case(
    self,
    cluster_id: int,
    canonical_name: str,
    court_id: str | None,
    year: int | None,
    cite_string: str | None,
    run_id: str,
) -> None:
    system, level = lookup_court(court_id)
    self.conn.execute(
        """
        INSERT INTO cases (cluster_id, canonical_name, court_id, year, system,
                           level, cite_string, first_seen_run_id, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cluster_id) DO UPDATE SET
            canonical_name = excluded.canonical_name,
            court_id       = COALESCE(excluded.court_id, cases.court_id),
            year           = COALESCE(excluded.year, cases.year),
            system         = COALESCE(excluded.system, cases.system),
            level          = COALESCE(excluded.level,  cases.level),
            cite_string    = COALESCE(excluded.cite_string, cases.cite_string)
        """,
        (cluster_id, canonical_name, court_id, year, system, level,
         cite_string, run_id, _now_iso()),
    )
    self.conn.commit()
```

`first_seen_run_id` and `first_seen_at` only ever get set on initial insert (the `ON CONFLICT` clause doesn't touch them). `system` and `level` are derived from `court_id` via `lookup_court`; explicit overrides aren't supported in v1 — if a case is mis-classified upstream in courts-db, fix it there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k upsert_case -v`
Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: upsert_case (idempotent, COALESCE for richer metadata)"
```

---

## Task 4: Proposition upsert (hash-keyed, normalized)

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_upsert_proposition_returns_id(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid = db.upsert_proposition("The court reviews summary judgment de novo.",
                                holding_verb="reviewing", run_id="test")
    assert isinstance(pid, str)
    assert len(pid) == 64  # sha256 hex


def test_upsert_proposition_same_text_same_id(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid1 = db.upsert_proposition("Summary judgment is reviewed de novo.",
                                 holding_verb=None, run_id="r1")
    pid2 = db.upsert_proposition("Summary judgment is reviewed de novo.",
                                 holding_verb=None, run_id="r2")
    assert pid1 == pid2
    n = db.conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
    assert n == 1


def test_upsert_proposition_normalizes_whitespace_and_case(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid1 = db.upsert_proposition("Summary judgment is reviewed de novo.",
                                 holding_verb=None, run_id="r1")
    pid2 = db.upsert_proposition("summary  judgment   is\nreviewed de novo.",
                                 holding_verb=None, run_id="r2")
    assert pid1 == pid2


def test_upsert_proposition_different_text_different_id(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid1 = db.upsert_proposition("Summary judgment is reviewed de novo.",
                                 holding_verb=None, run_id="r1")
    pid2 = db.upsert_proposition("Summary judgment is reviewed for abuse of discretion.",
                                 holding_verb=None, run_id="r2")
    assert pid1 != pid2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k upsert_proposition -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement `upsert_proposition`**

Add at the top of `gold_db.py`:

```python
import hashlib


def _normalize_proposition(text: str) -> str:
    """Lowercase + collapse all whitespace runs to a single space."""
    return " ".join(text.lower().split())


def _hash_proposition(text: str) -> str:
    return hashlib.sha256(_normalize_proposition(text).encode("utf-8")).hexdigest()
```

In `GoldDB`:

```python
def upsert_proposition(
    self,
    text: str,
    holding_verb: str | None,
    run_id: str,
) -> str:
    pid = _hash_proposition(text)
    self.conn.execute(
        """
        INSERT INTO propositions (proposition_id, text, normalized_text,
                                  holding_verb, first_seen_run_id, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(proposition_id) DO NOTHING
        """,
        (pid, text, _normalize_proposition(text), holding_verb, run_id, _now_iso()),
    )
    self.conn.commit()
    return pid
```

`ON CONFLICT DO NOTHING` — proposition text is the key, so once recorded we keep the first version's text exactly. This avoids the case where a slightly different whitespace version "wins" on a later insert.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k upsert_proposition -v`
Expected: PASS for all four.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: upsert_proposition (sha256 of normalized text)"
```

---

## Task 5: Citation row insert (UNIQUE constraint)

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_add_citation_row_inserts(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(cluster_id=1, canonical_name="A", court_id="ca9",
                   year=2020, cite_string=None, run_id="t")
    db.upsert_case(cluster_id=2, canonical_name="B", court_id="ca9",
                   year=2010, cite_string=None, run_id="t")
    pid = db.upsert_proposition("Some proposition.", None, "t")
    row_id = db.add_citation_row(
        citing_cluster_id=1, cited_cluster_id=2, proposition_id=pid,
        parenthetical="holding that ...", dataset_name=None,
    )
    assert isinstance(row_id, int)
    n = db.conn.execute("SELECT COUNT(*) FROM citation_rows").fetchone()[0]
    assert n == 1


def test_add_citation_row_idempotent_on_unique(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(cluster_id=1, canonical_name="A", court_id=None,
                   year=None, cite_string=None, run_id="t")
    db.upsert_case(cluster_id=2, canonical_name="B", court_id=None,
                   year=None, cite_string=None, run_id="t")
    pid = db.upsert_proposition("Some proposition.", None, "t")
    rid1 = db.add_citation_row(1, 2, pid, "holding ...", None)
    rid2 = db.add_citation_row(1, 2, pid, "holding ...", None)
    assert rid1 == rid2  # same row returned, no duplicate
    n = db.conn.execute("SELECT COUNT(*) FROM citation_rows").fetchone()[0]
    assert n == 1


def test_add_citation_row_fk_violation_raises(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid = db.upsert_proposition("Some proposition.", None, "t")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_citation_row(999, 998, pid, "holding ...", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k add_citation_row -v`
Expected: FAIL.

- [ ] **Step 3: Implement `add_citation_row`**

```python
def add_citation_row(
    self,
    citing_cluster_id: int,
    cited_cluster_id: int,
    proposition_id: str,
    parenthetical: str,
    dataset_name: str | None,
) -> int:
    cur = self.conn.execute(
        """
        INSERT INTO citation_rows
            (citing_cluster_id, cited_cluster_id, proposition_id,
             parenthetical, dataset_name, mined_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(citing_cluster_id, cited_cluster_id, proposition_id)
        DO UPDATE SET parenthetical = excluded.parenthetical
        RETURNING id
        """,
        (citing_cluster_id, cited_cluster_id, proposition_id,
         parenthetical, dataset_name, _now_iso()),
    )
    row = cur.fetchone()
    self.conn.commit()
    return row[0]
```

`RETURNING id` (SQLite ≥ 3.35, in Python 3.10+ stdlib bundles a recent enough version on Windows). The `DO UPDATE SET parenthetical = excluded.parenthetical` keeps the parenthetical fresh on re-insert without changing the row id.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k add_citation_row -v`
Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: add_citation_row (UNIQUE-aware, RETURNING id)"
```

---

## Task 6: Verdict get + insert (no scoring wrapper yet)

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_verdict_miss_returns_none(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    result = db.get_verdict(pid, 1, "opus-4.7", "v1", 60000)
    assert result is None


def test_insert_verdict_then_get(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    db.insert_verdict(
        proposition_id=pid, candidate_cluster_id=1, verdict="green",
        assessor_model="opus-4.7", assessor_prompt_version="v1",
        opinion_window_chars=60000, confidence=0.92,
        reasoning_excerpt="The opinion holds...", source="model_answer",
        run_id="r1",
    )
    result = db.get_verdict(pid, 1, "opus-4.7", "v1", 60000)
    assert result is not None
    assert result["verdict"] == "green"
    assert result["confidence"] == 0.92


def test_get_verdict_methodology_change_misses(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    db.insert_verdict(pid, 1, "green", "opus-4.7", "v1", 60000, 0.9,
                      "...", "model_answer", "r1")
    # Different prompt version => cache miss.
    assert db.get_verdict(pid, 1, "opus-4.7", "v2", 60000) is None
    # Different window => cache miss.
    assert db.get_verdict(pid, 1, "opus-4.7", "v1", 20000) is None
    # Different model => cache miss.
    assert db.get_verdict(pid, 1, "sonnet-4.6", "v1", 60000) is None
    # Original tuple still hits.
    assert db.get_verdict(pid, 1, "opus-4.7", "v1", 60000) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k verdict -v`
Expected: FAIL.

- [ ] **Step 3: Implement `get_verdict` and `insert_verdict`**

```python
def get_verdict(
    self,
    proposition_id: str,
    candidate_cluster_id: int,
    assessor_model: str,
    assessor_prompt_version: str,
    opinion_window_chars: int | None,
) -> sqlite3.Row | None:
    cur = self.conn.execute(
        """
        SELECT * FROM assessor_verdicts
        WHERE proposition_id = ?
          AND candidate_cluster_id = ?
          AND assessor_model = ?
          AND assessor_prompt_version = ?
          AND COALESCE(opinion_window_chars, -1) = COALESCE(?, -1)
        ORDER BY assessed_at DESC
        LIMIT 1
        """,
        (proposition_id, candidate_cluster_id, assessor_model,
         assessor_prompt_version, opinion_window_chars),
    )
    return cur.fetchone()


def insert_verdict(
    self,
    proposition_id: str,
    candidate_cluster_id: int,
    verdict: str,
    assessor_model: str,
    assessor_prompt_version: str,
    opinion_window_chars: int | None,
    confidence: float | None,
    reasoning_excerpt: str | None,
    source: str,
    run_id: str | None,
) -> int:
    cur = self.conn.execute(
        """
        INSERT INTO assessor_verdicts
            (proposition_id, candidate_cluster_id, verdict, assessor_model,
             assessor_prompt_version, opinion_window_chars, confidence,
             reasoning_excerpt, source, run_id, assessed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(proposition_id, candidate_cluster_id, assessor_model,
                    assessor_prompt_version, opinion_window_chars)
        DO NOTHING
        RETURNING id
        """,
        (proposition_id, candidate_cluster_id, verdict, assessor_model,
         assessor_prompt_version, opinion_window_chars, confidence,
         reasoning_excerpt, source, run_id, _now_iso()),
    )
    row = cur.fetchone()
    self.conn.commit()
    if row is None:
        # Existing row — return its id.
        existing = self.conn.execute(
            """
            SELECT id FROM assessor_verdicts
            WHERE proposition_id=? AND candidate_cluster_id=?
              AND assessor_model=? AND assessor_prompt_version=?
              AND COALESCE(opinion_window_chars,-1) = COALESCE(?,-1)
            """,
            (proposition_id, candidate_cluster_id, assessor_model,
             assessor_prompt_version, opinion_window_chars),
        ).fetchone()
        return existing[0]
    return row[0]
```

The `COALESCE(..., -1)` dance handles SQLite's NULL semantics: NULL = NULL is unknown, not true. For our cache lookup we want NULL == NULL to be a hit, so we substitute a sentinel.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k verdict -v`
Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: get_verdict + insert_verdict (UNIQUE-aware cache)"
```

---

## Task 7: get_or_score_verdict (cache-aware wrapper)

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_or_score_cache_miss_calls_score_fn(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    calls = []

    def score_fn():
        calls.append(1)
        return {"verdict": "green", "confidence": 0.9, "reasoning": "..."}

    result = db.get_or_score_verdict(
        proposition_id=pid, candidate_cluster_id=1,
        assessor_model="opus-4.7", assessor_prompt_version="v1",
        opinion_window_chars=60000, source="model_answer", run_id="r1",
        score_fn=score_fn,
    )
    assert result["verdict"] == "green"
    assert len(calls) == 1


def test_get_or_score_cache_hit_skips_score_fn(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    calls = []

    def score_fn():
        calls.append(1)
        return {"verdict": "green", "confidence": 0.9, "reasoning": "..."}

    db.get_or_score_verdict(pid, 1, "opus-4.7", "v1", 60000,
                            "model_answer", "r1", score_fn)
    db.get_or_score_verdict(pid, 1, "opus-4.7", "v1", 60000,
                            "model_answer", "r2", score_fn)
    assert len(calls) == 1  # second call hit the cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k get_or_score -v`
Expected: FAIL.

- [ ] **Step 3: Implement `get_or_score_verdict`**

```python
from typing import Callable, TypedDict


class VerdictResult(TypedDict, total=False):
    verdict: str
    confidence: float | None
    reasoning: str | None


def get_or_score_verdict(
    self,
    proposition_id: str,
    candidate_cluster_id: int,
    assessor_model: str,
    assessor_prompt_version: str,
    opinion_window_chars: int | None,
    source: str,
    run_id: str | None,
    score_fn: Callable[[], VerdictResult],
) -> sqlite3.Row:
    cached = self.get_verdict(
        proposition_id, candidate_cluster_id, assessor_model,
        assessor_prompt_version, opinion_window_chars,
    )
    if cached is not None:
        return cached
    result = score_fn()
    reasoning = result.get("reasoning")
    self.insert_verdict(
        proposition_id=proposition_id,
        candidate_cluster_id=candidate_cluster_id,
        verdict=result["verdict"],
        assessor_model=assessor_model,
        assessor_prompt_version=assessor_prompt_version,
        opinion_window_chars=opinion_window_chars,
        confidence=result.get("confidence"),
        reasoning_excerpt=reasoning[:500] if reasoning else None,
        source=source,
        run_id=run_id,
    )
    return self.get_verdict(
        proposition_id, candidate_cluster_id, assessor_model,
        assessor_prompt_version, opinion_window_chars,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k get_or_score -v`
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: get_or_score_verdict (cache-aware scoring wrapper)"
```

---

## Task 8: Model answer recording + run metadata + CSV export

**Files:**
- Modify: `src/citation_verifier/gold_db.py`
- Modify: `tests/test_gold_db.py`

- [ ] **Step 1: Write failing tests**

```python
def test_record_model_answer(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    db.record_model_answer(
        proposition_id=pid, answer_cluster_id=1, model_name="opus-4.7",
        raw_response="Foo v. Bar, 100 F.3d 1 (9th Cir. 2020)",
        parse_status="parsed", answered_cite_string="100 F.3d 1",
        cite_resolved_real=True, name_match_score=0.95, run_id="v1",
    )
    n = db.conn.execute("SELECT COUNT(*) FROM model_answers").fetchone()[0]
    assert n == 1


def test_record_model_answer_unknown(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid = db.upsert_proposition("p", None, "t")
    db.record_model_answer(
        proposition_id=pid, answer_cluster_id=None, model_name="sonnet-4.6",
        raw_response="UNKNOWN", parse_status="unknown",
        answered_cite_string=None, cite_resolved_real=None,
        name_match_score=None, run_id="v1",
    )
    row = db.conn.execute("SELECT * FROM model_answers").fetchone()
    assert row["answer_cluster_id"] is None
    assert row["parse_status"] == "unknown"


def test_start_and_end_run(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.start_run("v1-rerun-2026-05-03", kind="model_eval", git_commit="abc123",
                 notes="rerun for cache validation")
    db.end_run("v1-rerun-2026-05-03")
    row = db.conn.execute(
        "SELECT * FROM runs WHERE run_id=?", ("v1-rerun-2026-05-03",)
    ).fetchone()
    assert row["kind"] == "model_eval"
    assert row["git_commit"] == "abc123"
    assert row["ended_at"] is not None


def test_export_csvs(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    out = tmp_path / "exports"
    db.export_csvs(out)
    cases_csv = (out / "cases.csv").read_text(encoding="utf-8")
    assert "cluster_id" in cases_csv  # header
    assert "1," in cases_csv or ",1," in cases_csv  # data row
    # Every table has its CSV
    for name in ["cases", "propositions", "citation_rows",
                 "assessor_verdicts", "model_answers", "datasets", "runs"]:
        assert (out / f"{name}.csv").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -k "model_answer or run or export" -v`
Expected: FAIL.

- [ ] **Step 3: Implement the three methods**

```python
import csv

def record_model_answer(
    self,
    proposition_id: str,
    answer_cluster_id: int | None,
    model_name: str,
    raw_response: str,
    parse_status: str,
    answered_cite_string: str | None,
    cite_resolved_real: bool | None,
    name_match_score: float | None,
    run_id: str,
) -> int:
    cur = self.conn.execute(
        """
        INSERT INTO model_answers
            (proposition_id, answer_cluster_id, model_name, raw_response,
             parse_status, answered_cite_string, cite_resolved_real,
             name_match_score, run_id, answered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (proposition_id, answer_cluster_id, model_name, raw_response,
         parse_status, answered_cite_string, cite_resolved_real,
         name_match_score, run_id, _now_iso()),
    )
    rid = cur.fetchone()[0]
    self.conn.commit()
    return rid


def start_run(
    self,
    run_id: str,
    kind: str,
    git_commit: str | None = None,
    notes: str | None = None,
) -> None:
    self.conn.execute(
        "INSERT INTO runs (run_id, kind, started_at, git_commit, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, kind, _now_iso(), git_commit, notes),
    )
    self.conn.commit()


def end_run(self, run_id: str) -> None:
    self.conn.execute(
        "UPDATE runs SET ended_at=? WHERE run_id=?",
        (_now_iso(), run_id),
    )
    self.conn.commit()


def export_csvs(self, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = ["cases", "propositions", "datasets", "citation_rows",
              "assessor_verdicts", "model_answers", "runs"]
    for t in tables:
        cur = self.conn.execute(f"SELECT * FROM {t} ORDER BY 1")
        cols = [d[0] for d in cur.description]
        with (out / f"{t}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in cur.fetchall():
                w.writerow([row[c] for c in cols])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py -v`
Expected: ALL PASS (this is the full GoldDB unit test suite).

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/gold_db.py tests/test_gold_db.py
git commit -m "gold-DB: model_answers, runs, CSV export"
```

---

## Task 9: Backfill v1 from CSVs (with dedup)

**Files:**
- Create: `tests/benchmark_v1/backfill_gold_db.py`
- Create: `tests/benchmark_v1/test_backfill.py`

**Background:** v1's `dataset.csv` has 200 rows but only ~130 unique (proposition, gold-case) pairs after dedup (eyecite duplication bug). The backfill script does six passes:

1. **Pass 1 — `dataset.csv`:** dedup by `(_normalize_proposition(proposition), gold_cluster_id)`; insert cases (citing + cited), propositions, citation_rows (with `dataset_name='v1'`). Gold cluster_id extracted from `v_url` via regex.
2. **Pass 2 — `outputs_*.csv` × 3:** dedup model_answers by `(proposition_id, model_name)`; insert model_answers (without verdicts, those come in pass 3).
3. **Pass 3 — `results.csv`:** fill in `answer_cluster_id` / `cite_resolved_real` / `name_match_score` on existing model_answers; insert `assessor_verdicts` with `source='model_answer'`, `assessor_model='opus-4.7'`, `assessor_prompt_version='v1'`, `opinion_window_chars=20000` (v1's actual window).
4. **Pass 4 — `truncation_experiment_60k.csv`:** insert `assessor_verdicts` for the ~22 Reds re-scored at 60K, with `assessor_model='opus-4.7'`, `assessor_prompt_version='v1'`, `opinion_window_chars=60000`. These are *additional* rows on top of the 20K verdicts from pass 3 (different `opinion_window_chars` ⇒ different UNIQUE key ⇒ no collision).
5. **Pass 5 — `calibration_results.csv`:** insert `assessor_verdicts` with `assessor_model='sonnet-4.6'` or `'haiku-4.5'`, `opinion_window_chars=20000` (calibration ran at 20K). Joins with `results.csv` to recover `matched_cluster_id` (calibration CSV records `id` only).
6. **Pass 6 — sanity:** print final counts.

The `v_url` format is `https://www.courtlistener.com/opinion/{cluster_id}/...` — pull cluster_id with regex.

- [ ] **Step 1: Write failing test on small fixture**

```python
# tests/benchmark_v1/test_backfill.py
from pathlib import Path
import csv
import pytest
from citation_verifier.gold_db import GoldDB
from tests.benchmark_v1.backfill_gold_db import backfill_v1


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_backfill_dedupes_propositions(tmp_path: Path):
    bench = tmp_path / "benchmark_v1"
    bench.mkdir()
    # Two rows with the same (proposition, gold_cluster_id) pair — the
    # eyecite duplication scenario.
    _write_csv(bench / "dataset.csv", [
        {"id": "1", "court": "ca9", "proposition": "Standard of review.",
         "gold_name": "Foo v. Bar", "gold_cite": "100 F.3d 1",
         "citing_cluster_id": "999", "citing_year": "2024", "cited_year": "2010",
         "v_status": "VERIFIED",
         "v_url": "https://www.courtlistener.com/opinion/12345/foo/",
         "v_matched_name": "Foo v. Bar"},
        {"id": "2", "court": "ca9", "proposition": "standard  of\nreview.",  # whitespace dup
         "gold_name": "Foo v. Bar", "gold_cite": "100 F.3d 1",
         "citing_cluster_id": "999", "citing_year": "2024", "cited_year": "2010",
         "v_status": "VERIFIED",
         "v_url": "https://www.courtlistener.com/opinion/12345/foo/",
         "v_matched_name": "Foo v. Bar"},
    ], cols=["id", "court", "proposition", "gold_name", "gold_cite",
             "citing_cluster_id", "citing_year", "cited_year",
             "v_status", "v_url", "v_matched_name"])
    # No outputs_*.csv or results.csv — backfill should still complete
    db_path = tmp_path / "gold.db"
    db = GoldDB(db_path)
    backfill_v1(db, bench, run_id="v1-backfill-test")
    # 1 unique proposition, 1 cited case, 1 citing case, 1 citation_row
    assert db.conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2
    assert db.conn.execute("SELECT COUNT(*) FROM citation_rows").fetchone()[0] == 1


def test_backfill_extracts_cluster_id_from_url(tmp_path: Path):
    from tests.benchmark_v1.backfill_gold_db import _cluster_id_from_url
    assert _cluster_id_from_url(
        "https://www.courtlistener.com/opinion/12345/foo/") == 12345
    assert _cluster_id_from_url(
        "https://www.courtlistener.com/opinion/9876543/foo-v-bar/") == 9876543
    assert _cluster_id_from_url("not a cl url") is None
    assert _cluster_id_from_url("") is None
    assert _cluster_id_from_url(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/benchmark_v1/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.benchmark_v1.backfill_gold_db'`

- [ ] **Step 3: Implement the backfill script**

```python
# tests/benchmark_v1/backfill_gold_db.py
"""Backfill v1's CSV outputs into gold-DB.

Reads benchmark_v1/{dataset.csv, outputs_*.csv, results.csv}, dedupes,
and populates the gold-DB. Idempotent: rerunning on a populated DB
inserts only what's missing.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.gold_db import GoldDB, _normalize_proposition  # noqa: E402

_CL_URL_RE = re.compile(r"courtlistener\.com/opinion/(\d+)/")


def _cluster_id_from_url(url: str | None) -> int | None:
    if not url:
        return None
    m = _CL_URL_RE.search(url)
    return int(m.group(1)) if m else None


def _safe_int(s: str | None) -> int | None:
    if s in (None, "", "None"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _safe_float(s: str | None) -> float | None:
    if s in (None, "", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_bool(s: str | None) -> bool | None:
    if s in (None, "", "None"):
        return None
    return s.strip().lower() in ("true", "1", "yes", "y")


def backfill_v1(db: GoldDB, bench_dir: Path, run_id: str) -> dict:
    """Returns a dict of insertion counts for assertion in tests."""
    counts = {"cases": 0, "propositions": 0, "citation_rows": 0,
              "model_answers": 0, "verdicts": 0}

    db.start_run(run_id, kind="backfill", notes=f"backfill from {bench_dir}")

    # Register the dataset.
    db.conn.execute(
        """INSERT OR IGNORE INTO datasets (name, mining_window_start,
                  mining_window_end, mined_courts, n_rows, frozen_at, notes)
           VALUES ('v1', '2026-01-01', '2026-04-30',
                   '[\"dcd\",\"cand\",\"txsd\",\"ilnd\",\"nysd\",\"mad\"]',
                   130, ?, 'effective N=130 after eyecite dedup')""",
        (run_id,),  # using run_id timestamp as frozen_at proxy
    )
    db.conn.commit()

    # Pass 1: dataset.csv -> cases + propositions + citation_rows (deduped).
    seen_pairs: set[tuple[str, int]] = set()
    proposition_id_by_text: dict[str, str] = {}
    dataset_path = bench_dir / "dataset.csv"
    if dataset_path.exists():
        with dataset_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cited_id = _cluster_id_from_url(row.get("v_url"))
                citing_id = _safe_int(row.get("citing_cluster_id"))
                if cited_id is None or citing_id is None:
                    continue
                norm = _normalize_proposition(row.get("proposition") or "")
                if not norm:
                    continue
                pair = (norm, cited_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                db.upsert_case(
                    cluster_id=citing_id,
                    canonical_name=f"<citing-{citing_id}>",  # placeholder
                    court_id=row.get("court") or None,
                    year=_safe_int(row.get("citing_year")),
                    cite_string=None,
                    run_id=run_id,
                )
                counts["cases"] += 1

                db.upsert_case(
                    cluster_id=cited_id,
                    canonical_name=row.get("v_matched_name") or row.get("gold_name") or "",
                    court_id=None,  # not in dataset.csv; system/level NULL until v1.x metadata pass
                    year=_safe_int(row.get("cited_year")),
                    cite_string=row.get("gold_cite"),
                    run_id=run_id,
                )
                counts["cases"] += 1

                pid = db.upsert_proposition(
                    text=row.get("proposition"),
                    holding_verb=None,
                    run_id=run_id,
                )
                proposition_id_by_text[norm] = pid
                counts["propositions"] += 1

                db.add_citation_row(
                    citing_cluster_id=citing_id,
                    cited_cluster_id=cited_id,
                    proposition_id=pid,
                    parenthetical=row.get("proposition") or "",
                    dataset_name="v1",
                )
                counts["citation_rows"] += 1

    # Pass 2: outputs_*.csv -> model_answers (deduped per (prop, model)).
    seen_answers: set[tuple[str, str]] = set()
    for model_file, model_name in [
        ("outputs_sonnet.csv", "sonnet-4.6"),
        ("outputs_opus.csv",   "opus-4.7"),
        ("outputs_gpt5.csv",   "gpt-5"),
    ]:
        p = bench_dir / model_file
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                norm = _normalize_proposition(row.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid is None:
                    continue
                key = (pid, model_name)
                if key in seen_answers:
                    continue
                seen_answers.add(key)
                db.record_model_answer(
                    proposition_id=pid,
                    answer_cluster_id=None,  # filled from results.csv pass below
                    model_name=model_name,
                    raw_response=row.get("model_response") or "",
                    parse_status="parsed",  # refined in pass 3
                    answered_cite_string=None,
                    cite_resolved_real=None,
                    name_match_score=None,
                    run_id="v1",
                )
                counts["model_answers"] += 1

    # Pass 3: results.csv -> backfill answer_cluster_id + verdicts.
    seen_verdicts: set[tuple[str, int, str]] = set()
    results_path = bench_dir / "results.csv"
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                norm = _normalize_proposition(row.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid is None:
                    continue
                model = {
                    "sonnet": "sonnet-4.6",
                    "opus":   "opus-4.7",
                    "gpt-5":  "gpt-5",
                }.get(row.get("model"), row.get("model"))
                ans_id = _safe_int(row.get("matched_cluster_id"))

                # Update model_answer (fill in fields we now know)
                db.conn.execute(
                    """
                    UPDATE model_answers
                       SET answer_cluster_id = COALESCE(?, answer_cluster_id),
                           cite_resolved_real = ?,
                           name_match_score   = ?,
                           parse_status       = ?
                     WHERE proposition_id = ? AND model_name = ?
                    """,
                    (ans_id,
                     _parse_bool(row.get("real")),
                     _safe_float(row.get("name_match")),
                     "parsed" if (row.get("model_response") or "").strip()
                                 .upper() != "UNKNOWN" else "unknown",
                     pid, model),
                )

                # Verdict (only when there's an actual answer case).
                supports = (row.get("supports") or "").strip().lower()
                if ans_id is not None and supports in ("green", "yellow", "red"):
                    # Ensure the answer case exists in cases.
                    db.upsert_case(
                        cluster_id=ans_id,
                        canonical_name=row.get("matched_cl_name") or "",
                        court_id=None,
                        year=None,
                        cite_string=row.get("extracted_citation"),
                        run_id="v1",
                    )
                    counts["cases"] += 1

                    key = (pid, ans_id, model)
                    if key in seen_verdicts:
                        continue
                    seen_verdicts.add(key)
                    db.insert_verdict(
                        proposition_id=pid,
                        candidate_cluster_id=ans_id,
                        verdict=supports,
                        assessor_model="opus-4.7",
                        assessor_prompt_version="v1",
                        opinion_window_chars=20000,  # v1's actual window
                        confidence=None,
                        reasoning_excerpt=row.get("support_rationale"),
                        source="model_answer",
                        run_id="v1",
                    )
                    counts["verdicts"] += 1
        db.conn.commit()

    # Pass 4: truncation_experiment_60k.csv -> Opus 60K verdicts.
    counts["truncation_verdicts"] = _backfill_truncation(
        db, bench_dir, run_id, proposition_id_by_text)

    # Pass 5: calibration_results.csv -> Sonnet/Haiku verdicts.
    counts["calibration_verdicts"] = _backfill_calibration(
        db, bench_dir, run_id, proposition_id_by_text)

    db.end_run(run_id)
    return counts


def _backfill_truncation(
    db: GoldDB, bench_dir: Path, run_id: str,
    proposition_id_by_text: dict[str, str],
) -> int:
    """Pass 4: insert Opus 60K re-scored verdicts on Reds."""
    p = bench_dir / "truncation_experiment_60k.csv"
    if not p.exists():
        return 0
    n = 0
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ans_id = _safe_int(row.get("matched_cluster_id"))
            if ans_id is None:
                continue
            norm = _normalize_proposition(row.get("proposition") or "")
            pid = proposition_id_by_text.get(norm)
            if pid is None:
                # Proposition not in dataset.csv (shouldn't happen, but skip safely)
                continue
            verdict = (row.get("new_supports") or "").strip().lower()
            if verdict not in ("green", "yellow", "red"):
                continue
            db.insert_verdict(
                proposition_id=pid,
                candidate_cluster_id=ans_id,
                verdict=verdict,
                assessor_model="opus-4.7",
                assessor_prompt_version="v1",
                opinion_window_chars=60000,
                confidence=None,
                reasoning_excerpt=(row.get("new_rationale") or "")[:500],
                source="model_answer",
                run_id=run_id,
            )
            n += 1
    db.conn.commit()
    return n


def _backfill_calibration(
    db: GoldDB, bench_dir: Path, run_id: str,
    proposition_id_by_text: dict[str, str],
) -> int:
    """Pass 5: insert Sonnet/Haiku verdicts from the calibration study.

    calibration_results.csv has (id, model_under_test, candidate_model,
    candidate_verdict, ...) but no proposition text or matched_cluster_id.
    Recover matched_cluster_id by joining results.csv on (id, model).
    Recover proposition by joining dataset.csv on id.
    """
    cal_path = bench_dir / "calibration_results.csv"
    if not cal_path.exists():
        return 0

    # Join lookup: (model, id) -> matched_cluster_id (from results.csv)
    results_lookup: dict[tuple[str, str], int] = {}
    results_path = bench_dir / "results.csv"
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                mc = _safe_int(r.get("matched_cluster_id"))
                if mc is not None:
                    results_lookup[(r["model"], r["id"])] = mc

    # Lookup id -> proposition_id (from dataset.csv normalized text)
    id_to_pid: dict[str, str] = {}
    dataset_path = bench_dir / "dataset.csv"
    if dataset_path.exists():
        with dataset_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                norm = _normalize_proposition(r.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid:
                    id_to_pid[r["id"]] = pid

    # Map calibration's model strings to our canonical names
    cand_model_map = {
        "sonnet": "sonnet-4.6",
        "haiku":  "haiku-4.5",
        "opus":   "opus-4.7",
    }

    n = 0
    with cal_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("error") or "").strip():
                continue
            verdict = (row.get("candidate_verdict") or "").strip().lower()
            if verdict not in ("green", "yellow", "red"):
                continue
            mut = row.get("model_under_test")
            ans_id = results_lookup.get((mut, row["id"]))
            if ans_id is None:
                continue
            pid = id_to_pid.get(row["id"])
            if pid is None:
                continue
            cand_model = cand_model_map.get(
                row.get("candidate_model"), row.get("candidate_model"))
            db.insert_verdict(
                proposition_id=pid,
                candidate_cluster_id=ans_id,
                verdict=verdict,
                assessor_model=cand_model,
                assessor_prompt_version="v1",
                opinion_window_chars=20000,
                confidence=None,
                reasoning_excerpt=(row.get("candidate_rationale") or "")[:500],
                source="model_answer",
                run_id=run_id,
            )
            n += 1
    db.conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-dir", default="benchmark_v1")
    ap.add_argument("--db-path", default="gold_db/gold.db")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    run_id = args.run_id or f"v1-backfill-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    db = GoldDB(args.db_path)
    counts = backfill_v1(db, Path(args.bench_dir), run_id)
    print("Backfill complete:")
    for k, v in counts.items():
        print(f"  {k}: {v} insert attempts (some may have been deduped via UNIQUE)")
    actual = {
        t: db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("cases", "propositions", "citation_rows",
                  "model_answers", "assessor_verdicts")
    }
    print("Final row counts:")
    for k, v in actual.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/benchmark_v1/test_backfill.py -v`
Expected: PASS for both fixture tests.

- [ ] **Step 5: Run on real v1 data**

```bash
venv/Scripts/python.exe -m tests.benchmark_v1.backfill_gold_db
```

Expected output (approximate):
```
Final row counts:
  cases: ~150-300            # gold + citing + answer (overlap), plus answer cases for calibration
  propositions: 130
  citation_rows: 130
  model_answers: 390         # 130 × 3
  assessor_verdicts: ~700    # ~190 (Opus 20K, pass 3)
                             # + ~22 (Opus 60K truncation, pass 4)
                             # + ~500 (Sonnet+Haiku 20K calibration, pass 5; 514 calls × ~half non-error)
```

If propositions ≠ 130 exactly, investigate before committing. The dedup target is documented as 130; deviations indicate either the dedup rule needs tightening or the source data has more variance than the v1 retrospective recorded.

- [ ] **Step 6: Verify with sanity queries**

```bash
venv/Scripts/python.exe -c "
from citation_verifier.gold_db import GoldDB
db = GoldDB('gold_db/gold.db')
print('Tier distribution of cited (gold) cases:')
for r in db.conn.execute('''
    SELECT c.system, c.level, COUNT(*) FROM citation_rows cr
    JOIN cases c ON c.cluster_id = cr.cited_cluster_id
    WHERE cr.dataset_name = 'v1'
    GROUP BY c.system, c.level ORDER BY 3 DESC
'''):
    print(f'  {r[0]}: {r[1]}')
"
```

Expected: most rows have `system=NULL` and `level=NULL` (we didn't populate court_id for cited cases in dataset.csv — that's a separate metadata pass, deferred). Document this in the task summary; v1.x can do a one-shot CL metadata fetch later, after which `lookup_court` will populate system/level on the existing rows via the COALESCE in `upsert_case`.

- [ ] **Step 7: Commit**

```bash
git add tests/benchmark_v1/backfill_gold_db.py tests/benchmark_v1/test_backfill.py gold_db/gold.db gold_db/exports/
venv/Scripts/python.exe -c "from citation_verifier.gold_db import GoldDB; GoldDB('gold_db/gold.db').export_csvs('gold_db/exports')"
git add gold_db/exports/
git commit -m "gold-DB: backfill v1 (130 props/rows, ~390 answers, ~190 Opus-20K + ~22 Opus-60K + ~500 calibration verdicts)"
```

---

## Task 10: Gold-pair self-score pass

**Files:**
- Create: `tests/benchmark_v1/score_gold_pairs.py`
- Create: `tests/benchmark_v1/test_score_gold_pairs.py`

**Cost:** ~130 Opus assessor calls. **Pause and confirm with user before Step 5 (running on real data).**

The script iterates every `citation_rows` row in `dataset_name='v1'`, calls the existing Pilot A `call_assessor` with `(proposition, gold_case_name, gold_opinion_text)`, and stores the verdict via `db.get_or_score_verdict(..., source='gold_pair')`. Since `get_or_score_verdict` is cache-aware, reruns are zero-cost.

- [ ] **Step 1: Write failing test (mocked assessor)**

```python
# tests/benchmark_v1/test_score_gold_pairs.py
from pathlib import Path
from unittest.mock import MagicMock
from citation_verifier.gold_db import GoldDB
from tests.benchmark_v1.score_gold_pairs import score_gold_pairs


def _seed(db: GoldDB) -> tuple[str, int]:
    db.upsert_case(1, "Citing v. Court", "ca9", 2024, None, "t")
    db.upsert_case(2, "Foo v. Bar", "ca9", 2010, None, "t")
    pid = db.upsert_proposition("Standard of review.", None, "t")
    db.add_citation_row(1, 2, pid, "holding ...", "v1")
    return pid, 2


def test_score_gold_pairs_calls_assessor_per_pair(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid, cid = _seed(db)
    fake = MagicMock(return_value={
        "verdict": "green", "confidence": 0.9, "reasoning": "..."
    })
    n = score_gold_pairs(db, run_id="t-1", assessor_fn=fake)
    assert n == 1
    fake.assert_called_once()
    row = db.get_verdict(pid, cid, "opus-4.7", "v1", 60000)
    assert row["source"] == "gold_pair"
    assert row["verdict"] == "green"


def test_score_gold_pairs_skips_cached(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid, cid = _seed(db)
    fake = MagicMock(return_value={
        "verdict": "green", "confidence": 0.9, "reasoning": "..."
    })
    score_gold_pairs(db, run_id="t-1", assessor_fn=fake)
    score_gold_pairs(db, run_id="t-2", assessor_fn=fake)
    assert fake.call_count == 1  # second run hit cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/benchmark_v1/test_score_gold_pairs.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the script**

```python
# tests/benchmark_v1/score_gold_pairs.py
"""Score every v1 (proposition, gold-case) pair with Opus.

Establishes the calibration baseline: how often does Opus agree that the
gold case supports the gold proposition? Cache-aware via gold-DB.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.gold_db import GoldDB  # noqa: E402

OPINION_WINDOW = 60000  # post v1.1 standard
ASSESSOR_MODEL = "opus-4.7"
PROMPT_VERSION = "v1"


def _load_pilot_assessor():
    """Import call_assessor from pilot_a/score.py without name collision."""
    p = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
    spec = importlib.util.spec_from_file_location("pilot_a_score", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pilot_a_score"] = mod
    spec.loader.exec_module(mod)
    return mod


def _default_assessor(proposition: str, case_name: str, opinion_text: str) -> dict:
    pilot = _load_pilot_assessor()
    # call_assessor returns the existing tuple-of-(verdict, rationale, cost)
    verdict, rationale, _cost = pilot.call_assessor(
        proposition, case_name, opinion_text, model="opus",
    )
    return {"verdict": verdict.lower(), "confidence": None, "reasoning": rationale}


def score_gold_pairs(
    db: GoldDB,
    run_id: str,
    assessor_fn: Callable[[str, str, str], dict] | None = None,
) -> int:
    """Score every v1 citation_row's (proposition, cited-case) pair.

    Returns the number of new verdicts recorded (cache hits skipped).
    """
    if assessor_fn is None:
        assessor_fn = _default_assessor

    db.start_run(run_id, kind="calibration",
                 notes="gold-pair self-score baseline")

    rows = db.conn.execute("""
        SELECT cr.proposition_id, cr.cited_cluster_id, p.text AS prop_text,
               c.canonical_name AS case_name
          FROM citation_rows cr
          JOIN propositions p ON p.proposition_id = cr.proposition_id
          JOIN cases c ON c.cluster_id = cr.cited_cluster_id
         WHERE cr.dataset_name = 'v1'
    """).fetchall()

    new_verdicts = 0
    for r in rows:
        # Cache check first to avoid expensive opinion fetch on hits
        cached = db.get_verdict(r["proposition_id"], r["cited_cluster_id"],
                                ASSESSOR_MODEL, PROMPT_VERSION, OPINION_WINDOW)
        if cached is not None:
            continue

        # Fetch opinion text via Pilot A's helper (uses CL + cache)
        pilot = _load_pilot_assessor()
        opinion_text = pilot.fetch_opinion_text(r["cited_cluster_id"])
        if not opinion_text:
            print(f"WARN: no opinion text for cluster {r['cited_cluster_id']}, skipping")
            continue

        truncated = opinion_text[:OPINION_WINDOW]
        result = assessor_fn(r["prop_text"], r["case_name"], truncated)

        db.insert_verdict(
            proposition_id=r["proposition_id"],
            candidate_cluster_id=r["cited_cluster_id"],
            verdict=result["verdict"],
            assessor_model=ASSESSOR_MODEL,
            assessor_prompt_version=PROMPT_VERSION,
            opinion_window_chars=OPINION_WINDOW,
            confidence=result.get("confidence"),
            reasoning_excerpt=(result.get("reasoning") or "")[:500],
            source="gold_pair",
            run_id=run_id,
        )
        new_verdicts += 1
        if new_verdicts % 10 == 0:
            print(f"  scored {new_verdicts} new pairs...")

    db.end_run(run_id)
    return new_verdicts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default="gold_db/gold.db")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    run_id = args.run_id or f"v1-goldpair-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    db = GoldDB(args.db_path)
    n = score_gold_pairs(db, run_id)
    print(f"Done. {n} new verdicts recorded.")
    print("Distribution:")
    for r in db.conn.execute("""
        SELECT verdict, COUNT(*) FROM assessor_verdicts
         WHERE source='gold_pair'
         GROUP BY verdict
    """):
        print(f"  {r[0]}: {r[1]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/benchmark_v1/test_score_gold_pairs.py -v`
Expected: PASS for both.

- [ ] **Step 5: Pause and confirm with user before running on real data**

This step costs ~130 Opus calls. Confirm with user that they want to proceed and that quota / API budget is available.

After confirmation:

```bash
venv/Scripts/python.exe -m tests.benchmark_v1.score_gold_pairs
```

Expected output (approximate; depends on whether Opus agrees with citing courts):
```
  scored 10 new pairs...
  scored 20 new pairs...
  ...
  scored 130 new pairs...
Done. 130 new verdicts recorded.
Distribution:
  green: ~110
  yellow: ~15
  red: ~5
```

The exact distribution is the headline result for v1.3. Whatever the Yellow + Red rate is, that's the citing-court-overstates rate as judged by Opus on a 60K window.

- [ ] **Step 6: Re-export CSVs and commit**

```bash
venv/Scripts/python.exe -c "from citation_verifier.gold_db import GoldDB; GoldDB('gold_db/gold.db').export_csvs('gold_db/exports')"
git add gold_db/gold.db gold_db/exports/ tests/benchmark_v1/score_gold_pairs.py tests/benchmark_v1/test_score_gold_pairs.py
git commit -m "gold-DB: gold-pair self-score baseline (130 verdicts, source=gold_pair)"
```

---

## Task 11: Wire build-side cache into build_dataset.py

**Files:**
- Modify: `tests/benchmark_v1/build_dataset.py`

**Goal:** Before calling CL citation-lookup for any citation, check `cases` for the cluster_id (when known) or for a name+cite match. On hit, skip CL.

**Note:** This task only matters for *future* dataset builds (v2 and beyond). v1 is sealed. The wiring exists so v2's mining is faster.

- [ ] **Step 1: Read build_dataset.py to find CL call sites**

Open `tests/benchmark_v1/build_dataset.py`. Locate the section that calls `verifier.verify_batch(...)` for gold-case verification. That's the CL hit point.

- [ ] **Step 2: Write integration test**

Skipping a full integration test for v1 — the cache hit path is covered by Task 3's `upsert_case` idempotency. Instead, add a smoke check in build_dataset.py's existing print output: after the CL call, log `cache_hits / cl_calls`.

- [ ] **Step 3: Add cache-aware wrapper**

In `build_dataset.py`, before the `verifier.verify_batch(...)` call, partition the input citations into (a) those already in `cases` by cite_string match and (b) the rest. Only call `verify_batch` on (b). Reconstruct the result list preserving order.

```python
# At top of build_dataset.py
from citation_verifier.gold_db import GoldDB

GOLD_DB_PATH = PROJECT_ROOT / "gold_db" / "gold.db"

# Inside the function that batches CL calls:
db = GoldDB(GOLD_DB_PATH)
cached: dict[int, dict] = {}  # index -> result-shaped dict
to_verify_indices = []
to_verify_cites = []
to_verify_parsed = []
for i, (cite, parsed) in enumerate(zip(citation_strs, parsed_citations)):
    cur = db.conn.execute(
        "SELECT cluster_id, canonical_name FROM cases WHERE cite_string = ? LIMIT 1",
        (cite,),
    ).fetchone()
    if cur is not None:
        cached[i] = {
            "status": "VERIFIED",
            "matched_cluster_id": cur["cluster_id"],
            "matched_name": cur["canonical_name"],
            "from_cache": True,
        }
    else:
        to_verify_indices.append(i)
        to_verify_cites.append(cite)
        to_verify_parsed.append(parsed)

cl_results = await verifier.verify_batch(
    to_verify_cites, parsed_citations=to_verify_parsed, quick_only=True,
)
results = [None] * len(citation_strs)
for idx, r in zip(to_verify_indices, cl_results):
    results[idx] = r
for idx, r in cached.items():
    results[idx] = r

print(f"Build-side cache: {len(cached)} hits / {len(citation_strs)} total")
```

- [ ] **Step 4: Smoke test on existing v1 dataset.csv**

Run: `venv/Scripts/python.exe -m tests.benchmark_v1.build_dataset --dry-run` (or whatever dry-run flag exists; if none, skip — see step 5).

Expected: `Build-side cache: ~150 hits / 200 total` since v1's gold cases are in `cases` after Task 9 backfill.

- [ ] **Step 5: Commit**

If `build_dataset.py` doesn't have a clean dry-run mode and a real run would re-mine, skip the smoke test and commit the wiring as-is. The next v2 mining run will exercise it.

```bash
git add tests/benchmark_v1/build_dataset.py
git commit -m "gold-DB: wire build-side cache into build_dataset.py"
```

---

## Task 12: Wire score-side cache into score.py + rolling-sample re-check

**Files:**
- Modify: `tests/benchmark_v1/score.py`

**Goal:** Wrap the Opus assessor call in `db.get_or_score_verdict` so reruns hit the cache. Also call `record_model_answer` so future runs of `score.py` populate the gold-DB even on cache miss. Add a rolling-sample re-check that scores ~10 already-cached random pairs to detect drift.

- [ ] **Step 1: Read score.py's assessor call site**

Open `tests/benchmark_v1/score.py`. Locate the `call_assessor(...)` invocation and the surrounding loop that iterates over (model, example) cells.

- [ ] **Step 2: Write integration test**

```python
# tests/benchmark_v1/test_score_integration.py (new file)
from pathlib import Path
from unittest.mock import patch, MagicMock
from citation_verifier.gold_db import GoldDB


def test_score_uses_gold_db_cache(tmp_path: Path):
    """A second run of score.py against the same dataset hits cache for
    every assessor call (modulo rolling-sample re-check)."""
    # Seed gold-DB with a verdict that should be cached.
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(7, "Test v. Case", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("test prop", None, "t")
    db.insert_verdict(pid, 7, "green", "opus-4.7", "v1", 20000,
                      None, None, "model_answer", "v1")
    # Subsequent get_or_score with same params should hit.
    fake = MagicMock(return_value={"verdict": "yellow"})
    result = db.get_or_score_verdict(pid, 7, "opus-4.7", "v1", 20000,
                                      "model_answer", "v1-rerun", fake)
    assert result["verdict"] == "green"  # cached, not the fake
    fake.assert_not_called()
```

- [ ] **Step 3: Run test**

Run: `venv/Scripts/python.exe -m pytest tests/benchmark_v1/test_score_integration.py -v`
Expected: PASS (this is really a re-check of Task 7's contract; it's here as documentation that score.py consumes the contract correctly).

- [ ] **Step 4: Modify score.py**

In `score.py`, replace direct `call_assessor(...)` calls with a wrapper:

```python
# Near top
from citation_verifier.gold_db import GoldDB, _normalize_proposition

GOLD_DB_PATH = PROJECT_ROOT / "gold_db" / "gold.db"
ASSESSOR_PROMPT_VERSION = "v1"
OPINION_WINDOW = 20000  # v1's actual window; v1.1 will bump to 60000
ROLLING_RECHECK_N = 10

# Per-cell scoring loop:
def score_cell(db: GoldDB, row: dict, run_id: str) -> dict:
    """Score a single (model, example) cell, using gold-DB cache.

    `row` is a results.csv-shaped dict with at least: proposition,
    matched_cluster_id, matched_cl_name.
    """
    pid = db.upsert_proposition(row["proposition"], None, run_id)
    ans_id_str = (row.get("matched_cluster_id") or "").strip()
    if not ans_id_str:
        return {"supports": "", "support_rationale": ""}
    ans_id = int(ans_id_str)

    def score_fn():
        opinion = fetch_opinion_text(ans_id) or ""
        truncated = opinion[:OPINION_WINDOW]
        verdict, rationale, _cost = call_assessor(
            row["proposition"], row["matched_cl_name"], truncated, model="opus",
        )
        return {"verdict": verdict.lower(), "reasoning": rationale}

    record = db.get_or_score_verdict(
        proposition_id=pid, candidate_cluster_id=ans_id,
        assessor_model="opus-4.7",
        assessor_prompt_version=ASSESSOR_PROMPT_VERSION,
        opinion_window_chars=OPINION_WINDOW,
        source="model_answer", run_id=run_id, score_fn=score_fn,
    )
    return {
        "supports": record["verdict"],
        "support_rationale": record["reasoning_excerpt"] or "",
    }
```

- [ ] **Step 5: Add rolling-sample re-check**

After the main scoring loop, add:

```python
def rolling_recheck(db: GoldDB, run_id: str, n: int = ROLLING_RECHECK_N) -> int:
    """Re-score n random already-cached pairs to detect assessor drift.

    The re-check rows are recorded under `assessor_prompt_version=
    f'v1-drift-{run_id}'` so they don't collide with the canonical cache.
    Querying drift later: `WHERE assessor_prompt_version LIKE 'v1-drift%'`.
    """
    drift_version = f"v1-drift-{run_id}"
    rows = db.conn.execute("""
        SELECT v.proposition_id, v.candidate_cluster_id, p.text AS prop_text,
               c.canonical_name AS case_name
          FROM assessor_verdicts v
          JOIN propositions p ON p.proposition_id = v.proposition_id
          JOIN cases c        ON c.cluster_id     = v.candidate_cluster_id
         WHERE v.assessor_model = 'opus-4.7'
           AND v.assessor_prompt_version = 'v1'
         ORDER BY RANDOM()
         LIMIT ?
    """, (n,)).fetchall()

    rechecked = 0
    for r in rows:
        opinion = fetch_opinion_text(r["candidate_cluster_id"]) or ""
        if not opinion:
            continue
        truncated = opinion[:OPINION_WINDOW]
        verdict, rationale, _cost = call_assessor(
            r["prop_text"], r["case_name"], truncated, model="opus",
        )
        db.insert_verdict(
            proposition_id=r["proposition_id"],
            candidate_cluster_id=r["candidate_cluster_id"],
            verdict=verdict.lower(),
            assessor_model="opus-4.7",
            assessor_prompt_version=drift_version,
            opinion_window_chars=OPINION_WINDOW,
            confidence=None,
            reasoning_excerpt=(rationale or "")[:500],
            source="probe",
            run_id=run_id,
        )
        rechecked += 1
    return rechecked
```

**Drift design choice:** drift samples use `assessor_prompt_version=f'v1-drift-{run_id}'` so they don't collide with the canonical cache. `get_verdict(...prompt_version='v1'...)` still hits the canonical row; drift queries filter by the prefix.

- [ ] **Step 6: Smoke run on existing v1 data**

```bash
venv/Scripts/python.exe -m tests.benchmark_v1.score
```

Expected: zero new assessor calls (everything cached from Task 9 backfill). Plus 10 drift-sample calls.

If the run makes more than 10 + UNKNOWN-cell calls, investigate why the cache isn't hitting — most likely a `_normalize_proposition` mismatch between backfill and score paths.

- [ ] **Step 7: Commit**

```bash
git add tests/benchmark_v1/score.py tests/benchmark_v1/test_score_integration.py
git commit -m "gold-DB: wire score.py to use cache + rolling-sample re-check"
```

---

## Task 13: End-to-end validation

**Files:** No new files; runs existing scripts.

- [ ] **Step 1: Capture pre-run verdict count**

```bash
venv/Scripts/python.exe -c "
from citation_verifier.gold_db import GoldDB
db = GoldDB('gold_db/gold.db')
print('verdicts:', db.conn.execute('SELECT COUNT(*) FROM assessor_verdicts').fetchone()[0])
print('drift samples:', db.conn.execute(\"SELECT COUNT(*) FROM assessor_verdicts WHERE assessor_prompt_version LIKE 'v1-drift%'\").fetchone()[0])
"
```

Record the numbers.

- [ ] **Step 2: Re-run score.py end-to-end**

```bash
venv/Scripts/python.exe -m tests.benchmark_v1.score
```

- [ ] **Step 3: Capture post-run verdict count**

Same query as Step 1. Compare:
- `verdicts` should grow by ~10 (the drift samples)
- `drift samples` should grow by exactly the rolling-sample count

If `verdicts` grew by more than ~10 + cells-with-no-match, the cache failed somewhere.

- [ ] **Step 4: Spot-check verdict equivalence**

```bash
venv/Scripts/python.exe -c "
from citation_verifier.gold_db import GoldDB
db = GoldDB('gold_db/gold.db')
# How many drift-sample rows agree with their canonical row?
print(db.conn.execute('''
    SELECT canonical.verdict = drift.verdict AS agree, COUNT(*)
      FROM assessor_verdicts canonical
      JOIN assessor_verdicts drift
        ON canonical.proposition_id = drift.proposition_id
       AND canonical.candidate_cluster_id = drift.candidate_cluster_id
       AND canonical.assessor_prompt_version = 'v1'
       AND drift.assessor_prompt_version LIKE 'v1-drift%'
     GROUP BY agree
''').fetchall())
"
```

Expected: high agreement rate (~90%+) — anything less is a drift signal worth investigating.

- [ ] **Step 5: Update README and commit final artifacts**

Create `gold_db/README.md`:

```markdown
# Gold-DB

Cumulative knowledge corpus for the case-law benchmark. See
[../docs/plans/2026-05-03-gold-db-design.md](../docs/plans/2026-05-03-gold-db-design.md).

## Files

- `gold.db` — SQLite source of truth (committed)
- `migrations/001_initial.sql` — canonical schema
- `exports/*.csv` — periodic CSV snapshots (committed for diffability)

## Querying

```bash
sqlite3 gold_db/gold.db "
  SELECT verdict, COUNT(*) FROM assessor_verdicts
   WHERE source='gold_pair' GROUP BY verdict
"
```

## Refreshing exports

```bash
venv/Scripts/python.exe -c "from citation_verifier.gold_db import GoldDB; GoldDB('gold_db/gold.db').export_csvs('gold_db/exports')"
```
```

```bash
venv/Scripts/python.exe -c "from citation_verifier.gold_db import GoldDB; GoldDB('gold_db/gold.db').export_csvs('gold_db/exports')"
git add gold_db/README.md gold_db/gold.db gold_db/exports/
git commit -m "gold-DB: end-to-end validation + README"
```

---

## Self-review checklist (mark before declaring done)

- [ ] Re-running v1 scoring produces zero net new canonical assessor verdicts (rolling-sample drift rows are expected)
- [ ] `gold.db` final state: 130 propositions, ≤130 unique cited cases, 130 citation_rows, ~390 model_answers; on the verdict side: ~190 Opus-20K + ~22 Opus-60K (truncation) + ~500 Sonnet/Haiku-20K (calibration) + 130 gold_pair (60K) + ~10 drift samples
- [ ] `gold_db/exports/*.csv` re-exported and committed
- [ ] All unit tests pass: `venv/Scripts/python.exe -m pytest tests/test_gold_db.py tests/benchmark_v1/test_backfill.py tests/benchmark_v1/test_score_gold_pairs.py tests/benchmark_v1/test_score_integration.py -v`
- [ ] Gold-pair Green/Yellow/Red distribution recorded in retrospective notes (this is the v1.3 publishable result)

---

## Out of scope for this plan (deferred to v1.x or v2)

- One-shot CL metadata fetch to populate `cases.court_id` / `cases.year` for backfilled cited cases (Task 9 leaves them NULL because dataset.csv doesn't include court_id for cited cases — separate v1.x work item; once court_id is populated, `lookup_court` fills in system/level via the next `upsert_case`)
- 60K opinion-window rerun of v1's existing 20K model_answer verdicts that *aren't* in `truncation_experiment_60k.csv` (truncation only re-scored Reds, ~22 of ~190; the remaining ~170 Greens/Yellows are still 20K-only — bump in v1.x by changing `OPINION_WINDOW` in `score.py` and rerunning, which the cache will mostly miss)
- Semantic proposition matching across datasets (sha256 of normalized text means v2's freshly-mined propositions don't hit v1's verdict cache; add a `proposition_clusters` table populated by an embedding pass to enable cross-dataset cache hits — see spec §"Out of scope")
- Migration framework (single `001_initial.sql` is enough for v1)
- Public release / DOI for gold-DB
- Stratified-sampling tooling that consumes gold-DB
