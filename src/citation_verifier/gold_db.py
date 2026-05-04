"""Cumulative knowledge corpus for the case-law benchmark.

See docs/plans/2026-05-03-gold-db-design.md for the conceptual model.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import sqlite3
from pathlib import Path
from typing import Callable, Required, TypedDict


class VerdictResult(TypedDict, total=False):
    verdict: Required[str]              # must be present
    confidence: float | None
    reasoning: str | None

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

    def get_verdict(
        self,
        proposition_id: str,
        candidate_cluster_id: int,
        assessor_model: str,
        assessor_prompt_version: str,
        opinion_window_chars: int | None,
    ) -> sqlite3.Row | None:
        """Look up a verdict by the 5-tuple cache key.

        Returns the most recent matching row, or None on miss. The COALESCE
        on opinion_window_chars makes NULL == NULL a hit (SQLite's default
        NULL semantics treat NULL = NULL as unknown).
        """
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
        """Insert a verdict, or return the id of the existing row.

        UNIQUE on (proposition_id, candidate_cluster_id, assessor_model,
        assessor_prompt_version, opinion_window_chars). On conflict, does
        NOT overwrite — original verdict / confidence / reasoning stay.
        Returns the row id (new or existing).
        """
        cur = self.conn.execute(
            """
            INSERT INTO assessor_verdicts
                (proposition_id, candidate_cluster_id, verdict, assessor_model,
                 assessor_prompt_version, opinion_window_chars, confidence,
                 reasoning_excerpt, source, run_id, assessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (proposition_id, candidate_cluster_id, verdict, assessor_model,
             assessor_prompt_version, opinion_window_chars, confidence,
             reasoning_excerpt, source, run_id, _now_iso()),
        )
        row = cur.fetchone()
        self.conn.commit()
        if row is not None:
            return row[0]
        # ON CONFLICT DO NOTHING -> fetchone returned None; look up existing id.
        existing = self.conn.execute(
            """
            SELECT id FROM assessor_verdicts
             WHERE proposition_id = ?
               AND candidate_cluster_id = ?
               AND assessor_model = ?
               AND assessor_prompt_version = ?
               AND COALESCE(opinion_window_chars, -1) = COALESCE(?, -1)
            """,
            (proposition_id, candidate_cluster_id, assessor_model,
             assessor_prompt_version, opinion_window_chars),
        ).fetchone()
        return existing[0]

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
        """Cache-aware verdict scoring.

        Returns a verdict row. On cache miss, calls score_fn() and inserts
        its result. score_fn must return a dict with 'verdict' (required)
        and optional 'confidence' and 'reasoning' keys. Reasoning is
        truncated to 500 chars before storage.
        """
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

    def add_citation_row(
        self,
        citing_cluster_id: int,
        cited_cluster_id: int,
        proposition_id: str,
        parenthetical: str,
        dataset_name: str | None,
    ) -> int:
        """Insert a citation_rows row, or return the id of the matching one.

        UNIQUE on (citing_cluster_id, cited_cluster_id, proposition_id). On
        conflict, `parenthetical` is updated to the new value (most recent
        observation wins) but the row id stays stable. Other fields
        (`dataset_name`, `mined_at`) are preserved on conflict.
        """
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
        """Append a model answer (no deduplication; each call inserts a row).

        parse_status is one of 'parsed' | 'unknown' | 'unparseable' |
        'hallucinated_cite'. answer_cluster_id is NULL for parse_status
        in {'unknown', 'unparseable'}. Run_id is required (NOT NULL in schema).
        """
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
        """Insert a run record. Use end_run to set ended_at when finished."""
        self.conn.execute(
            "INSERT INTO runs (run_id, kind, started_at, git_commit, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, kind, _now_iso(), git_commit, notes),
        )
        self.conn.commit()

    def end_run(self, run_id: str) -> None:
        """Set ended_at on an existing run record."""
        self.conn.execute(
            "UPDATE runs SET ended_at=? WHERE run_id=?",
            (_now_iso(), run_id),
        )
        self.conn.commit()

    def export_csvs(self, out_dir: str | Path) -> None:
        """Write one CSV per table to out_dir (created if missing).

        Each CSV has a header row + one row per DB row, ordered by primary
        key. Used for diff-able commits and external researcher access.
        """
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
