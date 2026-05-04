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
                   court_id="ca9", year=2020, cite_string=None, run_id="first")
    first_seen_at = db.conn.execute(
        "SELECT first_seen_at FROM cases WHERE cluster_id=12345"
    ).fetchone()[0]

    db.upsert_case(cluster_id=12345, canonical_name="Foo v. Bar",
                   court_id="ca9", year=2020, cite_string=None, run_id="second")

    n = db.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    assert n == 1
    row = db.conn.execute(
        "SELECT first_seen_run_id, first_seen_at FROM cases"
    ).fetchone()
    assert row["first_seen_run_id"] == "first"   # not overwritten by second call
    assert row["first_seen_at"] == first_seen_at  # also not overwritten


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


def test_upsert_case_canonical_name_always_overwrites(tmp_path: Path):
    """canonical_name has no COALESCE protection; latest call wins.

    This is intentional: the most recent observation is treated as the
    canonical truth (e.g., a later CL fetch may have a more accurate
    name than an early eyecite parse).
    """
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(cluster_id=99, canonical_name="Detailed Name v. Other Party",
                   court_id="ca9", year=2020, cite_string=None, run_id="r1")
    db.upsert_case(cluster_id=99, canonical_name="Short Name",
                   court_id="ca9", year=2020, cite_string=None, run_id="r2")
    name = db.conn.execute(
        "SELECT canonical_name FROM cases WHERE cluster_id=99"
    ).fetchone()[0]
    assert name == "Short Name"  # second call wins, even though it's shorter


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


def test_upsert_proposition_first_seen_preserved(tmp_path: Path):
    """first_seen_run_id and first_seen_at are insert-only (matches upsert_case contract)."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_proposition("p", None, "r1")
    db.upsert_proposition("p", None, "r2")  # same text, different run_id
    row = db.conn.execute(
        "SELECT first_seen_run_id FROM propositions"
    ).fetchone()
    assert row["first_seen_run_id"] == "r1"


def test_upsert_proposition_holding_verb_preserved(tmp_path: Path):
    """holding_verb is insert-only — second call doesn't overwrite."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_proposition("p", "holding", "r1")
    db.upsert_proposition("p", "finding", "r2")  # different verb, same text
    row = db.conn.execute("SELECT holding_verb FROM propositions").fetchone()
    assert row["holding_verb"] == "holding"
