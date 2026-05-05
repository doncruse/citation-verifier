"""Integration tests for score.py's gold-DB cache wiring + rolling drift re-check.

We don't run score.py end-to-end (that does real CL fetches and Opus calls).
Instead we verify that the cache layer behaves correctly when given a
populated GoldDB, plus that the drift re-check uses the expected
prompt-version naming pattern.
"""
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from citation_verifier.gold_db import GoldDB


def test_get_or_score_returns_cached_when_available(tmp_path: Path):
    """Verify the cache integration contract: prior verdict at same key
    is returned without calling score_fn."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(7, "Test v. Case", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("test prop", None, "t")

    # Seed a verdict with the canonical cache key
    db.insert_verdict(pid, 7, "green", "opus-4.7", "v1", 20000,
                      None, "stored reasoning", "model_answer", "v1")

    # A subsequent get_or_score with the same params must hit cache
    fake_score = MagicMock(return_value={"verdict": "yellow"})
    result = db.get_or_score_verdict(
        proposition_id=pid, candidate_cluster_id=7,
        assessor_model="opus-4.7", assessor_prompt_version="v1",
        opinion_window_chars=20000, source="model_answer",
        run_id="v1-rerun", score_fn=fake_score,
    )
    assert result["verdict"] == "green"  # the cached value, not "yellow"
    fake_score.assert_not_called()


def test_drift_recheck_uses_distinct_prompt_version(tmp_path: Path):
    """Drift samples must NOT collide with canonical cache.

    Re-scoring a (prop, case) under prompt_version='v1-drift-<run_id>'
    should produce a separate row, leaving the canonical row at 'v1'
    unchanged."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(7, "Test v. Case", "ca9", 2020, None, "t")
    pid = db.upsert_proposition("test prop", None, "t")

    # Canonical row
    db.insert_verdict(pid, 7, "green", "opus-4.7", "v1", 20000,
                      None, "canonical", "model_answer", "v1")
    # Drift sample under a different prompt_version
    db.insert_verdict(pid, 7, "yellow", "opus-4.7", "v1-drift-2026-05-04", 20000,
                      None, "drift sample", "probe", "v1-drift-2026-05-04")

    canonical = db.get_verdict(pid, 7, "opus-4.7", "v1", 20000)
    drift = db.get_verdict(pid, 7, "opus-4.7", "v1-drift-2026-05-04", 20000)
    assert canonical["verdict"] == "green"
    assert drift["verdict"] == "yellow"
    # Both rows exist independently
    n = db.conn.execute("SELECT COUNT(*) FROM assessor_verdicts").fetchone()[0]
    assert n == 2
