# Citation Verifier Refactor — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Phase 1 schema rewrite for citation-verifier: replace the four-status `VerificationStatus` and flat `VerificationResult` with the six-status `Status` taxonomy and the new structured `VerificationResult` (`final_ids`, `resolution_path`, `warnings`, `gates_failed`, `timing`, `cache_hit`) from the v2 design, add `ParsedCitation.ecf_document_number`, and migrate every in-repo consumer (verifier core, brief pipeline, CLI, web app, test suite) to the new types in lockstep.

**Architecture:** Clean break, no compatibility shim (per design §5). Phase 1 is purely *schema and types* — no new procedural behavior. The verifier still runs the same three-stage pipeline and produces the same matches; what changes is the *shape* in which those matches are reported. Confidence moves off the top-level `VerificationResult` and onto a single `ResolutionPathEntry` for the resolving stage (the rest of `resolution_path` instrumentation lands in Phase 2). A `headline_confidence` accessor on `VerificationResult` (§2.5) walks the path in reverse so consumers don't have to. The four legacy statuses collapse per the §3 mapping: `VERIFIED`/`LIKELY_REAL`/`POSSIBLE_MATCH` → `VERIFIED` (with the differentiating number now on the stage entry); `NOT_FOUND` → `NOT_FOUND`. The richer states (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`) get their *types* defined here but are *produced* in Phase 3.

**Tech Stack:** Python 3.10+, dataclasses + Enum, pytest, eyecite (PyPI on Windows; editable fork on macOS — see Setup §0.3), CourtListener REST v4 API, FastAPI for the web app.

**Workflow conventions:** Per CLAUDE.md's "Refactor Workflow" section — work in the `.claude/worktrees/refactor-v0.3` worktree, push to `refactor/v0.3` every session, no push to `main` until Phase 4 acceptance, tag this phase as `refactor/phase-1-acceptance` when complete. This plan does not restate those rules; check CLAUDE.md if anything is unclear about per-session discipline.

**Out of scope (do not silently absorb):** Phase 2 (full per-stage path instrumentation with `raw_response_summary` for every attempted stage), Phase 2.5 (corpus assembly), Phase 3 (richer-status detection logic — partial verification, RECAP-only verification, full-caption investigation, WRONG_CASE), Phase 4 (gate evaluation). Phase 1 only emits a single `resolution_path` entry for the resolving stage (carrying the confidence number) and an empty `gates_failed` list. If a task starts to feel like it needs Phase 2+ behavior to ship, flag it as scope creep against this plan, not as a hidden Phase 1 sub-task.

---

## Setup

One-time setup work to do *before* starting Task 1. This is irreducible — Phase 1's acceptance criterion "all existing unit tests pass against new type signatures" cannot be checked without a green baseline to compare against, and the dedicated worktree + branch are required by CLAUDE.md's refactor workflow.

### 0.1 — Branch and worktree

Run these from the existing primary checkout at `C:\Users\Rebecca Fordon\Projects\citation-verifier` (the path the rest of the repo lives under; do *not* run them from the temporary worktree this plan was authored in).

- [ ] **Step 1: Create the refactor branch from main**

```powershell
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier"
git fetch origin
git switch -c refactor/v0.3 origin/main
git push -u origin refactor/v0.3
```

Expected: branch created locally, upstream set to `origin/refactor/v0.3`.

- [ ] **Step 2: Create the dedicated worktree pinned to refactor/v0.3**

```powershell
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier"
git worktree add .claude/worktrees/refactor-v0.3 refactor/v0.3
```

Expected: a new worktree at `.claude\worktrees\refactor-v0.3` checked out on `refactor/v0.3`. All remaining setup and Phase 1 work happens in that worktree. The temporary worktree this plan was drafted in (`gallant-hodgkin-ec573c`) is unrelated and can be torn down with `git worktree remove` at the implementer's convenience.

### 0.2 — Worktree venv

Windows path conventions per CLAUDE.md (`venv/Scripts/python.exe`, not `python` or `python3`).

- [ ] **Step 1: Create the venv inside the new worktree**

```powershell
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\refactor-v0.3"
py -3 -m venv venv
```

Expected: `venv\Scripts\python.exe` exists.

- [ ] **Step 2: Upgrade pip and install citation-verifier as editable**

```powershell
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -e ".[dev,web]"
```

Expected: `pip install` resolves dependencies from `pyproject.toml` (`eyecite>=2.6` pulled from PyPI as part of this), citation-verifier installed editable. The `dev` extra brings in `pytest` and `pdfplumber`; the `web` extra brings in FastAPI + uvicorn + sse-starlette for the web app smoke test in Task 10.

### 0.3 — Editable eyecite install (conditional)

Per CLAUDE.md's Project Overview, eyecite is used as a fork (`rlfordon/eyecite` branch `fix-pdf-metadata-parsing`) with PDF parsing improvements. On the user's macOS machine the fork is installed editable from `/Users/fordon.4/Projects/eyecite`. On the Windows machine this worktree lives on, that path does not exist and the published `eyecite==2.7.6` (already pulled in by Step 0.2.2) is the fallback.

- [ ] **Step 1: Detect whether a local eyecite fork checkout exists; install editable if so**

```powershell
$eyecitePath = "C:\Users\Rebecca Fordon\Projects\eyecite"
if (Test-Path "$eyecitePath\pyproject.toml") {
    venv\Scripts\python.exe -m pip install -e $eyecitePath
    Write-Host "Installed eyecite editable from $eyecitePath"
} else {
    Write-Host "No local eyecite checkout at $eyecitePath; using published eyecite from PyPI (already installed by Step 0.2.2)"
}
```

Expected: either an editable install message naming the fork path, or a "using published eyecite" message. On macOS, replace `$eyecitePath` with `/Users/fordon.4/Projects/eyecite` and use shell equivalents. If neither path matches your machine, edit the script — the rule is "use the local fork if you have one, otherwise the PyPI eyecite is sufficient for this phase." No Phase 1 task depends on a fork-only feature; the PDF-parsing improvements matter for brief ingestion in `verify-brief`, not for the schema work this phase does.

### 0.4 — Baseline green

The repo currently has 5 pre-existing test failures cataloged in `scratch/TODO.md` under "Testing → Test failures (2026-05-17)" — introduced as known issues in commit `252225c`. Without dispositioning them, the Phase 1 acceptance criterion "all existing unit tests pass" is unmeetable, and during the schema migration the implementer will not be able to tell new breakage from pre-existing noise. Decide per test: either fix now (cheap), or mark `@pytest.mark.xfail` with a reason that points back to `scratch/TODO.md`.

The five failures, with disposition:

| # | Test | Disposition | Reason |
|---|------|-------------|--------|
| 1 | `tests/test_report_template.py::TestReportGeneration::test_contains_red_finding` | **Fix now** | 5-minute fixture rename. The test fixture uses `brief_text` and `opinion_text` keys; the template was rewritten (per CLAUDE.md verify-brief notes) to read agent-authored `brief_block` and `opinion_block`. Rename the two fixture keys; the assertion `"anti-abortion protesters" in html` then matches the rendered `opinion_block`. |
| 2 | `tests/test_false_negatives.py::test_known_real_citation[Anderson v. Furst...]` | **xfail** | Cluster-ID drift (CL data drift, not a verifier regression — the verifier still finds a real Anderson cluster, just a different one). Tracked in `scratch/TODO.md`. |
| 3 | `tests/test_false_negatives.py::test_known_real_citation[Bossart v. King Cnty...]` | **xfail** | Same family — cluster-ID drift. |
| 4 | `tests/test_false_negatives.py::test_known_real_citation[Busha v. SC Dep't...]` | **xfail** | Same family — cluster-ID drift. |
| 5 | `tests/test_false_negatives.py::test_known_real_citation[Townsley v. Lifewise...]` | **xfail** | Same family — cluster-ID drift. |

- [ ] **Step 1: Fix `test_contains_red_finding` fixture**

File: `tests/test_report_template.py` — rename the two fixture keys.

Edit `tests/test_report_template.py` lines 24-26 (the `findings[0]` dict):

```python
"brief_block": "Courts hold that prior settlement evidence is irrelevant.",
"opinion_block": "This case is about anti-abortion protesters.",
"explanation": "Complete subject matter mismatch.",
```

(Replace `brief_text` → `brief_block` and `opinion_text` → `opinion_block`. Leave everything else in the fixture unchanged.)

Run: `venv\Scripts\python.exe -m pytest tests/test_report_template.py -v`
Expected: all 9 tests pass.

- [ ] **Step 2: Mark the 4 false-negative cases xfail**

`test_false_negatives.py` is parametrized over the JSON corpus at `tests/data/known_real_citations.json` rather than per-test functions, so the xfail can't be a decorator on a function — it has to be added per-case via the parametrize marker. The minimal change: thread a per-case `xfail` flag through the JSON corpus and apply it inside `test_known_real_citation`.

Edit `tests/data/known_real_citations.json` — add `"xfail_reason"` to each of the 4 drift cases (Anderson, Bossart, Busha, Townsley):

```json
{
  "citation": "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, 2025 WL 459154, at *1 (W.D. Wash. Feb. 11, 2025)",
  "expected_cluster_id": 69346061,
  "category": "abbreviation_normalization",
  "notes": "Cnty. -> County normalization needed for search match. Was false negative before normalization fix.",
  "xfail_reason": "Pre-existing cluster-ID drift; tracked in scratch/TODO.md (Test failures 2026-05-17)"
}
```

(Same shape for Anderson, Busha, Townsley — copy the existing entries and add the `xfail_reason` key. The exact citation strings to match are in `scratch/TODO.md`.)

Edit `tests/test_false_negatives.py:33`, replacing the body of `test_known_real_citation` to honor the flag. Add this near the top of the function (right after `notes = test_case.get("notes", "")`):

```python
    xfail_reason = test_case.get("xfail_reason")
    if xfail_reason:
        pytest.xfail(xfail_reason)
```

Run: `venv\Scripts\python.exe -m pytest tests/test_false_negatives.py -v`
Expected: 1 pass (Obergefell), 4 xfail, 0 fail.

- [ ] **Step 3: Confirm green baseline across the full suite**

```powershell
venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: pass + xfail only. No `FAILED`, no `ERRORS`. If anything else is red, stop and investigate before starting Task 1 — Phase 1's whole acceptance check depends on this being the baseline.

- [ ] **Step 4: Commit the baseline fix**

```powershell
git add tests/test_report_template.py tests/test_false_negatives.py tests/data/known_real_citations.json
git commit -m "test: green-baseline pre-existing failures before refactor v0.3

- Fix test_contains_red_finding fixture to use brief_block/opinion_block
  (template was rewritten for agent-authored blocks per CLAUDE.md).
- xfail 4 false-negative cluster-ID drift cases (Anderson, Bossart, Busha,
  Townsley) via JSON corpus xfail_reason field, tracked in scratch/TODO.md.

Phase 1 of refactor/v0.3 needs a green baseline so new schema-migration
breakage is distinguishable from pre-existing noise."
git push
```

---

## File structure

Files this phase touches, with responsibility per file:

**Created:**
- None. The schema rewrite is in-place in `models.py`.

**Modified (core library):**
- `src/citation_verifier/models.py` — replace `VerificationStatus` enum and `VerificationResult` dataclass with the v2 shapes; add `Status`, `WarningCategory`, `Warning`, `StageName`, `StageVerdict`, `TextSource`, `ResolutionPathEntry`, `FinalIds`, `GateName`, `GateSpec`, `GateFailure`, `BatchVerificationResult`. Add `ecf_document_number: str | None = None` to `ParsedCitation`. Keep `Diagnostic` and `CandidateMatch` unchanged (still used by stage internals; warnings replace diagnostics only at the result boundary).
- `src/citation_verifier/parser.py` — populate `ParsedCitation.ecf_document_number` from `ECF No. N`, `Doc. N`, `Dkt. N`, `Dkt. No. N` patterns (per design §8 open-question disposition).
- `src/citation_verifier/verifier.py` — produce new `VerificationResult` shape. Apply the §3 old→new mapping (`VERIFIED`/`LIKELY_REAL`/`POSSIBLE_MATCH` → `VERIFIED`; `NOT_FOUND` → `NOT_FOUND`). Emit a single `ResolutionPathEntry` for the resolving stage carrying the confidence number. Populate `final_ids` from the matched cluster/docket/RECAP IDs. Convert `Diagnostic` lists into either `Warning` lists (where the category maps cleanly) or leave a stub `notes` field on the stage entry; old-shape `diagnostics` accessor goes away. Expose `headline_confidence` as a property on `VerificationResult` (per design §2.5).
- `src/citation_verifier/brief_pipeline.py` — update every read of `result.status`, `result.confidence`, `result.diagnostics`, `result.matched_*` to the new shape. `_DOWNLOADABLE_STATUSES` collapses from `{VERIFIED, LIKELY_REAL, POSSIBLE_MATCH}` to `{VERIFIED}` (and, type-defined-only-not-produced-this-phase, the four other VERIFIED_* variants — but since Phase 1 never *emits* those, only the bare `VERIFIED` needs to be in the set in practice; include all six "verified-family" statuses in the set so Phase 3 doesn't have to revisit). Update `_visible_text_len` swap logic to mutate `final_ids.absolute_url` instead of `matched_url`. Update CSV writer to use `headline_confidence` for the confidence column.
- `src/citation_verifier/__main__.py` — update CLI status-label table (`VerificationStatus.LIKELY_REAL: "[~] LIKELY REAL"` etc.) to the new six-status set with labels for each. Update `verify-brief` subcommand reads of the result fields. Update the audit-misses CSV writer.
- `src/citation_verifier/report_template.py` — already migrated to read `brief_block`/`opinion_block` (per Setup §0.4 Step 1); no schema work needed unless it reads `result.confidence` somewhere (audit during Task 8).
- `web/app.py` — update every read of `VerificationStatus`, `result.confidence`, `result.diagnostics`, `result.matched_*` to the new shape. Add label + color entries for the new statuses in whatever the status-rendering map is.

**Modified (tests):**
- `tests/test_verifier.py` — translate every assertion that names `VerificationStatus.LIKELY_REAL`, `VerificationStatus.POSSIBLE_MATCH`, or `result.confidence == X`. Per §3: assertions that used to check `LIKELY_REAL`/`POSSIBLE_MATCH` now check `Status.VERIFIED` for the status *and* check `result.headline_confidence` (or `result.resolution_path[-1].confidence`) for the distinguishing score. **Do not couple new tests to cross-stage `raw_response_summary` shape** — per design §2.5, the shape is free-form per stage and may change between phases; assertions on path entries should name the stage first, then inspect only the keys documented for that stage. (Phase 1 doesn't populate `raw_response_summary` heavily; this is mostly a discipline-for-Phase-2 note, but new tests written now should obey it.)
- `tests/test_async_verifier.py` — same translation as `test_verifier.py` for the sync/async parity assertions. The async surface returns the same `VerificationResult` shape; parity tests just need the new assertion forms.
- `tests/test_brief_pipeline.py` — update fixture construction of `VerificationResult` and assertions over its fields.
- `tests/test_cli_audit_misses.py`, `tests/test_cli_verify_batch.py`, `tests/test_cli_verify_json.py` — update CLI test assertions over status strings and result-shape reads.
- `tests/test_false_negatives.py` — switch the printed-confidence line (`{result.confidence:.0%}`) to `{result.headline_confidence:.0%}` (handle `None` case). The xfail markers added in Setup §0.4 stay.
- `tests/test_report_template.py` — no further change (already fixed in setup).

**Not touched in Phase 1:**
- `src/citation_verifier/client.py`, `src/citation_verifier/court_map.py`, `src/citation_verifier/name_matcher.py`, `src/citation_verifier/state_reporter_map.py`, `src/citation_verifier/text_cleaner.py`, `src/citation_verifier/cache.py` — internal modules with public APIs cross-repo consumers depend on (per design principle §1.6 and §5). Do not modify their signatures.
- `tests/test_parser_diagnostics.py`, `tests/test_cl_api_issues.py`, `tests/test_client_html.py`, `tests/test_client_opinion_text.py` — exercise modules below the schema layer; should pass unchanged. Audit-by-running, not by-rewriting.

---

## Tasks

### Task 1: New types in models.py

The schema is the foundation; every other task depends on it. **This task lands red** — once `VerificationStatus` and `VerificationResult` change shape, every consumer module breaks until Tasks 2–10 migrate them. That is acceptable for one commit boundary; the green-baseline discipline from Setup §0.4 ensures we can tell schema-migration breakage from pre-existing noise. Do not try to ship Task 1 green by leaving the old types alongside the new — design §5 forbids the compatibility layer.

**Files:**
- Modify: `src/citation_verifier/models.py`

- [ ] **Step 1: Write the failing test for the new `Status` enum and dataclass shape**

Create `tests/test_models.py` (new file) with one test that exercises the new shape without any I/O:

```python
"""Unit tests for the v0.3 schema types in models.py."""
from __future__ import annotations

import pytest

from citation_verifier.models import (
    BatchVerificationResult,
    FinalIds,
    GateFailure,
    GateName,
    GateSpec,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)


class TestStatusEnum:
    def test_has_six_states(self):
        assert {s.value for s in Status} == {
            "VERIFIED",
            "VERIFIED_PARTIAL",
            "VERIFIED_VIA_RECAP",
            "VERIFIED_DOCKET_ONLY",
            "WRONG_CASE",
            "NOT_FOUND",
            "VERIFICATION_INCOMPLETE",
        } - {"VERIFICATION_INCOMPLETE"} | {"VERIFICATION_INCOMPLETE"}


class TestVerificationResult:
    def test_minimal_construction(self):
        result = VerificationResult(
            citation_as_written="Foo v. Bar, 1 U.S. 1 (2020)",
            parsed_citation=None,
            status=Status.NOT_FOUND,
            final_ids=FinalIds(
                cluster_id=None, opinion_id=None, docket_id=None,
                recap_document_id=None, absolute_url=None, text_source=None,
            ),
            resolution_path=[],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 0},
            cache_hit=False,
        )
        assert result.status == Status.NOT_FOUND
        assert result.headline_confidence is None

    def test_headline_confidence_walks_path_in_reverse(self):
        """Per design §2.5: returns confidence of the last `resolved`-or-
        `partial` entry, scanning from the tail."""
        result = VerificationResult(
            citation_as_written="x",
            parsed_citation=None,
            status=Status.VERIFIED,
            final_ids=FinalIds(None, None, None, None, None, None),
            resolution_path=[
                ResolutionPathEntry(
                    stage=StageName.citation_lookup,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.no_match,
                    confidence=None, notes=None, elapsed_ms=10,
                ),
                ResolutionPathEntry(
                    stage=StageName.opinion_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.resolved,
                    confidence=0.78, notes=None, elapsed_ms=120,
                ),
            ],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 130},
            cache_hit=False,
        )
        assert result.headline_confidence == 0.78

    def test_headline_confidence_skips_non_resolved_entries(self):
        result = VerificationResult(
            citation_as_written="x",
            parsed_citation=None,
            status=Status.NOT_FOUND,
            final_ids=FinalIds(None, None, None, None, None, None),
            resolution_path=[
                ResolutionPathEntry(
                    stage=StageName.opinion_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.partial,
                    confidence=0.55, notes=None, elapsed_ms=120,
                ),
                ResolutionPathEntry(
                    stage=StageName.recap_document_search,
                    query={}, raw_response_summary={},
                    verdict=StageVerdict.errored,
                    confidence=None, notes="rate limited", elapsed_ms=300,
                ),
            ],
            warnings=[],
            gates_failed=[],
            timing={"total_ms": 420},
            cache_hit=False,
        )
        # Reverse walk: errored is skipped, partial wins.
        assert result.headline_confidence == 0.55


class TestWarningAndGate:
    def test_warning_construction(self):
        w = Warning(
            category=WarningCategory.cl_display_name_data_bug,
            message="CL display name differs from real caption",
            details={"cl_name": "Ricky Koch v. Tote, Incorporated"},
        )
        assert w.category == WarningCategory.cl_display_name_data_bug

    def test_gate_failure_construction(self):
        gf = GateFailure(
            gate=GateName.no_not_found,
            reason="status is NOT_FOUND",
            details=None,
        )
        assert gf.gate == GateName.no_not_found


class TestBatchVerificationResult:
    def test_grouped_by_status_shape(self):
        batch = BatchVerificationResult(
            total=0, by_status={}, errors=[], elapsed_ms=0,
        )
        assert batch.total == 0
```

Run: `venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: ImportError — none of the new types exist yet.

- [ ] **Step 2: Replace `models.py` with the v0.3 shape**

Open `src/citation_verifier/models.py` and rewrite to the following (note: `Diagnostic` and `CandidateMatch` stay; they're still used internally by `verifier.py` stage code — warnings replace diagnostics only at the result boundary). The old `VerificationStatus` and old `VerificationResult` are deleted.

```python
"""Data structures for citation verification (v0.3 schema)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Status taxonomy (design §2.2)
# ---------------------------------------------------------------------------


class Status(Enum):
    # Resolved-clean
    VERIFIED = "VERIFIED"
    VERIFIED_PARTIAL = "VERIFIED_PARTIAL"
    VERIFIED_VIA_RECAP = "VERIFIED_VIA_RECAP"
    VERIFIED_DOCKET_ONLY = "VERIFIED_DOCKET_ONLY"
    # Resolved-but-wrong
    WRONG_CASE = "WRONG_CASE"
    # Unresolved
    NOT_FOUND = "NOT_FOUND"
    VERIFICATION_INCOMPLETE = "VERIFICATION_INCOMPLETE"


# ---------------------------------------------------------------------------
# Resolution path (design §2.5) — fully wired in Phase 2; Phase 1 emits at
# most a single entry for the resolving stage so that the confidence number
# previously held at the top level has a home.
# ---------------------------------------------------------------------------


class StageName(Enum):
    citation_lookup = "citation_lookup"
    opinion_search = "opinion_search"
    recap_document_search = "recap_document_search"
    recap_docket_search = "recap_docket_search"
    plain_docket_search = "plain_docket_search"
    caption_investigation = "caption_investigation"


class StageVerdict(Enum):
    resolved = "resolved"
    no_match = "no_match"
    partial = "partial"
    errored = "errored"
    skipped = "skipped"


@dataclass
class ResolutionPathEntry:
    stage: StageName
    query: dict[str, Any]
    raw_response_summary: dict[str, Any]   # Free-form per stage; see design §2.5
    verdict: StageVerdict
    confidence: float | None
    notes: str | None
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Final IDs (design §2.4)
# ---------------------------------------------------------------------------


class TextSource(Enum):
    opinion_plain_text = "opinion_plain_text"
    opinion_html = "opinion_html"
    recap_document = "recap_document"


@dataclass
class FinalIds:
    cluster_id: int | None
    opinion_id: int | None
    docket_id: int | None
    recap_document_id: int | None
    absolute_url: str | None
    text_source: TextSource | None


# ---------------------------------------------------------------------------
# Warnings (design §2.6)
# ---------------------------------------------------------------------------


class WarningCategory(Enum):
    silent_partial_verification = "silent_partial_verification"
    cl_display_name_data_bug = "cl_display_name_data_bug"
    court_mismatch_noted = "court_mismatch_noted"
    date_close_not_exact = "date_close_not_exact"
    name_formatting_noise = "name_formatting_noise"
    unparseable_citation = "unparseable_citation"
    extraction_contamination_detected = "extraction_contamination_detected"


@dataclass
class Warning:
    category: WarningCategory
    message: str
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Gates (design §2.7) — Phase 1 defines the types; gate evaluation lands in
# Phase 4. Phase 1's verifier always emits an empty gates_failed list.
# ---------------------------------------------------------------------------


class GateName(Enum):
    no_not_found = "no_not_found"
    no_wrong_case = "no_wrong_case"
    no_verification_incomplete = "no_verification_incomplete"
    no_partial_verification = "no_partial_verification"
    require_primary_reporter_resolved = "require_primary_reporter_resolved"
    require_caption_investigation_on_mismatch = (
        "require_caption_investigation_on_mismatch"
    )


@dataclass
class GateSpec:
    name: GateName
    config: dict[str, Any] | None = None


@dataclass
class GateFailure:
    gate: GateName
    reason: str
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Diagnostic + CandidateMatch — unchanged. Still used by verifier.py stage
# internals. Warnings replace Diagnostics only at the VerificationResult
# boundary.
# ---------------------------------------------------------------------------


@dataclass
class Diagnostic:
    category: str   # name, court, date, docket, cite, recap, info
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class ParsedCitation:
    raw_text: str
    case_name: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    court: str | None = None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    docket_number: str | None = None
    is_westlaw: bool = False
    wl_number: str | None = None
    ecf_document_number: str | None = None   # design §2.10 + §8 disposition


@dataclass
class CandidateMatch:
    case_name: str
    url: str
    cluster_id: int | None
    date_filed: str
    court_id: str
    score: float = 0.0
    description: str | None = None
    mismatches: list[Diagnostic] = field(default_factory=list)
    docket_id: int | None = None


# ---------------------------------------------------------------------------
# VerificationResult (design §2.1) — the contract with every consumer.
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    citation_as_written: str
    parsed_citation: ParsedCitation | None
    status: Status
    final_ids: FinalIds
    resolution_path: list[ResolutionPathEntry]
    warnings: list[Warning]
    gates_failed: list[GateFailure]
    timing: dict[str, Any]
    cache_hit: bool

    @property
    def headline_confidence(self) -> float | None:
        """Per design §2.5: walk resolution_path in reverse, return the
        confidence of the first entry whose verdict is `resolved` or
        `partial`. Returns None if no such entry exists."""
        for entry in reversed(self.resolution_path):
            if entry.verdict in (StageVerdict.resolved, StageVerdict.partial):
                return entry.confidence
        return None


@dataclass
class BatchError:
    citation: str
    error: str


@dataclass
class BatchVerificationResult:
    total: int
    by_status: dict[Status, list[VerificationResult]]
    errors: list[BatchError]
    elapsed_ms: int
```

- [ ] **Step 3: Run the new-types test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: 6 tests pass (status enum, 3 VerificationResult tests, warning, gate failure, batch).

- [ ] **Step 4: Confirm the rest of the suite is now red**

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=no -q
```

Expected: many failures across `test_verifier.py`, `test_async_verifier.py`, `test_brief_pipeline.py`, the CLI test files, etc. — all of them ImportError on `VerificationStatus` or AttributeError on the old `VerificationResult` fields. This confirms the migration scope and is the expected state after this commit; Tasks 2–10 restore green.

- [ ] **Step 5: Commit**

```powershell
git add src/citation_verifier/models.py tests/test_models.py
git commit -m "refactor(v0.3): replace VerificationStatus/VerificationResult with v0.3 schema

Phase 1, Task 1 of refactor/v0.3 — design doc at
docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md.

- Replace 4-state VerificationStatus enum with 6-state Status (§2.2).
- Rebuild VerificationResult with FinalIds + ResolutionPathEntry +
  Warning + GateFailure (§2.1).
- Add headline_confidence property walking resolution_path in reverse
  (§2.5).
- Add ParsedCitation.ecf_document_number (§2.10).
- Add Status, Warning, Gate, Batch supporting types.

Clean break per design §5 — no compatibility shim. Every consumer
breaks; Tasks 2-10 migrate verifier.py, brief_pipeline.py, CLI, web,
tests, parser in lockstep."
git push
```

---

### Task 2: Migrate `verifier.py` and `test_verifier.py`

This is the largest single task — it's the irreducible unit. `verifier.py` is the producer of the new shape; `test_verifier.py` is the assertion that the shape is correct. They must land together.

**Translation strategy for the old → new mapping** (per design §3 Phase 1 task list):

| Old VerificationStatus | New Status | Where the old confidence number goes |
|---|---|---|
| `VERIFIED` (top-level confidence 1.0 from citation lookup) | `Status.VERIFIED` | `resolution_path[-1].confidence = 1.0` on a `citation_lookup` stage entry with `verdict=resolved` |
| `LIKELY_REAL` (score ≥ 0.85 from opinion search) | `Status.VERIFIED` | `resolution_path[-1].confidence = <score>` on an `opinion_search` stage entry with `verdict=resolved` |
| `POSSIBLE_MATCH` (score 0.40–0.85 from opinion search, OR name mismatch from citation lookup at 0.3) | `Status.VERIFIED` for the search-fallback case; **stays as a fresh Phase 1 decision for the name-mismatch case** — see callout below | `resolution_path[-1].confidence = <score>` |
| `NOT_FOUND` (score < 0.40 or no fallback hit) | `Status.NOT_FOUND` | No entry needed (or one with `verdict=no_match` and `confidence=<low_score>`) |

**Callout — citation-lookup name mismatch at confidence 0.3.** Today `_process_citation_lookup_hit` returns `POSSIBLE_MATCH` when the reporter resolves but the case name doesn't match (verifier.py:97). In the Phase 3 design this becomes `WRONG_CASE` (per design §2.2). But Phase 3 is out of scope here — Phase 1's mapping table in design §3 only addresses `VERIFIED/LIKELY_REAL/POSSIBLE_MATCH/NOT_FOUND` → `VERIFIED/NOT_FOUND`. To stay strictly within Phase 1 (no new statuses *produced*, only type definitions): map this case to `Status.VERIFIED` with confidence 0.3 and a Warning of category `cl_display_name_data_bug` (closest existing category — the mismatch is real, but in Phase 1 we haven't yet built the caption investigation that would distinguish "real CL data bug" from "actual WRONG_CASE"). Phase 3 reclassifies these. Add a `# TODO(phase-3): WRONG_CASE detection` comment at the mapping site so it doesn't get lost.

**Files:**
- Modify: `src/citation_verifier/verifier.py` (1625 lines)
- Modify: `tests/test_verifier.py` (2020 lines, 60+ assertions on old shape)

- [ ] **Step 1: Audit every construction of `VerificationResult` in verifier.py**

```powershell
venv\Scripts\python.exe -c "import re,pathlib; t = pathlib.Path('src/citation_verifier/verifier.py').read_text(); [print(i+1, m.group()) for i,l in enumerate(t.splitlines()) for m in [re.search(r'VerificationResult\(|VerificationStatus\.', l)] if m]"
```

Expected: a short list of line numbers — every site that needs translation. Use this as the task's working checklist.

- [ ] **Step 2: Add the construction helper at the top of `CitationVerifier`**

To avoid 30+ lines of new-shape boilerplate at every site, add one helper inside `CitationVerifier`. New method (no new behavior — just sugar):

```python
    # ------------------------------------------------------------------
    # v0.3 result-construction sugar (Phase 1)
    # ------------------------------------------------------------------

    def _build_result(
        self,
        *,
        citation_text: str,
        parsed: ParsedCitation | None,
        status: Status,
        stage: StageName | None,
        verdict: StageVerdict | None,
        confidence: float | None,
        case_name: str | None = None,
        cluster_id: int | None = None,
        docket_id: int | None = None,
        absolute_url: str | None = None,
        text_source: TextSource | None = None,
        warnings: list[Warning] | None = None,
        notes: str | None = None,
        elapsed_ms: int = 0,
    ) -> VerificationResult:
        """Construct a Phase-1-shape VerificationResult.

        Phase 1 emits at most one ResolutionPathEntry — the resolving stage
        — so the confidence number that used to be a top-level field has a
        home. Phase 2 wraps every stage and replaces this helper with the
        full instrumentation.
        """
        path: list[ResolutionPathEntry] = []
        if stage is not None and verdict is not None:
            path.append(
                ResolutionPathEntry(
                    stage=stage,
                    query={},
                    raw_response_summary={"case_name": case_name} if case_name else {},
                    verdict=verdict,
                    confidence=confidence,
                    notes=notes,
                    elapsed_ms=elapsed_ms,
                )
            )
        return VerificationResult(
            citation_as_written=citation_text,
            parsed_citation=parsed,
            status=status,
            final_ids=FinalIds(
                cluster_id=cluster_id,
                opinion_id=None,
                docket_id=docket_id,
                recap_document_id=None,
                absolute_url=absolute_url,
                text_source=text_source,
            ),
            resolution_path=path,
            warnings=warnings or [],
            gates_failed=[],
            timing={},
            cache_hit=False,
        )
```

Update the module imports at the top of `verifier.py` to include the new types (replace the existing `models` import block):

```python
from .models import (
    CandidateMatch,
    Diagnostic,
    FinalIds,
    ParsedCitation,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)
```

- [ ] **Step 3: Migrate `_process_citation_lookup_hit` to the new shape**

This is the first concrete migration — covers the `VERIFIED` and `POSSIBLE_MATCH` (now name-mismatch warning) paths from citation lookup.

Replace `_process_citation_lookup_hit` (currently verifier.py:66) — the two return statements use the old shape. New version:

```python
    def _process_citation_lookup_hit(
        self,
        citation_text: str,
        parsed: ParsedCitation,
        cluster: dict[str, Any],
    ) -> VerificationResult:
        """Process a single cluster from the Citation Lookup API (Step 1)."""
        case_name = cluster.get("case_name", "")
        cluster_id = cluster.get("id")
        url = cluster.get("absolute_url", "")
        if url and not url.startswith("http"):
            url = f"https://www.courtlistener.com{url}"
        elif cluster_id and not url:
            url = f"https://www.courtlistener.com/opinion/{cluster_id}/"

        # Name-mismatch case: citation resolves but caption disagrees.
        # TODO(phase-3): this is the WRONG_CASE candidate path. Phase 3
        # adds full-caption investigation to distinguish CL display-name
        # data bug (stays VERIFIED) from genuine WRONG_CASE.
        if parsed.case_name and case_name and not self._names_match_citation_lookup(parsed, case_name):
            return self._build_result(
                citation_text=citation_text,
                parsed=parsed,
                status=Status.VERIFIED,
                stage=StageName.citation_lookup,
                verdict=StageVerdict.resolved,
                confidence=0.3,
                case_name=case_name,
                cluster_id=cluster_id,
                absolute_url=url,
                text_source=TextSource.opinion_plain_text if cluster_id else None,
                warnings=[Warning(
                    category=WarningCategory.cl_display_name_data_bug,
                    message=(
                        f"Name mismatch: citation exists at this reporter "
                        f'location but CL caption is "{case_name}". Phase 3 '
                        f"will run caption investigation to classify."
                    ),
                )],
            )

        return self._build_result(
            citation_text=citation_text,
            parsed=parsed,
            status=Status.VERIFIED,
            stage=StageName.citation_lookup,
            verdict=StageVerdict.resolved,
            confidence=1.0,
            case_name=case_name,
            cluster_id=cluster_id,
            absolute_url=url,
            text_source=TextSource.opinion_plain_text if cluster_id else None,
        )
```

- [ ] **Step 4: Migrate the opinion-search scoring band (verifier.py:219-241)**

Replace the band:

```python
        if best.score >= 0.85:
            status = VerificationStatus.LIKELY_REAL
        elif best.score >= 0.40:
            status = VerificationStatus.POSSIBLE_MATCH
        else:
            status = VerificationStatus.NOT_FOUND

        diagnostics = self._finalize_diagnostics(best.mismatches, best.score, status)

        return VerificationResult(
            input_citation=citation_text,
            status=status,
            confidence=best.score,
            matched_case_name=best.case_name,
            matched_url=best.url,
            matched_cluster_id=best.cluster_id,
            matched_docket_id=best.docket_id,
            matched_court=best.court_id or None,
            matched_date=best.date_filed or None,
            matched_description=best.description,
            candidates=candidates[:5],
            diagnostics=diagnostics,
        )
```

With:

```python
        # Per Phase 1 mapping (design §3): LIKELY_REAL and POSSIBLE_MATCH
        # collapse into VERIFIED; the distinguishing number lives on the
        # resolution_path entry below. NOT_FOUND stays NOT_FOUND.
        if best.score >= 0.40:
            status = Status.VERIFIED
            verdict = StageVerdict.resolved
        else:
            status = Status.NOT_FOUND
            verdict = StageVerdict.no_match

        # Phase 1 retains the existing diagnostic→warning bridge as a
        # lightweight conversion: each Diagnostic becomes a notes string
        # on the stage entry (no closed-set WarningCategory exists for
        # the legacy mismatch categories until Phase 3 audits them).
        diagnostics = self._finalize_diagnostics(best.mismatches, best.score, status)
        notes = "; ".join(d.message for d in diagnostics) if diagnostics else None

        return self._build_result(
            citation_text=citation_text,
            parsed=parsed,
            status=status,
            stage=StageName.opinion_search,
            verdict=verdict,
            confidence=best.score,
            case_name=best.case_name,
            cluster_id=best.cluster_id,
            docket_id=best.docket_id,
            absolute_url=best.url,
            text_source=TextSource.opinion_plain_text if status == Status.VERIFIED and best.cluster_id else None,
            notes=notes,
        )
```

Note the `candidates` field has been dropped — it wasn't in the new schema. If consumer code or tests rely on it, surface as a Phase 1 scope question (most likely answer: drop it from Phase 1 result; if a consumer needs it, add it back as a v0.3 schema amendment with a CHANGELOG note per design §1.6).

- [ ] **Step 5: Migrate `_finalize_diagnostics` callers that still reference the old status enum**

Search for remaining old-status references in `verifier.py`:

```powershell
venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('src/citation_verifier/verifier.py').read_text(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'VerificationStatus\.(LIKELY_REAL|POSSIBLE_MATCH|VERIFIED|NOT_FOUND)', l)]"
```

For each result line, apply the mapping table from this task's preamble. The known sites are verifier.py:97, :220, :222, :724 — but re-run the audit because the rewrites in Steps 3 and 4 may have introduced new ones via the helper, or shifted line numbers.

In particular, verifier.py:724 (the f-string `"likely" if status == VerificationStatus.LIKELY_REAL else "possible"`) needs translation — since both collapse to `Status.VERIFIED`, the prose distinction is gone. Replace with a single phrasing keyed off `headline_confidence`:

```python
        confidence = result.headline_confidence or 0.0
        likelihood_word = "likely" if confidence >= 0.85 else "possible"
```

- [ ] **Step 6: Migrate every other `VerificationResult(...)` construction site in verifier.py**

Use the audit from Step 1. For each site, replace the long-form construction with a `self._build_result(...)` call. The common patterns:

- *No-hit / NOT_FOUND* (e.g. when citation lookup returns nothing and fallbacks return nothing): `status=Status.NOT_FOUND, stage=None, verdict=None, confidence=None`.
- *Insufficient-data short-circuit* (e.g. verifier.py:200-218 — `INSUFFICIENT_DATA` doesn't exist; today the code returns NOT_FOUND with a diagnostic): keep as `Status.NOT_FOUND` with `notes` carrying the diagnostic message. Do *not* introduce a new INSUFFICIENT_DATA status in Phase 1.
- *RECAP-fallback hits*: Phase 1 keeps these as `Status.VERIFIED` per the §3 mapping (the richer `VERIFIED_VIA_RECAP` is Phase 3); set `stage=StageName.recap_document_search` or `recap_docket_search` as appropriate and `text_source` to None (Phase 3 sets it to `recap_document`).

- [ ] **Step 7: Migrate `test_verifier.py` assertions in batches**

The test file has 60+ assertions on old-shape fields. Translate in batches by `Test...` class — there are roughly a dozen classes. The translation table:

| Old assertion | New assertion |
|---|---|
| `result.status == VerificationStatus.VERIFIED` | `result.status == Status.VERIFIED` |
| `result.status == VerificationStatus.LIKELY_REAL` | `result.status == Status.VERIFIED` *and* `result.headline_confidence >= 0.85` |
| `result.status == VerificationStatus.POSSIBLE_MATCH` | `result.status == Status.VERIFIED` *and* `0.40 <= result.headline_confidence < 0.85` (for fallback hits) — *or* for the citation-lookup name-mismatch case: `result.status == Status.VERIFIED` *and* `any(w.category == WarningCategory.cl_display_name_data_bug for w in result.warnings)` |
| `result.status == VerificationStatus.NOT_FOUND` | `result.status == Status.NOT_FOUND` |
| `result.confidence == X` | `result.headline_confidence == X` (or `pytest.approx(X)` if comparing floats) |
| `result.matched_case_name` | look at the resolving entry's `raw_response_summary` if you populated it there, or stop asserting on case name in tests where it's not the test's actual focus; the new schema does not expose `matched_case_name` at top level. If a test genuinely needs to assert the matched name, expose it via the helper's `raw_response_summary={"case_name": …}` (Phase 1 already does this in `_build_result`) and read `result.resolution_path[-1].raw_response_summary["case_name"]`. **Per design §2.5: never let one test inspect cross-stage shape — always name the stage first.** |
| `result.matched_url` | `result.final_ids.absolute_url` |
| `result.matched_cluster_id` | `result.final_ids.cluster_id` |
| `result.matched_docket_id` | `result.final_ids.docket_id` |
| `result.diagnostics` (list of Diagnostic) | `result.warnings` (list of Warning) for the structured cases; `result.resolution_path[-1].notes` for the freeform legacy diagnostic bridge installed in Step 4. Tests asserting on a specific diagnostic message string should assert against the `notes` field by substring. |

Run after each class is migrated: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestStep1Verified -v` (etc.) Expected: that class passes; the rest may still be red.

- [ ] **Step 8: Run the full verifier test file green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_verifier.py tests/test_models.py -v
```

Expected: 100+ tests pass (101 in test_verifier per CLAUDE.md, plus 6 in test_models). No failures.

- [ ] **Step 9: Commit**

```powershell
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "refactor(v0.3): migrate verifier.py to v0.3 schema

Phase 1, Task 2 of refactor/v0.3.

- Add _build_result helper that emits one ResolutionPathEntry for the
  resolving stage (Phase 2 will instrument every attempted stage).
- Map old 4-state taxonomy per design §3: VERIFIED/LIKELY_REAL/
  POSSIBLE_MATCH → Status.VERIFIED with the distinguishing number on
  resolution_path[-1].confidence; NOT_FOUND → Status.NOT_FOUND.
- Citation-lookup name-mismatch case: stays VERIFIED+confidence=0.3 with
  a cl_display_name_data_bug warning, tagged TODO(phase-3) for the
  WRONG_CASE reclassification that the caption-investigation pipeline
  will do.
- Translate 100+ test_verifier.py assertions to the new shape: status
  reads, headline_confidence accessor, final_ids.* in place of
  matched_*, warnings/notes in place of diagnostics."
git push
```

---

### Task 3: Migrate `test_async_verifier.py`

Async parity tests live in `tests/test_async_verifier.py` and exercise the same `CitationVerifier` surface (via its async sibling) — the assertion shapes are nearly identical to `test_verifier.py`. The implementation under test (`verify_async`/`verify_batch`) already shares helper code with the sync path per CLAUDE.md, so Task 2's `_build_result` migration carries the async side automatically; only the *assertions* in this file need translation.

**Files:**
- Modify: `tests/test_async_verifier.py`

- [ ] **Step 1: Confirm the async surface compiles**

```powershell
venv\Scripts\python.exe -m pytest tests/test_async_verifier.py -x --collect-only
```

Expected: collection succeeds (no ImportError). If it fails on import, the `verifier.py` migration in Task 2 missed an async-only construction site — go back and fix in `verifier.py` before continuing here.

- [ ] **Step 2: Apply the same assertion translation table from Task 2 Step 7**

Walk every test in the file, applying the same mapping. The file is 1110 lines; budget time accordingly (this is not "just run it" — it is mechanical but substantive translation, similar in volume to Task 2 Step 7 but smaller).

- [ ] **Step 3: Run green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py tests/test_models.py -v
```

Expected: ~130 tests pass (101 sync + 29 async + 6 models). No failures.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_async_verifier.py
git commit -m "refactor(v0.3): translate async parity tests to new schema

Phase 1, Task 3 of refactor/v0.3. Mirrors the Task 2 translation table:
status reads, headline_confidence, final_ids, warnings/notes."
git push
```

---

### Task 4: Migrate `brief_pipeline.py` and `test_brief_pipeline.py`

Per the design's Phase 1 sub-task for verify-brief: `brief_pipeline.py` is a direct consumer of `VerificationResult`. Every read of `.status`, `.confidence`, `.diagnostics`, and `.matched_*` migrates. Per design §6 and design §7 Phase 8 callout: **do not rename to verify-proposition; do not refactor the brief orchestration; just update the consumer reads**.

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py` (1034 lines, 19 schema touchpoints)
- Modify: `tests/test_brief_pipeline.py` (778 lines, 18 schema touchpoints)

- [ ] **Step 1: Audit `brief_pipeline.py` for schema touchpoints**

```powershell
venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('src/citation_verifier/brief_pipeline.py').read_text(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'VerificationStatus\.|\.confidence|\.diagnostics|\.matched_', l)]"
```

Expected: list of ~19 lines covering `_write_verification_csv` (the CSV writer), `_DOWNLOADABLE_STATUSES` (status set), `_download_opinion` and `_find_substantive_sibling` (which mutate `result.matched_url` / `result.matched_cluster_id` / `result.matched_case_name` / append to `result.diagnostics`).

- [ ] **Step 2: Update the imports**

Replace the imports block at the top of `brief_pipeline.py`:

```python
from .models import (
    Diagnostic,
    FinalIds,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)
```

- [ ] **Step 3: Update `_DOWNLOADABLE_STATUSES`**

Replace (brief_pipeline.py:180-184):

```python
_DOWNLOADABLE_STATUSES = {
    VerificationStatus.VERIFIED,
    VerificationStatus.LIKELY_REAL,
    VerificationStatus.POSSIBLE_MATCH,
}
```

With:

```python
# Phase 1: only Status.VERIFIED is *produced* (per Phase 1 mapping).
# The other VERIFIED_* members are included so Phase 3 (which starts
# producing them) doesn't have to revisit this set.
_DOWNLOADABLE_STATUSES = {
    Status.VERIFIED,
    Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP,
    Status.VERIFIED_DOCKET_ONLY,
}
```

- [ ] **Step 4: Update `_write_verification_csv` (brief_pipeline.py:143-173)**

Update the row write to use the new shape. Diagnostics now come from either `warnings` (structured) or the resolving stage's `notes` (legacy bridge):

```python
        for cite, result in zip(citations, results):
            warn_cats = [w.category.value for w in result.warnings]
            warn_msgs = [w.message for w in result.warnings]
            # Pull the legacy diagnostic-bridge text from the resolving
            # stage entry if present (the Task 2 mapping packs old
            # Diagnostics into ResolutionPathEntry.notes).
            stage_notes = ""
            if result.resolution_path:
                last = result.resolution_path[-1]
                if last.notes:
                    stage_notes = last.notes
            confidence = result.headline_confidence or 0.0
            writer.writerow({
                "citation": cite,
                "status": result.status.value,
                "confidence": f"{confidence:.2f}",
                "cl_url": result.final_ids.absolute_url or "",
                "matched_name": (
                    result.resolution_path[-1].raw_response_summary.get("case_name", "")
                    if result.resolution_path else ""
                ),
                "diagnostics_cat": "; ".join(warn_cats),
                "diagnostics_msg": "; ".join(warn_msgs) or stage_notes,
                "syllabus": "",  # Phase 1: syllabus is no longer on the result; Phase 3 re-evaluates whether to add to FinalIds.
            })
```

Note: the `syllabus` column blanks in Phase 1. If a downstream tool (the QC web page, the audit-misses CLI) reads this column, audit it in Task 5 / Task 6. If `syllabus` was load-bearing for anyone, surface as a Phase 1 scope question.

- [ ] **Step 5: Update `_download_opinion` and `_find_substantive_sibling`**

Both functions currently mutate the result in place. Sites at `brief_pipeline.py:281, :289, :299, :304, :312, :315, :319, :322, :433` per the audit grep.

Mutation translation table for these helpers:
- `result.matched_url` reads/writes → `result.final_ids.absolute_url` reads/writes.
- `result.matched_cluster_id = X` → `result.final_ids.cluster_id = X`.
- `result.matched_case_name = X` → write into `result.resolution_path[-1].raw_response_summary["case_name"] = X` (per design §2.5, free-form per stage; this is the documented home for case-name display data). If `resolution_path` is empty (unlikely for a downloaded result, since download only runs on `Status.VERIFIED`), no-op the assignment.
- `result.diagnostics.append(Diagnostic("info", ...))` → `result.warnings.append(Warning(category=WarningCategory.cl_display_name_data_bug, message=...))` — but wait, the existing diagnostic ("Matched cluster looked like a short order ... swapped to sibling") is not really a CL data bug; it's an operational note. **There is no closed-set WarningCategory for "operational sibling swap note."** Per design §2.6 amendment workflow, adding a new category requires a schema change with a CHANGELOG entry — out of scope for Phase 1. Phase 1 workaround: append the note text to `result.resolution_path[-1].notes` instead (concatenate with `; ` if already present). Add a `# TODO(phase-3): consider a sibling_swap warning category` comment.

- [ ] **Step 6: Audit `test_brief_pipeline.py` for fixture constructions and assertions**

```powershell
venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('tests/test_brief_pipeline.py').read_text(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'VerificationStatus\.|\.confidence|\.diagnostics|\.matched_|VerificationResult\(', l)]"
```

Expected: ~18 hits. Apply the Task 2 Step 7 translation table to assertions; for fixture constructions of `VerificationResult(...)`, replace with the v0.3 keyword arguments (`citation_as_written=`, `parsed_citation=`, `status=`, `final_ids=`, `resolution_path=`, `warnings=`, `gates_failed=`, `timing=`, `cache_hit=`). Consider adding a `_make_verified_result(...)` test helper at the top of the file to keep fixtures readable — same pattern as `_make_client` in `test_verifier.py`.

- [ ] **Step 7: Run green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_brief_pipeline.py tests/test_verifier.py tests/test_async_verifier.py tests/test_models.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "refactor(v0.3): migrate brief_pipeline.py to v0.3 schema

Phase 1, Task 4 of refactor/v0.3. Per design Phase 1 sub-task:
brief_pipeline is a direct VerificationResult consumer.

- _DOWNLOADABLE_STATUSES now keyed on Status.VERIFIED + the four
  VERIFIED_* variants (Phase 3 starts producing the variants).
- _write_verification_csv reads via final_ids/headline_confidence/
  warnings + resolution_path notes (legacy diagnostic bridge).
- _download_opinion / _find_substantive_sibling mutate
  final_ids.absolute_url / final_ids.cluster_id and write the sibling-
  swap operational note into resolution_path[-1].notes (no closed-set
  WarningCategory yet; Phase 3 considers adding one).
- syllabus column blanks in Phase 1 — Phase 3 re-evaluates whether to
  re-add it to FinalIds (no current consumer breaks).
- test_brief_pipeline.py fixtures and assertions translated."
git push
```

---

### Task 5: Migrate `__main__.py` (CLI verify + verify-brief subcommand)

The CLI is a thin presentation shell over the library. The work: update the status-label table, update reads of `result.confidence`, `result.matched_*`, `result.diagnostics` to the new shape, audit CSV-export paths that touched the old `status` strings.

**Files:**
- Modify: `src/citation_verifier/__main__.py` (766 lines, ~45 schema touchpoints)
- Modify: `tests/test_cli_audit_misses.py`
- Modify: `tests/test_cli_verify_batch.py`
- Modify: `tests/test_cli_verify_json.py`

- [ ] **Step 1: Audit `__main__.py`**

```powershell
venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('src/citation_verifier/__main__.py').read_text(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'VerificationStatus\.|\.confidence|\.diagnostics|\.matched_', l)]"
```

- [ ] **Step 2: Update the status-label table (around line 17-18)**

Replace:

```python
    VerificationStatus.VERIFIED: "[OK] VERIFIED",
    VerificationStatus.LIKELY_REAL: "[~] LIKELY REAL",
    VerificationStatus.POSSIBLE_MATCH: "[?] POSSIBLE MATCH",
    VerificationStatus.NOT_FOUND: "[X] NOT FOUND",
```

With:

```python
    Status.VERIFIED: "[OK] VERIFIED",
    Status.VERIFIED_PARTIAL: "[OK] VERIFIED (partial)",
    Status.VERIFIED_VIA_RECAP: "[OK] VERIFIED (RECAP)",
    Status.VERIFIED_DOCKET_ONLY: "[OK] VERIFIED (docket only)",
    Status.WRONG_CASE: "[!] WRONG CASE",
    Status.NOT_FOUND: "[X] NOT FOUND",
    Status.VERIFICATION_INCOMPLETE: "[?] VERIFICATION INCOMPLETE",
```

Phase 1 only ever emits `Status.VERIFIED` and `Status.NOT_FOUND` (per the mapping in Task 2), but include labels for all seven so Phase 3/4 don't trip on a missing key. Use ASCII status labels per CLAUDE.md "Windows console" pitfall.

- [ ] **Step 3: Translate the audit/verify/JSON paths**

For each grep hit from Step 1, apply the Task 2 Step 7 translation. Specifically watch for:

- Line ~93 (`VerificationStatus.POSSIBLE_MATCH` in a downloadable-statuses set) — collapse to the v0.3 `_DOWNLOADABLE_STATUSES` set (same as in `brief_pipeline.py` — consider importing the constant from there rather than duplicating).
- Line ~363 (`row.get("status") in ("VERIFIED", "LIKELY_REAL", "POSSIBLE_MATCH")`) — this is reading from a CSV where the strings are the *old* status names. The CSV format change is consequential: any external CSV (in `scratch/citations_for_review.csv` per CLAUDE.md) has `LIKELY_REAL` / `POSSIBLE_MATCH` strings that no longer exist as Status enum values. Decision needed: either (a) the CSV reader accepts the old strings and maps them to `Status.VERIFIED` (one-time read compatibility), or (b) the CSV gets a one-time migration sweep. For Phase 1: pick (a) — the CSV is user-maintained workflow data per CLAUDE.md and forcing a re-verification of 525 rows is disproportionate. Add a small adapter:

```python
_LEGACY_STATUS_MAP = {
    "VERIFIED": Status.VERIFIED,
    "LIKELY_REAL": Status.VERIFIED,
    "POSSIBLE_MATCH": Status.VERIFIED,
    "NOT_FOUND": Status.NOT_FOUND,
}

def _read_status_from_csv(value: str) -> Status:
    # Accept both v0.3 names (Status enum values) and the four legacy names.
    if value in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[value]
    return Status(value)
```

(Place near the top of `__main__.py`; use it anywhere CSV `status` strings are read. The CSV *writer* always writes v0.3 names; the *reader* accepts both for backwards compatibility on user-maintained CSVs only.)

- Line ~566 and ~578 (`VerificationStatus.LIKELY_REAL` in batch-summary code) — collapse to `Status.VERIFIED`.
- Line ~724 inside `verifier.py` (the `"likely" if status == VerificationStatus.LIKELY_REAL` f-string) was already handled in Task 2 Step 5.

- [ ] **Step 4: Audit and migrate the three CLI test files**

```powershell
venv\Scripts\python.exe -c "import pathlib,re; [print('==', p, '=='); [print(i+1, l) for i,l in enumerate(pathlib.Path(p).read_text().splitlines()) if re.search(r'VerificationStatus\.|\.confidence|\.diagnostics|\.matched_|VerificationResult\(', l)] for p in ['tests/test_cli_audit_misses.py','tests/test_cli_verify_batch.py','tests/test_cli_verify_json.py']]"
```

(If the chained-list-comprehension form trips on the syntax, split into three single-file audits.) Apply the Task 2 Step 7 translation to each hit.

- [ ] **Step 5: Smoke-test the CLI end-to-end**

```powershell
$env:COURTLISTENER_API_TOKEN  # confirm token is loaded from .env or env
venv\Scripts\python.exe -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"
```

Expected: `[OK] VERIFIED` printed (or equivalent v0.3 label), no traceback. The headline confidence should print as 100% (the citation-lookup hit case).

- [ ] **Step 6: Run all migrated tests green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_cli_audit_misses.py tests/test_cli_verify_batch.py tests/test_cli_verify_json.py tests/test_brief_pipeline.py tests/test_verifier.py tests/test_async_verifier.py tests/test_models.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/citation_verifier/__main__.py tests/test_cli_audit_misses.py tests/test_cli_verify_batch.py tests/test_cli_verify_json.py
git commit -m "refactor(v0.3): migrate CLI (__main__.py + cli tests) to v0.3 schema

Phase 1, Task 5 of refactor/v0.3.

- Status-label table covers all seven v0.3 statuses (only VERIFIED and
  NOT_FOUND emit in Phase 1; rest are placeholders for Phase 3+).
- _read_status_from_csv accepts legacy status strings and maps them to
  Status.VERIFIED, so user-maintained workflow CSVs in scratch/ keep
  working without a re-verification sweep. Writer always writes v0.3.
- CLI tests translated to new shape."
git push
```

---

### Task 6: Migrate `web/app.py`

Per design §5 the web app stays a direct library consumer; the FastAPI scaffolding, SSE streaming, public-mode flag, and routing don't change. The work is mechanical: every read of `VerificationStatus`, `result.confidence`, `result.diagnostics`, `result.matched_*` updates to the new shape, plus label + color entries for the new statuses in whatever status-rendering map exists.

**Files:**
- Modify: `web/app.py` (1565 lines, 62 schema touchpoints)

The audit grep counted 62 hits — this is the densest migration of any single file in this phase, but the operations are repetitive (it's mostly serialization paths converting `result.matched_X` into JSON for the frontend).

- [ ] **Step 1: Audit `web/app.py`**

```powershell
venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('web/app.py').read_text(); [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'VerificationStatus\.|\.confidence|\.diagnostics|\.matched_', l)]"
```

- [ ] **Step 2: Locate the status-to-label / status-to-color rendering map**

Look for whatever dictionary maps `VerificationStatus.*` to display strings or CSS classes for the Retrieve, Debug, and QC pages. Update it to the new seven-status set, mirroring the CLI table from Task 5 Step 2 in spirit but using web-appropriate labels and colors.

- [ ] **Step 3: Translate every JSON serialization site**

Common pattern in the audit:

```python
return {
    "status": result.status.value,
    "confidence": result.confidence,
    "matched_url": result.matched_url,
    "matched_case_name": result.matched_case_name,
    "diagnostics": [{"category": d.category, "message": d.message} for d in result.diagnostics],
}
```

New shape:

```python
return {
    "status": result.status.value,
    "confidence": result.headline_confidence,
    "matched_url": result.final_ids.absolute_url,
    "matched_case_name": (
        result.resolution_path[-1].raw_response_summary.get("case_name")
        if result.resolution_path else None
    ),
    "warnings": [
        {"category": w.category.value, "message": w.message, "details": w.details}
        for w in result.warnings
    ],
    "stage_notes": (
        result.resolution_path[-1].notes if result.resolution_path else None
    ),
}
```

Frontend JS reading `diagnostics` needs to switch to `warnings`. If the frontend HTML/JS hard-codes the old status strings (e.g. `if (status === "LIKELY_REAL")`), update those too — but note: the QC web app is gated behind `MODE=public` for the deployed Replit version per CLAUDE.md, and the Retrieve page is the only public surface. Prioritize the Retrieve page's correctness for the smoke test; Debug and QC fix-ups can be follow-on within this task.

- [ ] **Step 4: Smoke-test the web app**

```powershell
venv\Scripts\python.exe web/app.py
```

In a separate PowerShell window:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/verify -Body (@{citation="Obergefell v. Hodges, 576 U.S. 644 (2015)"} | ConvertTo-Json) -ContentType "application/json"
```

Expected: a JSON response with `status: "VERIFIED"`, `confidence: 1.0`, `matched_url: "https://www.courtlistener.com/opinion/..."`, an empty `warnings` array, and `null` (or empty string) `stage_notes`. No 500.

Open `http://localhost:8000/` in a browser, paste `Obergefell v. Hodges, 576 U.S. 644 (2015)` into the Retrieve form, submit. Expected: result renders with a green "VERIFIED" status pill (or however the frontend labels it).

Open `http://localhost:8000/debug` in a browser, run a small batch (3-5 mixed citations including one known hallucination from `tests/data/known_fake_citations.json`). Expected: status column populates with v0.3 labels; confidence column shows the headline number; warnings/notes column shows whatever bridging text the Task 2 verifier produces.

Stop the server:

```powershell
# Find the python.exe PID for web/app.py and kill it
Get-Process python | Where-Object { $_.CommandLine -like "*web/app.py*" } | Stop-Process -Force
```

(Or `taskkill //PID <pid> //F` if running under Git Bash; CLAUDE.md notes the `//` prefix requirement.)

- [ ] **Step 5: Commit**

```powershell
git add web/app.py
git commit -m "refactor(v0.3): migrate web/app.py to v0.3 schema

Phase 1, Task 6 of refactor/v0.3.

- Status-to-label/color map covers all seven v0.3 statuses.
- JSON serialization paths read final_ids.* in place of matched_*,
  headline_confidence in place of confidence, warnings in place of
  diagnostics, plus stage_notes for the legacy diagnostic bridge.
- Frontend hard-coded status checks (LIKELY_REAL/POSSIBLE_MATCH)
  updated to check for VERIFIED + a confidence band.
- Smoke-tested Retrieve and Debug pages; both render v0.3 shape."
git push
```

---

### Task 7: `test_false_negatives.py` cleanup

The xfail markers from Setup §0.4 stay. The one Phase 1 change: the success-print path on line 74 reads `result.confidence`.

**Files:**
- Modify: `tests/test_false_negatives.py`

- [ ] **Step 1: Replace the confidence-print line**

```python
    conf = result.headline_confidence
    if conf is not None:
        print(f"     Confidence: {conf:.0%}")
```

(Handle the `None` case explicitly; `headline_confidence` can be None when no `resolved`-or-`partial` entry exists.)

- [ ] **Step 2: Run green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_false_negatives.py -v
```

Expected: 1 pass (Obergefell), 4 xfail. No failures.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_false_negatives.py
git commit -m "refactor(v0.3): false-negative success print uses headline_confidence

Phase 1, Task 7 of refactor/v0.3. xfail markers from setup baseline stay."
git push
```

---

### Task 8: Add `ParsedCitation.ecf_document_number` parsing

Per design §2.10 + §8 disposition: parse `ECF No. N`, `Doc. N`, `Dkt. N`, `Dkt. No. N`. The field was already added to the dataclass in Task 1; this task just wires the parser.

**Files:**
- Modify: `src/citation_verifier/parser.py`
- Modify: `tests/test_parser_diagnostics.py` (or add a new `tests/test_parser_ecf.py` if that file is purely diagnostic)

- [ ] **Step 1: Write the failing test**

Create a new test in `tests/test_parser_diagnostics.py` (or `tests/test_parser_ecf.py` if the diagnostics file convention argues against mixing in unit tests — check the existing file's structure first):

```python
import pytest

from citation_verifier.parser import parse_citation


@pytest.mark.parametrize("text,expected", [
    ("Smith v. Jones, ECF No. 42 (D. Mass. 2024)", "42"),
    ("Smith v. Jones, Doc. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, Dkt. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, Dkt. No. 17 (D. Mass. 2024)", "17"),
    ("Smith v. Jones, ECF No. 142-1 (D. Mass. 2024)", "142-1"),  # with attachment suffix
    ("Smith v. Jones, 100 F.3d 200 (D. Mass. 2024)", None),       # no ECF — None
])
def test_parses_ecf_document_number(text, expected):
    parsed = parse_citation(text)
    assert parsed.ecf_document_number == expected
```

Run: `venv\Scripts\python.exe -m pytest tests/test_parser_diagnostics.py -v -k ecf`
Expected: fail — field is always None.

- [ ] **Step 2: Add the regex and populate the field**

Near the top of `parser.py`, add a regex constant:

```python
# ECF / Doc / Dkt document number: "ECF No. 42", "Doc. 17", "Dkt. 17",
# "Dkt. No. 17". Captures the number (which may have an attachment suffix
# like "142-1"). Case-insensitive on the prefix.
_ECF_DOC_PATTERN = re.compile(
    r"\b(?:ECF\s+No\.?|Doc\.?|Dkt\.?\s+No\.?|Dkt\.?)\s+(\d+(?:-\d+)?)\b",
    re.IGNORECASE,
)
```

Inside `parse_citation()` (and `parsed_citation_from_eyecite()` if the same input shape can flow through it), after the existing docket-number extraction:

```python
    # ECF / Doc / Dkt document number (design §2.10)
    ecf_match = _ECF_DOC_PATTERN.search(text)
    if ecf_match:
        result.ecf_document_number = ecf_match.group(1)
```

Note: the regex matches before the docket-number regex would, so check ordering. If `Case No. 24-cv-9429, ECF No. 42` exists in a test fixture, both `docket_number = "24-cv-9429"` and `ecf_document_number = "42"` should populate. Add a test for that case if there isn't one in Step 1.

- [ ] **Step 3: Run green**

```powershell
venv\Scripts\python.exe -m pytest tests/test_parser_diagnostics.py -v
```

Expected: all parser tests pass (including the new ECF ones).

- [ ] **Step 4: Commit**

```powershell
git add src/citation_verifier/parser.py tests/test_parser_diagnostics.py
git commit -m "refactor(v0.3): parse ECF/Doc/Dkt document numbers

Phase 1, Task 8 of refactor/v0.3. Per design §2.10 + §8 disposition:
recognize ECF No. N, Doc. N, Dkt. N, Dkt. No. N (with optional
attachment suffix). Populates ParsedCitation.ecf_document_number; None
when absent. Phase 2.5 corpus assembly may surface forms to widen for."
git push
```

---

### Task 9: Full Phase 1 acceptance gate

Per design §3 Phase 1 acceptance criteria:

> - All existing unit tests pass against new type signatures.
> - All async-parity tests pass.
> - Live regression suite (`test_false_negatives.py`) passes against new types.
> - CLI and web app both function with new result shape.
> - `python -m citation_verifier verify-brief <workdir> --full` produces functionally equivalent output to pre-refactor; `tests/test_brief_pipeline.py` passes.

This task runs each criterion as a checklist.

- [ ] **Step 1: Full unit test sweep**

```powershell
venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: pass + xfail only. Same shape as the Setup §0.4 Step 3 baseline (1 pass + 4 xfail in `test_false_negatives.py`, everything else passes). If anything is FAILED or ERROR, fix before continuing — the acceptance criterion is "all pass," not "mostly pass."

- [ ] **Step 2: CLI smoke test (already done in Task 5 Step 5; re-run as a gate check)**

```powershell
venv\Scripts\python.exe -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"
venv\Scripts\python.exe -m citation_verifier "Made Up v. Fake Case, 999 U.S. 999 (2099)"
```

Expected: first shows `[OK] VERIFIED` with 100% confidence; second shows `[X] NOT FOUND` with no traceback.

- [ ] **Step 3: Web app smoke test (already done in Task 6 Step 4; re-run as a gate check)**

```powershell
venv\Scripts\python.exe web/app.py
```

Open browser, run a 5-citation mixed batch on the Debug page. Expected: rendered correctly with v0.3 status labels. Stop server.

- [ ] **Step 4: verify-brief functional equivalence check**

This is the most subjective acceptance criterion ("functionally equivalent output to pre-refactor"). The mechanical check: run `verify-brief --full` against a brief workdir that exists locally, then diff `verification_results.csv` against a pre-refactor version (captured before starting Phase 1 if possible; if not captured, run on a brief whose `verification_results.csv` is already in git from a recent run).

Pick a small brief from `briefs/` — ideally one with <10 citations to keep the smoke fast. Capture a baseline first by switching to the pre-refactor commit:

```powershell
# In a SEPARATE terminal, from the main repo (not this worktree):
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier"
git switch main
venv\Scripts\python.exe -m citation_verifier verify-brief briefs/<some-small-brief>/ --full
# Capture the resulting verification_results.csv as briefs/<name>/verification_results.pre-refactor.csv
git switch refactor/v0.3
```

(Or, if you'd rather not perturb the main checkout: skip the baseline capture and accept the looser criterion "the CLI runs to completion and produces a CSV with the same columns and a sensible per-citation status." `verification_results.csv` from a recent pre-refactor run in the brief workdir, if still on disk, can serve as the baseline.)

Run from the refactor worktree:

```powershell
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\refactor-v0.3"
venv\Scripts\python.exe -m citation_verifier verify-brief briefs/<some-small-brief>/ --full
```

Expected: pipeline runs to completion. Compare row-by-row against the baseline CSV. The expected differences:
- `status` column: old `LIKELY_REAL` / `POSSIBLE_MATCH` rows now show `VERIFIED` (per the Phase 1 mapping).
- `confidence` column: numbers should match within float tolerance (the per-stage confidence is the same number that was at the top level pre-refactor).
- `cl_url`, `matched_name`: should match exactly.
- `diagnostics_cat`, `diagnostics_msg`: `cat` column may differ (warning categories vs old diagnostic categories); `msg` column may carry slightly different text (warning messages vs Diagnostic.message strings). This is expected — verify each diff row corresponds to a known translation, not a regression.
- `syllabus`: blank in v0.3 (Task 4 Step 4 note). Pre-existing data here is expected lost.

If any row shows a status change *other than* `LIKELY_REAL`/`POSSIBLE_MATCH` → `VERIFIED`, investigate — it may be a Task 2 mapping bug.

- [ ] **Step 5: Merge `origin/main` to absorb conflicts at the phase boundary**

Per CLAUDE.md's Refactor Workflow: "Merge `origin/main` into the refactor branch at each phase boundary to absorb conflicts while they're small."

```powershell
git fetch origin
git merge origin/main
```

Resolve any conflicts that surface, run the full test sweep again, commit the merge.

- [ ] **Step 6: Tag Phase 1 acceptance**

Per CLAUDE.md: "Tag each phase acceptance: `refactor/phase-1-acceptance`, ... Push tags."

```powershell
git tag refactor/phase-1-acceptance
git push origin refactor/phase-1-acceptance
```

- [ ] **Step 7: Phase 1 retrospective (per CLAUDE.md workflow preference: "save this somewhere" means write to a file, never memory)**

Write `docs/retrospectives/2026-05-20-refactor-v0.3-phase-1.md` capturing:
- Time spent overall and per task (rough hours; useful for sizing Phase 2).
- Surprises: anything in the design that didn't survive contact with the code, scope creep that had to be pushed back, design decisions that need revisiting in Phase 2's plan.
- Open questions accumulated for Phase 2's plan (most important: was the `_build_result` helper's single-entry path good enough? Phase 2 wraps every stage, so the helper either gets rewritten or absorbed — the retrospective documents the implementer's intuition).
- Anything from `scratch/TODO.md` that touched Phase 1's surface (e.g. the cluster-ID drift xfails — did any of them flip green or red during the migration? If so, that's signal for Phase 3.).

Commit the retrospective:

```powershell
git add docs/retrospectives/2026-05-20-refactor-v0.3-phase-1.md
git commit -m "docs: Phase 1 retrospective for refactor/v0.3

Time spent, surprises, open questions to fold into the Phase 2 plan,
TODO items touched."
git push
```

Phase 1 is now complete. Phase 2's plan gets written *after* this lands, with the retrospective informing it — per CLAUDE.md: "Phase N+1's plan is written after Phase N lands, when the implementer knows what shipped."

---

## Self-Review

Spec coverage checked against design §3 Phase 1 task list:

- [x] Six-status `Status` enum (§2.2) — Task 1 Step 2.
- [x] New dataclasses `VerificationResult`, `FinalIds`, `ResolutionPathEntry`, `Warning`, `GateSpec`, `GateFailure`, `BatchVerificationResult`, supporting enums — Task 1 Step 2.
- [x] `ecf_document_number: str | None` on `ParsedCitation` (§2.10) — Task 1 Step 2 (field) + Task 8 (parser).
- [x] Old→new status mapping in `verifier.py` per §3 — Task 2 Steps 3-5 + the mapping-table preamble.
- [x] Per-stage confidence relocation, top-level field removed — Task 1 Step 2 (no `confidence` field on the new dataclass) + Task 2's `_build_result` helper.
- [x] §2.5 headline-confidence accessor — Task 1 Step 2 (`headline_confidence` property).
- [x] Consumers (CLI, web app, test suite) migrated to new types — Tasks 5, 6, 2-4-7-8.
- [x] `brief_pipeline.py` migrated per Phase 1 sub-task — Task 4.
- [x] `tests/test_brief_pipeline.py` migrated — Task 4 Step 6.
- [x] verify-brief SKILL.md updated if it references citation-checker-specific status names — *not yet addressed*. Add to Task 4 Step 7? Or call out as a separate task? **Resolution:** check `.claude/skills/verify-brief/SKILL.md` during Task 4. If it references `LIKELY_REAL`/`POSSIBLE_MATCH` strings in user-facing prose, edit and commit alongside `brief_pipeline.py` in Task 4. If it doesn't (likely — the skill speaks in Green/Yellow/Red, not in verifier statuses per CLAUDE.md), no change needed. Add this audit step to Task 4 explicitly:

  - [ ] **(Task 4 Step 5.5 — added by self-review): Audit `.claude/skills/verify-brief/SKILL.md` for old status string references**

    ```powershell
    venv\Scripts\python.exe -c "import pathlib,re; t = pathlib.Path('.claude/skills/verify-brief/SKILL.md').read_text() if pathlib.Path('.claude/skills/verify-brief/SKILL.md').exists() else ''; [print(i+1, l) for i,l in enumerate(t.splitlines()) if re.search(r'LIKELY_REAL|POSSIBLE_MATCH|VerificationStatus', l)]"
    ```

    Expected: no hits (the skill speaks Green/Yellow/Red, not verifier statuses). If there are hits, update them to `VERIFIED` (per the Phase 1 collapse), commit alongside Task 4's other changes.

- [x] `__main__.py` `verify-brief` subcommand updated for user-facing status display — Task 5.

Spec coverage checked against design §3 Phase 1 acceptance criteria:

- [x] All existing unit tests pass — Task 9 Step 1.
- [x] All async-parity tests pass — Task 3 + Task 9 Step 1.
- [x] Live regression suite passes — Task 7 + Task 9 Step 1.
- [x] CLI and web app function — Task 9 Steps 2, 3.
- [x] verify-brief --full produces functionally equivalent output — Task 9 Step 4.

Spec coverage checked against design §3 Phase 1 non-production constraint:

- [x] Richer states (`VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `VERIFICATION_INCOMPLETE`) get *types* defined but are not *produced* — Task 1 defines types; Task 2's mapping table explicitly stays within `VERIFIED` and `NOT_FOUND`. The `WRONG_CASE` candidate path (citation-lookup name mismatch) gets a `TODO(phase-3)` marker in Task 2 Step 3.

Placeholder scan — searched for "TBD", "TODO", "implement later", "fill in details", "Add appropriate error handling", "Similar to Task N" in this plan:

- Task 2 Step 6 says "Similar in volume to Task 2 Step 7 but smaller" for the async-test migration — that's a *sizing* note, not a "see other task for instructions"; the actual translation table is duplicated at Task 2 Step 7 and referenced by Tasks 3-5 by line. Acceptable.
- The plan includes deliberate `TODO(phase-3)` *code comments* (Task 2 Step 3, Task 4 Step 5). These are *load-bearing* — they mark where Phase 3 picks up — and are not plan-failure TODOs.

Type consistency check — names used in later tasks match earlier-task definitions:

- `Status` (Task 1) used in Tasks 2-6 — consistent.
- `Status.VERIFIED` (Task 1) used as the single Phase-1-emitted resolved state in Tasks 2, 4, 5 — consistent.
- `FinalIds.absolute_url` (Task 1) used in Tasks 4, 6 — consistent.
- `headline_confidence` property (Task 1) used in Tasks 4, 5, 6, 7 — consistent.
- `WarningCategory.cl_display_name_data_bug` (Task 1) used in Tasks 2, 4 — consistent.
- `_build_result` helper (Task 2) used throughout Task 2 — consistent.
- `_LEGACY_STATUS_MAP` (Task 5) — only used in Task 5 — consistent.
- `_DOWNLOADABLE_STATUSES` updated in Task 4, optionally imported by Task 5 — flagged in Task 5 Step 3 ("consider importing from brief_pipeline rather than duplicating"); consistent.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-05-20-citation-verifier-refactor-phase-1-plan.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Especially good for a schema migration with many similar mechanical sites — each task is a discrete chunk a subagent can hold in context.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Good if you want to watch each task land and intervene as it happens.

Which approach?
