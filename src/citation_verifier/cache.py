"""Simple file-based cache for verification results."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .models import (
    FinalIds,
    GateFailure,
    GateName,
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

logger = logging.getLogger(__name__)

CACHE_FILENAME = ".citation_cache.json"
DEFAULT_CACHE_PATH = Path(CACHE_FILENAME)

# Env var that relocates the CL citation cache (and, in the proposition
# pipeline, enables a persistent lookup cache). Unset -> historical
# CWD-relative default, behavior unchanged.
CACHE_DIR_ENV = "CITATION_VERIFIER_CACHE_DIR"


def resolve_cache_dir(cli_value: str | None = None) -> Path | None:
    """Resolve the cache directory. Precedence: explicit CLI value >
    ``CITATION_VERIFIER_CACHE_DIR`` env var > None (the default -- no
    relocation, CWD-relative cache). Returns a Path or None."""
    if cli_value:
        return Path(cli_value)
    env = os.environ.get(CACHE_DIR_ENV)
    if env:
        return Path(env)
    return None


def citation_cache_path(cache_dir: Path | None) -> Path:
    """Location of the CL citation cache file. ``None`` -> the CWD-relative
    ``DEFAULT_CACHE_PATH`` (unchanged); a dir -> ``<dir>/.citation_cache.json``."""
    if cache_dir is None:
        return DEFAULT_CACHE_PATH
    return Path(cache_dir) / CACHE_FILENAME


def open_citation_cache(cache_dir: Path | None) -> VerificationCache:
    """Open the CL citation cache rooted at ``cache_dir`` (creating the dir
    when relocated). ``None`` -> the default CWD-relative cache."""
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
    return VerificationCache(citation_cache_path(cache_dir))


def _serialize_path_entry(e: ResolutionPathEntry) -> dict[str, Any]:
    return {
        "stage": e.stage.value,
        "query": e.query,
        "raw_response_summary": e.raw_response_summary,
        "verdict": e.verdict.value,
        "confidence": e.confidence,
        "notes": e.notes,
        "elapsed_ms": e.elapsed_ms,
    }


def _serialize_warning(w: Warning) -> dict[str, Any]:
    return {
        "category": w.category.value,
        "message": w.message,
        "details": w.details,
    }


def _serialize_gate_failure(g: GateFailure) -> dict[str, Any]:
    return {
        "gate": g.gate.value,
        "reason": g.reason,
        "details": g.details,
    }


def _serialize_parsed_citation(p: ParsedCitation | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "raw_text": p.raw_text,
        "case_name": p.case_name,
        "plaintiff": p.plaintiff,
        "defendant": p.defendant,
        "volume": p.volume,
        "reporter": p.reporter,
        "page": p.page,
        "court": p.court,
        "year": p.year,
        "month": p.month,
        "day": p.day,
        "docket_number": p.docket_number,
        "is_westlaw": p.is_westlaw,
        "wl_number": p.wl_number,
        "ecf_document_number": p.ecf_document_number,
    }


def _serialize_final_ids(f: FinalIds) -> dict[str, Any]:
    return {
        "cluster_id": f.cluster_id,
        "opinion_id": f.opinion_id,
        "docket_id": f.docket_id,
        "recap_document_id": f.recap_document_id,
        "absolute_url": f.absolute_url,
        "text_source": f.text_source.value if f.text_source is not None else None,
    }


def _to_dict(result: VerificationResult) -> dict[str, Any]:
    """Produce a JSON-safe dict for a VerificationResult."""
    return {
        "citation_as_written": result.citation_as_written,
        "parsed_citation": _serialize_parsed_citation(result.parsed_citation),
        "status": result.status.value,
        "final_ids": _serialize_final_ids(result.final_ids),
        "resolution_path": [_serialize_path_entry(e) for e in result.resolution_path],
        "warnings": [_serialize_warning(w) for w in result.warnings],
        "gates_failed": [_serialize_gate_failure(g) for g in result.gates_failed],
        "timing": result.timing,
        "cache_hit": result.cache_hit,
    }


def _hydrate_path_entry(d: dict[str, Any]) -> ResolutionPathEntry:
    return ResolutionPathEntry(
        stage=StageName(d["stage"]),
        query=d.get("query", {}),
        raw_response_summary=d.get("raw_response_summary", {}),
        verdict=StageVerdict(d["verdict"]),
        confidence=d.get("confidence"),
        notes=d.get("notes"),
        elapsed_ms=d.get("elapsed_ms", 0),
    )


def _hydrate_warning(d: dict[str, Any]) -> Warning:
    return Warning(
        category=WarningCategory(d["category"]),
        message=d["message"],
        details=d.get("details"),
    )


def _hydrate_gate_failure(d: dict[str, Any]) -> GateFailure:
    return GateFailure(
        gate=GateName(d["gate"]),
        reason=d["reason"],
        details=d.get("details"),
    )


def _hydrate_parsed_citation(d: dict[str, Any] | None) -> ParsedCitation | None:
    if d is None:
        return None
    return ParsedCitation(**d)


def _hydrate_final_ids(d: dict[str, Any]) -> FinalIds:
    ts = d.get("text_source")
    return FinalIds(
        cluster_id=d.get("cluster_id"),
        opinion_id=d.get("opinion_id"),
        docket_id=d.get("docket_id"),
        recap_document_id=d.get("recap_document_id"),
        absolute_url=d.get("absolute_url"),
        text_source=TextSource(ts) if ts is not None else None,
    )


def _from_dict(d: dict[str, Any]) -> VerificationResult:
    """Hydrate a VerificationResult from a previously-serialized dict."""
    return VerificationResult(
        citation_as_written=d["citation_as_written"],
        parsed_citation=_hydrate_parsed_citation(d.get("parsed_citation")),
        status=Status(d["status"]),
        final_ids=_hydrate_final_ids(d.get("final_ids") or {}),
        resolution_path=[
            _hydrate_path_entry(e) for e in d.get("resolution_path", [])
        ],
        warnings=[_hydrate_warning(w) for w in d.get("warnings", [])],
        gates_failed=[
            _hydrate_gate_failure(g) for g in d.get("gates_failed", [])
        ],
        timing=d.get("timing", {}),
        cache_hit=d.get("cache_hit", False),
    )


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
            return _from_dict(entry)
        except (KeyError, ValueError):
            logger.debug("Invalid cache entry for %r, ignoring", key)
            return None

    def put(self, citation_text: str, result: VerificationResult) -> None:
        """Store a result in the cache and persist to disk."""
        key = citation_text.strip()
        self._data[key] = _to_dict(result)
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
