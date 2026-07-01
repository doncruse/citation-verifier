# MessagesAPIExecutor + A/B harness robustness — implementation plan

**Date:** 2026-07-01. **Parent:** `docs/plans/2026-07-01-pipeline-cost-audit.md`
(findings F1 + the Priority-1 harness fix), executing `scratch/TODO.md`
Priority-0 items 1–2.

**Billing context (why now, why not default):** the Agent SDK is currently
subscription-covered, so the SDK transport stays the metered-headless
default for the time being. This work builds and validates the direct-API
transport so the default can flip the day SDK usage starts drawing on
subscription credits. Validation arms that can run via SDK for free
(fresh opus-v2 SDK baseline, pinned-model sonnet arm) should be run while
that's still true; only the `opus-v2-api` arm itself must be metered
(~$2–4 est.).

## Part 1 — A/B harness: don't die on a missing verdict

Bug (TODO Priority-1): a transient assess-job failure leaves a claim with
no verdict; `score_workdir`'s default `RecordedExecutor` raises
`RecordedVerdictMiss` on the first gap, killing the whole multi-corpus run
(this lost payne/wainwright in the 2026-06-13 sonnet-v2 arm).

Changes:

- `RecordedExecutor(results_path, missing="raise")` gains
  `missing="skip"`: a missing `(claim_id, prompt_version)` is appended to
  `.misses` and the generator continues instead of raising. Default stays
  `"raise"` — the regression tests and `--replay` keep strict cassette
  policy.
- `tools/ab_test_runner.py::run_ab_config` (live branch): score through a
  skip-mode `RecordedExecutor` over the run copy's results file, then
  print the dropped-claim count (no silent truncation). Replay branch
  unchanged (strict).

## Part 2 — `MessagesAPIExecutor` (executor.py)

Same `LLMExecutor.run(jobs) -> Iterable[Verdict]` contract as the other
adapters. Key design decisions:

1. **Prompt adaptation, not prompt editing.** The versioned templates are
   written for a Read-tool agent ("Read the opinion file at: …", "Use ONLY
   the Read tool"). The byte-pinned templates are NOT edited (cassette
   policy). The executor wraps at the transport layer: message content =
   inlined file block(s) first, then a short bridging note ("the file(s)
   are provided inline above; you have no tools"), then `job.prompt`
   verbatim. `job.files` entries resolve against the executor's `cwd`
   (assess/prescreen files are workdir-relative; extract's is absolute).
   `.pdf` files become base64 `document` content blocks (extract verb);
   everything else is inlined text.
2. **Two modes.** Default: concurrent `messages.stream(...)` calls via a
   thread pool (`max_concurrency=8`; streaming so long extract outputs
   don't hit HTTP timeouts; `max_tokens=32000`). `batch=True`: one
   `messages.batches.create` (custom_id = `job_id`), poll until `ended`,
   map results by custom_id — 50% off, for the non-latency-sensitive
   `full` chain.
3. **Model aliases pinned at the executor.** `opus` → `claude-opus-4-8`,
   `sonnet` → `claude-sonnet-5`, `haiku` → `claude-haiku-4-5`; explicit
   IDs pass through. `Verdict.model` records the resolved ID (audit F2:
   alias drift silently changes what an A/B measures). Adaptive thinking
   is sent for Opus/Sonnet-tier models, omitted for Haiku.
4. **Shared fan-out.** The packed-job `verdicts`-array fan-out (one
   `Verdict` per claim, unknown claim_ids recorded+dropped, skipped claims
   stay pending, cost attributed to the first claim) is extracted from
   `AgentSDKExecutor._run_job` into a module-level helper used by both
   executors — one contract, not two copies.
5. **JSON parsing tightened** (TODO Priority-2 deferral): try
   `json.loads` on the stripped text, then a fenced ```json block, then
   the existing first-`{`/last-`}` slice. Same function, shared by both
   executors; existing behavior is a fallback so current tests hold.
6. **Errors.** `anthropic.AuthenticationError` → `MessagesAPIAuthError`
   (subclass of new `ExecutorAuthError` base, which `AgentSDKAuthError`
   also joins; the CLI catches the base). Other per-job failures →
   `.failures`, run continues, resume key re-runs them. Batch results
   `errored`/`expired`/`canceled` → `.failures`.
7. **Cost accounting.** `Verdict.cost_usd` computed from `response.usage`
   with a small pricing table (Opus 4.8 $5/$25, Sonnet 5 $3/$15, Haiku
   4.5 $1/$5 per MTok; cache reads 0.1×, cache writes 1.25×; batch ×0.5)
   so cassette cost sums stay truthful across transports.
8. **Auth/env.** `anthropic.Anthropic()` default resolution, after
   loading the project `.env` (needs `ANTHROPIC_API_KEY` added there —
   user action; only `COURTLISTENER_API_TOKEN` is present today). The
   client is injectable (`client=`) so all tests run offline with fakes.

## Part 3 — wiring

- CLI (`__main__.py` verify-propositions): `--executor` gains `api`;
  new `--batch` flag (api mode only). `--model` keeps default `opus`
  (alias-resolved per decision 3).
- `tools/ab_test_runner.py::make_executor`: config `"executor": "api"`
  supported alongside `sdk`.
- `tests/ab_test_configs.json`: add `opus-v2-api` and `sonnet-v1-api`
  arms with pinned model IDs.
- Docs: CLAUDE.md executor row + CHANGELOG (additive, minor).

## Validation sequence (from the audit checklist)

1. Offline suite green (`test_executor`, `test_ab_runner`, `test_scoring`,
   `test_proposition_pipeline`, `test_assessment_regression`).
2. Free (while SDK is subscription-covered): fresh same-day
   `opus-v2` SDK baseline over the 3 corpora; pinned `sonnet-v1` arm.
3. Metered (~$2–4): `ab_test_runner.py --config opus-v2-api --corpus
   withers payne wainwright`; require withers ≥16/19 yellows, ≤4 green
   over-flags, 3/3 reds; A/B ≥55/61 vs the same-day SDK baseline.
4. Only after 3 passes: consider flipping the CLI default when SDK
   billing changes. Until then SDK/jobs-mode remain the defaults.
