"""LLM executor protocol + adapters (pipeline redesign design SS5).

An LLM verb (assess, extract, prescreen) emits transport-neutral Jobs and
consumes Verdicts; the executor between them is pluggable. This module
defines the protocol, the JSONL verdict serialization shared by all
adapters (jobs/<phase>_results.jsonl sidecars), and the offline
RecordedExecutor -- the assessment-side mirror of tests/cassette_client.py.

Live adapters (AgentSDKExecutor, AgentToolExecutor, MessagesAPIExecutor)
come in later steps; see docs/plans/2026-06-11-proposition-verifier-
pipeline-design.md SS5.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol


@dataclass
class Job:
    """One LLM call: rendered prompt + the claims it answers for."""
    job_id: str
    claim_ids: list[str]
    prompt: str
    prompt_version: str
    files: list[str] = field(default_factory=list)
    schema: dict[str, Any] | None = None
    max_chars: int | None = None


@dataclass
class Verdict:
    """One claim's structured result from an LLM job."""
    claim_id: str
    fields: dict[str, Any]
    model: str = ""
    prompt_version: str = ""
    elapsed_s: float = 0.0
    cost_usd: float = 0.0


class LLMExecutor(Protocol):
    def run(self, jobs: list[Job]) -> Iterable[Verdict]: ...


def verdict_to_json(verdict: Verdict) -> dict[str, Any]:
    return {
        "claim_id": verdict.claim_id,
        "prompt_version": verdict.prompt_version,
        "model": verdict.model,
        "elapsed_s": verdict.elapsed_s,
        "cost_usd": verdict.cost_usd,
        "fields": verdict.fields,
    }


def verdict_from_json(data: dict[str, Any]) -> Verdict:
    return Verdict(
        claim_id=data["claim_id"],
        fields=data.get("fields", {}),
        model=data.get("model", ""),
        prompt_version=data.get("prompt_version", ""),
        elapsed_s=data.get("elapsed_s", 0.0),
        cost_usd=data.get("cost_usd", 0.0),
    )


def load_verdicts_jsonl(path: str | Path) -> list[Verdict]:
    path = Path(path)
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(verdict_from_json(json.loads(line)))
    return out


def append_verdict_jsonl(path: str | Path, verdict: Verdict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(verdict_to_json(verdict)) + "\n")


def job_to_json(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "claim_ids": job.claim_ids,
        "prompt": job.prompt,
        "prompt_version": job.prompt_version,
        "files": job.files,
        "schema": job.schema,
        "max_chars": job.max_chars,
    }


class AgentToolExecutor:
    """Jobs mode (design SS5): emits jobs/<phase>.json and produces no
    verdicts. The orchestrating Claude Code session dispatches one
    Agent-tool subagent per job; each appends a verdict line to the
    results JSONL. Rerun the verb to ingest progress (resume key =
    claim_id + prompt_version). This is the in-session default because
    the Agent tool is the one transport that always works inside a
    Claude Code session (design SS1 fact 3).
    """

    def __init__(self, jobs_path: str | Path):
        self.jobs_path = Path(jobs_path)
        self.pending: list[str] = []

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs_path.write_text(
            json.dumps([job_to_json(j) for j in jobs], indent=2),
            encoding="utf-8")
        self.pending = [cid for j in jobs for cid in j.claim_ids]
        return iter(())


class RecordedVerdictMiss(KeyError):
    """Raised in replay when (claim_id, prompt_version) has no recording.

    A prompt-template change bumps the version and deliberately invalidates
    the recording -- re-record live, exactly the cassette policy."""


class RecordedExecutor:
    """Replays verdicts from a recorded jobs/<phase>_results.jsonl.

    Keyed by (claim_id, prompt_version); the rendered prompt text is
    ignored. Duplicate keys (resumed recording runs append) resolve to the
    last line, matching how a resuming live run supersedes earlier rows.
    """

    def __init__(self, results_path: str | Path):
        self.results_path = Path(results_path)
        self._recorded: dict[tuple[str, str], Verdict] = {}
        for v in load_verdicts_jsonl(self.results_path):
            self._recorded[(v.claim_id, v.prompt_version)] = v
        self.misses: list[tuple[str, str]] = []

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        for job in jobs:
            for claim_id in job.claim_ids:
                key = (claim_id, job.prompt_version)
                if key not in self._recorded:
                    self.misses.append(key)
                    raise RecordedVerdictMiss(
                        f"no recorded verdict for claim_id={claim_id} "
                        f"prompt_version={job.prompt_version} in "
                        f"{self.results_path}")
                yield self._recorded[key]


# ---------------------------------------------------------------------------
# AgentSDKExecutor (design SS5 / SS5.1): the headless default transport.
# ---------------------------------------------------------------------------

_SDK_ENV_PREFIXES = ("ANTHROPIC", "CLAUDE")

# Markers of a stale/absent CLI OAuth credential (SS5.1: the desktop app
# refreshes its own auth, not the CLI's -- a headless 401 means the user
# must run `claude login`). Checked case-insensitively.
_AUTH_MARKERS = ("401", "authentication", "oauth", "api key",
                 "logged out", "log in", "login")

_AUTH_HELP = ("Claude CLI credentials are stale or missing (401). "
              "Run `claude login` in a terminal, then rerun this verb. "
              "No further jobs were attempted.")


class AgentSDKAuthError(RuntimeError):
    """Headless auth failure -- stop immediately, don't burn N jobs."""


@contextmanager
def _stripped_parent_env():
    """Remove ANTHROPIC*/CLAUDE* env around the SDK import + call.

    Inside a Claude Code session the parent's ANTHROPIC_BASE_URL / CLAUDE*
    leak into the spawned CLI and break auth (design SS5.1). The SDK's
    options.env only MERGES over inherited os.environ (it cannot remove
    keys), so the strip must happen here. Restored on exit."""
    saved = {k: os.environ.pop(k) for k in list(os.environ)
             if k.startswith(_SDK_ENV_PREFIXES)}
    try:
        yield
    finally:
        os.environ.update(saved)


def _looks_like_auth_failure(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _AUTH_MARKERS)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """PoC parse rule: the JSON object between the first '{' and the last
    '}' in the result text. None when absent or invalid."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class AgentSDKExecutor:
    """Headless default (design SS5): one claude-agent-sdk query() per job.

    allowed_tools=["Read"] only; model from config. Drains the SDK's async
    generator fully (partial consumption segfaults at shutdown on Windows,
    SS5.1). Auth failures raise AgentSDKAuthError immediately; other
    per-job failures are recorded in .failures (job_id, reason) and the
    run continues -- unfinished claims stay pending for a rerun.

    Not usable inside a running event loop (it calls anyio.run per job);
    in-session runs use AgentToolExecutor (jobs mode) instead.
    """

    def __init__(self, model: str = "opus", cwd: str | Path | None = None,
                 max_turns: int = 6, query_fn: Any = None):
        self.model = model
        self.cwd = str(cwd) if cwd is not None else None
        self.max_turns = max_turns
        self._query_fn = query_fn  # test seam; None = claude_agent_sdk.query
        self.failures: list[tuple[str, str]] = []

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        for job in jobs:
            yield from self._run_job(job)

    def _run_job(self, job: Job) -> list[Verdict]:
        import anyio

        with _stripped_parent_env():
            # Import inside the stripped env (the PoC strips before import;
            # the SDK may spawn/locate the CLI on first use).
            from claude_agent_sdk import (ClaudeAgentOptions,
                                          ClaudeSDKError, CLINotFoundError)
            query_fn = self._query_fn
            if query_fn is None:
                from claude_agent_sdk import query as query_fn
            options = ClaudeAgentOptions(
                allowed_tools=["Read"], max_turns=self.max_turns,
                model=self.model,
                **({"cwd": self.cwd} if self.cwd else {}))
            try:
                result_msg = anyio.run(self._drain, query_fn, job.prompt,
                                       options)
            except CLINotFoundError:
                raise  # fatal: no claude CLI on this machine
            except ClaudeSDKError as e:
                if _looks_like_auth_failure(str(e)):
                    raise AgentSDKAuthError(_AUTH_HELP) from e
                self.failures.append(
                    (job.job_id, f"{type(e).__name__}: {e}"))
                return []

        if result_msg is None:
            self.failures.append((job.job_id, "no ResultMessage from SDK"))
            return []
        text = getattr(result_msg, "result", "") or ""
        if getattr(result_msg, "is_error", False):
            if _looks_like_auth_failure(text):
                raise AgentSDKAuthError(_AUTH_HELP)
            self.failures.append((job.job_id, f"is_error: {text[:200]}"))
            return []
        fields = _parse_json_object(text)
        if fields is None:
            self.failures.append(
                (job.job_id, f"unparseable result: {text[:200]}"))
            return []
        elapsed_s = (getattr(result_msg, "duration_ms", 0) or 0) / 1000.0
        cost_usd = getattr(result_msg, "total_cost_usd", 0.0) or 0.0

        # Packed-job contract (assess-v2+): a per-claim verdicts array.
        # Entries for unknown claim_ids are recorded and dropped; claims
        # the model skipped stay pending (resume re-runs them). Cost is
        # attributed to the first emitted claim only, so summing
        # cost_usd over a cassette stays truthful.
        if isinstance(fields.get("verdicts"), list):
            out: list[Verdict] = []
            known = set(job.claim_ids)
            for entry in fields["verdicts"]:
                if not isinstance(entry, dict):
                    continue
                cid = entry.get("claim_id", "")
                if cid not in known:
                    self.failures.append(
                        (job.job_id,
                         f"verdict for unknown claim_id {cid!r} dropped"))
                    continue
                vfields = {k: v for k, v in entry.items()
                           if k != "claim_id"}
                out.append(Verdict(
                    claim_id=cid, fields=vfields, model=self.model,
                    prompt_version=job.prompt_version,
                    elapsed_s=elapsed_s if not out else 0.0,
                    cost_usd=cost_usd if not out else 0.0))
            return out

        return [Verdict(claim_id=cid, fields=fields, model=self.model,
                        prompt_version=job.prompt_version,
                        elapsed_s=elapsed_s, cost_usd=cost_usd)
                for cid in job.claim_ids]

    @staticmethod
    async def _drain(query_fn: Any, prompt: str, options: Any) -> Any:
        """Consume the generator to exhaustion; keep the last ResultMessage.
        Never break/return from inside the async-for (SS5.1 segfault)."""
        result = None
        async for msg in query_fn(prompt=prompt, options=options):
            # Name-suffix duck typing: matches the SDK's ResultMessage
            # without importing message classes (and test doubles).
            if type(msg).__name__.endswith("ResultMessage"):
                result = msg
        return result
