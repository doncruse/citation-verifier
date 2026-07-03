# MCP Server Design — Typed Tool Surface for the Proposition Pipeline

**Date:** 2026-07-02
**Status:** Draft for review
**Driver:** [Issue #29](https://github.com/rlfordon/citation-verifier/issues/29) — expose the verify-propositions verbs as typed MCP tools so the Cabinet memo-import lane can drop its `Bash(python:*)` interpreter grant.
**Prior art in this repo:** refactor design v2 §Phase 5 (MCP roadmap sketch, 2026-05-20); `scratch/ROADMAP.md` Tier 4 (candidates schema parked "until grounded callers — MCP server"); `scratch/drafts/foresight-88-consumer-api-access.md` (hosted/consumer MCP — explicitly *not* this design).

---

## 1. Problem

The memo-import pipeline (us-legal-research `import-memo` skill, running inside Cabinet) drives this engine headlessly through a shell. Narrow Bash allowlists proved cosmetic — denied command forms were improvised around via `python -c`. The lane's defining threat is prompt injection from the imported document (untrusted memos are the use case), and an interpreter grant cannot be pattern-restricted.

The durable boundary: named verbs with fixed, typed signatures. That is exactly what MCP tools are.

## 2. Approaches considered

**A. In-repo FastMCP stdio server wrapping the pipeline verbs (recommended, chosen).**
A single module, `src/citation_verifier/mcp_server.py`, exposing each `run_*` verb as a tool plus a document-intake tool and jobs-mode plumbing. Same repo, same venv, same editable install.

**B. Minimal server: only `full` + intake.**
Fewer tools, but the import-memo orchestrator needs per-verb control (the chain pends twice — at extract and at assess — and resumes by re-running individual verbs). `full` alone doesn't remove that need; it just hides the verbs the skill still has to call. Rejected.

**C. Separate repo (also answers "should the MCP be a new repo?").**
Rejected for v1. The server is a thin adapter over in-repo internals (`run_*` verbs, the executor protocol, the stats dataclasses) that have no stable public API outside this repo. A second repo means pinning citation-verifier versions, a second release process, and drift between the tool schemas and the pipeline schema (`schema_version` in run.json) — all cost, no benefit for a **local stdio server**. The future *hosted* verifier MCP (Phase 5's `verify_citation` for general clients, the foresight-#88 OAuth/rate-limit concerns) is a different product with different auth and transport needs; if that ever ships, it can be split out then. This design deliberately does not foreclose it (§9).

## 3. Shape

- **Framework:** FastMCP from the official `mcp` Python SDK. Python, same venv (per the issue's design notes and the mcp-builder discipline).
- **Transport:** stdio. Registered in the consuming session's MCP config; launched as `venv/Scripts/python.exe -m citation_verifier.mcp_server --root <dir> [--root <dir> ...]`.
- **Packaging:** new optional-dependency group `mcp = ["mcp>=1.2", "pdfplumber>=0.11", "python-docx>=1.1"]` and a console script `citation-verifier-mcp`. (pdfplumber is already the repo's PDF library — dev group; python-docx is new, for the intake tool.)
- **Discipline: the server wraps, never forks.** Every tool body is: validate paths → call the existing `run_*` verb → serialize its stats dataclass to a dict. No pipeline logic lives in the server. Outputs on disk are byte-identical to CLI runs — that is what keeps the import-memo adversarial eval (acceptance criterion 3) a pure regression gate.

## 4. Security model

- The server refuses to start without at least one `--root` directory. Every path-typed argument (workdir, document) is `Path.resolve()`d (symlinks followed) and must land inside a configured root; anything else is a structured tool error naming the offending argument. There is no default root — the boundary is explicit configuration, not convention.
- No shell, no subprocess, anywhere in the server.
- Tools never return contents of caller-named files; the intake tool *writes* into the workdir only, and job prompts returned by `get_job` come from pipeline-generated jobs files, not caller paths.
- The CourtListener token comes from the server process environment / `.env`, exactly as the CLI does today. Nothing token-shaped crosses the tool boundary.
- `CITATION_VERIFIER_CACHE_DIR` behavior is inherited from the environment; the `verify`/`full` tools also accept an explicit `cache_dir`, which is root-checked like any other path.

## 5. Tool inventory

One tool per CLI verb, plus intake, jobs plumbing, and a status probe. All tools return structured JSON (the verb's stats dataclass fields, plus `ok` and any pending info). Names use underscores (MCP convention); each maps to the identically-behaved pipeline function.

| Tool | Signature (beyond `workdir`) | Wraps | Returns |
|---|---|---|---|
| `intake_document` | `document` | *(new, ~60 lines)* | Extracts text from PDF (pdfplumber) / DOCX (python-docx) / TXT (copy) into `<workdir>/document.txt`; returns path, char count, page count |
| `extract` | `document`, `force=False` | `run_extract` | ExtractStats, or pending job summary (§6) |
| `verify` | `citations: list[str] \| None`, `force=False`, `cache_dir=None` | `run_verify` | Wave stats (misses, downloads); MCP progress notifications while running (§7) |
| `merge` | — | `run_merge` | matched/unmatched counts + unmatched claim details |
| `check_quotes` | — | `run_check_quotes` | claims checked |
| `crosscheck` | — | `run_crosscheck` | TOA/court/pincite flag counts |
| `triage` | — | `run_triage` | full/fast/deterministic counts |
| `assess` | `prompt_version="assess-v2"` | `run_assess` | AssessStats, or pending job summaries (§6) |
| `apply_assessments` | `prompt_version="assess-v2"` | `run_apply_assessments` | applied/invalid/missing + invalid claim_ids |
| `report` | — | `run_report` | ReportStats + paths to `report.html` / `findings.json` |
| `full` | `document=None`, `force=False`, `prompt_version`, `cache_dir=None` | the CLI `full` chain | Chain results; stops and returns pending at extract/assess exactly like the CLI |
| `get_job` | `phase` (`extract`\|`assess`), `job_id` | jobs file reader | One job's full `prompt`, `files`, `prompt_version` for subagent dispatch |
| `submit_job_result` | `phase`, `result` (envelope object) | `append_verdict_jsonl` | Validates the `{claim_id, prompt_version, model, fields}` envelope shape and appends to `jobs/<phase>_results.jsonl` |
| `status` | — | run.json + file probes | Which outputs exist (claims.csv, verification_results.csv, report.html), run.json stamps, pending job counts |

Notes:

- `citations` is a list parameter, not a file path — one less path to validate, and the CLI's `--citations-file` remains for humans.
- The `verify` tool's default (no `citations`) derives citations from claims.csv / the extract lists, same as the CLI.
- `prompt_version` defaults to assess-v2 (the CLI's user-facing default), not the library constant.

## 6. The pending-jobs protocol (extract / assess)

The v1 executor is **jobs mode only** — the same in-session default the CLI uses. When `extract`/`assess`/`full` pend, the tool response carries, per job: `job_id`, `claim_ids`, and `files` — *not* the full prompt (packed assess-v2 prompts are large; inlining all of them would blow up one tool result). The orchestrating skill then, per job:

1. `get_job(workdir, phase, job_id)` → full prompt + file list.
2. Dispatches a subagent with that prompt verbatim (the subagent Reads the listed files — no shell involved).
3. Submits the subagent's envelope via `submit_job_result` — either the subagent calls it directly (subagents inherit session MCP tools), or the orchestrator relays the subagent's returned envelope. Both work; `submit_job_result` also serializes concurrent appends, which raw file appends never did.
4. Re-runs the verb tool to ingest (idempotent resume, unchanged pipeline semantics).

This closes the last shell/write dependency: today's flow has subagents appending JSONL lines to the workdir themselves; with `submit_job_result`, the import lane needs neither Bash nor Write grants over the workdir. (`apply-assessments` still owns claims.csv; nothing here changes that.)

Headless executors (`--executor sdk|api`) are **deferred**: `AgentSDKExecutor` cannot run inside a running event loop (FastMCP is asyncio), and `MessagesAPIExecutor` would need thread offload. v2 can add an `executor="api"` parameter via `anyio.to_thread` if the memo-import lane ever wants subagent-free assessment.

## 7. Long-running verbs

`verify` is the long verb (CL rate limiting at 1 rps; a memo's worth of citations plus fallbacks and downloads is minutes, not seconds). v1 keeps it synchronous:

- `run_verify` is already async — FastMCP tools are async-native, so it's awaited directly, keeping the server responsive.
- The existing `progress_callback` seam is wired to MCP progress notifications (`ctx.report_progress(done, total)`), so clients see liveness instead of a silent multi-minute call.
- If a client times out or the call is killed mid-run, the verb is idempotent and (with a cache dir) resumes cheaply — "call again to resume" is the documented v1 semantics, per the issue.

No background-task machinery in v1.

## 8. Errors

- Pipeline preconditions surface as clean tool errors carrying the verb's own message (e.g. merge's "verification_results.csv missing — run the verify verb first"), not tracebacks.
- `ExecutorAuthError` maps to a tool error with the same remediation text the CLI prints.
- Path violations report which argument escaped the roots.
- Unexpected exceptions become generic tool errors with the exception message; FastMCP handles the wrapping.

## 9. Explicitly out of scope (v1)

- **`verify_citation` / `verify_citations_batch` general-purpose tools** (the Phase 5 sketch). Deferred to v2: they need a settled JSON serialization of `VerificationResult` (a schema-versioned wire format — its own small design conversation, and where the parked Tier-4 `candidates` schema question re-enters). The server module is structured so adding them is additive.
- **Hosted/HTTP transport, OAuth, multi-tenant rate limiting** — the foresight-#88 conversation. Different product; a local stdio server with the user's own CL token doesn't touch any of it.
- **sdk/api executors over MCP** (§6).
- **The legacy verify-brief verbs** — frozen; the MCP serves the current pipeline only.

## 10. Testing

- **Path security:** traversal (`..`), absolute paths outside roots, and symlink escapes are rejected for every path-typed argument; a workdir inside a root passes.
- **Adapter correctness:** each tool calls its `run_*` verb with the right arguments and serializes the stats faithfully (monkeypatched verb stubs; no live CL).
- **Pending flow end-to-end:** over a tmp workdir with a frozen-corpus fixture — `extract` pends → `get_job` returns the prompt → `submit_job_result` appends a valid envelope (and rejects a malformed one) → rerun ingests. Same for `assess` using `RecordedExecutor` cassette envelopes.
- **Intake:** small PDF and DOCX fixtures → expected text file in the workdir.
- All offline, consistent with the existing `live_api` marker discipline. Tests exercise tool functions directly or through the SDK's in-memory client session.

## 11. Acceptance (mirrors issue #29)

1. **import-memo swaps its engine invocation to MCP tools** in a one-line-ish skill PR — the inventory covers every CLI invocation the skill makes today, plus intake and the jobs plumbing it currently improvises.
2. **Cabinet's import-lane allowlist drops the `python` grant** — collapses to `mcp__citation-verifier__*` (and, with `submit_job_result`, the workdir Write grant can go too).
3. **The Wave-3 adversarial eval is green before and after the swap** — guaranteed-by-construction as far as this repo controls it: the server wraps the same verbs, writes the same files, stamps the same run.json.

## 12. Registration example

```jsonc
// .mcp.json (or Cabinet's MCP config)
{
  "mcpServers": {
    "citation-verifier": {
      "command": "C:/Users/Rebecca Fordon/Projects/citation-verifier/venv/Scripts/python.exe",
      "args": [
        "-m", "citation_verifier.mcp_server",
        "--root", "C:/Users/Rebecca Fordon/Projects/citation-verifier/matters",
        "--root", "<cabinet inbox dir>"
      ]
    }
  }
}
```

Roots to configure are the consuming lane's choice: the matters/workdir area, plus wherever imported memos land before intake.

## 13. Open questions for review

1. **Roots for the Cabinet lane** — which directories should the import lane's server registration allow? (Design assumes: its matters dir + memo inbox.)
2. **`python-docx` as a new dependency** — OK, or should DOCX intake read the zip/XML directly to stay dependency-light? (python-docx is small and boring; recommended.)
3. **Is `full` wanted as a tool**, or should the skill always drive verbs individually? (Included here — it mirrors the CLI and reduces orchestration chatter; cutting it removes one row.)
