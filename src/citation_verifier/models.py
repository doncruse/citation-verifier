"""Data structures for citation verification (v0.3 schema)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Status taxonomy (design §2.2)
# ---------------------------------------------------------------------------


class Status(Enum):
    # Resolved-clean
    VERIFIED = "VERIFIED"
    VERIFIED_PARTIAL = "VERIFIED_PARTIAL"
    VERIFIED_VIA_RECAP = "VERIFIED_VIA_RECAP"
    VERIFIED_DOCKET_ONLY = "VERIFIED_DOCKET_ONLY"
    # Resolved-but-wrong
    WRONG_CASE = "WRONG_CASE"
    # Unresolved
    NOT_FOUND = "NOT_FOUND"
    VERIFICATION_INCOMPLETE = "VERIFICATION_INCOMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Resolution path (design §2.5) — fully wired in Phase 2; Phase 1 emits at
# most a single entry for the resolving stage so that the confidence number
# previously held at the top level has a home.
# ---------------------------------------------------------------------------


class StageName(Enum):
    citation_lookup = "citation_lookup"
    opinion_search = "opinion_search"
    recap_document_search = "recap_document_search"
    recap_docket_search = "recap_docket_search"
    plain_docket_search = "plain_docket_search"
    caption_investigation = "caption_investigation"


class StageVerdict(Enum):
    resolved = "resolved"
    no_match = "no_match"
    partial = "partial"
    errored = "errored"
    skipped = "skipped"


@dataclass
class ResolutionPathEntry:
    stage: StageName
    query: dict[str, Any]
    raw_response_summary: dict[str, Any]   # Free-form per stage; see design §2.5
    verdict: StageVerdict
    confidence: float | None
    notes: str | None
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Final IDs (design §2.4)
# ---------------------------------------------------------------------------


class TextSource(Enum):
    opinion_plain_text = "opinion_plain_text"
    opinion_html = "opinion_html"
    recap_document = "recap_document"


@dataclass
class FinalIds:
    cluster_id: int | None
    opinion_id: int | None
    docket_id: int | None
    recap_document_id: int | None
    absolute_url: str | None
    text_source: TextSource | None


# ---------------------------------------------------------------------------
# Warnings (design §2.6)
# ---------------------------------------------------------------------------


class WarningCategory(Enum):
    silent_partial_verification = "silent_partial_verification"
    cl_display_name_data_bug = "cl_display_name_data_bug"
    court_mismatch_noted = "court_mismatch_noted"
    date_close_not_exact = "date_close_not_exact"
    name_formatting_noise = "name_formatting_noise"
    unparseable_citation = "unparseable_citation"
    extraction_contamination_detected = "extraction_contamination_detected"
    # Phase 3 additions (design v2 §2.6 amendment workflow; see CHANGELOG.md)
    cl_duplicate_clusters = "cl_duplicate_clusters"
    wrong_page_number = "wrong_page_number"


@dataclass
class Warning:
    category: WarningCategory
    message: str
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Gates (design §2.7) — Phase 1 defines the types; gate evaluation lands in
# Phase 4. Phase 1's verifier always emits an empty gates_failed list.
# ---------------------------------------------------------------------------


class GateName(Enum):
    no_not_found = "no_not_found"
    no_wrong_case = "no_wrong_case"
    no_verification_incomplete = "no_verification_incomplete"
    no_partial_verification = "no_partial_verification"
    require_primary_reporter_resolved = "require_primary_reporter_resolved"
    require_caption_investigation_on_mismatch = (
        "require_caption_investigation_on_mismatch"
    )


@dataclass
class GateSpec:
    name: GateName
    config: dict[str, Any] | None = None


@dataclass
class GateFailure:
    gate: GateName
    reason: str
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Diagnostic + CandidateMatch — unchanged. Still used by verifier.py stage
# internals. Warnings replace Diagnostics only at the VerificationResult
# boundary.
# ---------------------------------------------------------------------------


@dataclass
class Diagnostic:
    category: str   # name, court, date, docket, cite, recap, info
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class ParsedCitation:
    raw_text: str
    case_name: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    court: str | None = None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    docket_number: str | None = None
    is_westlaw: bool = False
    wl_number: str | None = None
    ecf_document_number: str | None = None   # design §2.10 + §8 disposition


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


# ---------------------------------------------------------------------------
# VerificationResult (design §2.1) — the contract with every consumer.
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    citation_as_written: str
    parsed_citation: ParsedCitation | None
    status: Status
    final_ids: FinalIds
    resolution_path: list[ResolutionPathEntry]
    warnings: list[Warning]
    gates_failed: list[GateFailure]
    timing: dict[str, Any]
    cache_hit: bool

    @property
    def headline_confidence(self) -> float | None:
        """Per design §2.5: walk resolution_path in reverse, return the
        confidence of the first entry whose verdict is `resolved` or
        `partial`. Returns None if no such entry exists."""
        for entry in reversed(self.resolution_path):
            if entry.verdict in (StageVerdict.resolved, StageVerdict.partial):
                return entry.confidence
        return None

    @property
    def syllabus(self) -> str | None:
        """Surface CourtListener-provided syllabus / nature_of_suit metadata
        from the citation_lookup stage entry, when present.

        Walks resolution_path in reverse looking for a citation_lookup entry
        whose verdict is `resolved` or `partial`. Joins the entry's
        raw_response_summary `syllabus` and `nature_of_suit` keys with '; '
        (preserving the pre-refactor convention from
        verifier._process_citation_lookup_hit). Returns None when no
        citation_lookup entry exists in the path or neither key is populated.

        Centralizes the per-stage shape coupling so consumers
        (notably brief_pipeline / the verify-brief skill) don't have to know
        the raw_response_summary internals. Restoration of the pre-refactor
        syllabus surface, deferred from Phase 1 (retro Q5)."""
        for entry in reversed(self.resolution_path):
            if entry.stage is not StageName.citation_lookup:
                continue
            if entry.verdict not in (StageVerdict.resolved, StageVerdict.partial):
                continue
            parts = []
            syl = entry.raw_response_summary.get("syllabus")
            if syl:
                parts.append(syl)
            nos = entry.raw_response_summary.get("nature_of_suit")
            if nos:
                parts.append(nos)
            return "; ".join(parts) if parts else None
        return None


@dataclass
class BatchError:
    citation: str
    error: str


@dataclass
class BatchVerificationResult:
    total: int
    by_status: dict[Status, list[VerificationResult]]
    errors: list[BatchError]
    elapsed_ms: int
