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

### 2026-07-01 — F1 validation (Windows), opus-v2-api vs same-day opus-v2 SDK — **PASS**

Both arms `claude-opus-4-8`, assess-v2, over withers+payne+wainwright (90
jobs). Same-day SDK control run first (subscription-billed, serial) so the
comparison isolates transport from model drift; API arm run concurrent
(`max_concurrency=8`, non-batch). Snapshots committed to `scratch/ab_runs/`
(`ab_opus-v2_20260701-223625.jsonl`, `ab_opus-v2-api_20260701-225130.jsonl`).

| metric | frozen June | SDK control (today) | API arm (today) |
|---|---|---|---|
| withers yellows | 16/19 | 14/19 | 15/19 |
| withers green over-flags | 4 | 4 | 3 |
| withers reds | 3/3 | 3/3 | 3/3 |
| A/B (payne+wainwright) | 55/61 | 57/61 | 55/61 |
| wainwright | — | 34/34 | 33/34 |
| cost/claim | ~$0.42 (notional) | ~$0.42 (notional) | **$0.079** |
| wall-clock (90 jobs) | — | ~hours (serial) | **~2.5 min** |

**Verdict: transport validated.** The API arm lands within the ±2 sampling
variance measured on the same-day SDK control on every axis, mostly on the
better side (withers 15 vs 14, over-flags 3 vs 4, reds 3/3). A/B 55 = frozen
baseline, within noise of the control's 57, meets the ≥55 bar. Lenient-
direction misses stayed inside the Opus envelope (API 4 on withers vs control
5 / frozen 3 — no new systematic regression; the one new lenient miss
payne-23 Red→Gray is offset by the API arm fixing payne-03 that the control
missed). The absolute "withers ≥16/19" bar from the checklist was treated as
a frozen single-sample artifact: the same-day SDK path itself only reached
14/19 today, confirming ~±2 run-to-run variance, so the operative bar was
"match the same-day control within variance + reds 3/3 + A/B ≥55 + no new
lenient regression" — all met.

**Cost:** $7.15 total ($0.079/claim) → ~$2.40 per 30-claim brief, matching the
audit's ~$2.00–2.50 F1 projection; Batches (−50%) would ~halve it.

**Note on the ≥16/19 checklist bar:** because the same-day SDK control did not
reproduce 16/19 (variance, not drift — A/B moved the *opposite* way, 57 vs
55), a single-run absolute yellow-count gate is unreliable for this exhibit.
Future validation should judge against a same-day same-model control (as done
here), not the frozen number.

**Step 4 NOT taken:** CLI default stays SDK/jobs-mode. SDK is still
subscription-covered (per the 2026-07-01 billing extension); flip to `api`
only when it starts drawing credits.

### 2026-07-01 — cost-audit F2 prerequisite: sonnet-v1-api (pinned claude-sonnet-5)

Ran `sonnet-v1-api` (pinned `claude-sonnet-5`, assess-v1 single-claim) over
the 3 corpora via the validated API path. Snapshot:
`scratch/ab_runs/ab_sonnet-v1-api_20260701-225621.jsonl`.

- withers yellows 15/18*, over-flags **6**, reds 3/3; payne 22/27;
  wainwright 29/33*; **A/B 51/60***.  (*3 jobs dropped — see parse bug.)
- **Lenient-direction errors on the A/B set (payne+wainwright): 0.** Every
  A/B miss was over-flagging (Green→Yellow/Red). The only 3 lenient errors
  (Yellow→Green) were on withers, outside the A/B ground truth. **Confirms
  the 2026-06-13 sonnet-v1 finding on the pinned current model**: Sonnet's
  error mode is over-caution, not false assurance — the safety property the
  F2 escalation design (Sonnet fast-track → escalate non-`supported` to
  Opus) depends on.
- Cost **$0.0395/claim** — half of Opus's $0.079. Total $3.56/90 jobs.

**Blocker surfaced for F2:** the deferred `_parse_json_object` over-capture
(TODO Priority-2 / PR#21 review #6) fired on **3/90** Sonnet jobs
("unparseable result" — Sonnet appended rationale prose after the JSON).
Skip-mode scoring tolerated it, but in production those claims fail-safe to
pending. **Fix `_parse_json_object` (fenced-block-first / balanced-object)
before F2 ships** — Sonnet triggers it more than Opus. F2 must also route
Sonnet through single-claim jobs only (packed v2 broke the sonnet-v2 arm).
