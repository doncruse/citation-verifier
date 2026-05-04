"""Unit tests for backfill_gold_db (uses small CSV fixtures, not real v1 data)."""
from pathlib import Path
import csv
import pytest
from citation_verifier.gold_db import GoldDB
from tests.benchmark_v1.backfill_gold_db import backfill_v1, _cluster_id_from_url


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_cluster_id_from_url():
    assert _cluster_id_from_url(
        "https://www.courtlistener.com/opinion/12345/foo/") == 12345
    assert _cluster_id_from_url(
        "https://www.courtlistener.com/opinion/9876543/foo-v-bar/") == 9876543
    assert _cluster_id_from_url("not a cl url") is None
    assert _cluster_id_from_url("") is None
    assert _cluster_id_from_url(None) is None


def test_backfill_dedupes_propositions(tmp_path: Path):
    """Two dataset.csv rows with the same (normalized proposition, gold cluster_id)
    should produce one citation_rows entry — eyecite duplication scenario."""
    bench = tmp_path / "benchmark_v1"
    bench.mkdir()
    _write_csv(bench / "dataset.csv", [
        {"id": "1", "court": "ca9", "proposition": "Standard of review.",
         "gold_name": "Foo v. Bar", "gold_cite": "100 F.3d 1",
         "citing_cluster_id": "999", "citing_year": "2024", "cited_year": "2010",
         "v_status": "VERIFIED",
         "v_url": "https://www.courtlistener.com/opinion/12345/foo/",
         "v_matched_name": "Foo v. Bar"},
        {"id": "2", "court": "ca9", "proposition": "standard  of\nreview.",  # whitespace dup
         "gold_name": "Foo v. Bar", "gold_cite": "100 F.3d 1",
         "citing_cluster_id": "999", "citing_year": "2024", "cited_year": "2010",
         "v_status": "VERIFIED",
         "v_url": "https://www.courtlistener.com/opinion/12345/foo/",
         "v_matched_name": "Foo v. Bar"},
    ], cols=["id", "court", "proposition", "gold_name", "gold_cite",
             "citing_cluster_id", "citing_year", "cited_year",
             "v_status", "v_url", "v_matched_name"])

    db = GoldDB(tmp_path / "gold.db")
    backfill_v1(db, bench, run_id="v1-backfill-test")

    assert db.conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM citation_rows").fetchone()[0] == 1
    # Should have created both citing case (999) and cited case (12345)
    assert db.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2


def test_backfill_inserts_dataset_record(tmp_path: Path):
    """A 'v1' row should be inserted into the datasets table."""
    bench = tmp_path / "benchmark_v1"
    bench.mkdir()
    _write_csv(bench / "dataset.csv", [], cols=["id", "court", "proposition", "gold_name",
        "gold_cite", "citing_cluster_id", "citing_year", "cited_year",
        "v_status", "v_url", "v_matched_name"])
    db = GoldDB(tmp_path / "gold.db")
    backfill_v1(db, bench, run_id="v1-backfill-test")
    row = db.conn.execute("SELECT name FROM datasets WHERE name='v1'").fetchone()
    assert row is not None
