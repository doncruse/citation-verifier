"""Unit tests for score_gold_pairs (mocked assessor)."""
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from citation_verifier.gold_db import GoldDB
from tests.benchmark_v1.score_gold_pairs import score_gold_pairs


def _seed(db: GoldDB) -> tuple[str, int]:
    """Insert a citing case, cited case, proposition, and citation_row.
    Returns (proposition_id, cited_cluster_id)."""
    db.conn.execute("INSERT OR IGNORE INTO datasets (name) VALUES ('v1')")
    db.conn.commit()
    db.upsert_case(1, "Citing v. Court", "ca9", 2024, None, "t")
    db.upsert_case(2, "Foo v. Bar", "ca9", 2010, None, "t")
    pid = db.upsert_proposition("Standard of review.", None, "t")
    db.add_citation_row(1, 2, pid, "holding ...", "v1")
    return pid, 2


def test_score_gold_pairs_calls_assessor_per_pair(tmp_path: Path):
    db = GoldDB(tmp_path / "gold.db")
    pid, cid = _seed(db)
    fake = MagicMock(return_value={
        "verdict": "green", "confidence": 0.9, "reasoning": "..."
    })
    n = score_gold_pairs(db, run_id="t-1", assessor_fn=fake)
    assert n == 1
    fake.assert_called_once()
    row = db.get_verdict(pid, cid, "opus-4.7", "v1", 60000)
    assert row is not None
    assert row["source"] == "gold_pair"
    assert row["verdict"] == "green"


def test_score_gold_pairs_skips_cached(tmp_path: Path):
    """Second run hits cache for already-scored pairs."""
    db = GoldDB(tmp_path / "gold.db")
    _seed(db)
    fake = MagicMock(return_value={
        "verdict": "green", "confidence": 0.9, "reasoning": "..."
    })
    score_gold_pairs(db, run_id="t-1", assessor_fn=fake)
    score_gold_pairs(db, run_id="t-2", assessor_fn=fake)
    assert fake.call_count == 1  # second call hit cache, didn't call score_fn


def test_score_gold_pairs_only_processes_v1_rows(tmp_path: Path):
    """Citation rows with dataset_name != 'v1' should be ignored."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(1, "A", "ca9", 2020, None, "t")
    db.upsert_case(2, "B", "ca9", 2010, None, "t")
    db.upsert_case(3, "C", "ca9", 2010, None, "t")
    pid = db.upsert_proposition("p", None, "t")
    pid2 = db.upsert_proposition("p2", None, "t")
    # Register both datasets before inserting citation_rows that reference them
    db.conn.execute("INSERT OR IGNORE INTO datasets (name) VALUES ('v1')")
    db.conn.execute("INSERT OR IGNORE INTO datasets (name) VALUES ('v2')")
    db.conn.commit()
    db.add_citation_row(1, 2, pid, "v1 row", "v1")
    db.add_citation_row(1, 3, pid2, "v2 row", "v2")
    fake = MagicMock(return_value={"verdict": "green"})
    n = score_gold_pairs(db, run_id="t-1", assessor_fn=fake)
    assert n == 1  # only the v1 row got scored
    assert fake.call_count == 1


def test_default_assessor_translates_pilot_dict_shape(tmp_path: Path, monkeypatch):
    """_default_assessor unpacks pilot_a's call_assessor return correctly.

    pilot_a returns {assessment, rationale, elapsed_s, cost_usd}; we
    must extract assessment->verdict and rationale->reasoning."""
    from tests.benchmark_v1 import score_gold_pairs as mod

    fake_pilot = type("FakePilot", (), {})()
    fake_pilot.call_assessor = lambda *args, **kwargs: {
        "assessment": "Green",
        "rationale": "The opinion holds the relevant proposition.",
        "elapsed_s": 12.3,
        "cost_usd": 0.05,
    }
    monkeypatch.setattr(mod, "_load_pilot_assessor", lambda: fake_pilot)

    result = mod._default_assessor("p", "Foo v. Bar", "...opinion text...")
    assert result["verdict"] == "green"
    assert result["reasoning"] == "The opinion holds the relevant proposition."
    assert result["confidence"] is None


def test_default_assessor_handles_timeout(tmp_path: Path, monkeypatch):
    """Timeout returns assessment=None; must produce a usable verdict (not crash)."""
    from tests.benchmark_v1 import score_gold_pairs as mod

    fake_pilot = type("FakePilot", (), {})()
    fake_pilot.call_assessor = lambda *args, **kwargs: {
        "assessment": None,
        "rationale": "TIMEOUT",
        "elapsed_s": 60.0,
        "cost_usd": 0.0,
    }
    monkeypatch.setattr(mod, "_load_pilot_assessor", lambda: fake_pilot)

    result = mod._default_assessor("p", "Foo v. Bar", "...")
    # None assessment must produce a recordable verdict, not raise
    assert result["verdict"] in ("green", "yellow", "red")
    assert "TIMEOUT" in result["reasoning"]


def test_score_gold_pairs_real_mode_passes_client_to_fetch(tmp_path: Path, monkeypatch):
    """In real mode (assessor_fn=None defaults to _default_assessor),
    fetch_opinion_text must be called with both client and cluster_id."""
    db = GoldDB(tmp_path / "gold.db")
    pid, cid = _seed(db)

    fetch_calls = []

    fake_pilot = type("FakePilot", (), {})()
    fake_pilot.fetch_opinion_text = lambda client, cluster_id: (
        fetch_calls.append((client, cluster_id)) or "opinion text body..."
    )
    fake_pilot.call_assessor = lambda *a, **kw: {
        "assessment": "Green", "rationale": "supports it", "elapsed_s": 1, "cost_usd": 0.05
    }

    from tests.benchmark_v1 import score_gold_pairs as mod
    monkeypatch.setattr(mod, "_load_pilot_assessor", lambda: fake_pilot)

    # Use the real default assessor path (assessor_fn=None triggers it)
    n = mod.score_gold_pairs(db, run_id="t-real")
    assert n == 1
    assert len(fetch_calls) == 1
    client, cluster = fetch_calls[0]
    # client must be non-None — the bug was passing only cluster_id
    assert client is not None
    assert cluster == cid
