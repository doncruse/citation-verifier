"""PoC for the proposition-verifier design's AgentSDKExecutor (design §5).

Validates, on this machine:
1. claude-agent-sdk can run a headless query (auth via CLI credentials —
   may auto-refresh a stale OAuth token on use).
2. allowed_tools=["Read"] restriction works and the agent can read an
   opinion file from a workdir.
3. A real Withers assess job (jobs/assess-format prompt) returns parseable
   verdict JSON, with model + cost reported.

Run: venv/Scripts/python.exe tests/poc_agent_sdk_executor.py [--job N]

Inside a Claude Code session the parent's ANTHROPIC_BASE_URL / CLAUDE* env
leaks into the child CLI; we strip those (same as measure_withers_assessment)
so the SDK uses the standalone CLI credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Strip parent-session env BEFORE importing the SDK (it spawns the CLI).
for k in list(os.environ):
    if k.startswith("ANTHROPIC") or k.startswith("CLAUDE"):
        del os.environ[k]

import anyio  # noqa: E402
from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: E402

_DATA = Path(__file__).parent / "data"
_JOBS = _DATA / "withers_assessment_jobs.json"


async def smoke() -> bool:
    print("--- 1. auth smoke test (no tools, haiku) ---")
    ok = False
    try:
        # Consume the generator fully — returning from inside the async-for
        # leaves it mid-close and segfaults on interpreter shutdown.
        async for msg in query(
            prompt="Reply with exactly: OK",
            options=ClaudeAgentOptions(
                allowed_tools=[], max_turns=1, model="haiku",
            ),
        ):
            t = type(msg).__name__
            if t == "ResultMessage":
                print(f"  result: {getattr(msg, 'result', None)!r}")
                print(f"  is_error: {getattr(msg, 'is_error', None)}, "
                      f"cost_usd: {getattr(msg, 'total_cost_usd', None)}")
                ok = not getattr(msg, "is_error", True)
    except Exception as e:  # noqa: BLE001
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
    return ok


async def assess_job(n: int) -> None:
    jobs = json.loads(_JOBS.read_text(encoding="utf-8"))
    job = jobs[n]
    print(f"--- 2. real assess job: {job['row_id']} "
          f"({Path(job['opinion_path']).name[:50]}) ---")
    opts = ClaudeAgentOptions(
        allowed_tools=["Read"],
        max_turns=6,
        model="opus",
        cwd=str(Path(__file__).parent.parent),
    )
    try:
        async for msg in query(prompt=job["prompt"], options=opts):
            t = type(msg).__name__
            if t == "ResultMessage":
                text = getattr(msg, "result", "") or ""
                print(f"  is_error: {getattr(msg, 'is_error', None)}")
                print(f"  cost_usd: {getattr(msg, 'total_cost_usd', None)}, "
                      f"turns: {getattr(msg, 'num_turns', None)}, "
                      f"duration_ms: {getattr(msg, 'duration_ms', None)}")
                print(f"  raw result: {text[:400]}")
                try:
                    start = text.find("{")
                    end = text.rfind("}")
                    verdict = json.loads(text[start:end + 1])
                    print(f"  PARSED VERDICT: assessment={verdict.get('assessment')}")
                except Exception as e:  # noqa: BLE001
                    print(f"  parse failed: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"  EXCEPTION: {type(e).__name__}: {e}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int, default=None,
                    help="run real assess job N from withers_assessment_jobs.json")
    args = ap.parse_args()

    ok = await smoke()
    print(f"  -> auth smoke: {'PASS' if ok else 'FAIL'}")
    if ok and args.job is not None:
        await assess_job(args.job)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    anyio.run(main)
