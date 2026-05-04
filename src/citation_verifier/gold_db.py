"""Cumulative knowledge corpus for the case-law benchmark.

See docs/plans/2026-05-03-gold-db-design.md for the conceptual model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "gold_db" / "migrations" / "001_initial.sql"


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _normalize_proposition(text: str) -> str:
    """Lowercase + collapse all whitespace runs to a single space."""
    return " ".join(text.lower().split())


def _hash_proposition(text: str) -> str:
    """sha256 hex digest of the normalized proposition text."""
    return hashlib.sha256(_normalize_proposition(text).encode("utf-8")).hexdigest()


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

    def upsert_case(
        self,
        cluster_id: int,
        canonical_name: str,
        court_id: str | None,
        year: int | None,
        cite_string: str | None,
        run_id: str,
    ) -> None:
        """Insert or update a case record.

        canonical_name always overwrites (latest call wins). court_id, year,
        cite_string use COALESCE semantics (non-NULL incoming wins; NULL
        incoming preserves existing). system and level are auto-derived from
        court_id via lookup_court and are never specified directly.
        first_seen_run_id and first_seen_at are set only on initial insert.
        """
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

    def upsert_proposition(
        self,
        text: str,
        holding_verb: str | None,
        run_id: str,
    ) -> str:
        """Insert a proposition or return its existing id.

        The id is sha256 of the normalized text (lowercased, whitespace
        collapsed). On conflict (same hash), the existing row is preserved
        unchanged — `text`, `holding_verb`, and `first_seen_*` all stay at
        the values from the original insert.
        """
        norm = _normalize_proposition(text)
        pid = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        self.conn.execute(
            """
            INSERT INTO propositions (proposition_id, text, normalized_text,
                                      holding_verb, first_seen_run_id, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposition_id) DO NOTHING
            """,
            (pid, text, norm, holding_verb, run_id, _now_iso()),
        )
        self.conn.commit()
        return pid


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
    """Return (system, level) for a CourtListener court_id, or (None, None).

    courts-db's `level` field is sparse and inconsistent for federal
    courts (SCOTUS, ca9, Tax Court all have empty `level`; districts split
    between 'trial' and 'gjc'). We normalize federal classification here
    so analysts can rely on (system='federal', level in {'colr','iac','trial'})
    being uniformly populated. State classification is left untouched
    because courts-db gets it right.
    """
    if not court_id:
        return None, None
    global _COURT_INDEX
    if _COURT_INDEX is None:
        _COURT_INDEX = _build_court_index()
    rec = _COURT_INDEX.get(court_id)
    if not rec:
        return None, None
    system = rec.get("system") or None
    level = rec.get("level") or None  # coerce '' to None
    ctype = rec.get("type")

    # Federal normalization (courts-db's level data is uneven for federal courts).
    if system == "federal":
        if court_id == "scotus":
            level = "colr"
        elif court_id.startswith("ca") and ctype == "appellate":
            # Circuits: ca1..ca11, cadc, cafc
            level = "iac"
        elif ctype in ("trial", "bankruptcy"):
            # All federal trial-level courts (district + bankruptcy) -> consistent label
            level = "trial"
        # else: federal specialty (tax, bia, cit, etc.) — leave courts-db value (or None)

    return system, level
