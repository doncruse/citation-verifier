# Citation Verifier Refactor — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument every resolution stage in `verifier.py` so that every `VerificationResult` carries a complete, in-order `resolution_path` — one `ResolutionPathEntry` per stage *attempted*, including `no_match` and `errored` paths, with stage-specific `raw_response_summary` shapes that downstream consumers and the Phase 7 diagnostic runner can inspect. Replace Phase 1's single-entry seed (`_build_result(stage=, verdict=, ...)`) with a `ResolutionPathBuilder` that accumulates entries across a verification run and a terminal `_finalize_result` that wraps the accumulated path into a `VerificationResult`.

**Architecture:** Per design v2 §3 Phase 2 and §2.5: the verifier instantiates a `ResolutionPathBuilder` once per `verify()` / `verify_async()` / per-citation slice of `verify_batch()`. Each stage runs inside a `builder.stage(StageName.X, query={...})` context manager. The caller sets the verdict on the yielded token (`token.resolved(...)`, `token.no_match(...)`, `token.partial(...)`, `token.errored(...)`) before exiting the block; the builder records elapsed time in the `finally` and appends a `ResolutionPathEntry`. No `skipped` entries — per §2.5, stages not attempted (state-court guard, no-docket-number guard, already-have-credible-match guard, `quick_only` short-circuit) are simply absent from the path. The terminal `_finalize_result(builder, status, ...)` replaces Phase 1's `_build_result`. No new statuses, no new procedural decisions, no caption investigation — that's Phase 3. The §2.8 internal gate (errored stages must produce `VERIFICATION_INCOMPLETE`) is Phase 4; Phase 2 records the errored entry in the path but lets the verifier proceed to fallback as today, so existing behavior is preserved while the audit trail becomes honest.

**Tech Stack:** Python 3.10+ (dataclasses + Enum + `contextlib.contextmanager` + `time.monotonic`), pytest, no new third-party deps.

**Workflow conventions:** Per CLAUDE.md's "Refactor Workflow" section — work in the `.claude/worktrees/refactor-v0.3` worktree, push to `refactor/v0.3` every session, no push to `main` until Phase 4, tag this phase as `refactor/phase-2-acceptance` when complete. Per-worktree `.env` is required for live-API tests (lesson from Phase 1 retrospective S5). The plan does not restate the workflow rules; check CLAUDE.md if unclear.

**Out of scope (do not silently absorb):** Phase 2.5 corpus assembly, Phase 3 richer-status detection (`VERIFIED_PARTIAL` / `VERIFIED_VIA_RECAP` / `VERIFIED_DOCKET_ONLY` / `WRONG_CASE` classification, `caption_investigation` stage), Phase 3 promotion of legacy diagnostic categories to closed-set `WarningCategory` entries (and the corresponding test-side `_diagnostics` classifier consolidation flagged in Phase 1 retrospective Q2 / note 4), Phase 4 gate evaluation including the §2.8 internal API-error gate. If a task starts to feel like it needs Phase 3+ behavior to ship, flag it as scope creep against this plan.

**Open questions folded in from Phase 1 retrospective:**
- **Q1 — `_build_result` is the seed for `ResolutionPathBuilder`.** This plan replaces it with the builder (Tasks 1–2) up front rather than as a refactor-in-passing.
- **Q4 — sync/async/batch confidence parity.** Task 7 adds the parity assertion the retrospective asked for; Phase 2's instrumentation is what enables it.
- **§8 raw_response_summary size budget.** This plan defines compact per-stage shapes (Task 1) and pins them with tests (Task 6). No debug-mode toggle in Phase 2 — that's a future concern.

---

## Setup

The worktree, venv, editable install, `.env`, and refactor branch are all already set up from Phase 1. Setup here is just confirming the baseline and absorbing any drift on `main` since `refactor/phase-1-acceptance`.

- [ ] **Step 1: Pull latest on `refactor/v0.3`**

```powershell
cd "C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\refactor-v0.3"
git fetch origin
git status
git pull --ff-only origin refactor/v0.3
```

Expected: branch up to date with `origin/refactor/v0.3`, working tree clean. If you have local commits ahead of remote, push them first; if there's a non-FF pull, stop and reconcile by hand — do *not* `git reset --hard` reflexively.

- [ ] **Step 2: Confirm green baseline**

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=no -q -m "not live_api"
```

Expected: pass + xfail only, no failures. The `-m "not live_api"` deselect matches Phase 1 retrospective S6 — the Obergefell live-API case is flaky under rate-limit; run it separately at the end of the phase rather than during every iteration.

If anything is red: stop. Phase 2's acceptance gate ("every VerificationResult has a non-empty resolution_path") cannot be checked without a known-green starting point, and you will not be able to tell instrumentation breakage from prior breakage during the migration.

- [ ] **Step 3: Merge `origin/main` into the refactor branch if there has been drift**

Per CLAUDE.md "Refactor Workflow": "Merge `origin/main` into the refactor branch at each phase boundary to absorb conflicts while they're small."

```powershell
git fetch origin
git log --oneline refactor/phase-1-acceptance..origin/main
```

If the log above is empty, skip the merge — `main` hasn't moved since Phase 1 acceptance. Otherwise:

```powershell
git merge origin/main
```

Resolve any conflicts (likely none if `main` has only docs-shaped commits); re-run `pytest` to confirm still-green; push.

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=no -q -m "not live_api"
git push
```

---

## File structure

**Created:**
- `src/citation_verifier/resolution_path.py` — new module containing `ResolutionPathBuilder` and its `_StageToken`. Pulled out of `verifier.py` because (a) `verifier.py` is already 1700+ lines and (b) the builder is a generic helper that doesn't depend on the rest of the verifier's state.
- `tests/test_resolution_path.py` — unit tests for the builder, independent of `verifier.py`.

**Modified (core library):**
- `src/citation_verifier/verifier.py` — replace `_build_result(stage=, verdict=, ...)` (Phase 1's single-entry seed) with two pieces: (1) `ResolutionPathBuilder` usage inside `verify()` / `verify_async()` / `verify_batch()`, with one `builder.stage(...)` block per stage attempted; (2) a terminal `_finalize_result(builder, *, citation_text, parsed, status, case_name=None, cluster_id=None, ...)` that constructs the `VerificationResult` from the accumulated builder. Apply to: `verify()`, `verify_async()`, `_search_fallback()`, `_search_fallback_async()`, `_batch_citation_lookup()`, `verify_batch()`, `_process_citation_lookup_hit()`, `_build_fallback_result()`.
- `src/citation_verifier/__init__.py` — re-export `ResolutionPathBuilder` only if it's needed by external consumers (audit during Task 1; if no external consumer needs it, leave it module-private).

**Modified (tests):**
- `tests/test_verifier.py` — add path-shape assertions to the existing 100+ sync tests (most are mock-driven and need an `assert len(result.resolution_path) == N` and `assert result.resolution_path[i].stage == StageName.X` where applicable). The `_diagnostics` / `_classify_note` compatibility helpers stay unchanged (their cleanup is Phase 3 work per retrospective note 4).
- `tests/test_async_verifier.py` — same path-shape additions on the async parity surface. Add a new test class `TestSyncAsyncBatchPathParity` that asserts the same mock input produces the same `resolution_path` shape across the three entry points (closes Phase 1 retrospective Q4).
- `tests/test_resolution_path.py` — new file, builder unit tests (Task 1).
- `tests/test_cache_roundtrip.py` — new file, single test that constructs a multi-stage `VerificationResult`, writes it through `VerificationCache`, reads it back, asserts the `resolution_path` survived the round-trip with all fields intact (Task 8). `cache.py` already serializes path entries (Phase 1 Task 2); this test pins that behavior against Phase 2's richer entries.

**Not touched in Phase 2:**
- `src/citation_verifier/cache.py` — Phase 1's `_serialize_path_entry` / `_hydrate_path_entry` already handle the full `ResolutionPathEntry` shape. Do not modify unless Task 8's round-trip test surfaces a real gap (and if it does, fix it under Task 8 rather than a new task).
- `src/citation_verifier/brief_pipeline.py`, `src/citation_verifier/__main__.py`, `web/app.py` — none of them read `resolution_path` contents today; Phase 2 doesn't require them to. Visible behavior is unchanged. Do not "improve" them in passing.
- `src/citation_verifier/parser.py`, `name_matcher.py`, `client.py`, `court_map.py`, `state_reporter_map.py`, `text_cleaner.py` — internal modules below the schema layer. Per design §1.6 / §5, do not modify their signatures.

---

## Per-stage `raw_response_summary` shapes

Pinning the compact-summary shapes here so every implementer of Tasks 2–5 produces the same dict keys and every Task 6 test can assert against them. Per design §2.5, the shape is free-form *per stage*; cross-stage shape stability is not promised. Consumers reading `path[i].raw_response_summary` must first inspect `path[i].stage`.

| Stage | Verdict | Required `raw_response_summary` keys |
|---|---|---|
| `citation_lookup` | `resolved` | `{"matched_cluster_id": int, "matched_case_name": str, "clusters_returned": int}` |
| `citation_lookup` | `no_match` | `{"clusters_returned": 0}` |
| `citation_lookup` | `errored` | `{"error_type": str}` |
| `opinion_search` | `resolved` | `{"candidate_count": int, "best_score": float, "best_case_name": str, "best_cluster_id": int}` |
| `opinion_search` | `no_match` | `{"candidate_count": int}` |
| `opinion_search` | `errored` | `{"error_type": str}` |
| `recap_document_search` | `resolved` | `{"docket_count": int, "best_score": float, "best_docket_id": int, "best_case_name": str}` |
| `recap_document_search` | `no_match` | `{"docket_count": int}` |
| `recap_document_search` | `errored` | `{"error_type": str}` |
| `recap_docket_search` | `resolved` | `{"docket_count": int, "best_score": float, "best_docket_id": int, "best_case_name": str}` |
| `recap_docket_search` | `no_match` | `{"docket_count": int}` |
| `recap_docket_search` | `errored` | `{"error_type": str}` |

Notes:
- "Best" candidate is whichever wins `_build_fallback_result`'s sort (highest score). When the result ultimately resolves via a different stage's candidate (rare — the fallback aggregates across opinion + RECAP), the entry's `raw_response_summary` describes its own stage's pool, not the cross-stage winner.
- `error_type` is the exception class name (`type(exc).__name__`). The exception message goes in the entry's `notes` field, not `raw_response_summary`.
- `query` (separate field from `raw_response_summary`) is the structured parameters the stage was called with:
  - `citation_lookup`: `{"text": citation_text}` (truncate to 200 chars; full text is in `citation_as_written` already)
  - `opinion_search`: `{"q": parsed.case_name, "court": court_id, "filed_after": filed_after, "filed_before": filed_before}`
  - `recap_document_search`: `{"docket_number": parsed.docket_number}`
  - `recap_docket_search`: `{"q": parsed.case_name, "court": court_id}`

---

## Tasks

### Task 1: `ResolutionPathBuilder` module

**Files:**
- Create: `src/citation_verifier/resolution_path.py`
- Create: `tests/test_resolution_path.py`

- [ ] **Step 1: Write the failing test for the builder**

```python
# tests/test_resolution_path.py
"""Unit tests for ResolutionPathBuilder (Phase 2)."""
from __future__ import annotations

import time

import pytest

from citation_verifier.models import StageName, StageVerdict
from citation_verifier.resolution_path import ResolutionPathBuilder


class TestResolutionPathBuilderBasic:
    def test_empty_builder_has_no_entries(self):
        b = ResolutionPathBuilder()
        assert b.entries() == []

    def test_resolved_stage_appends_entry(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup, query={"text": "x"}) as t:
            t.resolved(
                confidence=1.0,
                raw_response_summary={"matched_cluster_id": 42, "matched_case_name": "Foo v. Bar", "clusters_returned": 1},
            )
        entries = b.entries()
        assert len(entries) == 1
        e = entries[0]
        assert e.stage == StageName.citation_lookup
        assert e.verdict == StageVerdict.resolved
        assert e.confidence == 1.0
        assert e.query == {"text": "x"}
        assert e.raw_response_summary["matched_cluster_id"] == 42
        assert e.elapsed_ms >= 0

    def test_no_match_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.no_match(raw_response_summary={"clusters_returned": 0})
        e = b.entries()[0]
        assert e.verdict == StageVerdict.no_match
        assert e.confidence is None

    def test_partial_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.opinion_search) as t:
            t.partial(confidence=0.55, notes="primary reporter unverified")
        e = b.entries()[0]
        assert e.verdict == StageVerdict.partial
        assert e.confidence == 0.55
        assert e.notes == "primary reporter unverified"

    def test_errored_stage(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.errored(error_type="HTTPError", notes="429 rate-limited")
        e = b.entries()[0]
        assert e.verdict == StageVerdict.errored
        assert e.confidence is None
        assert e.raw_response_summary == {"error_type": "HTTPError"}
        assert e.notes == "429 rate-limited"


class TestResolutionPathBuilderOrdering:
    def test_multiple_stages_recorded_in_order(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.citation_lookup) as t:
            t.no_match(raw_response_summary={"clusters_returned": 0})
        with b.stage(StageName.opinion_search) as t:
            t.resolved(
                confidence=0.78,
                raw_response_summary={
                    "candidate_count": 3, "best_score": 0.78,
                    "best_case_name": "Foo v. Bar", "best_cluster_id": 100,
                },
            )
        entries = b.entries()
        assert [e.stage for e in entries] == [
            StageName.citation_lookup, StageName.opinion_search,
        ]
        assert [e.verdict for e in entries] == [
            StageVerdict.no_match, StageVerdict.resolved,
        ]


class TestResolutionPathBuilderTiming:
    def test_elapsed_ms_records_block_duration(self):
        b = ResolutionPathBuilder()
        with b.stage(StageName.opinion_search) as t:
            time.sleep(0.02)
            t.no_match(raw_response_summary={"candidate_count": 0})
        e = b.entries()[0]
        assert e.elapsed_ms >= 15   # generous lower bound for 20ms sleep


class TestResolutionPathBuilderExceptionPropagation:
    def test_exception_inside_block_still_records_entry(self):
        """If the caller doesn't catch and convert, the builder still
        appends an entry (the finally runs) and the exception propagates.
        Verifier code is expected to catch + token.errored() instead, but
        defensive behavior should not silently drop entries either way."""
        b = ResolutionPathBuilder()
        with pytest.raises(RuntimeError):
            with b.stage(StageName.citation_lookup) as t:
                raise RuntimeError("boom")
        entries = b.entries()
        assert len(entries) == 1
        # Default verdict when caller never set one — for debuggability,
        # this should be a clear indicator that something went wrong.
        assert entries[0].verdict == StageVerdict.errored
        assert entries[0].notes is not None and "RuntimeError" in entries[0].notes
```

Run: `venv\Scripts\python.exe -m pytest tests/test_resolution_path.py -v`
Expected: ImportError — `resolution_path` module doesn't exist yet.

- [ ] **Step 2: Implement `resolution_path.py`**

```python
# src/citation_verifier/resolution_path.py
"""ResolutionPathBuilder — accumulator for ResolutionPathEntry items
across a verification run.

Phase 2 of the v0.3 refactor. Replaces Phase 1's single-entry
``_build_result(stage=, verdict=, ...)`` seed with a builder that wraps
every stage attempt in a context manager and records one entry per
stage on exit, including ``no_match`` and ``errored`` paths.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from .models import ResolutionPathEntry, StageName, StageVerdict


@dataclass
class _StageToken:
    """Mutable carrier yielded by ``ResolutionPathBuilder.stage()``.

    The caller sets the verdict by calling one of ``resolved()``,
    ``no_match()``, ``partial()``, ``errored()`` before exiting the
    ``with`` block. The builder reads the final state in its ``finally``.
    """

    stage: StageName
    query: dict[str, Any]
    verdict: StageVerdict = StageVerdict.errored   # safe default: a forgotten verdict shows up as errored, not silently no_match
    confidence: float | None = None
    raw_response_summary: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def resolved(
        self,
        *,
        confidence: float | None = None,
        raw_response_summary: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> None:
        self.verdict = StageVerdict.resolved
        self.confidence = confidence
        if raw_response_summary is not None:
            self.raw_response_summary = raw_response_summary
        self.notes = notes

    def no_match(
        self,
        *,
        raw_response_summary: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> None:
        self.verdict = StageVerdict.no_match
        self.confidence = None
        if raw_response_summary is not None:
            self.raw_response_summary = raw_response_summary
        self.notes = notes

    def partial(
        self,
        *,
        confidence: float | None = None,
        raw_response_summary: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> None:
        self.verdict = StageVerdict.partial
        self.confidence = confidence
        if raw_response_summary is not None:
            self.raw_response_summary = raw_response_summary
        self.notes = notes

    def errored(
        self,
        *,
        error_type: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.verdict = StageVerdict.errored
        self.confidence = None
        if error_type is not None:
            self.raw_response_summary = {"error_type": error_type}
        self.notes = notes


class ResolutionPathBuilder:
    """Accumulates ResolutionPathEntry items across a verification run.

    Usage::

        builder = ResolutionPathBuilder()
        with builder.stage(StageName.citation_lookup, query={"text": cite}) as t:
            try:
                clusters = client.citation_lookup(cite)
                if clusters:
                    t.resolved(confidence=1.0, raw_response_summary={...})
                else:
                    t.no_match(raw_response_summary={"clusters_returned": 0})
            except Exception as exc:
                t.errored(error_type=type(exc).__name__, notes=str(exc))

        entries = builder.entries()  # list[ResolutionPathEntry], in order
    """

    def __init__(self) -> None:
        self._entries: list[ResolutionPathEntry] = []

    @contextlib.contextmanager
    def stage(
        self,
        name: StageName,
        query: dict[str, Any] | None = None,
    ) -> Iterator[_StageToken]:
        token = _StageToken(stage=name, query=query or {})
        start = time.monotonic()
        try:
            yield token
        except Exception as exc:
            # The caller didn't catch; record an errored entry from the
            # exception itself before re-raising. This is the defensive
            # path — production verifier code is expected to catch and
            # call ``token.errored()`` explicitly so the error_type lands
            # in raw_response_summary.
            if token.verdict == StageVerdict.errored and not token.notes:
                token.notes = f"{type(exc).__name__}: {exc}"
                if not token.raw_response_summary:
                    token.raw_response_summary = {"error_type": type(exc).__name__}
            raise
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._entries.append(
                ResolutionPathEntry(
                    stage=token.stage,
                    query=token.query,
                    raw_response_summary=token.raw_response_summary,
                    verdict=token.verdict,
                    confidence=token.confidence,
                    notes=token.notes,
                    elapsed_ms=elapsed_ms,
                )
            )

    def entries(self) -> list[ResolutionPathEntry]:
        """Return a snapshot of the accumulated entries (in order)."""
        return list(self._entries)
```

- [ ] **Step 3: Run the builder tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_resolution_path.py -v`
Expected: 8 tests pass.

- [ ] **Step 4: Confirm rest of suite still green (builder is unused so far)**

Run: `venv\Scripts\python.exe -m pytest tests/ --tb=no -q -m "not live_api"`
Expected: same pass/xfail count as Setup §0.2. The builder doesn't change any existing code path yet; this commit just adds the new module.

- [ ] **Step 5: Commit**

```powershell
git add src/citation_verifier/resolution_path.py tests/test_resolution_path.py
git commit -m "refactor(v0.3): add ResolutionPathBuilder for Phase 2 instrumentation

Phase 2's instrumentation needs an accumulator that wraps each stage in
a context manager and records ResolutionPathEntry items in order. This
commit lands the helper and unit tests; verifier.py adoption follows
in subsequent commits."
git push
```

---

### Task 2: Instrument `citation_lookup` stage and refactor `_build_result` → `_finalize_result`

This is the largest task in Phase 2. It does three things in one commit because they are entangled: (a) introduce the builder into `verify()`'s control flow; (b) replace the single-entry `_build_result(stage=, verdict=, ...)` API with a terminal `_finalize_result(builder, ...)`; (c) instrument the `citation_lookup` stage end-to-end (hit, miss, error). The fallback stages get instrumented in Task 3. Trying to split (a) and (b) into separate commits leaves the codebase in an inconsistent state where some paths use the builder and others don't — better to bite it off at once.

**Files:**
- Modify: `src/citation_verifier/verifier.py`
- Modify: `tests/test_verifier.py`

- [ ] **Step 1: Write failing tests for the citation_lookup path shape**

Add to `tests/test_verifier.py` (toward the top of the file, after the existing helpers):

```python
from citation_verifier.models import StageName, StageVerdict


class TestResolutionPathShape:
    """Phase 2 path-shape coverage for the citation_lookup stage.

    These tests assert on path entries directly (not via the
    _diagnostics compat helper), because the entries are what
    Phase 2 instruments. The compat helper covers warnings+notes
    legacy reads; this class covers structured path-entry reads.
    """

    def test_citation_lookup_hit_produces_one_resolved_entry(self):
        client = _make_client(citation_lookup=[
            {"clusters": [{"id": 100, "case_name": "Foo v. Bar", "absolute_url": "/opinion/100/"}]},
        ])
        verifier = CitationVerifier(client=client)
        result = verifier.verify("100 U.S. 1 (2020)")

        assert result.status == Status.VERIFIED
        assert len(result.resolution_path) == 1
        entry = result.resolution_path[0]
        assert entry.stage == StageName.citation_lookup
        assert entry.verdict == StageVerdict.resolved
        assert entry.confidence == 1.0
        assert entry.raw_response_summary == {
            "matched_cluster_id": 100,
            "matched_case_name": "Foo v. Bar",
            "clusters_returned": 1,
        }
        assert entry.query["text"].startswith("100 U.S. 1")
        assert entry.elapsed_ms >= 0

    def test_citation_lookup_miss_quick_only_records_no_match_entry(self):
        client = _make_client(citation_lookup=[])
        verifier = CitationVerifier(client=client)
        result = verifier.verify("999 U.S. 999 (2099)", quick_only=True)

        assert result.status == Status.NOT_FOUND
        assert len(result.resolution_path) == 1
        entry = result.resolution_path[0]
        assert entry.stage == StageName.citation_lookup
        assert entry.verdict == StageVerdict.no_match
        assert entry.raw_response_summary == {"clusters_returned": 0}

    def test_citation_lookup_error_records_errored_entry_then_falls_through(self):
        """The §2.8 internal API-error gate lands in Phase 4. In Phase 2,
        an errored citation_lookup entry must still appear in the path,
        and the verifier must still fall through to opinion_search (no
        behavior change vs. Phase 1)."""
        client = _make_client()
        client.citation_lookup.side_effect = ConnectionError("network down")
        verifier = CitationVerifier(client=client)
        result = verifier.verify("Smith v. Jones, 1 F.3d 1 (1st Cir. 1990)")

        # First entry is citation_lookup, errored.
        assert result.resolution_path[0].stage == StageName.citation_lookup
        assert result.resolution_path[0].verdict == StageVerdict.errored
        assert result.resolution_path[0].raw_response_summary == {"error_type": "ConnectionError"}
        assert "ConnectionError" in (result.resolution_path[0].notes or "")
        # Falls through to opinion_search per existing Phase 1 behavior.
        assert len(result.resolution_path) >= 2
        assert result.resolution_path[1].stage == StageName.opinion_search


class TestFinalizeResultTerminalShape:
    """The terminal helper wraps the builder's accumulated entries into
    a VerificationResult and is the only public producer of results
    inside the verifier. Phase 1's _build_result is gone."""

    def test_verifier_module_does_not_expose_build_result(self):
        from citation_verifier import verifier as v
        # Phase 1's _build_result is replaced by _finalize_result in Phase 2.
        # If you see _build_result on the class, the migration is incomplete.
        assert not hasattr(v.CitationVerifier, "_build_result"), (
            "_build_result should be removed in Phase 2; use _finalize_result"
        )
        assert hasattr(v.CitationVerifier, "_finalize_result")
```

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestResolutionPathShape tests/test_verifier.py::TestFinalizeResultTerminalShape -v`
Expected: all 4 new tests fail (`_build_result` still exists; resolution_path entries don't have the new shape).

- [ ] **Step 2: Refactor `verifier.py`**

Open `src/citation_verifier/verifier.py` and apply these edits:

**Add to the imports at the top (after the existing `from .models import ...` block):**

```python
from .resolution_path import ResolutionPathBuilder, _StageToken  # _StageToken imported for type hints only
```

**Delete the `_build_result` method** (lines 73–130 in the current file). It is replaced by `_finalize_result` below.

**Add `_finalize_result` immediately above `_process_citation_lookup_hit`** (in the "Shared helpers" section):

```python
def _finalize_result(
    self,
    builder: ResolutionPathBuilder,
    *,
    citation_text: str,
    parsed: ParsedCitation | None,
    status: Status,
    cluster_id: int | None = None,
    docket_id: int | None = None,
    absolute_url: str | None = None,
    text_source: TextSource | None = None,
    warnings: list[Warning] | None = None,
) -> VerificationResult:
    """Terminal helper: wrap the accumulated resolution_path into a result.

    Phase 2 of the v0.3 refactor. Replaces Phase 1's _build_result.
    The caller has already recorded each stage attempt via
    builder.stage(...) context managers; this helper just collects the
    entries, packs the FinalIds, and returns the VerificationResult.
    """
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
        resolution_path=builder.entries(),
        warnings=warnings or [],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )
```

**Rewrite `_process_citation_lookup_hit`** to take a builder and use `token.resolved(...)`:

```python
def _process_citation_lookup_hit(
    self,
    builder: ResolutionPathBuilder,
    token: _StageToken,
    citation_text: str,
    parsed: ParsedCitation,
    cluster: dict[str, Any],
    clusters_returned: int,
) -> VerificationResult:
    """Process a single cluster from the Citation Lookup API.

    The caller has already opened a builder.stage() block and yielded
    the token; this helper sets the token's resolved-verdict state and
    finalizes the result.
    """
    case_name = cluster.get("case_name", "")
    cluster_id = cluster.get("id")
    url = cluster.get("absolute_url", "")
    if url and not url.startswith("http"):
        url = f"https://www.courtlistener.com{url}"
    elif cluster_id and not url:
        url = f"https://www.courtlistener.com/opinion/{cluster_id}/"

    summary = {
        "matched_cluster_id": cluster_id,
        "matched_case_name": case_name,
        "clusters_returned": clusters_returned,
    }

    # Name-mismatch case: citation resolves but caption disagrees.
    # TODO(phase-3): caption investigation distinguishes CL display-name
    # data bug (stays VERIFIED) from genuine WRONG_CASE.
    if parsed.case_name and case_name and not self._names_match_citation_lookup(parsed, case_name):
        token.resolved(confidence=0.3, raw_response_summary=summary)
        return self._finalize_result(
            builder,
            citation_text=citation_text,
            parsed=parsed,
            status=Status.VERIFIED,
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

    token.resolved(confidence=1.0, raw_response_summary=summary)
    return self._finalize_result(
        builder,
        citation_text=citation_text,
        parsed=parsed,
        status=Status.VERIFIED,
        cluster_id=cluster_id,
        absolute_url=url,
        text_source=TextSource.opinion_plain_text if cluster_id else None,
    )
```

**Rewrite `verify()`'s citation_lookup section:**

```python
def verify(
    self,
    citation_text: str,
    parsed: ParsedCitation | None = None,
    quick_only: bool = False,
) -> VerificationResult:
    """Verify a citation string through the resolution pipeline.

    Stages attempted, in order:
      1. citation_lookup       (always)
      2. opinion_search        (if (1) misses and not quick_only)
      3. recap_document_search (if (2) doesn't yield a credible match
                                 and parsed.docket_number is present
                                 and court is federal)
      4. recap_docket_search   (if (2) doesn't yield a credible match
                                 and parsed.case_name is present
                                 and court is federal)

    Each stage attempted produces one ResolutionPathEntry. Stages not
    attempted (quick_only short-circuit, state-court guard, already-have-
    credible-match guard, missing-input guard) are absent from the path.
    """
    citation_text = citation_text.strip()
    if parsed is None:
        parsed = parse_citation(citation_text)

    builder = ResolutionPathBuilder()

    # Stage 1: Citation Lookup API
    with builder.stage(
        StageName.citation_lookup,
        query={"text": citation_text[:200]},
    ) as t:
        try:
            lookup_results = self.client.citation_lookup(citation_text)
            clusters_returned = sum(len(lr.get("clusters", [])) for lr in lookup_results)
            for lr in lookup_results:
                clusters = lr.get("clusters", [])
                for cluster in clusters:
                    return self._process_citation_lookup_hit(
                        builder, t, citation_text, parsed, cluster, clusters_returned,
                    )
            # No clusters in any of the lookup results.
            t.no_match(raw_response_summary={"clusters_returned": 0})
        except Exception as exc:
            logger.debug("Citation lookup failed", exc_info=True)
            t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

    if quick_only:
        return self._finalize_result(
            builder,
            citation_text=citation_text,
            parsed=parsed,
            status=Status.NOT_FOUND,
        )

    # Stage 2+: Fuzzy search fallback (instrumented in Task 3)
    return self._search_fallback(builder, citation_text, parsed)
```

(Note that `_search_fallback` now takes the existing `builder` so the path keeps growing. Its signature changes; the rewrite happens in Task 3.)

**Update `_search_fallback`'s signature** to accept the builder (temporary plumbing — internal stages remain a single entry until Task 3 instruments them):

```python
def _search_fallback(
    self,
    builder: ResolutionPathBuilder,
    citation_text: str,
    parsed: ParsedCitation,
) -> VerificationResult:
    """Search CourtListener using parsed citation metadata.

    Task 2 only wires the builder through. Task 3 will wrap each stage
    inside this method in its own builder.stage() context manager.
    """
    # ... existing body unchanged for Task 2; just plumb builder through
    # to _build_fallback_result below.
```

**Rewrite `_build_fallback_result`** with the same single-entry interim behavior as Phase 1, but routed through the builder. Task 3 will replace this with true per-stage instrumentation; for now, the fallback emits one aggregate entry (always under `opinion_search`, even for RECAP matches — this preserves Phase 1's behavior exactly):

```python
def _build_fallback_result(
    self,
    builder: ResolutionPathBuilder,
    citation_text: str,
    parsed: ParsedCitation,
    candidates: list[CandidateMatch],
    court_id: str | None,
) -> VerificationResult:
    """Build the final result from search fallback candidates.

    Task 2 interim: emits one opinion_search entry for the aggregate
    fallback outcome (matches Phase 1's single-entry behavior, just
    routed through the builder). Task 3 replaces this with per-stage
    entries inside _search_fallback.
    """
    if not candidates:
        with builder.stage(StageName.opinion_search) as t:
            t.no_match(
                raw_response_summary={"candidate_count": 0},
                notes="No matching cases found in CourtListener opinions or RECAP",
            )
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    best = candidates[0]

    has_unverified_cite = bool(
        (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
    )
    if has_unverified_cite and court_id and best.court_id != court_id:
        with builder.stage(StageName.opinion_search) as t:
            t.no_match(
                raw_response_summary={"candidate_count": len(candidates)},
                notes=(
                    f"Reporter citation could not be verified, and no matching "
                    f"cases were found in {parsed.court}"
                ),
            )
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    if not parsed.court and not parsed.year:
        with builder.stage(StageName.opinion_search) as t:
            t.no_match(
                raw_response_summary={"candidate_count": len(candidates)},
                notes=(
                    "Insufficient data to verify: citation text is missing "
                    "both court and date. A match cannot be confirmed with "
                    "name alone. Try adding the court and year parenthetical "
                    "(e.g. '(E.D. Tenn. 2020)') to the citation text."
                ),
            )
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    diagnostics = self._finalize_diagnostics(
        best.mismatches, best.score,
        Status.VERIFIED if best.score >= 0.40 else Status.NOT_FOUND,
    )
    notes = "; ".join(d.message for d in diagnostics) if diagnostics else None

    is_recap_match = best.docket_id is not None and best.cluster_id is None
    stage = StageName.recap_document_search if is_recap_match else StageName.opinion_search
    text_source = (
        None if is_recap_match
        else (TextSource.opinion_plain_text if best.score >= 0.40 and best.cluster_id else None)
    )

    summary = {"case_name": best.case_name} if best.case_name else {}
    with builder.stage(stage) as t:
        if best.score >= 0.40:
            t.resolved(confidence=best.score, raw_response_summary=summary, notes=notes)
            status = Status.VERIFIED
        else:
            t.no_match(raw_response_summary=summary, notes=notes)
            status = Status.NOT_FOUND
    return self._finalize_result(
        builder,
        citation_text=citation_text,
        parsed=parsed,
        status=status,
        cluster_id=best.cluster_id,
        docket_id=best.docket_id,
        absolute_url=best.url,
        text_source=text_source,
    )
```

The `raw_response_summary` shape for this interim path entry uses `{"case_name": best.case_name}` (Phase 1's minimal shape) rather than the richer Task 3 shape — Task 3 will overwrite this when it splits the aggregate entry into per-stage entries. Do not introduce new stages or richer summaries here.

- [ ] **Step 3: Run the new path-shape tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestResolutionPathShape tests/test_verifier.py::TestFinalizeResultTerminalShape -v`
Expected: 4 pass.

- [ ] **Step 4: Run the rest of `test_verifier.py` and confirm no regressions**

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py -v`
Expected: all tests pass (100+ Phase 1 tests + 4 new path-shape tests).

If anything regresses: the `_diagnostics` / `_classify_note` helpers read `result.warnings` and `result.resolution_path[-1].notes`. The Task 2 rewrite must preserve the `notes` field's join-of-mismatch-messages content on the terminal stage entry so those helpers keep working. The shape of `_finalize_result` doesn't change `notes`; only the per-stage instrumentation does. Audit which tests broke and adjust the `notes=` argument in the relevant builder.stage block.

- [ ] **Step 5: Run the full suite, no regressions outside `test_async_verifier.py`**

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=short -q -m "not live_api"
```

Expected: `test_async_verifier.py` may have failures because `verify_async` still calls the (deleted) `_build_result` — those land in Task 4. Every *other* test file should be green.

- [ ] **Step 6: Patch `verify_async` minimally so the async tests collect**

If `test_async_verifier.py` is red, apply the same Phase-2 surface to `verify_async` and `_search_fallback_async`: introduce a builder at the top of `verify_async`, instrument the `citation_lookup` block, plumb the builder into `_search_fallback_async`. Mirror the sync changes one-for-one. This is *deliberately* part of Task 2 (not deferred to Task 4) because leaving `verify_async` calling the deleted `_build_result` leaves the whole async surface broken between Task 2 and Task 4 — a worse state than the in-between we already accept on `_search_fallback`'s per-stage instrumentation.

Run: `venv\Scripts\python.exe -m pytest tests/ --tb=short -q -m "not live_api"`
Expected: full suite green again (pass + xfail only, no failures).

- [ ] **Step 7: Commit**

```powershell
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "refactor(v0.3): Phase 2 builder + citation_lookup instrumentation

Replaces Phase 1's _build_result single-entry seed with
ResolutionPathBuilder. Every verify()/verify_async() call accumulates
entries via builder.stage(...) blocks; _finalize_result wraps the
accumulated path into a VerificationResult. citation_lookup is fully
instrumented (resolved, no_match, errored); _search_fallback emits a
single aggregate opinion_search entry pending Task 3."
git push
```

---

### Task 3: Instrument the fallback stages (`opinion_search`, `recap_document_search`, `recap_docket_search`)

**Files:**
- Modify: `src/citation_verifier/verifier.py`
- Modify: `tests/test_verifier.py`

- [ ] **Step 1: Write failing tests for per-stage fallback path entries**

Add to `tests/test_verifier.py::TestResolutionPathShape`:

```python
def test_opinion_search_hit_after_citation_lookup_miss(self):
    client = _make_client(
        citation_lookup=[],
        search_opinions=[{
            "caseName": "Foo v. Bar",
            "cluster_id": 200,
            "dateFiled": "2020-06-15",
            "court_id": "scotus",
            "absolute_url": "/opinion/200/",
            "citation": ["100 U.S. 1"],
            "docketNumber": "",
        }],
    )
    verifier = CitationVerifier(client=client)
    result = verifier.verify("Foo v. Bar, 100 U.S. 1 (Sup. Ct. 2020)")

    stages = [e.stage for e in result.resolution_path]
    assert stages == [StageName.citation_lookup, StageName.opinion_search]
    assert result.resolution_path[0].verdict == StageVerdict.no_match
    assert result.resolution_path[1].verdict == StageVerdict.resolved
    # raw_response_summary shape on opinion_search resolved
    summary = result.resolution_path[1].raw_response_summary
    assert summary["candidate_count"] >= 1
    assert "best_score" in summary
    assert summary["best_case_name"] == "Foo v. Bar"
    assert summary["best_cluster_id"] == 200

def test_recap_docket_search_attempted_when_opinion_search_misses(self):
    client = _make_client(
        citation_lookup=[],
        search_opinions=[],
        search_recap=[{
            "caseName": "Smith v. Jones",
            "docket_id": 500,
            "court_id": "cand",
            "docket_absolute_url": "/docket/500/",
            "recap_documents": [{
                "short_description": "Opinion and order",
                "date_filed": "2020-06-15",
                "is_free_on_pacer": True,
                "page_count": 20,
                "absolute_url": "/recap/500/1/",
                "entry_date_filed": "2020-06-15",
                "entry_description": "ORDER granting motion to dismiss",
            }],
        }],
    )
    verifier = CitationVerifier(client=client)
    result = verifier.verify("Smith v. Jones, No. 20-cv-1234 (N.D. Cal. June 15, 2020)")

    stages = [e.stage for e in result.resolution_path]
    # docket_number present → recap_document_search runs;
    # case_name present → recap_docket_search runs after.
    assert StageName.citation_lookup in stages
    assert StageName.opinion_search in stages
    assert StageName.recap_docket_search in stages or StageName.recap_document_search in stages
    # The RECAP stage that resolved should be a `resolved` verdict.
    recap_entries = [
        e for e in result.resolution_path
        if e.stage in (StageName.recap_document_search, StageName.recap_docket_search)
    ]
    assert any(e.verdict == StageVerdict.resolved for e in recap_entries)

def test_all_stages_miss_produces_no_match_path(self):
    client = _make_client(
        citation_lookup=[],
        search_opinions=[],
        search_recap=[],
    )
    verifier = CitationVerifier(client=client)
    result = verifier.verify("Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)")

    assert result.status == Status.NOT_FOUND
    stages = [e.stage for e in result.resolution_path]
    # Must include citation_lookup + opinion_search at minimum.
    assert stages[0] == StageName.citation_lookup
    assert StageName.opinion_search in stages
    # Every entry's verdict is no_match (no errored or resolved).
    assert all(
        e.verdict == StageVerdict.no_match for e in result.resolution_path
    )

def test_state_court_skips_recap_stages(self):
    """RECAP is federal PACER data only. State-court citations should
    not emit recap_*_search entries (the guard is in _search_fallback)."""
    client = _make_client(
        citation_lookup=[],
        search_opinions=[],
        search_recap=[],
    )
    verifier = CitationVerifier(client=client)
    # "(Cal. Ct. App. 2020)" → state court
    result = verifier.verify("Foo v. Bar, 99 Cal.App.5th 99 (Cal. Ct. App. 2020)")

    stages = [e.stage for e in result.resolution_path]
    assert StageName.recap_document_search not in stages
    assert StageName.recap_docket_search not in stages

def test_opinion_search_error_falls_through_to_recap(self):
    client = _make_client(citation_lookup=[])
    client.search_opinions.side_effect = ConnectionError("opinion search down")
    client.search_recap.return_value = []
    verifier = CitationVerifier(client=client)
    result = verifier.verify("Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)")

    entries_by_stage = {e.stage: e for e in result.resolution_path}
    assert entries_by_stage[StageName.opinion_search].verdict == StageVerdict.errored
    assert entries_by_stage[StageName.opinion_search].raw_response_summary == {
        "error_type": "ConnectionError",
    }
```

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestResolutionPathShape -v`
Expected: 5 of the new tests fail (Task 2 only instrumented citation_lookup; fallback stages still emit a single aggregate entry).

- [ ] **Step 2: Rewrite `_search_fallback` with per-stage instrumentation**

Replace the body of `_search_fallback` so each stage is in its own `builder.stage(...)` block. Skeleton:

```python
def _search_fallback(
    self,
    builder: ResolutionPathBuilder,
    citation_text: str,
    parsed: ParsedCitation,
) -> VerificationResult:
    court_id, filed_after, filed_before = self._build_search_params(parsed)

    opinion_candidates: list[CandidateMatch] = []
    recap_candidates: list[CandidateMatch] = []

    # Stage: opinion_search
    if parsed.case_name:
        with builder.stage(
            StageName.opinion_search,
            query={
                "q": parsed.case_name,
                "court": court_id,
                "filed_after": filed_after,
                "filed_before": filed_before,
            },
        ) as t:
            try:
                results = self.client.search_opinions(
                    q=parsed.case_name,
                    court=court_id,
                    filed_after=filed_after,
                    filed_before=filed_before,
                )
                opinion_candidates = self._process_results(results, parsed)
                if opinion_candidates:
                    best = max(opinion_candidates, key=lambda c: c.score)
                    summary = {
                        "candidate_count": len(opinion_candidates),
                        "best_score": best.score,
                        "best_case_name": best.case_name,
                        "best_cluster_id": best.cluster_id,
                    }
                    if best.score >= 0.40:
                        t.resolved(confidence=best.score, raw_response_summary=summary)
                    else:
                        t.no_match(raw_response_summary=summary)
                else:
                    t.no_match(raw_response_summary={"candidate_count": 0})
            except Exception as exc:
                logger.debug("Opinion search failed", exc_info=True)
                t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

    # Guards for RECAP: federal-only, no credible match yet.
    is_state_court = court_id and not is_federal_court(court_id)
    has_credible_match = any(c.score >= 0.5 for c in opinion_candidates)

    # Stage: recap_document_search (by docket_number)
    if not has_credible_match and not is_state_court and parsed.docket_number:
        with builder.stage(
            StageName.recap_document_search,
            query={"docket_number": parsed.docket_number},
        ) as t:
            try:
                results = self.client.search_recap(docket_number=parsed.docket_number)
                cited_dn = self._normalize_docket_number(parsed.docket_number)
                results = [
                    r for r in results
                    if self._normalize_docket_number(
                        r.get("docketNumber") or r.get("docket_number") or ""
                    ) == cited_dn
                ]
                rd_candidates = self._process_recap_results(results, parsed)
                recap_candidates.extend(rd_candidates)
                if rd_candidates:
                    best = max(rd_candidates, key=lambda c: c.score)
                    summary = {
                        "docket_count": len(rd_candidates),
                        "best_score": best.score,
                        "best_docket_id": best.docket_id,
                        "best_case_name": best.case_name,
                    }
                    if best.score >= 0.40:
                        t.resolved(confidence=best.score, raw_response_summary=summary)
                    else:
                        t.no_match(raw_response_summary=summary)
                else:
                    t.no_match(raw_response_summary={"docket_count": 0})
            except Exception as exc:
                logger.debug("RECAP search by docket number failed", exc_info=True)
                t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

    # Stage: recap_docket_search (by case_name)
    if not has_credible_match and not is_state_court and parsed.case_name:
        with builder.stage(
            StageName.recap_docket_search,
            query={"q": parsed.case_name, "court": court_id},
        ) as t:
            try:
                results = self.client.search_recap(q=parsed.case_name, court=court_id)
                rd_candidates = self._process_recap_results(results, parsed)
                recap_candidates.extend(rd_candidates)
                if rd_candidates:
                    best = max(rd_candidates, key=lambda c: c.score)
                    summary = {
                        "docket_count": len(rd_candidates),
                        "best_score": best.score,
                        "best_docket_id": best.docket_id,
                        "best_case_name": best.case_name,
                    }
                    if best.score >= 0.40:
                        t.resolved(confidence=best.score, raw_response_summary=summary)
                    else:
                        t.no_match(raw_response_summary=summary)
                else:
                    t.no_match(raw_response_summary={"docket_count": 0})
            except Exception as exc:
                logger.debug("RECAP search failed", exc_info=True)
                t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

    # Aggregate and finalize. The per-stage instrumentation above already
    # appended path entries; _build_fallback_result no longer touches the
    # builder, only picks the winner across pooled candidates.
    candidates = opinion_candidates + recap_candidates
    return self._build_fallback_result(
        builder, citation_text, parsed, candidates, court_id,
    )
```

**Simplify `_build_fallback_result`** since the per-stage entries already exist: it now just sorts the combined candidates and finalizes the result (no `builder.stage(...)` calls; those are done in `_search_fallback`):

```python
def _build_fallback_result(
    self,
    builder: ResolutionPathBuilder,
    citation_text: str,
    parsed: ParsedCitation,
    candidates: list[CandidateMatch],
    court_id: str | None,
) -> VerificationResult:
    """Pick the winning candidate across pooled stages and finalize.

    Per-stage path entries were already appended in _search_fallback.
    This helper does NOT append any new entries; it only chooses
    final_ids and status.
    """
    if not candidates:
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    best = candidates[0]

    has_unverified_cite = bool(
        (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
    )
    if has_unverified_cite and court_id and best.court_id != court_id:
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    if not parsed.court and not parsed.year:
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    if best.score < 0.40:
        return self._finalize_result(
            builder, citation_text=citation_text, parsed=parsed,
            status=Status.NOT_FOUND,
        )

    is_recap_match = best.docket_id is not None and best.cluster_id is None
    text_source = (
        None if is_recap_match
        else (TextSource.opinion_plain_text if best.cluster_id else None)
    )
    return self._finalize_result(
        builder,
        citation_text=citation_text,
        parsed=parsed,
        status=Status.VERIFIED,
        cluster_id=best.cluster_id,
        docket_id=best.docket_id,
        absolute_url=best.url,
        text_source=text_source,
    )
```

Note that the `notes` carrying the joined diagnostic messages is now on the relevant *stage entry* (set via `t.no_match(notes=...)` or `t.resolved(notes=...)` inside `_search_fallback`), not on a terminal aggregate entry. The test-side `_diagnostics` compat helper reads `result.resolution_path[-1].notes` — which works only when the last entry's `notes` carries those messages.

**Decision:** to preserve the legacy compat helper without rewriting it, set the joined-diagnostic-messages notes on whichever stage produced the *winning* candidate (the one used in `_finalize_result`). When the result is `NOT_FOUND`, set it on the last stage in the path. The implementer should:
- Track `notes_for_winner` across stages: when a stage produces a candidate, build its diagnostics string and attach to that stage's `t.no_match`/`t.resolved` call via `notes=`.
- For the resolved path, this means the diagnostics for the winning candidate land on the *winning* stage's entry — which is the last `resolved` entry in the path, which is what `result.resolution_path[-1]` returns when the path ends at the winning stage.

If the test suite still breaks because the legacy helper reads `path[-1].notes` and the winner isn't the last entry: add a post-finalization step in `_finalize_result` that walks back to find the resolved-or-partial entry and uses its notes for the `_diagnostics` helper's compatibility. *Don't* duplicate the notes onto a synthetic terminal entry — that would re-introduce the Phase 1 anti-pattern.

- [ ] **Step 3: Run the new path-shape tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestResolutionPathShape -v`
Expected: all 8 path-shape tests pass.

- [ ] **Step 4: Run the full sync verifier test file**

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py -v`
Expected: all tests pass.

If the legacy compat tests broke on `notes` lookup: adjust how `notes` flows through the winning stage entry per the decision above. The fix is in `_search_fallback`'s per-stage `notes=` arguments, not in the tests.

- [ ] **Step 5: Run the rest of the suite**

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=short -q -m "not live_api"
```

Expected: `test_async_verifier.py` is now red because `_search_fallback_async` is still on Phase 1's shape. That gets fixed in Task 4.

- [ ] **Step 6: Commit**

```powershell
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "refactor(v0.3): Phase 2 per-stage instrumentation of sync fallback

opinion_search, recap_document_search, and recap_docket_search each get
their own ResolutionPathEntry in _search_fallback. _build_fallback_result
no longer touches the builder; it picks the winning candidate from the
pooled stages and finalizes the result. Path shape is asserted by 8 new
tests covering hit/miss/error variants and the state-court RECAP guard."
git push
```

---

### Task 4: Mirror per-stage instrumentation in the async fallback

**Files:**
- Modify: `src/citation_verifier/verifier.py`
- Modify: `tests/test_async_verifier.py`

- [ ] **Step 1: Mirror `_search_fallback`'s Task 3 changes into `_search_fallback_async`**

The async path is structurally identical to the sync path; mirror the per-stage instrumentation one-for-one. Each `with builder.stage(...) as t:` block becomes the same `with builder.stage(...) as t:` in the async method (it's a sync context manager — async generators are not needed for what's inside the block). The only async piece is `await async_client.search_opinions(...)` / `await async_client.search_recap(...)`.

- [ ] **Step 2: Add async path-shape parity tests**

Add to `tests/test_async_verifier.py` (a new class):

```python
class TestAsyncResolutionPathShape:
    """Phase 2: assert async path produces the same resolution_path
    shape as the sync path. Per-stage parity is the load-bearing
    invariant for the sync/async/batch parity test in Task 7."""

    def test_async_citation_lookup_hit_one_entry(self):
        client = AsyncMock(spec=AsyncCourtListenerClient)
        client.citation_lookup.return_value = [{
            "clusters": [{"id": 100, "case_name": "Foo v. Bar", "absolute_url": "/opinion/100/"}],
        }]
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        verifier = CitationVerifier()
        result = asyncio.run(verifier.verify_async(client, "100 U.S. 1 (2020)"))

        assert len(result.resolution_path) == 1
        assert result.resolution_path[0].stage == StageName.citation_lookup
        assert result.resolution_path[0].verdict == StageVerdict.resolved

    def test_async_all_stages_miss(self):
        client = AsyncMock(spec=AsyncCourtListenerClient)
        client.citation_lookup.return_value = []
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        verifier = CitationVerifier()
        result = asyncio.run(verifier.verify_async(
            client, "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)",
        ))

        stages = [e.stage for e in result.resolution_path]
        assert stages[0] == StageName.citation_lookup
        assert StageName.opinion_search in stages
        assert result.status == Status.NOT_FOUND
```

Add `from citation_verifier.models import StageName, StageVerdict` to the imports if not already present.

- [ ] **Step 3: Run async tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_async_verifier.py -v`
Expected: all tests pass (Phase 1's ~29 parity tests + the 2 new shape tests).

- [ ] **Step 4: Commit**

```powershell
git add src/citation_verifier/verifier.py tests/test_async_verifier.py
git commit -m "refactor(v0.3): Phase 2 per-stage instrumentation in async fallback

_search_fallback_async mirrors _search_fallback's per-stage
builder.stage(...) blocks. Async path-shape parity asserted by 2 new
tests; sync/async parity test (Task 7) will exercise the surface more
heavily once verify_batch is also instrumented."
git push
```

---

### Task 5: Instrument `verify_batch` and `_batch_citation_lookup`

**Files:**
- Modify: `src/citation_verifier/verifier.py`
- Modify: `tests/test_async_verifier.py`

The batch path takes a different shape than single-citation: `_batch_citation_lookup` collapses many citations into one network call. For path-instrumentation purposes, each citation in the batch gets its *own* `ResolutionPathBuilder`; the citation-lookup entry that lands in its path describes the batch lookup's outcome *for that citation*, not the global request. Citations with a batch hit get a one-entry path (`citation_lookup`, resolved). Citations without a batch hit fall through to `_search_fallback_async` and accumulate additional entries.

- [ ] **Step 1: Write failing tests for batch path shape**

Add to `tests/test_async_verifier.py`:

```python
class TestBatchPathShape:
    def test_batch_hits_produce_one_entry_paths(self):
        verifier = CitationVerifier()
        async def _run():
            with patch.object(verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={
                                  0: {"id": 100, "case_name": "Foo v. Bar"},
                                  1: {"id": 200, "case_name": "Baz v. Qux"},
                              })):
                return await verifier.verify_batch(
                    ["Foo v. Bar, 100 U.S. 1 (2020)",
                     "Baz v. Qux, 200 U.S. 2 (2021)"]
                )
        results = asyncio.run(_run())
        for r in results:
            assert len(r.resolution_path) == 1
            assert r.resolution_path[0].stage == StageName.citation_lookup
            assert r.resolution_path[0].verdict == StageVerdict.resolved
            # Batch-hit confidence is 1.0 (same as single citation_lookup hit)
            assert r.resolution_path[0].confidence == 1.0

    def test_batch_miss_falls_through_to_fallback_with_path(self):
        verifier = CitationVerifier()
        async def _run():
            # Mock the batch call to return empty (miss for all).
            # _search_fallback_async will be called for each citation.
            with patch.object(verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={})), \
                 patch("citation_verifier.verifier.AsyncCourtListenerClient") as MockClient:
                client = AsyncMock()
                client.search_opinions.return_value = []
                client.search_recap.return_value = []
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = client
                return await verifier.verify_batch(
                    ["Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)"]
                )
        results = asyncio.run(_run())
        r = results[0]
        # Batch-miss path: citation_lookup (no_match) + opinion_search (no_match) at minimum.
        assert r.resolution_path[0].stage == StageName.citation_lookup
        assert r.resolution_path[0].verdict == StageVerdict.no_match
        assert any(e.stage == StageName.opinion_search for e in r.resolution_path)
```

- [ ] **Step 2: Instrument `verify_batch`**

The batch-hits section currently calls `_process_citation_lookup_hit(stripped[idx], parsed_list[idx], cluster)`. Phase 2 needs this to operate on a per-citation builder. Wrap each hit in a fresh builder, open a `citation_lookup` stage block with the synthesized `clusters_returned=1` summary (the batch-call response doesn't surface a "clusters returned for this specific citation" count directly), and call `_process_citation_lookup_hit(builder, token, ...)`.

```python
# Inside verify_batch, replace the batch-hit loop:
for idx, cluster in batch_hits.items():
    builder = ResolutionPathBuilder()
    with builder.stage(
        StageName.citation_lookup,
        query={"text": stripped[idx][:200], "via": "batch"},
    ) as t:
        results[idx] = self._process_citation_lookup_hit(
            builder, t, stripped[idx], parsed_list[idx], cluster, clusters_returned=1,
        )
    # _process_citation_lookup_hit sets t.resolved(...) and calls
    # _finalize_result internally, so results[idx] is the finished
    # VerificationResult.
    completed += 1
    if progress_callback:
        progress_callback(completed, total)
```

The miss-fallback section is already correct — it calls `_search_fallback_async`, which now (Task 4) creates and threads its own builder internally via `verify_async` … *except* it doesn't, because `_search_fallback_async` is currently called directly from `verify_batch`'s `_fallback()` helper, bypassing `verify_async`. So the batch fallback section must also create a per-citation builder, open the `citation_lookup` stage block, set `t.no_match(raw_response_summary={"clusters_returned": 0, "via": "batch"})`, then call `_search_fallback_async(client, ..., builder, ...)` to continue accumulating entries:

```python
# Inside verify_batch's fallback section:
async def _fallback(idx: int) -> None:
    nonlocal completed
    builder = ResolutionPathBuilder()
    with builder.stage(
        StageName.citation_lookup,
        query={"text": stripped[idx][:200], "via": "batch"},
    ) as t:
        t.no_match(raw_response_summary={"clusters_returned": 0, "via": "batch"})
    results[idx] = await self._search_fallback_async(
        client, stripped[idx], parsed_list[idx], builder=builder,
    )
    completed += 1
    if progress_callback:
        progress_callback(completed, total)
```

This means `_search_fallback_async`'s signature changes to accept an optional `builder: ResolutionPathBuilder | None = None`. When `None`, create a fresh one (the path through `verify_async`). When passed, accumulate onto it (the path through `verify_batch`). Mirror this for `_search_fallback` if you want symmetric APIs, but it's not strictly required since the sync path doesn't have a batch entry point.

- [ ] **Step 3: Run batch tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_async_verifier.py::TestBatchPathShape -v`
Expected: 2 pass.

- [ ] **Step 4: Run full async test file**

Run: `venv\Scripts\python.exe -m pytest tests/test_async_verifier.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/citation_verifier/verifier.py tests/test_async_verifier.py
git commit -m "refactor(v0.3): Phase 2 batch path instrumentation

verify_batch creates a per-citation ResolutionPathBuilder for each
batch hit and miss. Batch hits get a one-entry path
(citation_lookup, resolved, via=batch). Batch misses thread the
builder through _search_fallback_async so the citation_lookup
no_match entry leads, followed by the fallback stages."
git push
```

---

### Task 6: Path-shape coverage tests for raw_response_summary schemas

The per-stage shapes pinned in the plan's "Per-stage raw_response_summary shapes" table need explicit test coverage so future changes can't silently drift them. Most are already exercised by Tasks 2–5's tests; this task adds a parametrized test that asserts the key set for each (stage, verdict) tuple seen in the path.

**Files:**
- Modify: `tests/test_verifier.py`

- [ ] **Step 1: Add a parametrized schema test**

Add `REQUIRED_KEYS` at module level (above the `TestResolutionPathShape` class) and the new test methods inside the class:

```python
# tests/test_verifier.py — module-level constant (above TestResolutionPathShape)

REQUIRED_KEYS = {
    (StageName.citation_lookup, StageVerdict.resolved): {
        "matched_cluster_id", "matched_case_name", "clusters_returned",
    },
    (StageName.citation_lookup, StageVerdict.no_match): {"clusters_returned"},
    (StageName.citation_lookup, StageVerdict.errored): {"error_type"},
    (StageName.opinion_search, StageVerdict.resolved): {
        "candidate_count", "best_score", "best_case_name", "best_cluster_id",
    },
    (StageName.opinion_search, StageVerdict.no_match): {"candidate_count"},
    (StageName.opinion_search, StageVerdict.errored): {"error_type"},
    (StageName.recap_document_search, StageVerdict.resolved): {
        "docket_count", "best_score", "best_docket_id", "best_case_name",
    },
    (StageName.recap_document_search, StageVerdict.no_match): {"docket_count"},
    (StageName.recap_document_search, StageVerdict.errored): {"error_type"},
    (StageName.recap_docket_search, StageVerdict.resolved): {
        "docket_count", "best_score", "best_docket_id", "best_case_name",
    },
    (StageName.recap_docket_search, StageVerdict.no_match): {"docket_count"},
    (StageName.recap_docket_search, StageVerdict.errored): {"error_type"},
}


# Inside TestResolutionPathShape (alongside the other test methods):

@pytest.mark.parametrize("scenario_name,citation,client_kwargs,quick_only", [
    (
        "citation_lookup_resolved",
        "Foo v. Bar, 100 U.S. 1 (2020)",
        {"citation_lookup": [{"clusters": [
            {"id": 1, "case_name": "Foo v. Bar", "absolute_url": "/opinion/1/"},
        ]}]},
        False,
    ),
    (
        "citation_lookup_no_match_quick_only",
        "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)",
        {"citation_lookup": []},
        True,
    ),
    (
        "opinion_search_resolved",
        "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
        {"citation_lookup": [], "search_opinions": [{
            "caseName": "Foo v. Bar", "cluster_id": 200,
            "dateFiled": "2020-06-15", "court_id": "ca1",
            "absolute_url": "/opinion/200/", "citation": ["100 F.3d 100"],
            "docketNumber": "",
        }]},
        False,
    ),
    (
        "opinion_search_no_match",
        "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
        {"citation_lookup": [], "search_opinions": [], "search_recap": []},
        False,
    ),
    (
        "recap_resolved",
        "Smith v. Jones, No. 20-cv-1234 (N.D. Cal. June 15, 2020)",
        {"citation_lookup": [], "search_opinions": [], "search_recap": [{
            "caseName": "Smith v. Jones", "docket_id": 500, "court_id": "cand",
            "docket_absolute_url": "/docket/500/",
            "recap_documents": [{
                "short_description": "Opinion and order",
                "date_filed": "2020-06-15", "is_free_on_pacer": True,
                "page_count": 20, "absolute_url": "/recap/500/1/",
                "entry_date_filed": "2020-06-15",
                "entry_description": "ORDER granting motion to dismiss",
            }],
        }]},
        False,
    ),
])
def test_raw_response_summary_required_keys_per_stage_verdict(
    self, scenario_name, citation, client_kwargs, quick_only,
):
    """Every (stage, verdict) tuple has a documented minimum key set
    in raw_response_summary. Each scenario exercises a different stage
    combination; the assertion runs across every entry produced."""
    client = _make_client(**client_kwargs)
    verifier = CitationVerifier(client=client)
    result = verifier.verify(citation, quick_only=quick_only)
    assert result.resolution_path, f"{scenario_name}: empty resolution_path"
    for entry in result.resolution_path:
        required = REQUIRED_KEYS.get((entry.stage, entry.verdict))
        assert required is not None, (
            f"{scenario_name}: no required-keys spec for "
            f"({entry.stage}, {entry.verdict}) — update REQUIRED_KEYS or fix the verdict"
        )
        missing = required - entry.raw_response_summary.keys()
        assert not missing, (
            f"{scenario_name}: stage {entry.stage}, verdict {entry.verdict}: "
            f"missing keys {missing} in raw_response_summary={entry.raw_response_summary}"
        )


@pytest.mark.parametrize("error_target", [
    "citation_lookup", "search_opinions", "search_recap",
])
def test_errored_entry_carries_error_type_key(self, error_target):
    """Errored stage entries must have raw_response_summary={'error_type': ...}.
    Exercises each stage's error path independently."""
    client = _make_client(citation_lookup=[], search_opinions=[], search_recap=[])
    getattr(client, error_target).side_effect = ConnectionError("down")
    verifier = CitationVerifier(client=client)
    result = verifier.verify("Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)")
    errored = [e for e in result.resolution_path if e.verdict == StageVerdict.errored]
    assert errored, f"expected at least one errored entry when {error_target} raises"
    for e in errored:
        assert e.raw_response_summary == {"error_type": "ConnectionError"}
```

Fill in the remaining scenarios with mock overrides that exercise opinion_search resolved/no_match, recap_*_search resolved/no_match, and the errored variants (use `side_effect=ConnectionError(...)` on the relevant client method).

- [ ] **Step 2: Run schema tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_verifier.py::TestResolutionPathShape::test_raw_response_summary_required_keys_per_stage_verdict -v`
Expected: passes.

If a (stage, verdict) tuple is missing keys: fix the production code's `raw_response_summary=` argument in the relevant `builder.stage` block, not the test. The schema is the spec.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_verifier.py
git commit -m "test(v0.3): pin raw_response_summary key sets per (stage, verdict)

Per the Phase 2 plan's per-stage shapes table: every (stage, verdict)
tuple has a documented minimum key set. The parametrized test exercises
mock scenarios across all four stages and both terminal verdicts (plus
errored) and asserts presence of the required keys."
git push
```

---

### Task 7: Sync/async/batch parity test

Closes Phase 1 retrospective Q4: "instrument the resolution_path entries deeply enough to see which stage resolved a given citation, and assert sync/async/batch parity." Phase 2's instrumentation is what makes this assertion possible.

**Files:**
- Modify: `tests/test_async_verifier.py`

- [ ] **Step 1: Write the parity test**

Add a new class `TestSyncAsyncBatchPathParity`:

```python
class TestSyncAsyncBatchPathParity:
    """Same mock data should produce the same resolution_path shape
    through sync verify(), async verify_async(), and batch verify_batch().

    "Same shape" = same sequence of (stage, verdict) tuples and same
    headline_confidence. Per-entry elapsed_ms is allowed to differ.
    """

    @staticmethod
    def _shape(result):
        return (
            [(e.stage, e.verdict) for e in result.resolution_path],
            result.headline_confidence,
        )

    def test_citation_lookup_hit_parity(self):
        cite = "Obergefell v. Hodges, 576 U.S. 644 (2015)"
        lookup_payload = [{
            "clusters": [{"id": 100, "case_name": "Obergefell v. Hodges",
                          "absolute_url": "/opinion/100/"}],
        }]

        # Sync
        sync_client = MagicMock()
        sync_client.citation_lookup.return_value = lookup_payload
        sync_verifier = CitationVerifier(client=sync_client)
        sync_result = sync_verifier.verify(cite)

        # Async (single)
        async_client = AsyncMock(spec=AsyncCourtListenerClient)
        async_client.citation_lookup.return_value = lookup_payload
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_verifier = CitationVerifier()
        async_result = asyncio.run(async_verifier.verify_async(async_client, cite))

        # Batch (one citation)
        batch_verifier = CitationVerifier()
        async def _run_batch():
            with patch.object(batch_verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={0: lookup_payload[0]["clusters"][0]})):
                return await batch_verifier.verify_batch([cite])
        batch_results = asyncio.run(_run_batch())

        assert self._shape(sync_result) == self._shape(async_result) == self._shape(batch_results[0]), (
            f"sync={self._shape(sync_result)}  "
            f"async={self._shape(async_result)}  "
            f"batch={self._shape(batch_results[0])}"
        )

    def test_all_stages_miss_parity(self):
        cite = "Foo v. Bar, 999 F.3d 999 (1st Cir. 2099)"

        sync_client = MagicMock()
        sync_client.citation_lookup.return_value = []
        sync_client.search_opinions.return_value = []
        sync_client.search_recap.return_value = []
        sync_result = CitationVerifier(client=sync_client).verify(cite)

        async_client = AsyncMock(spec=AsyncCourtListenerClient)
        async_client.citation_lookup.return_value = []
        async_client.search_opinions.return_value = []
        async_client.search_recap.return_value = []
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_result = asyncio.run(
            CitationVerifier().verify_async(async_client, cite)
        )

        batch_verifier = CitationVerifier()
        async def _run_batch():
            with patch.object(batch_verifier, "_batch_citation_lookup",
                              AsyncMock(return_value={})), \
                 patch("citation_verifier.verifier.AsyncCourtListenerClient") as MockClient:
                client = AsyncMock()
                client.search_opinions.return_value = []
                client.search_recap.return_value = []
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = client
                return await batch_verifier.verify_batch([cite])
        batch_results = asyncio.run(_run_batch())

        assert self._shape(sync_result) == self._shape(async_result) == self._shape(batch_results[0])
```

- [ ] **Step 2: Run the parity test**

Run: `venv\Scripts\python.exe -m pytest tests/test_async_verifier.py::TestSyncAsyncBatchPathParity -v`
Expected: 2 pass.

If the shapes differ: find which entry point produces the divergent path and fix the instrumentation there. The expected shape is determined by the design (each stage attempted → one entry), so the bug is whichever entry point deviates from that.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_async_verifier.py
git commit -m "test(v0.3): assert sync/async/batch resolution_path parity

Closes Phase 1 retrospective Q4. Sync verify(), async verify_async(),
and batch verify_batch() must produce identical (stage, verdict)
sequences and headline_confidence values for the same mock input."
git push
```

---

### Task 8: Cache round-trip reproducibility

Per Phase 2 acceptance criterion 2: "Replaying any cached result (or any test fixture) reproduces the same path." `cache.py` (Phase 1) already serializes path entries; this task pins that behavior under Phase 2's richer entries.

**Files:**
- Create: `tests/test_cache_roundtrip.py`

- [ ] **Step 1: Write the round-trip test**

```python
# tests/test_cache_roundtrip.py
"""Phase 2: VerificationResult resolution_path survives the cache.

cache.py already serializes path entries (Phase 1 Task 2). Phase 2's
richer entries (multiple stages, raw_response_summary keys, errored
verdicts) need explicit round-trip coverage so future cache changes
don't silently drop them.
"""
from __future__ import annotations

import json
from pathlib import Path

from citation_verifier.cache import VerificationCache
from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    TextSource,
    VerificationResult,
    Warning,
    WarningCategory,
)


def _make_multi_stage_result() -> VerificationResult:
    return VerificationResult(
        citation_as_written="Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)",
        parsed_citation=None,
        status=Status.VERIFIED,
        final_ids=FinalIds(
            cluster_id=200,
            opinion_id=None,
            docket_id=None,
            recap_document_id=None,
            absolute_url="https://www.courtlistener.com/opinion/200/",
            text_source=TextSource.opinion_plain_text,
        ),
        resolution_path=[
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={"text": "Foo v. Bar, 100 F.3d 100 (1st Cir. 2020)"},
                raw_response_summary={"clusters_returned": 0},
                verdict=StageVerdict.no_match,
                confidence=None,
                notes=None,
                elapsed_ms=42,
            ),
            ResolutionPathEntry(
                stage=StageName.opinion_search,
                query={"q": "Foo v. Bar", "court": "ca1", "filed_after": "2019-01-01", "filed_before": "2021-12-31"},
                raw_response_summary={
                    "candidate_count": 3, "best_score": 0.78,
                    "best_case_name": "Foo v. Bar", "best_cluster_id": 200,
                },
                verdict=StageVerdict.resolved,
                confidence=0.78,
                notes="Date close: cited 2020 vs filed 2020-06-15",
                elapsed_ms=180,
            ),
        ],
        warnings=[Warning(
            category=WarningCategory.date_close_not_exact,
            message="Date close: cited 2020 vs filed 2020-06-15",
            details=None,
        )],
        gates_failed=[],
        timing={"total_ms": 222},
        cache_hit=False,
    )


def test_resolution_path_survives_cache_round_trip(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache = VerificationCache(path=cache_path)
    original = _make_multi_stage_result()

    cache.put(original.citation_as_written, original)
    hydrated = cache.get(original.citation_as_written)

    assert hydrated is not None
    # Path length, stages, verdicts preserved
    assert len(hydrated.resolution_path) == 2
    assert [e.stage for e in hydrated.resolution_path] == [
        StageName.citation_lookup, StageName.opinion_search,
    ]
    assert [e.verdict for e in hydrated.resolution_path] == [
        StageVerdict.no_match, StageVerdict.resolved,
    ]
    # raw_response_summary keys and values preserved
    assert hydrated.resolution_path[1].raw_response_summary["best_score"] == 0.78
    assert hydrated.resolution_path[1].raw_response_summary["best_case_name"] == "Foo v. Bar"
    # confidence, notes, elapsed_ms preserved
    assert hydrated.resolution_path[1].confidence == 0.78
    assert hydrated.resolution_path[1].notes == "Date close: cited 2020 vs filed 2020-06-15"
    assert hydrated.resolution_path[1].elapsed_ms == 180
    # headline_confidence accessor still works after hydration
    assert hydrated.headline_confidence == 0.78


def test_errored_stage_survives_cache_round_trip(tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache = VerificationCache(path=cache_path)
    original = VerificationResult(
        citation_as_written="x",
        parsed_citation=None,
        status=Status.NOT_FOUND,
        final_ids=FinalIds(None, None, None, None, None, None),
        resolution_path=[
            ResolutionPathEntry(
                stage=StageName.citation_lookup,
                query={"text": "x"},
                raw_response_summary={"error_type": "ConnectionError"},
                verdict=StageVerdict.errored,
                confidence=None,
                notes="ConnectionError: network down",
                elapsed_ms=100,
            ),
        ],
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )
    cache.put(original.citation_as_written, original)
    hydrated = cache.get(original.citation_as_written)
    assert hydrated is not None
    assert hydrated.resolution_path[0].verdict == StageVerdict.errored
    assert hydrated.resolution_path[0].raw_response_summary == {"error_type": "ConnectionError"}
    assert hydrated.resolution_path[0].notes == "ConnectionError: network down"
```

- [ ] **Step 2: Run round-trip tests**

Run: `venv\Scripts\python.exe -m pytest tests/test_cache_roundtrip.py -v`
Expected: 2 pass. If a field doesn't survive the round-trip: the bug is in `cache.py`'s `_serialize_path_entry` / `_hydrate_path_entry` (or `_to_dict` / `_from_dict`). Fix it under this task; do not defer.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_cache_roundtrip.py
# If cache.py needed a fix, add it too:
# git add src/citation_verifier/cache.py
git commit -m "test(v0.3): pin resolution_path cache round-trip behavior

Phase 2 acceptance criterion 2: replaying any cached result reproduces
the same path. Two tests exercise a multi-stage resolved result and an
errored-stage NOT_FOUND result through VerificationCache.put/get and
assert every ResolutionPathEntry field survives."
git push
```

---

### Task 9: Phase 2 acceptance gate

Per design v2 §3 Phase 2 acceptance:
1. Every `VerificationResult` produced has a non-empty `resolution_path`.
2. Replaying any cached result (or any test fixture) reproduces the same path.
3. New tests verify path shape for each fallback scenario.

(1) and (3) are covered by Tasks 1–7's added tests. (2) is covered by Task 8. This task runs the whole suite, runs the live-API tests deliberately (deselect-then-include is the deal from Setup §0.2), and tags the phase.

**Files:**
- None modified; this is a verification task.

- [ ] **Step 1: Full test suite (no live API)**

```powershell
venv\Scripts\python.exe -m pytest tests/ --tb=short -v -m "not live_api"
```

Expected: all tests pass + 4 xfail (the cluster-ID drift cases preserved from Phase 1). Zero failures.

- [ ] **Step 2: Live-API tests (slow, requires `.env`)**

Per Phase 1 retrospective S5: confirm `.env` is present in the worktree root before running live tests. Per S6: live-API tests can be flaky under rate-limit; re-run individual failures alone before treating them as regressions.

```powershell
test-path .env   # PowerShell — should print True
venv\Scripts\python.exe -m pytest tests/ -v -m "live_api"
```

Expected: live-API tests pass (or fail in pre-existing-flakiness ways that re-run cleanly). If any live-API test reports a *new* regression — e.g., a previously-passing case now returning a path that doesn't include the expected stage — investigate before tagging.

- [ ] **Step 3: Phase 2 acceptance assertion — every result has a non-empty resolution_path**

This is the headline acceptance criterion. Run a smoke that exercises a known-real citation and inspects the path:

```powershell
venv\Scripts\python.exe -m citation_verifier "Obergefell v. Hodges, 576 U.S. 644 (2015)"
```

Expected output should now include a non-empty resolution_path. If the CLI's text output doesn't surface the path, add a JSON-output mode flag to inspect via:

```powershell
venv\Scripts\python.exe -c "import asyncio; from citation_verifier.verifier import CitationVerifier; r = CitationVerifier().verify('Obergefell v. Hodges, 576 U.S. 644 (2015)'); print([(e.stage.value, e.verdict.value, e.confidence) for e in r.resolution_path])"
```

Expected: `[('citation_lookup', 'resolved', 1.0)]` (a one-stage path for a clean citation-lookup hit).

- [ ] **Step 4: Tag the phase**

```powershell
git tag refactor/phase-2-acceptance
git push origin refactor/phase-2-acceptance
```

- [ ] **Step 5: Write the Phase 2 retrospective**

Per CLAUDE.md workflow rules ("Never write important information only to Claude memory"), save the retrospective to `docs/retrospectives/2026-MM-DD-refactor-v0.3-phase-2.md`. Mirror the shape of Phase 1's retrospective (`docs/retrospectives/2026-05-20-refactor-v0.3-phase-1.md`): what landed, time breakdown, surprises (what the plan didn't survive contact with code), open questions to fold into Phase 3's plan, notes for whoever writes Phase 3.

Phase 3 will need to know:
- How the per-stage `notes` field flows through `_finalize_result` (does the test-side `_diagnostics` classifier still need it on `path[-1]`? — if Phase 3 promotes WarningCategory members for the legacy categories, the classifier goes away anyway).
- Whether the `partial` verdict was used anywhere in Phase 2 (it's defined; Phase 3 will use it for `VERIFIED_PARTIAL`).
- Any caption-investigation entry points Phase 3 should slot into (likely after a `WrongCase`-candidate citation_lookup hit, before finalizing).

- [ ] **Step 6: Commit the retrospective**

```powershell
git add docs/retrospectives/2026-MM-DD-refactor-v0.3-phase-2.md
git commit -m "docs: Phase 2 retrospective for refactor/v0.3"
git push
```

---

## Acceptance summary

When Phase 2 is complete:

- `ResolutionPathBuilder` exists in `src/citation_verifier/resolution_path.py` with unit tests in `tests/test_resolution_path.py`.
- Every entry into `verify()`, `verify_async()`, and `verify_batch()` produces a `VerificationResult` whose `resolution_path` is non-empty.
- Each stage attempted (`citation_lookup`, `opinion_search`, `recap_document_search`, `recap_docket_search`) produces one `ResolutionPathEntry` with the per-stage `raw_response_summary` shape documented in this plan. Stages not attempted (per the §2.5 guards) produce no entry.
- Errored stages produce a path entry with `verdict=errored` and `raw_response_summary={"error_type": ...}`. The verifier still falls through to the next stage as today; the §2.8 internal API-error gate (forcing `VERIFICATION_INCOMPLETE`) is Phase 4.
- Sync, async, and batch produce identical `(stage, verdict)` sequences and `headline_confidence` for the same input.
- Round-tripping a multi-stage `VerificationResult` through `VerificationCache` preserves every `ResolutionPathEntry` field.
- The `refactor/phase-2-acceptance` tag is pushed.
- The Phase 2 retrospective is written and committed.

Phase 3's plan (richer-status detection, caption investigation, `WarningCategory` promotion + classifier consolidation) is the next plan to write, and is written *after* this retrospective, when the implementer knows what shipped.
