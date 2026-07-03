"""Tests for the MCP server (design docs/plans/2026-07-02-mcp-server-design.md).

All offline: verbs are monkeypatched or run over tmp workdirs.
"""
import asyncio

import pytest

pytest.importorskip("mcp", reason="mcp optional deps not installed")

from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from citation_verifier import mcp_server


@pytest.fixture()
def root(tmp_path):
    """A configured root containing one workdir; restores _ROOTS after."""
    saved = list(mcp_server._ROOTS)
    r = tmp_path / "root"
    (r / "wd").mkdir(parents=True)
    mcp_server.configure_roots([r])
    yield r
    mcp_server._ROOTS[:] = saved


class TestRootConfinement:
    def test_workdir_inside_root_resolves(self, root):
        assert mcp_server._workdir(str(root / "wd")) == (root / "wd").resolve()

    def test_traversal_rejected(self, root, tmp_path):
        (tmp_path / "outside").mkdir()
        with pytest.raises(ToolError, match="outside the configured roots"):
            mcp_server._resolve_under_roots(
                str(root / "wd" / ".." / ".." / "outside"), "workdir")

    def test_absolute_path_outside_root_rejected(self, root, tmp_path):
        (tmp_path / "outside").mkdir()
        with pytest.raises(ToolError, match="workdir"):
            mcp_server._resolve_under_roots(str(tmp_path / "outside"), "workdir")

    def test_missing_workdir_rejected(self, root):
        with pytest.raises(ToolError, match="does not exist"):
            mcp_server._workdir(str(root / "nope"))

    def test_no_roots_configured_rejected(self, root):
        mcp_server._ROOTS[:] = []
        with pytest.raises(ToolError, match="no --root"):
            mcp_server._resolve_under_roots(str(root / "wd"), "workdir")

    def test_configure_roots_requires_directories(self, tmp_path):
        with pytest.raises(ValueError, match="not a directory"):
            mcp_server.configure_roots([tmp_path / "missing"])


class TestMain:
    def test_main_requires_root(self, capsys):
        with pytest.raises(SystemExit):
            mcp_server.main([])


class TestSimpleVerbTools:
    def test_merge_serializes_stats(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import MergeStats
        seen = {}

        def fake(workdir):
            seen["wd"] = Path(workdir)
            return MergeStats(matched=3, unmatched=1,
                              unmatched_claims=["Camp v. Pitts"],
                              statuses={"VERIFIED": 3}, opinion_count=2)

        monkeypatch.setattr(mcp_server.pp, "run_merge", fake)
        out = mcp_server.merge(workdir=str(root / "wd"))
        assert seen["wd"] == (root / "wd").resolve()
        assert out == {"ok": True, "matched": 3, "unmatched": 1,
                       "unmatched_claims": ["Camp v. Pitts"],
                       "statuses": {"VERIFIED": 3}, "opinion_count": 2}

    def test_merge_precondition_maps_to_tool_error(self, root, monkeypatch):
        def fake(workdir):
            raise FileNotFoundError("verification_results.csv missing -- "
                                    "run the verify verb first")
        monkeypatch.setattr(mcp_server.pp, "run_merge", fake)
        with pytest.raises(ToolError, match="run the verify verb first"):
            mcp_server.merge(workdir=str(root / "wd"))

    def test_report_returns_paths(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import ReportStats
        wd = root / "wd"

        def fake(workdir):
            return ReportStats(path=Path(workdir) / "report.html",
                               findings=2, check_cite=1, verified=5,
                               unable=1)
        monkeypatch.setattr(mcp_server.pp, "run_report", fake)
        out = mcp_server.report(workdir=str(wd))
        assert out["ok"] is True
        assert out["path"].endswith("report.html")
        assert out["findings_json"].endswith("findings.json")
        assert out["findings"] == 2

    def test_check_quotes_crosscheck_triage(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import (
            CrosscheckStats, QuoteCheckStats, TriageStats)
        monkeypatch.setattr(mcp_server.pp, "run_check_quotes",
                            lambda w: QuoteCheckStats(total_claims=4))
        monkeypatch.setattr(mcp_server.pp, "run_crosscheck",
                            lambda w: CrosscheckStats(total=4,
                                                      court_mismatches=1))
        monkeypatch.setattr(mcp_server.pp, "run_triage",
                            lambda w: TriageStats(full=2, fast=1, skipped=1))
        wd = str(root / "wd")
        assert mcp_server.check_quotes(workdir=wd)["total_claims"] == 4
        assert mcp_server.crosscheck(workdir=wd)["court_mismatches"] == 1
        assert mcp_server.triage(workdir=wd)["full"] == 2


class TestVerifyTool:
    def _fake_result(self):
        from citation_verifier.proposition_pipeline import (
            MergeStats, PipelineResult, Wave1Result, Wave2Result)
        return PipelineResult(
            wave1=Wave1Result(results=[], miss_indices=[1, 4],
                              download_stats={"downloaded": 3}),
            wave2=Wave2Result(results=[], download_stats={"downloaded": 1}),
            merge=MergeStats())

    def test_verify_returns_wave_summary(self, root, monkeypatch):
        seen = {}
        fake_result = self._fake_result()

        async def fake(workdir, citations=None, force=False,
                       progress_callback=None, cache_dir=None):
            seen.update(citations=citations, force=force,
                        cache_dir=cache_dir)
            if progress_callback:
                progress_callback(1, 2)
            return fake_result

        monkeypatch.setattr(mcp_server.pp, "run_verify", fake)
        out = asyncio.run(mcp_server.verify(
            workdir=str(root / "wd"), citations=["576 U.S. 644"],
            force=True))
        assert out == {"ok": True, "already_done": False,
                       "wave1_misses": 2,
                       "wave1_downloads": {"downloaded": 3},
                       "wave2_downloads": {"downloaded": 1}}
        assert seen["citations"] == ["576 U.S. 644"]
        assert seen["force"] is True
        assert seen["cache_dir"] is None

    def test_verify_noop_reports_already_done(self, root, monkeypatch):
        async def fake(workdir, **kwargs):
            return None
        monkeypatch.setattr(mcp_server.pp, "run_verify", fake)
        out = asyncio.run(mcp_server.verify(workdir=str(root / "wd")))
        assert out == {"ok": True, "already_done": True}

    def test_verify_cache_dir_is_root_checked(self, root, tmp_path):
        (tmp_path / "outside").mkdir()
        with pytest.raises(ToolError, match="cache_dir"):
            asyncio.run(mcp_server.verify(
                workdir=str(root / "wd"),
                cache_dir=str(tmp_path / "outside")))


class TestStatus:
    def test_status_reports_files_and_pending(self, root):
        wd = root / "wd"
        (wd / "claims.csv").write_text("claim_id\n", encoding="utf-8")
        (wd / "run.json").write_text('{"verify": {"ok": true}}',
                                     encoding="utf-8")
        (wd / "jobs").mkdir()
        (wd / "jobs" / "assess.json").write_text(
            '[{"job_id": "j1", "claim_ids": ["c-01"], "prompt": "p",'
            ' "prompt_version": "assess-v2", "files": ["opinions/a.txt"],'
            ' "schema": null, "max_chars": null}]', encoding="utf-8")
        out = mcp_server.status(workdir=str(wd))
        assert out["files"]["claims.csv"] is True
        assert out["files"]["report.html"] is False
        assert out["run"] == {"verify": {"ok": True}}
        assert out["pending_jobs"]["assess"] == 1
        assert out["pending_jobs"]["extract"] == 0
