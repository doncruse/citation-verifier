"""MCP server: typed tool surface for the proposition pipeline.

Design: docs/plans/2026-07-02-mcp-server-design.md (issue #29). Every
tool wraps an existing run_* verb -- validate paths, call the verb,
serialize its stats. No pipeline logic lives here.

Launch: citation-verifier-mcp --root <dir> [--root <dir> ...]
    or: python -m citation_verifier.mcp_server --root <dir>
"""
from __future__ import annotations

import argparse
import asyncio
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


def _stats(obj: Any) -> dict[str, Any]:
    """Dataclass stats -> JSON-safe dict with ok=True (Path -> str)."""
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
