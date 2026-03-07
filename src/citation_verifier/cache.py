"""Simple file-based cache for verification results."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import CandidateMatch, Diagnostic, VerificationResult, VerificationStatus

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path(".citation_cache.json")


class VerificationCache:
    """JSON file-based cache keyed by citation text.

    Cache entries store the full VerificationResult so that repeated
    verifications of the same citation string skip all API calls.
    """

    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Cache file corrupted, starting fresh")
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2))

    def get(self, citation_text: str) -> VerificationResult | None:
        """Look up a cached result. Returns None on miss."""
        key = citation_text.strip()
        entry = self._data.get(key)
        if entry is None:
            return None
        try:
            candidates = []
            for c in entry.get("candidates", []):
                c = dict(c)
                c["mismatches"] = [
                    Diagnostic(**m) if isinstance(m, dict) else Diagnostic("info", m)
                    for m in c.get("mismatches", [])
                ]
                candidates.append(CandidateMatch(**c))
            diagnostics = [
                Diagnostic(**d) if isinstance(d, dict) else Diagnostic("info", d)
                for d in entry.get("diagnostics", [])
            ]
            return VerificationResult(
                input_citation=entry["input_citation"],
                status=VerificationStatus(entry["status"]),
                confidence=entry.get("confidence", 0.0),
                matched_case_name=entry.get("matched_case_name"),
                matched_url=entry.get("matched_url"),
                matched_cluster_id=entry.get("matched_cluster_id"),
                candidates=candidates,
                diagnostics=diagnostics,
                error=entry.get("error"),
            )
        except (KeyError, ValueError):
            logger.debug("Invalid cache entry for %r, ignoring", key)
            return None

    def put(self, citation_text: str, result: VerificationResult) -> None:
        """Store a result in the cache and persist to disk."""
        key = citation_text.strip()
        d = asdict(result)
        d["status"] = result.status.value
        self._data[key] = d
        self._save()

    def clear(self) -> int:
        """Remove all entries. Returns the number of entries cleared."""
        count = len(self._data)
        self._data = {}
        if self.path.exists():
            self.path.unlink()
        return count

    def __len__(self) -> int:
        return len(self._data)
