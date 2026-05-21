"""Citation Verifier — verify legal citations against CourtListener."""

from .client import CourtListenerClient
from .models import (
    CandidateMatch,
    ParsedCitation,
    Status,
    VerificationResult,
)
from .parser import parse_citation

# CitationVerifier re-export temporarily disabled during the v0.3 schema
# migration. verifier.py and cache.py still construct the old shape; Task 2
# of refactor/v0.3 migrates them and then restores this import.
# from .verifier import CitationVerifier

__all__ = [
    "CourtListenerClient",
    "CandidateMatch",
    "ParsedCitation",
    "Status",
    "VerificationResult",
    "parse_citation",
]
