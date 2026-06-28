"""Citation Verifier — verify legal citations against CourtListener."""

from .client import CourtListenerClient
from .models import (
    CandidateMatch,
    ParsedCitation,
    Status,
    VerificationResult,
)
from .parser import parse_citation
from .quote_matcher import QuoteMatch, QuoteVerification, verify_quote
from .verifier import CitationVerifier

__all__ = [
    "CitationVerifier",
    "CourtListenerClient",
    "CandidateMatch",
    "ParsedCitation",
    "QuoteMatch",
    "QuoteVerification",
    "Status",
    "VerificationResult",
    "parse_citation",
    "verify_quote",
]
