import sqlite3
from pathlib import Path
import pytest
from citation_verifier.gold_db import GoldDB, lookup_court


def test_init_creates_all_tables(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    cur = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
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


@pytest.mark.parametrize("court_id,expected_system,expected_level", [
    ("scotus", "federal", "colr"),    # normalized: courts-db says ''
    ("ca9",    "federal", "iac"),     # normalized: courts-db says ''
    ("cadc",   "federal", "iac"),     # courts-db already says 'iac'
    ("nysd",   "federal", "trial"),   # courts-db already says 'trial'
    ("cand",   "federal", "trial"),   # normalized: courts-db says 'gjc'
    ("ny",     "state",   "colr"),    # state pass-through, courts-db says 'colr'
    ("nysb",   "federal", "trial"),   # bankruptcy court, normalized from type='bankruptcy'
])
def test_lookup_court_known(court_id, expected_system, expected_level):
    system, level = lookup_court(court_id)
    assert system == expected_system
    assert level == expected_level


def test_lookup_court_unknown_returns_none():
    system, level = lookup_court("definitely-not-a-court-id-12345")
    assert system is None
    assert level is None


def test_lookup_court_empty_or_none():
    assert lookup_court(None) == (None, None)
    assert lookup_court("") == (None, None)


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
    assert row["system"] == "federal"   # auto-looked-up via courts-db
    assert row["level"] == "colr"       # normalized for SCOTUS


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
