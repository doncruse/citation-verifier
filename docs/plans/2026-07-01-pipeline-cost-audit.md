# Pipeline cost, latency & complexity audit — 2026-07-01

**Scope:** the proposition pipeline's LLM spend and call structure
(`proposition_pipeline.py`, `executor.py`, `scoring.py`, the four prompt
templates, the extract / assess / triage / prescreen paths), plus the
deterministic-vs-LLM boundary per step. Analysis only — no pipeline changes
made in this pass.

**Method:** every accuracy number below was either (a) reproduced by
replaying the frozen cassettes offline this session
(`python -m citation_verifier.scoring tests/data/assessment_corpora/{withers,payne,wainwright}`,
both prompt versions), or (b) taken from a recorded live run whose verdicts
are in the repo (cassette `cost_usd`/`elapsed_s` fields, `run.json` stamps,
`tests/data/results/ab_*.jsonl`). Cost projections for the not-yet-built
direct-API path are estimates and are labeled as such. Anthropic pricing
used: Opus 4.8 $5/$25 per MTok, Sonnet 5 $3/$15 ($2/$10 intro through
2026-08-31), Haiku 4.5 $1/$5; Batches API −50%; cache reads ~0.1×.

Replay baselines confirmed this session (they match
`tests/data/assessment_corpora/README.md` and
`test_assessment_regression.py`):

| config | withers yellows | withers green over-flags | reds | A/B (payne+wainwright) |
|---|---|---|---|---|
| opus assess-v1 | 14/19 | 2/12 | 3/3 | 56/61 |
| opus assess-v2 (default) | 16/19 | 4/12 (adjudicated OK) | 3/3 | 55/61 |
| sonnet assess-v1 (2026-06-13 live) | 16/19 | 5/12 | 3/3 | 55/61, **0 lenient errors** |
| sonnet assess-v2 (2026-06-13 live) | 16/19 | **9/12** | 3/3 | rejected — over-flags |

---

## The measured cost/latency profile today

The assess verb is where nearly all LLM money goes. Three transports exist;
only the expensive two are wired:

| transport | status | measured cost | measured wall-clock |
|---|---|---|---|
| `AgentToolExecutor` (jobs mode → interactive Claude Code subagents, ~5 parallel per SKILL) | **the current default** — all runs since 2026-06-25 (`payne` 75 claims, `sonnet-q3-protest` 52, `ohio-mailbox`, `extrinsic-evidence`) | invisible (`cost_usd: 0` in cassettes — billed to the session/subscription) | ~13 min for 75 claims (kettering `run.json`: dispatch gap 19:15→19:28) |
| `AgentSDKExecutor` (headless `claude-agent-sdk`, one `query()` per job, **serial**) | metered since subscription billing ended ~2026-06-15 | **$11–14 per ~30-claim brief on Opus v2** (withers $14.29/29, payne $11.35/27, wainwright $12.07/34; kettering $12.75/30) ≈ **$0.42/claim**. v1 was $4–5/run ≈ $0.15/claim | 860–1,180 s (14–20 min) per ~30 claims, because jobs run one at a time (`executor.py:236-238`) |
| `MessagesAPIExecutor` (direct API, opinion inlined) | **never built** — still only a docstring mention (`executor.py:9`) despite being the Priority-0 item in `scratch/TODO.md` with a 2026-06-15 deadline | est. **$0.05–0.08/claim** Opus, half that batched (see F1) | est. 1–3 min at 10–20 concurrent, or async via Batches |

Why $0.42/claim when the actual work is "read one opinion, emit ~345 output
tokens" (measured mean on the withers v2 cassette)? Because every job is a
full Claude Code agent: system prompt + tool definitions, then the opinion
arrives through paginated `Read` tool-result turns, each turn re-reading the
growing context. The March A/B runs (which logged token usage) show the same
shape: per-claim cost $0.154 (Opus v1) with `input_tokens` mean **5** — i.e.
essentially the whole bill was cache-read/harness traffic, not the task.
The task itself is a single-shot completion: one opinion (median cleaned
text ~20–40 KB ≈ 5–10K tokens) + a ~1.4K-token template + ~350 output
tokens.

The CourtListener side (verify/download) is not a cost problem (free API)
and its latency is floor-bound by the client's global 1 req/s rate limit
(`client.py:600-611`), which is close to CL's documented quota — leave it.

---

## Ranked findings

### F1. Build `MessagesAPIExecutor` (inline opinion, parallel, Batches) — the 6–12× lever `[HIGH confidence on cost; accuracy needs one cheap re-record]`

**Change.** Implement the executor `scratch/TODO.md` Priority-0 already
specifies: `anthropic` SDK, opinion text **inlined** in the prompt (no
agentic Read loop), structured outputs for the verdict JSON, same
`LLMExecutor.run(jobs) -> verdicts` contract, `--executor api` in the CLI
(`__main__.py:567`) and in `tools/ab_test_runner.py::make_executor`. Two
modes: concurrent `messages.create` (10–20 in flight) for interactive runs,
and `messages.batches.create` for the default `full` chain — assess already
blocks until all verdicts exist, so it is the textbook Batches case (50%
off, results within an hour, keyed by `custom_id` = job_id).

**Files:** `src/citation_verifier/executor.py` (new class; also fix the
deferred `_parse_json_object` over-capture, TODO Priority-2, while here —
or make it moot with `output_config.format`), `__main__.py`,
`tools/ab_test_runner.py`.

**Impact (estimate, per ~30-claim brief on Opus v2):**

| path | per claim | per brief |
|---|---|---|
| today (SDK/agent, measured) | $0.42 | ~$13 |
| direct API, inlined (est. ~10K in + ~0.4K out per opinion-job) | ~$0.06–0.08 | ~$2.00–2.50 |
| + Batches (−50%) | ~$0.03–0.04 | ~$1.00–1.25 |

Latency: 15–20 min serial → ~1–3 min concurrent, or async-with-poll under
Batches (fine for the `full` chain, which already pends and resumes).

**Accuracy guard.** Inlining changes how the model sees the opinion (whole
text up front vs. agentic paged reads), so treat it as a transport change
that needs one validation run, not an assumed no-op: run
`tools/ab_test_runner.py --config opus-v2-api` (new config) over the three
corpora and require the pinned baselines (withers ≥16/19 yellows, ≤4 green
over-flags, 3/3 reds; A/B ≥55/61). One live arm costs an estimated $2–4
via the API path itself. The harness and ground truth already exist; this
is a one-command check once the executor lands.

**Note on long opinions:** max opinion in the corpora is ~150 KB raw
(~35–40K tokens) — inlining it is ~$0.20 on Opus, still ~2× cheaper than
today's agent path, and 1M context makes truncation a non-issue. No paging
logic needed.

### F2. Wire `triage_track` to model routing — the built-but-dead lever `[MEDIUM-HIGH; eval-backed design, needs one live arm]`

**Finding.** The triage verb (`proposition_pipeline.py:1541`,
`_triage_track_for` at `:1510`) computes `full` vs `fast` per claim and
writes it to claims.csv — and **nothing consumes it**. `run_assess`
(`:979`) sends every assessable claim to the same model regardless of
track. Grep confirms the only readers are triage itself and tests. Today
the verb is pure overhead: a whole pipeline stage whose output is a
decorative CSV column.

Real-run track mix (from `run.json` across `matters/`): fast is 44/75
(payne), 24/52 (sonnet-q3-protest), 20/32 (kettering), 19/29
(withers-v2-demo) — **~50–60% of assessable claims are fast-track**.

**Change.** In `run_assess`, route fast-track claims to Sonnet and
full-track to Opus, with an **escalation rule**: any fast-track claim
Sonnet does not call `supported` gets re-queued as an Opus job (so every
finding card is Opus-authored, and Sonnet's known weakness — green
over-flagging — costs one extra call, never a wrong report card). The only
residual risk is a false Green on a fast-track claim, and the 2026-06-13
sonnet-v1 arm measured **0/61 lenient-direction errors** (every miss was
strict). Fast-track claims are, by construction of `_triage_track_for`,
the clean-verified / no-quote / no-flag population where that holds best.

Two eval-grounded cautions:
- **Do not give Sonnet the packed multi-claim v2 prompt** — the sonnet-v2
  arm failed precisely on packed two-axis jobs (9/12 greens over-flagged).
  Route Sonnet through single-claim jobs (v1-style, or a single-claim v2
  variant). With escalation, Sonnet's thin cards don't matter: Green cards
  render no agent blocks anyway (see F3).
- The June arm ran the CLI alias `"sonnet"` (Sonnet 4.x at the time). Pin
  explicit model IDs in `ab_test_configs.json` and re-run the Sonnet arm
  once on `claude-sonnet-5` before shipping the split — one arm, ~$1–2 on
  the F1 transport (intro pricing), scored by the existing harness.

**Impact (on top of F1, per 30-claim brief, est.):** ~55% of claims at
Sonnet intro pricing (~40% of Opus per-token) with ~10–15% escalated back
→ roughly **25–35% off the assess bill**, i.e. ~$1.00–1.25 → ~$0.70–0.90
batched. Also cuts latency (Sonnet is faster) and Opus rate-limit pressure.

**Alternative if you don't want the routing complexity:** delete the triage
verb (and its CSV columns) — see F6. Either wire it or cut it; the current
state is the worst of both.

### F3. Stop paying the agent to write text nobody reads, and don't ask an LLM to copy a CSV column `[HIGH on the facts; LOW-MEDIUM cost impact — this is mostly a reliability fix]`

Measured on the withers v2 cassette (29 verdicts, ~10K output tokens):

- **51% of all v2 output tokens are for `supported` claims** — whose
  `brief_block` / `opinion_block` / `finding_analysis` / `badge_label` the
  report **never renders**: the Green lane card is built from
  `proposition` + `supporting_language` + flag chips only, with a
  hard-coded "Supported" badge (`proposition_pipeline.py:2082-2092`).
- **`brief_block` ≈ `brief_sentence` for 26/29 claims.** The prompt
  (`prompts/assess_v2.md`) instructs "reproduce the brief's own language…
  verbatim" — a copy job. claims.csv already holds `brief_sentence`; a
  deterministic default (`brief_block = brief_sentence`, agent may only
  *trim*) is strictly **more reliable** than asking Opus to transcribe
  (the 3 mismatches are exactly the paraphrase risk the prompt warns
  against), and removes ~15% of output tokens.

**Change (this is an assess-v3 prompt bump → re-record, budget one
$15–20 recording session, or fold it into the F1 validation re-record):**
for `supported` verdicts, require only `{claim_id, support,
finding_analysis: one sentence}`; drop `brief_block` from the schema
entirely and default it from `brief_sentence` in `run_apply_assessments`.

**Why the cost impact is small:** output is ~345 tokens/claim ≈
$0.009/claim on Opus — under 15% of even the F1-optimized per-claim cost.
Rank this as a correctness/latency cleanup that rides along with the next
prompt version, not a reason to re-record on its own.

### F4. Delete the prescreen path — it's proven harmful and still costs complexity `[HIGH]`

The 2026-06-13 per-phase A/B (opus-v2 vs opus-v2-hints, recorded in
`docs/retrospectives/2026-06-13-…kettering.md` and the
`PRESCREEN_MIN_CHARS` comment at `proposition_pipeline.py:1455-1463`)
showed Haiku hints gave **no net A/B gain (55/61 both) and regressed
Withers 16→14 yellows, both losses lenient-direction** — the worst failure
mode for a citation checker. It defaults OFF, so it costs $0 today, but it
keeps ~150 LOC live (`run_triage`'s prescreen branch `:1576-1624`,
`prompts/prescreen_v1.md`, `_PRESCREEN_SCHEMA`, `render_prescreen_prompt`,
the `--prescreen` CLI flag, the `include_hints` arm plumbing in
`tools/ab_test_runner.py`, and the `opus-with-hints` / `sonnet-with-hints`
/ `opus-v2-hints` configs) — a standing invitation to re-enable a measured
regression. The design comment already says "revisit only with a redesigned
hint": that redesign would be a new prompt version anyway, so nothing is
lost by deleting the current code. Keep the A/B result files as the record.

**Change:** remove the prescreen branch, template, CLI flag, and hint
configs; keep `prescreen_hint` tolerated as a legacy CSV column in merge.

### F5. If the SDK executor survives F1, make it concurrent `[MEDIUM — superseded by F1]`

`AgentSDKExecutor.run` is a serial `for job in jobs` with `anyio.run` per
job (`executor.py:236-258`) — the measured 14–20 min per brief is pure
serialization. Five concurrent jobs (mirroring the SKILL's interactive ~5)
would cut wall-clock ~5× with zero cost change. Only worth doing if you
intend to keep the SDK transport as a fallback after F1; otherwise skip —
concurrency belongs in the new executor.

### F6. Over-engineering inventory — what isn't earning its keep

| item | verdict |
|---|---|
| **Triage verb writing an unread column** | Worst offender. Wire it (F2) or delete verb + columns. |
| **Prescreen path** (code, template, flag, 3 A/B configs) | Delete (F4) — measured harmful. |
| **Three executors, none of them the cheap one** | `RecordedExecutor` earns its keep (it *is* the eval harness). `AgentToolExecutor` earns its keep as the interactive-session transport the SKILL needs. `AgentSDKExecutor` (with its env-stripping, segfault-drain, auth-marker machinery, `executor.py:163-333`) exists to make an agent harness do a single-shot completion's job — after F1 it should shrink to a fallback or be retired. |
| **`brief_block` as an LLM field** | Deterministic copy is more reliable (F3). |
| **`brief_pipeline` alias** (`brief_pipeline.py`) | Fine — already scheduled for removal after one minor version. Do it at 0.6. |
| **`metadata_check`** (`proposition_pipeline.py:1943`) | Dead in the new chain (only the frozen verify-brief skill uses it). Leave until `verify-brief` is retired, then delete. |
| **Dual prompt versions (v1 byte-pinned + v2 default)** | Keep. v1 is the cassette key for the regression suite; the branching in `run_assess`/`apply`/`predict_workdir` is the price of a working offline eval, and it's paying for itself (this audit ran entirely on it). |
| **Stale A/B configs** (`opus-baseline`, `sonnet-baseline`, hint arms) | Prune to the arms you'd actually re-run: `opus-v2`, `sonnet-v1`, plus new `*-api` arms; pin explicit model IDs instead of `"opus"`/`"sonnet"` aliases (alias drift silently changes what an A/B measures). |
| **Deterministic verbs (check-quotes, crosscheck, merge, scoring, report lanes)** | Not over-engineered — this is the part of the design that's right. See the boundary table below. |

### F7. Prompt caching: mostly a non-lever here — correct the TODO plan `[HIGH]`

`scratch/TODO.md` step 3 proposes caching "the stable assess-v2
system/template prefix across the per-opinion jobs." Two problems:
(a) the template is ~1.4K tokens — **below Opus 4.8's 4,096-token minimum
cacheable prefix**, so a `cache_control` marker there silently does
nothing; (b) even if it cached, 1.4K tokens at 0.9× savings is ~$0.006/job.
The *shareable big thing* is the opinion text, and assess-v2's per-opinion
packing already de-duplicates that better than caching would (one job per
opinion, claims packed in). Caching only becomes relevant if F2's
escalation re-sends the same opinion to Opus after a Sonnet pass — caches
are per-model, so even that doesn't connect. Verdict: drop caching from the
plan; the levers are inline+Batches (F1) and routing (F2). (Concurrent
identical-prefix batch requests also can't read a cache entry that's still
being written, which further limits it under Batches.)

---

## Question 1 — the deterministic/LLM boundary, step by step

| step | today | genuinely needs a model? | recommendation |
|---|---|---|---|
| **extract: `proposition`, `cited_for`** | LLM (extract-v1, 1 job/doc) | **Yes** — restating a legal claim and spotting narrower parentheticals is semantic. | Keep LLM. One job per document; cost is negligible next to assess. **No eval exists for extraction accuracy** — I can't verify a cheaper model here, so don't downgrade it blind; if you want to try Sonnet, build a small ground-truth first (the kettering retro's Surace v. Wuliger/Willer catch is the seed of one). |
| **extract: `citations_toa` / `citations_body` lists** | LLM transcription | **No — and deterministic is MORE reliable.** eyecite (+ the parser.py fallbacks) extracts exact-span citations; an LLM can typo a volume/page — which is *exactly* the error class (`Bryant 597-vs-97`) the crosscheck diff exists to catch. Today crosscheck diffs two LLM-transcribed lists, so a transcription slip either fabricates a `toa_mismatch` or masks a real one. | Generate both lists deterministically from the document text (pdf→text, then eyecite); keep the LLM's lists only as a supplement for cites eyecite misses. Crosscheck's input becomes trustworthy. |
| **extract: `quoted_text`, `brief_sentence`, `page`** | LLM | Mostly mechanical, but sentence segmentation + short-form resolution (id./supra) around PDF line noise is where pure regex gets ugly. `check_quotes` already derives quoted spans deterministically when the LLM returns none (`extract_quoted_spans`, `:1834`). | Leave with the LLM for now; the deterministic derivation is the safety net. |
| **verify / download / merge / linkage** | Deterministic (CL API + code) | — | Correct as is. |
| **check-quotes + quote_floor** | Deterministic (`quote_matcher`, §6.4 floors) | — | Correct as is — and note the floor is *enforced over* agent verdicts (`run_apply_assessments`), i.e. determinism already outranks the model where it should. |
| **crosscheck (TOA diff, court, pincite)** | Deterministic flags | — | Correct; reliability improves further once its inputs are deterministic (row 2). Known pincite false-positive class (Royal Truck, cross-reporter star markers) is logged. |
| **triage tracks** | Deterministic rules | — | Rules are fine; the output is unused (F2). |
| **prescreen hints** | LLM (Haiku), default off | It *was* an LLM judgment — and the eval said it subtracts value. | Delete (F4). |
| **assess: `support` axis** | LLM (Opus) | **Yes** — the core semantic judgment; no deterministic substitute. | Keep; right-size transport (F1) and model-by-track (F2). |
| **assess: `brief_block`** | LLM copy job | **No — deterministic is more reliable** (26/29 identical to `brief_sentence`; the other 3 are the paraphrase risk). | Default from `brief_sentence` (F3). |
| **assess: `opinion_block` / `finding_analysis`** | LLM | Yes for findings (choosing the contrasting passage is judgment). **No value for greens** — never rendered. | Slim the schema for `supported` (F3). |
| **color derivation, lanes, floors, report** | Deterministic (`scoring.py`) | — | Correct as is; v2's "agent never outputs a color" design is the right call. |

---

## Question 2 — API-efficiency summary (what to do, in order)

1. **F1: direct Messages API executor with inlined opinions + Batches.**
   ~$13 → ~$1.00–1.25 per 30-claim brief (est.), 15–20 min → minutes/async.
   Validate with one `opus-v2-api` arm over the three corpora against the
   pinned baselines before switching the default.
2. **F2: triage-gated Sonnet/Opus split with escalation.** Further
   ~25–35% off; safety is eval-backed (sonnet-v1 55/61, 0 lenient errors)
   but re-run the Sonnet arm once on a pinned current model ID, and never
   give Sonnet the packed prompt.
3. **Batches vs. parallelism:** default `full` chain → Batches (it already
   pends/resumes, so async fits); interactive/latency-sensitive → 10–20
   concurrent `messages.create`. Both live in the same executor.
4. **Prompt caching: skip** (F7) — template below the cacheable minimum;
   per-opinion packing already captures the shareable-context win.
5. **Model right-sizing elsewhere:** extraction stays Opus until an
   extraction eval exists (unverifiable claim otherwise); prescreen-Haiku
   is deleted, not right-sized; report/lanes/quotes are code, not models.

Projected end state per 30-claim brief (estimates to be confirmed by the
F1 validation run): **~$0.70–1.25 and a few minutes**, vs. ~$13 and ~15–20
min metered today — with assessment accuracy pinned by the same replay
suite at every step, and every finding card still Opus-authored.

## Verification checklist (each maps to an existing eval)

- [ ] F1 executor: `ab_test_runner.py --config opus-v2-api --corpus withers payne wainwright` ≥ pinned v2 baselines (16/19, ≤4 over-flags, 3/3, ≥55/61). Est. $2–4.
- [ ] F2 routing: new `hybrid-v2-api` arm (Sonnet fast-track single-claim + Opus escalation) scored the same way; additionally require 0 lenient errors on the A/B set. Est. $1–3.
- [ ] F2 prereq: re-run `sonnet-v1` with a pinned `claude-sonnet-5` ID (the June arm ran an unpinned alias). Est. $1–2.
- [ ] F3 schema slim: rides the next re-record; verify `brief_block` fallback via `test_proposition_pipeline.py` unit tests (offline).
- [ ] F4/F6 deletions: offline test suite only; no accuracy surface.
- [ ] Fix first (blocks live arms): the A/B harness crash on transient job failures (`scratch/TODO.md` Priority-1) — score completed claims + report the drop instead of dying on `RecordedVerdictMiss`.

## Appendix — measured numbers used above

- Cassette costs (`jobs/assess_results.jsonl`, `cost_usd`/`elapsed_s`):
  withers v2 $14.29 / 1,179 s (29 verdicts); payne v1 $4.17 / 346 s, v2
  $11.35 / 860 s (27); wainwright v1 $5.24 / 380 s, v2 $12.07 / 887 s (34);
  kettering v2 $12.75 / 1,071 s (30).
- Jobs-mode runs record `cost_usd: 0` (session-billed): payne 75,
  sonnet-q3-protest 52, ohio-mailbox 5, extrinsic-evidence 4 — all
  `claude-opus-4-8` / assess-v2.
- March 2026 A/B (per-claim, agent harness, v1 prompt): opus $0.154/claim,
  54/61; sonnet $0.088/claim, 53/61; `input_tokens` mean ~5 (uncached
  remainder — the bill was cache reads).
- Withers v2 output profile: ~345 output tokens/claim; finding_analysis
  66%, opinion_block 16%, brief_block 15%; supported claims 51% of output;
  brief_block ≈ brief_sentence 26/29.
- Corpora: opinions median 19–40 KB raw, max 150 KB; claims-per-opinion is
  1 for ~88% of opinions (packing rarely packs, which is also why the
  packed-prompt risk in F2 only bites Sonnet).
- Triage mix on real matters: fast 44/75, 24/52, 20/32, 19/29.
