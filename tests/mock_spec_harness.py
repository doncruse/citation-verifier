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

import requests

# Stage-name -> URL-substring regex. Used to classify each
# _request_with_retry call into the StageName the verifier would
# attribute it to. The order in which patterns are tried matters
# only for citation_lookup (which is the most specific endpoint);
# the search endpoints are mutually exclusive by query-string.
#
# IMPORTANT: recap_document_search (type=rd) must appear BEFORE
# recap_docket_search (type=r) because type=r is a substring of
# type=rd. The regex boundary `(?:&|$)` prevents false matches but
# we keep the ordering defensive anyway.
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
_CLEAN_NO_MATCH: dict[str, Any] = {
    "citation_lookup": [],             # Citation lookup returns a top-level list.
    "opinion_search": {"results": []},
    "recap_document_search": {"results": []},
    "recap_docket_search": {"results": []},
    "plain_docket_search": {"results": []},
    "caption_investigation": {},       # Cluster/docket/opinion-text endpoints; empty dict is acceptable.
    "_default": {"results": []},
}


def _classify_url(url: str, params: dict[str, str] | None = None) -> str:
    """Map a CL REST URL to its stage name string.

    The client passes query parameters as a separate ``params`` kwarg to
    _request_with_retry — they are NOT embedded in the URL string.
    To classify search endpoint calls (opinion_search, recap_*_search,
    plain_docket_search) we must inspect the ``params`` dict when the
    bare /search/ URL is given.

    Priority order:
    1. /citation-lookup/ URL -> citation_lookup (exact path match).
    2. /search/ URL + params["type"] -> map type letter to stage name.
    3. Full URL match against _STAGE_URL_PATTERNS (handles hand-crafted
       URLs with embedded query strings, e.g. in unit tests).
    4. "_default" for unrecognized URLs.
    """
    # Fast-path: citation-lookup is a distinct endpoint.
    if "/citation-lookup/" in url:
        return "citation_lookup"

    # Search endpoint: classify by the "type" query param.
    if "/search/" in url:
        type_val = None
        if params and "type" in params:
            type_val = params["type"]
        elif "?" in url:
            # Params embedded in URL (unit-test hand-crafted URLs).
            m = re.search(r"[?&]type=([^&]+)", url)
            if m:
                type_val = m.group(1)
        _TYPE_TO_STAGE = {
            "o": "opinion_search",
            "r": "recap_docket_search",
            "rd": "recap_document_search",
            "d": "plain_docket_search",
        }
        if type_val in _TYPE_TO_STAGE:
            return _TYPE_TO_STAGE[type_val]

    # caption_investigation: hits /clusters/{id}/, /dockets/{id}/, etc.
    if re.search(r"/(?:clusters|dockets|recap-documents)/\d+/", url):
        return "caption_investigation"

    # General pattern fallback (handles remaining cases).
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
        resp.reason = {
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
        }[resp.status_code]
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


class _StubResponse:
    """Minimal Response-like for sync _request_with_retry's contract.

    The sync client's _request_with_retry returns a requests.Response.
    Callers invoke .json() on it to get data, and .raise_for_status()
    before the return. This stub satisfies both.
    """

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


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

    Non-target-stage calls always return a stubbed clean no-match
    response, making the harness CI-safe: no live API calls are made,
    no token is consumed.

    The sync client's _request_with_retry returns a requests.Response;
    the stub wraps each payload in a _StubResponse that implements
    .json() and .raise_for_status().
    """

    def __init__(self, client: Any, spec: dict[str, Any]) -> None:
        self.client = client
        self.spec = spec
        self.target_stage: str = spec["stage"]
        self.failure_mode: str = spec["failure_mode"]
        self.target_attempt_idx: int = int(spec.get("attempt_idx", 0))
        self._stage_call_counts: dict[str, int] = {}
        self._original: Callable[..., Any] | None = None

    def __enter__(self) -> "MockSpecPatcher":
        self._original = self.client._request_with_retry
        self.client._request_with_retry = self._build_wrapped(self._original)  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        # Restore the original bound method.
        self.client._request_with_retry = self._original  # type: ignore[assignment]

    def _build_wrapped(
        self, original: Callable[..., Any],
    ) -> Callable[..., Any]:
        def wrapped(method: str, url: str, **kwargs: Any) -> Any:
            params = kwargs.get("params")
            stage = _classify_url(url, params=params)
            count = self._stage_call_counts.get(stage, 0)
            self._stage_call_counts[stage] = count + 1

            if stage == self.target_stage and count == self.target_attempt_idx:
                _raise_for_failure_mode(self.failure_mode, stage)

            # Non-target call (or target call before attempt_idx): return a
            # stubbed clean response. The sync _request_with_retry returns a
            # requests.Response, so wrap the payload in _StubResponse.
            payload = _CLEAN_NO_MATCH.get(stage, _CLEAN_NO_MATCH["_default"])
            return _StubResponse(payload)

        return wrapped


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


class AsyncMockSpecPatcher:
    """Async equivalent of MockSpecPatcher.

    The async client's _request_with_retry returns a parsed dict directly
    (not a requests.Response), so this patcher returns the payload bare
    — no _StubResponse wrapper needed.

    Usage::

        async with AsyncMockSpecPatcher(async_client, spec=fixture.mock_spec):
            result = await async_verifier.verify(fixture.citation)
    """

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
            params = kwargs.get("params")
            stage = _classify_url(url, params=params)
            count = self._stage_call_counts.get(stage, 0)
            self._stage_call_counts[stage] = count + 1
            if stage == self.target_stage and count == self.target_attempt_idx:
                _raise_for_failure_mode(self.failure_mode, stage)
            # Async _request_with_retry returns a dict directly.
            return _CLEAN_NO_MATCH.get(stage, _CLEAN_NO_MATCH["_default"])

        return wrapped
