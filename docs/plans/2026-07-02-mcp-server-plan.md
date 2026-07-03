# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `citation_verifier.mcp_server` — a FastMCP stdio server exposing the proposition-pipeline verbs as typed, path-rooted MCP tools per `docs/plans/2026-07-02-mcp-server-design.md` (approved 2026-07-02) and issue #29.

**Architecture:** One new module `src/citation_verifier/mcp_server.py` that wraps the existing `run_*` verbs — every tool body is: validate paths against configured roots → call the verb → serialize its stats dataclass. Internal `_do_*` helpers are shared between the per-verb tools and the `full` chain tool. Jobs-mode LLM flow is served by `get_job` / `submit_job_result` over the existing `jobs/<phase>.json` + `jobs/<phase>_results.jsonl` files.

**Tech Stack:** Python 3.10+, `mcp` SDK (FastMCP), pdfplumber, python-docx, pytest (offline — no live CL calls).

## Global Constraints

- Working directory: the worktree at `.claude/worktrees/mcp-server-design` (branch `worktree-mcp-server-design`). All commands run there.
- Python is `venv/Scripts/python.exe` (Windows Git Bash; **never** `python`/`python3`). The venv lives in the MAIN checkout, not the worktree — use the absolute path `"/c/Users/Rebecca Fordon/Projects/citation-verifier/venv/Scripts/python.exe"` (alias below: `$PY`).
- ASCII-only console output in server/CLI code (Windows console; `[OK]`-style labels).
- The server **wraps, never forks** the pipeline: no pipeline logic in `mcp_server.py`, no writes except through the verbs (plus `intake_document`'s single `document.txt` and `submit_job_result`'s JSONL append via the existing `append_verdict_jsonl`).
- Tool names: `intake_document`, `extract`, `verify`, `merge`, `check_quotes`, `crosscheck`, `triage`, `assess`, `apply_assessments`, `report`, `full`, `get_job`, `submit_job_result`, `status` (client namespaces as `mcp__citation-verifier__*`).
- Every path-typed tool argument must pass `_resolve_under_roots` (design §4). No default roots.
- Tests are offline: monkeypatch `run_*` verbs or use tmp workdirs; never hit CourtListener.
- Commit after every task; push at the end (user syncs machines via git).

---

### Task 1: Packaging, server skeleton, path-root security

**Files:**
- Modify: `pyproject.toml` (optional-deps group + console script)
- Create: `src/citation_verifier/mcp_server.py`
- Create: `tests/test_mcp_server.py`

**Interfaces:**
- Produces: module `citation_verifier.mcp_server` with:
  - `mcp = FastMCP("citation_verifier")`
  - `configure_roots(roots: list[str | Path]) -> list[Path]` (module state `_ROOTS`)
  - `_resolve_under_roots(value: str, arg: str) -> Path` (raises `ToolError` on escape)
  - `_workdir(value: str) -> Path` (root check + must exist + must be a directory)
  - `main(argv: list[str] | None = None) -> int` (argparse `--root`, repeatable, required; runs stdio)
- Every later task registers tools on this `mcp` instance and uses these helpers.

- [ ] **Step 1: Add the `[mcp]` optional-dependency group and console script**

In `pyproject.toml`, extend `[project.optional-dependencies]`:

```toml
mcp = [
    "mcp>=1.9",
    "pdfplumber>=0.11",
    "python-docx>=1.1",
]
```

and `[project.scripts]`:

```toml
citation-verifier-mcp = "citation_verifier.mcp_server:main"
```

- [ ] **Step 2: Install into the venv**

Run: `"$PY" -m pip install -e ".[mcp]"` (from the worktree root)
Expected: installs `mcp`, `pdfplumber`, `python-docx` without dependency conflicts.

- [ ] **Step 3: Write failing tests for root confinement**

Create `tests/test_mcp_server.py`:

```python
"""Tests for the MCP server (design docs/plans/2026-07-02-mcp-server-design.md).

All offline: verbs are monkeypatched or run over tmp workdirs.
"""
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation_verifier.mcp_server'` (or collection error).

- [ ] **Step 5: Write the skeleton**

Create `src/citation_verifier/mcp_server.py`:

```python
"""MCP server: typed tool surface for the proposition pipeline.

Design: docs/plans/2026-07-02-mcp-server-design.md (issue #29). Every
tool wraps an existing run_* verb -- validate paths, call the verb,
serialize its stats. No pipeline logic lives here.

Launch: citation-verifier-mcp --root <dir> [--root <dir> ...]
    or: python -m citation_verifier.mcp_server --root <dir>
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import proposition_pipeline as pp
from .executor import Verdict, append_verdict_jsonl

mcp = FastMCP("citation_verifier")

# Configured allowlist of directories every path argument must resolve
# under. Set by main()/configure_roots(); empty means "refuse everything"
# (the boundary is explicit configuration, not convention -- design SS4).
_ROOTS: list[Path] = []


def configure_roots(roots: list[str | Path]) -> list[Path]:
    """Resolve and install the --root allowlist (replaces any prior set)."""
    resolved = []
    for r in roots:
        p = Path(r).resolve()
        if not p.is_dir():
            raise ValueError(f"--root is not a directory: {r}")
        resolved.append(p)
    _ROOTS[:] = resolved
    return resolved


def _resolve_under_roots(value: str, arg: str) -> Path:
    """Resolve a caller-supplied path and require it inside a root."""
    if not _ROOTS:
        raise ToolError(
            "server misconfigured: no --root directories were set")
    resolved = Path(value).resolve()
    for root in _ROOTS:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise ToolError(
        f"{arg} is outside the configured roots: {value}")


def _workdir(value: str) -> Path:
    """Root-check a workdir argument and require an existing directory."""
    p = _resolve_under_roots(value, "workdir")
    if not p.is_dir():
        raise ToolError(f"workdir does not exist: {value}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="citation-verifier-mcp",
        description="MCP stdio server for the proposition pipeline "
                    "(wraps the verify-propositions verbs).",
    )
    parser.add_argument(
        "--root", action="append", required=True, dest="roots",
        metavar="DIR",
        help="Directory every workdir/document path must live under "
             "(repeatable; required)",
    )
    args = parser.parse_args(argv)
    configure_roots(args.roots)
    mcp.run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): server skeleton with path-root confinement (#29)"
```

---

### Task 2: Stats serialization + the six simple verb tools

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp`, `_workdir` from Task 1; `pp.run_merge/run_check_quotes/run_crosscheck/run_triage/run_report` (existing).
- Produces:
  - `_stats(obj: Any) -> dict[str, Any]` — dataclass → JSON-safe dict (`Path` → str), `{}` for None
  - `_call(fn, *args, **kwargs)` — invokes a verb, mapping `FileNotFoundError` / `ValueError` / `ExecutorAuthError` to `ToolError`
  - Tools (all sync, all returning `dict`): `merge(workdir)`, `check_quotes(workdir)`, `crosscheck(workdir)`, `triage(workdir)`, `report(workdir)`, `status(workdir)`
  - `_pending_jobs(workdir: Path, phase: str) -> list[dict]` — job summaries (`job_id`, `claim_ids`, `files`) from `jobs/<phase>.json`, `[]` if absent. Tasks 4-6 reuse it.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k "SimpleVerb or Status"`
Expected: FAIL — `AttributeError: module ... has no attribute 'merge'`.

- [ ] **Step 3: Implement helpers and tools**

Add to `mcp_server.py` (below `_workdir`, above `main`):

```python
def _stats(obj: Any) -> dict[str, Any]:
    """Dataclass stats -> JSON-safe dict with ok=True; {} stays honest."""
    if obj is None:
        return {"ok": True}
    d = json.loads(json.dumps(asdict(obj), default=str))
    return {"ok": True, **d}


def _call(fn, *args, **kwargs):
    """Run a verb, mapping known failures to actionable tool errors."""
    from .executor import ExecutorAuthError
    try:
        return fn(*args, **kwargs)
    except (FileNotFoundError, ValueError, ExecutorAuthError) as e:
        raise ToolError(str(e)) from e


def _pending_jobs(workdir: Path, phase: str) -> list[dict[str, Any]]:
    """Job summaries (no prompts -- those are large; use get_job) from
    the jobs file the executor wrote at pend time."""
    jobs_file = workdir / "jobs" / f"{phase}.json"
    if not jobs_file.exists():
        return []
    jobs = json.loads(jobs_file.read_text(encoding="utf-8"))
    return [{"job_id": j["job_id"], "claim_ids": j["claim_ids"],
             "files": j.get("files", [])} for j in jobs]


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def merge(workdir: str) -> dict:
    """Join claims.csv to verification_results.csv + link opinion files
    (verb 2). Requires the verify tool to have run first."""
    stats = _call(pp.run_merge, _workdir(workdir))
    return _stats(stats)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def check_quotes(workdir: str) -> dict:
    """Deterministic quote verdicts + quote floors (verb 3). Run after
    merge."""
    stats = _call(pp.run_check_quotes, _workdir(workdir))
    return _stats(stats)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def crosscheck(workdir: str) -> dict:
    """Deterministic TOA-vs-body, court, and pincite flags (verb 4).
    Flags only -- never moves assessment colors."""
    stats = _call(pp.run_crosscheck, _workdir(workdir))
    return _stats(stats)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def triage(workdir: str) -> dict:
    """Assessment-depth track per claim (verb 5): full | fast |
    deterministic."""
    stats = _call(pp.run_triage, _workdir(workdir))
    return _stats(stats)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def report(workdir: str) -> dict:
    """Render claims.csv -> report.html + findings.json (verb 8)."""
    wd = _workdir(workdir)
    stats = _call(pp.run_report, wd)
    out = _stats(stats)
    out["findings_json"] = str(wd / "findings.json")
    return out


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True,
                       "openWorldHint": False})
def status(workdir: str) -> dict:
    """Workdir progress probe: which outputs exist, run.json stamps,
    pending LLM-job counts. Read-only."""
    wd = _workdir(workdir)
    run: dict[str, Any] = {}
    run_path = wd / "run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text(encoding="utf-8"))
    files = {name: (wd / name).exists()
             for name in ("claims.csv", "verification_results.csv",
                          "report.html", "findings.json")}
    pending = {phase: len(_pending_jobs(wd, phase))
               for phase in ("extract", "assess")}
    return {"ok": True, "files": files, "run": run,
            "pending_jobs": pending}
```

- [ ] **Step 4: Run the full test file**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS. If `@mcp.tool(annotations=...)` raises `TypeError` (older SDK), upgrade `mcp` (`"$PY" -m pip install -U "mcp>=1.9"`) rather than dropping annotations.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): merge/check-quotes/crosscheck/triage/report/status tools"
```

---

### Task 3: The `verify` tool (async, progress, cache_dir)

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `pp.run_verify(workdir, citations=None, force=False, progress_callback=None, cache_dir=None) -> PipelineResult | None` (async).
- Produces:
  - `async _do_verify(wd: Path, citations, force, cache_dir, ctx) -> dict` (shared with `full`, Task 6)
  - Tool `verify(workdir: str, citations: list[str] | None = None, force: bool = False, cache_dir: str | None = None, ctx: Context | None = None) -> dict`
  - Return shape: `{"ok": True, "already_done": bool, "wave1_misses": int, "wave1_downloads": dict, "wave2_downloads": dict}`

- [ ] **Step 1: Write failing tests**

Append:

```python
import asyncio


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

        async def fake(workdir, citations=None, force=False,
                       progress_callback=None, cache_dir=None):
            seen.update(citations=citations, force=force,
                        cache_dir=cache_dir)
            if progress_callback:
                progress_callback(1, 2)
            return self._fake_result()

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k Verify`
Expected: FAIL — no attribute `verify`.

- [ ] **Step 3: Implement**

Add near the other tools (plus `import asyncio` at the top of the module):

```python
async def _do_verify(wd: Path, citations: list[str] | None, force: bool,
                     cache_dir: str | None,
                     ctx: Context | None) -> dict[str, Any]:
    resolved_cache = (str(_resolve_under_roots(cache_dir, "cache_dir"))
                      if cache_dir else None)
    progress_callback = None
    if ctx is not None:
        loop = asyncio.get_running_loop()

        def progress_callback(done: int, total: int) -> None:
            loop.create_task(ctx.report_progress(done, total))

    from .executor import ExecutorAuthError
    try:
        result = await pp.run_verify(
            wd, citations=citations, force=force,
            progress_callback=progress_callback, cache_dir=resolved_cache)
    except (FileNotFoundError, ValueError, ExecutorAuthError) as e:
        raise ToolError(str(e)) from e
    if result is None:
        return {"ok": True, "already_done": True}
    return {"ok": True, "already_done": False,
            "wave1_misses": len(result.wave1.miss_indices),
            "wave1_downloads": result.wave1.download_stats,
            "wave2_downloads": result.wave2.download_stats}


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": True})
async def verify(workdir: str, citations: list[str] | None = None,
                 force: bool = False, cache_dir: str | None = None,
                 ctx: Context | None = None) -> dict:
    """Wave1 + wave2 citation verification + opinion downloads (verb 1).

    Long-running (CourtListener is rate-limited to ~1 request/second);
    progress is reported via MCP notifications. Idempotent: no-ops when
    verification_results.csv exists (already_done=true; force=true to
    redo), and a killed call can simply be re-issued to resume. Omitting
    `citations` derives them from claims.csv / the extract lists.
    """
    return await _do_verify(_workdir(workdir), citations, force,
                            cache_dir, ctx)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): async verify tool with progress + cache_dir"
```

---

### Task 4: `extract` and `assess` tools with pending-job summaries

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `pp.run_extract(workdir, document, executor=None, force=False) -> ExtractStats | None` (`.pending: bool`); `pp.run_assess(workdir, executor=None, prompt_version=...) -> AssessStats` (`.pending: int`); `pp.ASSESS_V2_PROMPT_VERSION`; `_pending_jobs` (Task 2).
- Produces:
  - `_do_extract(wd, document: Path, force) -> dict` and `_do_assess(wd, prompt_version) -> dict` (shared with `full`)
  - Tools `extract(workdir, document, force=False)` and `assess(workdir, prompt_version=None)`
  - Pending shape (both): `{"ok": True, "pending": True, "pending_jobs": [...], "next": "<dispatch instructions>"}`. Non-pending extract: `_stats(ExtractStats)`; non-pending assess: `_stats(AssessStats)` with `"pending": 0`.
- Executor is always the jobs-mode default (`executor=None`) — design §6.

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k "Extract or Assess"`
Expected: FAIL — no attribute `extract`.

- [ ] **Step 3: Implement**

```python
_DISPATCH_NEXT = (
    "dispatch one subagent per pending job: get_job for the full prompt, "
    "run it verbatim, submit the result envelope via submit_job_result, "
    "then call this tool again to ingest")


def _do_extract(wd: Path, document: Path, force: bool) -> dict[str, Any]:
    stats = _call(pp.run_extract, wd, document, executor=None, force=force)
    if stats is None:
        return {"ok": True, "already_done": True}
    if stats.pending:
        return {"ok": True, "pending": True,
                "pending_jobs": _pending_jobs(wd, "extract"),
                "next": _DISPATCH_NEXT}
    return _stats(stats)


def _do_assess(wd: Path, prompt_version: str | None) -> dict[str, Any]:
    pv = prompt_version or pp.ASSESS_V2_PROMPT_VERSION
    stats = _call(pp.run_assess, wd, executor=None, prompt_version=pv)
    if stats.pending:
        return {"ok": True, "pending": True, "stats": asdict(stats),
                "pending_jobs": _pending_jobs(wd, "assess"),
                "next": _DISPATCH_NEXT}
    out = _stats(stats)
    out["pending"] = False
    return out


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def extract(workdir: str, document: str, force: bool = False) -> dict:
    """LLM verb 0: document -> claims.csv + TOA/body citation lists.

    Jobs mode: first call returns pending=true with job summaries; use
    get_job / submit_job_result, then call again to ingest. No-ops
    (already_done=true) when claims.csv exists; force=true to redo.
    """
    wd = _workdir(workdir)
    doc = _resolve_under_roots(document, "document")
    if not doc.is_file():
        raise ToolError(f"document does not exist: {document}")
    return _do_extract(wd, doc, force)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def assess(workdir: str, prompt_version: str | None = None) -> dict:
    """LLM verb 6: grouped assessment jobs (jobs mode; default
    prompt_version assess-v2, the two-axis prompt). Same pending
    protocol as extract; rerun to ingest submitted verdicts.
    """
    return _do_assess(_workdir(workdir), prompt_version)
```

Note for the implementer: `extract`'s pending branch (`stats.pending`) is only reached when `stats` is not None; the `pending` key is absent from the done branch because `_stats(ExtractStats(...))` already carries `pending: False` from the dataclass field — the `test_extract_done` assertion relies on that.

- [ ] **Step 4: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): extract/assess tools with pending-jobs protocol"
```

---

### Task 5: `get_job` and `submit_job_result`

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `Verdict`, `append_verdict_jsonl` (imported in Task 1); jobs-file format written by `AgentToolExecutor` (`job_to_json`: `job_id`, `claim_ids`, `prompt`, `prompt_version`, `files`, `schema`, `max_chars`).
- Produces:
  - `get_job(workdir, phase, job_id) -> dict` — full `prompt` + `files` + `prompt_version` + `claim_ids`
  - `submit_job_result(workdir, phase, result: dict) -> dict` — validates the envelope `{claim_id, prompt_version, fields[, model]}` and appends one line to `jobs/<phase>_results.jsonl`
  - `_check_phase(phase: str) -> str` (raises `ToolError` unless `extract`/`assess`)

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k "GetJob or Submit"`
Expected: FAIL — no attribute `get_job`.

- [ ] **Step 3: Implement**

```python
def _check_phase(phase: str) -> str:
    if phase not in ("extract", "assess"):
        raise ToolError("phase must be 'extract' or 'assess'")
    return phase


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True,
                       "openWorldHint": False})
def get_job(workdir: str, phase: str, job_id: str) -> dict:
    """Fetch one pending LLM job's full prompt for subagent dispatch.

    Reads the pipeline-written jobs/<phase>.json (call the extract or
    assess tool first to generate it). The subagent should run the
    prompt verbatim, Reading the listed files itself.
    """
    wd = _workdir(workdir)
    _check_phase(phase)
    jobs_file = wd / "jobs" / f"{phase}.json"
    if not jobs_file.exists():
        raise ToolError(f"no jobs/{phase}.json -- run the {phase} tool "
                        "first to generate pending jobs")
    for j in json.loads(jobs_file.read_text(encoding="utf-8")):
        if j["job_id"] == job_id:
            return {"ok": True, "job_id": j["job_id"],
                    "claim_ids": j["claim_ids"], "prompt": j["prompt"],
                    "prompt_version": j["prompt_version"],
                    "files": j.get("files", [])}
    raise ToolError(f"job_id {job_id!r} not found in jobs/{phase}.json")


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False,
                       "openWorldHint": False})
def submit_job_result(workdir: str, phase: str, result: dict) -> dict:
    """Append one validated result envelope to jobs/<phase>_results.jsonl.

    Envelope shape: {"claim_id": str, "prompt_version": str,
    "fields": object[, "model": str]} -- the same line subagents used
    to append by hand. After submitting all jobs, call the phase's verb
    tool again to ingest. Appends are serialized by the server; this
    tool never touches claims.csv (apply_assessments owns it).
    """
    wd = _workdir(workdir)
    _check_phase(phase)
    for key in ("claim_id", "prompt_version", "fields"):
        if key not in result:
            raise ToolError(f"result envelope missing {key!r} "
                            "(expected claim_id, prompt_version, fields)")
    if not isinstance(result["fields"], dict):
        raise ToolError("result 'fields' must be a JSON object")
    verdict = Verdict(claim_id=str(result["claim_id"]),
                      fields=result["fields"],
                      model=str(result.get("model", "")),
                      prompt_version=str(result["prompt_version"]))
    results_path = wd / "jobs" / f"{phase}_results.jsonl"
    append_verdict_jsonl(results_path, verdict)
    total = len(results_path.read_text(encoding="utf-8").splitlines())
    return {"ok": True, "results_file": str(results_path),
            "total_results": total}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): get_job/submit_job_result jobs-mode plumbing"
```

---

### Task 6: The `full` chain tool

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `_do_extract`, `_do_verify`, `_do_assess`, `_call`, `_stats`, `_workdir`, `_resolve_under_roots`; `pp.run_merge/run_check_quotes/run_crosscheck/run_triage/run_apply_assessments/run_report`.
- Produces: tool `full(workdir, document=None, force=False, prompt_version=None, citations=None, cache_dir=None, ctx=None) -> dict` returning `{"status": "pending-extract" | "pending-assess" | "complete", "steps": {<verb>: <that verb's dict>}}` — same stop-at-pending semantics as the CLI `full` verb.

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k Full`
Expected: FAIL — no attribute `full`.

- [ ] **Step 3: Implement**

```python
@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": True})
async def full(workdir: str, document: str | None = None,
               force: bool = False, prompt_version: str | None = None,
               citations: list[str] | None = None,
               cache_dir: str | None = None,
               ctx: Context | None = None) -> dict:
    """Run the whole pipeline: [extract ->] verify -> merge ->
    check_quotes -> crosscheck -> triage -> assess (-> apply_assessments
    -> report once verdicts are complete).

    Mirrors the CLI's `full` verb: stops with status pending-extract /
    pending-assess while LLM jobs are outstanding (dispatch via get_job
    / submit_job_result, then call full again -- every verb is
    idempotent). status=complete means report.html is written.
    """
    wd = _workdir(workdir)
    steps: dict[str, Any] = {}
    out = {"status": "complete", "steps": steps}

    if document:
        doc = _resolve_under_roots(document, "document")
        if not doc.is_file():
            raise ToolError(f"document does not exist: {document}")
        steps["extract"] = _do_extract(wd, doc, force)
        if steps["extract"].get("pending"):
            out["status"] = "pending-extract"
            return out

    steps["verify"] = await _do_verify(wd, citations, force, cache_dir,
                                       ctx)
    steps["merge"] = _stats(_call(pp.run_merge, wd))
    steps["check_quotes"] = _stats(_call(pp.run_check_quotes, wd))
    steps["crosscheck"] = _stats(_call(pp.run_crosscheck, wd))
    steps["triage"] = _stats(_call(pp.run_triage, wd))

    steps["assess"] = _do_assess(wd, prompt_version)
    if steps["assess"].get("pending"):
        out["status"] = "pending-assess"
        return out

    pv = prompt_version or pp.ASSESS_V2_PROMPT_VERSION
    steps["apply_assessments"] = _stats(
        _call(pp.run_apply_assessments, wd, prompt_version=pv))
    report_stats = _call(pp.run_report, wd)
    steps["report"] = _stats(report_stats)
    steps["report"]["findings_json"] = str(wd / "findings.json")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): full chain tool with CLI-parity pending stops"
```

---

### Task 7: `intake_document`

**Files:**
- Modify: `src/citation_verifier/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `_workdir`, `_resolve_under_roots`; pdfplumber; python-docx.
- Produces: tool `intake_document(workdir, document) -> {"ok": True, "path": str, "chars": int, "pages": int | None}` writing `<workdir>/document.txt`. This is the one new capability (design §5 note: ~60 lines) — everything else wraps existing verbs.

- [ ] **Step 1: Write failing tests (with self-building fixtures)**

Append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k Intake`
Expected: FAIL — no attribute `intake_document`.

- [ ] **Step 3: Implement**

```python
@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def intake_document(workdir: str, document: str) -> dict:
    """Extract text from a PDF / DOCX / TXT document into
    <workdir>/document.txt so downstream callers need no shell.

    PDF via pdfplumber (pages joined by blank lines -- the parser
    treats consecutive newlines as paragraph breaks), DOCX via
    python-docx paragraphs, .txt/.md copied through. Returns the
    written path, character count, and page count (PDF only).
    """
    wd = _workdir(workdir)
    doc = _resolve_under_roots(document, "document")
    if not doc.is_file():
        raise ToolError(f"document does not exist: {document}")
    suffix = doc.suffix.lower()
    pages: int | None = None
    try:
        if suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(doc) as pdf:
                page_texts = [p.extract_text() or "" for p in pdf.pages]
            pages = len(page_texts)
            text = "\n\n".join(page_texts)
        elif suffix == ".docx":
            import docx
            text = "\n".join(p.text for p in docx.Document(str(doc)).paragraphs)
        elif suffix in (".txt", ".md"):
            text = doc.read_text(encoding="utf-8", errors="replace")
        else:
            raise ToolError(f"unsupported document type {suffix!r} "
                            "(supported: .pdf, .docx, .txt, .md)")
    except ToolError:
        raise
    except Exception as e:  # unreadable/corrupt document
        raise ToolError(f"could not read {doc.name}: {e}") from e
    target = wd / "document.txt"
    target.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(target), "chars": len(text),
            "pages": pages}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v`
Expected: all PASS. If the PDF test fails inside pdfplumber, debug the fixture bytes (offsets are computed, so failures mean a structural typo) rather than loosening the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): intake_document tool (pdf/docx/txt -> document.txt)"
```

---

### Task 8: Registration smoke test, docs, full suite, push

**Files:**
- Modify: `tests/test_mcp_server.py` (smoke tests)
- Modify: `CLAUDE.md` (Files table + skills-adjacent note)
- Modify: `docs/plans/2026-07-02-mcp-server-design.md` (status line)

**Interfaces:** none new — verification and documentation.

- [ ] **Step 1: Add smoke tests**

Append to `tests/test_mcp_server.py`:

```python
EXPECTED_TOOLS = {
    "intake_document", "extract", "verify", "merge", "check_quotes",
    "crosscheck", "triage", "assess", "apply_assessments", "report",
    "full", "get_job", "submit_job_result", "status",
}


class TestRegistration:
    def test_all_tools_registered(self):
        tools = asyncio.run(mcp_server.mcp.list_tools())
        assert {t.name for t in tools} == EXPECTED_TOOLS

    def test_every_tool_has_description(self):
        tools = asyncio.run(mcp_server.mcp.list_tools())
        for t in tools:
            assert t.description and len(t.description) > 20, t.name
```

Wait — `apply_assessments` has no task yet if only Tasks 2-7 registered tools. It was NOT implemented above. Add it in this step (it is a one-liner in the Task 2 pattern):

```python
@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True,
                       "openWorldHint": False})
def apply_assessments(workdir: str, prompt_version: str | None = None) -> dict:
    """Ingest verdicts JSONL into claims.csv with schema validation and
    quote-floor enforcement (verb 7). The pipeline owns the CSV."""
    pv = prompt_version or pp.ASSESS_V2_PROMPT_VERSION
    stats = _call(pp.run_apply_assessments, _workdir(workdir),
                  prompt_version=pv)
    return _stats(stats)
```

plus a unit test in the Task 2 style:

```python
class TestApplyAssessments:
    def test_apply(self, root, monkeypatch):
        from citation_verifier.proposition_pipeline import ApplyStats
        seen = {}

        def fake(workdir, prompt_version=None):
            seen["pv"] = prompt_version
            return ApplyStats(applied=3, invalid=1,
                              invalid_claims=["wd-02"])
        monkeypatch.setattr(mcp_server.pp, "run_apply_assessments", fake)
        out = mcp_server.apply_assessments(workdir=str(root / "wd"))
        assert seen["pv"] == mcp_server.pp.ASSESS_V2_PROMPT_VERSION
        assert out["applied"] == 3 and out["invalid_claims"] == ["wd-02"]
```

- [ ] **Step 2: Run the new tests, expect the registration test to drive out `apply_assessments`, implement it, re-run**

Run: `"$PY" -m pytest tests/test_mcp_server.py -v -k "Registration or Apply"`
Expected: FAIL first (missing tool), PASS after adding the tool above.

- [ ] **Step 3: Manual server-start check**

Run: `"$PY" -m citation_verifier.mcp_server --help`
Expected: usage text with `--root`. Then confirm the required-root exit:
`"$PY" -m citation_verifier.mcp_server` → exits non-zero with "required: --root".

- [ ] **Step 4: Run the whole offline suite**

Run: `"$PY" -m pytest -q`
Expected: everything green (existing suite untouched — the server only adds a module). Investigate any failure before proceeding; do not commit on red.

- [ ] **Step 5: Update docs**

- `CLAUDE.md` Files table (Core library section), new row after `report_template.py`:
  `| mcp_server.py | MCP stdio server (issue #29): the verify-propositions verbs + intake_document + get_job/submit_job_result as typed, path-rooted tools. Jobs-mode only. Launch: citation-verifier-mcp --root <dir> (needs pip install -e ".[mcp]"). Design: docs/plans/2026-07-02-mcp-server-design.md |`
- `docs/plans/2026-07-02-mcp-server-design.md`: change `**Status:** Draft for review` to `**Status:** Approved 2026-07-02; implemented (see 2026-07-02-mcp-server-plan.md)`.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "feat(mcp): apply_assessments tool, registration smoke tests, docs (#29)"
git push
```

---

## Explicitly not in this plan (per approved design §9)

- `verify_citation` / `verify_citations_batch` general tools; sdk/api executors over MCP; hosted/HTTP transport; legacy verify-brief verbs; MCP resources; the mcp-builder eval XML (the migration's regression gate is the existing import-memo adversarial eval, per issue #29 acceptance 3 — a local eval set can follow once the Cabinet swap happens).

## Self-review notes

- Spec coverage: design §3 (Task 1), §4 (Task 1), §5 (Tasks 2-8 — all 14 tools), §6 (Tasks 4-5), §7 (Task 3), §8 (`_call` in Task 2 + per-tool ToolError paths), §10 (each task's tests), §12 (CLAUDE.md row documents launch form).
- Type consistency: `_do_extract(wd, document: Path, force)` / `_do_assess(wd, prompt_version)` / `_do_verify(wd, citations, force, cache_dir, ctx)` are used with those exact signatures in Tasks 4 and 6.
- Known judgment call for the implementer: if `mcp.list_tools()` is named differently in the installed SDK version, use the FastMCP instance's documented listing method; the assertion set stays the same.
