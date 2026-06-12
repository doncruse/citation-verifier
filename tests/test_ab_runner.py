"""Offline tests for the re-pointed A/B harness (design SS9).

The harness's executor seam is exercised with RecordedExecutor over the
frozen corpora -- no LLM, no network. Frozen corpora are read-only here
(live mode copies them to tmp_path first).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import ab_test_runner as ab  # noqa: E402


class TestReplayMode:
    def test_scores_frozen_cassettes(self, capsys):
        scores = ab.run_ab_config("baseline", {}, replay=True)
        assert (scores["payne"].correct, scores["payne"].total) == (23, 27)
        assert (scores["wainwright"].correct,
                scores["wainwright"].total) == (33, 34)
        assert "baseline/payne" in capsys.readouterr().out


class TestLiveModeOfflineSeam:
    def test_injected_executor_runs_assess_and_scores(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor

        def factory(config, wd):
            # replay the ORIGINAL frozen cassette as if it were live
            return RecordedExecutor(
                ab.CORPORA / wd.name / "jobs" / "assess_results.jsonl")

        scores = ab.run_ab_config(
            "test", {"model": "opus"}, corpora=("payne",),
            run_root=tmp_path, executor_factory=factory)
        assert (scores["payne"].correct, scores["payne"].total) == (23, 27)
        # the copy got a fresh cassette written through run_assess
        copy_cassette = tmp_path / "payne" / "jobs" / "assess_results.jsonl"
        assert copy_cassette.exists()
        # frozen corpus untouched
        assert (ab.CORPORA / "payne" / "jobs" /
                "assess_results.jsonl").exists()

    def test_live_requires_run_root(self):
        with pytest.raises(ValueError, match="run_root"):
            ab.run_ab_config("x", {}, corpora=("payne",))

    def test_hint_config_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="assess-v2"):
            ab.run_ab_config("hints", {"include_hints": True},
                             corpora=("payne",), run_root=tmp_path)


class TestSaveAndCompare:
    def test_roundtrip(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(ab, "RESULTS_DIR", tmp_path)
        scores = ab.run_ab_config("baseline", {}, corpora=("payne",),
                                  replay=True)
        out = ab.save_results("baseline", scores)
        assert out.exists()
        capsys.readouterr()
        ab.compare_results(str(out), str(out))
        printed = capsys.readouterr().out
        assert "23/27 correct" in printed
        assert "Disagreements: 0" in printed


class TestDryRun:
    def test_prints_job_counts(self, capsys):
        ab.dry_run_config("opus-baseline", {"model": "opus"},
                          corpora=("payne",))
        out = capsys.readouterr().out
        assert "assess jobs" in out
