# F2 Hybrid Sonnet/Opus Model Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route fast-track claims to Sonnet with escalation to Opus, so assessment cost drops ~25–35% without ever risking a wrong "verified".

**Architecture:** A new `run_assess_hybrid` verb runs Sonnet single-claim v2 jobs over `triage_track == "fast"` claims; any verdict not `support == "supported"` (or that fails) escalates to Opus alongside the full-track claims (packed per opinion). `run_assess` is untouched. Opt-in via `--route hybrid` / an A/B config. No new prompt version (single-claim v2 = a group of one through the existing renderer).

**Tech Stack:** Python 3.11, pytest, the existing `citation_verifier.executor` (`MessagesAPIExecutor`/`AgentSDKExecutor`/`Verdict`/`Job`) and `proposition_pipeline` verbs.

## Global Constraints

- Windows dev box: run Python as `venv/Scripts/python.exe` (not `python`). No `head`/`tail`/`grep` in Git Bash — use Python or the dedicated tools.
- Design spec: `docs/plans/2026-07-01-f2-hybrid-model-routing-design.md`. Every task's requirements implicitly include it.
- **Hybrid is assess-v2 only.** `run_assess_hybrid` raises `ValueError` on a non-`assess-v2` prompt version (v1 has no `support` axis).
- **No new prompt version, no cassette re-record.** Both models use `render_assess_v2_prompt`; a group of one is a single-claim job.
- **Fast model pinned** to `claude-sonnet-5`; full model defaults to `--model` (default `opus`).
- **Opt-in; no CLI default flips.** `--route` defaults to `single`.
- **Escalation invariant:** only Sonnet `support == "supported"` verdicts are kept; everything else (incl. job failures) escalates to Opus, so every non-Green card is Opus-authored.
- **Discarded Sonnet verdicts' cost is captured** in `AssessStats.escalated_cost_usd` (cassette cost sums get quoted; keep them honest).
- Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- `src/citation_verifier/proposition_pipeline.py` — extract `_build_v2_jobs` helper (shared by `run_assess` and hybrid); extend `AssessStats`; add `run_assess_hybrid`.
- `src/citation_verifier/__main__.py` — `--route` arg + hybrid dispatch/executor construction in the assess branch.
- `tools/ab_test_runner.py` — hybrid branch in `run_ab_config` (runs `run_triage` first, prints the mix, hard-fails on `fast==0`, builds two executors, calls `run_assess_hybrid`).
- `tests/ab_test_configs.json` — new `hybrid-v2-api` config.
- `tests/test_assess_hybrid.py` — new; unit tests for `_build_v2_jobs` + `run_assess_hybrid` with fake executors.
- `tests/test_ab_runner.py` — add the vacuous-arm-guard test.
- `CLAUDE.md` + `CHANGELOG.md` — doc updates.

---

### Task 1: Extract `_build_v2_jobs` and refactor `run_assess`

Behavior-preserving refactor so `run_assess` and hybrid share one v2 job builder.

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (add `_build_v2_jobs`; replace the v2 branch of `run_assess` at ~`:1031-1048`)
- Test: `tests/test_assess_hybrid.py`

**Interfaces:**
- Produces: `_build_v2_jobs(claims: list[dict], workdir: Path, prompt_version: str, *, packed: bool) -> list[Job]` — `packed=True` groups one job per `opinion_file`; `packed=False` yields one single-claim job per claim. Both render via `render_assess_v2_prompt`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_assess_hybrid.py`:

```python
import csv
import json

import pytest

from citation_verifier import proposition_pipeline as pp

# render_assess_v2_claim_block only hard-requires claim_id; the rest is
# .get() with defaults. render_assess_v2_prompt substitutes the opinion
# PATH (does not read the file), so no real opinion files are needed.
CLAIM_FIELDS = ["claim_id", "triage_track", "opinion_file", "cl_status",
                "cited_case", "proposition", "quote_check_worst"]


def _claim(**over):
    base = {k: "" for k in CLAIM_FIELDS}
    base.update(over)
    return base


def test_build_v2_jobs_packed_groups_by_opinion(tmp_path):
    claims = [
        _claim(claim_id="c1", opinion_file="opinions/a.txt"),
        _claim(claim_id="c2", opinion_file="opinions/a.txt"),
        _claim(claim_id="c3", opinion_file="opinions/b.txt"),
    ]
    jobs = pp._build_v2_jobs(claims, tmp_path, "assess-v2", packed=True)
    assert len(jobs) == 2
    by_ids = sorted(sorted(j.claim_ids) for j in jobs)
    assert by_ids == [["c1", "c2"], ["c3"]]


def test_build_v2_jobs_unpacked_one_per_claim(tmp_path):
    claims = [
        _claim(claim_id="c1", opinion_file="opinions/a.txt"),
        _claim(claim_id="c2", opinion_file="opinions/a.txt"),
    ]
    jobs = pp._build_v2_jobs(claims, tmp_path, "assess-v2", packed=False)
    assert len(jobs) == 2
    assert all(len(j.claim_ids) == 1 for j in jobs)
    assert {j.claim_ids[0] for j in jobs} == {"c1", "c2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_assess_hybrid.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_build_v2_jobs'`

- [ ] **Step 3: Add `_build_v2_jobs` above `run_assess`**

Insert before `def run_assess(` in `proposition_pipeline.py`:

```python
def _build_v2_jobs(claims: list[dict], workdir: Path, prompt_version: str,
                   *, packed: bool) -> list["Job"]:
    """Build assess-v2 Jobs. packed=True: one job per opinion_file (§6.8
    per-opinion packing, the default assess path). packed=False: one
    single-claim job per claim (the hybrid fast-track pass -- avoids the
    packed prompt that regressed the sonnet-v2 arm). Both render through
    render_assess_v2_prompt (a group of one is a single-claim prompt), so
    verdicts stay homogeneous assess-v2."""
    from .executor import Job
    if packed:
        by_opinion: dict[str, list[dict]] = {}
        for c in claims:
            by_opinion.setdefault(c["opinion_file"], []).append(c)
        groups = [(Path(op).stem[:60], op, grp)
                  for op, grp in by_opinion.items()]
    else:
        groups = [(c["claim_id"], c["opinion_file"], [c]) for c in claims]
    return [Job(
        job_id="assess-" + label,
        claim_ids=[c["claim_id"] for c in group],
        prompt=render_assess_v2_prompt(
            prompt_version, str(workdir / opinion), group),
        prompt_version=prompt_version,
        files=[opinion],
        schema=_ASSESS_V2_SCHEMA,
    ) for label, opinion, group in groups]
```

- [ ] **Step 4: Refactor `run_assess`'s v2 branch to call the helper**

Replace the `else:` branch (the `by_opinion` block, ~`:1031-1048`) with:

```python
    else:
        # v2+: one packed job per opinion (Step 8 decision log:
        # per-opinion only -- documented deviation from §6.8's
        # multi-opinion caps).
        jobs = _build_v2_jobs(todo, workdir, prompt_version, packed=True)
```

- [ ] **Step 5: Run tests to verify pass + no regression**

Run: `venv/Scripts/python.exe -m pytest tests/test_assess_hybrid.py tests/test_proposition_pipeline.py tests/test_assessment_regression.py -q`
Expected: PASS (new tests pass; the refactor is behavior-preserving so existing pipeline + regression tests stay green).

- [ ] **Step 6: Commit**

```bash
git add tests/test_assess_hybrid.py src/citation_verifier/proposition_pipeline.py
git commit -m "$(cat <<'EOF'
refactor: extract _build_v2_jobs shared by run_assess (F2 prep)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `AssessStats` fields + `run_assess_hybrid`

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (extend `AssessStats` at `:963`; add `run_assess_hybrid` after `run_assess`)
- Test: `tests/test_assess_hybrid.py`

**Interfaces:**
- Consumes: `_build_v2_jobs` (Task 1); `AssessStats`; `_assessable`; `_update_run_json`; `render_assess_v2_prompt`; executor `.run(jobs) -> Iterable[Verdict]` + `.failures`; `Verdict(claim_id, fields, model, prompt_version, elapsed_s, cost_usd)`; `append_verdict_jsonl`, `load_verdicts_jsonl`.
- Produces: `run_assess_hybrid(workdir, *, fast_executor, full_executor, prompt_version="assess-v2") -> AssessStats` with new fields `fast_kept: int`, `escalated: int`, `escalated_cost_usd: float`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assess_hybrid.py`:

```python
from citation_verifier.executor import Verdict, append_verdict_jsonl


def _write_claims(workdir, rows):
    workdir.mkdir(parents=True, exist_ok=True)
    with (workdir / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CLAIM_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(_claim(**r))


class FakeExecutor:
    """Yields a Verdict per claim_id from support_by_id; claim_ids in
    fail_ids yield no verdict (recorded in .failures), mirroring a real
    executor's non-auth per-job failure handling."""

    def __init__(self, support_by_id, fail_ids=(), cost=0.02):
        self.support_by_id = support_by_id
        self.fail_ids = set(fail_ids)
        self.cost = cost
        self.failures = []
        self.model = "fake"
        self.seen = []

    def run(self, jobs):
        out = []
        for job in jobs:
            for cid in job.claim_ids:
                self.seen.append(cid)
                if cid in self.fail_ids:
                    self.failures.append((job.job_id, "sim fail"))
                    continue
                out.append(Verdict(
                    claim_id=cid,
                    fields={"support": self.support_by_id[cid],
                            "badge_label": "", "brief_block": "",
                            "opinion_block": "", "finding_analysis": ""},
                    model="fake-model", prompt_version=job.prompt_version,
                    cost_usd=self.cost))
        return out


def _persisted_ids(workdir):
    path = workdir / "jobs" / "assess_results.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["claim_id"]
            for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_supported_fast_kept_and_full_routed(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [
        dict(claim_id="f1", triage_track="fast",
             opinion_file="opinions/a.txt", cl_status="VERIFIED"),
        dict(claim_id="u1", triage_track="full",
             opinion_file="opinions/b.txt", cl_status="VERIFIED"),
    ])
    fast = FakeExecutor({"f1": "supported"})
    full = FakeExecutor({"u1": "unsupported"})
    stats = pp.run_assess_hybrid(wd, fast_executor=fast, full_executor=full,
                                 prompt_version="assess-v2")
    assert fast.seen == ["f1"]
    assert full.seen == ["u1"]
    assert stats.fast_kept == 1 and stats.escalated == 0
    assert sorted(_persisted_ids(wd)) == ["f1", "u1"]


def test_non_supported_fast_escalates_not_persisted(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [dict(claim_id="f1", triage_track="fast",
                            opinion_file="opinions/a.txt", cl_status="VERIFIED")])
    fast = FakeExecutor({"f1": "partial"}, cost=0.05)
    full = FakeExecutor({"f1": "partial"})
    stats = pp.run_assess_hybrid(wd, fast_executor=fast, full_executor=full,
                                 prompt_version="assess-v2")
    assert "f1" in full.seen  # escalated to Opus
    assert stats.escalated == 1 and stats.fast_kept == 0
    assert abs(stats.escalated_cost_usd - 0.05) < 1e-9
    assert _persisted_ids(wd) == ["f1"]  # only the Opus verdict


def test_fast_failure_escalates(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [dict(claim_id="f1", triage_track="fast",
                            opinion_file="opinions/a.txt", cl_status="VERIFIED")])
    fast = FakeExecutor({}, fail_ids=["f1"])
    full = FakeExecutor({"f1": "supported"})
    stats = pp.run_assess_hybrid(wd, fast_executor=fast, full_executor=full,
                                 prompt_version="assess-v2")
    assert "f1" in full.seen
    assert stats.escalated == 1
    assert stats.escalated_cost_usd == 0.0  # no verdict -> no cost captured
    assert _persisted_ids(wd) == ["f1"]


def test_legacy_missing_triage_all_full(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [
        dict(claim_id="x1", triage_track="", opinion_file="opinions/a.txt",
             cl_status="VERIFIED"),
        dict(claim_id="x2", triage_track="", opinion_file="opinions/a.txt",
             cl_status="VERIFIED"),
    ])
    fast = FakeExecutor({})
    full = FakeExecutor({"x1": "supported", "x2": "unsupported"})
    stats = pp.run_assess_hybrid(wd, fast_executor=fast, full_executor=full,
                                 prompt_version="assess-v2")
    assert fast.seen == []
    assert sorted(full.seen) == ["x1", "x2"]
    assert stats.fast_kept == 0 and stats.escalated == 0


def test_resume_skips_persisted(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [dict(claim_id="f1", triage_track="fast",
                            opinion_file="opinions/a.txt", cl_status="VERIFIED")])
    append_verdict_jsonl(wd / "jobs" / "assess_results.jsonl", Verdict(
        claim_id="f1", fields={"support": "supported"},
        model="prior", prompt_version="assess-v2"))
    fast = FakeExecutor({"f1": "supported"})
    full = FakeExecutor({})
    stats = pp.run_assess_hybrid(wd, fast_executor=fast, full_executor=full,
                                 prompt_version="assess-v2")
    assert fast.seen == [] and full.seen == []
    assert stats.done == 1 and stats.pending == 0


def test_v1_prompt_raises(tmp_path):
    wd = tmp_path / "wd"
    _write_claims(wd, [dict(claim_id="f1", triage_track="fast",
                            opinion_file="opinions/a.txt", cl_status="VERIFIED")])
    with pytest.raises(ValueError):
        pp.run_assess_hybrid(wd, fast_executor=FakeExecutor({}),
                             full_executor=FakeExecutor({}),
                             prompt_version="assess-v1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_assess_hybrid.py -v -k "hybrid or escalate or legacy or resume or v1_prompt or supported_fast"`
Expected: FAIL — `AttributeError: ... 'run_assess_hybrid'` (and `AssessStats` has no `fast_kept`).

- [ ] **Step 3: Extend `AssessStats`**

Replace the `AssessStats` dataclass (`:963-969`) with:

```python
@dataclass
class AssessStats:
    """Statistics from run_assess / run_assess_hybrid."""
    eligible: int = 0
    done: int = 0
    pending: int = 0
    skipped_deterministic: int = 0
    fast_kept: int = 0            # hybrid: Sonnet 'supported' verdicts kept
    escalated: int = 0           # hybrid: fast-track claims sent to Opus
    escalated_cost_usd: float = 0.0  # cost of discarded Sonnet verdicts
```

- [ ] **Step 4: Add `run_assess_hybrid`**

Insert immediately after `run_assess` (after its `return stats`):

```python
def run_assess_hybrid(workdir: Path, *, fast_executor: Any,
                      full_executor: Any,
                      prompt_version: str = ASSESS_V2_PROMPT_VERSION,
                      ) -> AssessStats:
    """Verb 6, hybrid routing (cost-audit F2). Fast-track claims
    (triage_track == 'fast') go to fast_executor (Sonnet) as single-claim
    v2 jobs; any verdict not support=='supported' -- or a job that fails
    -- escalates to full_executor (Opus) alongside the full-track claims,
    packed per opinion. Only final verdicts persist (Sonnet-supported +
    all Opus); discarded Sonnet verdicts' cost is captured in
    escalated_cost_usd. Requires a v2 prompt (the 'support' axis)."""
    from .executor import append_verdict_jsonl, load_verdicts_jsonl

    if not prompt_version.startswith("assess-v2"):
        raise ValueError(
            f"run_assess_hybrid needs a v2 prompt (support axis); "
            f"got {prompt_version!r}")

    workdir = Path(workdir)
    results_path = workdir / "jobs" / "assess_results.jsonl"
    have: set[str] = set()
    if results_path.exists():
        have = {v.claim_id for v in load_verdicts_jsonl(results_path)
                if v.prompt_version == prompt_version}

    with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    stats = AssessStats()
    fast_todo: list[dict] = []
    full_todo: list[dict] = []
    for c in claims:
        if not _assessable(c):
            stats.skipped_deterministic += 1
            continue
        stats.eligible += 1
        if c["claim_id"] in have:
            stats.done += 1
        elif c.get("triage_track") == "fast":
            fast_todo.append(c)
        else:
            full_todo.append(c)  # 'full', '' or missing -> Opus (safe default)

    # Pass 1: Sonnet, single-claim v2 over fast-track.
    escalate: list[dict] = []
    if fast_todo:
        returned = {v.claim_id: v for v in fast_executor.run(
            _build_v2_jobs(fast_todo, workdir, prompt_version, packed=False))}
        for c in fast_todo:
            v = returned.get(c["claim_id"])
            if v is not None and v.fields.get("support") == "supported":
                append_verdict_jsonl(results_path, v)
                stats.done += 1
                stats.fast_kept += 1
            else:
                if v is not None:  # discarded verdict still cost tokens
                    stats.escalated_cost_usd += v.cost_usd
                escalate.append(c)
                stats.escalated += 1

    # Pass 2: Opus, packed per opinion, over full-track + escalated.
    pass2 = full_todo + escalate
    if pass2:
        for v in full_executor.run(
                _build_v2_jobs(pass2, workdir, prompt_version, packed=True)):
            append_verdict_jsonl(results_path, v)
            stats.done += 1

    stats.pending = stats.eligible - stats.done
    _update_run_json(workdir, "assess", prompt_version=prompt_version,
                     route="hybrid", done=stats.done, pending=stats.pending,
                     fast_kept=stats.fast_kept, escalated=stats.escalated,
                     escalated_cost_usd=round(stats.escalated_cost_usd, 6))
    return stats
```

- [ ] **Step 5: Run tests to verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_assess_hybrid.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_assess_hybrid.py
git commit -m "$(cat <<'EOF'
feat: run_assess_hybrid — Sonnet fast-track + Opus escalation (F2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: CLI `--route` wiring

**Files:**
- Modify: `src/citation_verifier/__main__.py` (add `--route` arg near `:584`; hybrid branch in the assess dispatch at `:711`)
- Test: manual smoke (no unit test — argparse + dispatch glue; behavior is covered by Task 2 + Task 4).

**Interfaces:**
- Consumes: `pp.run_assess_hybrid` (Task 2); `args.executor`, `args.model`, `args.batch`, `args.replay`.

- [ ] **Step 1: Add the `--route` argument**

After the `--prescreen` argument block (~`:588`), add:

```python
    parser.add_argument(
        "--route", choices=["single", "hybrid"], default="single",
        help="assess routing: single = one model (default); hybrid = "
             "Sonnet single-claim fast-track + Opus escalation "
             "(cost-audit F2; requires --executor api or sdk)",
    )
```

- [ ] **Step 2: Replace the assess dispatch branch**

Replace the `if args.verb in ("assess", "full"):` block (`:711-721`) with:

```python
    if args.verb in ("assess", "full"):
        if args.route == "hybrid":
            if not args.replay and args.executor not in ("api", "sdk"):
                print("Error: --route hybrid requires --executor api or sdk "
                      "(jobs mode is interactive; it can't do the two-pass "
                      "escalation in-process)", file=sys.stderr)
                return 1
            if args.replay:
                from .executor import RecordedExecutor
                fast_ex = full_ex = RecordedExecutor(args.replay)
            elif args.executor == "sdk":
                from .executor import AgentSDKExecutor
                fast_ex = AgentSDKExecutor(model="claude-sonnet-5",
                                           cwd=str(workdir))
                full_ex = AgentSDKExecutor(model=args.model, cwd=str(workdir))
            else:  # api
                from .executor import MessagesAPIExecutor
                fast_ex = MessagesAPIExecutor(model="claude-sonnet-5",
                                              cwd=str(workdir),
                                              batch=args.batch)
                full_ex = MessagesAPIExecutor(model=args.model,
                                              cwd=str(workdir),
                                              batch=args.batch)
            astats = pp.run_assess_hybrid(
                workdir, fast_executor=fast_ex, full_executor=full_ex,
                prompt_version=prompt_version)
            print(f"[OK] assess (hybrid): {astats.eligible} eligible, "
                  f"{astats.done} done, fast_kept={astats.fast_kept}, "
                  f"escalated={astats.escalated}, "
                  f"escalated_cost=${astats.escalated_cost_usd:.4f}, "
                  f"pending={astats.pending}")
        else:
            astats = pp.run_assess(workdir, executor=_make_executor(),
                                   prompt_version=prompt_version)
            print(f"[OK] assess: {astats.eligible} eligible, "
                  f"{astats.done} done, {astats.pending} pending, "
                  f"{astats.skipped_deterministic} deterministic")
        if astats.pending:
            print(f"  PENDING: dispatch agents over jobs/assess.json, "
                  f"append verdicts to jobs/assess_results.jsonl, then "
                  f"rerun this verb to ingest")
            return 0  # full stops here until verdicts are complete
```

- [ ] **Step 3: Smoke-test the guard and help**

Run: `venv/Scripts/python.exe -m citation_verifier verify-propositions --help`
Expected: `--route {single,hybrid}` appears.

Run (guard, needs any existing workdir with claims.csv, e.g. a frozen corpus copied to a tmp dir — or expect the workdir-missing error first):
`venv/Scripts/python.exe -m citation_verifier verify-propositions tests/data/assessment_corpora/withers assess --route hybrid`
Expected: `Error: --route hybrid requires --executor api or sdk` (default executor is `jobs`).

- [ ] **Step 4: Run the CLI/proposition tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -q`
Expected: PASS (no regressions from the argparse/dispatch change).

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/__main__.py
git commit -m "$(cat <<'EOF'
feat: --route hybrid CLI wiring for run_assess_hybrid (F2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: A/B harness hybrid dispatch + `hybrid-v2-api` config + vacuous-arm guard

**Files:**
- Modify: `tools/ab_test_runner.py` (`run_ab_config` live branch)
- Modify: `tests/ab_test_configs.json` (add `hybrid-v2-api`)
- Test: `tests/test_ab_runner.py`

**Interfaces:**
- Consumes: `pp.run_assess_hybrid`, `pp.run_triage`, `make_executor`, `run_ab_config(config_name, config, corpora, run_root, executor_factory)`.

- [ ] **Step 1: Write the failing test (vacuous-arm guard + triage-runs-first)**

Append to `tests/test_ab_runner.py` (imports `run_ab_config`, `FakeExecutor`-style factory; check existing imports and reuse the module's patterns):

```python
def test_hybrid_arm_runs_triage_and_guards_vacuous(tmp_path):
    """The frozen corpora lack triage_track; the hybrid branch must run
    run_triage on the copy so Sonnet actually fires. With a corpus that
    triages to some fast-track claims, the fake factory's fast executor
    must see >=1 claim."""
    import tools.ab_test_runner as abr
    from citation_verifier.executor import Verdict

    class _Fake:
        def __init__(self, model):
            self.model = model
            self.failures = []
            self.seen = []
        def run(self, jobs):
            out = []
            for job in jobs:
                for cid in job.claim_ids:
                    self.seen.append(cid)
                    out.append(Verdict(claim_id=cid,
                        fields={"support": "supported"},
                        model=self.model, prompt_version=job.prompt_version))
            return out

    made = {}
    def factory(config, workdir, phase):
        ex = _Fake(config.get("model", "?"))
        made.setdefault(config.get("model"), ex)
        return ex

    config = {"route": "hybrid", "fast_model": "claude-sonnet-5",
              "full_model": "claude-opus-4-8", "executor": "api",
              "prompt_version": "assess-v2"}
    abr.run_ab_config("hybrid-test", config, corpora=["withers"],
                      run_root=tmp_path, executor_factory=factory)
    # The Sonnet (fast) executor must have seen at least one fast-track claim.
    assert made["claude-sonnet-5"].seen, "Sonnet never ran -- vacuous arm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_ab_runner.py::test_hybrid_arm_runs_triage_and_guards_vacuous -v`
Expected: FAIL — `run_ab_config` has no hybrid branch, so it runs single-model `run_assess` and the Sonnet fake is never built/exercised (KeyError or empty `seen`).

- [ ] **Step 3: Add the hybrid branch to `run_ab_config`**

In `tools/ab_test_runner.py`, at the top of `run_ab_config` add the imports and read `route`; then branch the live path. Replace the live `else:` body (the `executor = ...; run_assess(...)` block, ~`:100-136`) so it reads:

```python
        else:
            if run_root is None:
                raise ValueError("run_root is required for live runs")
            wd = Path(run_root) / name
            shutil.copytree(src, wd)
            cassette = wd / "jobs" / "assess_results.jsonl"
            if cassette.exists():
                cassette.unlink()  # fresh verdicts for this config
            mk = executor_factory or make_executor

            if config.get("route") == "hybrid":
                from citation_verifier.proposition_pipeline import (
                    run_assess_hybrid, run_triage)
                # Frozen corpora lack triage_track; without this the legacy-
                # safety rule routes every claim to Opus and the arm is
                # vacuous (Sonnet never fires).
                run_triage(wd, prescreen=False)
                import csv as _csv
                with open(wd / "claims.csv", newline="",
                          encoding="utf-8") as f:
                    tracks = [r.get("triage_track", "")
                              for r in _csv.DictReader(f)]
                fast_n, full_n = tracks.count("fast"), tracks.count("full")
                print(f"  {name}: triage mix fast={fast_n} full={full_n}")
                if fast_n == 0:
                    raise SystemExit(
                        f"{name}: 0 fast-track claims -- hybrid arm would be "
                        f"vacuous (Sonnet never runs). Aborting.")
                fast_ex = mk({**config, "model": config["fast_model"]},
                             wd, "assess")
                full_ex = mk({**config, "model": config["full_model"]},
                             wd, "assess")
                stats = run_assess_hybrid(
                    wd, fast_executor=fast_ex, full_executor=full_ex,
                    prompt_version=prompt_version)
                print(f"  {name}: fast_kept={stats.fast_kept} "
                      f"escalated={stats.escalated} "
                      f"escalated_cost=${stats.escalated_cost_usd:.4f}")
            else:
                executor = mk(config, wd, "assess")
                if config.get("include_hints"):
                    from citation_verifier.proposition_pipeline import \
                        run_triage
                    pre_config = dict(config)
                    pre_config["model"] = config.get("prescreen_model",
                                                     "haiku")
                    pre_ex = mk(pre_config, wd, "prescreen")
                    tstats = run_triage(wd, prescreen=True, executor=pre_ex)
                    if tstats.prescreen_pending:
                        print(f"  WARNING {name}: "
                              f"{tstats.prescreen_pending} prescreen hints "
                              f"pending -- assess runs without them")
                stats = run_assess(wd, executor=executor,
                                   prompt_version=prompt_version)
                failures = getattr(executor, "failures", [])
                if failures:
                    print(f"  WARNING {name}: {len(failures)} job "
                          f"failures: {failures[:3]}")
                if stats.pending:
                    print(f"  WARNING {name}: {stats.pending} verdicts "
                          f"still pending -- scoring the rest")

            from citation_verifier.executor import RecordedExecutor
            scorer = RecordedExecutor(wd / "jobs" / "assess_results.jsonl",
                                      missing="skip")
            scores[name] = score_workdir(wd, executor=scorer,
                                         prompt_version=prompt_version)
            if scorer.misses:
                print(f"  WARNING {name}: {len(scorer.misses)} claims "
                      f"dropped from scoring (no verdict): "
                      f"{[m[0] for m in scorer.misses]}")
```

Note: this preserves the existing single-model path (including the `include_hints` prescreen block and failure/pending warnings) verbatim inside the `else:`, and shares the scoring tail. Confirm `run_assess` is imported at the top of `run_ab_config` (it already is, alongside `score_workdir`).

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_ab_runner.py -q`
Expected: PASS (new hybrid test + existing ab_runner tests).

- [ ] **Step 5: Add the `hybrid-v2-api` config**

In `tests/ab_test_configs.json`, add inside `"configs"`:

```json
    "hybrid-v2-api": {
      "description": "F2 hybrid routing: Sonnet single-claim fast-track + Opus escalation via the API. cost-audit F2 validation arm -- require 0 lenient-direction errors on the A/B set, reds 3/3, A/B >=55/61, withers yellows >=14.",
      "route": "hybrid",
      "fast_model": "claude-sonnet-5",
      "full_model": "claude-opus-4-8",
      "executor": "api",
      "prompt_version": "assess-v2",
      "include_hints": false
    }
```

- [ ] **Step 6: Verify the config loads**

Run: `venv/Scripts/python.exe -c "import json; print('hybrid-v2-api' in json.load(open('tests/ab_test_configs.json'))['configs'])"`
Expected: `True`

- [ ] **Step 7: Commit**

```bash
git add tools/ab_test_runner.py tests/ab_test_configs.json tests/test_ab_runner.py
git commit -m "$(cat <<'EOF'
feat: A/B hybrid dispatch + hybrid-v2-api config + vacuous-arm guard (F2)

run_ab_config runs run_triage on the copy before the hybrid arm (frozen
corpora lack triage_track) and hard-fails on fast==0 so the arm can't
pass trivially.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Docs

**Files:**
- Modify: `CLAUDE.md` (proposition_pipeline row — add `run_assess_hybrid`; A/B runner row — add `hybrid-v2-api`)
- Modify: `CHANGELOG.md` (additive, minor)

- [ ] **Step 1: Update CLAUDE.md**

In the `proposition_pipeline.py` row, after the `run_assess(...)` description, add a sentence:

> `run_assess_hybrid()` (cost-audit F2): Sonnet single-claim v2 over `triage_track=='fast'` claims → any not `support=='supported'` (or that fails) escalates to Opus with the full-track claims (packed per opinion); only final verdicts persist, discarded Sonnet cost captured in `AssessStats.escalated_cost_usd`. Opt-in via `--route hybrid` (requires `--executor api|sdk`); assess-v2 only.

In the `tools/ab_test_runner.py` row, add `hybrid-v2-api` to the config list and note the hybrid arm runs `run_triage` on the copy and hard-fails on `fast==0`.

- [ ] **Step 2: Update CHANGELOG.md**

Add under an Unreleased/next-minor heading (match the file's existing style):

```markdown
### Added
- Hybrid model routing (`run_assess_hybrid`, cost-audit F2): fast-track
  claims assessed by Sonnet single-claim v2, escalating anything not
  `supported` (or that fails) to Opus. Opt-in via `--route hybrid`
  (requires `--executor api|sdk`) and the `hybrid-v2-api` A/B config.
  `AssessStats` gains `fast_kept`, `escalated`, `escalated_cost_usd`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: run_assess_hybrid + hybrid-v2-api (F2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Full offline suite green**

Run: `venv/Scripts/python.exe -m pytest -q -m "not live_api" --deselect tests/test_false_negatives.py`
Expected: PASS (baseline was 870 passed, 2 skipped; now +~9 new tests).

---

## Validation (run-time, metered — not a code task)

After Task 5, run the F2 validation arm and gate on the results (design spec "Testing"):

```bash
# Same-day Opus control (free while SDK subscription-covered), for the
# variance baseline the hybrid arm is judged against:
venv/Scripts/python.exe tools/ab_test_runner.py --config opus-v2 \
    --corpus withers payne wainwright

# Hybrid arm (metered; Sonnet is ~half Opus/token, so cheap):
venv/Scripts/python.exe tools/ab_test_runner.py --config hybrid-v2-api \
    --corpus withers payne wainwright
```

**Accept the hybrid arm only if all hold** (else do not ship / tune first):
- **0 lenient-direction errors on the A/B set** (payne+wainwright) — hard fail otherwise;
- reds **3/3**;
- A/B **≥ 55/61**;
- withers yellows **≥ 14** (the same-day Opus control floor).

Also read the printed `fast_kept` / `escalated` / `escalated_cost_usd` per corpus: confirm Sonnet fired (`fast>0`, guaranteed by the guard), note the escalation rate (high escalation = Sonnet over-flags on single-claim v2 → cost creeps up but safety holds), and confirm total cost (incl. `escalated_cost_usd`) beats the Opus-only arm. Snapshot the result JSONLs to `scratch/ab_runs/` and commit; append outcomes to the design doc. **Do not flip any CLI default** — hybrid stays opt-in.

---

## Self-Review

**Spec coverage:**
- `run_assess_hybrid` verb + two-pass flow + partition + escalation → Task 2. ✓
- No new prompt version (single-claim v2 via shared builder) → Task 1 + Task 2. ✓
- Persistence/resume (only final verdicts; escalated re-run on resume) → Task 2 (`have` set + `test_resume_skips_persisted`). ✓
- Legacy `triage_track` empty → all Opus → Task 2 (`test_legacy_missing_triage_all_full`). ✓
- Stats `fast_kept`/`escalated`/`escalated_cost_usd` + run.json → Task 2. ✓
- CLI `--route` + jobs-mode guard + fast-model pin → Task 3. ✓
- A/B `hybrid-v2-api` + `run_triage`-first + vacuous-arm hard-fail + mix print → Task 4. ✓
- Validation gate (0 lenient, reds 3/3, A/B ≥55, withers ≥14) → Validation section. ✓
- Docs → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. ✓

**Type consistency:** `_build_v2_jobs(..., *, packed)` signature identical in Task 1 (definition), Task 2 (both call sites). `run_assess_hybrid(workdir, *, fast_executor, full_executor, prompt_version)` identical across Task 2 (def), Task 3 (CLI call), Task 4 (A/B call). `AssessStats` new fields (`fast_kept`, `escalated`, `escalated_cost_usd`) referenced consistently in Task 2/3/4. ✓
