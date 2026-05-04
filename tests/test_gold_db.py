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


def test_add_citation_row_updates_parenthetical(tmp_path: Path):
    """A second call with a different parenthetical updates it; mined_at and
    dataset_name are preserved (no new row, no metadata churn)."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", None, None, None, "t")
    db.upsert_case(2, "B", None, None, None, "t")
    db.conn.execute("INSERT INTO datasets (name) VALUES ('v1')")
    db.conn.commit()
    pid = db.upsert_proposition("p", None, "t")
    rid1 = db.add_citation_row(1, 2, pid, "first paren", "v1")
    first_mined_at = db.conn.execute(
        "SELECT mined_at FROM citation_rows WHERE id=?", (rid1,)
    ).fetchone()[0]

    rid2 = db.add_citation_row(1, 2, pid, "updated paren", "v1")
    assert rid1 == rid2

    row = db.conn.execute(
        "SELECT parenthetical, mined_at, dataset_name FROM citation_rows WHERE id=?",
        (rid1,),
    ).fetchone()
    assert row["parenthetical"] == "updated paren"
    assert row["mined_at"] == first_mined_at  # preserved on conflict
    assert row["dataset_name"] == "v1"        # preserved on conflict


def test_add_citation_row_fk_violation_raises(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid = db.upsert_proposition("Some proposition.", None, "t")
    # SQLite 3.35+ may raise OperationalError instead of IntegrityError when
    # FK fails on a statement with a RETURNING clause; accept either.
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
        db.add_citation_row(999, 998, pid, "holding ...", None)


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
    """Cache key includes (model, prompt_version, opinion_window_chars).
    Changing any of these causes a cache miss."""
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


def test_get_verdict_null_opinion_window_matches(tmp_path: Path):
    """NULL opinion_window_chars in storage matches NULL in query (COALESCE trick)."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    db.insert_verdict(pid, 1, "green", "opus-4.7", "v1",
                      opinion_window_chars=None,  # NULL
                      confidence=None, reasoning_excerpt=None,
                      source="probe", run_id="r1")
    result = db.get_verdict(pid, 1, "opus-4.7", "v1", None)
    assert result is not None
    assert result["verdict"] == "green"
    # And NULL doesn't accidentally match a non-NULL window:
    assert db.get_verdict(pid, 1, "opus-4.7", "v1", 60000) is None


def test_insert_verdict_idempotent_on_unique(tmp_path: Path):
    """Re-insert with the same 5-tuple returns the existing row's id."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    rid1 = db.insert_verdict(pid, 1, "green", "opus-4.7", "v1", 60000,
                             None, None, "model_answer", "r1")
    rid2 = db.insert_verdict(pid, 1, "yellow", "opus-4.7", "v1", 60000,
                             None, None, "model_answer", "r2")
    assert rid1 == rid2
    n = db.conn.execute("SELECT COUNT(*) FROM assessor_verdicts").fetchone()[0]
    assert n == 1
    # Original verdict ('green') stays — new call does NOT overwrite.
    row = db.conn.execute(
        "SELECT verdict FROM assessor_verdicts WHERE id=?", (rid1,)
    ).fetchone()
    assert row["verdict"] == "green"
