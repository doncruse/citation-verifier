"""Citation Verifier — verify legal citations against CourtListener."""

from .client import CourtListenerClient
from .models import (
    CandidateMatch,
    ParsedCitation,
    VerificationResult,
    VerificationStatus,
)
from .parser import parse_citation
from .verifier import CitationVerifier

__all__ = [
    "CitationVerifier",
    "CourtListenerClient",
    "CandidateMatch",
    "ParsedCitation",
    "VerificationResult",
    "VerificationStatus",
    "parse_citation",
]
