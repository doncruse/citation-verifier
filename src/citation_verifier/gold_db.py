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
