# Proposition-Verifier Step 4: assess / apply-assessments Verbs + Jobs Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land design §10 step 4: the versioned prompt template (`assess-v1`, extracted verbatim from the established single-claim prompt), the `AgentToolExecutor` (jobs mode), and verbs 6-7 (`assess`, `apply-assessments`) — all offline-testable end-to-end against the frozen Withers corpus via `RecordedExecutor`.

**Architecture:** The assess verb selects agent-assessable claims (opinion linked, not WRONG_CASE) that lack a verdict for the current prompt version, renders one job per claim from `src/citation_verifier/prompts/assess_v1.md`, writes the transport-neutral `jobs/assess.json`, and hands jobs to the executor. `AgentToolExecutor` (the in-session default) produces no verdicts — it leaves the jobs file for the orchestrating Claude Code session to dispatch Agent-tool subagents that append to `jobs/assess_results.jsonl`; rerunning the verb ingests progress (resume key = claim_id + prompt_version). `apply-assessments` validates verdicts against the version's schema, **enforces the §6.4 quote floor** (agent may lower a color, never below the floor), and writes `assessment`/`support`/`assessed_by` into claims.csv.

**Scope decision (documented deviation):** §6.8's multi-opinion job packing (≤4-5 opinions, ≤200K chars) is deferred to the `assess-v2` prompt work. Every recorded cassette is single-claim `assess-v1`; a multi-claim prompt is a *new prompt version* requiring live re-recording, which is exactly what Step 4 cannot do offline. The packing caps land as constants with the v2 TODO; jobs here are one-claim-per-job, grouped (ordered) by opinion file.

**Source facts:**
- The v1 prompt text: `tests/ab_test_runner.py::build_prompt` == `tests/measure_withers_assessment.py::build_prompt` (criteria block verbatim; placeholders: opinion path, cited_case, proposition, quote_check_worst). The equivalence test pins template fidelity by importing the measurement script's builder and comparing.
- v1 verdict schema: `{"assessment": "Green|Yellow|Red", "rationale": str}` — matches every cassette's `fields`.
- Severity rank for floors exists in `scoring.py` (`_SEVERITY_RANK`); reuse by import (scoring does not import proposition_pipeline — no cycle).
- Frozen Withers corpus: 29 agent-assessable rows with recorded verdicts; 5 deterministic-lane rows.

---

### Task 1: Prompt template + renderer

**Files:** Create `src/citation_verifier/prompts/assess_v1.md`; add renderer to `proposition_pipeline.py`; tests in `test_proposition_pipeline.py`.

- [ ] **1.1 Template** (`assess_v1.md`) — header line `<!-- prompt_version: assess-v1 -->` then the prompt with `{opinion_path}`, `{cited_case}`, `{proposition}`, `{quote_check_worst}` placeholders, body text byte-identical to the established prompt when rendered.
- [ ] **1.2 Renderer:**

```python
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_VERSION_RE = re.compile(r"<!--\s*prompt_version:\s*(\S+)\s*-->")

def load_prompt_template(version: str) -> str:
    """Load a versioned prompt template; the header must declare the
    version it was asked for (a renamed file can't silently lie)."""
    path = _PROMPTS_DIR / f"{version.replace('-', '_')}.md"
    text = path.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m or m.group(1) != version:
        raise ValueError(f"{path} does not declare prompt_version={version}")
    return text[m.end():].lstrip("\n")

def render_assess_prompt(version: str, opinion_path: str, cited_case: str,
                         proposition: str, quote_check_worst: str) -> str:
    return load_prompt_template(version).format(
        opinion_path=opinion_path, cited_case=cited_case,
        proposition=proposition, quote_check_worst=quote_check_worst)
```

- [ ] **1.3 Fidelity test:** render for a synthetic claim and assert `==` `measure_withers_assessment.build_prompt(...)` output (import via `sys.path` like other tests import test modules — or simpler, paste the expected string? NO: import the script (tests dir is importable) and compare, so drift fails loudly).
- [ ] **1.4** Ensure packaging: `prompts/*.md` must ship — check `pyproject.toml`/`setup.cfg` for package-data config and add if needed (editable install works regardless, but fix it properly).
- [ ] **1.5 Commit.**

### Task 2: AgentToolExecutor (jobs mode)

**Files:** `src/citation_verifier/executor.py`; `tests/test_executor.py`.

- [ ] **2.1 Tests:** `AgentToolExecutor(jobs_path)` — `run(jobs)` writes the jobs file (list of `{job_id, claim_ids, prompt, prompt_version, files, schema, max_chars}`) and returns an empty iterator; `pending` attribute lists claim_ids. Writing over an existing jobs file replaces it.
- [ ] **2.2 Implement:**

```python
def job_to_json(job: Job) -> dict: ...   # symmetric with verdict serde

class AgentToolExecutor:
    """Jobs mode (design SS5): emits jobs/<phase>.json and produces no
    verdicts. The orchestrating Claude Code session dispatches one
    Agent-tool subagent per job; each appends a verdict line to the
    results JSONL. Rerun the verb to ingest progress."""
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
```

- [ ] **2.3 Commit.**

### Task 3: `assess` verb

**Files:** `proposition_pipeline.py`; tests.

- [ ] **3.1 Tests:** over a copied Withers corpus:
  - jobs mode (default executor): JSONL removed → `run_assess(wd)` writes `jobs/assess.json` with 29 jobs, returns stats `pending=29, done=0, skipped_deterministic=5`; claims.csv untouched. Rerun after manually appending one verdict → 28 jobs, done=1.
  - RecordedExecutor: JSONL removed, executor built on the *original* corpus cassette → verdicts appended to the copy's JSONL (29 lines), `done=29, pending=0`.
  - already-complete corpus → no jobs file rewrite needed, `done=29` (idempotent no-op path).
- [ ] **3.2 Implement:**

```python
@dataclass
class AssessStats:
    eligible: int = 0; done: int = 0; pending: int = 0
    skipped_deterministic: int = 0

def _assessable(claim) -> bool:
    return bool(claim.get("opinion_file")) and claim.get("cl_status") != "WRONG_CASE"

def run_assess(workdir, executor=None, prompt_version=DEFAULT...):
    # existing verdicts (resume key)
    results_path = workdir / "jobs" / "assess_results.jsonl"
    have = {v.claim_id for v in load_verdicts_jsonl(results_path)
            if v.prompt_version == prompt_version} if results_path.exists() else set()
    jobs = []
    for claim sorted/grouped by opinion_file:
        if not _assessable: skipped_deterministic += 1; continue
        eligible += 1
        if claim_id in have: done += 1; continue
        prompt = render_assess_prompt(prompt_version,
            str(workdir / claim["opinion_file"]), claim["cited_case"],
            claim["proposition"], claim.get("quote_check_worst", "NO_QUOTES"))
        jobs.append(Job(job_id=f"assess-{claim_id}", claim_ids=[claim_id],
                        prompt=prompt, prompt_version=prompt_version,
                        files=[claim["opinion_file"]],
                        schema=_ASSESS_V1_SCHEMA))
    if jobs:
        executor = executor or AgentToolExecutor(workdir / "jobs" / "assess.json")
        for v in executor.run(jobs):
            append_verdict_jsonl(results_path, v); done += 1
        pending = eligible - done
    _update_run_json(workdir, "assess", prompt_version=prompt_version,
                     done=done, pending=pending)
```

`_ASSESS_V1_SCHEMA = {"assessment": "Green|Yellow|Red", "rationale": "str"}` (documentation-shaped; validation happens in apply).
Note `DEFAULT_PROMPT_VERSION = "assess-v1"` — import from `scoring` or define here and have scoring import it (single source; choose `executor.py` as the neutral home and re-export).

- [ ] **3.3 Commit.**

### Task 4: `apply-assessments` verb

- [ ] **4.1 Tests:** over the copied corpus with full JSONL: `run_apply_assessments(wd)` →
  - every assessable claim's `assessment` column = floor-enforced verdict color; `assessed_by` = `"opus/assess-v1"`; `support` column exists (empty for v1); `finding_analysis` = rationale when it was empty.
  - floor case: claim with quote_floor=Yellow + verdict Green → assessment Yellow (find one in the corpus: withers-09 or -38 — assert directly).
  - invalid verdict color in JSONL → that row reported in `stats.invalid`, claim untouched.
  - deterministic rows untouched (no assessment overwrite).
  - **consistency check with scoring:** for every withers ground-truth row present, claims.csv assessment (agent rows) == `scoring.predict_workdir` prediction (the two floor implementations agree).
- [ ] **4.2 Implement** `run_apply_assessments(workdir, prompt_version=...) -> ApplyStats(applied, invalid, missing)`: load verdicts keyed claim_id (last-wins), validate `fields["assessment"] in {Green,Yellow,Red}`, floor via `_SEVERITY_RANK` (import from scoring), write columns (`assessment`, `support`, `assessed_by`, `finding_analysis`-if-empty), add columns to fieldnames as needed, `_update_run_json`.
- [ ] **4.3 Commit.**

### Task 5: CLI verbs + docs + push

- [ ] **5.1** Extend `verify_propositions_main`: verbs `assess` (flags: `--prompt-version`, `--replay PATH` → RecordedExecutor on PATH for offline runs) and `apply-assessments`; `full` chains verify → merge → assess (jobs mode) → stops with pending message when verdicts incomplete, else apply. ASCII output: `[OK] assess: 29 eligible, 0 done, 29 pending -> jobs/assess.json (dispatch agents, then rerun)`.
- [ ] **5.2** Tests for dispatch (monkeypatch the verb functions, same pattern as TestCli).
- [ ] **5.3** CLAUDE.md (verbs, prompts dir, jobs-mode flow), plan execution notes, full offline suite, push.

## Execution notes (2026-06-11, all tasks complete)

- Offline end-to-end is green: copy of the frozen Withers corpus →
  `assess --replay <cassette>` (29 done) → `apply-assessments` (29
  applied; withers-09 floored Green→Yellow) — and a dedicated test pins
  that apply-assessments and `scoring.predict_workdir` agree on every
  agent-assessed claim (one floor rule, two implementations, asserted
  equal).
- Template rendering is `.replace()`-based (the body contains literal
  JSON braces that break `str.format`); `load_prompt_template` refuses a
  file whose header declares a different version than requested.
- The fidelity test imports `measure_withers_assessment.build_prompt`
  (sys.path tweak — tests/ isn't a package) and asserts byte-equality.
- §6.8 packing deferred to assess-v2 as planned (cassettes are
  single-claim v1); jobs are ordered by opinion file so a future packer
  slots in without reordering.
- `pyproject.toml` gained `[tool.setuptools.package-data]` for
  `prompts/*.md`.

## Self-review notes
- §5 AgentToolExecutor: Task 2 (the verb writes the jobs file *through* the executor — one write path).
- §6.6: apply-assessments owns the CSV; subagents only append JSON lines (Task 4).
- §6.8 packing deferred with rationale (header of this plan); the external-tool prohibition belongs to the template — v1's text predates it, and changing v1's text invalidates the cassettes, so the prohibition lands in v2's template (noted for Step 5/6).
- §3 reproducibility: prompt template versioned on disk; run.json stamps prompt_version per assess run.
