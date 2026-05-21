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
