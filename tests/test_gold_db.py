import sqlite3
from pathlib import Path
import pytest
from citation_verifier.gold_db import GoldDB


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
