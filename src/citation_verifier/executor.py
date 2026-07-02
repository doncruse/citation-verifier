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
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol

from json_repair import repair_json


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

    missing="raise" (default) enforces the strict cassette policy (the
    regression tests and --replay). missing="skip" records the gap in
    .misses and keeps yielding -- for scoring a live run where transient
    job failures left some claims without verdicts (the 2026-06-13
    sonnet-v2 A/B lost two corpora to a mid-generator raise here); the
    caller reports the drop count, no silent truncation.
    """

    def __init__(self, results_path: str | Path, missing: str = "raise"):
        if missing not in ("raise", "skip"):
            raise ValueError(f"missing must be 'raise' or 'skip', "
                             f"got {missing!r}")
        self.results_path = Path(results_path)
        self.missing = missing
        self._recorded: dict[tuple[str, str], Verdict] = {}
        if self.results_path.exists() or missing == "raise":
            for v in load_verdicts_jsonl(self.results_path):
                self._recorded[(v.claim_id, v.prompt_version)] = v
        self.misses: list[tuple[str, str]] = []

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        for job in jobs:
            for claim_id in job.claim_ids:
                key = (claim_id, job.prompt_version)
                if key not in self._recorded:
                    self.misses.append(key)
                    if self.missing == "skip":
                        continue
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


class ExecutorAuthError(RuntimeError):
    """Auth failure on a metered transport -- stop immediately, don't
    burn N jobs. Base class so the CLI can catch every transport's
    variant with one handler."""


class AgentSDKAuthError(ExecutorAuthError):
    """Headless auth failure -- stop immediately, don't burn N jobs."""


class MessagesAPIAuthError(ExecutorAuthError):
    """Anthropic API auth failure (missing/invalid ANTHROPIC_API_KEY)."""


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


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Extract the verdict JSON object from a model's result text.

    Tries, in order: the whole (stripped) text as JSON; the first fenced
    ```json block; the span between the first '{' and the last '}'; and
    finally json_repair, which recovers the almost-valid JSON models
    intermittently emit -- unescaped inner double-quotes in a string
    value, or a missing closing brace (both observed from claude-sonnet-5
    on 2026-07-01; see tests/test_parse_json_object.py). The strict
    json.loads candidates run first so well-formed output is untouched;
    json_repair is the last resort. None when nothing yields a dict."""
    candidates = [text.strip()]
    m = _FENCED_JSON_RE.search(text)
    if m:
        candidates.append(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    # Last resort: repair malformed-but-nearly-valid JSON. json_repair
    # returns "" for non-JSON prose, so a dict result means real recovery.
    try:
        repaired = repair_json(text, return_objects=True)
    except Exception:
        return None
    if isinstance(repaired, dict) and repaired:
        return repaired
    return None


def _fan_out_verdicts(job: Job, fields: dict[str, Any], model: str,
                      elapsed_s: float, cost_usd: float,
                      failures: list[tuple[str, str]]) -> list["Verdict"]:
    """Shared Job-result -> Verdict(s) contract for live transports.

    Packed jobs (assess-v2+) return a per-claim `verdicts` array: one
    Verdict per entry, entries for unknown claim_ids recorded in
    `failures` and dropped, claims the model skipped stay pending (the
    resume key re-runs them). Cost/elapsed are attributed to the first
    emitted claim only, so summing cost_usd over a cassette stays
    truthful. Single-object results fan out identically to every
    claim_id (the v1 shape)."""
    if isinstance(fields.get("verdicts"), list):
        out: list[Verdict] = []
        known = set(job.claim_ids)
        for entry in fields["verdicts"]:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("claim_id", "")
            if cid not in known:
                failures.append(
                    (job.job_id,
                     f"verdict for unknown claim_id {cid!r} dropped"))
                continue
            vfields = {k: v for k, v in entry.items() if k != "claim_id"}
            out.append(Verdict(
                claim_id=cid, fields=vfields, model=model,
                prompt_version=job.prompt_version,
                elapsed_s=elapsed_s if not out else 0.0,
                cost_usd=cost_usd if not out else 0.0))
        return out
    return [Verdict(claim_id=cid, fields=fields, model=model,
                    prompt_version=job.prompt_version,
                    elapsed_s=elapsed_s, cost_usd=cost_usd)
            for cid in job.claim_ids]


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
                                          CLINotFoundError)
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
            except AgentSDKAuthError:
                raise
            except Exception as e:
                # Not just ClaudeSDKError: the SDK's message stream can
                # raise plain Exceptions on transient API blips ("Claude
                # Code returned an error result: ..." -- seen live during
                # the Step 8 re-record). One flaky job must not kill the
                # batch; the resume key re-runs it on the next invocation.
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

        # Packed-job contract (assess-v2+): shared with MessagesAPIExecutor.
        return _fan_out_verdicts(job, fields, self.model, elapsed_s,
                                 cost_usd, self.failures)

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


# ---------------------------------------------------------------------------
# MessagesAPIExecutor (design SS5 / cost-audit F1): direct Messages API.
# ---------------------------------------------------------------------------

_MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}

# $/MTok (input, output). Cache reads bill ~0.1x input, writes ~1.25x.
# Unknown models cost 0.0 (recorded, not guessed).
_PRICING_PER_MTOK = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Transport bridge: the versioned templates are written for a Read-tool
# agent ("Read the opinion file at: ..."). The templates are byte-pinned
# (cassette policy) so the adaptation happens here, around the untouched
# job.prompt.
_INLINE_NOTE = (
    "The file(s) referenced by the instructions below are provided "
    "inline above. You have no tools in this environment -- do not "
    "attempt any tool call; treat the inline content as the file's "
    "contents and follow the instructions.")

_API_AUTH_HELP = (
    "Anthropic API authentication failed. Add ANTHROPIC_API_KEY to the "
    "project .env (or environment), then rerun this verb. No further "
    "jobs were attempted.")


class MessagesAPIExecutor:
    """Direct Anthropic Messages API transport (the metered-cheap path).

    One single-shot completion per job: job.files are inlined into the
    user message (PDFs as base64 document blocks, everything else as
    text), followed by the job's rendered prompt verbatim. No agent
    harness, no Read loop.

    Two modes: default runs jobs concurrently via streaming
    `messages.stream` calls on a thread pool (streaming so long extract
    outputs don't hit HTTP timeouts); `batch=True` submits one Message
    Batch (50% off) and polls until it ends -- for the non-latency-
    sensitive `full` chain.

    Auth failures raise MessagesAPIAuthError immediately; other per-job
    failures are recorded in .failures and the run continues (the
    resume key re-runs them). Model aliases are pinned here so
    Verdict.model always records an explicit model ID.
    """

    def __init__(self, model: str = "opus", cwd: str | Path | None = None,
                 batch: bool = False, max_concurrency: int = 8,
                 max_tokens: int = 32000, poll_interval_s: float = 20.0,
                 client: Any = None):
        self.model = _MODEL_ALIASES.get(model, model)
        self.cwd = Path(cwd) if cwd is not None else None
        self.batch = batch
        self.max_concurrency = max_concurrency
        self.max_tokens = max_tokens
        self.poll_interval_s = poll_interval_s
        self._client = client  # test seam; None = anthropic.Anthropic()
        self.failures: list[tuple[str, str]] = []

    # -- client / request construction ------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            from dotenv import load_dotenv
            load_dotenv(
                Path(__file__).resolve().parent.parent.parent / ".env")
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _resolve_file(self, f: str) -> Path:
        p = Path(f)
        if not p.is_absolute() and self.cwd is not None:
            p = self.cwd / p
        return p

    def _build_content(self, job: Job) -> list[dict[str, Any]]:
        import base64

        blocks: list[dict[str, Any]] = []
        for f in job.files:
            p = self._resolve_file(f)
            if p.suffix.lower() == ".pdf":
                data = base64.standard_b64encode(
                    p.read_bytes()).decode("ascii")
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64",
                               "media_type": "application/pdf",
                               "data": data},
                })
            else:
                blocks.append({
                    "type": "text",
                    "text": (f'<file path="{f}">\n'
                             f'{p.read_text(encoding="utf-8")}\n</file>'),
                })
        blocks.append(
            {"type": "text", "text": f"{_INLINE_NOTE}\n\n{job.prompt}"})
        return blocks

    def _request_params(self, job: Job) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "user", "content": self._build_content(job)}],
        }
        # Adaptive thinking for Opus/Sonnet tiers (matches the agentic
        # transports the accuracy baselines were recorded on). Haiku 4.5
        # doesn't support adaptive -- omit.
        if not self.model.startswith("claude-haiku"):
            params["thinking"] = {"type": "adaptive"}
        return params

    # -- accounting / parsing ----------------------------------------------

    def _cost_usd(self, usage: Any) -> float:
        rates = _PRICING_PER_MTOK.get(self.model)
        if not rates or usage is None:
            return 0.0
        in_rate, out_rate = rates

        def _u(field: str) -> int:
            return getattr(usage, field, 0) or 0

        cost = (_u("input_tokens") * in_rate
                + _u("cache_creation_input_tokens") * in_rate * 1.25
                + _u("cache_read_input_tokens") * in_rate * 0.1
                + _u("output_tokens") * out_rate) / 1_000_000
        return cost * (0.5 if self.batch else 1.0)

    def _verdicts_from_message(self, job: Job, message: Any,
                               elapsed_s: float) -> list[Verdict]:
        text = "".join(
            getattr(b, "text", "") for b in (message.content or [])
            if getattr(b, "type", "") == "text")
        fields = _parse_json_object(text)
        if fields is None:
            stop = getattr(message, "stop_reason", "")
            self.failures.append(
                (job.job_id,
                 f"unparseable result (stop_reason={stop}): {text[:200]}"))
            return []
        return _fan_out_verdicts(job, fields, self.model, elapsed_s,
                                 self._cost_usd(getattr(message, "usage",
                                                        None)),
                                 self.failures)

    @staticmethod
    def _is_auth_error(e: Exception) -> bool:
        return type(e).__name__ == "AuthenticationError"

    # -- run ---------------------------------------------------------------

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        if not jobs:
            return iter(())
        if self.batch:
            return self._run_batch(jobs)
        return self._run_concurrent(jobs)

    def _call_one(self, client: Any, job: Job) -> tuple[Any, float]:
        import time

        t0 = time.monotonic()
        with client.messages.stream(**self._request_params(job)) as stream:
            message = stream.get_final_message()
        return message, time.monotonic() - t0

    def _run_concurrent(self, jobs: list[Job]) -> Iterator[Verdict]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        client = self._get_client()
        workers = max(1, min(self.max_concurrency, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._call_one, client, job): job
                       for job in jobs}
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    message, elapsed_s = fut.result()
                except Exception as e:
                    if self._is_auth_error(e):
                        raise MessagesAPIAuthError(_API_AUTH_HELP) from e
                    self.failures.append(
                        (job.job_id, f"{type(e).__name__}: {e}"))
                    continue
                yield from self._verdicts_from_message(job, message,
                                                       elapsed_s)

    def _run_batch(self, jobs: list[Job]) -> Iterator[Verdict]:
        import time

        client = self._get_client()
        requests = [{"custom_id": job.job_id,
                     "params": self._request_params(job)}
                    for job in jobs]
        try:
            batch = client.messages.batches.create(requests=requests)
            while getattr(batch, "processing_status", "") != "ended":
                time.sleep(self.poll_interval_s)
                batch = client.messages.batches.retrieve(batch.id)
            results = client.messages.batches.results(batch.id)
        except Exception as e:
            if self._is_auth_error(e):
                raise MessagesAPIAuthError(_API_AUTH_HELP) from e
            raise
        by_id = {job.job_id: job for job in jobs}
        for result in results:
            job = by_id.get(result.custom_id)
            if job is None:
                continue
            if result.result.type != "succeeded":
                self.failures.append(
                    (result.custom_id,
                     f"batch result: {result.result.type}"))
                continue
            yield from self._verdicts_from_message(
                job, result.result.message, elapsed_s=0.0)
