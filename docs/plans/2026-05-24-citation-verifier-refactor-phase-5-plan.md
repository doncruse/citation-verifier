# Citation Verifier Refactor v0.3 — Phase 5 Implementation Plan (Consumer Compatibility Sweep)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically audit every consumer of the v0.3 schema before the `refactor/v0.3` → `main` merge, fix the regressions the audit uncovers, and add lightweight integration tests so the next schema change doesn't re-enter the same hole. Phase 5 ends when (a) every consumer surface in `docs/consumer-surface-manifest.md` is verified v0.3-clean, (b) the new web-app integration tests pass, and (c) Phase 4's deferred Task 10 (merge to main with `v0.3.0` tag) is unblocked.

**Architecture:** Phase 5 adds no new schema. It (1) introduces a `tests/test_web_app.py` integration harness using FastAPI's `TestClient` + a stubbed `AsyncCourtListenerClient`, plus a static `tests/test_frontend_status_coverage.py` that greps each `web/static/*.html` JS switch for every `Status` enum value; (2) re-routes `/api/qc/run-batch` (and restores `/api/verify`) through the public `verifier.verify_batch()` API instead of private helpers; (3) extends the JS retry/filter/coverage logic in the three frontend pages to recognize the 5 v0.3-new statuses; (4) updates the iterative-workflow scripts (`verify_from_csv.py`'s "needs QC" highlight, `audit_misses_main`'s retry trigger, `verify_sample_citations.py`'s schema references); (5) reconciles README.md / scratch/README.md / inline comments with the v0.3 shape; and (6) leaves behind `docs/consumer-surface-manifest.md` so future schema changes have a checklist instead of needing another retro to discover its consumers. No `src/citation_verifier/models.py` or `verifier.py` core changes — Phase 4 froze the schema, Phase 5 only teaches consumers.

**Tech Stack:** Python 3.10+, `pytest`, `pytest-asyncio`, FastAPI's `TestClient` (from `starlette.testclient`), `unittest.mock`, the existing web app (`web/app.py`), frontend pages (`web/static/{get,index,qc}.html`), iterative-workflow CLI (`tests/verify_from_csv.py`), batch script (`tests/verify_sample_citations.py`), public API (`src/citation_verifier/__main__.py`'s `audit-misses` subcommand), and the new manifest (`docs/consumer-surface-manifest.md`).

---

## Phase 5 scope: the consumer-surface audit

The Phase 4 retro Addendum (`docs/retrospectives/2026-05-24-refactor-v0.3-phase-4.md` §A1–A3 + "Lessons for Phase 5") names the failure mode: Phase 4's plan assumed `web/app.py` "produces the new statuses correctly" without a test. Three regressions slipped past: a broken private-helper call in `/api/verify`, v0.2 schema references in `verify_from_csv.py`, and v0.2-only JS switches across all three frontend pages. Each got an addendum fix on `refactor/v0.3` (commits `e6bf6ca`, `6a21e5f`, `3316fd2`), but the pattern argues for a systematic audit rather than another round of ad-hoc smoke.

Phase 5's audit (performed during plan-writing, see `docs/consumer-surface-manifest.md` produced by Task 11) found these additional consumer-side gaps still on `refactor/v0.3` HEAD (`abf38e2`):

| # | Surface | Severity | Symptom |
|---|---|---|---|
| C1 | `web/app.py:1465-1495` `/api/qc/run-batch` | **Critical** | Still calls `_verifier._batch_citation_lookup(client, batch_citations)` + `_verifier._process_citation_lookup_hit(cite_text, parsed, batch_hits[i])` with the OLD v0.2 3-arg signature. Same regression as A1 but in the QC batch endpoint. The addendum only fixed `/api/verify`. Every QC batch hit raises `TypeError`. |
| C2 | `tests/verify_sample_citations.py:135-141, 208-220` | **Critical** | Hardcoded results dict has only v0.2 statuses (`{VERIFIED, LIKELY_REAL, POSSIBLE_MATCH, NOT_FOUND, SKIPPED}`); KeyError on any of the 5 v0.3-new statuses. Lines 208-220 read v0.2 fields (`result.matched_url`, `result.matched_cluster_id`, `result.confidence`, `result.diagnostics`) that don't exist on v0.3 `VerificationResult`. AttributeError on the first verified result. |
| C3 | `web/static/qc.html:378-385` filter chips | **Important** | Chips only cover `ALL / NOT_FOUND / POSSIBLE_MATCH / LIKELY_REAL / VERIFIED / SKIPPED`. The 5 v0.3-new statuses (`VERIFIED_PARTIAL/VIA_RECAP/DOCKET_ONLY/WRONG_CASE/VERIFICATION_INCOMPLETE`) have no chip — silently filtered out of the QC review view. The default `activeFilters = ['NOT_FOUND', 'POSSIBLE_MATCH']` (line 421) excludes them too, so a QC reviewer cannot see WRONG_CASE rows that demand the most attention. |
| C4 | `web/static/get.html:778` deep-search retry | **Important** | Deep-search retry triggers only on `data.status === 'NOT_FOUND' \|\| data.status === 'ERROR'`. `VERIFICATION_INCOMPLETE` is by design the infra-failure case (CL outage / 5xx / timeout per design §2.8) — exactly the case retry was built for. Currently a transient CL hiccup leaves the citation stuck at INCOMPLETE forever; the reviewer has no path to retry except a manual page reload. |
| C5 | `tests/verify_from_csv.py:429` "needs QC" highlight | **Important** | Selects only `("NOT_FOUND", "POSSIBLE_MATCH")` for the post-run QC review summary. `WRONG_CASE` (cite resolves to a different case — the single most important class to QC) and `VERIFICATION_INCOMPLETE` (infra error — needs rerun) are silently omitted from the report. The reviewer following the master workflow per `CLAUDE.md`'s post-run checklist may not realize they exist in the sidecar. |
| C6 | `src/citation_verifier/__main__.py:771` `audit-misses` retry | **Important** | The two-pass `audit-misses` CLI selects which quick-results need the full pipeline via `r.status == Status.NOT_FOUND`. By the design §2.8 rationale (the quick-pass infra failure is exactly what the full pipeline can recover from), `Status.VERIFICATION_INCOMPLETE` should also retry. |
| C7 | `src/citation_verifier/__main__.py:264-265` single-citation CLI exit code | **Important** | Returns `1` on any `Status.NOT_FOUND` result, `0` otherwise. `VERIFICATION_INCOMPLETE` currently exits `0` — a CI script checking exit code treats an infrastructure failure as success. By the §2.8 "fail-closed at verifier integrity" rule, an INCOMPLETE result should also non-zero. (Verifier semantics: "we couldn't tell" is not the same as "we verified.") |
| C8 | `README.md:37-38, 121-122` | **Documentation** | Public-facing README still references v0.2 status taxonomy (`LIKELY_REAL`, `POSSIBLE_MATCH`) and v0.2 schema (`result.matched_url`, `result.diagnostics`). The first contact a new user has with the project. |
| C9 | `scratch/README.md:26, 52, 73` | **Documentation** | Master iterative workflow doc references v0.2 statuses in the CSV column legend and post-run checklist. Cross-machine workflow doc per CLAUDE.md. |
| C10 | `web/app.py:43-44` inline comment | **Documentation** | Comment claims the frontend JS "still recognizes the legacy v0.2 names (LIKELY_REAL, POSSIBLE_MATCH) for backward compat with older JSON sidecars on disk." Partially true (the QC page's `badgeClass`/`statusLabel` still has cases for these — see Task 3 review focus) but misleading: `/api/verify` doesn't emit them, so this comment describes a phantom contract. Worth a one-line clean-up. |
| C11 | Web app integration test coverage | **Infrastructure** | **Zero integration tests exist** for any FastAPI endpoint. This is the root cause of A1 slipping past Phase 4. Phase 5's HEADLINE Task 1 adds them. |

### Verified-already-fine surfaces (audit confirmed no work needed)

The audit also confirmed the following don't need work — capturing this so Task 11's manifest can record the affirmative finding rather than leaving them ambiguous:

- `src/citation_verifier/cache.py` — `_from_dict` catches `(KeyError, ValueError)` from `Status(d["status"])`, so old v0.2-shape cache entries gracefully fall through to cache-miss + re-verify. No migration of the on-disk `.citation_cache.json` is required.
- JSON sidecars under `tests/data/results/` — the QC page's `/api/qc/run/{filename}` enriches stored sidecar dicts with current CSV state. Old v0.2-status sidecars render via the same `badgeClass`/`statusLabel` JS that already handles both shapes (post-addendum-fix `3316fd2`). No migration needed.
- Replit `MODE=public` deployment (`web/app.py:210-225` `_BlockQCMiddleware`) — the gate blocks paths by URL prefix (`/qc`, `/debug`, `/api/flag-for-flp`, `/api/qc/*`) and does not depend on schema. v0.3-orthogonal; no work needed. Confirm in Task 11 by listing the gate's URL set against the public-mode contract.
- `src/citation_verifier/brief_pipeline.py` — Phase 4 Task 8 already taught it the v0.3 statuses (`_STATUS_BADGE_FALLBACK` + `_DOWNLOADABLE_STATUSES`). Verified by audit: every `Status.` reference in the file is v0.3-correct.
- `src/citation_verifier/__main__.py` v0.3 schema use — every line that previously held v0.2 field names was migrated during the refactor; the file passes a `grep -E 'result\\.(matched_url|matched_cluster_id|confidence|diagnostics)'` check with zero hits.

### Out of Phase 5 scope (deliberate non-work)

- **Web app `/api/qc/opinion-text` text fallback chain** (`web/app.py:1131-1212`). Its `plain_text -> html_with_citations -> html` chain is missing `html_lawbox / html_columbia / html_anon_2020 / xml_harvard` per the canonical CLAUDE.md chain. This is a **pre-existing** bug (predates v0.3); the QC page's opinion-text-peek panel underserves state opinions. **NOT a v0.3 regression** — left as roadmap. Tracked in Task 11's manifest "known-issues" section so it isn't forgotten, but does not block the merge.
- **`_STATUS_DISPLAY` dict in `web/app.py:45-53`**. Defined but no references in `web/app.py`. Either dead code or intended for a future templated-response feature that wasn't wired. Removing it is a small clean-up; not regression-fixing work. Defer to roadmap unless the implementer notices an active reference during Task 1.
- **`pyproject.toml` version bump 0.2.0 → 0.3.0**. Stays with the original Task 10 (merge-to-main); Phase 5 does NOT bump it. Phase 5 ends parked on a new `refactor/phase-5-acceptance` tag with `version = "0.2.0"` unchanged.
- **`scratch/casedev/*.py`** (`test_waterfall.py`, `waterfall_batch_50.py`). These reference v0.2 fields (`result.matched_url`, `LIKELY_REAL`, `POSSIBLE_MATCH`) but are one-off exploratory scripts from a March 2026 case.dev API evaluation (per `scratch/casedev/README.md`). Not active code paths. **Document in Task 11 manifest as known v0.2 dust**; do not modify.
- **Caller-policy gates** (`gates: list[GateSpec]` parameter on entry points). Still deferred per Phase 4's out-of-scope. No work in Phase 5.

---

## Setup

### §0.1 Worktree, branch, and Phase 4-acceptance baseline confirmation

Phase 5 work happens in the existing worktree at `.claude/worktrees/refactor-v0.3` on branch `refactor/v0.3`, currently at HEAD `abf38e2` (the retro-addendum commit, three commits past the original Phase 4 acceptance retro at `a1adfe8` and one commit past the last addendum fix at `3316fd2`). The `refactor/phase-4-acceptance` tag points at `3316fd2`.

- [ ] **Step 1: Confirm worktree, branch, tag, and addendum-fix commit chain**

```
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git log --oneline -8
```

Expected: working tree at `.claude/worktrees/refactor-v0.3`, branch `refactor/v0.3`, HEAD at `abf38e2` (or descendant), `git log -8` shows in reverse chronological order: `abf38e2 docs(v0.3): Phase 4 retro addendum`, `3316fd2 fix(v0.3): Task 9 addendum -- frontend JS`, `6a21e5f fix(v0.3): Task 9 addendum -- verify_from_csv.py`, `e6bf6ca fix(v0.3): Task 9 addendum -- web app /api/verify`, `a1adfe8 docs(v0.3): Phase 4 retrospective`, `d6923b7 feat(v0.3): Task 8`, `37b36d2 feat(v0.3): Task 5`, `7a335a6 docs(v0.3): Task 7`.

```
git status --short
```

Expected: the same two long-standing modifications shown in the Phase 4 plan's §0 — `M briefs/fivehouse-v-dod/report.html` and `M briefs/fivehouse-v-dod/verification_results.csv`. Leave untouched (Phase 5 does not modify briefs/).

- [ ] **Step 2: Pull origin and check for main drift**

```
git fetch origin
git log --oneline --max-count=10 origin/main ^HEAD
```

If the second command prints commits, merge them:

```
git merge --no-edit origin/main
```

If the merge produces conflicts in `src/citation_verifier/`, `tests/`, or `web/`, stop and surface them. The cross-repo benchmark is still pinned to `v0.2.0` (per CHANGELOG v0.3.0 "Cross-repo consumers"), so no schema-changing work is expected on `origin/main`. If the merge is clean or empty, proceed.

- [ ] **Step 3: Confirm venv + .env are present**

```
venv/Scripts/python.exe --version
test -f .env && echo ".env present" || echo ".env MISSING -- copy from primary checkout before live-API tests"
```

Expected: Python 3.10+, `.env present`. The worktree's `.env` is path-explicit per `client.py`'s `load_dotenv` call.

### §0.2 Pre-Phase-5 test baselines

Phase 5's HEADLINE Task 1 adds a new integration test file (`tests/test_web_app.py`) and a new static frontend coverage test (`tests/test_frontend_status_coverage.py`). The other tasks fix regressions and add small unit tests where appropriate. Establish per-suite baselines so per-task deltas can be diffed cleanly.

- [ ] **Step 4: Capture the non-live baseline**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected (per the Phase 4 retro): `362 passed, 5 skipped, 154 deselected, 0 failed`. Record actual count.

- [ ] **Step 5: Capture the live-API baseline (only if `.env` has `COURTLISTENER_API_TOKEN`)**

```
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py tests/test_phase3_corpus_acceptance.py -v -m live_api
```

Expected: all 141 corpus tests + 5 mock-runnable tests + 7 false_negatives tests pass (153 total). This is also the Phase 5 CL-drift pre-flight: if anything has gone red since Phase 4 acceptance, triage per the Phase 4 §0.4 protocol (cluster-ID drift / status change / transient outage) and absorb as a §0.3 fixture-pin refresh task.

### §0.3 Corpus-drift pin refresh (only if §0.2 Step 5 found drift)

Identical protocol to the Phase 4 plan's §0.4: edit `tests/data/refactor_corpus.json`, set `phase5_pin_refresh_note` on each touched fixture, commit:

```
git add tests/data/refactor_corpus.json
git commit -m "test(v0.3): Phase 5 pre-flight corpus pin refresh for CL drift"
git push origin refactor/v0.3
```

If §0.2 Step 5 was green, skip.

- [ ] **Step 6: Commit §0 outcomes (none expected unless §0.3 ran)**

If `§0.3` ran, the commits already happened. The baseline runs produce no commitable artifacts. The merge from Step 2, if it ran, is its own auto-commit from `git merge`.

```
git push origin refactor/v0.3
```

---

## File Structure

Phase 5 modifies and creates these files. Each task names its exact targets.

**Created:**
- `tests/test_web_app.py` — FastAPI `TestClient`-driven integration tests for `/api/verify`, `/api/qc/run-batch`, `/api/qc/runs`, `/api/qc/run/{filename}`, `/api/qc/save`, `/api/flag-for-flp`, `/api/download-pdfs`, `/api/download-texts`, `/api/download-htmls`, and the v0.3-schema-contract assertions on `/api/verify` SSE event payloads. Uses a stubbed `AsyncCourtListenerClient` to keep the suite CI-safe (no live CL needed). (Task 1)
- `tests/test_frontend_status_coverage.py` — static test that loads each of `web/static/get.html`, `index.html`, `qc.html`, greps the JS switch statements (`badgeClass`, `statusLabel`, and the entry-point `case '...'` blocks), and asserts every member of `Status` appears as a case. Plus a parallel check for filter chips in `qc.html`. (Task 3)
- `docs/consumer-surface-manifest.md` — checklist artifact enumerating every consumer of `VerificationResult`. For each row: file/line, what fields it reads, what statuses it expects, last-verified phase, and a `^audit-on-next-schema-change` flag. The manifest is what makes the next status-taxonomy or `final_ids` change a 30-minute audit instead of a multi-session retro discovery. (Task 11)
- `docs/retrospectives/2026-05-2X-refactor-v0.3-phase-5.md` — Phase 5 retrospective. Filename uses actual completion date. (Task 12)

**Modified:**
- `web/app.py` — (a) `/api/qc/run-batch`: replace the `_batch_citation_lookup` + `_process_citation_lookup_hit` private-helper batch path (lines 1460-1574) with a single `verifier.verify_batch()` call that gives the same batching benefit without coupling to v0.3-internal helper signatures. (b) `/api/verify`: restore batching via the same `verifier.verify_batch()` path (lines 400-455 currently route through per-citation `verify_async()` per the addendum-`e6bf6ca` fix; switching back to `verify_batch()` recovers the API-call savings noted in the Phase 4 retro Addendum §A1). (c) Inline comment at line 42-44: drop the misleading "v0.2 backward compat" claim. (Task 2 + Task 10c)
- `web/static/qc.html` — (a) lines 378-385: add chips for `WRONG_CASE`, `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `VERIFICATION_INCOMPLETE`. (b) line 421: extend `activeFilters` default to include `WRONG_CASE` and `VERIFICATION_INCOMPLETE` (the actionable ones — `VERIFIED_PARTIAL`/`VIA_RECAP`/`DOCKET_ONLY` stay off-by-default so the chip-set works as a triage funnel). (Task 4)
- `web/static/get.html` — line 778 (inside `runSSE`): extend the deep-search-retry condition from `data.status === 'NOT_FOUND' || data.status === 'ERROR'` to also include `data.status === 'VERIFICATION_INCOMPLETE'`. (Task 5)
- `tests/verify_from_csv.py` — line 429: extend the `needs_qc` filter set from `("NOT_FOUND", "POSSIBLE_MATCH")` to `("NOT_FOUND", "WRONG_CASE", "VERIFICATION_INCOMPLETE")` (drop the v0.2-only POSSIBLE_MATCH since v0.3 doesn't emit it). (Task 6)
- `src/citation_verifier/__main__.py` — (a) line 264-265: extend the single-citation CLI's non-zero-exit condition from `Status.NOT_FOUND` to `Status.NOT_FOUND` or `Status.VERIFICATION_INCOMPLETE` (the §2.8 "fail-closed at verifier integrity" rule applied to exit codes). Document the change in a one-line CLI-help footnote. (b) line 770-772: extend the `audit-misses` retry trigger from `r.status == Status.NOT_FOUND` to `r.status in (Status.NOT_FOUND, Status.VERIFICATION_INCOMPLETE)`. (Task 7 + Task 8)
- `tests/verify_sample_citations.py` — (a) lines 135-141: rebuild the `results` dict via `{s.value: [] for s in Status}` plus `'SKIPPED'`, so every v0.3 status has a bucket. (b) lines 208-220: migrate v0.2 field reads to v0.3 (`result.matched_url` → `result.final_ids.absolute_url`; `result.matched_cluster_id` → `result.final_ids.cluster_id`; `result.confidence` → `result.headline_confidence`; `result.diagnostics` → `[w.message for w in result.warnings]`). Same migration patterns as `verify_from_csv.py`'s addendum fix (`6a21e5f`) — borrow the `_v03_matched_case_name` and `_v03_diagnostics_list` helpers via import or copy. (Task 9)
- `README.md` — lines 37-38: drop `LIKELY_REAL` and `POSSIBLE_MATCH` rows; add rows for the five new v0.3 statuses. Lines 121-122: replace v0.2 schema example with v0.3 (`result.final_ids.absolute_url`; `[w.message for w in result.warnings]`). (Task 10a)
- `scratch/README.md` — lines 26, 52, 73: update CSV column legend and post-run checklist for v0.3 statuses. (Task 10b)

**Not touched in Phase 5 (deliberate non-scope):**
- `src/citation_verifier/models.py` — schema is frozen at Phase 4.
- `src/citation_verifier/verifier.py` — no behavior changes; Phase 4 closed the verifier work.
- `src/citation_verifier/brief_pipeline.py` — verified v0.3-clean by audit (Phase 4 Task 8).
- `src/citation_verifier/cache.py` — verified safe-by-design (catches v0.2 status `ValueError` and falls through to re-verify).
- `pyproject.toml` — version stays at `0.2.0`; bumped to `0.3.0` by Phase 4 Task 10 (merge to main).
- `CLAUDE.md` "Refactor Workflow" + "VerificationResult fields" pitfall — deleted/collapsed by Phase 4 Task 10 (merge to main), not Phase 5.
- `scratch/casedev/*.py` — exploration-only; documented in Task 11 manifest as known v0.2 dust.
- `tests/data/refactor_corpus.json` — unchanged unless §0.3 pin refresh fires.
- The Replit `.replit` / `replit.nix` config — gating logic is URL-prefix-based and v0.3-orthogonal.

---

## Task 1: Web app integration test infrastructure (HEADLINE — Sonnet implementer + Opus reviewer)

The Phase 4 Addendum's #2 lesson — "'Produces correctly' needs a test, not an assumption" — names this as load-bearing for Phase 5's credibility. A1 slipped past because zero tests covered `web/app.py`'s endpoints; the verifier's own 362 passing unit tests said nothing about whether the FastAPI surface emitted the v0.3 shape. Phase 5 fixes this with a `TestClient` harness and **regression-pattern coverage** — not exhaustive integration testing, but enough that an A1/A2/A3-class regression cannot land silently.

**Mocking strategy decision.** The web app's endpoints all call `AsyncCourtListenerClient` (instantiated per-request inside the route). Two viable patches:

- **(A) Patch `web.app.AsyncCourtListenerClient`** at the test boundary with a stub class whose `citation_lookup_batch`, `search_opinions`, `search_recap`, etc. return canned dicts. The verifier sees the stub through the patched constructor, runs its real logic, and produces real `VerificationResult` objects. This is the integration-test equivalent of the Phase 4 `MockSpecPatcher`'s posture — exercise the verifier's real code, mock only the network boundary.
- **(B) Patch `web.app._verifier.verify_async` / `_verifier.verify_batch`** directly with a stub that returns a hand-built `VerificationResult`. Faster to write but doesn't exercise the verifier's serialization-to-dict path, which is where A1 lived. Defeats the purpose.

**Recommended posture: (A).** The harness lives in `tests/test_web_app.py` and uses `unittest.mock.patch.object(web.app, "AsyncCourtListenerClient", StubClient)` for each test. The stub class is small — five canned methods returning empty-but-well-formed responses, with hooks to override per-test. The Phase 4 `MockSpecPatcher` is the existence proof that this style works; this harness is the web-app analog at the HTTP boundary.

**Files:**
- Create: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing tests first (regression-pattern coverage)**

Create `tests/test_web_app.py`:

```python
"""Phase 5 Task 1 — integration tests for the FastAPI web app.

Coverage strategy: regression-pattern tests, not exhaustive endpoint coverage.
Each test reproduces a specific class of Phase 4-Addendum-style regression so
those classes cannot land silently:

* A1-class: web endpoint dispatches to a private verifier helper whose
  signature changed during refactor. Test: POST /api/verify with N>1
  citations and assert no event has status='ERROR' with TypeError-shaped
  error message. (Reproduces the original A1 if /api/verify reverted.)
* A2-class: schema-contract regression on the JSON response shape.
  Test: assert each /api/verify SSE 'result' event has the v0.3 keys
  (status, confidence, matched_url, warnings, diagnostics) and the
  status value is a member of the v0.3 Status enum.
* A3-class: covered by tests/test_frontend_status_coverage.py (Task 3).

We mock AsyncCourtListenerClient at the web.app module boundary so the
verifier's real logic runs; only the network is stubbed.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# IMPORTANT: import web.app via the package path, not relative — the test
# runs from the repo root and the web/ package is not on sys.path unless
# we add it. The conftest.py addition (Step 3 below) handles this.
import web.app as web_app
from citation_verifier.models import Status


# ---------------------------------------------------------------------------
# Stub AsyncCourtListenerClient — minimal contract surface
# ---------------------------------------------------------------------------

class _StubAsyncCLClient:
    """Drop-in async client stub for the web app tests.

    Configurable per-test via class attributes (set in fixtures).  Default
    posture: no matches, no errors.  Each method matches the real
    AsyncCourtListenerClient signature, returning empty-but-well-formed
    payloads."""

    BASE_URL = "https://www.courtlistener.com/api/rest/v4"

    # Per-test overrides — fixture-controlled.
    citation_lookup_payloads: dict[str, list[dict]] = {}  # citation -> CL response
    opinion_search_results: list[dict] = []
    recap_search_results: list[dict] = []

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def citation_lookup(self, citation_text: str) -> list[dict]:
        return self.citation_lookup_payloads.get(citation_text, [])

    async def search_opinions(self, **kwargs) -> list[dict]:
        return self.opinion_search_results

    async def search_recap(self, **kwargs) -> list[dict]:
        return self.recap_search_results

    async def get_pdf_url(self, matched_url: str) -> str | None:
        return None

    async def get_opinion_text_with_metadata(
        self, matched_url: str, prefer_html: bool = False,
    ) -> dict | None:
        return None

    async def _request_with_retry(self, method: str, url: str, **kwargs):
        # No-op default; tests that need this should override per-test.
        return {"results": []}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """FastAPI TestClient with the stubbed CL client patched in."""
    with patch.object(web_app, "AsyncCourtListenerClient", _StubAsyncCLClient):
        yield TestClient(web_app.app)


# ---------------------------------------------------------------------------
# A1-class regression tests: dispatch + private-helper signature shape
# ---------------------------------------------------------------------------

class TestVerifyEndpointA1Class:
    """Reproduces the A1 regression: /api/verify must not raise TypeError
    on batches > 1 citation."""

    def _parse_sse(self, response_iter) -> list[tuple[str, dict]]:
        """Parse an SSE response body into a list of (event, data-dict) pairs."""
        events = []
        current_event: str | None = None
        for line in response_iter.split("\n"):
            line = line.strip()
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if current_event:
                    events.append((current_event, data))
        return events

    def test_post_verify_single_citation_no_typeerror(self, client):
        """Single-citation case (worked before the addendum fix too)."""
        response = client.post(
            "/api/verify",
            json={"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]},
        )
        assert response.status_code == 200
        events = self._parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        assert len(result_events) == 1
        for _, data in result_events:
            assert data["status"] != "ERROR", (
                f"Expected non-ERROR status; got error: {data.get('error')!r}"
            )

    def test_post_verify_batch_no_typeerror(self, client):
        """Batch case (THIS was the A1 regression). Five citations through
        /api/verify must not produce any ERROR-status results from a
        TypeError or AttributeError signature mismatch."""
        response = client.post(
            "/api/verify",
            json={"citations": [
                "Obergefell v. Hodges, 576 U.S. 644 (2015)",
                "Brown v. Board, 347 U.S. 483 (1954)",
                "Miranda v. Arizona, 384 U.S. 436 (1966)",
                "Roe v. Wade, 410 U.S. 113 (1973)",
                "Marbury v. Madison, 5 U.S. 137 (1803)",
            ]},
        )
        assert response.status_code == 200
        events = self._parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        assert len(result_events) == 5
        for _, data in result_events:
            assert data["status"] != "ERROR", (
                f"A1-class regression: {data.get('input_citation')} returned "
                f"ERROR with: {data.get('error')!r}"
            )

    def test_post_qc_run_batch_no_typeerror(self, client, tmp_path, monkeypatch):
        """QC run-batch (currently broken at HEAD per audit row C1).
        Once Task 2 lands, this must pass: no result event should have
        status='ERROR' from a TypeError on the private-helper signature."""
        # Skip if the master CSV isn't present (the endpoint short-circuits to 404)
        if not web_app._default_csv.exists():
            pytest.skip("master CSV not present in this checkout")
        response = client.post(
            "/api/qc/run-batch",
            json={"sample_size": 3, "rerun_only": False},
        )
        # Endpoint may return 200 SSE or 404 if no actionable rows. Both fine
        # — we only care that any 'result' events that DO appear are not
        # ERROR-status from a TypeError.
        if response.status_code != 200:
            return
        events = self._parse_sse(response.text)
        for event, data in events:
            if event == "result" and data.get("status") == "ERROR":
                # An ERROR is acceptable IF its message is not a Python
                # TypeError/AttributeError (those are signature regressions).
                err = data.get("error", "")
                assert "TypeError" not in err and "AttributeError" not in err, (
                    f"A1-class regression in /api/qc/run-batch: {err}"
                )


# ---------------------------------------------------------------------------
# A2-class regression tests: v0.3 schema contract on JSON response shape
# ---------------------------------------------------------------------------

class TestVerifyEndpointA2Class:
    """The /api/verify response shape must be the v0.3 contract: every
    status value must be a member of the v0.3 Status enum (no LIKELY_REAL
    / POSSIBLE_MATCH leaking back); every result event must have the
    documented keys."""

    def _parse_sse(self, response_iter) -> list[tuple[str, dict]]:
        events = []
        current_event: str | None = None
        for line in response_iter.split("\n"):
            line = line.strip()
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if current_event:
                    events.append((current_event, data))
        return events

    def test_result_event_has_v03_keys(self, client):
        response = client.post(
            "/api/verify",
            json={"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]},
        )
        events = self._parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        assert len(result_events) >= 1
        _, data = result_events[0]
        for required_key in (
            "input_citation", "citation_as_written", "status",
            "confidence", "matched_url", "matched_case_name",
            "diagnostics", "warnings", "stage_notes",
        ):
            assert required_key in data, (
                f"v0.3 schema contract: key {required_key!r} missing from "
                f"/api/verify result event"
            )

    def test_status_value_is_v03_enum_member(self, client):
        response = client.post(
            "/api/verify",
            json={"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]},
        )
        events = self._parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        v03_values = {s.value for s in Status} | {"ERROR"}
        # ERROR is a sentinel emitted by the route's except block — not a
        # Status member, but acceptable for shape purposes.
        for _, data in result_events:
            assert data["status"] in v03_values, (
                f"v0.3 schema contract: status {data['status']!r} is not a "
                f"member of v0.3 Status enum {sorted(v03_values)}"
            )


# ---------------------------------------------------------------------------
# Other endpoints — smoke tests (no v0.3-specific assertion, but exercises
# the dispatch path so future regressions show up at HTTP boundary)
# ---------------------------------------------------------------------------

class TestOtherEndpointsSmoke:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_qc_runs_returns_list(self, client):
        response = client.get("/api/qc/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_index_returns_get_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_get_redirect(self, client):
        response = client.get("/get", follow_redirects=False)
        assert response.status_code in (302, 307)

    def test_invalid_json_returns_400(self, client):
        response = client.post(
            "/api/verify",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_empty_citations_returns_400(self, client):
        response = client.post("/api/verify", json={"citations": []})
        assert response.status_code == 400

    def test_download_pdfs_no_urls_returns_400(self, client):
        response = client.post("/api/download-pdfs", json={"urls": []})
        assert response.status_code == 400

    def test_flag_for_flp_writes_row(self, client, tmp_path, monkeypatch):
        """Smoke: /api/flag-for-flp must accept and append. Use a tmp path
        so the test doesn't pollute scratch/flp_findings.csv."""
        tmp_csv = tmp_path / "flp_findings_test.csv"
        monkeypatch.setattr(web_app, "_flp_csv", tmp_csv)
        response = client.post("/api/flag-for-flp", json={
            "citation": "Test v. Test, 1 U.S. 1 (2099)",
            "status": "WRONG_CASE",
            "confidence": 0.0,
            "matched_url": "",
            "matched_case_name": "",
            "matched_court": "",
            "matched_date": "",
            "matched_description": "",
            "diagnostics": "",
        })
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert tmp_csv.exists()
        content = tmp_csv.read_text(encoding="utf-8")
        assert "WRONG_CASE" in content


# ---------------------------------------------------------------------------
# Public-mode middleware smoke
# ---------------------------------------------------------------------------

class TestPublicModeMiddleware:
    """When MODE=public, /qc /debug /api/flag-for-flp /api/qc/* return 404.
    The middleware is URL-prefix based and v0.3-orthogonal, but smoke it
    so a regression in the prefix list doesn't go silent."""

    def test_public_mode_blocks_qc(self, monkeypatch):
        # Re-import the app under MODE=public to exercise the middleware.
        monkeypatch.setenv("MODE", "public")
        # Importlib reload trick: easier to instantiate a fresh TestClient
        # against a copy of the app with the middleware added. The cleanest
        # implementation is in the test, mimicking the production path:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response as StarletteResponse
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/qc")
        def qc():
            return {"ok": "should be blocked"}

        @app.post("/api/qc/save")
        def qc_save():
            return {"ok": "should be blocked"}

        class _Block(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                path = request.url.path
                if path in ("/qc", "/debug", "/api/flag-for-flp") or path.startswith("/api/qc"):
                    return StarletteResponse("Not Found", status_code=404)
                return await call_next(request)

        app.add_middleware(_Block)
        c = TestClient(app)
        assert c.get("/qc").status_code == 404
        assert c.post("/api/qc/save").status_code == 404
```

Run the tests (they will fail until Task 2 lands the `/api/qc/run-batch` fix, but the `/api/verify` and smoke tests should pass at HEAD):

```
venv/Scripts/python.exe -m pytest tests/test_web_app.py -v
```

Expected at HEAD `abf38e2`: `test_post_qc_run_batch_no_typeerror` fails with a captured TypeError-shaped error in the SSE event payload (proves the A1-class harness catches the regression that's still live). Other tests pass.

- [ ] **Step 2: Add `web/__init__.py` so `import web.app` works under pytest**

The web/ directory has no `__init__.py` today (it's treated as a script directory). For `import web.app as web_app` to work in the test, add an empty package marker:

```
test -f web/__init__.py || echo "" > web/__init__.py
```

Or via Python (Windows Git Bash compat):

```
venv/Scripts/python.exe -c "from pathlib import Path; Path('web/__init__.py').touch()"
```

Verify with:

```
venv/Scripts/python.exe -c "import web.app; print('ok')"
```

Expected output: `ok` (any other output means a path or import-cycle issue — investigate before continuing).

- [ ] **Step 3: Conftest entry so web/ is importable from tests/**

Check if `tests/conftest.py` exists and already adds the repo root to `sys.path`:

```
venv/Scripts/python.exe -c "import pathlib; p=pathlib.Path('tests/conftest.py'); print(p.read_text(encoding='utf-8')[:500] if p.exists() else 'missing')"
```

If `tests/conftest.py` does not exist or doesn't put the repo root on `sys.path`, create or extend it:

```python
# tests/conftest.py — Phase 5 addendum: ensure web/ is importable
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
```

If `tests/conftest.py` already exists, append the snippet at the end (don't duplicate the import if present).

- [ ] **Step 4: Run the failing tests to confirm shape**

```
venv/Scripts/python.exe -m pytest tests/test_web_app.py -v
```

Expected:
- `TestVerifyEndpointA1Class::test_post_qc_run_batch_no_typeerror` — **FAIL** (the A1-class regression that's still live on `refactor/v0.3` HEAD). Will pass after Task 2.
- All other tests in the file — **PASS**.

Confirm the failure message shows a Python TypeError signature from `_process_citation_lookup_hit(cite_text, parsed, batch_hits[i])` — that's the v0.2 3-arg call site. The test asserts on the error string `"TypeError" not in err`, so the actual failure message will be informative.

If `test_post_qc_run_batch_no_typeerror` PASSES at HEAD, the audit was wrong about C1 — re-read `web/app.py:1465-1495` and confirm before proceeding. (Either the helper signature is backward-compatible enough to accept the v0.2 call, or the route is short-circuiting before reaching the broken line. Either way, that's a finding to record in Task 11's manifest.)

- [ ] **Step 5: Commit**

```
git add tests/test_web_app.py tests/conftest.py web/__init__.py
git commit -m "test(v0.3): Phase 5 Task 1 -- web app integration test infrastructure

Phase 5 Task 1 (HEADLINE). TestClient-driven regression-pattern tests
covering /api/verify, /api/qc/run-batch, /api/qc/runs, /api/qc/save,
/api/flag-for-flp, /api/download-pdfs, /api/health, and the
public-mode middleware. AsyncCourtListenerClient is stubbed at the
web.app module boundary so the verifier's real serialization logic
runs; only the network is mocked.

Coverage strategy: regression-pattern tests, not exhaustive endpoint
coverage. Each test reproduces a class of Phase 4-Addendum-style
regression (A1 dispatch / A2 schema-contract / public-mode-middleware)
so those classes cannot land silently next time.

test_post_qc_run_batch_no_typeerror INTENTIONALLY FAILS at this commit
-- it is the failing test for Task 2 (C1 regression on /api/qc/run-batch).
Task 2's implementation will turn it green."
git push origin refactor/v0.3
```

- [ ] **Step 6: Submit for two-stage review (HEADLINE)**

Reviewer focus areas (Opus):
- **Mocking strategy correctness.** Does `_StubAsyncCLClient` cover every method the verifier touches under each endpoint's code path? Missing methods will surface as AttributeError on real-API calls during tests. Cross-reference against `verifier.py`'s use of `self.client.*` / `self.async_client.*`.
- **SSE parsing robustness.** The `_parse_sse` helper assumes one `event:` / `data:` pair per pair of lines. CRLF / multi-line `data:` continuations / heartbeat events would defeat it. Test against the actual SSE output of `EventSourceResponse` and tighten if needed.
- **Test isolation from globals.** `web.app` instantiates `_master_csv = MasterCSV()` at import time (module-scope global). Tests that hit `/api/qc/save` or `/api/qc/run-batch` will mutate it. Decide whether to (a) monkeypatch `web_app._master_csv` to a tmp instance per-test, (b) accept the global mutation and rely on cleanup, or (c) skip those tests in this commit and defer to a follow-up. Implementer's call; document the choice in the test docstring.
- **Schema-contract test completeness.** Does the v0.3 key list at `test_result_event_has_v03_keys` (Step 1) cover every required-key the frontend reads? Cross-check against `web/static/get.html`'s `data.matched_url`/`data.confidence`/etc. accesses. Missing keys here means the test won't catch a frontend-schema regression.
- **Public-mode middleware test fidelity.** The test re-implements the middleware locally rather than importing the production middleware (`_BlockQCMiddleware`). Reviewer: is that acceptable as smoke, or should we refactor the middleware to a top-level importable so the test exercises the real class? Implementer's call; recommended posture: leave the local re-implementation for now (the middleware is 5 lines and unit-test-fine as a contract test) and flag for refactor in Task 11's manifest if the implementer prefers.

If the reviewer finds issues, fold the fixes into a follow-up commit on `refactor/v0.3` before starting Task 2.

---

## Task 2: Restore correct batch fast path for `/api/verify` and fix `/api/qc/run-batch` (HEADLINE — Sonnet implementer + Opus reviewer)

This is the audit's C1 fix combined with the Phase 4 Addendum §A1 follow-up ("Phase 5+ should restore a correct batch path using the new helper signatures"). Both endpoints should converge on `verifier.verify_batch()` — the public API that already exists, is fully v0.3-aware, internally does the batched citation_lookup, and is what CLAUDE.md tells consumers to use ("Always prefer `verify_batch()` over looping `verify()` when verifying multiple citations").

**Why `verify_batch()` and not the private helpers.** The addendum-fix commit `e6bf6ca` chose the conservative posture: drop private-helper coupling, route every citation through `verify_async()`. That's correct for safety but loses the batching benefit. The right next step is the same direction, just one layer up: route through `verify_batch()` instead of looping `verify_async()`. `verify_batch()` is the public API that's been there since Phase 1; the Phase 4 refactor preserved its contract. Coupling to it (instead of the private `_batch_citation_lookup` + `_process_citation_lookup_hit` helpers) gives the web app the same API-call savings while shielding it from internal-helper signature drift.

**SSE preservation.** Both endpoints stream results as they complete. `verify_batch()` accepts a `progress_callback(completed, total)` parameter — we can wire that to push `progress` events, but `result` events need per-citation result objects. The simplest correct pattern: `verify_batch()` returns a list in input order; iterate and yield once each result is ready. For the QC endpoint's mid-batch SSE streaming experience, this means batching the citation_lookup phase (one shared API call) but then yielding results as the batch returns — slightly less responsive than the addendum's per-citation streaming, but the batched citation_lookup completes fast enough that the UX difference is invisible for typical batch sizes (1-100). Document this trade-off in the route docstring.

**Files:**
- Modify: `web/app.py` — replace `/api/verify`'s event_generator inner loop (lines 400-455) and `/api/qc/run-batch`'s entire async event_generator (lines 1397-1574) with a `verify_batch()`-based flow.

- [ ] **Step 1: Confirm Task 1's failing test still fails before Task 2 work**

```
venv/Scripts/python.exe -m pytest tests/test_web_app.py::TestVerifyEndpointA1Class -v
```

Expected: `test_post_qc_run_batch_no_typeerror` FAIL (the regression is still live); `test_post_verify_batch_no_typeerror` PASS (the addendum fix `e6bf6ca` already covers this case via per-citation `verify_async`).

- [ ] **Step 2: Modify `/api/verify` to use `verify_batch()`**

In `web/app.py`, replace the inner loop of `event_generator` in the `/api/verify` route (currently lines 400-455). The structure becomes:

```python
async def event_generator():
    yield {
        "event": "start",
        "data": json.dumps({"total": len(citations)}),
    }

    async with AsyncCourtListenerClient(api_token=token) as client:
        # Phase 5 Task 2: route through verify_batch() for the batched
        # citation_lookup API-call savings without coupling to private
        # helper signatures. The addendum fix (e6bf6ca) routed everything
        # through per-citation verify_async() — correct but loses the
        # batching benefit. verify_batch() restores it via the public API.
        # Slight UX trade-off: results stream as the batch completes
        # rather than per-citation, but the citation_lookup phase is fast
        # enough that for typical web batches (1-10) the difference is
        # invisible.
        # NOTE: verify_batch is a method on CitationVerifier; the shared
        # _verifier instance at module scope holds no client (it pulls
        # one in), so we pass our request-scoped client by hooking the
        # verifier to use it. Cleanest path is to call the underlying
        # _verify_batch_with_client helper if it exists, or to construct
        # a per-request CitationVerifier. Check verifier.py for the
        # public signature first.
        results = await _verifier.verify_batch(
            citations,
            quick_only=quick_only,
            # progress_callback omitted -- we'll send progress events from
            # the iteration loop instead so the SSE 'progress' events stay
            # 1-to-1 with 'result' events.
        )
        for i, result in enumerate(results):
            if not quick_only or result.status != Status.NOT_FOUND:
                _cache.put(citations[i], result)
            result_dict = _result_to_dict(result)
            result_dict["index"] = i
            result_dict["cached"] = False
            yield {
                "event": "result",
                "data": json.dumps(result_dict),
            }
            yield {
                "event": "progress",
                "data": json.dumps({
                    "completed": i + 1,
                    "total": len(citations),
                }),
            }

    yield {"event": "done", "data": json.dumps({"total": len(citations)})}
```

**Sub-decision: `verify_batch()` client injection.** Inspect `src/citation_verifier/verifier.py` to confirm `verify_batch()`'s signature. Per CLAUDE.md, it's `async def verify_batch(self, citations, ...)` on `CitationVerifier`. The shared `_verifier = CitationVerifier()` is constructed at module-scope with no client — it lazily constructs an `AsyncCourtListenerClient` internally per call. Two possibilities:

- (a) **If `verify_batch()` accepts an injectable client**, pass the request-scoped `client` (which carries the BYOK `token`) and the existing `async with AsyncCourtListenerClient(api_token=token)` stays. Confirm via:
  ```
  venv/Scripts/python.exe -c "import inspect; from citation_verifier.verifier import CitationVerifier; print(inspect.signature(CitationVerifier.verify_batch))"
  ```
- (b) **If `verify_batch()` constructs its own client internally and has no injectable parameter**, we must instantiate a per-request `CitationVerifier(api_token=token)` rather than relying on the module-scope `_verifier`. Inspect `CitationVerifier.__init__` to confirm it accepts `api_token`.

Implementer: do whichever (a) or (b) the actual signature supports. If neither works (the public API doesn't have a way to pass BYOK), the conservative fallback is: keep the addendum-fix's per-citation `verify_async(client, ...)` loop and do NOT restore batching in this commit. Document that disposition explicitly: "Phase 5+ batch-restore blocked on a `verify_batch(client=, api_token=)` parameter addition to `CitationVerifier`; deferred." If you take this path, still fix `/api/qc/run-batch` (Step 3 below) — it doesn't have a BYOK constraint and can use the module-scope `_verifier`.

- [ ] **Step 3: Modify `/api/qc/run-batch` to use `verify_batch()` (C1 fix)**

Replace the bulk of `qc_run_batch`'s `event_generator` (currently lines 1397-1574) with a `verify_batch()`-based flow. The pre-batch skip-pass for short cites (lines 1411-1451) stays — those are skipped *before* the batch verifier runs. The batch verification + per-citation result handling collapses to:

```python
# Run the batch via the public API. verify_batch internally does the
# batched citation_lookup + per-citation search fallback. No private-
# helper coupling.
if batch_citations:
    completed_n = 0
    results = await _verifier.verify_batch(
        batch_citations,
        parsed_citations=batch_parsed,
        # No progress_callback -- we yield SSE events per-result below
        # rather than per-progress-callback invocation, so each
        # result/progress event pair carries an actual cited string.
    )
    for i, result in enumerate(results):
        cite_text = batch_citations[i]
        row = to_verify[batch_row_indices[i]]
        _apply_verification_to_row(row, result, git_hash)
        results_for_sidecar.append(_sidecar_entry(cite_text, row, result))
        completed_n += 1
        yield {
            "event": "result",
            "data": json.dumps({
                "index": batch_row_indices[i],
                "citation_text": cite_text,
                "status": result.status.value,
                "confidence": result.headline_confidence,
                "matched_case_name": _matched_case_name(result),
            }),
        }
        yield {
            "event": "progress",
            "data": json.dumps({
                "completed": completed_n + len(skipped),
                "total": len(to_verify),
            }),
        }
```

The original `miss_indices` / `_verify_miss` / `asyncio.Queue` machinery (lines 1505-1574) goes away — `verify_batch()` handles miss-fallback internally. The CSV write-back and sidecar emit (lines 1577-1627) stay unchanged.

Note: the addendum's `/api/verify` fix `e6bf6ca` left a comment in the route explaining why batching was dropped. Replace that comment with one explaining the Phase 5 Task 2 restoration.

- [ ] **Step 4: Run Task 1's tests to confirm Task 2 turns the failing test green**

```
venv/Scripts/python.exe -m pytest tests/test_web_app.py -v
```

Expected: all tests in `tests/test_web_app.py` PASS, including the previously-failing `test_post_qc_run_batch_no_typeerror`.

- [ ] **Step 5: Run the broader unit suite to confirm no regressions**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected: same pass count as §0.2 Step 4 baseline + ~14 from `tests/test_web_app.py`. The web-app changes should not regress any verifier-internal test.

- [ ] **Step 6: Manual smoke against the live web app**

Spin up the dev server and exercise both routes manually with `curl` or the browser, to confirm SSE streaming actually works end-to-end (TestClient doesn't fully exercise the EventSource lifecycle):

```
venv/Scripts/python.exe web/app.py
```

Then in a second terminal (or the browser at `http://localhost:8000`):

```
curl -X POST http://localhost:8000/api/verify -H "Content-Type: application/json" -d '{"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]}'
```

Expected: SSE stream emits `start`, one or more `result`, `progress`, `done` events. The `result` event's `status` is `VERIFIED` (live API permitting) and the `matched_url` is populated.

Stop the server:

```
taskkill //IM python.exe //F
```

(Or `Ctrl-C` in the server terminal if interactive.)

Document the smoke result in the commit message (Step 7).

- [ ] **Step 7: Commit**

```
git add web/app.py
git commit -m "fix(v0.3): Phase 5 Task 2 -- restore batched verify_batch() for /api/verify and /api/qc/run-batch

Phase 5 Task 2 (HEADLINE). Both batch endpoints now route through the
public CitationVerifier.verify_batch() API instead of private helpers.

/api/qc/run-batch (C1, the unfixed Phase 4 addendum sibling of A1):
previously called _batch_citation_lookup + _process_citation_lookup_hit
with the v0.2 3-arg signature, raising TypeError on every batch hit.
Replaced with a single verify_batch() call that internally does the
batched citation_lookup + per-citation search fallback. No private-
helper coupling.

/api/verify: restores the batching benefit that the addendum fix
(e6bf6ca) dropped when it routed through per-citation verify_async()
for safety. The public verify_batch() API gives the same API-call
savings (one shared citation_lookup for N citations) without coupling
to internal helper signatures.

UX trade-off documented in inline comment: results stream as the
batch completes rather than per-citation. For typical web batch sizes
(1-100) the citation_lookup phase is fast enough that the difference
is invisible.

Live smoke: /api/verify with 5 citations completed in <expected time>;
SSE event ordering preserved.

Closes the audit's C1 row. Restores A1's batching benefit per the
Phase 4 retro Addendum §A1 follow-up."
git push origin refactor/v0.3
```

- [ ] **Step 8: Submit for two-stage review (HEADLINE)**

Reviewer focus areas (Opus):
- **`verify_batch()` client-injection correctness.** Is the implementer's choice between (a) module-scope `_verifier` (no BYOK passthrough), (b) per-request `CitationVerifier(api_token=token)`, or (c) deferred-batch-restore consistent with the actual `verify_batch()` signature? Read `src/citation_verifier/verifier.py` directly to confirm.
- **SSE event ordering.** Does the new structure preserve the contract the frontend reads — `start` once, then alternating `result`/`progress` per citation, then `done` once? Anything that violates that breaks the frontend's progress bar even if the schema is right.
- **Per-citation cache write timing.** The original per-citation loop wrote to `_cache` immediately as each result returned. The new batch flow writes to `_cache` in a post-batch loop. For the `quick_only=True` case, the original `if not quick_only or result.status != Status.NOT_FOUND: _cache.put(...)` logic is preserved — confirm in the diff.
- **Short-cite skip preservation in `/api/qc/run-batch`.** The pre-batch SKIPPED-row pass (lines 1411-1451) must remain — it filters out citations with no case_name *before* calling `verify_batch()`. Confirm the new structure still calls that pass first.
- **CSV write-back integrity.** The CSV write-back loop at lines 1577-1590 mutates `to_verify[batch_row_indices[i]]`. With the new batch flow, `_apply_verification_to_row(row, result, git_hash)` must still fire for every successful batch result. Confirm.
- **Error-path coverage.** `verify_batch()` doesn't raise on per-citation errors (it catches them and returns ERROR-status results). The route's old `except Exception` per-citation block (lines 432-455 / 1519-1564) no longer fires for that reason. But the route's outer `try / except` boundary should still be intact for catastrophic failures (e.g. `AsyncCourtListenerClient` constructor raises). Confirm.

If issues are found, fold fixes into a follow-up commit before starting Task 3.

---

## Task 3: Frontend status-coverage static test

The Phase 4 Addendum's #3 lesson — "The frontend is a consumer too" — names the gap. A3 happened because the three `.html` files' JS switch statements had v0.2-only `case` blocks; the new v0.3 statuses fell through to the default branch and rendered as a permanent "Searching..." badge. A Python-side static test catches that without needing a browser:

**Files:**
- Create: `tests/test_frontend_status_coverage.py`

- [ ] **Step 1: Write the test**

```python
"""Phase 5 Task 3 — static coverage check for frontend status switches.

Each of web/static/get.html, index.html, qc.html has JS switch statements
that map Status enum values to badge classes and label text. When a new
Status value is added in models.py, these switches must add a `case`
block; otherwise the new status renders as the default branch ('Searching'
or empty), which is what Phase 4 Addendum A3 caught manually.

This test loads each HTML, extracts the JS switch statements via regex,
and asserts every Status enum member appears as a case in each one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from citation_verifier.models import Status


_PROJECT_ROOT = Path(__file__).parent.parent
_STATIC_DIR = _PROJECT_ROOT / "web" / "static"


# Pages and the switch-function names each must cover.
_PAGES_AND_SWITCHES = [
    # (filename, [switch-function-name, ...])
    ("get.html", ["statusLabel", "badgeClass"]),
    ("index.html", ["statusLabel", "badgeClass"]),
    ("qc.html", ["statusLabel", "badgeClass"]),
]


def _extract_switch_body(html: str, fn_name: str) -> str:
    """Return the body of a `function fn_name(status) { switch (status) { ... } }`
    block in the given HTML/JS source. Raises AssertionError if the function
    isn't found.
    """
    # Find the function declaration and grab through the matching closing brace
    # of the switch.  We use a coarse regex that captures until the last `}`
    # before the next top-level `function` declaration -- imperfect, but tight
    # enough for the small switches in these files.
    pat = re.compile(
        r"function\s+" + re.escape(fn_name)
        + r"\s*\([^)]*\)\s*\{[^{]*?switch\s*\([^)]+\)\s*\{(.*?)\}\s*\}",
        re.DOTALL,
    )
    m = pat.search(html)
    if not m:
        raise AssertionError(
            f"Could not locate function {fn_name!r} (with switch) in HTML. "
            f"The regex may need updating if the source structure changed."
        )
    return m.group(1)


@pytest.mark.parametrize("filename,switch_fns", _PAGES_AND_SWITCHES)
def test_every_status_has_case_in_every_switch(filename, switch_fns):
    html_path = _STATIC_DIR / filename
    assert html_path.exists(), f"Static file not found: {html_path}"
    html = html_path.read_text(encoding="utf-8")

    for fn_name in switch_fns:
        body = _extract_switch_body(html, fn_name)
        for status in Status:
            # The JS switch uses 'case STATUS_VALUE:' -- match flexibly with
            # quotes around the value.
            pattern = re.compile(
                r"case\s+['\"]" + re.escape(status.value) + r"['\"]\s*:",
            )
            assert pattern.search(body), (
                f"Status {status.value!r} has no 'case' block in "
                f"{filename}::{fn_name}(). When you added this status to "
                f"src/citation_verifier/models.py::Status, you also need to "
                f"add a 'case {status.value!r}:' to {filename}'s {fn_name}() "
                f"switch -- the default branch renders as a stale 'Searching' "
                f"badge (Phase 4 Addendum A3)."
            )


def test_qc_filter_chips_cover_actionable_v03_statuses():
    """The QC page's filter chips drive which rows the reviewer sees. After
    the v0.3 schema change, WRONG_CASE and VERIFICATION_INCOMPLETE became the
    most important triage categories. Both must have chips in qc.html.
    The other v0.3-new statuses (PARTIAL/VIA_RECAP/DOCKET_ONLY) should also
    have chips so the reviewer can filter to them deliberately.
    """
    html_path = _STATIC_DIR / "qc.html"
    html = html_path.read_text(encoding="utf-8")
    # Crude but tight: each chip is a <span class="chip ..." data-filter="STATUS">.
    chip_pat = re.compile(r"data-filter\s*=\s*['\"]([A-Z_]+)['\"]")
    chips = set(chip_pat.findall(html))
    # ALL is the chip-set master toggle; not a status.
    chips.discard("ALL")
    # SKIPPED is a non-Status sentinel emitted by the iterative workflow when
    # the citation has no case_name; the chip stays for backward compat.
    expected_min_chips = {
        s.value for s in Status
    } | {"SKIPPED"}
    missing = expected_min_chips - chips
    assert not missing, (
        f"QC page filter chips missing the following statuses: {sorted(missing)}. "
        f"Add a <span class='chip' data-filter='STATUS'> for each missing status "
        f"in qc.html. Currently has: {sorted(chips)}."
    )
```

- [ ] **Step 2: Run the test to confirm it fails at HEAD**

```
venv/Scripts/python.exe -m pytest tests/test_frontend_status_coverage.py -v
```

Expected at HEAD:
- `test_every_status_has_case_in_every_switch` for each `(filename, switch_fns)` parametrization — **PASS** (the addendum fix `3316fd2` already added every status case to every `statusLabel`/`badgeClass` switch).
- `test_qc_filter_chips_cover_actionable_v03_statuses` — **FAIL** with the missing-statuses message naming `WRONG_CASE`, `VERIFICATION_INCOMPLETE`, `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`. This is the C3 audit row; Task 4 will turn it green.

If `test_every_status_has_case_in_every_switch` fails for any (file, fn_name) combination, the addendum fix `3316fd2` missed a switch — Task 3 has caught a still-live regression. Document the finding and either fix it inline (since it's a one-liner per case) or defer to a Task 3.5 addendum commit. Implementer's call; the inline fix is preferred since this test was added specifically to make these regressions trivial to spot.

- [ ] **Step 3: Commit**

```
git add tests/test_frontend_status_coverage.py
git commit -m "test(v0.3): Phase 5 Task 3 -- frontend status-switch coverage test

Static test that loads each web/static/*.html, extracts the JS switch
bodies for statusLabel() and badgeClass(), and asserts every member
of Status appears as a 'case' block. Also asserts the QC page filter
chips cover the v0.3 status set (will fail until Task 4).

Catches the class of regression that hit Phase 4 Addendum A3 without
needing a browser. When you add a new Status enum member, this test
points you at which HTML files still need the matching case block."
git push origin refactor/v0.3
```

---

## Task 4: QC page filter chips — add the five v0.3-new statuses

Audit row C3 fix. The QC page's filter chips at `web/static/qc.html:378-385` currently expose only `ALL / NOT_FOUND / POSSIBLE_MATCH / LIKELY_REAL / VERIFIED / SKIPPED`. The five v0.3-new statuses have no chip and the default-active set `['NOT_FOUND', 'POSSIBLE_MATCH']` (line 421) excludes them.

**Default-active set decision.** The chips work as a triage funnel — what the reviewer sees by default should be the actionable subset. The v0.3 successor to that subset:
- `NOT_FOUND` — actionable (review for hallucination).
- `WRONG_CASE` — actionable (cite resolves to a different case — high priority).
- `VERIFICATION_INCOMPLETE` — actionable (rerun needed).
- `POSSIBLE_MATCH` — legacy (won't appear in v0.3 sidecars but may appear in old ones — keep the chip for backward-compat, off by default).
- `LIKELY_REAL` — legacy (same).
- `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY` — confirmed-good (verified, no review needed by default; chip available for opt-in inspection).
- `VERIFIED`, `SKIPPED` — confirmed-good / skipped (chip available, off by default).

Default-active in v0.3: `['NOT_FOUND', 'WRONG_CASE', 'VERIFICATION_INCOMPLETE', 'POSSIBLE_MATCH']` (the last for backward-compat with sidecars from before v0.3).

**Files:**
- Modify: `web/static/qc.html` — lines 378-385 (chip HTML) and line 421 (`activeFilters` default).

- [ ] **Step 1: Confirm the failing test from Task 3**

```
venv/Scripts/python.exe -m pytest tests/test_frontend_status_coverage.py::test_qc_filter_chips_cover_actionable_v03_statuses -v
```

Expected: FAIL with `missing: ['VERIFICATION_INCOMPLETE', 'VERIFIED_DOCKET_ONLY', 'VERIFIED_PARTIAL', 'VERIFIED_VIA_RECAP', 'WRONG_CASE']`.

- [ ] **Step 2: Add the five new chips and update `activeFilters` default**

In `web/static/qc.html:378-385`, expand the filters block to include the five new chips. The exact HTML (matching the existing pattern at lines 379-384):

```html
<div class="filters" id="filters" style="display:none;">
  <span class="chip active" data-filter="ALL">ALL</span>
  <span class="chip active" data-filter="NOT_FOUND">NOT_FOUND</span>
  <span class="chip active" data-filter="WRONG_CASE">WRONG_CASE</span>
  <span class="chip active" data-filter="VERIFICATION_INCOMPLETE">INCOMPLETE</span>
  <span class="chip active" data-filter="POSSIBLE_MATCH">POSSIBLE</span>
  <span class="chip" data-filter="LIKELY_REAL">LIKELY_REAL</span>
  <span class="chip" data-filter="VERIFIED">VERIFIED</span>
  <span class="chip" data-filter="VERIFIED_PARTIAL">PARTIAL</span>
  <span class="chip" data-filter="VERIFIED_VIA_RECAP">VIA_RECAP</span>
  <span class="chip" data-filter="VERIFIED_DOCKET_ONLY">DOCKET_ONLY</span>
  <span class="chip" data-filter="SKIPPED">SKIPPED</span>
</div>
```

At line 421, update the JS `activeFilters` initialization:

```javascript
var activeFilters = new Set(['NOT_FOUND', 'WRONG_CASE', 'VERIFICATION_INCOMPLETE', 'POSSIBLE_MATCH']);
```

- [ ] **Step 3: Optionally add styling for the new chip data-filter colors**

The existing styling at `web/static/qc.html:48-49` colors `POSSIBLE_MATCH` and `LIKELY_REAL` chips when active. Add parallel rules for the new chips so they stand out from the inactive set:

```css
.chip[data-filter="WRONG_CASE"].active { background: #b21f1f; border-color: #b21f1f; }
.chip[data-filter="VERIFICATION_INCOMPLETE"].active { background: #856404; border-color: #856404; }
.chip[data-filter="VERIFIED_PARTIAL"].active { background: #1d7e3a; border-color: #1d7e3a; }
.chip[data-filter="VERIFIED_VIA_RECAP"].active { background: #1d7e3a; border-color: #1d7e3a; }
.chip[data-filter="VERIFIED_DOCKET_ONLY"].active { background: #1d7e3a; border-color: #1d7e3a; }
```

Implementer's call on exact hex values; keep the WRONG_CASE chip visually distinct (red-family) so reviewers' eyes are drawn to it.

- [ ] **Step 4: Run Task 3's coverage test to confirm it passes**

```
venv/Scripts/python.exe -m pytest tests/test_frontend_status_coverage.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Manual smoke**

Open the QC page in a browser (server must be running):

```
venv/Scripts/python.exe web/app.py
```

Then http://localhost:8000/qc — visually confirm: ten chips visible (ALL + 9 status chips); the four default-active chips highlight (NOT_FOUND / WRONG_CASE / INCOMPLETE / POSSIBLE); clicking each chip toggles row visibility.

Stop server:

```
taskkill //IM python.exe //F
```

- [ ] **Step 6: Commit**

```
git add web/static/qc.html
git commit -m "fix(v0.3): Phase 5 Task 4 -- QC page filter chips for the 5 v0.3-new statuses

Audit row C3. Adds chips for WRONG_CASE, VERIFICATION_INCOMPLETE,
VERIFIED_PARTIAL, VERIFIED_VIA_RECAP, VERIFIED_DOCKET_ONLY in
qc.html. Default activeFilters extended to include WRONG_CASE and
VERIFICATION_INCOMPLETE (the actionable triage categories under the
v0.3 taxonomy); POSSIBLE_MATCH chip kept for backward-compat with
pre-v0.3 sidecar JSONs.

WRONG_CASE chip styled in red so reviewers' eyes are drawn to the
highest-priority class. Phase 5 Task 3's test_qc_filter_chips_cover_
actionable_v03_statuses now passes."
git push origin refactor/v0.3
```

---

## Task 5: Deep-search retry includes VERIFICATION_INCOMPLETE

Audit row C4. The `runSSE` handler in `web/static/get.html` decides which citations to enqueue for the deep-search retry pass based on the quick-pass status. Currently `NOT_FOUND` and `ERROR` qualify; `VERIFICATION_INCOMPLETE` doesn't, but it's exactly the case (CL outage / 5xx / timeout per design §2.8) where a retry makes sense.

**Files:**
- Modify: `web/static/get.html` — line 778.

- [ ] **Step 1: Write the failing test (frontend logic check)**

Add to `tests/test_frontend_status_coverage.py`:

```python
def test_get_html_deep_search_retries_on_verification_incomplete():
    """The deep-search retry condition in get.html's runSSE handler must
    include VERIFICATION_INCOMPLETE alongside NOT_FOUND and ERROR. Otherwise
    transient CL hiccups leave citations stuck at INCOMPLETE forever (audit
    row C4)."""
    html = (_STATIC_DIR / "get.html").read_text(encoding="utf-8")
    # The condition lives inside the SSE result-event handler. We look for
    # the literal triple of statuses; the exact JS expression may use ||
    # chains or a Set membership.
    has_all_three = (
        "NOT_FOUND" in html
        and "VERIFICATION_INCOMPLETE" in html
        and "ERROR" in html
    )
    assert has_all_three, (
        "get.html must reference all three of NOT_FOUND, ERROR, and "
        "VERIFICATION_INCOMPLETE for the deep-search retry trigger to work "
        "(audit row C4)."
    )
    # Tighter: the retry-trigger expression should mention VERIFICATION_INCOMPLETE
    # alongside the other two. We look for a 5-line window containing all three.
    lines = html.split("\n")
    for i, line in enumerate(lines):
        if "NOT_FOUND" in line and "ERROR" in line:
            window = "\n".join(lines[max(0, i-2):i+3])
            if "VERIFICATION_INCOMPLETE" in window:
                return  # found the retry-condition site
    pytest.fail(
        "get.html has NOT_FOUND + ERROR + VERIFICATION_INCOMPLETE somewhere, "
        "but not in the same retry-condition expression. Confirm the deep-"
        "search retry trigger includes VERIFICATION_INCOMPLETE."
    )
```

- [ ] **Step 2: Run the failing test to confirm**

```
venv/Scripts/python.exe -m pytest tests/test_frontend_status_coverage.py::test_get_html_deep_search_retries_on_verification_incomplete -v
```

Expected: FAIL (the file has `VERIFICATION_INCOMPLETE` in its `statusLabel`/`badgeClass` switches per `3316fd2`, but NOT in the retry-condition expression).

- [ ] **Step 3: Modify get.html line 778**

Currently:

```javascript
if (searchMode === 'quick' && (data.status === 'NOT_FOUND' || data.status === 'ERROR')) {
```

Change to:

```javascript
if (searchMode === 'quick' && (data.status === 'NOT_FOUND' || data.status === 'ERROR' || data.status === 'VERIFICATION_INCOMPLETE')) {
```

Also update line 706 (the post-deep-search "still missing" check) consistently:

```javascript
if (results[idx] && (results[idx].status === 'NOT_FOUND' || results[idx].status === 'ERROR' || results[idx].status === 'VERIFICATION_INCOMPLETE')) stillMissing++;
```

- [ ] **Step 4: Run the test to confirm it passes**

```
venv/Scripts/python.exe -m pytest tests/test_frontend_status_coverage.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add web/static/get.html tests/test_frontend_status_coverage.py
git commit -m "fix(v0.3): Phase 5 Task 5 -- deep-search retry triggers on VERIFICATION_INCOMPLETE

Audit row C4. The deep-search retry in get.html's runSSE handler now
queues VERIFICATION_INCOMPLETE citations for retry alongside NOT_FOUND
and ERROR. Per design §2.8, INCOMPLETE represents CL infra failures
(5xx, timeout, connection error) -- exactly the case the deep-search
retry was built for.

Also updates the post-deep-search 'still missing' counter to include
INCOMPLETE in the still-failed set.

Test in tests/test_frontend_status_coverage.py asserts the retry
expression mentions all three status values."
git push origin refactor/v0.3
```

---

## Task 6: verify_from_csv.py "needs QC" includes WRONG_CASE + VERIFICATION_INCOMPLETE

Audit row C5. The iterative workflow script `tests/verify_from_csv.py` produces a "NEEDS QC" summary at the end of each run, listing items the reviewer should look at. Currently it only flags `("NOT_FOUND", "POSSIBLE_MATCH")` — missing the two highest-priority v0.3 classes.

**Files:**
- Modify: `tests/verify_from_csv.py` — line 429.

- [ ] **Step 1: Modify the `needs_qc` filter set**

Line 428-429 currently:

```python
needs_qc = [r for r in results_for_sidecar
            if r["status"] in ("NOT_FOUND", "POSSIBLE_MATCH")]
```

Change to:

```python
# v0.3 statuses needing human review: NOT_FOUND (potential hallucination),
# WRONG_CASE (cite resolves to a different case -- highest priority),
# VERIFICATION_INCOMPLETE (infra failure, needs rerun). POSSIBLE_MATCH is
# kept for backward-compat with old runs that read this script's logic.
needs_qc = [r for r in results_for_sidecar
            if r["status"] in ("NOT_FOUND", "WRONG_CASE",
                               "VERIFICATION_INCOMPLETE", "POSSIBLE_MATCH")]
```

- [ ] **Step 2: Smoke-test with `--dry-run` to confirm the script still parses**

```
venv/Scripts/python.exe tests/verify_from_csv.py --dry-run --sample-size 5
```

Expected: prints the dry-run sample list with no exception. (Dry-run doesn't hit the API, so we just verify the filter-set syntax is valid.)

- [ ] **Step 3: Commit**

```
git add tests/verify_from_csv.py
git commit -m "fix(v0.3): Phase 5 Task 6 -- verify_from_csv.py 'needs QC' includes WRONG_CASE + INCOMPLETE

Audit row C5. The iterative workflow's post-run 'NEEDS QC' summary
now flags WRONG_CASE and VERIFICATION_INCOMPLETE items in addition
to NOT_FOUND. POSSIBLE_MATCH kept for backward-compat with reviewers
reading old sidecars.

Per CLAUDE.md's post-run checklist, this is the script's signal that
a row needs human attention. v0.3's WRONG_CASE (cite resolves to a
different case) is the single most important class to surface."
git push origin refactor/v0.3
```

---

## Task 7: audit-misses CLI retries on VERIFICATION_INCOMPLETE

Audit row C6. `src/citation_verifier/__main__.py`'s `audit_misses_main` runs a two-pass verify: pass 1 is quick (`quick_only=True`), pass 2 is the full pipeline on quick-misses. The "quick-misses" set is selected via `r.status == Status.NOT_FOUND` (line 770-772). By the same design-§2.8 logic that motivates Task 5, INCOMPLETE results from the quick pass should also be retried — they are exactly the case the full pipeline can recover from.

**Files:**
- Modify: `src/citation_verifier/__main__.py` — line 770-772.

- [ ] **Step 1: Modify the retry-trigger condition**

Lines 769-772 currently:

```python
miss_indices: list[int] = [
    i for i, r in enumerate(quick_results)
    if r.status == Status.NOT_FOUND
]
```

Change to:

```python
miss_indices: list[int] = [
    i for i, r in enumerate(quick_results)
    if r.status in (Status.NOT_FOUND, Status.VERIFICATION_INCOMPLETE)
]
```

- [ ] **Step 2: Add a unit test**

Locate the existing `tests/test_cli_audit_misses.py` — it has fixtures for the audit-misses workflow. Append a test that constructs a quick-result with `Status.VERIFICATION_INCOMPLETE` and asserts it gets retried in the full pass.

```
venv/Scripts/python.exe -c "import pathlib; p=pathlib.Path('tests/test_cli_audit_misses.py'); print('exists' if p.exists() else 'missing')"
```

If the file exists, append the test. If not, create a minimal test that exercises just the `audit_misses_main` retry-selection logic. The implementer should look at the existing patterns in `test_cli_*` and mirror them. (Per CLAUDE.md, audit-misses is mocked at the verifier level; a test that constructs two fake `VerificationResult`s, one NOT_FOUND and one VERIFICATION_INCOMPLETE, and confirms both go into the second-pass full results, is the right shape.)

Suggested test body:

```python
def test_audit_misses_retries_verification_incomplete(monkeypatch):
    """Both NOT_FOUND and VERIFICATION_INCOMPLETE in the quick pass should
    be retried by the full pass (audit row C6)."""
    from citation_verifier.models import (
        FinalIds, ResolutionPathEntry, Status, StageName, StageVerdict,
        VerificationResult,
    )

    not_found_quick = VerificationResult(
        citation_as_written="X v. Y, 1 U.S. 1",
        parsed_citation=None, status=Status.NOT_FOUND,
        final_ids=FinalIds(None, None, None, None, None, None),
        resolution_path=[], warnings=[], gates_failed=[],
        timing={}, cache_hit=False,
    )
    incomplete_quick = VerificationResult(
        citation_as_written="A v. B, 2 U.S. 2",
        parsed_citation=None, status=Status.VERIFICATION_INCOMPLETE,
        final_ids=FinalIds(None, None, None, None, None, None),
        resolution_path=[ResolutionPathEntry(
            stage=StageName.citation_lookup, query={},
            raw_response_summary={}, verdict=StageVerdict.errored,
            confidence=None, notes="HTTP 500", elapsed_ms=10,
        )],
        warnings=[], gates_failed=[], timing={}, cache_hit=False,
    )
    # Replicate the retry-selection logic from audit_misses_main line 769-772
    quick_results = [not_found_quick, incomplete_quick]
    miss_indices = [
        i for i, r in enumerate(quick_results)
        if r.status in (Status.NOT_FOUND, Status.VERIFICATION_INCOMPLETE)
    ]
    assert miss_indices == [0, 1], (
        "Both NOT_FOUND and VERIFICATION_INCOMPLETE quick-results should be "
        "retried by the full pass; got: " + repr(miss_indices)
    )
```

- [ ] **Step 3: Run tests**

```
venv/Scripts/python.exe -m pytest tests/test_cli_audit_misses.py -v
```

Expected: PASS (including the new test).

- [ ] **Step 4: Commit**

```
git add src/citation_verifier/__main__.py tests/test_cli_audit_misses.py
git commit -m "fix(v0.3): Phase 5 Task 7 -- audit-misses retries VERIFICATION_INCOMPLETE

Audit row C6. The audit-misses CLI's two-pass design now retries
VERIFICATION_INCOMPLETE quick-results in the full pipeline, alongside
NOT_FOUND. Per design §2.8, INCOMPLETE means a stage errored out
(CL infrastructure failure) -- exactly the case the full pipeline's
retry/fallback logic was built for.

Unit test asserts the retry-selection logic includes both statuses."
git push origin refactor/v0.3
```

---

## Task 8: Single-citation CLI exit code on VERIFICATION_INCOMPLETE

Audit row C7. The single-citation CLI at `__main__.py:264-265` exits non-zero on `Status.NOT_FOUND` and zero otherwise. `VERIFICATION_INCOMPLETE` currently exits zero — a CI script checking exit code sees an infrastructure failure as success.

**Rationale.** Per design §2.8 "fail-closed at verifier integrity," the verifier returns INCOMPLETE precisely because it cannot answer the question. A CI caller asking "is this citation real?" gets "I don't know" — that's not success. The exit code should propagate the uncertainty.

**Decision (recommended to implementer; user can override during execution).** `VERIFICATION_INCOMPLETE` → exit code `2` (distinct from NOT_FOUND's `1`, so CI scripts can distinguish "fake citation" from "couldn't check"). NOT_FOUND stays at `1`. Other statuses stay at `0`.

**Files:**
- Modify: `src/citation_verifier/__main__.py` — line 260-267.

- [ ] **Step 1: Modify the exit-code logic**

Lines 260-267 currently:

```python
# Print all results in original order
any_not_found = False
for result in results:
    assert result is not None
    _print_result(result, args.json_mode)
    if result.status == Status.NOT_FOUND:
        any_not_found = True

return 1 if any_not_found else 0
```

Change to:

```python
# Print all results in original order. Exit codes (audit row C7):
#   0 = all citations verified (any VERIFIED_* class) or SKIPPED
#   1 = at least one NOT_FOUND (potential hallucination)
#   2 = at least one VERIFICATION_INCOMPLETE (CL infra failure; rerun)
# Per design §2.8 "fail-closed at verifier integrity" -- INCOMPLETE means
# "we couldn't tell," not "verified," so CI scripts must distinguish it.
# NOT_FOUND beats INCOMPLETE (1 < 2 is intentional: a confirmed hallucination
# is a stronger signal than an infra failure).
exit_code = 0
for result in results:
    assert result is not None
    _print_result(result, args.json_mode)
    if result.status == Status.NOT_FOUND:
        exit_code = max(exit_code, 1)
    elif result.status == Status.VERIFICATION_INCOMPLETE:
        exit_code = max(exit_code, 2)

return exit_code
```

- [ ] **Step 2: Add a unit test**

`tests/test_cli_verify_*.py` files have the existing CLI tests. Append to whichever already covers the exit-code behavior (likely `test_cli_verify_json.py` or a sibling). If none does, append to `tests/test_cli_audit_misses.py`'s sibling. The test should construct a fake result, call `main()` with the citation, and assert the exit code.

Suggested test body:

```python
def test_main_exit_code_on_verification_incomplete(monkeypatch, capsys):
    """VERIFICATION_INCOMPLETE should exit 2 (distinct from NOT_FOUND's 1
    so CI scripts can distinguish infra failure from confirmed-fake)."""
    from citation_verifier import __main__ as cli_main
    from citation_verifier.models import (
        FinalIds, ResolutionPathEntry, Status, StageName, StageVerdict,
        VerificationResult,
    )

    incomplete = VerificationResult(
        citation_as_written="Test v. Test, 1 U.S. 1 (2099)",
        parsed_citation=None, status=Status.VERIFICATION_INCOMPLETE,
        final_ids=FinalIds(None, None, None, None, None, None),
        resolution_path=[ResolutionPathEntry(
            stage=StageName.citation_lookup, query={},
            raw_response_summary={}, verdict=StageVerdict.errored,
            confidence=None, notes="HTTP 500", elapsed_ms=10,
        )],
        warnings=[], gates_failed=[], timing={}, cache_hit=False,
    )

    class _StubVerifier:
        def verify(self, _): return incomplete
        async def verify_batch(self, *a, **k): return [incomplete]
    monkeypatch.setattr(cli_main, "CitationVerifier", lambda *a, **k: _StubVerifier())
    monkeypatch.setattr(cli_main, "VerificationCache", lambda *a, **k: type("C", (), {"get": lambda self, _: None, "put": lambda self, *a: None, "clear": lambda self: 0, "__len__": lambda self: 0})())

    exit_code = cli_main.main(["Test v. Test, 1 U.S. 1 (2099)", "--no-cache"])
    assert exit_code == 2, (
        f"Expected exit code 2 for VERIFICATION_INCOMPLETE; got {exit_code}"
    )
```

- [ ] **Step 3: Run tests**

```
venv/Scripts/python.exe -m pytest tests/test_cli_verify_json.py tests/test_cli_audit_misses.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```
git add src/citation_verifier/__main__.py tests/test_cli_verify_json.py
git commit -m "fix(v0.3): Phase 5 Task 8 -- single-citation CLI exits 2 on VERIFICATION_INCOMPLETE

Audit row C7. The single-citation CLI now exits with distinct codes:
0 = verified, 1 = NOT_FOUND (potential hallucination),
2 = VERIFICATION_INCOMPLETE (CL infra failure; rerun).

Per design §2.8 'fail-closed at verifier integrity,' INCOMPLETE means
'we couldn't tell,' not 'verified.' CI scripts checking exit code now
distinguish a confirmed-fake citation from an infrastructure failure
worth retrying."
git push origin refactor/v0.3
```

---

## Task 9: Fix tests/verify_sample_citations.py v0.3 compatibility

Audit row C2 fix. The script crashes the moment it processes any non-SKIPPED citation due to (a) a hardcoded results-dict missing the 5 v0.3-new statuses (KeyError) and (b) v0.2 field reads on `VerificationResult` (AttributeError on `result.matched_url` / `.matched_cluster_id` / `.confidence` / `.diagnostics`).

**Files:**
- Modify: `tests/verify_sample_citations.py` — lines 135-141 and 208-220 (plus minor surrounding cleanup).

- [ ] **Step 1: Rebuild the results dict to auto-cover all v0.3 statuses**

Lines 135-141 currently:

```python
results = {
    'VERIFIED': [],
    'LIKELY_REAL': [],
    'POSSIBLE_MATCH': [],
    'NOT_FOUND': [],
    'SKIPPED': []
}
```

Change to (import-driven, so new statuses auto-bucket):

```python
from citation_verifier.models import Status

results = {s.value: [] for s in Status}
results['SKIPPED'] = []  # script-internal sentinel for short cites
```

The `from ... import Status` line goes near the top of the file (around line 26 alongside the existing `from citation_verifier.text_cleaner import clean_case_name`).

- [ ] **Step 2: Migrate v0.2 field reads to v0.3**

Lines 207-221 currently:

```python
print(f"  Status: {result.status.value}")
if result.matched_url:
    print(f"  Found: {result.matched_url}")

# Organize by status
cite_result = {
    'citation': simple_citation,
    'original': citation_text,
    'source_pdf': source_pdf,
    'status': result.status.value,
    'matched_url': result.matched_url,
    'matched_cluster_id': result.matched_cluster_id,
    'confidence': result.confidence,
    'diagnostics': result.diagnostics
}

results[result.status.value].append(cite_result)
```

Change to:

```python
# v0.3 schema accessors (matches verify_from_csv.py's _v03_* helpers and
# brief_pipeline.py's _write_verification_csv).
matched_url = result.final_ids.absolute_url
matched_cluster_id = result.final_ids.cluster_id
confidence = result.headline_confidence
matched_case_name = (
    result.resolution_path[-1].raw_response_summary.get("case_name")
    if result.resolution_path else None
)
diagnostics_strs = [w.message for w in (result.warnings or [])]

print(f"  Status: {result.status.value}")
if matched_url:
    print(f"  Found: {matched_url}")

cite_result = {
    'citation': simple_citation,
    'original': citation_text,
    'source_pdf': source_pdf,
    'status': result.status.value,
    'matched_url': matched_url,
    'matched_cluster_id': matched_cluster_id,
    'matched_case_name': matched_case_name,
    'confidence': confidence,
    'diagnostics': diagnostics_strs,
}

results[result.status.value].append(cite_result)
```

- [ ] **Step 3: Also fix the NOT_FOUND printout at lines 343-355**

Lines 344-355 read `item.get('diagnostics')` and try to print `item['diagnostics'][0]`. With the new diagnostics being a list of strings (rather than v0.2's list of `Diagnostic` objects), the existing code happens to still work since both shapes index as `[0]` and produce a printable thing — but the print format will be slightly different. Confirm output is reasonable; no code change needed unless the printout is jarring.

- [ ] **Step 4: Smoke-test (small sample, no API call expected to succeed but the script must parse and run)**

If there's a small `tests/data/citations_extracted_*.json` available, run:

```
venv/Scripts/python.exe tests/verify_sample_citations.py --sample-size 2
```

If no extraction file is available, the script exits early at line 264 ("no extraction files found") — that's fine; it exercised the imports and the `Status`-keyed dict construction without crashing.

If an extraction file is present and the test would hit the live API, that's OK to skip — the schema changes are clear-cut and don't need a live-API smoke beyond parsing-correctness.

- [ ] **Step 5: Commit**

```
git add tests/verify_sample_citations.py
git commit -m "fix(v0.3): Phase 5 Task 9 -- verify_sample_citations.py v0.3 schema compat

Audit row C2. Two regressions fixed:

(a) Hardcoded results dict {VERIFIED, LIKELY_REAL, POSSIBLE_MATCH,
    NOT_FOUND, SKIPPED} would KeyError on any of the 5 v0.3-new
    statuses. Replaced with dict comprehension over Status enum so
    future status additions auto-bucket.

(b) v0.2 field reads on VerificationResult (result.matched_url,
    result.matched_cluster_id, result.confidence, result.diagnostics)
    would AttributeError on every successful verify. Migrated to v0.3
    (result.final_ids.absolute_url, result.final_ids.cluster_id,
    result.headline_confidence, result.warnings) using the same
    helper pattern as verify_from_csv.py (addendum fix 6a21e5f).

Mirrors the post-refactor pattern documented in CLAUDE.md's
'VerificationResult fields on refactor/v0.3' pitfall bullet."
git push origin refactor/v0.3
```

---

## Task 10: Documentation accuracy — README.md, scratch/README.md, and inline comment

Audit rows C8 / C9 / C10. Bring the public-facing and workflow docs in line with the v0.3 shape.

**Files:**
- Modify: `README.md` — lines 37-38, 121-122.
- Modify: `scratch/README.md` — lines 26, 52, 73.
- Modify: `web/app.py` — line 42-44.

- [ ] **Step 1 (10a): Update README.md status taxonomy table**

Lines 37-38 of `README.md` currently:

```markdown
| `LIKELY_REAL` | Strong fuzzy match (>= 85% confidence) |
| `POSSIBLE_MATCH` | Partial match found (>= 40% confidence) |
```

Replace with the v0.3 taxonomy (mirror the CHANGELOG.md §v0.3.0 schema entries for wording consistency):

```markdown
| `VERIFIED_PARTIAL` | Parallel cite resolved; primary reporter did not (e.g. NY A.D.3d + slip op). |
| `VERIFIED_VIA_RECAP` | Matched to a specific RECAP document (federal PACER). |
| `VERIFIED_DOCKET_ONLY` | Docket found, but the specific cited opinion couldn't be pinned. |
| `WRONG_CASE` | Citation resolves, but to a different case (caption divergence + party-overlap fails). |
| `VERIFICATION_INCOMPLETE` | CL infrastructure failure (5xx / timeout); rerun. |
```

- [ ] **Step 2 (10a cont): Update README.md schema example**

Lines 121-122 currently:

```python
print(result.matched_url)     # https://www.courtlistener.com/opinion/2812209/...
print(result.diagnostics)     # [] (List[Diagnostic], each with .category and .message)
```

Replace with the v0.3 shape:

```python
print(result.final_ids.absolute_url)     # https://www.courtlistener.com/opinion/2812209/...
print(result.headline_confidence)        # 0.96 (or None)
for w in result.warnings:                # List[Warning], each with .category and .message
    print(f"[{w.category.value}] {w.message}")
```

Audit the surrounding paragraph (lines 110-130 area) for any other v0.2-shape references and update consistently.

- [ ] **Step 3 (10b): Update scratch/README.md workflow doc**

Line 26 in `scratch/README.md`:

```markdown
#    Review NOT_FOUND and POSSIBLE_MATCH items
```

Change to:

```markdown
#    Review NOT_FOUND, WRONG_CASE, and VERIFICATION_INCOMPLETE items
```

Line 52 (CSV column legend):

```markdown
| `v_status` | `VERIFIED`, `LIKELY_REAL`, `POSSIBLE_MATCH`, `NOT_FOUND`, `SKIPPED`, (empty) | Verifier result. Empty = not yet run. |
```

Change to:

```markdown
| `v_status` | `VERIFIED`, `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `NOT_FOUND`, `VERIFICATION_INCOMPLETE`, `SKIPPED`, (empty) | Verifier result. Empty = not yet run. Old rows may carry v0.2 `LIKELY_REAL`/`POSSIBLE_MATCH`; verify_from_csv.py reads both. |
```

Line 73 (post-run checklist):

```markdown
1. Review NOT_FOUND and POSSIBLE_MATCH items from the JSON sidecar
```

Change to:

```markdown
1. Review NOT_FOUND, WRONG_CASE, and VERIFICATION_INCOMPLETE items from the JSON sidecar
```

Audit surrounding lines for similar references.

- [ ] **Step 4 (10c): Update web/app.py:42-44 misleading comment**

Lines 42-44 currently:

```python
# Status -> display label / CSS class. Phase 1 only emits VERIFIED and
# NOT_FOUND; the rest are placeholders so Phase 3/4 don't trip on missing
# keys. The web app's frontend (get.html, index.html, qc.html) has its own
# JS-side status switches that still recognize the legacy v0.2 names
# (LIKELY_REAL, POSSIBLE_MATCH) for backward compat with older JSON
# sidecars on disk; the API only emits v0.3 names going forward.
```

Change to:

```python
# Status -> display label / CSS class.  All v0.3 statuses are emitted in
# production.  Frontend JS in web/static/{get,index,qc}.html switches
# cover the full v0.3 enum (see tests/test_frontend_status_coverage.py).
# Legacy v0.2 names (LIKELY_REAL, POSSIBLE_MATCH) still appear in old
# on-disk JSON sidecars under tests/data/results/ and in the master
# CSV's pre-v0.3 rows; the QC page's badgeClass/statusLabel keep cases
# for them so historical data renders correctly.  The API only emits v0.3.
```

Also: check whether `_STATUS_DISPLAY` (lines 45-53) is actually referenced anywhere in `web/app.py`. If not, the implementer can leave it (mark with a TODO) or remove it. Quick grep:

```
venv/Scripts/python.exe -c "from pathlib import Path; t=Path('web/app.py').read_text(encoding='utf-8'); print('_STATUS_DISPLAY references:', t.count('_STATUS_DISPLAY'))"
```

If the count is 1 (only the definition), the dict is dead. Implementer's call whether to remove in this commit or defer to a separate clean-up — neither is regression-fixing work.

- [ ] **Step 5: Commit**

```
git add README.md scratch/README.md web/app.py
git commit -m "docs(v0.3): Phase 5 Task 10 -- README + scratch workflow doc + web/app.py comment v0.3 alignment

Audit rows C8/C9/C10. Three documentation updates:

* README.md: status taxonomy table replaces LIKELY_REAL/POSSIBLE_MATCH
  with the 5 v0.3-new statuses (VERIFIED_PARTIAL, VERIFIED_VIA_RECAP,
  VERIFIED_DOCKET_ONLY, WRONG_CASE, VERIFICATION_INCOMPLETE). Schema
  example switches result.matched_url/diagnostics -> result.final_ids.
  absolute_url + result.warnings.

* scratch/README.md: CSV v_status column legend lists v0.3 values and
  notes that old rows may carry the legacy v0.2 names (handled by
  verify_from_csv.py). Post-run checklist updated to include WRONG_CASE
  and VERIFICATION_INCOMPLETE.

* web/app.py: inline comment at line 42-44 corrected -- claimed the
  API emits only VERIFIED/NOT_FOUND ('Phase 1 only emits...'); production
  emits the full v0.3 enum since Phase 3."
git push origin refactor/v0.3
```

---

## Task 11: Write `docs/consumer-surface-manifest.md`

The Phase 4 Addendum's lesson #1 was "Audit, don't smoke." Phase 5 performs the audit; this task captures the audit's output as a checklist artifact so the next schema change doesn't re-discover the same consumer surfaces.

**Files:**
- Create: `docs/consumer-surface-manifest.md`

- [ ] **Step 1: Write the manifest**

Create `docs/consumer-surface-manifest.md`:

```markdown
# Consumer Surface Manifest (v0.3)

This file enumerates every consumer of `VerificationResult` and the
`Status` enum, what each one reads, and what statuses each one expects.
**Run through this list before merging any change to `models.py`** —
schema changes that touch the status taxonomy or `final_ids` shape
need to update every entry below.

**Last full audit:** Phase 5 (2026-05-2X). Maintainer: see CHANGELOG.md.

## How to use this file

1. Before changing `Status`, `FinalIds`, `WarningCategory`, or
   `VerificationResult` fields, read this file end-to-end.
2. For each consumer row, decide whether it needs to be updated.
3. After landing the schema change, update each row's "Last verified"
   column to the phase / commit that re-checked it.
4. If you add a NEW consumer, add a row here in the same commit.

## Core library (verified Phase 5; v0.3 shape is canonical here)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `src/citation_verifier/models.py` | Defines the schema | N/A (source of truth) | Phase 4 |
| `src/citation_verifier/verifier.py` | Constructs `VerificationResult` via `_finalize_result` | Emits every `Status` value | Phase 4 |
| `src/citation_verifier/brief_pipeline.py` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence` | `_DOWNLOADABLE_STATUSES` + `_STATUS_BADGE_FALLBACK` cover every status | Phase 4 Task 8 |
| `src/citation_verifier/cache.py` | Full schema (round-trips) | Catches `ValueError` on unknown status enum value → safe cache-miss fallback | Phase 4 |
| `src/citation_verifier/__main__.py` (`main`, single-citation CLI) | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status` | Exit code: 0/1/2 by Status (Phase 5 Task 8) | Phase 5 Task 8 |
| `src/citation_verifier/__main__.py` (`audit_misses_main`) | `result.status` | Retries `NOT_FOUND` + `VERIFICATION_INCOMPLETE` in pass 2 (Phase 5 Task 7) | Phase 5 Task 7 |
| `src/citation_verifier/__main__.py` (`verify_brief_main`) | `_DOWNLOADABLE_STATUSES` via brief_pipeline | Covered by brief_pipeline's status mapping | Phase 4 |
| `src/citation_verifier/__main__.py` (`verify_batch_main`) | `result.final_ids`, `result.warnings`, `result.headline_confidence` | Emits every status to output CSV | Phase 4 |

## Web app (verified Phase 5; integration tests in `tests/test_web_app.py`)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `web/app.py` `/api/verify` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status`. Serializes via `_result_to_dict`. | Emits every v0.3 status value; ERROR sentinel for catch-all | Phase 5 Task 2 |
| `web/app.py` `/api/qc/run-batch` | Same as above + writes to CSV via `_apply_verification_to_row` | Same | Phase 5 Task 2 |
| `web/app.py` `/api/qc/runs` | Reads JSON sidecar metadata only | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/qc/run/{filename}` | Enriches sidecar rows with CSV state; sidecar dicts carry whatever status they had at write time (v0.2 or v0.3) | N/A (passthrough) | Phase 5 (smoke) |
| `web/app.py` `/api/qc/save` | None (writes `qc_status` field only) | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/qc/opinion-text` | None | N/A. **Known issue:** uses outdated text fallback chain (missing `html_lawbox`/`html_columbia`/`xml_harvard`); see `client._extract_opinion_text` for canonical chain. Pre-existing bug; not v0.3-related. | Phase 5 noted; deferred |
| `web/app.py` `/api/flag-for-flp` | None (writes user-supplied dict) | N/A | Phase 5 (smoke) |
| `web/app.py` `/api/download-{pdfs,texts,htmls}` | None (operates on URLs) | N/A | Phase 5 (smoke) |
| `web/app.py` `_BlockQCMiddleware` (MODE=public) | URL prefix only | N/A (schema-orthogonal) | Phase 5 (smoke) |
| `web/static/get.html` `statusLabel/badgeClass` | `data.status` from SSE result events | Every v0.3 status has a `case` block (test in `tests/test_frontend_status_coverage.py`) | Phase 5 Task 3 |
| `web/static/get.html` deep-search retry | `data.status` | Retries `NOT_FOUND`, `ERROR`, `VERIFICATION_INCOMPLETE` | Phase 5 Task 5 |
| `web/static/index.html` `statusLabel/badgeClass` | Same as get.html | Same | Phase 5 Task 3 |
| `web/static/qc.html` `statusLabel/badgeClass` | Same | Same | Phase 5 Task 3 |
| `web/static/qc.html` filter chips | `data-filter` attribute on chip spans | Chips cover every v0.3 status + legacy LIKELY_REAL/POSSIBLE_MATCH for old sidecars | Phase 5 Task 4 |

## Iterative workflow scripts (verified Phase 5)

| File | What it reads | Status handling | Last verified |
|---|---|---|---|
| `tests/verify_from_csv.py` | `result.final_ids.absolute_url`, `result.warnings`, `result.headline_confidence`, `result.status` | "needs QC" highlights NOT_FOUND/WRONG_CASE/INCOMPLETE/POSSIBLE_MATCH (Phase 5 Task 6) | Phase 5 Task 6 |
| `tests/verify_sample_citations.py` | `result.final_ids.absolute_url`, `result.final_ids.cluster_id`, `result.warnings`, `result.headline_confidence` | Results dict built from `Status` enum (Phase 5 Task 9) | Phase 5 Task 9 |
| `tests/extract_citations_batch.py` | None (PDF extraction, pre-verify) | N/A | n/a |
| `tests/extract_hallucination_citations.py` | None | N/A | n/a |

## Test files (verified Phase 5; the test suite IS the consumer here)

| File | What it reads | Coverage notes |
|---|---|---|
| `tests/test_verifier.py` | Full schema | 101 unit tests; covers every status path |
| `tests/test_async_verifier.py` | Full schema | 29 sync/async parity tests |
| `tests/test_brief_pipeline.py` | brief_pipeline status mapping | Covers DOWNLOADABLE_STATUSES + badge fallback |
| `tests/test_resolution_path.py` | resolution_path entries | Covers verdict types |
| `tests/test_phase3_corpus_acceptance.py` | Full schema (live API + mock) | 141 live + 5 mock fixtures pin expected statuses |
| `tests/test_false_negatives.py` | Full schema (live API) | 7 known-real citations |
| `tests/test_web_app.py` | API JSON shape | **NEW Phase 5 Task 1** -- regression-pattern tests |
| `tests/test_frontend_status_coverage.py` | Static JS coverage | **NEW Phase 5 Task 3** -- every Status enum value has a JS case |
| `tests/test_cli_*.py` | CLI exit codes + output | Covers Phase 5 Tasks 7 + 8 |

## Known v0.2 dust (deliberately NOT updated; not in active code paths)

| File | What | Reason kept | Action needed |
|---|---|---|---|
| `scratch/casedev/test_waterfall.py` | `result.matched_url`, `LIKELY_REAL`, `POSSIBLE_MATCH` | One-off case.dev API exploration script from 2026-03 (per `scratch/casedev/README.md`); not run since | None — exploration archive |
| `scratch/casedev/waterfall_batch_50.py` | Same | Same | None |
| Old JSON sidecars under `tests/data/results/` (gitignored) | v0.2-status fields | Backward-compat handled by frontend JS + cache `ValueError` swallow | None |
| Master CSV pre-v0.3 rows with `v_status=LIKELY_REAL` / `POSSIBLE_MATCH` | Same | `verify_from_csv.py` reads both via `__main__._read_status_from_csv` mapping | None |

## Adding a new consumer

When you write code that consumes `VerificationResult` or `Status`:

1. Add a row to the appropriate table above in the same commit.
2. Declare which fields you read and what statuses you handle.
3. Add an integration or static test to one of:
   - `tests/test_web_app.py` for web-app endpoints
   - `tests/test_frontend_status_coverage.py` for HTML/JS coverage
   - `tests/test_cli_*.py` for CLI scripts
   - `tests/test_<your_module>.py` for new library modules
4. If you handle status in a `match` / `switch` / dict, write a test
   that asserts every `Status` enum member appears as a case. The
   pattern in `tests/test_frontend_status_coverage.py` is the model.
```

- [ ] **Step 2: Commit**

```
git add docs/consumer-surface-manifest.md
git commit -m "docs(v0.3): Phase 5 Task 11 -- consumer surface manifest

Checklist artifact enumerating every consumer of VerificationResult
and Status, what each reads, and what statuses each handles.

Outcome of the Phase 5 audit. Future status-taxonomy or final_ids
schema changes should run through this list before merging, instead
of needing another retro to rediscover the same consumer surfaces
(the Phase 4 Addendum's lesson #1: 'Audit, don't smoke').

Includes a 'Known v0.2 dust' section for exploration-only scripts
that are deliberately not updated, and an 'Adding a new consumer'
section that names the test pattern to follow."
git push origin refactor/v0.3
```

---

## Task 12: Phase 5 acceptance gate + retrospective + tag + Task 10 handoff

Run the full test suite, confirm no regressions, tag the acceptance point, write the retrospective, and explicitly hand off to the original Phase 4 Task 10 (merge to main) which has been blocked on Phase 5.

**Files:**
- Modify: `tests/data/refactor_corpus_survey.md` — optionally add a §3.3 noting Phase 5 dispositions (purely doc; can also be subsumed into Task 11's manifest).
- Create: `docs/retrospectives/2026-05-2X-refactor-v0.3-phase-5.md` (filename uses actual completion date).

- [ ] **Step 1: Non-live full-suite run**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -v
```

Expected: §0.2 Step 4 baseline + Phase 5 additions. Phase 5 nets:
- Task 1: +14 tests (estimated) in `tests/test_web_app.py`
- Task 3: +4 tests in `tests/test_frontend_status_coverage.py` (3 parametrized HTML files × 2 switches + 1 chips test + 1 retry-condition test ≈ 8 individual test invocations)
- Task 7: +1 test
- Task 8: +1 test

Estimated final count: 362 + 24 ≈ 386 passed. Record actual.

- [ ] **Step 2: Live-API regression run**

```
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py tests/test_phase3_corpus_acceptance.py -v -m live_api
```

Expected: same 153 live-api tests pass as in §0.2 Step 5. Phase 5 should have changed zero verifier-internal behavior; if any live test goes red, triage before tagging.

- [ ] **Step 3: Web-app end-to-end smoke**

Launch the server and exercise both endpoints with realistic inputs:

```
venv/Scripts/python.exe web/app.py
```

Then in browser at http://localhost:8000:
- Paste 3 citations into the Retrieve page, run "Verify Selected", confirm SSE results stream and status badges render correctly for each.
- Navigate to /qc, select an available run, confirm filter chips work as expected (WRONG_CASE chip visible, INCOMPLETE chip visible, etc.).
- (Optional) Open /debug, paste a citation, confirm debug output renders.

Stop server:

```
taskkill //IM python.exe //F
```

If a citation hits VERIFICATION_INCOMPLETE in the wild during this smoke (unlikely unless CL is having a bad day), confirm the deep-search retry button appears and re-queues it. Document the smoke outcome in the retro.

- [ ] **Step 4: Verify-brief CLI smoke**

```
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/fivehouse-v-dod --merge
```

Expected: completes cleanly, prints merge stats, no error. (The existing briefs/fivehouse-v-dod artifacts are the standing smoke target per CLAUDE.md.)

- [ ] **Step 5: Write the Phase 5 retrospective**

Create `docs/retrospectives/2026-05-2X-refactor-v0.3-phase-5.md` (date = actual completion date). Mirror the Phase 4 retrospective structure: "What landed," "Time breakdown," "Surprises," "Q dispositions" (Phase 5 has no Qs; replace with audit-row dispositions C1-C11), "Open questions for post-refactor work," "Notes for the v0.3 → main merge (Task 10 — now unblocked)."

The retro must explicitly state: **"Phase 5 acceptance gate passes. The original Phase 4 Task 10 (merge `refactor/v0.3` → `main` with `v0.3.0` tag) is now unblocked. Proceed to Task 10 per the Phase 4 plan's instructions at `docs/plans/2026-05-23-citation-verifier-refactor-phase-4-plan.md` (Task 10 section)."**

- [ ] **Step 6: Tag the acceptance point and push tags**

```
git add docs/retrospectives/2026-05-2X-refactor-v0.3-phase-5.md
git commit -m "docs(v0.3): Phase 5 retrospective

Phase 5 (consumer compatibility sweep) acceptance gate. All 11 audit
rows (C1-C11) dispositioned; web-app integration tests + frontend
status-coverage tests landed; documentation aligned with v0.3 shape.

The original Phase 4 Task 10 (merge refactor/v0.3 -> main with
v0.3.0 tag) is now unblocked. Proceed per the Phase 4 plan."

git tag -a refactor/phase-5-acceptance -m "Phase 5 acceptance: consumer compatibility sweep complete"
git push origin refactor/v0.3
git push origin refactor/phase-5-acceptance
```

- [ ] **Step 7: Confirm the handoff to Phase 4 Task 10 is ready**

The Phase 4 retrospective's "Notes for the v0.3 → main merge (Task 10)" section (lines 98-105) and the Addendum's "Task 10 disposition" (line 152) name the steps. Confirm:

- `git log --oneline refactor/phase-4-acceptance..refactor/phase-5-acceptance` shows the full Phase 5 commit chain.
- `pyproject.toml` `version` is still `0.2.0` (Phase 5 does NOT bump it; Task 10 does).
- `CLAUDE.md` "Refactor Workflow" section still present (Task 10 deletes it).
- `CHANGELOG.md` v0.3.0 entry present (Task 10 confirms it's complete; Phase 5 may add a small "consumer compatibility sweep" sub-bullet).
- The benchmark project pin (`~/Projects/case-law-proposition-benchmark`) is still `v0.2.0` (will bump to `v0.3.0` after Task 10's main-merge).

Print the handoff prompt for the next session:

```
echo "Phase 5 complete. Tag refactor/phase-5-acceptance pushed."
echo "Next session: execute Phase 4 plan's Task 10 (merge to main + tag v0.3.0)."
echo "See docs/plans/2026-05-23-citation-verifier-refactor-phase-4-plan.md (Task 10)."
echo "See docs/retrospectives/2026-05-24-refactor-v0.3-phase-4.md ('Notes for the v0.3 -> main merge')."
```

- [ ] **Step 8: (Optional) Add a one-line Phase 5 entry to CHANGELOG.md**

The Phase 4 retro's `CHANGELOG.md` v0.3.0 entry doesn't mention Phase 5 (it was written before this phase existed). Append a small subsection under "Phase 4 behavior" or insert a new "Phase 5 behavior" sub-heading:

```markdown
### Phase 5 behavior (consumer compatibility sweep)

- **Web app batch endpoints** route through the public `verifier.verify_batch()` API instead of private helpers — `/api/qc/run-batch` (which had a pre-existing v0.2-signature regression) and `/api/verify` (which had dropped batching in the Phase 4 addendum) both restored to one shared citation_lookup API call per batch.
- **Frontend coverage** statically asserted: every `Status` enum value has a `case` block in each of `web/static/{get,index,qc}.html`'s `statusLabel`/`badgeClass` switches. Test in `tests/test_frontend_status_coverage.py`.
- **QC page filter chips** cover all v0.3 statuses; default-active set is `NOT_FOUND` + `WRONG_CASE` + `VERIFICATION_INCOMPLETE` + `POSSIBLE_MATCH` (the last for backward-compat with pre-v0.3 sidecars).
- **Single-citation CLI exit codes** distinguish `NOT_FOUND` (exit 1, potential hallucination) from `VERIFICATION_INCOMPLETE` (exit 2, infrastructure failure).
- **Audit-misses CLI** retries `VERIFICATION_INCOMPLETE` quick-results in the full pass alongside `NOT_FOUND`.
- **`tests/verify_sample_citations.py`** migrated to v0.3 schema (was crashing on every successful verify due to `result.matched_url`/`result.diagnostics` AttributeErrors).
- **Web app integration test infrastructure** lands as `tests/test_web_app.py`. Regression-pattern coverage so the next schema change cannot land A1/A2/A3-class regressions silently.
- **`docs/consumer-surface-manifest.md`** enumerates every consumer of `VerificationResult` and `Status` — checklist artifact for future schema changes.
```

Commit and push.

---

## Risks and explicit deferred decisions

- **`verify_batch()` client-injection.** If `verify_batch()`'s actual signature does not allow passing a BYOK-bearing `AsyncCourtListenerClient`, Task 2 falls back to the conservative posture (per-citation `verify_async()` loop, same as the addendum fix) and the API-call savings are deferred to a follow-up that adds the parameter. Task 2 Step 2 names this contingency explicitly.
- **JS testing.** Phase 5 does not add browser-driven JS tests (Playwright / Cypress). The frontend coverage test in Task 3 is a static check; it catches missing `case` blocks but not actual rendered behavior. Manual smoke in Task 12 Step 3 fills the gap. Bringing in a JS testing framework is out of scope.
- **`web/app.py:1131-1212` `/api/qc/opinion-text` text fallback chain** is a pre-existing bug (not v0.3-introduced). The QC page's opinion-text-peek panel will continue to under-serve state opinions until someone replaces the inline regex chain with a call to `client._extract_opinion_text` / `get_opinion_text_with_metadata`. Tracked in Task 11's manifest under "Known issue."
- **`_STATUS_DISPLAY` dict at `web/app.py:45-53`** may be dead code. Task 10 Step 4 names the audit; implementer's call whether to remove.
- **Audit row C7 exit-code decision (NOT_FOUND=1, INCOMPLETE=2).** If the user prefers a different exit-code mapping (e.g. INCOMPLETE=1 also, or distinguishing more statuses), override during Task 8 execution. The recommendation is based on the principle that CI scripts care most about distinguishing "definitively fake" from "couldn't check."
- **`scratch/casedev/*.py`** v0.2 references are deliberately NOT updated. If those scripts get re-run in the future, they'll crash on contact with v0.3 results — that's fine; they're exploration-archive and the manifest documents them. If the user wants them updated, that's a Phase 6+ housekeeping pass.

---

## Headline vs mechanical task classification

Per the Phase 4 plan's pattern.

**HEADLINE tasks (Sonnet implementer + Opus reviewer):**
- **Task 1: Web app integration test infrastructure.** The harness lands once and shapes how every future web-app test is written. Mocking strategy, SSE parsing, schema-contract assertion structure, test isolation from globals — these are design decisions worth Opus review. Reviewer focus: mocking strategy correctness, SSE parser robustness, test isolation, schema-contract coverage completeness, public-mode middleware test fidelity.
- **Task 2: Restore batched verify_batch() flow in /api/verify + /api/qc/run-batch.** Two endpoints, one architectural decision (public-API instead of private-helper coupling), live behavior change in the user-facing UX (SSE event ordering trade-off). Reviewer focus: `verify_batch()` signature compatibility, SSE event ordering, per-citation cache write timing, short-cite skip preservation, CSV write-back integrity, error-path coverage.

**Mechanical tasks (Sonnet alone or controller-direct):**
- **Task 3: Frontend status-coverage static test.** Sonnet alone — one new test file, mechanical regex against existing HTML.
- **Task 4: QC page filter chips.** Controller-direct — straightforward HTML + CSS + one-line JS edit, validated by Task 3's test.
- **Task 5: get.html deep-search retry condition.** Controller-direct — one-line change, validated by Task 3's test.
- **Task 6: verify_from_csv.py "needs QC" set.** Controller-direct — one-line filter-set extension.
- **Task 7: audit-misses retry trigger.** Sonnet alone — one-line condition extension + one unit test.
- **Task 8: Single-citation CLI exit codes.** Sonnet alone — small refactor + one unit test.
- **Task 9: verify_sample_citations.py v0.3 schema.** Sonnet alone — mechanical field-name migration mirroring the addendum-fix `6a21e5f` pattern.
- **Task 10: Documentation accuracy.** Controller-direct — three doc edits.
- **Task 11: Consumer surface manifest.** Controller-direct — writing-only.
- **Task 12: Phase 5 acceptance gate + retrospective + tag + Task 10 handoff.** Controller-direct — coordination, test-running, writing, tagging.

**Total HEADLINE: 2.** Same density as Phase 4 (2 headlines: MockSpecPatcher + VERIFICATION_INCOMPLETE wiring).
**Total tasks: 12.** Phase 4 had 10 substantive tasks (1-9 plus Task 10 merge); Phase 5 trims the merge to its own session (handoff at Task 12) and adds the consumer-manifest task that didn't exist in Phase 4.

---

## Self-review notes

The writing-plans skill's self-review checklist:

1. **Spec coverage** — the user's brief named these minimum scope items; map each to a task:
   - Every web API endpoint that isn't /api/verify (download-pdfs, download-htmls, flag-for-flp, /api/qc/*, /api/qc/run-batch) → Task 1 smoke tests + Task 2 /api/qc/run-batch fix.
   - QC page filter chips for the 5 new v0.3 statuses → Task 4.
   - Deep-search retry logic in get.html for VERIFICATION_INCOMPLETE → Task 5.
   - `tests/verify_sample_citations.py` v0.3 compat → Task 9.
   - README.md and CLAUDE.md instruction accuracy against v0.3 → Task 10 (CLAUDE.md "Refactor Workflow" section deletion stays with Phase 4 Task 10 per the Phase 4 plan — Phase 5 only addresses README.md and scratch/README.md).
   - Cached .json sidecars / .citation_cache.json — round-trip behavior **verified by audit** as safe-by-design (cache catches ValueError → cache miss → re-verify); documented in Task 11 manifest. No migration needed.
   - Replit MODE=public deployment path — **verified by audit** as v0.3-orthogonal (URL-prefix gating); smoke-tested in Task 1; documented in Task 11.
   - "Anywhere else a systematic audit surfaces" — the audit found 11 rows (C1-C11) plus 4 verified-already-fine surfaces plus 4 deliberate non-scope items, all enumerated in the "Phase 5 scope" section above and recorded in Task 11's manifest.
   - Web app integration test infrastructure decision (Phase 5 vs Phase 6+) → Task 1 (Phase 5; rationale in the audit section).
   - Correct batch-mode replacement for /api/verify → Task 2 (via `verifier.verify_batch()`).
   - Headline vs mechanical classification → above.

2. **Placeholder scan** — no "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling" anywhere. Implementer's-call notes (Task 1 Step 6 mocking, Task 2 Step 2 verify_batch signature contingency, Task 4 Step 3 chip styling, Task 8 exit code mapping) are explicit delegations with named alternatives, not punts. Task 11's manifest "Known issue" rows (opinion-text fallback chain, _STATUS_DISPLAY potential dead code) are deferred with explicit rationale.

3. **Type consistency:**
   - `_StubAsyncCLClient` (Task 1) methods match `AsyncCourtListenerClient`'s real signatures so the verifier can drop in without surprise.
   - `Status` enum values used in tests are imported from `citation_verifier.models` (not string-literal duplicated), so when models.py gets a new enum value, the tests pick it up automatically.
   - `_PAGES_AND_SWITCHES` in `tests/test_frontend_status_coverage.py` lists the static facts (filename + function-name pairs) once at module scope; the test iterates rather than copy-pasting.
   - All file:line references in the audit table match what's actually at HEAD `abf38e2` per the audit performed during plan-writing.

4. **No spec drift from the user's brief:**
   - The plan does NOT modify `models.py`, `verifier.py`, or any other core library beyond the consumer surfaces.
   - The plan does NOT bump `pyproject.toml` version (that stays with Task 10).
   - The plan does NOT merge to main (also Task 10).
   - The plan does NOT touch `scratch/casedev/*.py` (deliberately deferred; documented in manifest).
   - The plan adheres to "audit, don't smoke" (Task 11's manifest is the audit's persisted output).
   - Integration tests scoped to "regression-pattern coverage" rather than exhaustive — explicit decision documented in Task 1's preamble + "Risks and explicit deferred decisions."
   - The headline-vs-mechanical classification matches the Phase 4 plan's pattern (2 headlines, mechanical for the rest).
