"""CourtListener API wrapper with rate limiting (sync and async)."""

from __future__ import annotations

import asyncio
import os
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
import certifi
import requests
from dotenv import load_dotenv

# Load .env from project root (walk up from this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


class CourtListenerClient:
    """Client for the CourtListener REST API v4."""

    BASE_URL = "https://www.courtlistener.com/api/rest/v4"
    REQUEST_TIMEOUT = 15  # seconds

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or os.environ.get("COURTLISTENER_API_TOKEN", "")
        self._session = requests.Session()
        if self.api_token:
            self._session.headers["Authorization"] = f"Token {self.api_token}"
        self._session.headers["User-Agent"] = "citation-verifier/0.1"
        self._last_request_time: float = 0.0

    MAX_RETRIES = 3

    def _rate_limit(self) -> None:
        """Enforce at least 1 second between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.monotonic()

    def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Make an HTTP request with 429 retry handling.

        On 429 (Too Many Requests), respects the ``wait_until`` timestamp
        from the response body or falls back to ``Retry-After`` header.
        """
        kwargs.setdefault("timeout", self.REQUEST_TIMEOUT)
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            resp = self._session.request(method, url, **kwargs)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp

            # Parse wait time from response
            wait_seconds = 60.0  # conservative default
            try:
                body = resp.json()
                wait_until = body.get("wait_until")
                if wait_until:
                    target = datetime.fromisoformat(wait_until)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    wait_seconds = max(
                        0.0, (target - datetime.now(timezone.utc)).total_seconds()
                    )
            except Exception:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_seconds = float(retry_after)
                    except ValueError:
                        pass

            if attempt < self.MAX_RETRIES - 1:
                time.sleep(wait_seconds + 1.0)  # +1s buffer

        # Final attempt failed
        resp.raise_for_status()
        return resp  # unreachable but satisfies type checker

    def citation_lookup(self, text: str) -> list[dict[str, Any]]:
        """Look up citations using the Citation Lookup API.

        Returns a list of matched opinion clusters.
        """
        url = f"{self.BASE_URL}/citation-lookup/"
        resp = self._request_with_retry("POST", url, json={"text": text})
        data: Any = resp.json()
        # The API returns a list of matched clusters
        if isinstance(data, list):
            return data
        # Or it may return a dict with results
        if isinstance(data, dict):
            results_val = data.get("results", data.get("clusters", []))
            if isinstance(results_val, list):
                return results_val
        return []

    def search_opinions(
        self,
        q: str | None = None,
        court: str | None = None,
        filed_after: str | None = None,
        filed_before: str | None = None,
        case_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search opinions using the CourtListener Search API.

        Returns a list of search result dicts.
        """
        params: dict[str, str] = {"type": "o"}
        if q:
            params["q"] = q
        if court:
            params["court"] = court
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        if case_name:
            params["case_name"] = case_name

        url = f"{self.BASE_URL}/search/"
        resp = self._request_with_retry("GET", url, params=params)
        data: Any = resp.json()
        results: list[dict[str, Any]] = data.get("results", [])
        return results

    def search_recap(
        self,
        q: str | None = None,
        court: str | None = None,
        filed_after: str | None = None,
        filed_before: str | None = None,
        case_name: str | None = None,
        docket_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search RECAP docket entries (orders, opinions from PACER).

        Returns a list of search result dicts.
        """
        params: dict[str, str] = {"type": "r"}
        if q:
            params["q"] = q
        if court:
            params["court"] = court
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        if case_name:
            params["case_name"] = case_name
        if docket_number:
            # Use q with quoted string — the docket param is unreliable
            q_parts = [params.get("q", ""), f'"{docket_number}"']
            params["q"] = " ".join(p for p in q_parts if p)

        url = f"{self.BASE_URL}/search/"
        resp = self._request_with_retry("GET", url, params=params)
        data: Any = resp.json()
        results: list[dict[str, Any]] = data.get("results", [])
        return results

    MAX_DOCKET_ENTRIES = 200

    def get_docket_entries(
        self,
        docket_id: int,
        date_filed_after: str | None = None,
        date_filed_before: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch docket entries for a specific docket, optionally filtered by date.

        Follows cursor pagination to retrieve all matching entries (up to
        MAX_DOCKET_ENTRIES to avoid runaway requests on very large dockets).

        Returns individual docket entries with their recap_documents.
        """
        params: dict[str, str] = {"docket": str(docket_id)}
        if date_filed_after:
            params["date_filed__gte"] = date_filed_after
        if date_filed_before:
            params["date_filed__lte"] = date_filed_before

        url: str | None = f"{self.BASE_URL}/docket-entries/"
        results: list[dict[str, Any]] = []
        while url and len(results) < self.MAX_DOCKET_ENTRIES:
            resp = self._request_with_retry("GET", url, params=params)
            data: Any = resp.json()
            results.extend(data.get("results", []))
            url = data.get("next")
            # Only pass params on the first request; subsequent pages
            # encode params in the next URL already.
            params = {}
        return results


class AsyncCourtListenerClient:
    """Async client for the CourtListener REST API v4.

    Uses aiohttp with a semaphore to limit concurrent requests.
    Must be used as an async context manager::

        async with AsyncCourtListenerClient() as client:
            results = await client.citation_lookup("576 U.S. 644")
    """

    BASE_URL = CourtListenerClient.BASE_URL
    REQUEST_TIMEOUT = CourtListenerClient.REQUEST_TIMEOUT
    MAX_RETRIES = CourtListenerClient.MAX_RETRIES
    MAX_DOCKET_ENTRIES = CourtListenerClient.MAX_DOCKET_ENTRIES

    # Max concurrent HTTP connections to CourtListener
    MAX_CONCURRENT = 5
    # Minimum interval between any two requests (seconds).
    # Mirrors the sync client's 1-second rate limit but slightly faster
    # since we're authenticated and want some parallelism benefit.
    MIN_REQUEST_INTERVAL = 0.5

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or os.environ.get("COURTLISTENER_API_TOKEN", "")
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._rate_lock = asyncio.Lock()
        self._last_request_time: float = 0.0

    async def __aenter__(self) -> AsyncCourtListenerClient:
        headers: dict[str, str] = {"User-Agent": "citation-verifier/0.1"}
        if self.api_token:
            headers["Authorization"] = f"Token {self.api_token}"
        timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        self._session = aiohttp.ClientSession(
            headers=headers, timeout=timeout, connector=connector
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests (async-safe).

        Uses a lock so only one coroutine checks/updates the timestamp
        at a time, guaranteeing a global minimum interval.
        """
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                await asyncio.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

    async def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Make an HTTP request with rate limiting and 429 retry.

        Rate limiting enforces a global minimum interval between requests.
        The semaphore caps concurrent connections. On 429, the semaphore
        is released during backoff so other requests can proceed.

        Returns parsed JSON response.
        """
        assert self._session is not None, "Use 'async with' to create the client"
        for attempt in range(self.MAX_RETRIES):
            await self._rate_limit()
            async with self._semaphore:
                async with self._session.request(method, url, **kwargs) as resp:
                    if resp.status == 429:
                        wait_seconds = 60.0
                        try:
                            body = await resp.json()
                            wait_until = body.get("wait_until")
                            if wait_until:
                                target = datetime.fromisoformat(wait_until)
                                if target.tzinfo is None:
                                    target = target.replace(tzinfo=timezone.utc)
                                wait_seconds = max(
                                    0.0,
                                    (target - datetime.now(timezone.utc)).total_seconds(),
                                )
                        except Exception:
                            retry_after = resp.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait_seconds = float(retry_after)
                                except ValueError:
                                    pass
                        if attempt < self.MAX_RETRIES - 1:
                            # Release semaphore during backoff sleep
                            backoff = wait_seconds * (2**attempt)
                            await asyncio.sleep(backoff + 1.0)
                            continue
                        resp.raise_for_status()

                    resp.raise_for_status()
                    return await resp.json()
        # Unreachable but satisfies type checker
        return {}

    async def citation_lookup(self, text: str) -> list[dict[str, Any]]:
        """Look up citations using the Citation Lookup API."""
        url = f"{self.BASE_URL}/citation-lookup/"
        data = await self._request_with_retry("POST", url, json={"text": text})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            results_val = data.get("results", data.get("clusters", []))
            if isinstance(results_val, list):
                return results_val
        return []

    async def search_opinions(
        self,
        q: str | None = None,
        court: str | None = None,
        filed_after: str | None = None,
        filed_before: str | None = None,
        case_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search opinions using the CourtListener Search API."""
        params: dict[str, str] = {"type": "o"}
        if q:
            params["q"] = q
        if court:
            params["court"] = court
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        if case_name:
            params["case_name"] = case_name

        url = f"{self.BASE_URL}/search/"
        data = await self._request_with_retry("GET", url, params=params)
        return data.get("results", [])

    async def search_recap(
        self,
        q: str | None = None,
        court: str | None = None,
        filed_after: str | None = None,
        filed_before: str | None = None,
        case_name: str | None = None,
        docket_number: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search RECAP docket entries."""
        params: dict[str, str] = {"type": "r"}
        if q:
            params["q"] = q
        if court:
            params["court"] = court
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        if case_name:
            params["case_name"] = case_name
        if docket_number:
            q_parts = [params.get("q", ""), f'"{docket_number}"']
            params["q"] = " ".join(p for p in q_parts if p)

        url = f"{self.BASE_URL}/search/"
        data = await self._request_with_retry("GET", url, params=params)
        return data.get("results", [])

    async def get_docket_entries(
        self,
        docket_id: int,
        date_filed_after: str | None = None,
        date_filed_before: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch docket entries for a specific docket, optionally filtered by date."""
        params: dict[str, str] = {"docket": str(docket_id)}
        if date_filed_after:
            params["date_filed__gte"] = date_filed_after
        if date_filed_before:
            params["date_filed__lte"] = date_filed_before

        url: str | None = f"{self.BASE_URL}/docket-entries/"
        results: list[dict[str, Any]] = []
        while url and len(results) < self.MAX_DOCKET_ENTRIES:
            data = await self._request_with_retry("GET", url, params=params)
            results.extend(data.get("results", []))
            url = data.get("next")
            params = {}
        return results

    STORAGE_BASE = "https://storage.courtlistener.com/"

    async def get_pdf_url(self, matched_url: str) -> str | None:
        """Resolve a CL matched_url to a PDF download URL.

        For opinions: CL serves PDFs at {opinion_url}pdf/ — no API call needed.
        For RECAP dockets: fetches docket-entries via API to find
        recap_documents with filepath_local.

        The caller should verify the URL actually returns a PDF
        (check content-type) since not all opinions have PDFs.
        """
        if not matched_url:
            return None

        # Opinion URL: https://www.courtlistener.com/opinion/12345/slug/
        if "/opinion/" in matched_url:
            url = matched_url.rstrip("/")
            return f"{url}/pdf/"

        # RECAP docket URL: /docket/12345/...
        docket_match = re.search(r"/docket/(\d+)/", matched_url)
        if not docket_match:
            return None

        docket_id = docket_match.group(1)

        # Check for entry number (second digit group): /docket/12345/67/
        docket_entry_match = re.search(r"/docket/\d+/(\d+)/", matched_url)

        try:
            if docket_entry_match:
                entry_number = docket_entry_match.group(1)
                entry_data = await self._request_with_retry(
                    "GET",
                    f"{self.BASE_URL}/docket-entries/",
                    params={"docket": docket_id, "entry_number": entry_number},
                )
                for entry in entry_data.get("results", []):
                    url = self._first_recap_doc_url(entry)
                    if url:
                        return url

            # Fallback: fetch recent entries for this docket
            entry_data = await self._request_with_retry(
                "GET",
                f"{self.BASE_URL}/docket-entries/",
                params={"docket": docket_id, "page_size": "5"},
            )
            for entry in entry_data.get("results", []):
                url = self._first_recap_doc_url(entry)
                if url:
                    return url

        except Exception:
            pass

        return None

    def _first_recap_doc_url(self, entry: dict[str, Any]) -> str | None:
        """Extract the PDF URL from the first recap_document in a docket entry."""
        for doc in entry.get("recap_documents", []):
            filepath = doc.get("filepath_local") or ""
            if filepath:
                return f"{self.STORAGE_BASE}{filepath}"
        return None
