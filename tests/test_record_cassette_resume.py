"""Tests for the cassette recorder's checkpoint/resume logic (offline)."""
from __future__ import annotations

from tests.record_benchmark_cassette import (
    _recompute_counts,
    _should_skip_on_resume,
)


class TestShouldSkipOnResume:
    def test_missing_entry_not_skipped(self):
        assert not _should_skip_on_resume(None)

    def test_recorded_verdict_skipped(self):
        assert _should_skip_on_resume({"status": "NOT_FOUND"})
        assert _should_skip_on_resume({"status": "VERIFIED"})
        assert _should_skip_on_resume({"status": "WRONG_CASE"})

    def test_transient_verdicts_retried(self):
        assert not _should_skip_on_resume({"status": "ERROR"})
        assert not _should_skip_on_resume({"status": "VERIFICATION_INCOMPLETE"})


class TestRecomputeCounts:
    def test_counts_from_baseline(self):
        baseline = {
            "a": {"status": "VERIFIED", "cluster_id": 1, "expected_cluster_id": 1},
            "b": {"status": "VERIFIED_DOCKET_ONLY", "cluster_id": None,
                  "expected_cluster_id": None},
            "c": {"status": "NOT_FOUND"},
            "d": {"status": "WRONG_CASE", "cluster_id": 9},
            "e": {"status": "VERIFICATION_INCOMPLETE"},
            "f": {"status": "ERROR", "error": "boom"},
            "g": {"status": "CITE_UNCONFIRMED", "docket_id": 5},
        }
        counts = _recompute_counts(baseline)
        assert counts == {
            "found": 2,
            "not_found": 2,  # NOT_FOUND + WRONG_CASE (not a resolved family)
            "incomplete": 1,
            "error": 1,
            "cluster_match": 1,
            # Check Cite (2026-06-11): its own bucket, never in `found` —
            # for a fake corpus, found stays the FP headline.
            "check_cite": 1,
        }
