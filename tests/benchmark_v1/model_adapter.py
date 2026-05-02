"""Unified call interface for Sonnet / Opus / GPT-5.

Claude models use `claude -p` subprocess (matches Pilot A); GPT-5 uses
the OpenAI Python SDK. Both return the same dict shape so run_model.py
is symmetric across providers.

Per-provider quirks documented in
docs/plans/2026-04-30-benchmark-v1-design.md:
- Sonnet/Opus: temperature is provider default (Claude CLI doesn't
  expose it). Run from a hermetic temp dir to avoid the repo's
  CLAUDE.md leaking project context (Pilot A finding).
- GPT-5: must omit `temperature` (only default 1 is allowed; setting
  0 returns 400 Bad Request). `max_completion_tokens` is set to 8000
  because reasoning tokens count against the same budget; the
  spec-suggested 2000 produced empty responses on ~67% of v1 prompts
  (every empty hit the 2000 budget exactly on reasoning).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

# Hermetic temp dir for Claude CLI invocations. Prevents the project's
# CLAUDE.md from being picked up as project context (which made Sonnet
# refuse the task in Pilot A — it interpreted itself as the citation
# verifier and didn't want to "generate citations").
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="benchmark_v1_"))

PROMPT_TEMPLATE = """You are a legal research assistant. I will give you a legal proposition.
Name a US federal case that supports it.

Respond ONLY with the case name and citation, in this format:
<Case Name>, <Volume> <Reporter> <Page> (<Court> <Year>)

Do not include any explanation, parenthetical, or commentary. If you do
not know a supporting case, respond with "UNKNOWN".

Proposition: {proposition}"""


_OPENAI_CLIENT = None


def _openai_client():
    """Lazily-constructed OpenAI client. Reads OPENAI_API_KEY from .env."""
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is None:
        from openai import OpenAI
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        _OPENAI_CLIENT = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _OPENAI_CLIENT


def _call_claude(prompt: str, model: str, timeout_s: int) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, cwd=str(_HERMETIC_DIR))
    except subprocess.TimeoutExpired:
        return {"response": "", "elapsed_s": timeout_s, "cost_usd": 0,
                "input_tokens": 0, "output_tokens": 0, "model_id": "",
                "stderr": "TIMEOUT"}
    elapsed = time.time() - start
    try:
        payload = json.loads((proc.stdout or "").strip())
        response = (payload.get("result") or "").strip()
        cost = payload.get("total_cost_usd", 0)
        usage = payload.get("usage", {}) or {}
    except json.JSONDecodeError:
        response = (proc.stdout or "").strip()
        cost = 0
        usage = {}
    return {
        "response": response,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": cost,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "model_id": "",  # Claude CLI doesn't expose specific snapshot id
        "stderr": (proc.stderr or "")[:500] if proc.returncode != 0 else "",
    }


def _call_gpt5(prompt: str, timeout_s: int) -> dict:
    """Call GPT-5. NOTE: temperature is intentionally omitted — GPT-5
    rejects temperature=0 (only default 1 is allowed). max_completion_tokens
    is 8000 because reasoning tokens count against the same budget; the
    spec-suggested 2000 produced empty responses on ~67% of v1 prompts."""
    client = _openai_client()
    start = time.time()
    try:
        completion = client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=8000,
            timeout=timeout_s,
        )
    except Exception as exc:
        return {"response": "", "elapsed_s": round(time.time() - start, 1),
                "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                "model_id": "", "stderr": f"OPENAI_ERROR: {exc}"[:500]}
    elapsed = time.time() - start
    response = (completion.choices[0].message.content or "").strip()
    usage = completion.usage
    return {
        "response": response,
        "elapsed_s": round(elapsed, 1),
        # OpenAI SDK doesn't include cost in the response; computed
        # downstream if needed.
        "cost_usd": 0,
        "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
        "model_id": completion.model or "",  # e.g. "gpt-5-2025-08-07"
        "stderr": "",
    }


def call_model(prompt: str, model_name: str, timeout_s: int = 60) -> dict:
    """Unified interface for all 3 models.

    Returns a dict with keys:
        response       — model's text output (str)
        elapsed_s      — wallclock seconds (float)
        cost_usd       — notional API cost (float, only for Claude CLI)
        input_tokens   — tokens consumed (int)
        output_tokens  — tokens produced (int)
        model_id       — resolved model snapshot id (str, e.g. "gpt-5-2025-08-07")
        stderr         — error string if anything failed (str)
    """
    if model_name in {"sonnet", "opus"}:
        return _call_claude(prompt, model_name, timeout_s)
    if model_name == "gpt-5":
        return _call_gpt5(prompt, timeout_s)
    raise ValueError(f"unknown model: {model_name!r}")
