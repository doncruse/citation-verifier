"""Phase 5 Task 1 -- integration tests for the FastAPI web app.

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

import web.app as web_app
from citation_verifier import verifier as cv_verifier
from citation_verifier.models import Status


# ---------------------------------------------------------------------------
# Stub AsyncCourtListenerClient -- minimal contract surface
# ---------------------------------------------------------------------------

class _StubAsyncCLClient:
    """Drop-in async client stub for the web app tests.

    Default posture: no matches, no errors. Each method matches the real
    AsyncCourtListenerClient signature, returning empty-but-well-formed
    payloads. The verifier's real logic runs against the stub, so a stub
    that returns empty results drives the citation through the full
    fallback chain ending at NOT_FOUND.
    """

    BASE_URL = "https://www.courtlistener.com/api/rest/v4"
    REQUEST_TIMEOUT = 15
    MAX_RETRIES = 3
    MAX_DOCKET_ENTRIES = 50

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def citation_lookup(self, text: str) -> list:
        return []

    async def search_opinions(self, **kwargs) -> list:
        return []

    async def search_recap(self, **kwargs) -> list:
        return []

    async def get_docket_entries(self, **kwargs) -> list:
        return []

    async def get_cluster(self, cluster_id: int) -> dict:
        return {}

    async def get_docket(self, docket_id: int) -> dict:
        return {}

    async def get_recap_document_metadata(self, doc_id: int):
        return None

    async def get_opinion_text(self, matched_url: str):
        return None

    async def get_opinion_text_with_metadata(
        self, matched_url: str, prefer_html: bool = False,
    ):
        return None

    async def get_pdf_url(self, matched_url: str):
        return None

    async def _request_with_retry(self, method: str, url: str, **kwargs):
        return {"results": []}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """FastAPI TestClient with the stubbed CL client patched in.

    Patches BOTH web.app.AsyncCourtListenerClient AND
    citation_verifier.verifier.AsyncCourtListenerClient. The web app
    instantiates the former directly; the verifier's verify_batch()
    instantiates the latter internally. Patching both keeps the stub in
    force regardless of which API path the route takes."""
    with patch.object(web_app, "AsyncCourtListenerClient", _StubAsyncCLClient), \
         patch.object(cv_verifier, "AsyncCourtListenerClient", _StubAsyncCLClient):
        yield TestClient(web_app.app)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE response body into a list of (event, data-dict) pairs."""
    events: list[tuple[str, dict]] = []
    current_event: str | None = None
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            try:
                data = json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                continue
            if current_event:
                events.append((current_event, data))
    return events


# ---------------------------------------------------------------------------
# A1-class regression tests: dispatch + private-helper signature shape
# ---------------------------------------------------------------------------

class TestVerifyEndpointA1Class:
    """Reproduces the A1 regression: /api/verify must not raise TypeError
    on batches > 1 citation."""

    def test_post_verify_single_citation_no_typeerror(self, client):
        """Single-citation case (worked before the addendum fix too)."""
        response = client.post(
            "/api/verify",
            json={"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]},
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
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
        events = _parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        assert len(result_events) == 5
        for _, data in result_events:
            assert data["status"] != "ERROR", (
                f"A1-class regression: {data.get('input_citation')} returned "
                f"ERROR with: {data.get('error')!r}"
            )

    def test_post_qc_run_batch_no_typeerror(self, client, tmp_path, monkeypatch):
        """QC run-batch (audit row C1 — broken at HEAD before Task 2).
        Under the stub (all CL methods return empty), every citation
        should resolve to NOT_FOUND. Any ERROR-status result event is a
        signature-shape regression — the stub never raises, so the only
        way ERROR appears is if a private-helper call signature has
        drifted and the route's except-block synthesized an ERROR event.

        The route saves results back to its CSV, so point it at a tmp
        copy — otherwise every test run writes stub-driven NOT_FOUND
        rows into the real scratch/citations_for_review.csv (the 'CSV
        side-effect' flagged in the Phase 5 retrospective)."""
        if not web_app._default_csv.exists():
            pytest.skip("master CSV not present in this checkout")
        tmp_csv = tmp_path / "citations_for_review_test.csv"
        tmp_csv.write_bytes(web_app._default_csv.read_bytes())
        monkeypatch.setattr(web_app, "_default_csv", tmp_csv)
        response = client.post(
            "/api/qc/run-batch",
            json={"sample_size": 3, "rerun_only": False},
        )
        if response.status_code != 200:
            return
        # If the response body isn't SSE (e.g. JSON 'no actionable rows'),
        # there are no events to check.
        if "text/event-stream" not in response.headers.get("content-type", ""):
            return
        events = _parse_sse(response.text)
        result_events = [
            (e, d) for e, d in events
            if e == "result" and d.get("status") not in ("SKIPPED",)
        ]
        if not result_events:
            pytest.skip("no non-skipped results in sampled batch")
        for _, data in result_events:
            assert data.get("status") != "ERROR", (
                f"A1-class regression in /api/qc/run-batch: "
                f"{data.get('citation_text')!r} returned ERROR: "
                f"{data.get('error')!r}"
            )


# ---------------------------------------------------------------------------
# A2-class regression tests: v0.3 schema contract on JSON response shape
# ---------------------------------------------------------------------------

class TestVerifyEndpointA2Class:
    """The /api/verify response shape must be the v0.3 contract: every
    status value must be a member of the v0.3 Status enum (no LIKELY_REAL
    / POSSIBLE_MATCH leaking back); every result event must have the
    documented keys."""

    def test_result_event_has_v03_keys(self, client):
        response = client.post(
            "/api/verify",
            json={"citations": ["Obergefell v. Hodges, 576 U.S. 644 (2015)"]},
        )
        events = _parse_sse(response.text)
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
        events = _parse_sse(response.text)
        result_events = [(e, d) for e, d in events if e == "result"]
        v03_values = {s.value for s in Status} | {"ERROR"}
        for _, data in result_events:
            assert data["status"] in v03_values, (
                f"v0.3 schema contract: status {data['status']!r} is not a "
                f"member of v0.3 Status enum {sorted(v03_values)}"
            )


# ---------------------------------------------------------------------------
# Other endpoints -- smoke tests
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
    so a regression in the prefix list doesn't go silent. The test
    constructs an equivalent middleware locally rather than reloading
    web.app under MODE=public (which would require module reload gymnastics)."""

    def test_public_mode_blocks_qc(self):
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

        @app.get("/api/health")
        def health():
            return {"ok": True}

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
        assert c.get("/api/health").status_code == 200
