# Citation Verifier Refactor v0.3 — Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the final phase of the v0.3 refactor — wire `Status.VERIFICATION_INCOMPLETE` into production from API errors (design §2.8 internal gate) via a mock-spec harness that exercises the 5 corpus fixtures; sweep up the Phase 3 retro's Q1–Q6 follow-ups (opinion-typing gate refinement, `X v. United States` caption_investigation gap, fixture rulings, candidates-field decision); teach `brief_pipeline.py` + `report_template.py` the four richer Phase 3 statuses; then merge `refactor/v0.3` to `main` with a merge commit, tag `v0.3.0`, and delete the refactor scaffolding from `CLAUDE.md`.

**Architecture:** Phase 4's new code lives in three places. (1) A reusable test-only `MockSpecPatcher` (in `tests/conftest.py` or `tests/mock_spec_harness.py`) wraps `client._request_with_retry` (sync) and `async_client._request_with_retry` (async); the wrapper inspects the URL to identify which stage is being called, and for the stage named by `fixture.mock_spec.stage` raises a configured exception (`requests.HTTPError` / `requests.Timeout` / `requests.ConnectionError` / `json.JSONDecodeError`). Non-target stages are stubbed to clean no-match responses so the harness has no live-API dependency. (2) `verifier.py` gains an `_emit_verification_incomplete_if_stages_errored()` helper that runs at the end of `_build_fallback_result` (and the citation_lookup-empty path) and promotes the result to `Status.VERIFICATION_INCOMPLETE` when any stage in the resolution path has `verdict=errored`. (3) `brief_pipeline.py` and `report_template.py` get small lookup tables that translate the four new statuses into download-eligibility (already partial), badge labels, severity colors, and report-template branches; the existing pipeline shape does not change. The Q2 opinion-typing fix uses the existing `_opinion_likelihood` score (no new keyword list) per the Phase 3 retro recommendation; the Q3 `X v. United States` fix is a four-line extension to the common-prefix branch in `_names_match_citation_lookup`.

**Tech Stack:** Python 3.10+, `unittest.mock`, `pytest`, `pytest-asyncio`, `requests`, `aiohttp`, the existing `client.py` / `verifier.py` / `brief_pipeline.py` / `report_template.py` / `tests/data/refactor_corpus.json` / `tests/data/refactor_corpus_loader.py`.

---

## Setup

### §0.1 Worktree, branch, and Phase 3 baseline confirmation

Phase 4 work happens in the existing worktree at `.claude/worktrees/refactor-v0.3` on branch `refactor/v0.3`, currently at tag `refactor/phase-3-acceptance` (commit `d88ad86`). Per CLAUDE.md "Refactor Workflow," merge `origin/main` at the phase boundary to absorb conflicts while they are small.

- [ ] **Step 1: Confirm worktree, branch, and tag**

```
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git tag --points-at HEAD
git status --short
```

Expected: working tree at `.claude/worktrees/refactor-v0.3`, branch `refactor/v0.3`, HEAD at `d88ad86` (or descendant), tag `refactor/phase-3-acceptance` points here, working tree clean. The pre-existing modification to `briefs/fivehouse-v-dod/verification_results.csv` shown in the session-start `git status` is a left-over artifact from a verify-brief run — leave it untouched (Phase 4 does not modify briefs/).

- [ ] **Step 2: Pull origin and merge main drift**

```
git fetch origin
git log --oneline --max-count=10 origin/main ^HEAD
```

If the second command prints commits, `origin/main` has moved since Phase 3 acceptance. Merge it:

```
git merge --no-edit origin/main
```

If the merge produces conflicts in `src/citation_verifier/` or `tests/`, stop and surface them — do not silent-resolve. The merge should be small; the post-Phase-3 acceptance test surface is stable and the cross-repo benchmark (per design §5) stays pinned to `v0.2.0` so no incoming refactor work is expected on main.

- [ ] **Step 3: Confirm venv + .env are present**

```
venv/Scripts/python.exe --version
test -f .env && echo ".env present" || echo ".env MISSING -- copy from primary checkout before live-API tests"
```

Expected: Python 3.10+, `.env present`. The worktree's `.env` is path-explicit (per `client.py`'s `load_dotenv` call) and does not walk up to the parent repo.

### §0.2 Pre-Phase-4 test baselines

Phase 4 changes touch the verifier's status-assignment surface (Task 2), the brief pipeline (Task 8), and corpus pinning (Tasks 4 + 5 + 6). Establish per-suite baselines so per-task regressions can be diffed cleanly.

- [ ] **Step 4: Capture the non-live baseline**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected at Phase 3 acceptance: `325 passed, 5 skipped, 149 deselected, 0 failed` (per the Phase 3 retrospective "Final test state" line). Record the actual count here in the implementer's notes; Phase 4 work should net the deltas called out per task.

- [ ] **Step 5: Capture the live-API baseline (only if `.env` is present and `COURTLISTENER_API_TOKEN` is set)**

```
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py tests/test_phase3_corpus_acceptance.py -v -m live_api
```

Expected: all 141 corpus tests + 7 false_negatives tests pass. **This is also Phase 4's pre-flight check for CL drift.** If anything has gone red since Phase 3 acceptance (CL re-ingest, cluster ID drift, etc.), absorb the pin refresh as a §0.4 task below before starting Task 1.

### §0.3 Create the `docs/notes/wl-disambiguation-limit.md` note (Phase 3 follow-up)

Per the Phase 3 retro under "TODO items touched during Phase 3":

> WL-disambiguation limit (§0.3 finding) — DOCUMENTED. New `docs/notes/wl-disambiguation-limit.md` referenced from survey §4. (Note: the docs/notes/ file referenced in the survey may need to actually be created — Phase 4 should confirm.)

Check whether the file exists; if not, create it with the §0.3 finding from the Phase 3 retro (S6) consolidated into a short standalone note.

- [ ] **Step 6: Check whether the note already exists**

```
test -f docs/notes/wl-disambiguation-limit.md && echo "exists" || echo "missing"
```

If `exists`, skip Step 7 (no work to do). If `missing`, do Step 7.

- [ ] **Step 7: Create the note**

Create `docs/notes/wl-disambiguation-limit.md` (the parent `docs/notes/` directory may also not exist — `mkdir -p` is not on Windows Git Bash; use `venv/Scripts/python.exe -c "import pathlib; pathlib.Path('docs/notes').mkdir(parents=True, exist_ok=True)"`):

```markdown
# Verifier limitation: WL-citation disambiguation when multiple substantive docs share a docket

## Summary

Westlaw assigns a single WL citation (e.g. `2009 WL 2392094`) to one specific
opinion or order on a docket. The verifier cannot disambiguate from CourtListener
docket data alone — both the substantive opinion and the costs-taxation order
that earned the WL number may live on the same docket, and only Westlaw "knows"
which one carried the cite.

## Discovered in

Phase 3 §0.3 fixture validation (Darensburg v. Metro. Transp. Comm'n,
2009 WL 2392094). The WL number maps to the Aug 4, 2009 procedural
costs-taxation order (doc #460), not the substantive July 7, 2009 attorneys'
fees opinion (doc #452). Both docs are on the same docket. CourtListener's
RECAP archive has the documents but no metadata linking the WL number to
either one.

## What the verifier does

Under Phase 3's strict VIA_RECAP gate (`_recap_doc_is_cited_opinion`), the
verifier picks the doc whose `entry_date_filed` falls within ±14 days of the
cited date AND whose description matches opinion-typed keywords. When the
cited date falls within the window for an opinion-typed doc, the verifier
returns `VERIFIED_VIA_RECAP`. When neither doc on the docket satisfies both
gates (as in Darensburg, where doc #460 is procedural and doc #452 is outside
the window), the verifier returns `VERIFIED_DOCKET_ONLY` — the case is real,
the docket exists, but the specific WL-cited document cannot be confidently
identified.

## What would fix it

External Westlaw-index lookup (Westlaw's own metadata maps WL numbers to specific
docs). CourtListener does not currently expose this mapping, and the WL index
is not in the public domain. Until such a data source becomes available, the
verifier accepts `VERIFIED_DOCKET_ONLY` as the honest answer for this class
of cite.

## Fixtures that demonstrate the limit

`verified-docket-only-darensburg-wl-disambiguation` in `tests/data/refactor_corpus.json`.
```

- [ ] **Step 8: Commit Setup outcomes**

Only commit the WL-disambiguation note if Step 7 ran. The baseline runs (Steps 4 + 5) produce no commitable artifacts (they're status checks). The merge from Step 2, if it ran, is its own auto-commit from `git merge`.

```
git add docs/notes/wl-disambiguation-limit.md
git commit -m "docs(v0.3): create wl-disambiguation-limit note per Phase 3 retro follow-up"
```

Push:

```
git push origin refactor/v0.3
```

### §0.4 Corpus-drift pin refresh (only if §0.2 Step 5 found drift)

If the live-API baseline came back red, triage each failure into one of:

- (a) **Cluster ID drift** — CL has re-ingested the case at a new cluster_id. Update the fixture's `expected_final_ids.cluster_id` pin to the live value. Add a brief `phase4_pin_refresh_note` field on the fixture if the drift is non-obvious.
- (b) **Status change** — CL has indexed a previously-missing case (NOT_FOUND → VERIFIED), or a previously-resolved case now scores below threshold (VERIFIED → NOT_FOUND). Apply the new status; document in `phase4_pin_refresh_note`.
- (c) **CL outage / transient** — re-run; if still red after a 30-minute gap, treat as (a) or (b) per the diagnosis.

- [ ] **Step 9: Apply pin refreshes (only if drift surfaced)**

For each drifted fixture, edit `tests/data/refactor_corpus.json` per the diagnosis. Re-run §0.2 Step 5 until clean. Commit:

```
git add tests/data/refactor_corpus.json
git commit -m "test(v0.3): Phase 4 pre-flight corpus pin refresh for CL drift"
git push origin refactor/v0.3
```

---

## File Structure

Phase 4 modifies and creates these files. Each task names its exact targets in its "Files" header.

**Created:**
- `tests/mock_spec_harness.py` — the reusable `MockSpecPatcher` (sync + async) consumed by Phase 4's INCOMPLETE corpus run and any future fixture-driven mock work. (Task 1)
- `tests/test_mock_spec_harness.py` — unit tests for the patcher's URL-routing and exception-injection behavior, against a toy fixture (no live API). (Task 1)
- `tests/test_verification_incomplete_wiring.py` — sync + async unit tests for the design §2.8 internal gate that promotes `errored`-bearing results to `VERIFICATION_INCOMPLETE`. (Task 2)
- `docs/notes/wl-disambiguation-limit.md` — standalone note referenced from `tests/data/refactor_corpus_survey.md` §4. (Setup §0.3, if missing)
- `docs/retrospectives/2026-05-2X-refactor-v0.3-phase-4.md` — Phase 4 retrospective (Task 9). Filename uses the actual completion date.

**Modified:**
- `src/citation_verifier/verifier.py` — (a) new `_emit_verification_incomplete_if_stages_errored()` static helper; called from `_build_fallback_result` and from the citation_lookup-empty fallthrough in `verify()` / `verify_async()`. (b) extend `_OPINION_KEYWORDS` / refactor `_recap_doc_is_cited_opinion` to gate on the existing `_opinion_likelihood` score (per Phase 3 retro Q2 recommendation). (c) extend `_names_match_citation_lookup` common-prefix branch to detect `X v. United States` / `v. State` / `v. Commonwealth` / `v. People` defendant-side patterns (per Q3). (Tasks 2 + 4 + 5)
- `src/citation_verifier/brief_pipeline.py` — extend `_DOWNLOADABLE_STATUSES` already includes the four richer statuses (per Phase 1 mapping); add badge-label / severity logic for the Phase 1c `claims.csv` merge path and the report template's badge_label fallback so `WRONG_CASE`, `VIA_RECAP`, `DOCKET_ONLY`, and `VERIFIED_PARTIAL` get distinguishable presentation. (Task 8)
- `src/citation_verifier/report_template.py` — add severity-color mapping for the four new statuses; add a separate report card class so `WRONG_CASE` reds and `DOCKET_ONLY` yellows render distinctly. (Task 8)
- `tests/test_phase3_corpus_acceptance.py` — the existing `_RUNNABLE` excludes `VERIFICATION_INCOMPLETE`; Phase 4 splits the parametrize into two sets — `_LIVE_RUNNABLE` (still live API) and `_MOCK_RUNNABLE` (Phase 4's INCOMPLETE fixtures, consumed via the new harness). The mock-runnable set does not require a CL token. (Task 3)
- `tests/data/refactor_corpus.json` — Mehar Holdings (per Q2) flips `expected_status` back to `VERIFIED_VIA_RECAP` when the opinion-likelihood gate is in place; Koch and 5 Rule-25(d)/SSA fixtures (per Q3) re-add `cl_display_name_data_bug` to `expected_warnings_subset`. Each affected fixture gets a `phase4_ruling` field documenting the Phase 4 decision (analogous to `phase3_ruling`). (Tasks 4 + 5)
- `tests/data/refactor_corpus_survey.md` — add a new §3.2 "Phase 4 rulings" subsection, parallel to §3.1, summarizing the Q1–Q6 dispositions. (Task 9)
- `CHANGELOG.md` — add the v0.3.0 release entry summarizing Phase 4 behavior changes (VERIFICATION_INCOMPLETE production wiring, opinion-likelihood-based VIA_RECAP gate, X-v-US name-match extension, brief pipeline status-aware presentation). (Task 9)
- `CLAUDE.md` — at the final-acceptance step, delete the "Refactor Workflow (Phases 1–4, ongoing)" section (lines 15–25); collapse the two `VerificationResult fields` pitfall bullets (lines 234 and 235) into one bullet that describes the v0.3 shape as the canonical main-branch shape (drop the "(pre-refactor v0.2 schema — refactor/v0.3 branch reshaped this)" qualifier and the "(Phase 1–3)" qualifier). (Task 10)

**Not touched in Phase 4 (deliberate non-scope):**
- `src/citation_verifier/parser.py` — Phase 4 does not change citation parsing.
- `src/citation_verifier/models.py` — the v0.3 schema is frozen; no new fields. The Q6 `candidates` field decision (Task 7) deliberately defers schema growth.
- `src/citation_verifier/cache.py` — the cache round-trips the v0.3 shape correctly per Phase 2 retro S6; Phase 4's INCOMPLETE results are never cached (they represent infrastructure-failure paths) but the schema is enum-additive-safe so no work is required.
- `web/app.py` — Phase 4 does not touch the FastAPI server. The web app produces the new statuses correctly; presentation polish for them is roadmap (per design §5 web-app note).
- `tests/data/known_real_citations.json` — unchanged. Phase 3 already unmarked the 4 xfails.
- The `Gate` schema in `models.py` — Phase 4 does NOT implement caller-policy gates (`gates: list[GateSpec] | None` parameter on verify entry points). The only gate Phase 4 lands is the internal API-error gate per design §2.8. Caller-policy gates are deferred to a future phase per the user's brief, which named only Q1 + roll-up as the Phase 4 scope.

---

## Task 1: Build the `MockSpecPatcher` harness (HEADLINE — Sonnet implementer + Opus reviewer)

The Phase 3 retro names this as "the main Phase 4 task." The Phase 2.5 corpus has 5 `VERIFICATION_INCOMPLETE` fixtures each carrying a `mock_spec` dict of shape `{stage, failure_mode, attempt_idx, details}`. Phase 4 must consume those mock_specs to drive the verifier through each failure path. The harness is also useful beyond the corpus — any future test that wants to assert verifier behavior under a specific stage failure can reuse it.

**Design choice.** The patcher wraps `_request_with_retry` (sync) and `_request_with_retry` (async) directly, not the lower-level `_session.request` / `aiohttp.ClientSession.request`. This means the existing retry loop (the 429 backoff logic in `client.py:103-144`) is NOT exercised inside the harness — when the corpus says "429 with retries exhausted," the harness simulates the final raised `HTTPError` directly. The retry loop's own correctness is verified separately by the existing client tests; Phase 4's harness focuses on what the verifier sees when retries have failed. This trade keeps the harness simple and avoids the brittleness of constructing mock `requests.Response` / `aiohttp.ClientResponse` objects.

**Files:**
- Create: `tests/mock_spec_harness.py`
- Create: `tests/test_mock_spec_harness.py`

- [ ] **Step 1: Write the failing harness unit tests first**

Create `tests/test_mock_spec_harness.py`:

```python
"""Phase 4 Task 1 — unit tests for the MockSpecPatcher.

These tests verify the patcher's URL-routing and exception-injection
behavior against a toy CitationVerifier setup. They do NOT touch the
live CL API.
"""
from __future__ import annotations

import json

import pytest
import requests

from citation_verifier.client import CourtListenerClient
from citation_verifier.models import StageName, StageVerdict
from citation_verifier.verifier import CitationVerifier
from tests.mock_spec_harness import MockSpecPatcher, _STAGE_URL_PATTERNS


def _client(monkeypatch) -> CourtListenerClient:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-not-used")
    return CourtListenerClient(api_token="test-token-not-used")


class TestStageRouting:
    """The harness identifies stages by URL pattern. The patterns must
    match the URLs the client actually constructs."""

    def test_citation_lookup_endpoint_routes_to_citation_lookup(self):
        assert _STAGE_URL_PATTERNS["citation_lookup"].search(
            "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
        )

    def test_opinion_search_endpoint_routes_to_opinion_search(self):
        # search?type=o
        assert _STAGE_URL_PATTERNS["opinion_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=o&q=foo"
        )

    def test_recap_docket_search_routes_to_recap_docket_search(self):
        assert _STAGE_URL_PATTERNS["recap_docket_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=r&q=foo"
        )

    def test_recap_document_search_routes_to_recap_document_search(self):
        assert _STAGE_URL_PATTERNS["recap_document_search"].search(
            "https://www.courtlistener.com/api/rest/v4/search/?type=rd&q=foo"
        )


class TestSyncFailureInjection:
    def test_http_500_on_citation_lookup_raises_http_error(self, monkeypatch):
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            with pytest.raises(requests.HTTPError):
                client.citation_lookup("Obergefell v. Hodges, 576 U.S. 644 (2015)")

    def test_connection_error_on_citation_lookup_raises_connection_error(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "connection_error",
                  "attempt_idx": 0, "details": ""},
        ):
            with pytest.raises(requests.ConnectionError):
                client.citation_lookup("Obergefell v. Hodges, 576 U.S. 644 (2015)")

    def test_timeout_on_opinion_search_returns_empty_for_citation_lookup(
        self, monkeypatch,
    ):
        """citation_lookup is stubbed to clean no-match; opinion_search times out."""
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "opinion_search", "failure_mode": "timeout",
                  "attempt_idx": 0, "details": ""},
        ):
            # citation_lookup is NOT the target — returns clean no-match.
            result = client.citation_lookup("Nonexistent Case, 999 F.3d 999 (2099)")
            assert result == []
            # opinion_search IS the target — raises Timeout.
            with pytest.raises(requests.Timeout):
                client.search_opinions(case_name="X")

    def test_non_target_stage_calls_return_clean_no_match(self, monkeypatch):
        """Calls to non-target stages get stubbed empty responses, NOT live
        API calls. This is what makes the harness CI-safe (no token needed)."""
        client = _client(monkeypatch)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            # search_opinions is NOT the target -> empty list, no raise.
            assert client.search_opinions(case_name="X") == []
            assert client.search_recap(q='"X v. Y"') == []


class TestVerifierEndToEndUnderHarness:
    """The verifier driven by an instrumented client under the harness
    must record `verdict=errored` on the target stage's path entry."""

    def test_verify_http_500_records_errored_on_citation_lookup(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(
            client,
            spec={"stage": "citation_lookup", "failure_mode": "http_500",
                  "attempt_idx": 0, "details": ""},
        ):
            result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")
        entries = [e for e in result.resolution_path
                   if e.stage == StageName.citation_lookup]
        assert entries, "citation_lookup stage entry missing"
        assert entries[0].verdict == StageVerdict.errored
        # Phase 4 Task 2 will assert status==VERIFICATION_INCOMPLETE here;
        # this test only confirms the harness wired the error correctly.
```

Run them (expect ImportError on the harness module — the file does not exist yet):

```
venv/Scripts/python.exe -m pytest tests/test_mock_spec_harness.py -q
```

Expected: collection-time `ImportError: cannot import name 'MockSpecPatcher'`.

- [ ] **Step 2: Create `tests/mock_spec_harness.py`**

```python
"""Phase 4 Task 1 — MockSpecPatcher.

Consumes a corpus mock_spec dict and wraps the client's
_request_with_retry method (sync + async) so the verifier sees the
configured failure on the target stage and clean no-match responses
on all other stages.

URL-routing maps the CourtListener REST endpoint substrings to the
StageName values the verifier emits. Calls whose URL matches the
target stage's pattern raise the spec's exception type; everything
else returns an empty-but-well-formed response shape.

The patcher operates at the _request_with_retry layer, so the
existing 429 retry loop in client.py is NOT exercised. When the
spec says "http_429_no_retry_after" with attempt_idx=N, the harness
simulates "all retries exhausted" by raising the terminal HTTPError
on the first call. The retry loop's correctness is verified
separately by the existing client tests; this harness focuses on
what the verifier sees post-exhaustion.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from unittest.mock import patch

import requests

# Stage-name -> URL-substring regex. Used to classify each
# _request_with_retry call into the StageName the verifier would
# attribute it to. The order in which patterns are tried matters
# only for citation_lookup (which is the most specific endpoint);
# the search endpoints are mutually exclusive by query-string.
_STAGE_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    "citation_lookup": re.compile(r"/citation-lookup/"),
    "opinion_search": re.compile(r"/search/\?(?:[^&]*&)*type=o(?:&|$)"),
    "recap_document_search": re.compile(r"/search/\?(?:[^&]*&)*type=rd(?:&|$)"),
    "recap_docket_search": re.compile(r"/search/\?(?:[^&]*&)*type=r(?:&|$)"),
    "plain_docket_search": re.compile(r"/search/\?(?:[^&]*&)*type=d(?:&|$)"),
    # caption_investigation hits multiple endpoints (clusters, dockets,
    # recap-documents, opinion-text) and is not a clean URL pattern;
    # Phase 4 does not have a mock_spec.stage="caption_investigation"
    # fixture, so this entry is forward-looking only.
    "caption_investigation": re.compile(r"/(?:clusters|dockets|recap-documents)/\d+/"),
}


# Empty-but-well-formed response shapes for non-target stages. Returned
# as plain dicts; the sync client wraps via _session.request -> Response,
# but here we are patching _request_with_retry directly so the dict
# shape is what the caller's .json() consumer receives.
_CLEAN_NO_MATCH = {
    "citation_lookup": [],            # Citation lookup returns a top-level list.
    "opinion_search": {"results": []},
    "recap_document_search": {"results": []},
    "recap_docket_search": {"results": []},
    "plain_docket_search": {"results": []},
    "caption_investigation": {},      # Cluster/docket/opinion-text endpoints; empty dict is acceptable.
    "_default": {"results": []},
}


def _classify_url(url: str) -> str:
    for stage, pat in _STAGE_URL_PATTERNS.items():
        if pat.search(url):
            return stage
    return "_default"


def _raise_for_failure_mode(mode: str, stage: str) -> None:
    """Raise the exception type associated with the spec's failure_mode.

    The mapping mirrors client.py's _request_with_retry behavior:
    * http_500 / http_502 / http_503 -> requests.HTTPError (5xx is not retried;
      raise_for_status raises HTTPError on the first non-200 non-429 response).
    * http_429_no_retry_after -> requests.HTTPError after retries exhausted.
    * timeout -> requests.Timeout (raised by the underlying session).
    * connection_error -> requests.ConnectionError (TCP/DNS-level failure).
    * json_malformed -> json.JSONDecodeError (raised inside _request_with_retry
      when resp.json() fails; the verifier sees the same exception type).
    """
    if mode in ("http_500", "http_502", "http_503"):
        # Mock the Response object so HTTPError carries a useful str().
        resp = requests.Response()
        resp.status_code = int(mode.split("_")[1])
        resp.reason = {500: "Internal Server Error",
                       502: "Bad Gateway",
                       503: "Service Unavailable"}[resp.status_code]
        raise requests.HTTPError(f"{resp.status_code} {resp.reason}", response=resp)
    if mode == "http_429_no_retry_after":
        resp = requests.Response()
        resp.status_code = 429
        resp.reason = "Too Many Requests"
        raise requests.HTTPError(
            "429 Too Many Requests (retries exhausted)", response=resp,
        )
    if mode == "timeout":
        raise requests.Timeout(f"Read timed out on {stage} stage (15s)")
    if mode == "connection_error":
        raise requests.ConnectionError(f"Connection error on {stage} stage")
    if mode == "json_malformed":
        # Match what client.py would raise on a malformed JSON body.
        raise json.JSONDecodeError("Expecting value", "", 0)
    raise ValueError(f"Unknown mock_spec.failure_mode: {mode!r}")


class MockSpecPatcher:
    """Context manager that patches client._request_with_retry to
    inject a stage-targeted failure per the corpus mock_spec.

    Usage::

        with MockSpecPatcher(client, spec=fixture.mock_spec):
            result = verifier.verify(fixture.citation)

    The patcher tracks per-stage call counts so attempt_idx is honored:
    only when the call count for the target stage reaches the spec's
    attempt_idx does the configured exception fire. Calls before that
    return _CLEAN_NO_MATCH for the stage. (For attempt_idx=0 — the
    common case — the first call fires.)
    """

    def __init__(self, client: Any, spec: dict[str, Any]) -> None:
        self.client = client
        self.spec = spec
        self.target_stage: str = spec["stage"]
        self.failure_mode: str = spec["failure_mode"]
        self.target_attempt_idx: int = int(spec.get("attempt_idx", 0))
        self._stage_call_counts: dict[str, int] = {}
        self._patcher: Any = None
        self._original: Callable[..., Any] | None = None

    def __enter__(self) -> "MockSpecPatcher":
        self._original = self.client._request_with_retry
        # Wrap both the bound method and the underlying type for safety.
        # The bound method on the instance is what the verifier consumes,
        # so patching it via setattr is sufficient.
        wrapped = self._build_wrapped(self._original)
        self.client._request_with_retry = wrapped  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        # Restore the original.
        self.client._request_with_retry = self._original  # type: ignore[assignment]

    def _build_wrapped(
        self, original: Callable[..., Any],
    ) -> Callable[..., Any]:
        def wrapped(method: str, url: str, **kwargs: Any) -> Any:
            stage = _classify_url(url)
            count = self._stage_call_counts.get(stage, 0)
            self._stage_call_counts[stage] = count + 1

            if stage == self.target_stage and count == self.target_attempt_idx:
                _raise_for_failure_mode(self.failure_mode, stage)

            # Non-target call: return a stubbed clean response.
            # The sync _request_with_retry returns a requests.Response;
            # the async one returns a parsed dict. We return whichever
            # shape matches what the client's .citation_lookup /
            # .search_opinions / etc. consumers expect after their
            # post-processing. Inspect the caller's downstream
            # expectation by stage type.
            #
            # Sync: citation_lookup() calls resp.json() on the return
            # value, expecting a list. search_opinions() and friends
            # call resp.json() expecting a dict with "results".
            # The original _request_with_retry returns a Response, so
            # the wrapper must return a Response-like that .json()'s
            # to the right shape.
            payload = _CLEAN_NO_MATCH.get(stage, _CLEAN_NO_MATCH["_default"])
            return _StubResponse(payload)

        return wrapped


class _StubResponse:
    """Minimal Response-like for sync _request_with_retry's contract:
    .json() returns the stored payload, .status_code is 200,
    .raise_for_status() is a no-op."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


# Async variant — Phase 4 Task 1 follow-on. The async client's
# _request_with_retry returns a parsed dict directly (not a Response),
# so the async patcher returns the payload directly.
class AsyncMockSpecPatcher:
    """Async equivalent of MockSpecPatcher.

    The async client's _request_with_retry returns a parsed dict
    directly; this patcher returns the payload bare (no _StubResponse
    wrapper)."""

    def __init__(self, async_client: Any, spec: dict[str, Any]) -> None:
        self.client = async_client
        self.spec = spec
        self.target_stage: str = spec["stage"]
        self.failure_mode: str = spec["failure_mode"]
        self.target_attempt_idx: int = int(spec.get("attempt_idx", 0))
        self._stage_call_counts: dict[str, int] = {}
        self._original: Callable[..., Any] | None = None

    async def __aenter__(self) -> "AsyncMockSpecPatcher":
        self._original = self.client._request_with_retry
        self.client._request_with_retry = self._build_wrapped(self._original)  # type: ignore[assignment]
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.client._request_with_retry = self._original  # type: ignore[assignment]

    def _build_wrapped(
        self, original: Callable[..., Any],
    ) -> Callable[..., Any]:
        async def wrapped(method: str, url: str, **kwargs: Any) -> Any:
            stage = _classify_url(url)
            count = self._stage_call_counts.get(stage, 0)
            self._stage_call_counts[stage] = count + 1
            if stage == self.target_stage and count == self.target_attempt_idx:
                _raise_for_failure_mode(self.failure_mode, stage)
            return _CLEAN_NO_MATCH.get(stage, _CLEAN_NO_MATCH["_default"])
        return wrapped
```

- [ ] **Step 3: Run the harness unit tests to confirm they pass**

```
venv/Scripts/python.exe -m pytest tests/test_mock_spec_harness.py -q
```

Expected: all PASS. If any fail, common pitfalls:

- The URL regex order matters: `recap_docket_search` (type=r) and `recap_document_search` (type=rd) — the `rd` test must come first in the dict iteration since `type=r` is a substring of `type=rd`. The provided dict orders them rd before r already; verify the regex `(?:&|$)` boundary holds.
- `_request_with_retry` is a bound method on the instance; patching via `setattr` works but only on this specific instance. The harness only needs per-instance scope (it takes `client` as argument), so this is fine.
- The sync client's `.citation_lookup()` does `resp = self._request_with_retry(...)` then `data: Any = resp.json()`. The `_StubResponse` must implement `.json()` to return the bare list (not wrap in `{"results": [...]}`). The provided `_CLEAN_NO_MATCH["citation_lookup"] = []` honors this.

- [ ] **Step 4: Run the broader unit suite to confirm no regressions**

The harness module imports `from citation_verifier.client import CourtListenerClient` and from `tests.mock_spec_harness` — the latter is a new top-level test module. Confirm the broader suite still passes (importing test modules across tests/ should not regress anything):

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected: same pass count as §0.2 Step 4 baseline + 12 new (from `test_mock_spec_harness.py`).

- [ ] **Step 5: Commit**

```
git add tests/mock_spec_harness.py tests/test_mock_spec_harness.py
git commit -m "feat(v0.3): Task 1 — MockSpecPatcher harness for VERIFICATION_INCOMPLETE fixtures

$(cat <<'EOF'
Phase 4 Task 1. Sync + async patchers wrap client._request_with_retry
to inject stage-targeted failures (http_500/502/503, http_429
exhausted, timeout, connection_error, json_malformed) per the corpus
mock_spec dict. URL-routing classifies each call into the StageName
the verifier would attribute it to; the target stage's matching
attempt raises the configured exception, all other stages return
empty-but-well-formed stub responses. Unit tests cover URL routing,
each failure mode, and verifier integration. No live-API dependency.

Headline Task 1 of Phase 4 — consumed by Task 3 to drive the 5
VERIFICATION_INCOMPLETE corpus fixtures.
EOF
)"
git push origin refactor/v0.3
```

- [ ] **Step 6: Submit for two-stage review**

Per the user's brief, the mock harness is a HEADLINE task warranting two-stage review (Sonnet implementer + Opus reviewer). The reviewer's focus areas:
- **URL-classification correctness**: do the regexes actually identify the right stage, including for paginated `&page=2` URLs and url-encoded query strings?
- **Exception-type fidelity**: do the raised exception types match what the verifier's `except Exception as exc` blocks (`verifier.py:486-488`, `:512-516`) see in production?
- **Stub-response shape**: does `_StubResponse.json()` return the shape that each downstream client method expects after its own post-processing (`citation_lookup` flattens, `search_opinions` reads `.get("results", [])`, etc.)?
- **Async parity**: does `AsyncMockSpecPatcher` produce identical observable behavior to the sync patcher, modulo `await` boundaries?
- **No live-API leak**: does the harness completely isolate from live CL (the `_request_with_retry` patch covers all client method paths)?

If the reviewer finds issues, fold the fixes into a follow-up commit on `refactor/v0.3` before starting Task 2.

---

## Task 2: VERIFICATION_INCOMPLETE production wiring per design §2.8 (HEADLINE — Sonnet implementer + Opus reviewer)

Design §2.8 says: "API errors, rate limits, and timeouts must not silently degrade to `NOT_FOUND`. The verifier itself enforces this: any stage that errors out without a clean 'no match' response triggers status `VERIFICATION_INCOMPLETE`. The resolution_path captures which stage(s) failed. No caller policy can disable this — it protects the integrity of the verifier's own semantics."

Currently the verifier catches stage exceptions and records `verdict=errored` on the path entry (see e.g. `verifier.py:486-488`, where `t.errored(error_type=type(exc).__name__, ...)` runs), but the fall-through still produces `Status.NOT_FOUND` (silent degradation). Phase 4 wires the internal gate.

**Decision rule (recommended to implementer).** The simplest correct rule: if ANY entry in `result.resolution_path` has `verdict == StageVerdict.errored` AND no entry has `verdict in (resolved, partial)`, set `Status.VERIFICATION_INCOMPLETE`. This honors design §2.8's intent without overcorrecting: a resolved stage trumps an errored later stage (e.g., citation_lookup resolves, opinion_search errors during a separate downstream lookup that's not actually load-bearing). The asymmetry "errored short-circuits to INCOMPLETE only when nothing else resolved" is what §2.8 means by "fail-closed only at the boundary of verifier integrity."

**Caption_investigation defensive-fallback decision (Phase 3 retro Q1 sub-question).** The Phase 3 retro asks: "decide whether `caption_investigation`'s defensive fallback (currently VERIFIED + `cl_display_name_data_bug` on infra failure) upgrades to `VERIFICATION_INCOMPLETE` once the gate lands."

**Recommended disposition (implementer free to override with brief justification):** Keep the existing defensive fallback. Rationale: when citation_lookup successfully resolved the cluster, the verifier has *answered the verification question* — the cluster exists, the citation maps to it. caption_investigation is a *refinement* that classifies whether the case-name divergence is cosmetic (`name_formatting_noise`), a CL data quirk (`cl_display_name_data_bug`), or a hallucination (`WRONG_CASE`). Failing the refinement does not invalidate the underlying verification. Per design §1.5 ("Fail-closed only at the boundary of verifier integrity"), a refinement-stage failure should not promote the result to INCOMPLETE; the existing warning already tells the consumer the refinement was incomplete. The implementer should update the warning *message* to make the refinement-failure context explicit, but not the *status*.

**Files:**
- Modify: `src/citation_verifier/verifier.py` — add `_promote_to_incomplete_if_only_errored()` static helper near `_VERIFIED_SCORE_THRESHOLD`; call it from `_finalize_result` (so every result passes through the gate uniformly) OR from the two call sites in `_build_fallback_result` + the citation_lookup-empty fallthrough (more surgical). Implementer's call; the centralized `_finalize_result` placement is preferred for uniformity but check the existing tests for any that assert "errored stages still produce VERIFIED" — those would need to demonstrate the resolved stage's precedence under the rule above.
- Create: `tests/test_verification_incomplete_wiring.py` — sync + async unit tests covering each failure mode + the resolved-stage-trumps-errored case.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_verification_incomplete_wiring.py`:

```python
"""Phase 4 Task 2 — VERIFICATION_INCOMPLETE production wiring per design §2.8.

The internal API-error gate: if any stage in resolution_path is
`errored` AND no stage has `resolved`/`partial`, status is
VERIFICATION_INCOMPLETE (not NOT_FOUND). When a stage IS resolved,
errors in later stages are tolerated and status stands.
"""
from __future__ import annotations

import asyncio

import pytest

from citation_verifier.client import (
    AsyncCourtListenerClient,
    CourtListenerClient,
)
from citation_verifier.models import StageName, StageVerdict, Status
from citation_verifier.verifier import CitationVerifier
from tests.mock_spec_harness import (
    AsyncMockSpecPatcher,
    MockSpecPatcher,
)


def _client(monkeypatch) -> CourtListenerClient:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test")
    return CourtListenerClient(api_token="test")


class TestSyncWiring:
    def test_http_500_on_citation_lookup_produces_verification_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup", "failure_mode": "http_500",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Obergefell v. Hodges, 576 U.S. 644 (2015)")
        assert result.status == Status.VERIFICATION_INCOMPLETE
        assert result.final_ids.cluster_id is None
        assert result.final_ids.docket_id is None
        # The path must record the errored stage; consumers depend on this.
        errored = [e for e in result.resolution_path
                   if e.verdict == StageVerdict.errored]
        assert any(e.stage == StageName.citation_lookup for e in errored)

    def test_connection_error_on_citation_lookup_produces_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup", "failure_mode": "connection_error",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Hanover Shoe, Inc. v. United Shoe, 392 U.S. 481 (1968)")
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_timeout_on_opinion_search_produces_incomplete(self, monkeypatch):
        """citation_lookup returns clean no_match; opinion_search times out.
        Per §2.8: cannot silently degrade to NOT_FOUND."""
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "opinion_search", "failure_mode": "timeout",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify(
                "Anderson v. Furst, No. 17-cv-12676, "
                "2018 WL 4407750 (E.D. Mich. Sept. 17, 2018)"
            )
        assert result.status == Status.VERIFICATION_INCOMPLETE
        stages_errored = [
            e.stage for e in result.resolution_path
            if e.verdict == StageVerdict.errored
        ]
        assert StageName.opinion_search in stages_errored

    def test_http_429_exhausted_produces_incomplete(self, monkeypatch):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "citation_lookup",
            "failure_mode": "http_429_no_retry_after",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Bossart v. King Cnty., 2025 WL 459154 "
                              "(W.D. Wash. Feb. 11, 2025)")
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_json_malformed_on_recap_docket_search_produces_incomplete(
        self, monkeypatch,
    ):
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        with MockSpecPatcher(client, spec={
            "stage": "recap_docket_search", "failure_mode": "json_malformed",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify(
                "Mehar Holdings, LLC v. Evanston Ins. Co., "
                "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
            )
        assert result.status == Status.VERIFICATION_INCOMPLETE

    def test_clean_no_match_everywhere_still_produces_not_found(
        self, monkeypatch,
    ):
        """Sanity: with no errored stages, the existing NOT_FOUND path holds.
        Phase 4 must NOT promote clean negatives to INCOMPLETE."""
        client = _client(monkeypatch)
        v = CitationVerifier(client)
        # No mock_spec — but stub the client manually for a fully-clean run.
        # Easier: use the patcher with a fake target stage that no call
        # matches; the patcher then stubs every call to clean no-match.
        with MockSpecPatcher(client, spec={
            "stage": "caption_investigation",  # never reached for an unresolvable cite
            "failure_mode": "http_500",
            "attempt_idx": 0, "details": "",
        }):
            result = v.verify("Nonexistent v. Madeup, 999 F.3d 999 (5th Cir. 2099)")
        assert result.status == Status.NOT_FOUND


class TestAsyncWiring:
    @pytest.mark.asyncio
    async def test_async_http_500_produces_verification_incomplete(self):
        async with AsyncCourtListenerClient(api_token="test") as async_client:
            v = CitationVerifier(client=None, async_client=async_client)
            async with AsyncMockSpecPatcher(async_client, spec={
                "stage": "citation_lookup", "failure_mode": "http_500",
                "attempt_idx": 0, "details": "",
            }):
                result = await v.verify_async(
                    "Obergefell v. Hodges, 576 U.S. 644 (2015)"
                )
            assert result.status == Status.VERIFICATION_INCOMPLETE
```

Note on the async test: `CitationVerifier`'s constructor signature for the async client may differ — confirm via `grep -n "def __init__" src/citation_verifier/verifier.py`. If the verifier takes a single `client` param that can be either sync or async, adjust the test instantiation accordingly.

- [ ] **Step 2: Run the failing tests to confirm they fail before wiring**

```
venv/Scripts/python.exe -m pytest tests/test_verification_incomplete_wiring.py -q
```

Expected: all tests in `TestSyncWiring` (except the sanity test) FAIL with `assert Status.NOT_FOUND == Status.VERIFICATION_INCOMPLETE`. The sanity test passes (current behavior is correct for clean negatives).

- [ ] **Step 3: Add the `_promote_to_incomplete_if_only_errored` helper**

In `src/citation_verifier/verifier.py`, add as a static method on `CitationVerifier`, located near `_VERIFIED_SCORE_THRESHOLD` (top of file):

```python
@staticmethod
def _promote_to_incomplete_if_only_errored(
    status: Status,
    resolution_path: list[ResolutionPathEntry],
) -> Status:
    """Design §2.8 internal gate: API errors must not silently degrade
    to NOT_FOUND. If any stage entry has verdict=errored AND no entry
    has verdict in (resolved, partial), promote to VERIFICATION_INCOMPLETE.

    A resolved or partial stage trumps later errors — the verification
    question was answered at that stage, and a downstream error during
    a refinement / fallback is not a verifier-integrity failure.

    Pre-promoted statuses (anything other than NOT_FOUND) are not
    re-evaluated: an already-resolved status carries its own truth.
    """
    if status != Status.NOT_FOUND:
        return status
    has_errored = any(
        e.verdict == StageVerdict.errored for e in resolution_path
    )
    has_resolved = any(
        e.verdict in (StageVerdict.resolved, StageVerdict.partial)
        for e in resolution_path
    )
    if has_errored and not has_resolved:
        return Status.VERIFICATION_INCOMPLETE
    return status
```

- [ ] **Step 4: Wire it into `_finalize_result`**

The cleanest placement is `_finalize_result` itself — every result the verifier returns flows through it, so the gate applies uniformly to all entry points (`verify()`, `verify_async()`, `verify_batch()`). In `verifier.py:74-111`, modify `_finalize_result` to consult the gate just before constructing the `VerificationResult`:

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
    recap_document_id: int | None = None,
    absolute_url: str | None = None,
    text_source: TextSource | None = None,
    warnings: list[Warning] | None = None,
) -> VerificationResult:
    path = builder.entries()
    # Phase 4 Task 2: design §2.8 internal gate. Promote NOT_FOUND to
    # VERIFICATION_INCOMPLETE when only errored stages exist.
    status = self._promote_to_incomplete_if_only_errored(status, path)
    # When promoting to INCOMPLETE, also null out any partial IDs the
    # caller may have set — the verifier did not authoritatively answer
    # and consumers must not treat partial IDs as truth.
    if status == Status.VERIFICATION_INCOMPLETE:
        cluster_id = None
        docket_id = None
        recap_document_id = None
        absolute_url = None
        text_source = None
    return VerificationResult(
        citation_as_written=citation_text,
        parsed_citation=parsed,
        status=status,
        final_ids=FinalIds(
            cluster_id=cluster_id,
            opinion_id=None,
            docket_id=docket_id,
            recap_document_id=recap_document_id,
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

The ID-nulling on INCOMPLETE is defensive: if a stage errored partway through producing a candidate match (e.g. citation_lookup raised after pulling a cluster), no candidate should leak into `final_ids` — the consumer must not see an INCOMPLETE result that nonetheless points to a cluster.

- [ ] **Step 5: Run the failing tests to confirm they pass**

```
venv/Scripts/python.exe -m pytest tests/test_verification_incomplete_wiring.py -q
```

Expected: all PASS. If any fail:
- The `_finalize_result` placement may be bypassed in some paths. Audit `verify()`, `verify_async()`, `verify_batch()`, and the citation_lookup-empty fallthroughs to confirm every code path that returns a `VerificationResult` goes through `_finalize_result`. The Phase 3 plan refactor consolidated this, but spot-check is worth it.
- For the timeout-on-opinion-search case, confirm the existing `_search_fallback` error handling actually marks the stage `errored` and falls through to `_build_fallback_result` (which then calls `_finalize_result`). Trace via `grep -n "t.errored" src/citation_verifier/verifier.py`.
- For the async case, confirm `verify_async()` calls `_finalize_result` (a sync helper that constructs the result dataclass — no awaitable needed inside it).

- [ ] **Step 6: Update caption_investigation's defensive-fallback warning message**

In `verifier.py:512-530` (sync) and the corresponding async block, the existing defensive-fallback warning reads:

> `Name mismatch flagged by citation_lookup but caption_investigation could not complete ({type(exc).__name__}). Treating as VERIFIED + warning.`

This message is correct for what it does, but the Phase 3 retro asked Phase 4 to decide whether the defensive fallback should upgrade. Per the recommended disposition in this task's preamble (keep the existing fallback), update the message to make the rationale explicit:

```python
hit_finalize["warnings"] = [Warning(
    category=WarningCategory.cl_display_name_data_bug,
    message=(
        f"Citation_lookup resolved the cluster, but caption_investigation "
        f"could not complete ({type(exc).__name__}). The citation is verified "
        f"(the cluster exists); the case-name divergence between the brief "
        f"and CL's caption is unclassified. Per design §2.8, refinement-stage "
        f"failures do not trigger VERIFICATION_INCOMPLETE."
    ),
)]
```

The cross-reference to §2.8 in the message text doubles as documentation for anyone debugging from the warning output. Apply the same change to the async mirror.

- [ ] **Step 7: Run the broader unit suite to confirm no regression**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected: same pass count as §0.2 Step 4 baseline + 12 from Task 1 + ~7 from this task. If any existing tests went red, the most likely culprit is a test that asserts `Status.NOT_FOUND` on a code path that now produces `errored`-stage entries (and so promotes to INCOMPLETE). Triage each: either (a) the test is asserting incorrect behavior and should be updated, or (b) the test exposes an over-broad gate. Per the design rule, (a) is the expected disposition.

- [ ] **Step 8: Commit**

```
git add src/citation_verifier/verifier.py tests/test_verification_incomplete_wiring.py
git commit -m "feat(v0.3): Task 2 — VERIFICATION_INCOMPLETE production wiring (design §2.8 internal gate)

$(cat <<'EOF'
Phase 4 Task 2 (HEADLINE). _finalize_result now consults the design
§2.8 internal gate: when status would be NOT_FOUND but the
resolution_path has any errored entries AND no resolved/partial
entries, promote to VERIFICATION_INCOMPLETE. Per-stage IDs are nulled
on promotion so consumers don't see partial truth.

Resolved-stage-trumps-errored asymmetry honors §2.8's intent: API
failures during refinement / late fallback don't invalidate a stage
that already answered the verification question.

caption_investigation's defensive fallback (VERIFIED + cl_display_name_
data_bug warning on infra failure) is preserved per the Phase 3 retro
Q1 sub-question disposition: refinement-stage failures don't promote.
Warning message updated to make the §2.8 rationale explicit.

Sync + async unit tests cover the 5 failure modes the corpus declares
plus the clean-no-match-stays-NOT_FOUND sanity case.
EOF
)"
git push origin refactor/v0.3
```

- [ ] **Step 9: Submit for two-stage review**

Per the user's brief, VERIFICATION_INCOMPLETE wiring is a HEADLINE task warranting Opus review. Reviewer focus:
- **Decision-rule scope**: is "any errored stage + no resolved/partial" the right rule? Consider edge cases like citation_lookup resolves, opinion_search errors during a fallback that wouldn't have been reached anyway — does the current rule handle these correctly?
- **ID-nulling on promotion**: is the defensive null-out the right call, or does some downstream consumer benefit from seeing the partial-candidate ID even under INCOMPLETE? (Check `brief_pipeline.py` and the web app.)
- **Caption_investigation disposition**: is "keep defensive fallback" the right call per design §1.5? Could there be cases where caption_investigation failure should promote — e.g., if the divergence detected at citation_lookup is so severe that without the investigation the verifier can't honestly say "verified"?
- **`_finalize_result` placement**: are there code paths that return a `VerificationResult` bypassing `_finalize_result`? (Search for `return VerificationResult(` and confirm every site is `_finalize_result`'s constructor or a known exception.)

---

## Task 3: Wire the 5 VERIFICATION_INCOMPLETE corpus fixtures through the harness (depends on Tasks 1+2)

Phase 3 left `tests/test_phase3_corpus_acceptance.py` with `_RUNNABLE = [fx for fx in _ALL_FIXTURES if fx.expected_status != "VERIFICATION_INCOMPLETE"]` — the INCOMPLETE fixtures were excluded because no harness existed. Phase 4 splits the parametrize: live-API fixtures stay on the existing run, mock-driven INCOMPLETE fixtures run on a new parametrize that uses the harness.

**Files:**
- Modify: `tests/test_phase3_corpus_acceptance.py`

- [ ] **Step 1: Restructure the parametrize**

Edit `tests/test_phase3_corpus_acceptance.py`. Replace the existing `_RUNNABLE` constant and `test_corpus_fixture_status` parametrize with a split:

```python
_ALL_FIXTURES_BY_RUNNABILITY = {
    "live": [fx for fx in _ALL_FIXTURES
             if fx.expected_status != "VERIFICATION_INCOMPLETE"],
    "mock": [fx for fx in _ALL_FIXTURES
             if fx.expected_status == "VERIFICATION_INCOMPLETE"],
}
_LIVE_RUNNABLE = _ALL_FIXTURES_BY_RUNNABILITY["live"]
_MOCK_RUNNABLE = _ALL_FIXTURES_BY_RUNNABILITY["mock"]

# Existing live-API tests stay parameterized over _LIVE_RUNNABLE.
# Rename the parametrize ids decorator to use _LIVE_RUNNABLE wherever
# it currently uses _RUNNABLE. (Three test functions to update.)


@pytest.mark.parametrize("fx", _MOCK_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_incomplete_status_via_mock(fx, monkeypatch):
    """Phase 4 Task 3: INCOMPLETE fixtures consume the corpus mock_spec
    via the MockSpecPatcher. Does not require COURTLISTENER_API_TOKEN."""
    from tests.mock_spec_harness import MockSpecPatcher
    from citation_verifier.client import CourtListenerClient
    from citation_verifier.models import Status
    from citation_verifier.verifier import CitationVerifier

    assert fx.mock_spec is not None, (
        f"{fx.id}: VERIFICATION_INCOMPLETE fixture must have mock_spec"
    )
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-not-used")
    client = CourtListenerClient(api_token="test-token-not-used")
    v = CitationVerifier(client)
    with MockSpecPatcher(client, spec=fx.mock_spec):
        result = v.verify(fx.citation)
    assert result.status == Status.VERIFICATION_INCOMPLETE, (
        f"{fx.id}: expected VERIFICATION_INCOMPLETE, got {result.status.value}\n"
        f"  Mock spec: {fx.mock_spec}\n"
        f"  Resolution path: "
        f"{[(e.stage.value, e.verdict.value) for e in result.resolution_path]}"
    )
    # Final IDs must all be null on INCOMPLETE (Task 2 enforces this).
    assert result.final_ids.cluster_id is None
    assert result.final_ids.docket_id is None
    assert result.final_ids.recap_document_id is None
```

The mock-driven test does NOT carry the `pytestmark = pytest.mark.live_api` mark (the module-level mark only applies to the live tests). Move the live-api mark from module-level to per-function on the three existing live tests, OR keep it module-level and override on this one function with `@pytest.mark.parametrize` + `@pytest.mark.no_live_api` (the latter requires the marker registered in `pyproject.toml`). The first option is cleaner:

```python
# At top of file, REMOVE the module-level mark:
# pytestmark = pytest.mark.live_api  <-- delete

# On each of the three existing test_corpus_fixture_* functions, add:
@pytest.mark.live_api
@pytest.mark.parametrize("fx", _LIVE_RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_status(fx, verifier):
    ...
```

- [ ] **Step 2: Run the mock-driven INCOMPLETE tests**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py::test_corpus_fixture_incomplete_status_via_mock -v
```

Expected: 5 PASSED (one per VERIFICATION_INCOMPLETE fixture). Total wall time should be sub-second since no network calls happen.

If any fail, the most likely causes:
- The Mehar Holdings fixture (`json_malformed on recap_docket_search`) requires citation_lookup to return clean no-match AND opinion_search to return clean no-match before recap_docket_search runs. The MockSpecPatcher does that automatically (it stubs non-target stages), but confirm the verifier's fallback ladder actually reaches `recap_docket_search` for this citation. If parser logic short-circuits earlier (e.g. citation parses as a state cite and skips RECAP), the test will fail not with a status mismatch but with the recap_docket_search stage never appearing in the path. Add a per-fixture diagnostic to the assertion to surface this.
- For Anderson v. Furst (opinion_search timeout), confirm the verifier actually calls opinion_search on this WL cite. If parser routing pushes it straight to recap_docket_search (skipping opinion_search for WL cites), the timeout never fires and the test fails. Possible fixture-level fix: change the mock_spec to target whichever stage the verifier actually attempts, and update the fixture's `rationale` + `mock_spec.stage` accordingly.

- [ ] **Step 3: Run the full corpus acceptance (live + mock)**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py -v
```

Expected: 141 live + 5 mock pass. Total wall time ~18 min (the live half dominates).

- [ ] **Step 4: Commit**

```
git add tests/test_phase3_corpus_acceptance.py
git commit -m "test(v0.3): Task 3 — wire VERIFICATION_INCOMPLETE corpus fixtures via harness

$(cat <<'EOF'
Phase 4 Task 3 (depends on Tasks 1+2). Splits the parametrize:
live-API fixtures stay on the existing 3 test functions (now per-test
@live_api marked instead of module-level), VERIFICATION_INCOMPLETE
fixtures run on a new function that uses MockSpecPatcher. The mock-
driven test does not require COURTLISTENER_API_TOKEN.

All 5 INCOMPLETE fixtures produce Status.VERIFICATION_INCOMPLETE with
null final_ids, exercising design §2.8's internal API-error gate.
EOF
)"
git push origin refactor/v0.3
```

---

## Task 4: Q2 — opinion-typing gate refinement (score-based, not keyword-only)

Per the Phase 3 retro S1 + Q2: `_recap_doc_is_cited_opinion` rejects substantive opinions whose descriptions don't match the narrow `_OPINION_KEYWORDS` list. Mehar Holdings is the documented exemplar — a 12-page substantive opinion granting reconsideration + remand, whose description is "ORDER GRANTING 14 Motion for Reconsideration re 13 Order" — matches no opinion keyword, falls to DOCKET_ONLY.

**Recommended fix (per retro vote):** add a score-based gate alongside the keyword gate. The existing `_opinion_likelihood` method on `CitationVerifier` already produces a composite `(tier, page_count)` score used in `_pick_best_recap_doc` for ranking candidate documents. Phase 4 reuses that score to gate VIA_RECAP: if either (a) the description matches an opinion keyword, OR (b) the score reaches a threshold (recommend: tier ≥ medium AND page_count ≥ 5), accept VIA_RECAP. The existing procedural-keyword exclusion stays — even a high-scoring doc gets rejected if its description matches `"taxation of costs"` etc.

This also addresses Phase 3 retro S4 (Doe v. Lawrence WL-only no-specific-date): a clean opinion-typed doc with a 5+-page count and an unambiguous opinion description should pass VIA_RECAP regardless of the ±14 day window. The implementer should decide between: (a) accept VIA_RECAP when score ≥ threshold even outside the date window, or (b) widen the date window to ±90 days when the citation has no specific date (parsed.month is None). Recommend (a) as more general; the date heuristic is fragile.

**Files:**
- Modify: `src/citation_verifier/verifier.py` — refactor `_recap_doc_is_cited_opinion` to accept the score as input; update `_build_fallback_result` to compute the score and pass it in. Or alternatively, give `_recap_doc_is_cited_opinion` access to the `CandidateMatch` and let it call `_opinion_likelihood` internally.
- Modify: `tests/test_verifier.py` — add `TestVerifiedViaRecapScoreGate` class with Mehar-Holdings-shaped + Doe-Lawrence-shaped mocks.
- Modify: `tests/data/refactor_corpus.json` — `named-exemplar-mehar-holdings` flips back to `VERIFIED_VIA_RECAP`; `phase4_ruling` field added. `verified-via-recap-doe-lawrence` may also flip back depending on the implementer's WL-no-date disposition.

- [ ] **Step 1: Refactor `_recap_doc_is_cited_opinion` to accept a score**

In `verifier.py`, change the signature:

```python
@staticmethod
def _recap_doc_is_cited_opinion(
    parsed: ParsedCitation,
    desc: str,
    entry_date: str,
    *,
    page_count: int = 0,
    is_free_on_pacer: bool = False,
    has_wl_cite_in_cluster: bool = False,
) -> bool:
    """Strict VIA_RECAP gate (design v2 §2.2 + Phase 4 retro Q2).

    A RECAPDocument qualifies as the cited opinion when:
      (a) has_wl_cite_in_cluster is True (WL number confirmed in CL's
          citation index for this cluster — trust unconditionally), OR
      (b) The description matches opinion-typed keywords AND the date
          is within ±14 days of cited date AND no procedural-order
          keywords match, OR
      (c) The score-based gate fires: page_count >= 5 AND
          is_free_on_pacer AND no procedural-order keywords match
          (substantive long-form opinion regardless of description
          wording; the score-based fallback handles "ORDER GRANTING ..."
          style descriptions that are substantive but keyword-poor).
    """
    desc_lower = (desc or "").lower()

    # Procedural-keyword guard runs first; never accept a doc whose
    # description matches a procedural type, regardless of score.
    _PROCEDURAL_KEYWORDS = (
        "certifying interlocutory appeal",
        "taxation of costs", "taxation order",
        "motion in limine", "in limine",
        "objections to", "objection to",
        "stipulation", "scheduling order",
        "minute order", "minute entry",
        "notice of",
        "certificate of service",
        "stipulated protective order",  # narrow: don't reject "ORDER GRANTING Motion for X"
    )
    if any(kw in desc_lower for kw in _PROCEDURAL_KEYWORDS):
        return False

    if has_wl_cite_in_cluster:
        return True

    # Path (b): opinion keyword + date window.
    _OPINION_KEYWORDS = (
        "opinion", "memorandum",
        "order & reasons", "order and reasons",
        "findings of fact", "report and recommendation",
        "report & recommendation",
        "memorandum and order", "memorandum & order",
    )
    has_opinion_keyword = any(kw in desc_lower for kw in _OPINION_KEYWORDS)

    if has_opinion_keyword and _date_within_window(parsed, entry_date, days=14):
        return True

    # Path (c) — score-based fallback for substantive-but-keyword-poor
    # docs. Catches "ORDER GRANTING Motion for X" rulings that ARE
    # substantive opinions (page count >= 5, is_free_on_pacer is the
    # PACER signal for "filed by the court itself, free to download").
    if page_count >= 5 and is_free_on_pacer:
        # Substantive long-form, court-filed -> trust as opinion
        # regardless of description wording. Still gated by the
        # procedural-keyword guard above.
        return True

    return False


def _date_within_window(parsed: ParsedCitation, entry_date: str, *, days: int) -> bool:
    """Helper: date-proximity check pulled out of the old
    _recap_doc_is_cited_opinion body."""
    if not (parsed.year and entry_date and len(entry_date) >= 10):
        return False
    try:
        from datetime import date as _date
        cited_y = parsed.year
        cited_m = parsed.month or 6
        cited_d = parsed.day or 15
        ey = int(entry_date[0:4])
        em = int(entry_date[5:7])
        ed = int(entry_date[8:10])
        delta_days = abs(
            (_date(cited_y, cited_m, cited_d) - _date(ey, em, ed)).days
        )
        return delta_days <= days
    except (ValueError, TypeError):
        return False
```

If `_date_within_window` is in module scope, the existing call site in `_recap_doc_is_cited_opinion` should be updated to use it directly. If keeping it inside the class as a static method is preferred, prefix with `CitationVerifier.`.

- [ ] **Step 2: Update `_build_fallback_result` to pass `page_count` + `is_free_on_pacer`**

The `CandidateMatch` from `_pick_best_recap_doc` doesn't currently carry `page_count` or `is_free_on_pacer` as named fields, but the underlying doc dict does. Two options:

(a) Add `page_count: int = 0` and `is_free_on_pacer: bool = False` to `CandidateMatch` (in `models.py`) and populate from `_pick_best_recap_doc`. Cleaner.

(b) Have `_pick_best_recap_doc` store the original doc dict on `CandidateMatch.raw_doc: dict | None = None` and read the two fields off it in `_build_fallback_result`. Less schema churn but introduces a free-form field.

Recommend (a). Add to `CandidateMatch`:

```python
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
    recap_document_id: int | None = None   # Phase 3 Task 4
    page_count: int = 0                    # Phase 4 Task 4 (Q2)
    is_free_on_pacer: bool = False         # Phase 4 Task 4 (Q2)
```

Populate in `_pick_best_recap_doc`:

```python
return CandidateMatch(
    case_name=case_name,
    url=doc_url or docket_url,
    cluster_id=None,
    date_filed=entry_date,
    court_id=court_id,
    score=score,
    description=full_desc or None,
    mismatches=mismatches,
    docket_id=docket_id,
    recap_document_id=doc.get("id"),
    page_count=int(doc.get("page_count") or 0),
    is_free_on_pacer=bool(doc.get("is_free_on_pacer")),
)
```

Update `_build_fallback_result` (the call site of `_recap_doc_is_cited_opinion`) to pass the new kwargs:

```python
if is_recap_match and status == Status.VERIFIED:
    desc = best.description or ""
    if best.recap_document_id and self._recap_doc_is_cited_opinion(
        parsed, desc, best.date_filed,
        page_count=best.page_count,
        is_free_on_pacer=best.is_free_on_pacer,
    ):
        status = Status.VERIFIED_VIA_RECAP
        text_source = TextSource.recap_document
        recap_document_id = best.recap_document_id
    else:
        status = Status.VERIFIED_DOCKET_ONLY
        text_source = None
        recap_document_id = None
```

- [ ] **Step 3: Write the score-gate tests**

Append to `tests/test_verifier.py`:

```python
class TestVerifiedViaRecapScoreGate:
    """Phase 4 Task 4 (Q2): score-based VIA_RECAP gate catches
    substantive-but-keyword-poor opinion descriptions like Mehar
    Holdings' 'ORDER GRANTING Motion for Reconsideration'."""

    def test_score_based_gate_accepts_substantive_long_form_doc(self):
        """Mehar Holdings shape: 12-page is_free_on_pacer doc with
        'ORDER GRANTING' description -> VIA_RECAP via score gate."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": (
                                "ORDER GRANTING 14 Motion for Reconsideration "
                                "re 13 Order on Motion to Dismiss"
                            ),
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.recap_document_id == 18720567

    def test_score_gate_does_not_override_procedural_keywords(self):
        """Cabot v. Lewis shape: 'ORDER CERTIFYING INTERLOCUTORY APPEAL'
        matches a procedural keyword and stays DOCKET_ONLY even with
        a 5-page count + is_free_on_pacer."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": (
                                "ORDER CERTIFYING INTERLOCUTORY APPEAL"
                            ),
                            "page_count": 8,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY

    def test_score_gate_requires_both_page_count_and_is_free(self):
        """A short doc (page_count < 5) or a non-free doc fails the
        score gate even with a non-procedural description."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Short Case",
                    "docket_id": 9999,
                    "id": 9999,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/9999/short/",
                    "dateFiled": "2020-06-15",
                    "docketNumber": "1:20-cv-00001",
                    "recap_documents": [
                        {
                            "id": 12345,
                            "entry_date_filed": "2020-06-15",
                            "short_description": "ORDER on motion",
                            "page_count": 2,         # too short
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Short Case v. Other, 2020 WL 999999 (W.D. Tex. June 15, 2020)")
        assert result.status == Status.VERIFIED_DOCKET_ONLY
```

- [ ] **Step 4: Run the tests and mirror to async**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestVerifiedViaRecapScoreGate -q
```

Expected: 3 PASS. Mirror the test class into `tests/test_async_verifier.py` using async client mocks. Run async parity:

```
venv/Scripts/python.exe -m pytest tests/test_async_verifier.py::TestVerifiedViaRecapScoreGate -q
```

- [ ] **Step 5: Update Mehar Holdings fixture**

Edit `tests/data/refactor_corpus.json`. Find `named-exemplar-mehar-holdings`:

```json
{
  "expected_status": "VERIFIED_VIA_RECAP",
  "expected_final_ids": {
    "docket_id": 5474769,
    "recap_document_id": 18720567,
    "text_source": "recap_document"
  },
  "phase3_classification_open": false,
  "phase4_ruling": "Restored to VERIFIED_VIA_RECAP per Q2: the score-based gate (page_count >= 5 AND is_free_on_pacer, gated by procedural-keyword exclusion) accepts substantive 'ORDER GRANTING Motion for X' rulings even when the description lacks opinion keywords."
}
```

Also: if the implementer's WL-no-specific-date disposition (per S4) was (a) accept on score-gate regardless of window, update `verified-via-recap-doe-lawrence` similarly. If (b) widen the window only for no-date WL cites, document the disposition in a parallel fixture ruling.

- [ ] **Step 6: Re-run the live-API corpus acceptance**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py -v -m live_api
```

Expected: all live tests pass. Mehar Holdings (and possibly Doe v. Lawrence) now produce VERIFIED_VIA_RECAP.

- [ ] **Step 7: Commit**

```
git add src/citation_verifier/models.py src/citation_verifier/verifier.py tests/test_verifier.py tests/test_async_verifier.py tests/data/refactor_corpus.json
git commit -m "feat(v0.3): Task 4 — score-based VIA_RECAP gate per Phase 3 retro Q2

$(cat <<'EOF'
Phase 4 Task 4. Adds page_count + is_free_on_pacer to CandidateMatch
and to the _recap_doc_is_cited_opinion signature. New score-based
gate path (c): page_count >= 5 AND is_free_on_pacer AND no procedural
keywords -> VIA_RECAP regardless of opinion-keyword presence.

Catches substantive 'ORDER GRANTING Motion for X' rulings that are
opinion-typed in substance but keyword-poor in description (Mehar
Holdings is the documented exemplar). Procedural-keyword exclusion
still gates; Cabot v. Lewis stays DOCKET_ONLY because its description
matches 'certifying interlocutory appeal'.

named-exemplar-mehar-holdings fixture flipped back to VERIFIED_VIA_
RECAP with phase4_ruling documenting the new gate path. Sync + async
unit tests cover accept/reject/score-required branches.
EOF
)"
git push origin refactor/v0.3
```

---

## Task 5: Q3 — `X v. United States` defendant-side caption_investigation gap

Per Phase 3 retro S2: `_names_match_citation_lookup` uses surname containment for common-prefix cases. The current common-prefix branch handles `United States v. X` (US as plaintiff) but not `X v. United States` (US as defendant). When CL returns a different "X" defendant or plaintiff and the brief cites a US-defendant case, the lenient surname check passes and caption_investigation never fires. Six fixtures lose their expected `cl_display_name_data_bug` warning because of this.

**Fix:** extend `_names_match_citation_lookup` to detect `X v. United States` / `v. State` / `v. Commonwealth` / `v. People` / `v. State of [State]` patterns and require defendant-side overlap in those cases (mirroring the existing plaintiff-side logic for `United States v. X`).

**Files:**
- Modify: `src/citation_verifier/verifier.py` — `_names_match_citation_lookup` common-prefix branch.
- Modify: `tests/test_verifier.py` — add `TestNamesMatchXvUnitedStates` with cases for Koch / `v. State` / `v. Commonwealth`.
- Modify: `tests/data/refactor_corpus.json` — re-add `cl_display_name_data_bug` to `expected_warnings_subset` on `named-exemplar-koch` + `verified-rule-25d-*` (3) + `verified-ssa-pseudonym-*` (2). Add `phase4_ruling`.

- [ ] **Step 1: Inspect the current `_names_match_citation_lookup`**

```
venv/Scripts/python.exe -c "
import inspect
from citation_verifier.verifier import CitationVerifier
print(inspect.getsource(CitationVerifier._names_match_citation_lookup))
"
```

The current method handles `United States v. X` via prefix detection. Identify the exact branch to extend; the existing plaintiff-side check is a model for the defendant-side mirror.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_verifier.py`:

```python
class TestNamesMatchXvUnitedStates:
    """Phase 4 Task 5 (Q3): generic-government-defendant patterns must
    require defendant-side overlap, mirroring the existing United-
    States-as-plaintiff logic."""

    @pytest.fixture
    def parser(self):
        from citation_verifier.parser import parse_citation
        return parse_citation

    def test_koch_v_us_with_different_us_defendant_fails_match(self, parser):
        """Brief: 'Koch v. United States'. CL returns: 'Ricky Koch v. Tote,
        Incorporated'. The defendant (United States) and CL's defendant
        (Tote) don't overlap; the new gate must return False so
        caption_investigation fires and emits cl_display_name_data_bug."""
        parsed = parser("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")
        v = CitationVerifier(client=None)  # client unused for this static-ish test
        result = v._names_match_citation_lookup(parsed, "Ricky Koch v. Tote, Incorporated")
        assert result is False, (
            "X v. United States with a CL-side different defendant must "
            "NOT lenient-match; caption_investigation must fire."
        )

    def test_koch_v_us_with_same_us_defendant_passes_match(self, parser):
        """Sanity: when CL also has 'X v. United States' shape with the
        same plaintiff, the lenient match still works."""
        parsed = parser("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Koch v. United States")
        assert result is True

    def test_x_v_state_pattern_requires_defendant_overlap(self, parser):
        parsed = parser("Smith v. State, 100 So. 3d 100 (Ala. 2020)")
        v = CitationVerifier(client=None)
        # CL returns a different X v. <something-else> case at this cite
        result = v._names_match_citation_lookup(parsed, "Smith v. ABC Corp")
        assert result is False

    def test_x_v_commonwealth_pattern_requires_defendant_overlap(self, parser):
        parsed = parser("Doe v. Commonwealth, 200 S.E.2d 200 (Va. 2020)")
        v = CitationVerifier(client=None)
        result = v._names_match_citation_lookup(parsed, "Doe v. XYZ Inc.")
        assert result is False
```

- [ ] **Step 3: Run the failing tests**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestNamesMatchXvUnitedStates -q
```

Expected: 3 fail (the X-v-US tests) + 1 pass (the matching-CL-shape sanity test). The failing ones return `True` under the current lenient surname check.

- [ ] **Step 4: Extend `_names_match_citation_lookup`**

Locate the existing common-prefix branch in `verifier.py:_names_match_citation_lookup`. The fix is to add a defendant-side mirror to the plaintiff-side `United States v. X` detection. Pseudocode:

```python
# Existing logic (plaintiff-side common prefix):
_PLAINTIFF_COMMON_PREFIXES = (
    "united states v",
    "state v", "commonwealth v", "people v",
    "in re ", "in the matter of",
)
# Brief: "United States v. Defendant" + CL: "United States v. Other"
# -> require defendant-side overlap.

# NEW (Phase 4 Task 5): defendant-side mirror.
_DEFENDANT_COMMON_GENERIC = (
    " v. united states", " v united states",
    " v. state", " v state",
    " v. commonwealth", " v commonwealth",
    " v. people", " v people",
)

cited_lower = (parsed.case_name or "").lower()
is_defendant_side_common = any(
    suffix in cited_lower for suffix in _DEFENDANT_COMMON_GENERIC
)

if is_defendant_side_common:
    # Brief has "X v. United States" / "X v. State" / etc. The
    # distinctive party is the plaintiff (X). Require plaintiff-side
    # overlap with the CL caption.
    plaintiff_token_or_surname = ...  # use parsed.plaintiff or surname-extract
    if plaintiff_token_or_surname:
        return plaintiff_token_or_surname.lower() in case_name.lower()
    # Fall through to the existing lenient check if we can't extract.
```

The implementer should locate the right insertion point inside the existing method body — likely after the plaintiff-side common-prefix branch returns, before the catch-all lenient surname check. The exact tokens used to detect `X` (plaintiff) versus the CL caption's tokens depends on what `_extract_surname` already returns.

A concrete refactor sketch (adapt to the actual method shape):

```python
@staticmethod
def _names_match_citation_lookup(parsed: ParsedCitation, case_name: str) -> bool:
    if not (parsed.case_name and case_name):
        return False

    cited_lower = parsed.case_name.lower()
    cl_lower = case_name.lower()

    # Existing plaintiff-side common-prefix detection (United States v. X).
    if cited_lower.startswith(("united states v", "state v",
                               "commonwealth v", "people v")):
        # Compare defendant tokens only.
        # ... (existing implementation)
        pass  # Existing code stays here.

    # NEW Phase 4 Task 5: defendant-side common-suffix detection
    # (X v. United States / State / Commonwealth / People).
    _DEFENDANT_GENERIC_SUFFIXES = (
        " v. united states", " v united states",
        " v. state", " v state",
        " v. commonwealth", " v commonwealth",
        " v. people", " v people",
    )
    if any(s in cited_lower for s in _DEFENDANT_GENERIC_SUFFIXES):
        # Compare plaintiff side only. The plaintiff is the distinctive
        # party in "X v. United States."
        cited_plaintiff = parsed.plaintiff or cited_lower.split(" v")[0]
        cited_plaintiff_norm = re.sub(r"[^a-z0-9 ]+", "", cited_plaintiff.lower()).strip()
        if not cited_plaintiff_norm:
            # Can't extract; fall through to lenient check.
            pass
        else:
            # CL caption must contain the plaintiff token. If the CL
            # caption is "Ricky Koch v. Tote, Incorporated," the
            # plaintiff "koch" IS in there (from the longer caption).
            # The case_name = "Koch v. United States" must NOT match
            # CL = "Ricky Koch v. Tote, Incorporated" because the
            # CL caption's defendant is NOT United States.
            #
            # The required additional check: cl_lower MUST also
            # contain the suffix (or the plaintiff alone is not enough).
            cl_has_suffix = any(s in cl_lower for s in _DEFENDANT_GENERIC_SUFFIXES)
            if not cl_has_suffix:
                # Brief is "X v. United States" but CL caption doesn't
                # have a generic-government defendant -> different case.
                return False
            # Both have the suffix; compare plaintiff tokens.
            tokens = [t for t in re.findall(r"[a-z0-9]+", cited_plaintiff_norm)
                      if len(t) >= 3]
            return any(t in cl_lower for t in tokens)

    # Existing catch-all lenient surname check.
    # ... (existing implementation)
```

The exact integration depends on the existing method structure; the implementer should preserve all current behavior for non-common-prefix cases.

- [ ] **Step 5: Run the tests to confirm fix**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestNamesMatchXvUnitedStates -q
```

Expected: all PASS.

- [ ] **Step 6: Run the full unit suite to confirm no regression**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

If any existing tests went red, the most likely cause is a test that relied on the old lenient match accepting a defendant-side common-prefix case. Triage each: in most cases, the new behavior is correct (the old behavior was the bug) and the test should be updated.

- [ ] **Step 7: Update the 6 fixtures' `expected_warnings_subset`**

Edit `tests/data/refactor_corpus.json`. For each of:
- `named-exemplar-koch`
- `verified-rule-25d-gilliard-mcwilliams`
- `verified-rule-25d-preston-smith`
- `verified-rule-25d-viken-detection`
- `verified-ssa-pseudonym-john-s-bisignano`
- `verified-ssa-pseudonym-michael-b-berryhill`

Re-add `cl_display_name_data_bug` to `expected_warnings_subset`. Add `phase4_ruling`:

```json
{
  "expected_warnings_subset": ["cl_display_name_data_bug"],
  "phase4_ruling": "cl_display_name_data_bug restored to expected_warnings_subset per Task 5: _names_match_citation_lookup now detects 'X v. United States' / 'v. State' / 'v. Commonwealth' / 'v. People' defendant-side patterns and rejects lenient matches when CL's caption lacks the generic suffix. caption_investigation now fires and emits the warning."
}
```

For the 5 Rule-25(d) / SSA fixtures, the Phase 3 ruling noted that they "resolve via opinion_search (not citation_lookup), because CL's citation index doesn't carry the WL cite in many of these cases" and concluded that `caption_investigation` only runs after citation_lookup. **Decision needed:** Phase 4 Task 5's fix to `_names_match_citation_lookup` is for citation_lookup-resolved cases. If these 5 fixtures still resolve via opinion_search after the fix, the warning still won't fire. The implementer should:

(a) Run each fixture against the live API after the Task 5 fix.
(b) For fixtures that now resolve via citation_lookup (because the fix changed the routing) → re-add the warning to `expected_warnings_subset`, document via `phase4_ruling`.
(c) For fixtures that STILL resolve via opinion_search → leave `expected_warnings_subset` empty and document in `phase4_ruling` that the warning still doesn't fire because opinion_search-resolved divergences need separate plumbing (out of Phase 4 scope; flag as a Phase 5 candidate or close as accepted limitation).

Koch is the cleanest test case — it resolves via citation_lookup, so the Task 5 fix will fire caption_investigation and the warning. The 5 Rule-25(d)/SSA may or may not benefit from this fix alone.

- [ ] **Step 8: Run the live corpus acceptance**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py -v -m live_api
```

Expected: live tests pass. The 6 fixtures' warnings-subset assertions now hold for whichever ones the Task 5 fix recovers; the rest get a `phase4_ruling` accepting the limitation.

- [ ] **Step 9: Commit**

```
git add src/citation_verifier/verifier.py tests/test_verifier.py tests/data/refactor_corpus.json
git commit -m "feat(v0.3): Task 5 — X v. United States caption_investigation gap per Q3

$(cat <<'EOF'
Phase 4 Task 5. _names_match_citation_lookup now detects generic-
government-defendant patterns ('X v. United States', 'v. State',
'v. Commonwealth', 'v. People') and requires CL's caption to also
have a generic-government suffix; otherwise the lenient match
rejects and caption_investigation fires.

This mirrors the existing plaintiff-side 'United States v. X'
common-prefix detection. Per Phase 3 retro S2 / Q3: 6 fixtures
(Koch + 3 Rule-25(d) + 2 SSA pseudonyms) lost their expected
cl_display_name_data_bug warning because the lenient check accepted
'Koch' as a surname-only match even when CL's defendant differed
completely.

Koch named exemplar now correctly produces VERIFIED + cl_display_name_
data_bug. Per-fixture phase4_ruling documents which other Rule-25(d)
/ SSA fixtures recovered the warning via citation_lookup routing
and which still resolve via opinion_search (where the divergence-
detection plumbing is separate; flagged for future work).
EOF
)"
git push origin refactor/v0.3
```

---

## Task 6: Q4 / Q5 — `wrong_page_number` and `cl_duplicate_clusters` fixture decisions

The Phase 3 retro asks:

- **Q4:** `wrong_page_number` is added to `WarningCategory` but no fixture exercises it. Phase 4 should either find/synthesize a fixture OR document as forward-looking infrastructure.
- **Q5:** `cl_duplicate_clusters` fires only weakly; the 4 unmarked xfails in `known_real_citations.json` resolved as single-cluster pin-updates, not duplicate-cluster cases.

**Recommended disposition.** Keep both categories as forward-looking, do not retire them. Rationale:

- The §2.6 amendment workflow says removals are a major-version bump (consumers may key on category names). Removing in v0.3.0 is fine but commits us to that being a v1.0 change — a higher-stakes decision than worth making for "no fixture today."
- Future Phase 5+ corpus expansion (the diagnostic runner per design §7) will produce real-world fixtures that may exercise these warnings. Forward-looking infrastructure is cheap to keep.
- The verifier's code paths that emit these warnings exist as designed; deleting unused-but-correct code is unwise.

**Action items in Phase 4:**

(a) Document the Q4/Q5 disposition in the survey's new §3.2 (Task 9).
(b) Optionally synthesize a single fixture for each category to keep the code path exercised.

The "optionally" makes this an implementer choice. The synthetic-fixture path keeps the verifier honest; the document-only path saves time and accepts dead code.

**Files:**
- Modify: `tests/data/refactor_corpus_survey.md` — append §3.2 (in Task 9; this task just decides).
- Optional: `tests/data/refactor_corpus.json` — add 1 synthetic fixture per category.
- Optional: `tests/test_caption_investigation.py` — add 1 unit test per category against a mock that triggers it.

- [ ] **Step 1: Make the disposition decision**

The implementer reads the Q4/Q5 analysis above and picks: **synthesize fixtures** (Steps 2 + 3) or **document-only** (skip to Task 9).

If document-only: nothing to commit in this task. The decision is captured in the Phase 4 retrospective (Task 9). Skip to Task 7.

If synthesize: proceed.

- [ ] **Step 2: Synthesize a `cl_duplicate_clusters` fixture (optional)**

Identify a citation where CL has two clusters for the same case (re-ingest with different IDs). The Phase 3 retro mentions Bossart, Busha, Townsley, Anderson-Furst as candidates but ruled them as single-cluster pin updates. Run a live search for newer duplicate cases:

```
venv/Scripts/python.exe -c "
import os
from citation_verifier.client import CourtListenerClient
c = CourtListenerClient()
# Citation lookup on a known case; inspect for >1 cluster
r = c.citation_lookup('Smith v. Jones, 100 F.3d 100 (5th Cir. 2020)')
for lr in r:
    for cl in lr.get('clusters', []):
        print(cl.get('case_name'), cl.get('id'))
"
```

Inspect a handful of cases to find one with multiple clusters returned. If none surfaces in 10 minutes of poking, abandon the synthesis and revert to document-only.

If one surfaces, add to `tests/data/refactor_corpus.json`:

```json
{
  "id": "verified-cl-duplicate-clusters-synthesized",
  "citation": "<the duplicate-cluster citation>",
  "expected_status": "VERIFIED",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {"cluster_id": null, ...},
  "expected_warnings_subset": ["cl_duplicate_clusters"],
  "rationale": "Phase 4 Task 6: synthesized fixture exercising the cl_duplicate_clusters warning. CL has multiple clusters for this case (re-ingest with different IDs); caption_investigation should emit cl_duplicate_clusters per Q3 maintainer pre-decision.",
  "source": "phase4_live_discovery#<case-name>",
  "category": "cl_duplicate_clusters_exemplar",
  "phase4_ruling": "Synthesized per Task 6 to exercise cl_duplicate_clusters warning code path."
}
```

- [ ] **Step 3: Synthesize a `wrong_page_number` fixture (optional)**

`wrong_page_number` requires the citation_lookup or sibling-cluster-search to find the case at a different reporter page. The Butler Motors example was the candidate but neither page resolved. Find a citation where:
- Page X cited
- Page Y resolves to the same case (different page of the same opinion)
- Page X does not resolve

This requires intra-volume searching: for a given volume + reporter, find all clusters; check if any has the cited case-name at a different page than cited.

Synthesizing this is hard without a script. **Recommended:** skip synthesis for `wrong_page_number` in Phase 4. Document as forward-looking infrastructure in the survey §3.2.

- [ ] **Step 4: Commit (if synthesis happened)**

If a fixture was synthesized, commit:

```
git add tests/data/refactor_corpus.json
git commit -m "test(v0.3): Task 6 — synthesize cl_duplicate_clusters fixture per Q4"
git push origin refactor/v0.3
```

If document-only, no commit yet (the survey update is Task 9).

---

## Task 7: Q6 — `candidates` field on `VerificationResult` decision (no code)

The Phase 3 retro Q6 asks whether to grow `VerificationResult` with `candidates: list[CandidateMatch] | None` to surface multiple candidates when the verifier is uncertain, or to keep expressing uncertainty through warnings only.

**Recommended disposition: defer to roadmap.** Rationale:

- The current `cl_duplicate_clusters` warning + the warning's `details` dict already carry "here are the multiple candidates" information when caption_investigation found duplicates. A consumer that wants to enumerate candidates can read `warning.details["candidate_clusters"]`.
- Adding `candidates: list[CandidateMatch] | None` to `VerificationResult` is a schema growth. Per design §2.6 amendment workflow, schema additions are a minor-version bump; the addition itself is small but the downstream commitment (cross-repo benchmark, future MCP clients) means the data shape we'd expose needs to be honest about what "candidate" means in each status context — and that's a design conversation we don't yet have grounded use cases for.
- The roadmap item (per `scratch/ROADMAP.md`) for surfacing multiple candidates when uncertain remains open. Phase 5+ work (the MCP server, the diagnostic runner) will produce concrete use cases that constrain the field's design. Adding it speculatively in Phase 4 risks getting the shape wrong.

**Action:** capture the decision in the Phase 4 retrospective (Task 9). Document in `scratch/ROADMAP.md` that the `candidates` field is a Phase 5+ design conversation, not Phase 4.

**Files:**
- Modify: `scratch/ROADMAP.md` — append a one-line entry under the relevant section.

- [ ] **Step 1: Confirm `scratch/ROADMAP.md` exists**

```
test -f scratch/ROADMAP.md && echo "exists" || echo "missing"
```

If missing, create it as a stub.

- [ ] **Step 2: Update with the candidates-field disposition**

Append (or edit, if a roadmap section already covers candidates):

```markdown
## Deferred to Phase 5+

- **`candidates: list[CandidateMatch] | None` on `VerificationResult`** — surface multiple candidates when the verifier is uncertain (e.g., when caption_investigation finds duplicate clusters or sibling-cluster matches). Decision (Phase 4 Task 7): defer to roadmap. Rationale: the `cl_duplicate_clusters` warning's `details` dict already carries candidate enumeration for the duplicate-cluster case; broader use cases for a typed candidates list emerge in Phase 5+ (MCP server, diagnostic runner). Adding speculatively now risks getting the shape wrong before grounded use cases constrain it.
```

- [ ] **Step 3: Commit**

```
git add scratch/ROADMAP.md
git commit -m "docs(v0.3): Task 7 — candidates-field decision deferred to Phase 5+ per Q6"
git push origin refactor/v0.3
```

---

## Task 8: Teach `brief_pipeline.py` + `report_template.py` the 4 new statuses

Phase 3 produces `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, and `WRONG_CASE` cleanly but the brief pipeline + HTML report classify them generically. Per the Phase 3 retro:

> The `verify-brief` skill still consumes the old shape. Phase 3 produces VERIFIED_PARTIAL / VIA_RECAP / DOCKET_ONLY / WRONG_CASE statuses cleanly, but the brief pipeline + HTML report templates don't yet have presentation logic for them. Smoke passes because the pipeline falls through to a generic "verified" or "not verified" classification. Phase 4 (or a follow-up) should update the report template to surface the new statuses meaningfully.

`_DOWNLOADABLE_STATUSES` in `brief_pipeline.py` already includes all four (Phase 1 had pre-staged this), so download eligibility is correct. The presentation gap is in:

1. The `claims.csv` `cl_status` column — already populated correctly from `result.status.value`.
2. The Phase 2c agent-authored `badge_label` field — set by Opus subagents based on the assessment, not deterministically from status. But the report template's *fallback* badge logic for legacy claims.csv data (pre-agent-authored blocks) uses a generic mapping.
3. `report_template.py`'s severity-color mapping — currently treats all VERIFIED_* the same color.

**Phase 4's scope** is narrow: extend the deterministic fallback so reports of new briefs (where agents may not have authored a `badge_label`) get distinguishable badges for the four richer statuses. The agent-authored path is unchanged.

**Files:**
- Modify: `src/citation_verifier/report_template.py` — add a `_STATUS_BADGE_FALLBACK` mapping; use it in the fallback rendering paths.
- Modify: `src/citation_verifier/brief_pipeline.py` — confirm `_DOWNLOADABLE_STATUSES` is correct and document the four-status awareness in the module docstring.
- Optional: add a `tests/test_brief_pipeline_status_aware.py` if a regression-shape test is wanted.

- [ ] **Step 1: Define the status → badge mapping in `report_template.py`**

Locate the existing badge rendering code (`_badge`, the `badge_label` reads in `_render_card` and similar). Add a module-level constant near the top:

```python
# Phase 4 Task 8: deterministic fallback for status-based badge labels
# when the agent-authored badge_label is absent (legacy claims.csv or
# pre-agent runs). The agent-authored path is unchanged; this only
# governs the fallback render.
_STATUS_BADGE_FALLBACK: dict[str, tuple[str, str]] = {
    # status.value -> (badge_text, severity_color)
    "VERIFIED": ("Verified", "green"),
    "VERIFIED_PARTIAL": ("Verified -- parallel cite only", "yellow"),
    "VERIFIED_VIA_RECAP": ("Verified via RECAP", "blue"),
    "VERIFIED_DOCKET_ONLY": ("Docket only -- no opinion text", "yellow"),
    "WRONG_CASE": ("Case mismatch -- cite resolves to a different case", "red"),
    "NOT_FOUND": ("Not found", "gray"),
    "VERIFICATION_INCOMPLETE": (
        "Verification incomplete -- infrastructure error", "orange",
    ),
}


def _badge_for_status(status_value: str) -> tuple[str, str]:
    return _STATUS_BADGE_FALLBACK.get(status_value, ("Unknown", "gray"))
```

- [ ] **Step 2: Wire the fallback into the report rendering**

In `report_template.py`, find the legacy-fallback branch where the agent-authored `badge_label` is absent (around line 184 per the grep earlier — `_badge("Unable to verify", "gray")` etc.). Replace generic "Unable to verify" fallbacks with status-driven ones:

```python
# Before:
badge_label = f.get("badge_label", "")
# ... fallback render uses _badge("Unable to verify", "gray") ...

# After:
badge_label = f.get("badge_label", "")
cl_status = f.get("cl_status", "")
if not badge_label and cl_status:
    fallback_label, fallback_severity = _badge_for_status(cl_status)
    badge_html = _badge(fallback_label, fallback_severity)
elif badge_label:
    badge_html = _badge(badge_label, sev)
else:
    badge_html = _badge("Unable to verify", "gray")
```

Apply the same pattern at all three identified fallback sites (lines ~184, ~426 per the grep).

- [ ] **Step 3: Confirm `brief_pipeline.py`'s `_DOWNLOADABLE_STATUSES` covers the four richer statuses**

The grep earlier confirmed it already does:

```python
_DOWNLOADABLE_STATUSES = {
    Status.VERIFIED,
    Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP,
    Status.VERIFIED_DOCKET_ONLY,
}
```

Update the comment to remove the Phase 1 staging note since Phase 3 now produces all four:

```python
# Phase 3 produces all four VERIFIED_* statuses; Phase 4 confirms each
# has a populated absolute_url and is download-eligible. WRONG_CASE,
# NOT_FOUND, and VERIFICATION_INCOMPLETE deliberately stay excluded —
# downloading their (missing) opinion text doesn't make sense.
_DOWNLOADABLE_STATUSES = {
    Status.VERIFIED,
    Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP,
    Status.VERIFIED_DOCKET_ONLY,
}
```

- [ ] **Step 4: Confirm `WRONG_CASE` has a `final_ids.absolute_url` to render**

Per design §2.4: `For WRONG_CASE: the IDs point to the case the reporter actually resolves to (useful context even though the citation is unusable as written). text_source is populated as for VERIFIED.` This means the report can link to the WRONG_CASE cluster's URL ("the brief cites X but the reporter actually resolves to Y → [link to Y]").

Confirm `brief_pipeline.py`'s rendering of WRONG_CASE makes use of `final_ids.absolute_url` (or the equivalent `matched_url` field on the CSV row). If it currently treats WRONG_CASE as "no URL" (because the user's intent fails), update to surface "actually resolves to: <URL>" as a distinct affordance.

This is a small but valuable presentation fix. If `brief_pipeline.py` does not currently differentiate, the change is a one-line addition to the CSV-render path:

```python
# In _write_verification_csv or report-row construction:
cl_url = result.final_ids.absolute_url or ""
# WRONG_CASE includes the URL of the case the reporter actually resolves
# to — surface it to the consumer with a distinct affordance.
```

Since `cl_url = result.final_ids.absolute_url or ""` is already the existing line, no change is needed here — the URL is captured. The presentation differentiation lives in the report template (Step 2 above) where the badge color/text already encodes "this is a wrong case, the URL points to the actual cluster."

- [ ] **Step 5: Run the brief-pipeline smoke**

Use the existing briefs/ workdir (the `briefs/fivehouse-v-dod` directory the session-start `git status` showed). The smoke confirms the pipeline runs end-to-end:

```
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/fivehouse-v-dod --report
```

Expected: regenerates the HTML report without exception. Open the report in a browser and visually confirm the new badges render distinctly for any VIA_RECAP / DOCKET_ONLY / WRONG_CASE / VERIFIED_PARTIAL citations in the brief. If the brief has none of these statuses, the new badges aren't exercised — find a brief workdir that does (any of the `briefs/` workdirs the user has retained).

- [ ] **Step 6: Run the brief_pipeline unit tests for regression**

```
venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py -q
```

Expected: same pass count as §0.2 baseline. The new fallback logic is additive (only fires when `badge_label` is missing); existing tests that set `badge_label` in their fixtures are unaffected.

- [ ] **Step 7: Commit**

```
git add src/citation_verifier/brief_pipeline.py src/citation_verifier/report_template.py
git commit -m "feat(v0.3): Task 8 — brief pipeline + report aware of 4 new statuses

$(cat <<'EOF'
Phase 4 Task 8. report_template.py now has a deterministic fallback
mapping from status value to badge label + severity color, used when
the agent-authored badge_label is absent (legacy claims.csv data or
pre-agent runs). The agent-authored path is unchanged.

Badge mapping:
- VERIFIED_PARTIAL: yellow 'Verified -- parallel cite only'
- VERIFIED_VIA_RECAP: blue 'Verified via RECAP'
- VERIFIED_DOCKET_ONLY: yellow 'Docket only -- no opinion text'
- WRONG_CASE: red 'Case mismatch -- cite resolves to a different case'
- VERIFICATION_INCOMPLETE: orange 'Verification incomplete -- infrastructure error'
- NOT_FOUND: gray 'Not found'

brief_pipeline.py's _DOWNLOADABLE_STATUSES comment refreshed (Phase 3
now produces all four VERIFIED_* statuses; Phase 1 staging note removed).
WRONG_CASE's final_ids.absolute_url is preserved through the CSV ->
report path so the consumer sees 'actually resolves to: <URL>' as
distinct affordance.

verify-brief CLI smoke regenerates reports cleanly. Existing
brief_pipeline unit tests unchanged (the fallback is additive).
EOF
)"
git push origin refactor/v0.3
```

---

## Task 9: Phase 4 acceptance gate + retrospective

Standing pre-acceptance checklist, mirroring Phase 1 / 2 / 2.5 / 3.

- [ ] **Step 1: Run the full non-live unit suite**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected: zero failures. Pass count = §0.2 baseline + (Task 1 +12) + (Task 2 +6) + (Task 4 +3 sync +3 async) + (Task 5 +4) + optional Task 6 +0 or +1 fixture. Implementer counts.

- [ ] **Step 2: Run all live + mock corpus tests**

```
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py tests/test_phase3_corpus_acceptance.py -v
```

Expected: 141 live corpus + 5 mock VERIFICATION_INCOMPLETE + 7 false_negatives all PASS. Per-fixture named exemplars (Koch, Gilliam, Menges, WRONG_CASE Hogan, INCOMPLETE Obergefell) explicitly pass.

- [ ] **Step 3: Run the verify-brief end-to-end smoke**

```
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/<workdir> --full
```

Expected: completes without exception. Visually confirm at least one citation in the brief renders the new status-based badge styling (if no brief workdir exercises VIA_RECAP / WRONG_CASE / DOCKET_ONLY / PARTIAL, the smoke still passes — Task 8's presentation update is exercised by manual report inspection).

- [ ] **Step 4: Write the Phase 4 retrospective**

Create `docs/retrospectives/<today>-refactor-v0.3-phase-4.md` (use the actual completion date — likely 2026-05-23 through 2026-05-25 depending on time-to-acceptance):

```markdown
# Phase 4 Retrospective — citation-verifier v0.3 final refactor phase

**Branch:** `refactor/v0.3` -> merged to `main` as v0.3.0
**Plan:** `docs/plans/2026-05-23-citation-verifier-refactor-phase-4-plan.md`
**Acceptance tag:** `refactor/phase-4-acceptance` (and `v0.3.0`)

## What landed

[List the commits from §0 through Task 10.]

## Time breakdown

[Per-task token/dispatch costs.]

## Surprises

[Where the plan didn't survive contact with code or data.]

## Open questions to consider for future work (post-refactor)

- The Q4 / Q5 forward-looking warning categories (wrong_page_number, cl_duplicate_clusters) — did synthesis happen, or did Phase 4 document-only them? If document-only, when does the diagnostic runner / Phase 7 work surface fixtures that exercise them?
- The Q6 `candidates` field — what concrete use cases surfaced during Phase 4 that would change the disposition?
- Any opinion-typing edge cases the score-based gate (Task 4) missed?
- Any X-v-State / X-v-Commonwealth fixtures that didn't recover the warning despite the Task 5 fix?
- Whether the brief pipeline + HTML report status-aware fallback (Task 8) is sufficient or whether the agent-authored badge path needs status-awareness too.

## Notes for the v0.3 → main merge (Task 10)

[Anything specific that came up during Phase 4 that affects the merge or post-merge CLAUDE.md cleanup.]
```

Add §3.2 to `tests/data/refactor_corpus_survey.md` summarizing the Q4/Q5 dispositions:

```markdown
## §3.2 Phase 4 rulings on retrospective open questions

### Q2 — opinion-typing gate (Task 4)

`named-exemplar-mehar-holdings` restored to VERIFIED_VIA_RECAP via the new
score-based gate (page_count >= 5 AND is_free_on_pacer AND no procedural
keywords). The procedural-keyword guard still rejects Cabot v. Lewis and
similar genuinely-procedural docs. Doe v. Lawrence [retained/restored — implementer fills in].

### Q3 — X v. United States caption_investigation (Task 5)

`_names_match_citation_lookup` now detects generic-government-defendant patterns
and requires CL's caption to also have a generic suffix; otherwise the lenient
match rejects and caption_investigation fires. Koch named exemplar recovers
its cl_display_name_data_bug warning. The 5 Rule-25(d)/SSA fixtures: [N of 5]
recovered; the rest still resolve via opinion_search where divergence-detection
plumbing is separate (out of v0.3 scope; flagged for Phase 5+).

### Q4 — wrong_page_number

Kept as forward-looking infrastructure. No fixture synthesized in Phase 4
[OR: synthesized fixture `wrong-page-number-synthesized` per Task 6].
Rationale: removal is a major-version bump per §2.6 amendment workflow;
keeping the category supports future Phase 5+ corpus expansion via the
diagnostic runner.

### Q5 — cl_duplicate_clusters

Kept as forward-looking infrastructure for the same reason. [Synthesized
fixture: yes/no per Task 6.]

### Q1 — VERIFICATION_INCOMPLETE production wiring (Task 2)

design §2.8 internal gate now lives in `_finalize_result`. The 5 corpus
INCOMPLETE fixtures pass via the new MockSpecPatcher harness (Task 1 + 3).
caption_investigation's defensive fallback preserved (refinement-stage
failures do not promote to INCOMPLETE; design §1.5).

### Q6 — candidates field on VerificationResult

Deferred to Phase 5+ per Task 7. The cl_duplicate_clusters warning's
details dict already carries candidate enumeration; broader use cases
will emerge with the MCP server and diagnostic runner.
```

Update `CHANGELOG.md` with the v0.3.0 release entry:

```markdown
## v0.3.0 — 2026-05-2X

### Schema (unchanged from Phase 3)

[Reference the existing CHANGELOG entry from Phase 3 Task 2.]

### Phase 4 behavior

- **VERIFICATION_INCOMPLETE production wiring** (design §2.8 internal gate):
  `_finalize_result` now promotes `NOT_FOUND` to `VERIFICATION_INCOMPLETE`
  when any stage in `resolution_path` has `verdict=errored` and no stage
  has `resolved`/`partial`. Resolved-stage-trumps-errored asymmetry honors
  the rule "fail-closed only at the boundary of verifier integrity"
  (design §1.5). On promotion, all `final_ids` are nulled so consumers
  cannot mistake an INCOMPLETE result for a partial verification.
- **Opinion-typing gate refinement** (Phase 3 retro Q2): VIA_RECAP now
  accepts substantive-but-keyword-poor opinion descriptions
  ("ORDER GRANTING Motion for X") via a score-based gate
  (`page_count >= 5 AND is_free_on_pacer AND no procedural keywords`).
  Mehar Holdings restored to VIA_RECAP.
- **X v. United States caption_investigation gap** (Phase 3 retro Q3):
  `_names_match_citation_lookup` now detects generic-government-defendant
  patterns. Koch named exemplar recovers its `cl_display_name_data_bug`
  warning.
- **Brief pipeline + HTML report 4-status awareness** (Phase 3 retro
  carry-forward): deterministic status-to-badge fallback in
  `report_template.py` so VIA_RECAP, DOCKET_ONLY, WRONG_CASE,
  VERIFIED_PARTIAL get distinguishable presentation when the
  agent-authored `badge_label` is absent.

### Cross-repo consumers

The benchmark project (`~/Projects/case-law-proposition-benchmark`) is
unblocked to upgrade from `v0.2.0` to `v0.3.0`. Per design §5
"tag-pin staging," the benchmark's own migration is on a separate
branch; this CHANGELOG entry is the migration reference.
```

- [ ] **Step 5: Tag the Phase 4 acceptance**

```
git tag -a refactor/phase-4-acceptance -m "Phase 4 acceptance — final phase of v0.3 refactor

Tasks 1+2 (HEADLINE): MockSpecPatcher harness + VERIFICATION_INCOMPLETE
production wiring. Tasks 3-8: corpus INCOMPLETE wiring, opinion-typing
gate refinement, X v. United States fix, candidates-field deferral,
brief pipeline + report 4-status awareness.

All Phase 3 retro Q1-Q6 dispositioned. All 5 corpus INCOMPLETE fixtures
pass via the mock harness. The 141 live corpus + 7 false_negatives
suites still green. brief-pipeline smoke completes cleanly.

Next: merge to main with merge commit, tag v0.3.0, delete CLAUDE.md
refactor section."
git push origin refactor/v0.3 refactor/phase-4-acceptance
```

- [ ] **Step 6: Commit the retro + survey + changelog**

```
git add docs/retrospectives/<today>-refactor-v0.3-phase-4.md tests/data/refactor_corpus_survey.md CHANGELOG.md
git commit -m "docs(v0.3): Phase 4 retrospective + survey §3.2 + v0.3.0 changelog"
git push origin refactor/v0.3
```

---

## Task 10: Final merge to main, tag v0.3.0, delete CLAUDE.md refactor scaffolding (controller-direct)

This is the final step. The user's brief is explicit: **merge with a merge commit (no squash — preserve per-phase history), tag v0.3.0, delete the "Refactor Workflow" section from CLAUDE.md, update the VerificationResult-fields pitfall.**

This task is controller-direct (no subagent). The merge to main is a high-stakes, irreversible operation; the controller drives it under the user's awareness and confirms each step.

**Files:**
- Modify: `CLAUDE.md` — delete lines 15–25 (the "Refactor Workflow" section); collapse the two VerificationResult-fields pitfall bullets (lines 234–235) into one canonical v0.3 description.

- [ ] **Step 1: Final pre-merge confirmation**

Confirm Phase 4 acceptance is tagged and pushed:

```
git rev-parse refactor/phase-4-acceptance
git tag --list "refactor/phase-*"
git status --short
```

Expected: tag exists, working tree clean (modulo the same `briefs/fivehouse-v-dod/verification_results.csv` modification that's been present since session start).

- [ ] **Step 2: Confirm with user before merging to main**

This is the irreversible step. Surface to the user (paraphrasing):

> Phase 4 is at acceptance. Ready to merge `refactor/v0.3` into `main` with a merge commit (per CLAUDE.md "Refactor Workflow") and tag `v0.3.0`. This will:
> - Land all per-phase commits on `main` (no squash — full history preserved)
> - Tag the merge commit as `v0.3.0`
> - Push the tag to origin
> - Then I'll delete the `Refactor Workflow` section from `CLAUDE.md` and update the `VerificationResult fields` pitfall in a follow-up commit (also pushed to main)
>
> Proceed?

Wait for user confirmation. **Do not run Step 3 without it.**

- [ ] **Step 3: Merge to main**

```
git checkout main
git pull origin main      # absorb any drift since the §0.1 merge
git merge --no-ff refactor/v0.3 -m "Merge refactor/v0.3: v0.3 schema rewrite (Phases 1-4)

Final integration of the v0.3 refactor. Per-phase commits preserved
via --no-ff. See docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md
for the design and docs/retrospectives/2026-05-*-refactor-v0.3-phase-*.md
for each phase's retrospective.

Major changes:
- Status taxonomy: 4 -> 7 (VERIFIED, VERIFIED_PARTIAL, VERIFIED_VIA_RECAP,
  VERIFIED_DOCKET_ONLY, WRONG_CASE, NOT_FOUND, VERIFICATION_INCOMPLETE)
- New VerificationResult schema (final_ids, resolution_path, warnings)
- caption_investigation stage for case-name mismatch classification
- Strict VIA_RECAP gate with score-based fallback
- VERIFICATION_INCOMPLETE wiring via design §2.8 internal API-error gate"
```

If the merge produces conflicts (it shouldn't if §0.1 absorbed drift, but check), resolve favoring `refactor/v0.3` content for anything in `src/citation_verifier/`, `tests/`, `docs/plans/`, `docs/retrospectives/`, `CHANGELOG.md`.

- [ ] **Step 4: Tag v0.3.0 and push**

```
git tag -a v0.3.0 -m "v0.3.0: schema rewrite (Phases 1-4 of the v0.3 refactor)

See CHANGELOG.md for the full release notes."
git push origin main
git push origin v0.3.0
```

- [ ] **Step 5: Delete the CLAUDE.md "Refactor Workflow" section**

Edit `CLAUDE.md`. Delete lines 15–25 inclusive (the heading `## Refactor Workflow (Phases 1–4, ongoing)` through the bullet ending `**delete this section from CLAUDE.md**`). The "## Architecture" section that follows starts on line 27 (was line 27 pre-deletion); after deletion it moves up.

Use the Edit tool with the exact old_string spanning the section:

```python
# Use Edit tool with:
# old_string = full text of lines 15-26 (including the trailing blank line)
# new_string = "" (empty — section is gone)
```

- [ ] **Step 6: Collapse the VerificationResult-fields pitfall bullets**

CLAUDE.md currently has two bullets at lines 234 (pre-refactor v0.2 description) and 235 (refactor/v0.3 Phase 1–3 description). After the merge, only the v0.3 description is canonical for main.

Edit `CLAUDE.md`. Delete the line-234 bullet entirely. Edit the line-235 bullet to remove the `(Phase 1-3)` qualifier and the "on refactor/v0.3" prefix — it IS the main-branch description now:

Old line 234 (delete entirely):

```
- **VerificationResult fields** (pre-refactor v0.2 schema — refactor/v0.3 branch reshaped this; the description below applies on `main`): URL attribute is `matched_url` (not `court_listener_url`). [... full bullet ...]
```

Old line 235 (edit):

```
- **VerificationResult fields on refactor/v0.3** (Phase 1–3): top-level `matched_*` and `diagnostics` are gone; everything moved under `result.final_ids` (cluster_id, opinion_id, docket_id, **recap_document_id** (Phase 3), absolute_url, text_source) and `result.warnings` (typed `Warning` with `.category` enum). [... rest ...]
```

New canonical bullet (replaces both):

```
- **VerificationResult fields**: top-level `matched_*` and `diagnostics` are gone; everything moved under `result.final_ids` (cluster_id, opinion_id, docket_id, recap_document_id, absolute_url, text_source) and `result.warnings` (typed `Warning` with `.category` enum). Use `result.final_ids.docket_id is not None and result.final_ids.cluster_id is None` as the RECAP-vs-opinion discriminator. `VERIFIED_VIA_RECAP` populates `recap_document_id`; `VERIFIED_DOCKET_ONLY` leaves it `None`. `VERIFICATION_INCOMPLETE` nulls all final_ids per design §2.8. See `src/citation_verifier/models.py` and `docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md` for the full schema.
```

- [ ] **Step 7: Commit the CLAUDE.md cleanup and push**

```
git add CLAUDE.md
git commit -m "docs: post-v0.3.0 CLAUDE.md cleanup — drop refactor scaffolding

Per the v0.3 refactor 'Refactor Workflow' final-acceptance step:
- Delete the 'Refactor Workflow (Phases 1-4, ongoing)' section
  (no longer applicable — v0.3 is now main).
- Collapse the two VerificationResult-fields pitfall bullets into
  one canonical v0.3 description (drop the pre-refactor v0.2 bullet
  and the 'on refactor/v0.3 (Phase 1-3)' qualifier on the v0.3 bullet).

The 'Refactor Workflow' deletion was the explicit final step of the
v0.3 refactor plan (per CLAUDE.md line 25 before deletion)."
git push origin main
```

- [ ] **Step 8: Final post-merge verification**

```
git log --oneline --max-count=20 main
git tag --list "v0.3*"
git show v0.3.0 --stat | head -50
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected:
- The merge commit and CLAUDE.md cleanup commit visible on `main`'s recent history.
- `v0.3.0` tag present.
- Test suite passes on `main` post-merge (same count as Phase 4 acceptance).

- [ ] **Step 9: Notify the user**

Surface to the user (paraphrasing):

> v0.3.0 is on main. The refactor branch `refactor/v0.3` has served its purpose; it can be deleted at the user's convenience (`git branch -d refactor/v0.3` + `git push origin --delete refactor/v0.3`) or kept as a historical reference. The Phase 4 retrospective is at `docs/retrospectives/<date>-refactor-v0.3-phase-4.md`. The CHANGELOG.md v0.3.0 entry is the migration reference for cross-repo consumers (notably the benchmark project, which can now bump from `v0.2.0` to `v0.3.0`).

---

## Acceptance Criteria (summary)

- The 5 `VERIFICATION_INCOMPLETE` corpus fixtures all produce `Status.VERIFICATION_INCOMPLETE` via the `MockSpecPatcher` (Task 1 + 2 + 3).
- The 141 live corpus + 7 false_negatives suites are still green; new tasks add net-positive test count without regressions (Task 9 Step 2).
- `Status.VERIFICATION_INCOMPLETE` produces null `final_ids` on every code path; consumers cannot mistake an INCOMPLETE result for a partial verification (Task 2 Step 4).
- The full non-live unit suite (`pytest --deselect live_api -q`) is zero-failures (Task 9 Step 1).
- `verify-brief` smoke completes without exception (Task 9 Step 3).
- The opinion-typing score gate (Task 4) accepts Mehar-Holdings-shape substantive-but-keyword-poor opinions; the procedural-keyword guard still rejects Cabot-shape orders.
- The `X v. United States` fix (Task 5) recovers `cl_display_name_data_bug` on Koch named exemplar; any 5 Rule-25(d)/SSA fixtures that still resolve via opinion_search have `phase4_ruling` documenting why the warning still doesn't fire.
- `tests/data/refactor_corpus_survey.md` §3.2 captures all Phase 4 rulings (Task 9 Step 4).
- `CHANGELOG.md` v0.3.0 entry is the cross-repo consumer migration reference (Task 9 Step 4).
- `refactor/phase-4-acceptance` tag exists and is pushed (Task 9 Step 5).
- `refactor/v0.3` is merged to `main` with a merge commit (no squash) (Task 10 Step 3).
- `v0.3.0` tag is on the merge commit and pushed (Task 10 Step 4).
- The "Refactor Workflow (Phases 1–4, ongoing)" section is deleted from `CLAUDE.md` on `main` (Task 10 Step 5).
- The VerificationResult-fields pitfall is collapsed to a single canonical v0.3 description on `main` (Task 10 Step 6).
- The user is notified that v0.3.0 is on main (Task 10 Step 9).

---

## Out of scope (do not implement in Phase 4)

- **Caller-policy gates** (`gates: list[GateSpec] | None` parameter on verify entry points; `no_not_found` / `no_wrong_case` / etc. gate evaluation). The user's brief named only Q1 (INCOMPLETE wiring) and roll-up tasks as Phase 4 scope. The `GateSpec` / `GateFailure` / `GateName` types exist in `models.py` from Phase 1 but their evaluation logic is deferred to a future phase.
- **`candidates: list[CandidateMatch] | None` on `VerificationResult`.** Task 7's disposition is to defer.
- **MCP server, skill rewrite, diagnostic runner, verify-proposition split.** All design §7 roadmap items.
- **Web app presentation polish.** Task 8 covers brief_pipeline + report_template; the FastAPI web app stays as Phase 3 left it.
- **opinion_search-resolved divergences emitting `cl_display_name_data_bug`.** Task 5 only fixes citation_lookup-resolved divergences. The opinion_search divergence-detection plumbing is a separate work item; flag as Phase 5+ candidate.
- **WL-index integration to disambiguate same-docket WL citations.** The Phase 3 §0.3 finding (Darensburg) documents the limit; `docs/notes/wl-disambiguation-limit.md` (created in §0.3) names it. External WL-index data source is required; CL does not currently expose it.

---

## Self-review notes

The writing-plans skill's self-review checklist:

1. **Spec coverage:**
   - Phase 3 retro Q1 (VERIFICATION_INCOMPLETE production wiring + mock harness) → Tasks 1 + 2 + 3 (HEADLINE).
   - Phase 3 retro Q2 (Mehar Holdings opinion-typing gap) → Task 4.
   - Phase 3 retro Q3 (X v. United States caption_investigation gap) → Task 5.
   - Phase 3 retro Q4 (`wrong_page_number` fixture decision) → Task 6.
   - Phase 3 retro Q5 (`cl_duplicate_clusters` exercise decision) → Task 6.
   - Phase 3 retro Q6 (`candidates` field decision) → Task 7.
   - Caption_investigation defensive fallback upgrade question (Q1 sub-question) → Task 2 Step 6 (disposition: keep, update message text).
   - Brief pipeline + HTML report 4-status awareness → Task 8.
   - Final merge to main with merge commit + tag v0.3.0 + CLAUDE.md cleanup + VerificationResult-fields pitfall update → Task 10.
   - WL-disambiguation-limit note creation (Phase 3 retro TODO) → §0.3.
   - Phase 4 retrospective + survey §3.2 + CHANGELOG v0.3.0 entry → Task 9.

2. **Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", "similar to Task N (without code)" in any step. The "implementer's call" notes in Task 4 Step 2 (CandidateMatch field-vs-raw-dict choice), Task 5 Step 4 (exact integration point in `_names_match_citation_lookup`), Task 6 (synthesize-vs-document-only choice), and Task 8 Step 4 (WRONG_CASE URL surfacing) are explicit delegations with direction and rationale, not punts. The mock_spec harness `attempt_idx` interpretation (Task 1) is explicitly resolved (the harness simulates "all retries failed" regardless of `attempt_idx`).

3. **Type consistency:**
   - `MockSpecPatcher` (sync) and `AsyncMockSpecPatcher` (async) have identical method shapes modulo async; both consume the same `{stage, failure_mode, attempt_idx, details}` dict shape.
   - `_promote_to_incomplete_if_only_errored` (Task 2) is a static method on `CitationVerifier`; called from `_finalize_result` which is the single chokepoint for `VerificationResult` construction.
   - `CandidateMatch.page_count` + `is_free_on_pacer` (Task 4 Step 2) added with safe defaults so existing producers don't break.
   - `_recap_doc_is_cited_opinion` (Task 4) gains two kwargs with safe defaults so existing callers in tests don't break.
   - `_names_match_citation_lookup` (Task 5) extension is additive — new defendant-side branch added before the existing catch-all lenient check.

4. **No spec drift from the user's brief:**
   - The plan does not propose caller-policy gates (per Phase 4 out-of-scope).
   - The plan does not add `candidates` to `VerificationResult` (per Task 7 disposition).
   - The plan does not surface-area-expand outside Q1-Q6 + roll-up.
   - The final-acceptance steps (merge, tag, CLAUDE.md cleanup, pitfall update) match the user's brief verbatim.

---

## Headline vs mechanical task classification

Per the user's brief: "Default per-task budget: subagent-driven-development with Sonnet implementer + Opus reviewer on headline tasks (mock harness + VERIFICATION_INCOMPLETE wiring), Sonnet alone on smaller cleanups."

**HEADLINE tasks (Sonnet implementer + Opus reviewer):**
- **Task 1: MockSpecPatcher harness.** The harness is reusable beyond Phase 4 and its design choices (wrapping `_request_with_retry` rather than the lower-level session call; stubbing non-target stages rather than passthrough) have downstream implications. Reviewer focus: URL classification correctness, exception-type fidelity, stub-response shape, async parity, no live-API leak.
- **Task 2: VERIFICATION_INCOMPLETE production wiring.** The design §2.8 internal gate is the verifier's load-bearing semantic boundary. The "errored-trumps-resolved-or-not" decision rule and the caption_investigation defensive-fallback disposition warrant Opus review. Reviewer focus: decision-rule scope, ID-nulling on promotion, caption_investigation disposition, `_finalize_result` placement coverage.

**Mechanical tasks (Sonnet alone or controller-direct):**
- **Task 3: Wire INCOMPLETE corpus fixtures.** Sonnet alone — consumes Tasks 1 + 2 with mechanical parametrize splitting.
- **Task 4: Score-based VIA_RECAP gate.** Sonnet alone — the design recommendation is in the retro and the code path is well-understood.
- **Task 5: X v. United States fix.** Sonnet alone — the fix is a four-line common-prefix branch extension.
- **Task 6: Q4/Q5 fixture decisions.** Sonnet alone or controller-direct — synthesis is best-effort and the document-only path is mechanical.
- **Task 7: Q6 candidates-field deferral.** Controller-direct — writing-only, no code.
- **Task 8: brief_pipeline + report_template 4-status awareness.** Sonnet alone — additive fallback mapping.
- **Task 9: Phase 4 acceptance gate + retrospective.** Controller-direct — coordination, test-running, writing.
- **Task 10: Final merge to main + tag v0.3.0 + CLAUDE.md cleanup.** Controller-direct under user awareness — high-stakes irreversible operations need the controller's caution and confirmation pause (Step 2).
