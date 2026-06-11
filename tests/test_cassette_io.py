"""Tests for the gzip-aware cassette I/O helpers.

Cassettes are large (the charlotin one is ~90 MB of JSON), re-recorded
often, and synced across machines via git. Storing them gzip-compressed
keeps the repo small, the diffs binary (not 150k-line text churn), and
the multi-machine pull fast. These tests pin the round-trip, that the
file on disk is actually compressed, atomic-write hygiene, and a
plain-.json fallback for transition robustness.
"""
from __future__ import annotations

import gzip
import json

from tests.cassette_client import dump_cassette, load_cassette


def test_gzip_roundtrip(tmp_path):
    p = tmp_path / "x_cassette.json.gz"
    data = {"a": [1, 2, 3], "b": {"c": "d"}}
    dump_cassette(p, data)
    assert load_cassette(p) == data


def test_file_on_disk_is_gzip(tmp_path):
    p = tmp_path / "x_cassette.json.gz"
    data = {"hello": "world"}
    dump_cassette(p, data)
    # Readable as gzip, and NOT as plain UTF-8 JSON.
    with gzip.open(p, "rt", encoding="utf-8") as f:
        assert json.load(f) == data


def test_compresses_repetitive_payload(tmp_path):
    p = tmp_path / "big_cassette.json.gz"
    # Cassettes are full of repeated opinion text — compresses heavily.
    data = {str(i): "the quick brown fox jumped " * 40 for i in range(300)}
    raw_len = len(json.dumps(data).encode("utf-8"))
    dump_cassette(p, data)
    assert p.stat().st_size < raw_len / 3


def test_atomic_write_leaves_no_tmp(tmp_path):
    p = tmp_path / "x_cassette.json.gz"
    dump_cassette(p, {"k": "v"})
    assert not (tmp_path / "x_cassette.json.gz.tmp").exists()
    assert p.exists()


def test_load_falls_back_to_plain_json_sibling(tmp_path):
    # A machine mid-migration may still have only the plain .json file.
    plain = tmp_path / "x_cassette.json"
    plain.write_text(json.dumps({"k": "v"}), encoding="utf-8")
    gz = tmp_path / "x_cassette.json.gz"
    assert not gz.exists()
    assert load_cassette(gz) == {"k": "v"}


def test_load_prefers_gz_over_stale_plain_sibling(tmp_path):
    plain = tmp_path / "x_cassette.json"
    plain.write_text(json.dumps({"stale": True}), encoding="utf-8")
    gz = tmp_path / "x_cassette.json.gz"
    dump_cassette(gz, {"fresh": True})
    assert load_cassette(gz) == {"fresh": True}


def test_dump_and_load_plain_json_path(tmp_path):
    # A non-.gz path round-trips as plain JSON (baselines stay uncompressed).
    p = tmp_path / "baseline.json"
    dump_cassette(p, {"k": "v"})
    assert load_cassette(p) == {"k": "v"}
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": "v"}
