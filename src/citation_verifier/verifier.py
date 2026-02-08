"""Core verification pipeline: citation lookup → fuzzy search fallback."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from .client import CourtListenerClient
from .court_map import lookup_court_id
from .models import CandidateMatch, ParsedCitation, VerificationResult, VerificationStatus
from .parser import parse_citation

logger = logging.getLogger(__name__)


class CitationVerifier:
    """Two-step citation verifier using CourtListener APIs."""

    def __init__(self, client: CourtListenerClient | None = None):
        self.client = client or CourtListenerClient()

    def verify(self, citation_text: str) -> VerificationResult:
        """Verify a citation string through the two-step pipeline.

        Step 1: Try the Citation Lookup API (fast, precise).
        Step 2: Parse and fuzzy-search as fallback.
        """
        citation_text = citation_text.strip()

        # Step 1: Citation Lookup API
        parsed = parse_citation(citation_text)
        try:
            lookup_results = self.client.citation_lookup(citation_text)
            for lr in lookup_results:
                clusters = lr.get("clusters", [])
                for cluster in clusters:
                    case_name = cluster.get("case_name", "")
                    cluster_id = cluster.get("id")
                    url = cluster.get("absolute_url", "")
                    if url and not url.startswith("http"):
                        url = f"https://www.courtlistener.com{url}"
                    elif cluster_id and not url:
                        url = f"https://www.courtlistener.com/opinion/{cluster_id}/"

                    # Verify the case name actually matches before calling it VERIFIED
                    if parsed.case_name and case_name:
                        if not self._names_match(parsed, case_name):
                            return VerificationResult(
                                input_citation=citation_text,
                                status=VerificationStatus.NOT_FOUND,
                                confidence=0.0,
                                matched_case_name=case_name,
                                matched_url=url,
                                matched_cluster_id=cluster_id,
                                diagnostics=[
                                    f"Citation exists but belongs to a different case: "
                                    f"\"{case_name}\"",
                                ],
                            )

                    return VerificationResult(
                        input_citation=citation_text,
                        status=VerificationStatus.VERIFIED,
                        confidence=1.0,
                        matched_case_name=case_name,
                        matched_url=url,
                        matched_cluster_id=cluster_id,
                    )
        except Exception:
            # Citation lookup failed; fall through to search
            logger.debug("Citation lookup failed", exc_info=True)

        # Step 1b: Try adjacent starting pages (off-by-one is common)
        if parsed.volume and parsed.reporter and parsed.page:
            try:
                base_page = int(parsed.page)
                for offset in (-1, 1, -2, 2):
                    alt_page = str(base_page + offset)
                    alt_cite = f"{parsed.volume} {parsed.reporter} {alt_page}"
                    try:
                        lookup_results = self.client.citation_lookup(alt_cite)
                    except Exception:
                        logger.debug("Adjacent page lookup failed for %s", alt_cite, exc_info=True)
                        continue
                    for lr in lookup_results:
                        clusters = lr.get("clusters", [])
                        for cluster in clusters:
                            case_name = cluster.get("case_name", "")
                            cluster_id = cluster.get("id")
                            url = cluster.get("absolute_url", "")
                            if url and not url.startswith("http"):
                                url = f"https://www.courtlistener.com{url}"
                            elif cluster_id and not url:
                                url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
                            if not (parsed.case_name and case_name):
                                continue
                            # Stricter name check for adjacent-page matches:
                            # require defendant similarity >= 0.7
                            result_lower = case_name.lower()
                            result_def = ""
                            if " v. " in result_lower:
                                result_def = result_lower.split(" v. ", 1)[1].strip()
                            elif " v " in result_lower:
                                result_def = result_lower.split(" v ", 1)[1].strip()
                            if parsed.defendant and result_def:
                                def_sim = SequenceMatcher(
                                    None, parsed.defendant.lower(), result_def,
                                ).ratio()
                                if def_sim < 0.7:
                                    continue
                            elif not self._names_match(parsed, case_name):
                                continue
                            return VerificationResult(
                                    input_citation=citation_text,
                                    status=VerificationStatus.VERIFIED,
                                    confidence=1.0,
                                    matched_case_name=case_name,
                                    matched_url=url,
                                    matched_cluster_id=cluster_id,
                                    diagnostics=[
                                        f"Matched via adjacent page: cited page {parsed.page}, "
                                        f"case starts at page {alt_page}",
                                    ],
                                )
            except (ValueError, TypeError):
                pass

        # Step 2: Fuzzy search fallback
        return self._search_fallback(citation_text, parsed)

    def _search_fallback(
        self, citation_text: str, parsed: ParsedCitation
    ) -> VerificationResult:
        """Search CourtListener using parsed citation metadata."""
        court_id = lookup_court_id(parsed.court) if parsed.court else None

        # Build date range: +/- 1 year from cited year
        filed_after = None
        filed_before = None
        if parsed.year:
            filed_after = f"{parsed.year - 1}-01-01"
            filed_before = f"{parsed.year + 1}-12-31"

        candidates: list[CandidateMatch] = []

        # First search: with court filter
        if parsed.case_name:
            try:
                results = self.client.search_opinions(
                    case_name=parsed.case_name,
                    court=court_id,
                    filed_after=filed_after,
                    filed_before=filed_before,
                )
                candidates = self._process_results(results, parsed)
            except Exception:
                logger.debug("Opinion search with court filter failed", exc_info=True)

            # Retry without court filter if no results
            if not candidates and court_id:
                try:
                    results = self.client.search_opinions(
                        case_name=parsed.case_name,
                        filed_after=filed_after,
                        filed_before=filed_before,
                    )
                    candidates = self._process_results(results, parsed)
                except Exception:
                    logger.debug("Opinion search without court filter failed", exc_info=True)

        # Step 3: RECAP fallback (docket entries, orders, PACER documents)
        # Note: RECAP dateFiled is the case filing date, not the opinion date,
        # so we skip date filtering here and rely on name/court matching.
        if not candidates and parsed.case_name:
            try:
                results = self.client.search_recap(
                    case_name=parsed.case_name,
                    court=court_id,
                )
                candidates = self._process_recap_results(results, parsed)
            except Exception:
                logger.debug("RECAP search with court filter failed", exc_info=True)

            if not candidates and court_id:
                try:
                    results = self.client.search_recap(
                        case_name=parsed.case_name,
                    )
                    candidates = self._process_recap_results(results, parsed)
                except Exception:
                    logger.debug("RECAP search without court filter failed", exc_info=True)

        if not candidates:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                diagnostics=["No matching cases found in CourtListener opinions or RECAP"],
            )

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        # When a reporter/WL citation was given but couldn't be verified
        # via lookup, require court corroboration before calling it a match.
        # A name-only hit in the wrong court is likely a coincidence.
        has_unverified_cite = bool(
            (parsed.volume and parsed.reporter and parsed.page)
            or parsed.wl_number
        )
        if has_unverified_cite and court_id and best.court_id != court_id:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                candidates=candidates[:5],
                diagnostics=[
                    f"Reporter citation could not be verified, and no matching "
                    f"cases were found in {parsed.court}",
                ],
            )

        if best.score >= 0.85:
            status = VerificationStatus.LIKELY_REAL
        elif best.score >= 0.40:
            status = VerificationStatus.POSSIBLE_MATCH
        else:
            status = VerificationStatus.NOT_FOUND

        diagnostics = self._finalize_diagnostics(best.mismatches, best.score, status)

        return VerificationResult(
            input_citation=citation_text,
            status=status,
            confidence=best.score,
            matched_case_name=best.case_name,
            matched_url=best.url,
            matched_cluster_id=best.cluster_id,
            candidates=candidates[:5],
            diagnostics=diagnostics,
        )

    def _process_results(
        self, results: list[dict], parsed: ParsedCitation
    ) -> list[CandidateMatch]:
        """Convert API results to scored CandidateMatch objects."""
        candidates = []
        for r in results:
            case_name = r.get("caseName") or r.get("case_name", "")
            cluster_id = r.get("cluster_id") or r.get("id")
            date_filed = r.get("dateFiled") or r.get("date_filed", "")
            court_id = r.get("court_id") or r.get("court", "")
            url = r.get("absolute_url", "")
            if cluster_id and not url:
                url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
            elif url and not url.startswith("http"):
                url = f"https://www.courtlistener.com{url}"

            score, mismatches = self._score_match(parsed, case_name, court_id, date_filed, r)
            candidates.append(
                CandidateMatch(
                    case_name=case_name,
                    url=url,
                    cluster_id=cluster_id,
                    date_filed=date_filed,
                    court_id=court_id,
                    score=score,
                    mismatches=mismatches,
                )
            )
        return candidates

    def _process_recap_results(
        self, results: list[dict], parsed: ParsedCitation
    ) -> list[CandidateMatch]:
        """Convert RECAP search results to scored CandidateMatch objects.

        The RECAP search only returns a few documents per docket. When the
        cited date doesn't match any returned documents, we query the
        docket-entries API to look for entries near the cited date.
        """
        candidates = []
        seen_dockets: set[int] = set()
        for r in results:
            case_name = r.get("caseName") or r.get("case_name", "")
            docket_id = r.get("docket_id") or r.get("id")
            court_id = r.get("court_id") or r.get("court", "")
            docket_url = r.get("docket_absolute_url") or r.get("absolute_url", "")
            if docket_url and not docket_url.startswith("http"):
                docket_url = f"https://www.courtlistener.com{docket_url}"
            elif docket_id and not docket_url:
                docket_url = f"https://www.courtlistener.com/docket/{docket_id}/"

            if docket_id in seen_dockets:
                continue
            seen_dockets.add(docket_id)

            # Collect documents from search results
            docs = r.get("recap_documents", [])

            # Check if any doc is near the cited year
            has_date_match = False
            if parsed.year and docs:
                for doc in docs:
                    entry_date = doc.get("entry_date_filed") or doc.get("date_filed", "")
                    try:
                        if entry_date and int(entry_date[:4]) == parsed.year:
                            has_date_match = True
                            break
                    except (ValueError, IndexError):
                        pass

            # If no matching docs, query docket-entries API for the cited date
            if not has_date_match and parsed.year and docket_id:
                self._fetch_docs_for_docket(docket_id, parsed, docs)

            # Build candidates from individual documents
            if docs:
                candidate = self._pick_best_recap_doc(
                    docs, parsed, case_name, court_id, docket_url, docket_id, r
                )
                if candidate:
                    candidates.append(candidate)
            else:
                # No documents at all — docket-level fallback
                candidate = self._build_docket_only_candidate(
                    parsed, case_name, court_id, docket_url, docket_id, r
                )
                candidates.append(candidate)
        return candidates

    def _fetch_docs_for_docket(
        self, docket_id: int, parsed: ParsedCitation, docs: list[dict]
    ) -> None:
        """Query docket-entries API for documents matching the cited date.

        Tries exact date first (when month/day available), then year range.
        Appends found documents to the *docs* list (mutates in place).
        """
        found_entries = False
        # Exact date query when we have month and day
        if parsed.month and parsed.day:
            exact = f"{parsed.year}-{parsed.month:02d}-{parsed.day:02d}"
            try:
                entries = self.client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=exact,
                    date_filed_before=exact,
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        docs.append(doc)
                        found_entries = True
            except Exception:
                logger.debug(
                    "Docket entries query (exact date) failed for docket %s",
                    docket_id, exc_info=True
                )
        # Fall back to year range if exact date found nothing
        if not found_entries:
            try:
                entries = self.client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=f"{parsed.year}-01-01",
                    date_filed_before=f"{parsed.year}-12-31",
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        docs.append(doc)
            except Exception:
                logger.debug(
                    "Docket entries query (year range) failed for docket %s",
                    docket_id, exc_info=True
                )

    def _pick_best_recap_doc(
        self,
        docs: list[dict],
        parsed: ParsedCitation,
        case_name: str,
        court_id: str,
        docket_url: str,
        docket_id: int,
        result: dict,
    ) -> CandidateMatch | None:
        """Score all docs, pick the best substantive one, and build a CandidateMatch.

        Prefers opinions/orders over procedural filings. Returns None if no docs.
        """
        if not docs:
            return None

        # Score all docs, preferring opinions/orders over procedural filings
        scored_docs = []
        for doc in docs:
            entry_date = doc.get("entry_date_filed") or doc.get("date_filed", "")
            score, mismatches = self._score_match(
                parsed, case_name, court_id, entry_date, result,
            )
            desc = (
                doc.get("short_description")
                or doc.get("description")
                or ""
            ).lower()
            is_substantive = self._is_substantive_doc(desc)
            scored_docs.append((doc, entry_date, score, mismatches, is_substantive))

        # Pick best substantive doc; fall back to best overall
        substantive = [d for d in scored_docs if d[4]]
        pool = substantive or scored_docs
        best_doc = max(pool, key=lambda d: d[2])

        doc, entry_date, score, mismatches, _ = best_doc
        doc_url = doc.get("absolute_url", "")
        if doc_url and not doc_url.startswith("http"):
            doc_url = f"https://www.courtlistener.com{doc_url}"
        desc = doc.get("short_description") or doc.get("description", "")
        if desc and len(desc) > 80:
            desc = desc[:80] + "..."

        recap_note = "Found in RECAP (not in opinions database)"
        if entry_date:
            recap_note += f". Document dated {entry_date}"
        if desc:
            recap_note += f": {desc}"
        mismatches.insert(0, recap_note)

        return CandidateMatch(
            case_name=case_name,
            url=doc_url or docket_url,
            cluster_id=docket_id,
            date_filed=entry_date,
            court_id=court_id,
            score=score,
            mismatches=mismatches,
        )

    def _build_docket_only_candidate(
        self,
        parsed: ParsedCitation,
        case_name: str,
        court_id: str,
        docket_url: str,
        docket_id: int,
        result: dict,
    ) -> CandidateMatch:
        """Build a docket-level candidate when no documents are available.

        Discounts the score (0.6x) and strips date/citation diagnostics.
        """
        score, mismatches = self._score_match(
            parsed, case_name, court_id, "", result,
        )
        score = round(score * 0.6, 4)
        # Remove date/citation diagnostics — they're redundant when
        # we already can't verify a specific document.
        # Keep court/name diagnostics — those are still useful.
        _date_cite_prefixes = (
            "Year ", "Date close", "Date mismatch",
            "Reporter citation ", "WL number ",
            "Citation mismatch", "Case name not returned",
        )
        mismatches = [
            m for m in mismatches
            if not m.startswith(_date_cite_prefixes)
        ]
        mismatches.insert(
            0,
            "We found a possible docket match in RECAP, "
            "but no specific document could be verified",
        )
        return CandidateMatch(
            case_name=case_name,
            url=docket_url,
            cluster_id=docket_id,
            date_filed="",
            court_id=court_id,
            score=score,
            mismatches=mismatches,
        )

    @staticmethod
    def _finalize_diagnostics(
        mismatches: list[str],
        score: float,
        status: VerificationStatus,
    ) -> list[str]:
        """Finalize diagnostics by appending match language for non-verified results.

        When score >= 0.40, appends "However, we identified a likely/possible match"
        to the last diagnostic or as a standalone message.
        """
        diagnostics = list(mismatches)
        if score >= 0.40:
            match_word = "likely" if status == VerificationStatus.LIKELY_REAL else "possible"
            if diagnostics:
                last = diagnostics[-1]
                if last.endswith("could be verified"):
                    diagnostics[-1] = last + f". However, we identified a {match_word} match."
                else:
                    diagnostics[-1] = last + f", but we identified a {match_word} match."
            else:
                diagnostics.append(f"We identified a {match_word} match.")
        return diagnostics

    @staticmethod
    def _normalize_docket_number(dn: str) -> str:
        """Normalize a docket number for comparison.

        Strips division prefix ('2:') and leading zeros from numeric
        segments so that '17-cv-12676' and '2:17-cv-00012676' compare
        as equal.
        """
        # Strip optional division prefix (e.g. "2:" or "4:")
        dn = re.sub(r"^\d+:", "", dn)
        # Strip leading zeros from numeric segments
        return re.sub(r"(?<!\d)0+(?=\d)", "", dn).lower()

    @staticmethod
    def _is_substantive_doc(desc: str) -> bool:
        """Return True if a RECAP document description looks like an opinion,
        order, judgment, or similar ruling rather than a procedural filing."""
        _SUBSTANTIVE_KEYWORDS = (
            "opinion", "order", "judgment", "memorandum", "ruling",
            "decision", "decree", "findings of fact",
        )
        return any(kw in desc for kw in _SUBSTANTIVE_KEYWORDS)

    @staticmethod
    def _names_match(parsed: ParsedCitation, result_case_name: str) -> bool:
        """Check whether parsed citation and result refer to the same case.

        For cases with common prefixes like "State v.", "United States v.",
        or "In re", the full-name similarity is misleading. We compare the
        distinctive party names (defendant/plaintiff) instead.
        """
        result_lower = result_case_name.lower()

        # Extract defendant from the result case name
        result_defendant = ""
        if " v. " in result_lower:
            result_defendant = result_lower.split(" v. ", 1)[1].strip()
        elif " v " in result_lower:
            result_defendant = result_lower.split(" v ", 1)[1].strip()

        # If we have parsed party names, compare them directly
        if parsed.defendant and result_defendant:
            defendant_sim = SequenceMatcher(
                None,
                parsed.defendant.lower(),
                result_defendant,
            ).ratio()
            # Defendant is the distinctive part — require a real match
            if defendant_sim < 0.4:
                return False

        # Also check full name similarity as a baseline
        if parsed.case_name:
            full_sim = SequenceMatcher(
                None,
                parsed.case_name.lower(),
                result_lower,
            ).ratio()
            if full_sim < 0.4:
                return False

        return True

    def _score_match(
        self,
        parsed: ParsedCitation,
        result_case_name: str,
        result_court: str,
        result_date: str,
        result: dict,
    ) -> tuple[float, list[str]]:
        """Score how well a search result matches the parsed citation.

        Weights: case name (50%), court (20%), date (20%),
        docket number (5%), reporter/WL citation (5%).
        Returns (score, list of mismatch descriptions).
        """
        score = 0.0
        mismatches: list[str] = []

        # Case name similarity (50%)
        if parsed.case_name and result_case_name:
            name_sim = SequenceMatcher(
                None,
                parsed.case_name.lower(),
                result_case_name.lower(),
            ).ratio()
            score += 0.5 * name_sim
            if name_sim < 0.6:
                mismatches.append(
                    f"Name mismatch: cited \"{parsed.case_name}\" "
                    f"vs found \"{result_case_name}\""
                )
            elif name_sim < 0.85:
                mismatches.append(
                    f"Name differs: cited \"{parsed.case_name}\" "
                    f"~ found \"{result_case_name}\" ({name_sim:.0%} similar)"
                )
        elif parsed.case_name:
            mismatches.append("Case name not returned by API")

        # Court match (20%)
        if parsed.court and result_court:
            expected_court = lookup_court_id(parsed.court)
            if expected_court and expected_court == result_court:
                score += 0.2
            elif expected_court:
                mismatches.append(
                    f"Court mismatch: cited {parsed.court} ({expected_court}) "
                    f"vs found {result_court}"
                )
            elif parsed.court.lower() == result_court.lower():
                # Direct match on raw court string (e.g. state courts)
                score += 0.2
            else:
                mismatches.append(
                    f"Court mismatch: cited {parsed.court} vs found {result_court}"
                )
        elif parsed.court:
            mismatches.append(f"Court {parsed.court} could not be verified")

        # Date match (20%) — with month/day granularity when available
        if parsed.year and result_date:
            try:
                result_year = int(result_date[:4])
                year_diff = abs(parsed.year - result_year)
                if year_diff == 0:
                    # Same year — refine with month/day if available
                    if parsed.month and len(result_date) >= 7:
                        result_month = int(result_date[5:7])
                        if parsed.month == result_month:
                            if parsed.day and len(result_date) >= 10:
                                result_day = int(result_date[8:10])
                                if parsed.day == result_day:
                                    score += 0.20  # exact date
                                else:
                                    score += 0.18  # same month
                            else:
                                score += 0.18  # same month, no day to compare
                        else:
                            score += 0.15  # same year, wrong month
                            cited_date = f"{parsed.year}-{parsed.month:02d}"
                            if parsed.day:
                                cited_date += f"-{parsed.day:02d}"
                            mismatches.append(
                                f"Date close: cited {cited_date} vs filed {result_date}"
                            )
                    else:
                        score += 0.20  # same year, no month info to compare
                elif year_diff == 1:
                    score += 0.1
                    mismatches.append(
                        f"Date close: cited {parsed.year} vs filed {result_date}"
                    )
                else:
                    mismatches.append(
                        f"Date mismatch: cited {parsed.year} vs filed {result_date}"
                    )
            except (ValueError, IndexError):
                pass
        elif parsed.year:
            mismatches.append(f"Year {parsed.year} could not be verified")

        # Docket number match (5%)
        if parsed.docket_number:
            result_docket = (
                result.get("docketNumber")
                or result.get("docket_number")
                or ""
            )
            if result_docket:
                cited_dn = self._normalize_docket_number(parsed.docket_number)
                found_dn = self._normalize_docket_number(result_docket)
                if cited_dn == found_dn:
                    score += 0.05
                else:
                    mismatches.append(
                        f"Docket mismatch: cited {parsed.docket_number} "
                        f"vs found {result_docket}"
                    )

        # Reporter/WL citation match (5%)
        result_citation = result.get("citation", [])
        if isinstance(result_citation, list):
            result_citation = " ".join(str(c) for c in result_citation)
        elif not isinstance(result_citation, str):
            result_citation = str(result_citation)

        if parsed.volume and parsed.page and parsed.reporter:
            cite_str = f"{parsed.volume} {parsed.reporter} {parsed.page}"
            if cite_str.lower() in result_citation.lower():
                score += 0.05
            elif not result_citation.strip():
                mismatches.append(
                    f"Reporter citation {cite_str} could not be confirmed "
                    f"(CourtListener has no reporter citations on file for this case)"
                )
            else:
                mismatches.append(
                    f"Citation mismatch: cited {cite_str} "
                    f"but CourtListener has {result_citation}"
                )
        elif parsed.wl_number:
            if parsed.wl_number in result_citation:
                score += 0.05
            elif not result_citation.strip():
                mismatches.append(
                    f"WL number {parsed.wl_number} could not be confirmed "
                    f"(CourtListener has no citations on file for this case)"
                )
            else:
                mismatches.append(
                    f"WL number {parsed.wl_number} not found "
                    f"in CourtListener citations: {result_citation}"
                )

        return round(score, 4), mismatches
