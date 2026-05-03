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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if not self._schema_applied():
            self._apply_schema()

    def _schema_applied(self) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cases'"
        ).fetchone())

    def _apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(sql)

    def close(self) -> None:
        self.conn.close()
