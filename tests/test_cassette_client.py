"""Unit tests for the record/replay CassetteClient (offline, mocked)."""
from unittest.mock import MagicMock

import pytest

from tests.cassette_client import CassetteClient, CassetteMiss


def _fake_real():
    real = MagicMock()
    real.citation_lookup.return_value = [{"clusters": [{"id": 1}]}]
    real.search_opinions.return_value = [{"id": 2}]
    return real


def test_record_then_replay_returns_same_value_without_calling_real():
    cassette: dict = {}
    real = _fake_real()

    rec = CassetteClient(real, cassette, mode="record")
    recorded = rec.citation_lookup("Foo v. Bar, 1 U.S. 1")
    assert recorded == [{"clusters": [{"id": 1}]}]
    assert real.citation_lookup.call_count == 1
    assert len(cassette) == 1  # the call was stored

    # Replay against a fresh real client that must NOT be called.
    real2 = _fake_real()
    rep = CassetteClient(real2, cassette, mode="replay")
    replayed = rep.citation_lookup("Foo v. Bar, 1 U.S. 1")
    assert replayed == recorded
    real2.citation_lookup.assert_not_called()


def test_replay_distinguishes_calls_by_arguments():
    cassette: dict = {}
    real = _fake_real()
    rec = CassetteClient(real, cassette, mode="record")
    rec.search_opinions(case_name="A", court="ca9")
    real.search_opinions.return_value = [{"id": 99}]
    rec.search_opinions(case_name="B", court="ca9")

    rep = CassetteClient(_fake_real(), cassette, mode="replay")
    assert rep.search_opinions(case_name="A", court="ca9") == [{"id": 2}]
    assert rep.search_opinions(case_name="B", court="ca9") == [{"id": 99}]


def test_replay_miss_raises():
    rep = CassetteClient(_fake_real(), {}, mode="replay")
    with pytest.raises(CassetteMiss):
        rep.citation_lookup("never recorded")


def test_uncached_attributes_pass_through():
    real = _fake_real()
    real.BASE_URL = "https://example.test"
    c = CassetteClient(real, {}, mode="replay")
    assert c.BASE_URL == "https://example.test"
