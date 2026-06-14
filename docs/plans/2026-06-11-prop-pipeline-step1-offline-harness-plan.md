# Proposition-Verifier Step 1: Offline Test Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the offline TDD harness everything else in the pipeline redesign builds on: three frozen assessment corpora, the `LLMExecutor` protocol with a `RecordedExecutor` replay adapter, and an offline scoring function over the design's two-axis mapping.

**Architecture:** This is §10 step 1 of `docs/plans/2026-06-11-proposition-verifier-pipeline-design.md` (the contract — §5 executor, §6.9 two-axis mapping, §7 corpora, §8 acceptance baselines). Three frozen workdirs under `tests/data/assessment_corpora/` each carry `claims.csv` (with a new stable `claim_id` column), `opinions/`, `ground_truth.csv`, and a recorded `jobs/assess_results.jsonl` cassette. `RecordedExecutor` replays cassette verdicts keyed by `(claim_id, prompt_version)` and raises on miss, mirroring `tests/cassette_client.py`'s `CassetteMiss`. A scoring module reproduces both committed baselines (Withers 12/19 yellows; A/B 54/61) offline in seconds, as pytest.

**Tech Stack:** Python 3.10+ stdlib only (dataclasses, csv, json, pathlib, typing.Protocol). pytest. No network, no LLM calls, no new dependencies.

**Verified source-data facts (gathered 2026-06-11, current branch `pipeline-redesign`):**

- `tests/data/withers_aberdeen/assessment_workdir/claims.csv` — 34 rows, **no claim_id column**; row order exactly matches the measurement sample (verified 34/34 by proposition+citation against `withers_baseline_results.csv` filtered to `label in (yellow, red) or row_id in GREEN_SAMPLE`).
- `tests/data/withers_assessment_runs.jsonl` — 34 records `{row_id, predicted, rationale, mode[, elapsed_s, cost_usd]}`; 29 `mode=agent`, 5 `mode=deterministic`.
- `tests/ab_test_cases.json` — **61** cases (design says 62; actual count is 61): payne 27, wainwright 34. `case.id` = row index into that brief's `claims.csv` (verified: 27/27 + 34/34 match on `cited_case` AND `opinion_file`). **ids overlap between sources** — payne ids include 11..83, wainwright 0..33 — so `(id, cited_case)` is the unique key.
- `tests/data/results/ab_opus-baseline_20260323-002228.jsonl` — git-tracked; 61 records `{case_id, cited_case, proposition(80ch), expected, actual, correct, rationale, elapsed_s, model, cost_usd, input_tokens, output_tokens}`; covers all 61 cases exactly once via `(case_id, cited_case)`; payne 21/27 correct, wainwright 33/34, total 54/61.
- `briefs/payne-proposed/claims.csv` (84 rows) and `briefs/wainwright-v-state/claims.csv` (34 rows) — columns `page, proposition, cited_case, retrieved_case, supporting_language, assessment, cl_url, cl_status, diagnostics, opinion_file, quoted_text, quote_check, quote_check_worst` (no `syllabus`, no `brief_sentence`). Withers claims.csv additionally has `syllabus` and `brief_sentence`.
- The assessment prompt in `tests/ab_test_runner.py::build_prompt` and `tests/measure_withers_assessment.py::build_prompt` is the **same criteria text and JSON contract** → both recordings share one prompt version: **`assess-v1`**.
- Withers baseline numbers to reproduce (from `tests/data/withers_aberdeen/README.md` + `withers_assessment_results.csv`): yellows caught 12/19 (6 exact Yellow, 6 Red), missed 7 = withers-05, -09, -12, -32, -38, -44, -49; greens 9/12 exact, over-flagged withers-01 and withers-26, Gray withers-29; reds: withers-43 Red (deterministic WRONG_CASE), withers-42 and withers-54 Gray.

**Windows invocations:** always `venv/Scripts/python.exe -m pytest ...`; ASCII-only console output.

---

### Task 1: Executor data types + JSONL serde

**Files:**
- Create: `src/citation_verifier/executor.py`
- Create: `tests/test_executor.py`

- [ ] **Step 1.1: Write failing tests for Job/Verdict/serde**

```python
# tests/test_executor.py
"""Tests for the LLM executor protocol and RecordedExecutor (design SS5).

Offline only -- no network, no LLM. RecordedExecutor is the assessment-side
mirror of tests/cassette_client.py.
"""
import json
from pathlib import Path

import pytest

from citation_verifier.executor import (
    Job,
    RecordedExecutor,
    RecordedVerdictMiss,
    Verdict,
    append_verdict_jsonl,
    load_verdicts_jsonl,
)


def _verdict(claim_id="w-01", version="assess-v1", assessment="Yellow"):
    return Verdict(
        claim_id=claim_id,
        fields={"assessment": assessment, "rationale": "test rationale"},
        model="opus",
        prompt_version=version,
        elapsed_s=1.5,
        cost_usd=0.02,
    )


class TestVerdictSerde:
    def test_round_trip_through_jsonl(self, tmp_path):
        path = tmp_path / "results.jsonl"
        v1 = _verdict("w-01")
        v2 = _verdict("w-02", assessment="Green")
        append_verdict_jsonl(path, v1)
        append_verdict_jsonl(path, v2)
        loaded = load_verdicts_jsonl(path)
        assert loaded == [v1, v2]

    def test_jsonl_lines_are_flat_json_objects(self, tmp_path):
        path = tmp_path / "results.jsonl"
        append_verdict_jsonl(path, _verdict())
        line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert line["claim_id"] == "w-01"
        assert line["prompt_version"] == "assess-v1"
        assert line["fields"]["assessment"] == "Yellow"

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_verdicts_jsonl(tmp_path / "nope.jsonl")

    def test_job_defaults(self):
        job = Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                  prompt_version="assess-v1")
        assert job.files == []
        assert job.schema is None
        assert job.max_chars is None
```

- [ ] **Step 1.2: Run tests, verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation_verifier.executor'`

- [ ] **Step 1.3: Implement Job, Verdict, protocol, serde**

```python
# src/citation_verifier/executor.py
"""LLM executor protocol + adapters (pipeline redesign design SS5).

An LLM verb (assess, extract, prescreen) emits transport-neutral Jobs and
consumes Verdicts; the executor between them is pluggable. This module
defines the protocol, the JSONL verdict serialization shared by all
adapters (jobs/<phase>_results.jsonl sidecars), and the offline
RecordedExecutor -- the assessment-side mirror of tests/cassette_client.py.

Live adapters (AgentSDKExecutor, AgentToolExecutor, MessagesAPIExecutor)
come in later steps; see the design doc.
"""
from __future__ import annotations

import json
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
```

(`RecordedExecutor` / `RecordedVerdictMiss` come in Task 2 — the import in the test file will still fail, which is fine: Task 2's tests drive them. To keep Task 1 green on its own, add the Task 2 class stubs only if you want the import to resolve; preferred order is to do Task 2 immediately after, in the same sitting.)

- [ ] **Step 1.4: Run serde tests** (Task 2 classes not yet present — run only the serde class)

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v`
Expected: still FAIL on import of `RecordedExecutor`. Proceed straight to Task 2 (same commit); the two tasks share the test module.

### Task 2: RecordedExecutor (replay adapter)

**Files:**
- Modify: `src/citation_verifier/executor.py` (append)
- Modify: `tests/test_executor.py` (append)

- [ ] **Step 2.1: Write failing tests for replay, miss, version mismatch**

```python
# append to tests/test_executor.py
class TestRecordedExecutor:
    @pytest.fixture
    def cassette(self, tmp_path):
        path = tmp_path / "assess_results.jsonl"
        append_verdict_jsonl(path, _verdict("w-01", assessment="Yellow"))
        append_verdict_jsonl(path, _verdict("w-02", assessment="Green"))
        return path

    def test_replays_recorded_verdicts(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01", "w-02"], prompt="ignored",
                    prompt_version="assess-v1")]
        verdicts = list(ex.run(jobs))
        assert [v.claim_id for v in verdicts] == ["w-01", "w-02"]
        assert verdicts[0].fields["assessment"] == "Yellow"
        assert verdicts[1].fields["assessment"] == "Green"

    def test_unknown_claim_raises_miss(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-99"], prompt="p",
                    prompt_version="assess-v1")]
        with pytest.raises(RecordedVerdictMiss):
            list(ex.run(jobs))
        assert ex.misses == [("w-99", "assess-v1")]

    def test_prompt_version_mismatch_raises_miss(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                    prompt_version="assess-v2")]
        with pytest.raises(RecordedVerdictMiss):
            list(ex.run(jobs))

    def test_duplicate_claim_id_last_write_wins(self, cassette):
        append_verdict_jsonl(cassette, _verdict("w-01", assessment="Red"))
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                    prompt_version="assess-v1")]
        (v,) = list(ex.run(jobs))
        assert v.fields["assessment"] == "Red"
```

- [ ] **Step 2.2: Run, verify fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v`
Expected: FAIL — `ImportError: cannot import name 'RecordedExecutor'`

- [ ] **Step 2.3: Implement RecordedExecutor**

```python
# append to src/citation_verifier/executor.py
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
```

- [ ] **Step 2.4: Run full test module, verify all pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v`
Expected: all PASS (9 tests)

- [ ] **Step 2.5: Run the existing mocked suite to confirm no collateral damage**

Run: `venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_brief_pipeline.py -q`
Expected: PASS (same counts as before)

- [ ] **Step 2.6: Commit**

```bash
git add src/citation_verifier/executor.py tests/test_executor.py
git commit -m "feat: LLMExecutor protocol + RecordedExecutor replay adapter (design SS5)"
```

### Task 3: Move the Withers workdir (history-preserving, standalone commit)

**Files:**
- Move: `tests/data/withers_aberdeen/assessment_workdir/` -> `tests/data/assessment_corpora/withers/`
- Modify: `tests/measure_withers_assessment.py:68` (`_WORKDIR` constant)
- Modify: `tests/data/withers_aberdeen/README.md` (pointer)

- [ ] **Step 3.1: git mv**

```bash
mkdir -p tests/data/assessment_corpora
git mv tests/data/withers_aberdeen/assessment_workdir tests/data/assessment_corpora/withers
```

- [ ] **Step 3.2: Re-point the measurement script's workdir constant**

In `tests/measure_withers_assessment.py` change:

```python
_WORKDIR = _DATA / "withers_aberdeen" / "assessment_workdir"
```
to:
```python
_WORKDIR = _DATA / "assessment_corpora" / "withers"
```

In `tests/data/withers_aberdeen/README.md`, update the line that says
`pipeline workdir in `assessment_workdir/`` to
`pipeline workdir now frozen at `tests/data/assessment_corpora/withers/``,
and update the Output block path
`tests/data/withers_aberdeen/assessment_workdir/` likewise.

- [ ] **Step 3.3: Verify nothing else references the old path**

Run: Grep for `assessment_workdir` across the repo.
Expected: only hits in `docs/plans/` design/history docs (leave those — they record history) and this plan. No hits in `src/` or executable `tests/` code.

- [ ] **Step 3.4: Commit the move alone**

```bash
git add -A
git commit -m "refactor: move Withers assessment workdir to tests/data/assessment_corpora/withers (design SS7)"
```

### Task 4: Corpus builder — Withers (claim_id, ground_truth.csv, cassette)

**Files:**
- Create: `tests/build_assessment_corpora.py`
- Create: `tests/test_assessment_corpora.py`
- Generated: `tests/data/assessment_corpora/withers/{claims.csv,ground_truth.csv,jobs/assess_results.jsonl}`

- [ ] **Step 4.1: Write failing structural tests for the withers corpus**

```python
# tests/test_assessment_corpora.py
"""Structural invariants for the frozen assessment corpora (design SS7).

Each corpus is a conforming workdir: claims.csv (with stable claim_id),
opinions/, ground_truth.csv, jobs/assess_results.jsonl. These tests are
offline and run against committed data only.
"""
import csv
import json
from pathlib import Path

import pytest

from citation_verifier.executor import load_verdicts_jsonl

CORPORA = Path(__file__).parent / "data" / "assessment_corpora"
PROMPT_VERSION = "assess-v1"
CORPUS_NAMES = ["withers", "payne", "wainwright"]

# Claims in these states never get an agent verdict (deterministic lanes).
LOCATED = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
           "VERIFIED_DOCKET_ONLY", "CITE_UNCONFIRMED"}


def load_claims(name):
    path = CORPORA / name / "claims.csv"
    return list(csv.DictReader(path.open(encoding="utf-8")))


def load_ground_truth(name):
    path = CORPORA / name / "ground_truth.csv"
    return list(csv.DictReader(path.open(encoding="utf-8")))


@pytest.mark.parametrize("name", CORPUS_NAMES)
class TestCorpusStructure:
    def test_files_exist(self, name):
        d = CORPORA / name
        assert (d / "claims.csv").is_file()
        assert (d / "ground_truth.csv").is_file()
        assert (d / "jobs" / "assess_results.jsonl").is_file()
        assert (d / "opinions").is_dir()

    def test_claim_ids_unique_and_prefixed(self, name):
        ids = [c["claim_id"] for c in load_claims(name)]
        assert len(ids) == len(set(ids))
        assert all(i.startswith(name + "-") for i in ids)

    def test_opinion_files_exist(self, name):
        d = CORPORA / name
        for c in load_claims(name):
            if c.get("opinion_file"):
                assert (d / c["opinion_file"]).is_file(), c["claim_id"]

    def test_ground_truth_covers_all_claims(self, name):
        gt_ids = {g["claim_id"] for g in load_ground_truth(name)}
        for c in load_claims(name):
            assert c["claim_id"] in gt_ids

    def test_cassette_covers_agent_assessable_claims(self, name):
        verdicts = load_verdicts_jsonl(
            CORPORA / name / "jobs" / "assess_results.jsonl")
        assert all(v.prompt_version == PROMPT_VERSION for v in verdicts)
        assert all(v.fields.get("assessment") in ("Green", "Yellow", "Red")
                   for v in verdicts)
        recorded = {v.claim_id for v in verdicts}
        for c in load_claims(name):
            needs_agent = (bool(c.get("opinion_file"))
                           and c.get("cl_status") != "WRONG_CASE")
            if needs_agent:
                assert c["claim_id"] in recorded, c["claim_id"]


class TestWithersSpecifics:
    def test_row_counts(self):
        assert len(load_claims("withers")) == 34
        assert len(load_ground_truth("withers")) == 54  # full exhibit

    def test_ground_truth_scale_and_labels(self):
        gt = load_ground_truth("withers")
        assert all(g["scale"] == "withers_exhibit" for g in gt)
        labels = {g["expected"] for g in gt}
        assert labels == {"green", "yellow", "red"}
```

- [ ] **Step 4.2: Run, verify failure mode**

Run: `venv/Scripts/python.exe -m pytest tests/test_assessment_corpora.py -v`
Expected: FAIL — withers claims.csv has no `claim_id` column (KeyError) and `ground_truth.csv` / `jobs/` don't exist; payne/wainwright corpora missing entirely (FileNotFoundError). All failures, no passes.

- [ ] **Step 4.3: Write the builder script (withers part)**

```python
# tests/build_assessment_corpora.py
"""Build/refresh the frozen assessment corpora (design SS7).

Idempotent: safe to rerun. Each corpus directory under
tests/data/assessment_corpora/ becomes a conforming pipeline workdir:

  claims.csv                 input + deterministic-phase columns + claim_id
  opinions/                  downloaded opinion texts
  ground_truth.csv           expected verdicts + provenance
  jobs/assess_results.jsonl  recorded live LLM verdicts (the cassette)

Sources (all committed):
  withers     workdir frozen from the 2026-06-11 measurement run
              (tests/measure_withers_assessment.py); ground truth from
              withers_aberdeen_corpus.csv via withers_baseline_results.csv;
              cassette from withers_assessment_runs.jsonl (agent rows only;
              deterministic lanes are recomputed by scoring, not recorded).
  payne       claims rows + opinions from briefs/payne-proposed/ selected by
              tests/ab_test_cases.json; cassette from the recorded opus run
              tests/data/results/ab_opus-baseline_20260323-002228.jsonl.
  wainwright  same, from briefs/wainwright-v-state/.

prompt_version "assess-v1" = the established single-claim assessment prompt
(identical criteria text in ab_test_runner.build_prompt and
measure_withers_assessment.build_prompt).

Usage:
    venv/Scripts/python.exe tests/build_assessment_corpora.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from citation_verifier.executor import Verdict, append_verdict_jsonl

DATA = Path(__file__).parent / "data"
CORPORA = DATA / "assessment_corpora"
PROMPT_VERSION = "assess-v1"

# Mirrors measure_withers_assessment.py's sample definition.
GREEN_SAMPLE = [
    "withers-01", "withers-07", "withers-21", "withers-39", "withers-26",
    "withers-36", "withers-46", "withers-11", "withers-20", "withers-30",
    "withers-50", "withers-29",
]

AB_SOURCE_DIRS = {
    "payne": Path("briefs/payne-proposed"),
    "wainwright": Path("briefs/wainwright-v-state"),
}
AB_OPUS_RUN = DATA / "results" / "ab_opus-baseline_20260323-002228.jsonl"


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_cassette(path: Path, verdicts: list[Verdict]) -> None:
    if path.exists():
        path.unlink()
    for v in verdicts:
        append_verdict_jsonl(path, v)


# ---------------------------------------------------------------------------
# Withers
# ---------------------------------------------------------------------------

def build_withers() -> None:
    corpus = CORPORA / "withers"
    baseline = list(csv.DictReader(
        (DATA / "withers_baseline_results.csv").open(encoding="utf-8")))

    # Replay the measurement sample selection to recover row_id per claim row.
    sample = [r for r in baseline
              if r["label"] in ("yellow", "red") or r["row_id"] in GREEN_SAMPLE]

    claims = list(csv.DictReader((corpus / "claims.csv").open(encoding="utf-8")))
    assert len(claims) == len(sample), (len(claims), len(sample))

    if "claim_id" not in claims[0]:
        stamped = []
        for s, c in zip(sample, claims):
            assert c["proposition"] == s["proposition"], s["row_id"]
            assert c["cited_case"] == s["citation"], s["row_id"]
            stamped.append({"claim_id": s["row_id"], **c})
        write_csv(corpus / "claims.csv", stamped)
        print(f"withers: stamped claim_id on {len(stamped)} claims")
    else:
        print("withers: claim_id already present")

    # Ground truth: ALL 54 exhibit rows (the workdir holds 34; scoring only
    # scores rows present in claims.csv, the rest await corpus expansion).
    gt = [{
        "claim_id": r["row_id"],
        "scale": "withers_exhibit",
        "expected": r["label"],
        "exists": r["exists"],
        "hedged": r["hedged"],
        "notes": r["irregularity"],
        "provenance": "exhibit1_doc112-1.pdf via withers_aberdeen_corpus.csv",
    } for r in baseline]
    write_csv(corpus / "ground_truth.csv", gt)
    print(f"withers: ground_truth.csv {len(gt)} rows")

    # Cassette: agent rows only. Deterministic lanes (WRONG_CASE -> Red,
    # no-text -> Gray, located-no-opinion -> Yellow) are recomputed from
    # claims.csv state by the scorer -- they are not LLM verdicts.
    runs = [json.loads(line) for line in
            (DATA / "withers_assessment_runs.jsonl").open(encoding="utf-8")]
    verdicts = [Verdict(
        claim_id=r["row_id"],
        fields={"assessment": r["predicted"], "rationale": r["rationale"]},
        model="opus",
        prompt_version=PROMPT_VERSION,
        elapsed_s=r.get("elapsed_s", 0.0),
        cost_usd=r.get("cost_usd", 0.0),
    ) for r in runs if r.get("mode") == "agent" and r.get("predicted")]
    write_cassette(corpus / "jobs" / "assess_results.jsonl", verdicts)
    print(f"withers: cassette {len(verdicts)} agent verdicts")


# ---------------------------------------------------------------------------
# Payne / Wainwright (from ab_test_cases.json + recorded opus run)
# ---------------------------------------------------------------------------

def build_ab_corpus(source: str) -> None:
    corpus = CORPORA / source
    src_dir = AB_SOURCE_DIRS[source]
    cases = [c for c in json.loads(
        (Path(__file__).parent / "ab_test_cases.json").read_text(
            encoding="utf-8"))["cases"] if c["source"] == source]
    src_claims = list(csv.DictReader(
        (src_dir / "claims.csv").open(encoding="utf-8")))

    (corpus / "opinions").mkdir(parents=True, exist_ok=True)
    (corpus / "jobs").mkdir(exist_ok=True)

    rows = []
    for case in sorted(cases, key=lambda c: c["id"]):
        row = src_claims[case["id"]]
        # ab_test_cases.json ids are row indices into the brief's claims.csv
        # (verified 2026-06-11: 61/61 match on cited_case AND opinion_file).
        assert row["cited_case"] == case["cited_case"], (source, case["id"])
        assert row.get("opinion_file", "") == case["opinion_file"]
        claim_id = f"{source}-{case['id']:02d}"
        out = {"claim_id": claim_id, **row}
        out.setdefault("syllabus", "")
        out.setdefault("brief_sentence", "")
        rows.append(out)
        opinion = src_dir / case["opinion_file"]
        dest = corpus / case["opinion_file"]
        if not dest.exists():
            shutil.copy2(opinion, dest)
    write_csv(corpus / "claims.csv", rows)
    print(f"{source}: claims.csv {len(rows)} rows, "
          f"{len(list((corpus / 'opinions').iterdir()))} opinions")

    gt = [{
        "claim_id": f"{source}-{c['id']:02d}",
        "scale": "internal",
        "expected": c["expected_assessment"],
        "exists": "",
        "hedged": "",
        "notes": c.get("notes", ""),
        "provenance": "ab_test_cases.json (human-reviewed ledger)",
    } for c in sorted(cases, key=lambda c: c["id"])]
    write_csv(corpus / "ground_truth.csv", gt)
    print(f"{source}: ground_truth.csv {len(gt)} rows")

    # Cassette from the recorded opus baseline. case_id alone is ambiguous
    # across sources (ids overlap); key by (case_id, cited_case).
    by_key = {(c["id"], c["cited_case"]): c for c in cases}
    verdicts = []
    for line in AB_OPUS_RUN.open(encoding="utf-8"):
        r = json.loads(line)
        case = by_key.get((r["case_id"], r["cited_case"]))
        if case is None:
            continue  # belongs to the other source
        verdicts.append(Verdict(
            claim_id=f"{source}-{case['id']:02d}",
            fields={"assessment": r["actual"], "rationale": r["rationale"]},
            model=r.get("model", "opus"),
            prompt_version=PROMPT_VERSION,
            elapsed_s=r.get("elapsed_s", 0.0),
            cost_usd=r.get("cost_usd", 0.0),
        ))
    assert len(verdicts) == len(cases), (source, len(verdicts), len(cases))
    write_cassette(corpus / "jobs" / "assess_results.jsonl", verdicts)
    print(f"{source}: cassette {len(verdicts)} verdicts")


def main() -> None:
    build_withers()
    for source in AB_SOURCE_DIRS:
        build_ab_corpus(source)
    print("done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.4: Run the builder**

Run: `venv/Scripts/python.exe tests/build_assessment_corpora.py`
Expected output (ASCII):
```
withers: stamped claim_id on 34 claims
withers: ground_truth.csv 54 rows
withers: cassette 29 agent verdicts
payne: claims.csv 27 rows, 2X opinions
payne: ground_truth.csv 27 rows
payne: cassette 27 verdicts
wainwright: claims.csv 34 rows, 2X opinions
wainwright: ground_truth.csv 34 rows
wainwright: cassette 34 verdicts
done
```
(Opinion counts are "number of distinct opinion files referenced by ground-truth rows" — verify they equal `len({c['opinion_file'] for c in cases})` per source.)

- [ ] **Step 4.5: Rerun builder to prove idempotence**

Run: `venv/Scripts/python.exe tests/build_assessment_corpora.py`
Expected: same output except `withers: claim_id already present`; `git status` shows no modified files after the second run.

- [ ] **Step 4.6: Run the structural tests, verify all pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_assessment_corpora.py -v`
Expected: all PASS

- [ ] **Step 4.7: Commit (corpora are data — commit them all per CLAUDE.md)**

```bash
git add tests/build_assessment_corpora.py tests/test_assessment_corpora.py tests/data/assessment_corpora tests/measure_withers_assessment.py tests/data/withers_aberdeen/README.md
git commit -m "data: frozen assessment corpora (withers/payne/wainwright) + builder + structural tests (design SS7)"
```

### Task 5: §6.9 color function (pure, TDD)

**Files:**
- Create: `src/citation_verifier/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 5.1: Write failing tests — one per row of the §6.9 table**

```python
# tests/test_scoring.py
"""Tests for the two-axis scoring module (design SS6.9 / SS8)."""
import pytest

from citation_verifier.scoring import derive_color


class TestDeriveColor:
    """The SS6.9 color table: color is a documented function of
    (existence, support, quote)."""

    @pytest.mark.parametrize("existence", [
        "NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"])
    def test_unlocatable_is_gray(self, existence):
        assert derive_color(existence, "supported", "VERBATIM") == "Gray"

    def test_wrong_case_is_red(self):
        assert derive_color("WRONG_CASE", "supported", "VERBATIM") == "Red"

    def test_cite_unconfirmed_is_check_cite_never_red(self):
        assert derive_color("CITE_UNCONFIRMED", "unsupported",
                            "FABRICATED") == "CheckCite"

    @pytest.mark.parametrize("quote", ["VERBATIM", "NO_QUOTES", None, ""])
    def test_verified_supported_clean_quotes_is_green(self, quote):
        assert derive_color("VERIFIED", "supported", quote) == "Green"

    @pytest.mark.parametrize("quote", ["CLOSE", "FABRICATED"])
    def test_verified_supported_bad_quote_floors_to_yellow(self, quote):
        assert derive_color("VERIFIED", "supported", quote) == "Yellow"

    def test_verified_partial_support_is_yellow(self):
        assert derive_color("VERIFIED_PARTIAL", "partial", "VERBATIM") == "Yellow"

    def test_verified_unsupported_is_red(self):
        assert derive_color("VERIFIED", "unsupported", "VERBATIM") == "Red"

    def test_verified_unverifiable_support_is_gray(self):
        assert derive_color("VERIFIED", "unverifiable", None) == "Gray"

    @pytest.mark.parametrize("existence", [
        "VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
        "VERIFIED_DOCKET_ONLY"])
    def test_all_verified_family_members_use_support_axis(self, existence):
        assert derive_color(existence, "unsupported", None) == "Red"
```

- [ ] **Step 5.2: Run, verify fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation_verifier.scoring'`

- [ ] **Step 5.3: Implement derive_color**

```python
# src/citation_verifier/scoring.py
"""Two-axis scoring for the proposition pipeline (design SS6.9 / SS8).

Every claim carries three independent verdicts -- existence (verifier
status), support (supported|partial|unsupported|unverifiable), quote
(worst per-quote verdict). Report color is a documented pure function of
the three (derive_color). Scoring against external audits uses a
documented per-scale mapping (score_workdir): the Withers exhibit's
colors encode existence, ours encode support severity, so exhibit-yellow
matches our {Yellow, Red} and exhibit-red matches our existence lanes.

Offline by default: predictions replay a recorded cassette through
RecordedExecutor over a frozen corpus workdir
(tests/data/assessment_corpora/<name>/).
"""
from __future__ import annotations

GREEN = "Green"
YELLOW = "Yellow"
RED = "Red"
GRAY = "Gray"
CHECK_CITE = "CheckCite"

UNLOCATABLE = {"NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"}
LOCATED = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
           "VERIFIED_DOCKET_ONLY", "CITE_UNCONFIRMED"}
_BAD_QUOTES = {"CLOSE", "FABRICATED"}


def derive_color(existence: str, support: str | None = None,
                 quote_worst: str | None = None) -> str:
    """SS6.9: report color as a function of the three axes."""
    if existence in UNLOCATABLE:
        return GRAY
    if existence == "WRONG_CASE":
        return RED
    if existence == "CITE_UNCONFIRMED":
        return CHECK_CITE  # amber lane -- never Red
    # VERIFIED family: the support axis decides, quote floors apply.
    if support == "unsupported":
        return RED
    if support == "partial":
        return YELLOW
    if support == "supported":
        if quote_worst in _BAD_QUOTES:
            return YELLOW
        return GREEN
    return GRAY  # unverifiable / missing support axis
```

- [ ] **Step 5.4: Run, verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_scoring.py -v`
Expected: all PASS

- [ ] **Step 5.5: Commit**

```bash
git add src/citation_verifier/scoring.py tests/test_scoring.py
git commit -m "feat: SS6.9 two-axis color function (derive_color)"
```

### Task 6: predict_workdir + score_workdir + CLI

**Files:**
- Modify: `src/citation_verifier/scoring.py` (append)
- Modify: `tests/test_scoring.py` (append)

The recorded `assess-v1` cassettes are single-color verdicts (the legacy
prompt predates the two-axis schema), so prediction for a frozen corpus is:
deterministic existence lanes from claims.csv state, else the recorded
agent color. `derive_color` is exercised by later steps (two-axis prompts);
here it ships tested and ready.

- [ ] **Step 6.1: Write failing tests against a synthetic mini-workdir**

```python
# append to tests/test_scoring.py
import csv
import json
from pathlib import Path

from citation_verifier.executor import (
    RecordedExecutor, Verdict, append_verdict_jsonl)
from citation_verifier.scoring import (
    predict_workdir, score_workdir)


def make_workdir(tmp_path):
    """Synthetic 4-claim corpus exercising every deterministic lane."""
    wd = tmp_path / "corpus"
    (wd / "opinions").mkdir(parents=True)
    (wd / "jobs").mkdir()
    (wd / "opinions" / "A.html").write_text("opinion A", encoding="utf-8")
    claims = [
        # agent lane: located with opinion text
        {"claim_id": "t-01", "cl_status": "VERIFIED",
         "opinion_file": "opinions/A.html"},
        # deterministic: WRONG_CASE -> Red
        {"claim_id": "t-02", "cl_status": "WRONG_CASE", "opinion_file": ""},
        # deterministic: not located, no text -> Gray
        {"claim_id": "t-03", "cl_status": "NOT_FOUND", "opinion_file": ""},
        # deterministic: located but no opinion text -> Yellow
        {"claim_id": "t-04", "cl_status": "VERIFIED", "opinion_file": ""},
    ]
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["claim_id", "cl_status",
                                          "opinion_file"])
        w.writeheader()
        w.writerows(claims)
    gt = [
        {"claim_id": "t-01", "scale": "internal", "expected": "Yellow"},
        {"claim_id": "t-02", "scale": "internal", "expected": "Red"},
        {"claim_id": "t-03", "scale": "internal", "expected": "Green"},
        {"claim_id": "t-04", "scale": "internal", "expected": "Yellow"},
    ]
    with (wd / "ground_truth.csv").open("w", newline="",
                                        encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["claim_id", "scale", "expected"])
        w.writeheader()
        w.writerows(gt)
    append_verdict_jsonl(
        wd / "jobs" / "assess_results.jsonl",
        Verdict(claim_id="t-01",
                fields={"assessment": "Yellow", "rationale": "r"},
                model="opus", prompt_version="assess-v1"))
    return wd


class TestPredictWorkdir:
    def test_lanes_and_agent_replay(self, tmp_path):
        wd = make_workdir(tmp_path)
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Yellow"
        assert preds["t-01"].mode == "agent"
        assert preds["t-02"].predicted == "Red"
        assert preds["t-02"].mode == "deterministic"
        assert preds["t-03"].predicted == "Gray"
        assert preds["t-04"].predicted == "Yellow"
        assert preds["t-04"].mode == "deterministic"


class TestScoreWorkdir:
    def test_internal_scale_exact_match(self, tmp_path):
        wd = make_workdir(tmp_path)
        report = score_workdir(wd)
        assert report.total == 4
        # t-01 Yellow==Yellow, t-02 Red==Red, t-04 Yellow==Yellow correct;
        # t-03 Gray vs Green incorrect
        assert report.correct == 3
        wrong = [r for r in report.rows if not r["correct"]]
        assert [r["claim_id"] for r in wrong] == ["t-03"]

    def test_withers_scale_mapping(self, tmp_path):
        wd = make_workdir(tmp_path)
        # rewrite ground truth on the exhibit scale
        gt = [
            # exhibit yellow caught by our Yellow
            {"claim_id": "t-01", "scale": "withers_exhibit",
             "expected": "yellow"},
            # exhibit red caught by Red-via-WRONG_CASE
            {"claim_id": "t-02", "scale": "withers_exhibit",
             "expected": "red"},
            # exhibit green, we said Gray -> unable (not over-flagged,
            # not exact)
            {"claim_id": "t-03", "scale": "withers_exhibit",
             "expected": "green"},
            # exhibit green, we said Yellow -> over-flagged
            {"claim_id": "t-04", "scale": "withers_exhibit",
             "expected": "green"},
        ]
        with (wd / "ground_truth.csv").open("w", newline="",
                                            encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["claim_id", "scale",
                                              "expected"])
            w.writeheader()
            w.writerows(gt)
        report = score_workdir(wd)
        assert report.yellows_total == 1
        assert report.yellows_caught == 1
        assert report.reds_total == 1
        assert report.reds_caught == 1
        assert report.greens_total == 2
        assert report.greens_exact == 0
        assert report.greens_overflagged == 1
```

- [ ] **Step 6.2: Run, verify fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_scoring.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'predict_workdir'`

- [ ] **Step 6.3: Implement prediction + scoring + CLI**

```python
# append to src/citation_verifier/scoring.py
import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

from .executor import Job, LLMExecutor, RecordedExecutor

DEFAULT_PROMPT_VERSION = "assess-v1"

# Exhibit-scale mapping (SS6.9): the Withers exhibit's colors encode
# existence, ours encode support severity.
#   exhibit yellow ~= our {Yellow, Red} on a real case
#   exhibit red    ~= our {WRONG_CASE-Red, NOT_FOUND-Gray, CheckCite}
_EXHIBIT_YELLOW_CAUGHT = {YELLOW, RED}
_EXHIBIT_RED_CAUGHT = {RED, GRAY, CHECK_CITE}


@dataclass
class ClaimPrediction:
    claim_id: str
    predicted: str
    mode: str  # "deterministic" | "agent"
    rationale: str = ""


def predict_workdir(workdir: str | Path, executor: LLMExecutor,
                    prompt_version: str = DEFAULT_PROMPT_VERSION,
                    ) -> list[ClaimPrediction]:
    """Predict a color per claim in a conforming workdir.

    Deterministic existence lanes are computed from claims.csv state
    (mirroring the 2026-06-11 measurement script); everything else gets
    the executor's verdict. With RecordedExecutor this is fully offline.
    """
    workdir = Path(workdir)
    claims = list(csv.DictReader(
        (workdir / "claims.csv").open(encoding="utf-8")))
    preds: list[ClaimPrediction] = []
    agent_claims: list[dict] = []
    for c in claims:
        status = c.get("cl_status", "")
        has_opinion = bool(c.get("opinion_file"))
        if status == "WRONG_CASE":
            preds.append(ClaimPrediction(
                c["claim_id"], RED, "deterministic",
                "WRONG_CASE -- citation resolves to a different case"))
        elif not has_opinion and status not in LOCATED:
            preds.append(ClaimPrediction(
                c["claim_id"], GRAY, "deterministic",
                f"{status or 'unmatched'} and no opinion text"))
        elif not has_opinion:
            preds.append(ClaimPrediction(
                c["claim_id"], YELLOW, "deterministic",
                f"{status} but opinion text not available"))
        else:
            agent_claims.append(c)
    if agent_claims:
        jobs = [Job(job_id=f"assess-{c['claim_id']}",
                    claim_ids=[c["claim_id"]],
                    prompt="",  # replay keys on (claim_id, prompt_version)
                    prompt_version=prompt_version,
                    files=[c["opinion_file"]])
                for c in agent_claims]
        for v in executor.run(jobs):
            preds.append(ClaimPrediction(
                v.claim_id, v.fields["assessment"], "agent",
                v.fields.get("rationale", "")))
    order = {c["claim_id"]: i for i, c in enumerate(claims)}
    preds.sort(key=lambda p: order[p.claim_id])
    return preds


@dataclass
class CorpusScore:
    rows: list[dict] = field(default_factory=list)
    # internal scale
    total: int = 0
    correct: int = 0
    # withers_exhibit scale
    yellows_total: int = 0
    yellows_caught: int = 0
    yellows_exact: int = 0
    greens_total: int = 0
    greens_exact: int = 0
    greens_overflagged: int = 0
    reds_total: int = 0
    reds_caught: int = 0


def score_workdir(workdir: str | Path,
                  executor: LLMExecutor | None = None,
                  prompt_version: str = DEFAULT_PROMPT_VERSION,
                  ) -> CorpusScore:
    """Score predictions against the workdir's ground_truth.csv.

    Ground-truth rows absent from claims.csv are skipped (e.g. the Withers
    exhibit has 54 rows; the frozen workdir holds the 34-row measurement
    sample). Default executor replays jobs/assess_results.jsonl.
    """
    workdir = Path(workdir)
    if executor is None:
        executor = RecordedExecutor(workdir / "jobs" / "assess_results.jsonl")
    preds = {p.claim_id: p for p in
             predict_workdir(workdir, executor, prompt_version)}
    gt = list(csv.DictReader(
        (workdir / "ground_truth.csv").open(encoding="utf-8")))

    score = CorpusScore()
    for g in gt:
        p = preds.get(g["claim_id"])
        if p is None:
            continue  # ground truth beyond the frozen workdir's sample
        row = {"claim_id": g["claim_id"], "scale": g["scale"],
               "expected": g["expected"], "predicted": p.predicted,
               "mode": p.mode}
        if g["scale"] == "internal":
            score.total += 1
            row["correct"] = p.predicted == g["expected"]
            score.correct += row["correct"]
        elif g["scale"] == "withers_exhibit":
            label = g["expected"]
            if label == "yellow":
                score.yellows_total += 1
                row["correct"] = p.predicted in _EXHIBIT_YELLOW_CAUGHT
                score.yellows_caught += row["correct"]
                score.yellows_exact += p.predicted == YELLOW
            elif label == "green":
                score.greens_total += 1
                row["correct"] = p.predicted == GREEN
                score.greens_exact += row["correct"]
                score.greens_overflagged += p.predicted in (YELLOW, RED)
            elif label == "red":
                score.reds_total += 1
                row["correct"] = p.predicted in _EXHIBIT_RED_CAUGHT
                score.reds_caught += row["correct"]
        else:
            raise ValueError(f"unknown ground-truth scale: {g['scale']!r}")
        score.rows.append(row)
    return score


def format_report(name: str, score: CorpusScore) -> str:
    """ASCII summary (Windows-console safe)."""
    lines = [f"=== {name} ==="]
    if score.total:
        lines.append(f"internal scale: {score.correct}/{score.total} exact "
                     f"({score.correct / score.total:.0%})")
    if score.yellows_total or score.greens_total or score.reds_total:
        lines.append(
            f"exhibit scale: yellows caught {score.yellows_caught}/"
            f"{score.yellows_total} ({score.yellows_exact} exact); "
            f"greens exact {score.greens_exact}/{score.greens_total} "
            f"({score.greens_overflagged} over-flagged); "
            f"reds caught {score.reds_caught}/{score.reds_total}")
    misses = [r for r in score.rows if not r.get("correct")]
    for r in misses:
        lines.append(f"  MISS {r['claim_id']}: expected {r['expected']}, "
                     f"predicted {r['predicted']} ({r['mode']})")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score a frozen assessment corpus offline "
                    "(replays jobs/assess_results.jsonl).")
    ap.add_argument("workdir", nargs="+",
                    help="corpus workdir(s), e.g. "
                         "tests/data/assessment_corpora/withers")
    ap.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    args = ap.parse_args()
    for wd in args.workdir:
        score = score_workdir(wd, prompt_version=args.prompt_version)
        print(format_report(Path(wd).name, score))


if __name__ == "__main__":
    main()
```

Note: the `import argparse`/`csv`/dataclass/Path lines belong at the top of
`scoring.py` with the existing imports — merge them there rather than
mid-file.

- [ ] **Step 6.4: Run, verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_scoring.py -v`
Expected: all PASS

- [ ] **Step 6.5: Commit**

```bash
git add src/citation_verifier/scoring.py tests/test_scoring.py
git commit -m "feat: offline corpus scoring (predict_workdir/score_workdir + CLI)"
```

### Task 7: Offline regression test — reproduce both committed baselines

**Files:**
- Create: `tests/test_assessment_regression.py`

- [ ] **Step 7.1: Cross-check the scorer against the measurement run (one-off, not committed)**

Run:
```bash
venv/Scripts/python.exe -c "
import csv
from pathlib import Path
from citation_verifier.scoring import score_workdir
score = score_workdir('tests/data/assessment_corpora/withers')
mine = {r['claim_id']: r['predicted'] for r in score.rows}
old = {r['row_id']: r['predicted'] for r in csv.DictReader(
    Path('tests/data/withers_assessment_results.csv').open(encoding='utf-8'))}
diff = {k: (old[k], mine[k]) for k in old if mine.get(k) != old[k]}
print('per-row diffs vs measurement run:', diff or 'NONE')
"
```
Expected: `NONE`. If any row differs, STOP — the deterministic-lane logic or cassette conversion drifted from the measurement script; reconcile before writing the regression test (the regression numbers below assume row-for-row agreement).

- [ ] **Step 7.2: Write the regression test (numbers from the committed baselines)**

```python
# tests/test_assessment_regression.py
"""Offline regression: the frozen corpora + recorded cassettes must keep
reproducing the two committed acceptance baselines (design SS8).

  1. Withers assessment baseline (2026-06-11, README second table):
     12/19 yellows caught, 7 missed, greens 9 exact / 2 over-flagged,
     reds 1 Red + 2 Gray.
  2. A/B opus baseline (ab_opus-baseline_20260323-002228.jsonl):
     payne 21/27, wainwright 33/34 -> 54/61 (88.5%, >= the 85% target).

No network, no LLM: RecordedExecutor replay only. A prompt-template change
bumps the version key and makes these tests fail loudly via
RecordedVerdictMiss -- that is the cassette policy working as intended:
re-record live, update the numbers deliberately.
"""
from pathlib import Path

from citation_verifier.scoring import score_workdir

CORPORA = Path(__file__).parent / "data" / "assessment_corpora"


class TestWithersBaseline:
    def test_reproduces_2026_06_11_assessment_baseline(self):
        s = score_workdir(CORPORA / "withers")
        assert s.yellows_total == 19
        assert s.yellows_caught == 12
        assert s.yellows_exact == 6
        assert s.greens_total == 12
        assert s.greens_exact == 9
        assert s.greens_overflagged == 2
        assert s.reds_total == 3
        assert s.reds_caught == 3  # 1 Red via WRONG_CASE + 2 Gray

    def test_known_misses_are_stable(self):
        s = score_workdir(CORPORA / "withers")
        missed = sorted(r["claim_id"] for r in s.rows
                        if r["expected"] == "yellow" and not r["correct"])
        assert missed == ["withers-05", "withers-09", "withers-12",
                          "withers-32", "withers-38", "withers-44",
                          "withers-49"]


class TestABOpusBaseline:
    def test_payne(self):
        s = score_workdir(CORPORA / "payne")
        assert (s.correct, s.total) == (21, 27)

    def test_wainwright(self):
        s = score_workdir(CORPORA / "wainwright")
        assert (s.correct, s.total) == (33, 34)

    def test_no_lenient_direction_errors_recorded(self):
        """SS8.2: the recorded baseline's wrong answers are all in the
        strict direction (predicted more severe than expected). New runs
        get compared against this property."""
        rank = {"Green": 0, "Yellow": 1, "Red": 2}
        for name in ("payne", "wainwright"):
            s = score_workdir(CORPORA / name)
            lenient = [r for r in s.rows if not r["correct"]
                       and rank[r["predicted"]] < rank[r["expected"]]]
            assert lenient == [], name
```

Caveat on `test_no_lenient_direction_errors_recorded`: verify the premise
first (the recorded run may contain lenient misses). Run step 7.1's pattern:

```bash
venv/Scripts/python.exe -c "
from citation_verifier.scoring import score_workdir
rank = {'Green': 0, 'Yellow': 1, 'Red': 2}
for n in ('payne', 'wainwright'):
    s = score_workdir(f'tests/data/assessment_corpora/{n}')
    for r in s.rows:
        if not r['correct'] and rank[r['predicted']] < rank[r['expected']]:
            print('LENIENT MISS', n, r)
"
```
If lenient misses exist in the recording, change that test to pin the exact
set (e.g. `assert lenient_ids == [...]`) instead of asserting empty — the
§8 target is "no NEW lenient errors", so the recorded set is the allowed
baseline. Document whichever form ships in the test docstring.

- [ ] **Step 7.3: Run, verify pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_assessment_regression.py -v`
Expected: all PASS

- [ ] **Step 7.4: Try the CLI end-to-end**

Run: `venv/Scripts/python.exe -m citation_verifier.scoring tests/data/assessment_corpora/withers tests/data/assessment_corpora/payne tests/data/assessment_corpora/wainwright`
Expected: three ASCII report blocks; withers shows `yellows caught 12/19 (6 exact)`; payne `21/27`; wainwright `33/34`.

- [ ] **Step 7.5: Run the whole suite**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py tests/test_scoring.py tests/test_assessment_corpora.py tests/test_assessment_regression.py tests/test_verifier.py tests/test_brief_pipeline.py -q`
Expected: all PASS

- [ ] **Step 7.6: Commit**

```bash
git add tests/test_assessment_regression.py
git commit -m "test: offline regression reproducing Withers 12/19 + A/B 54/61 baselines (design SS8)"
```

### Task 8: Documentation + push

**Files:**
- Create: `tests/data/assessment_corpora/README.md`
- Modify: `CLAUDE.md` (Files tables)
- Modify: `tests/data/withers_aberdeen/README.md` (if not already done in Task 3)

- [ ] **Step 8.1: Write the corpora README**

```markdown
# Assessment corpora — frozen workdirs + recorded LLM cassettes

The assessment layer's record/replay harness (design
`docs/plans/2026-06-11-proposition-verifier-pipeline-design.md` SS7),
mirroring `tests/cassette_client.py` for the verifier layer.

Each `<name>/` is a **frozen, conforming pipeline workdir**:

| file | contents |
|---|---|
| `claims.csv` | claims through the deterministic phases (verify/merge/check-quotes), plus a stable `claim_id` (`<corpus>-NN`) |
| `opinions/` | downloaded opinion texts the claims link to |
| `ground_truth.csv` | `claim_id, scale, expected, exists, hedged, notes, provenance` |
| `jobs/assess_results.jsonl` | recorded live LLM verdicts — the cassette, keyed by `(claim_id, prompt_version)` |

**Scales.** `withers_exhibit`: labels are the Withers exhibit author's
green/yellow/red, which encode *existence* (red = hallucinated); scoring
maps exhibit-yellow to our {Yellow, Red} and exhibit-red to our
{Red-via-WRONG_CASE, Gray, CheckCite} (design SS6.9). `internal`: labels
are our own Green/Yellow/Red, scored exact-match.

**Prompt versions.** `assess-v1` = the established single-claim assessment
prompt (identical criteria text in `tests/ab_test_runner.py::build_prompt`
and `tests/measure_withers_assessment.py::build_prompt`). Changing a prompt
template bumps the version, which makes `RecordedExecutor` raise
`RecordedVerdictMiss` — re-record live, update baselines deliberately.

**Corpora:**

| corpus | rows (claims / ground truth) | cassette | source |
|---|---|---|---|
| `withers` | 34 / 54 | 29 opus verdicts (2026-06-11 measurement run) | `tests/data/withers_aberdeen/` (exhibit + baselines) |
| `payne` | 27 / 27 | 27 opus verdicts (`ab_opus-baseline_20260323-002228.jsonl`) | `briefs/payne-proposed/` + `tests/ab_test_cases.json` |
| `wainwright` | 34 / 34 | 34 opus verdicts (same run) | `briefs/wainwright-v-state/` + `tests/ab_test_cases.json` |

`ab_test_cases.json` remains the human-review ledger; `ground_truth.csv`
is generated from it (one scoring path, not two). Rebuild/refresh with
`venv/Scripts/python.exe tests/build_assessment_corpora.py` (idempotent).

**Offline scoring:**

    venv/Scripts/python.exe -m citation_verifier.scoring tests/data/assessment_corpora/withers

Baselines pinned by `tests/test_assessment_regression.py`: Withers 12/19
yellows caught (the redesign targets >= 15/19); A/B 54/61 (>= 85% target).

Candidate additions (SS7): kettering, brooks, maxwell — add
opportunistically when ground truth is recovered from retros.
```

- [ ] **Step 8.2: Update CLAUDE.md**

Add to the Core library files table:

```
| `executor.py` | LLM executor protocol (design SS5): `Job`/`Verdict` dataclasses, `LLMExecutor` Protocol, JSONL verdict serde, `RecordedExecutor` replay adapter (raises `RecordedVerdictMiss` on cassette miss; key = claim_id + prompt_version) |
| `scoring.py` | Two-axis scoring (design SS6.9/SS8): `derive_color()` pure color function, `predict_workdir()`/`score_workdir()` offline corpus scoring, CLI `python -m citation_verifier.scoring <corpus-dir>` |
```

Add to the Tests table:

```
| `test_executor.py` | Executor protocol + RecordedExecutor replay tests |
| `test_scoring.py` | derive_color table + workdir prediction/scoring tests |
| `test_assessment_corpora.py` | Structural invariants of the frozen corpora |
| `test_assessment_regression.py` | Offline baselines: Withers 12/19, A/B 54/61 |
| `build_assessment_corpora.py` | Builds/refreshes `tests/data/assessment_corpora/` (idempotent) |
| `data/assessment_corpora/` | Frozen assessment workdirs + recorded LLM cassettes (see its README) |
```

- [ ] **Step 8.3: Final full-suite run**

Run: `venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_false_negatives.py --ignore=tests/test_cl_api_issues.py -p no:cacheprovider`
Expected: PASS (live-API suites excluded). If other live-marked tests trip without a token, exclude per existing repo convention.

- [ ] **Step 8.4: Commit and push everything**

```bash
git add tests/data/assessment_corpora/README.md CLAUDE.md docs/plans/2026-06-11-prop-pipeline-step1-offline-harness-plan.md
git commit -m "docs: assessment corpora README + CLAUDE.md entries for Step 1 harness"
git push -u origin pipeline-redesign
```

---

## Self-review notes (spec coverage)

- §5 executor protocol: Task 1-2 (Job, Verdict, LLMExecutor, RecordedExecutor + miss-raise). Live adapters explicitly deferred (§10 steps 4-5).
- §7 corpora: Tasks 3-4 (three frozen workdirs, ground_truth generated from `ab_test_cases.json` + exhibit — one scoring path; cassette = recorded verdicts JSONL; re-record policy documented).
- §6.9 two-axis mapping: Task 5 (`derive_color`, full table) + Task 6 (exhibit-scale external mapping in `score_workdir`).
- §8 acceptance baselines: Task 7 pins both before-numbers offline; `measure_withers_assessment.py` re-point is deliberately limited to the `_WORKDIR` path fix (Task 3) — full re-point onto `scoring.score_workdir` happens when the `assess` verb exists (§10 step 4), since the script's live phases still call `brief_pipeline`.
- §3 "every verb CLI + importable": scoring ships as importable functions + `python -m citation_verifier.scoring`; the nine pipeline verbs are §10 step 2+.
- Known deltas from the design text: ab corpus is **61** cases (27+34), not 62; the design's "payne (28)" is actually 27. The plan uses verified counts.

## Execution notes (2026-06-11, all tasks complete)

- Executed as planned; all suites green (358 passed offline).
- **Baseline correction:** the plan's payne 21/27 (54/61 overall) came from
  the recording's own `correct` flags. Two payne cases (ids 16, 75) had
  `expected_assessment` revised in `ab_test_cases.json` after the March
  recording — both to agree with the model's answer. Scored against the
  authoritative current ledger (one scoring path, §7), the recorded
  verdicts give **payne 23/27, overall 56/61 (91.8%)**. Regression test and
  corpora README document this.
- The recorded run contains exactly two lenient-direction misses
  (payne-03 Red->Yellow, payne-58 Yellow->Green); per the Step 7.2 caveat,
  `test_lenient_direction_errors_pinned` pins that exact set.
- Withers offline scorer verified row-for-row identical (diff = NONE) to
  the live measurement run `withers_assessment_results.csv`.

## Subsequent steps (not this session — §10 map)

2. `proposition_pipeline.py` skeleton; verify/merge ported; `matched_name` batch-path bug fixed at the source (§11 bug 1); slug-token linkage; `brief_pipeline` alias.
3. Quote-check extensions (>=2-word spans, CLOSE/FABRICATED floors) — TDD off the withers frozen workdir.
4. AgentToolExecutor (jobs mode) + assess/apply-assessments verbs; prompt templates to `src/citation_verifier/prompts/` (this is when `assess-v2` and re-recording happen).
5. AgentSDKExecutor (strip ANTHROPIC*/CLAUDE* env; drain the async generator on Windows); `extract` verb.
6. crosscheck + triage verbs.
7. Report lanes, SKILL stub, A/B harness re-point.
8. Acceptance runs (§8); retro.
