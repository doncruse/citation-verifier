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
