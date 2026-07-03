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


_NEXT = "dispatch"  # substring of the pending 'next' instruction


class TestExtractTool:
    def test_extract_pending_lists_jobs(self, root, monkeypatch):
        wd = root / "wd"
        (wd / "jobs").mkdir(exist_ok=True)
        (wd / "jobs" / "extract.json").write_text(
            '[{"job_id": "extract", "claim_ids": ["extract"],'
            ' "prompt": "big prompt", "prompt_version": "extract-v1",'
            ' "files": ["memo.pdf"], "schema": null, "max_chars": null}]',
            encoding="utf-8")
        doc = root / "memo.pdf"
        doc.write_bytes(b"%PDF-1.4 stub")
        from citation_verifier.proposition_pipeline import ExtractStats

        def fake(workdir, document, executor=None, force=False):
            assert executor is None  # jobs mode only in v1
            return ExtractStats(pending=True)
        monkeypatch.setattr(mcp_server.pp, "run_extract", fake)
        out = mcp_server.extract(workdir=str(wd), document=str(doc))
        assert out["pending"] is True
        assert out["pending_jobs"] == [{"job_id": "extract",
                                        "claim_ids": ["extract"],
                                        "files": ["memo.pdf"]}]
        assert _NEXT in out["next"]
        assert "prompt" not in out["pending_jobs"][0]

    def test_extract_document_is_root_checked(self, root, tmp_path):
        outside = tmp_path / "evil.pdf"
        outside.write_bytes(b"x")
        with pytest.raises(ToolError, match="document"):
            mcp_server.extract(workdir=str(root / "wd"),
                               document=str(outside))

    def test_extract_noop(self, root, monkeypatch):
        doc = root / "memo.pdf"
        doc.write_bytes(b"x")
        monkeypatch.setattr(mcp_server.pp, "run_extract",
                            lambda *a, **k: None)
        out = mcp_server.extract(workdir=str(root / "wd"),
                                 document=str(doc))
        assert out == {"ok": True, "already_done": True}

    def test_extract_done(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import ExtractStats
        doc = root / "memo.pdf"
        doc.write_bytes(b"x")
        monkeypatch.setattr(
            mcp_server.pp, "run_extract",
            lambda *a, **k: ExtractStats(claims=7, toa=5, body=9))
        out = mcp_server.extract(workdir=str(root / "wd"),
                                 document=str(doc))
        assert out["claims"] == 7 and out["pending"] is False


class TestAssessTool:
    def test_assess_pending_lists_jobs(self, root, monkeypatch):
        wd = root / "wd"
        (wd / "jobs").mkdir(exist_ok=True)
        (wd / "jobs" / "assess.json").write_text(
            '[{"job_id": "op1", "claim_ids": ["wd-01", "wd-02"],'
            ' "prompt": "packed prompt", "prompt_version": "assess-v2",'
            ' "files": ["opinions/a.txt"], "schema": null,'
            ' "max_chars": null}]', encoding="utf-8")
        from citation_verifier.proposition_pipeline import AssessStats
        seen = {}

        def fake(workdir, executor=None, prompt_version=None):
            seen["pv"] = prompt_version
            return AssessStats(eligible=2, done=0, pending=2)
        monkeypatch.setattr(mcp_server.pp, "run_assess", fake)
        out = mcp_server.assess(workdir=str(wd))
        assert seen["pv"] == mcp_server.pp.ASSESS_V2_PROMPT_VERSION
        assert out["pending"] is True
        assert out["stats"]["pending"] == 2
        assert out["pending_jobs"][0]["job_id"] == "op1"

    def test_assess_complete(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import AssessStats
        monkeypatch.setattr(
            mcp_server.pp, "run_assess",
            lambda workdir, executor=None, prompt_version=None:
            AssessStats(eligible=2, done=2, pending=0,
                        skipped_deterministic=1))
        out = mcp_server.assess(workdir=str(root / "wd"),
                                prompt_version="assess-v1")
        assert out["pending"] is False
        assert out["done"] == 2


class TestFullTool:
    def _patch_chain(self, monkeypatch, assess_pending):
        from citation_verifier.proposition_pipeline import (
            ApplyStats, AssessStats, CrosscheckStats, MergeStats,
            QuoteCheckStats, ReportStats, TriageStats)

        async def fake_verify(workdir, **kwargs):
            return None  # already done

        monkeypatch.setattr(mcp_server.pp, "run_verify", fake_verify)
        monkeypatch.setattr(mcp_server.pp, "run_merge",
                            lambda w: MergeStats(matched=1))
        monkeypatch.setattr(mcp_server.pp, "run_check_quotes",
                            lambda w: QuoteCheckStats(total_claims=1))
        monkeypatch.setattr(mcp_server.pp, "run_crosscheck",
                            lambda w: CrosscheckStats(total=1))
        monkeypatch.setattr(mcp_server.pp, "run_triage",
                            lambda w: TriageStats(full=1))
        monkeypatch.setattr(
            mcp_server.pp, "run_assess",
            lambda workdir, executor=None, prompt_version=None:
            AssessStats(eligible=1, done=0 if assess_pending else 1,
                        pending=1 if assess_pending else 0))
        monkeypatch.setattr(
            mcp_server.pp, "run_apply_assessments",
            lambda workdir, prompt_version=None: ApplyStats(applied=1))
        monkeypatch.setattr(mcp_server.pp, "run_report",
                            lambda w: ReportStats(path=Path(w) / "report.html",
                                                  verified=1))

    def test_full_stops_at_pending_assess(self, root, monkeypatch):
        self._patch_chain(monkeypatch, assess_pending=True)
        out = asyncio.run(mcp_server.full(workdir=str(root / "wd")))
        assert out["status"] == "pending-assess"
        assert "apply_assessments" not in out["steps"]
        assert "report" not in out["steps"]
        assert out["steps"]["merge"]["matched"] == 1

    def test_full_runs_to_report(self, root, monkeypatch):
        self._patch_chain(monkeypatch, assess_pending=False)
        out = asyncio.run(mcp_server.full(workdir=str(root / "wd")))
        assert out["status"] == "complete"
        assert out["steps"]["apply_assessments"]["applied"] == 1
        assert out["steps"]["report"]["path"].endswith("report.html")

    def test_full_stops_at_pending_extract(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import ExtractStats
        doc = root / "memo.pdf"
        doc.write_bytes(b"x")
        (root / "wd" / "jobs").mkdir(exist_ok=True)
        (root / "wd" / "jobs" / "extract.json").write_text(
            "[]", encoding="utf-8")
        monkeypatch.setattr(mcp_server.pp, "run_extract",
                            lambda *a, **k: ExtractStats(pending=True))
        out = asyncio.run(mcp_server.full(workdir=str(root / "wd"),
                                          document=str(doc)))
        assert out["status"] == "pending-extract"
        assert list(out["steps"]) == ["extract"]


_JOB_LINE = ('[{"job_id": "op1", "claim_ids": ["wd-01"],'
             ' "prompt": "ASSESS THIS", "prompt_version": "assess-v2",'
             ' "files": ["opinions/a.txt"], "schema": null,'
             ' "max_chars": null}]')


class TestGetJob:
    def test_returns_full_prompt(self, root):
        wd = root / "wd"
        (wd / "jobs").mkdir(exist_ok=True)
        (wd / "jobs" / "assess.json").write_text(_JOB_LINE,
                                                 encoding="utf-8")
        out = mcp_server.get_job(workdir=str(wd), phase="assess",
                                 job_id="op1")
        assert out == {"ok": True, "job_id": "op1",
                       "claim_ids": ["wd-01"], "prompt": "ASSESS THIS",
                       "prompt_version": "assess-v2",
                       "files": ["opinions/a.txt"]}

    def test_unknown_phase_rejected(self, root):
        with pytest.raises(ToolError, match="phase"):
            mcp_server.get_job(workdir=str(root / "wd"),
                               phase="../../etc", job_id="x")

    def test_missing_jobs_file(self, root):
        with pytest.raises(ToolError, match="run the assess tool first"):
            mcp_server.get_job(workdir=str(root / "wd"), phase="assess",
                               job_id="op1")

    def test_unknown_job_id(self, root):
        wd = root / "wd"
        (wd / "jobs").mkdir(exist_ok=True)
        (wd / "jobs" / "assess.json").write_text(_JOB_LINE,
                                                 encoding="utf-8")
        with pytest.raises(ToolError, match="job_id"):
            mcp_server.get_job(workdir=str(wd), phase="assess",
                               job_id="nope")


class TestSubmitJobResult:
    def test_appends_valid_envelope(self, root):
        from citation_verifier.executor import load_verdicts_jsonl
        wd = root / "wd"
        envelope = {"claim_id": "wd-01", "prompt_version": "assess-v2",
                    "model": "opus",
                    "fields": {"verdicts": [{"claim_id": "wd-01",
                                             "support": "supported"}]}}
        out = mcp_server.submit_job_result(workdir=str(wd),
                                           phase="assess",
                                           result=envelope)
        assert out["ok"] is True and out["total_results"] == 1
        verdicts = load_verdicts_jsonl(wd / "jobs" / "assess_results.jsonl")
        assert verdicts[0].claim_id == "wd-01"
        assert verdicts[0].prompt_version == "assess-v2"
        assert verdicts[0].model == "opus"
        assert verdicts[0].fields["verdicts"][0]["support"] == "supported"

    @pytest.mark.parametrize("broken", [
        {"prompt_version": "assess-v2", "fields": {}},          # no claim_id
        {"claim_id": "wd-01", "fields": {}},                    # no version
        {"claim_id": "wd-01", "prompt_version": "assess-v2"},   # no fields
        {"claim_id": "wd-01", "prompt_version": "assess-v2",
         "fields": "not-an-object"},
    ])
    def test_rejects_malformed_envelope(self, root, broken):
        with pytest.raises(ToolError):
            mcp_server.submit_job_result(workdir=str(root / "wd"),
                                         phase="assess", result=broken)
        results = (root / "wd" / "jobs" / "assess_results.jsonl")
        assert not results.exists()


def _make_minimal_pdf(path, text="Hello MCP"):
    """One-page valid PDF with a correct xref (pdfplumber-readable)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF").encode()
    path.write_bytes(bytes(out))


class TestIntakeDocument:
    def test_pdf(self, root):
        doc = root / "memo.pdf"
        _make_minimal_pdf(doc)
        out = mcp_server.intake_document(workdir=str(root / "wd"),
                                         document=str(doc))
        target = root / "wd" / "document.txt"
        assert out["path"] == str(target) and out["pages"] == 1
        assert "Hello MCP" in target.read_text(encoding="utf-8")

    def test_docx(self, root):
        import docx
        doc_path = root / "memo.docx"
        d = docx.Document()
        d.add_paragraph("The parties stipulated to dismissal.")
        d.save(str(doc_path))
        out = mcp_server.intake_document(workdir=str(root / "wd"),
                                         document=str(doc_path))
        assert out["pages"] is None
        text = (root / "wd" / "document.txt").read_text(encoding="utf-8")
        assert "stipulated to dismissal" in text

    def test_txt_passthrough(self, root):
        doc = root / "memo.txt"
        doc.write_text("plain text memo", encoding="utf-8")
        out = mcp_server.intake_document(workdir=str(root / "wd"),
                                         document=str(doc))
        assert out["chars"] == len("plain text memo")

    def test_unsupported_extension(self, root):
        doc = root / "memo.wpd"
        doc.write_bytes(b"x")
        with pytest.raises(ToolError, match="unsupported document type"):
            mcp_server.intake_document(workdir=str(root / "wd"),
                                       document=str(doc))

    def test_document_outside_roots_rejected(self, root, tmp_path):
        outside = tmp_path / "evil.txt"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(ToolError, match="document"):
            mcp_server.intake_document(workdir=str(root / "wd"),
                                       document=str(outside))


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
