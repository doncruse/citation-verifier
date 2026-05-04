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
