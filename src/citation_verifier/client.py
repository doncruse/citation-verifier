"""CourtListener API wrapper with rate limiting."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

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

    def _rate_limit(self) -> None:
        """Enforce at least 1 second between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.monotonic()

    def citation_lookup(self, text: str) -> list[dict[str, Any]]:
        """Look up citations using the Citation Lookup API.

        Returns a list of matched opinion clusters.
        """
        self._rate_limit()
        url = f"{self.BASE_URL}/citation-lookup/"
        resp = self._session.post(
            url, json={"text": text}, timeout=self.REQUEST_TIMEOUT
        )
        resp.raise_for_status()
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
        self._rate_limit()
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
        resp = self._session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
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
        self._rate_limit()
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
        resp = self._session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data: Any = resp.json()
        results: list[dict[str, Any]] = data.get("results", [])
        return results

    def get_docket_entries(
        self,
        docket_id: int,
        date_filed_after: str | None = None,
        date_filed_before: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch docket entries for a specific docket, optionally filtered by date.

        Returns individual docket entries with their recap_documents.
        """
        self._rate_limit()
        params: dict[str, str] = {"docket": str(docket_id)}
        if date_filed_after:
            params["date_filed__gte"] = date_filed_after
        if date_filed_before:
            params["date_filed__lte"] = date_filed_before

        url = f"{self.BASE_URL}/docket-entries/"
        resp = self._session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data: Any = resp.json()
        results: list[dict[str, Any]] = data.get("results", [])
        return results
