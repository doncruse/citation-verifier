"""Data structures for citation verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class VerificationStatus(Enum):
    VERIFIED = "VERIFIED"
    LIKELY_REAL = "LIKELY_REAL"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class Diagnostic:
    category: str   # name, court, date, docket, cite, recap, info
    message: str    # human-readable detail

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


@dataclass
class CandidateMatch:
    case_name: str
    url: str
    cluster_id: int
    date_filed: str
    court_id: str
    score: float = 0.0
    description: str | None = None
    mismatches: list[Diagnostic] = field(default_factory=list)


@dataclass
class VerificationResult:
    input_citation: str
    status: VerificationStatus
    confidence: float = 0.0
    matched_case_name: str | None = None
    matched_url: str | None = None
    matched_cluster_id: int | None = None
    matched_court: str | None = None
    matched_date: str | None = None
    matched_description: str | None = None
    candidates: list[CandidateMatch] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    error: str | None = None
