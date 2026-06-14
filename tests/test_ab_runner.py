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

        def factory(config, wd, phase):
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

    def test_hint_config_rejected_for_v1(self, tmp_path):
        with pytest.raises(ValueError, match="assess-v2"):
            ab.run_ab_config("hints", {"include_hints": True},
                             corpora=("payne",), run_root=tmp_path)


class TestHintConfigs:
    def test_hints_config_runs_prescreen_then_assess(self, tmp_path):
        import csv as csv_mod

        from citation_verifier.executor import (
            RecordedExecutor, Verdict, append_verdict_jsonl)
        # synthetic recorded executors: prescreen hints + v2 verdicts
        pre = tmp_path / "pre.jsonl"
        v2 = tmp_path / "v2.jsonl"
        src_claims = list(csv_mod.DictReader(
            (ab.CORPORA / "payne" / "claims.csv").open(encoding="utf-8")))
        for c in src_claims:
            if c.get("opinion_file"):
                append_verdict_jsonl(pre, Verdict(
                    claim_id=c["claim_id"], fields={"hint": "H"},
                    model="haiku", prompt_version="prescreen-v1"))
                append_verdict_jsonl(v2, Verdict(
                    claim_id=c["claim_id"],
                    fields={"support": "supported", "badge_label": "S",
                            "brief_block": "", "opinion_block": "",
                            "finding_analysis": "f"},
                    model="opus", prompt_version="assess-v2"))

        def factory(config, wd, phase):
            return RecordedExecutor(pre if phase == "prescreen" else v2)

        scores = ab.run_ab_config(
            "v2h", {"include_hints": True, "prompt_version": "assess-v2"},
            corpora=("payne",), run_root=tmp_path / "run",
            executor_factory=factory)
        rows = list(csv_mod.DictReader(
            (tmp_path / "run" / "payne" / "claims.csv")
            .open(encoding="utf-8")))
        hinted = [r for r in rows if r.get("prescreen_hint")]
        assert hinted  # big-opinion claims got hints before assess
        assert scores["payne"].total == 27


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


class TestWithersCorpusViaRunner:
    def test_replay_scores_exhibit_scale(self, capsys):
        scores = ab.run_ab_config("baseline", {}, corpora=("withers",),
                                  replay=True)
        s = scores["withers"]
        assert (s.yellows_caught, s.yellows_total) == (14, 19)
        assert (s.reds_caught, s.reds_total) == (3, 3)
        assert "yellows caught 14/19" in capsys.readouterr().out


class TestDryRun:
    def test_prints_job_counts(self, capsys):
        ab.dry_run_config("opus-baseline", {"model": "opus"},
                          corpora=("payne",))
        out = capsys.readouterr().out
        assert "assess jobs" in out
