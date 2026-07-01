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

1. ✅ 2026-07-01 — offline suite green (860 passed: `test_executor`,
   `test_messages_api_executor` (new), `test_ab_runner`, `test_scoring`,
   `test_proposition_pipeline`, `test_assessment_regression`, rest).
   Implementation committed as b19fbc2.
2. Free (while SDK is subscription-covered): fresh same-day
   `opus-v2` SDK baseline over the 3 corpora; pinned `sonnet-v1` arm.
3. Metered (~$2–4): `ab_test_runner.py --config opus-v2-api --corpus
   withers payne wainwright`; require withers ≥16/19 yellows, ≤4 green
   over-flags, 3/3 reds; A/B ≥55/61 vs the same-day SDK baseline.
4. Only after 3 passes: consider flipping the CLI default when SDK
   billing changes. Until then SDK/jobs-mode remain the defaults.

## Runbook for the validation session (steps 2–3; delegable, no design
## judgment required — a fresh Opus session executing this verbatim is fine)

Prereqs (all confirmed 2026-07-01 on the Mac): `.env` has a **valid**
`ANTHROPIC_API_KEY` and `COURTLISTENER_API_TOKEN`; `claude-agent-sdk`,
`fastapi`, `openai` installed in the venv. SDK runs additionally need
`claude login` credentials on the machine. Windows: use
`venv/Scripts/python.exe` instead of `venv/bin/python`.

```bash
# 1. FREE same-day SDK controls (run both while SDK is subscription-
#    covered; ~15-20 min each, jobs run serially):
venv/bin/python tools/ab_test_runner.py --config opus-v2 --corpus withers payne wainwright
venv/bin/python tools/ab_test_runner.py --config sonnet-v1 --corpus withers payne wainwright

# 2. METERED validation arm (~$2-4, concurrent so a few minutes):
venv/bin/python tools/ab_test_runner.py --config opus-v2-api --corpus withers payne wainwright

# 3. Compare the printed per-corpus scores, and optionally:
venv/bin/python tools/ab_test_runner.py --compare tests/data/results/ab_opus-v2_<TS>.jsonl tests/data/results/ab_opus-v2-api_<TS>.jsonl
```

Interpretation:
- Each run prints per-corpus scores and saves rows to
  `tests/data/results/ab_<config>_<timestamp>.jsonl` (**gitignored** —
  copy anything worth keeping to `scratch/ab_runs/` and commit).
- If a run prints `WARNING ... dropped from scoring`, those are transient
  job failures: rerun the SAME config over a fresh run (or rerun assess on
  the run copy — resume-keyed) rather than accepting a partial score.
- PASS bar for `opus-v2-api` (vs the SAME-DAY `opus-v2` SDK control, so
  model drift is excluded): withers ≥16/19 yellows caught, ≤4 green
  over-flags, 3/3 reds; payne+wainwright internal ≥55/61 combined. Also
  eyeball total cost (sum `cost_usd` in the run copy's
  `jobs/assess_results.jsonl`) — expect roughly $0.05–0.10/claim vs the
  SDK's measured ~$0.42.
- `sonnet-v1` (pinned-alias control) feeds cost-audit F2 later: record
  its scores + lenient-error count next to the 2026-06-13 numbers in the
  kettering retro table.
- Record outcomes: append results to this file (below), update
  `scratch/TODO.md` Priority-0, and commit + push. Do NOT flip any CLI
  default in that session — that's a separate decision after review.

## Results (append per run)

_(none yet)_
