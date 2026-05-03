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
