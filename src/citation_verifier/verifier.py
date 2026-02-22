"""Core verification pipeline: citation lookup → fuzzy search fallback."""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable

from .client import AsyncCourtListenerClient, CourtListenerClient
from .court_map import is_federal_court, lookup_court_id
from .models import (
    CandidateMatch,
    ParsedCitation,
    VerificationResult,
    VerificationStatus,
)
from .name_matcher import CaseNameMatcher
from .parser import parse_citation
from .state_reporter_map import get_states_for_reporter

logger = logging.getLogger(__name__)


class CitationVerifier:
    """Two-step citation verifier using CourtListener APIs."""

    def __init__(self, client: CourtListenerClient | None = None):
        self.client = client or CourtListenerClient()
        self.name_matcher = CaseNameMatcher()

    def verify(
        self,
        citation_text: str,
        parsed: ParsedCitation | None = None,
    ) -> VerificationResult:
        """Verify a citation string through the two-step pipeline.

        Step 1: Try the Citation Lookup API (fast, precise).
        Step 2: Parse and fuzzy-search as fallback.

        Parameters
        ----------
        citation_text : str
            Raw citation string used for the citation-lookup API call
            and stored in ``VerificationResult.input_citation``.
        parsed : ParsedCitation | None
            Pre-parsed citation metadata.  When provided the internal
            ``parse_citation()`` call is skipped, preserving fields
            (court, month, day) that would otherwise be lost in a
            text round-trip.
        """
        citation_text = citation_text.strip()

        # Step 1: Citation Lookup API
        if parsed is None:
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
                        if not self._names_match_citation_lookup(parsed, case_name):
                            return VerificationResult(
                                input_citation=citation_text,
                                status=VerificationStatus.NOT_FOUND,
                                confidence=0.0,
                                diagnostics=[
                                    f"Citation exists but belongs to a different case: "
                                    f'"{case_name}"',
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

        # Step 1b: Try adjacent starting pages (off-by-one is common).
        # Skip for WL citations — WL numbers aren't in the citation lookup API.
        if parsed.volume and parsed.reporter and parsed.page and not parsed.is_westlaw:
            try:
                base_page = int(parsed.page)
                for offset in (-1, 1, -2, 2):
                    alt_page = str(base_page + offset)
                    alt_cite = f"{parsed.volume} {parsed.reporter} {alt_page}"
                    try:
                        lookup_results = self.client.citation_lookup(alt_cite)
                    except Exception:
                        logger.debug(
                            "Adjacent page lookup failed for %s",
                            alt_cite,
                            exc_info=True,
                        )
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
                                    None,
                                    parsed.defendant.lower(),
                                    result_def,
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

        # If no court was parsed but we have a reporter, we can infer possible
        # states from regional/state-specific reporters. This helps with state
        # court citations where eyecite doesn't return a court ID.
        possible_states = []
        if not court_id and parsed.reporter:
            possible_states = get_states_for_reporter(parsed.reporter)
            # For single-state reporters, use as court filter
            if len(possible_states) == 1:
                court_id = possible_states[0]
                logger.debug(
                    f"Inferred court {court_id} from reporter {parsed.reporter}"
                )
            elif possible_states:
                logger.debug(
                    f"Reporter {parsed.reporter} maps to {len(possible_states)} states: "
                    f"{possible_states[:3]}..."
                )

        # Build date range: +/- 1 year from cited year
        filed_after = None
        filed_before = None
        if parsed.year:
            filed_after = f"{parsed.year - 1}-01-01"
            filed_before = f"{parsed.year + 1}-12-31"

        candidates: list[CandidateMatch] = []

        # First search: with court filter (from parsed court or inferred from reporter)
        if parsed.case_name:
            try:
                results = self.client.search_opinions(
                    q=parsed.case_name,
                    court=court_id,
                    filed_after=filed_after,
                    filed_before=filed_before,
                )
                candidates = self._process_results(results, parsed)
            except Exception:
                logger.debug("Opinion search failed", exc_info=True)

        # Step 3: RECAP fallback (docket entries, orders, PACER documents)
        # Note: RECAP dateFiled is the case filing date, not the opinion date,
        # so we skip date filtering here and rely on name/court matching.

        # Skip RECAP for state courts — RECAP is federal PACER data only.
        is_state_court = court_id and not is_federal_court(court_id)

        # Only skip RECAP if we have a credible opinion match (score >= 0.5).
        # Full-text search (q=) can return junk results that score low but block
        # RECAP from firing. By checking score quality, we ensure RECAP runs when
        # opinion search returns only noise.
        has_credible_match = any(c.score >= 0.5 for c in candidates)

        # If docket number is available, try searching by it first (without court
        # filter since docket numbers are court-specific). This handles cases where
        # the case name differs significantly (e.g., "Estate of X" vs "X").
        if not has_credible_match and not is_state_court and parsed.docket_number:
            try:
                results = self.client.search_recap(docket_number=parsed.docket_number)
                # API does fuzzy matching, so filter to actual docket matches
                cited_dn = self._normalize_docket_number(parsed.docket_number)
                results = [
                    r
                    for r in results
                    if self._normalize_docket_number(
                        r.get("docketNumber") or r.get("docket_number") or ""
                    )
                    == cited_dn
                ]
                recap_candidates = self._process_recap_results(results, parsed)
                candidates.extend(recap_candidates)
            except Exception:
                logger.debug("RECAP search by docket number failed", exc_info=True)

        # Fall back to case name search if docket search didn't work
        if not has_credible_match and not is_state_court and parsed.case_name:
            try:
                results = self.client.search_recap(
                    q=parsed.case_name,
                    court=court_id,
                )
                recap_candidates = self._process_recap_results(results, parsed)
                candidates.extend(recap_candidates)
            except Exception:
                logger.debug("RECAP search failed", exc_info=True)

        if not candidates:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                diagnostics=[
                    "No matching cases found in CourtListener opinions or RECAP"
                ],
            )

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        # When a reporter/WL citation was given but couldn't be verified
        # via lookup, require court corroboration before calling it a match.
        # A name-only hit in the wrong court is likely a coincidence.
        has_unverified_cite = bool(
            (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
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

        # When both court and date are missing from the parsed citation,
        # we don't have enough signal to verify reliably — any match is
        # essentially name-only, which is too weak (especially for generic
        # names like "In re Wright"). Return NOT_FOUND with a clear
        # diagnostic so the user knows this is a data issue, not
        # necessarily a fake citation.
        if not parsed.court and not parsed.year:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                candidates=candidates[:5],
                diagnostics=[
                    "Insufficient data to verify: citation text is missing "
                    "both court and date. A match cannot be confirmed with "
                    "name alone. Try adding the court and year parenthetical "
                    "(e.g. '(E.D. Tenn. 2020)') to the citation text.",
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
        self, results: list[dict[str, Any]], parsed: ParsedCitation
    ) -> list[CandidateMatch]:
        """Convert API results to scored CandidateMatch objects."""
        candidates = []
        for r in results:
            case_name = r.get("caseName") or r.get("case_name", "")
            cluster_id = r.get("cluster_id") or r.get("id")
            if cluster_id is None:
                continue
            date_filed = r.get("dateFiled") or r.get("date_filed", "")
            court_id = r.get("court_id") or r.get("court", "")
            url = r.get("absolute_url", "")
            if cluster_id and not url:
                url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
            elif url and not url.startswith("http"):
                url = f"https://www.courtlistener.com{url}"

            score, mismatches = self._score_match(
                parsed, case_name, court_id, date_filed, r
            )
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
        self, results: list[dict[str, Any]], parsed: ParsedCitation
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

            if docket_id is None:
                continue
            if docket_id in seen_dockets:
                continue
            seen_dockets.add(docket_id)

            # Collect documents from search results
            docs = r.get("recap_documents", [])

            # Check if any substantive doc matches the cited date closely
            # enough to skip the more targeted docket-entries query.
            # Only substantive docs (opinions, orders, etc.) qualify —
            # procedural filings like writs or motions shouldn't prevent
            # us from querying for the actual opinion document.
            has_date_match = False
            if parsed.year and docs:
                for doc in docs:
                    entry_date = doc.get("entry_date_filed") or doc.get(
                        "date_filed", ""
                    )
                    try:
                        if not entry_date or int(entry_date[:4]) != parsed.year:
                            continue
                        if parsed.month and len(entry_date) >= 7:
                            if int(entry_date[5:7]) != parsed.month:
                                continue
                        desc = (
                            doc.get("short_description")
                            or doc.get("description")
                            or ""
                        ).lower()
                        is_free = doc.get("is_free_on_pacer") is True
                        if not self._is_substantive_doc(desc) and not is_free:
                            continue
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
        self, docket_id: int, parsed: ParsedCitation, docs: list[dict[str, Any]]
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
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
                        found_entries = True
            except Exception:
                logger.debug(
                    "Docket entries query (exact date) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )
        # Fall back to month ± 1 if exact date found nothing and month is known
        if not found_entries and parsed.month:
            m_start = max(parsed.month - 1, 1)
            m_end = min(parsed.month + 1, 12)
            _, last_day = calendar.monthrange(parsed.year, m_end)
            try:
                entries = self.client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=f"{parsed.year}-{m_start:02d}-01",
                    date_filed_before=f"{parsed.year}-{m_end:02d}-{last_day:02d}",
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
                        found_entries = True
            except Exception:
                logger.debug(
                    "Docket entries query (month range) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )
        # Fall back to year range if narrower queries found nothing
        if not found_entries:
            try:
                entries = self.client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=f"{parsed.year}-01-01",
                    date_filed_before=f"{parsed.year}-12-31",
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
            except Exception:
                logger.debug(
                    "Docket entries query (year range) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )

    def _pick_best_recap_doc(
        self,
        docs: list[dict[str, Any]],
        parsed: ParsedCitation,
        case_name: str,
        court_id: str,
        docket_url: str,
        docket_id: int,
        result: dict[str, Any],
    ) -> CandidateMatch | None:
        """Score all docs, pick the best substantive one, and build a CandidateMatch.

        Prefers opinions/orders over procedural filings. Returns None if no docs.
        """
        if not docs:
            return None

        # Score all docs, preferring opinions/orders over procedural filings.
        # Use both document short_description and entry-level description
        # (the latter is often richer, e.g. "ORDER by District Judge ...").
        scored_docs = []
        for doc in docs:
            entry_date = doc.get("entry_date_filed") or doc.get("date_filed", "")
            score, mismatches = self._score_match(
                parsed,
                case_name,
                court_id,
                entry_date,
                result,
            )
            desc = (
                doc.get("short_description") or doc.get("description") or ""
            )
            entry_desc = doc.get("entry_description") or ""
            full_desc = f"{desc} {entry_desc}".lower()
            is_substantive = self._is_substantive_doc(full_desc)
            is_free = doc.get("is_free_on_pacer") is True
            page_count = doc.get("page_count") or 0
            scored_docs.append((doc, entry_date, score, mismatches, is_substantive, is_free, page_count))

        # Pick best substantive doc; fall back to best overall.
        # is_free_on_pacer=True is a strong signal the doc is an opinion
        # (PACER's Written Opinion Report), so treat it as substantive.
        # Tiebreakers (in order): score, date proximity, opinion likelihood
        # (composite of doc-type keyword + is_free + page count).
        # Date proximity ranks above opinion likelihood because a perfect
        # date match is stronger evidence than the PACER free flag.
        substantive = [d for d in scored_docs if d[4] or d[5]]
        pool = substantive or scored_docs
        best_doc = max(
            pool,
            key=lambda d: (
                d[2],                                    # score
                self._date_proximity(parsed, d[1]),      # date proximity
                self._opinion_likelihood(                 # composite: tier + pages
                    f"{d[0].get('short_description') or d[0].get('description') or ''} "
                    f"{d[0].get('entry_description') or ''}",
                    d[5],   # is_free
                    d[6],   # page_count
                ),
            ),
        )

        doc, entry_date, score, mismatches, _, _, _ = best_doc
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
        result: dict[str, Any],
    ) -> CandidateMatch:
        """Build a docket-level candidate when no documents are available.

        Discounts the score (0.6x) and strips date/citation diagnostics.
        """
        score, mismatches = self._score_match(
            parsed,
            case_name,
            court_id,
            "",
            result,
        )
        score = round(score * 0.6, 4)
        # Remove date/citation diagnostics — they're redundant when
        # we already can't verify a specific document.
        # Keep court/name diagnostics — those are still useful.
        _date_cite_prefixes = (
            "Year ",
            "Date close",
            "Date mismatch",
            "Reporter citation ",
            "WL number ",
            "Citation mismatch",
            "Case name not returned",
        )
        mismatches = [m for m in mismatches if not m.startswith(_date_cite_prefixes)]
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
            match_word = (
                "likely" if status == VerificationStatus.LIKELY_REAL else "possible"
            )
            if diagnostics:
                last = diagnostics[-1]
                if last.endswith("could be verified"):
                    diagnostics[-1] = (
                        last + f". However, we identified a {match_word} match."
                    )
                else:
                    diagnostics[-1] = (
                        last + f", but we identified a {match_word} match."
                    )
            else:
                diagnostics.append(f"We identified a {match_word} match.")
        return diagnostics

    @staticmethod
    def _normalize_docket_number(dn: str) -> str:
        """Normalize a docket number for comparison.

        Strips division prefix ('2:'), judge suffix ('-JCC'), and leading
        zeros from numeric segments so that '17-cv-12676' and
        '2:17-cv-00012676' compare as equal.

        Also expands shorthand prefixes: 'C15-1228' → '15-cv-1228',
        'CR15-1228' → '15-cr-1228'.
        """
        # Strip optional division prefix (e.g. "2:" or "4:")
        dn = re.sub(r"^\d+:", "", dn)
        # Strip trailing judge initials (e.g. "-JCC", "-DCC", "-JHC")
        dn = re.sub(r"-[A-Za-z]{2,4}$", "", dn)
        # Expand shorthand: CR15-1228 → 15-cr-1228, C15-1228 → 15-cv-1228
        dn = re.sub(r"^CR(\d+)", r"\1-cr", dn, flags=re.IGNORECASE)
        dn = re.sub(r"^C(\d+)", r"\1-cv", dn, flags=re.IGNORECASE)
        # Strip leading zeros from numeric segments
        return re.sub(r"(?<!\d)0+(?=\d)", "", dn).lower()

    @staticmethod
    def _is_substantive_doc(desc: str) -> bool:
        """Return True if a RECAP document description looks like an opinion,
        order, judgment, or similar ruling rather than a procedural filing."""
        _NON_SUBSTANTIVE_PATTERNS = (
            "leave to file",
            "leave to seal",
            "proposed order",
            "proposed judgment",
            "proposed ",
            "transcript order form",
            "certificate of service",
            "notice of ",
            "motion to ",
            "motion for ",
        )
        _SUBSTANTIVE_KEYWORDS = (
            "opinion",
            "order",
            "judgment",
            "memorandum",
            "ruling",
            "decision",
            "decree",
            "findings of fact",
            "report and recommendation",
        )
        # Reject docs whose primary type is non-substantive, even if they
        # contain a substantive keyword (e.g. "proposed order", "leave to file")
        if any(desc.startswith(pat) for pat in _NON_SUBSTANTIVE_PATTERNS):
            return False
        return any(kw in desc for kw in _SUBSTANTIVE_KEYWORDS)

    @staticmethod
    def _date_proximity(parsed: ParsedCitation, entry_date: str) -> float:
        """Score date proximity for tiebreaking (higher = closer match).

        When the citation includes month/day, prefers documents filed on or
        near that exact date. Returns 0.0 when no useful comparison can be made.
        """
        if not entry_date or not parsed.year:
            return 0.0
        try:
            result_year = int(entry_date[:4])
            if result_year != parsed.year:
                return 0.0
            if parsed.month and len(entry_date) >= 7:
                result_month = int(entry_date[5:7])
                if parsed.month == result_month:
                    if parsed.day and len(entry_date) >= 10:
                        result_day = int(entry_date[8:10])
                        day_diff = abs(parsed.day - result_day)
                        return max(0.0, 1.0 - day_diff / 31.0)
                    return 0.5  # same month, no day info
                # Different month — closer months rank higher
                month_diff = abs(parsed.month - result_month)
                return max(0.0, 0.3 - month_diff / 12.0)
        except (ValueError, IndexError):
            pass
        return 0.0

    @staticmethod
    def _opinion_likelihood(desc: str, is_free: bool, page_count: int) -> tuple[int, int]:
        """Composite score for how likely a doc is an opinion.

        Returns (tier, page_count) for use as a sort key.
        Tier values:
          3 = opinion/memo/R&R/findings keyword + is_free_on_pacer
          2 = opinion/memo/R&R/findings keyword (no free flag)
              OR order/ruling keyword + is_free_on_pacer
          1 = order/ruling keyword (no free flag)
              OR is_free_on_pacer alone (no keyword match)
          0 = none
        """
        desc = desc.lower()
        is_opinion = any(kw in desc for kw in (
            "opinion", "memorandum", "report and recommendation",
            "report & recommendation", "findings of fact",
        ))
        is_order = any(kw in desc for kw in (
            "order", "ruling", "decision", "decree",
        ))

        if is_opinion:
            tier = 3 if is_free else 2
        elif is_order:
            tier = 2 if is_free else 1
        elif is_free:
            tier = 1
        else:
            tier = 0

        return (tier, min(page_count, 50))

    @staticmethod
    def _extract_surname(party_name: str) -> str:
        """Extract the likely surname from a party name.

        Takes the first word, which in abbreviated legal citations is typically
        the surname: 'Gomez' from 'Gomez', 'Daou' from 'Daou Systems, Inc.'
        Returns empty string if input is empty/None-like.
        """
        if not party_name or party_name.lower() in ("none", ""):
            return ""
        return party_name.split()[0].rstrip(",.")

    _NONDISTINCTIVE_SURNAMES = frozenset({
        "american", "national", "united", "general", "federal",
        "first", "central", "western", "eastern", "northern",
        "southern", "international", "new", "state", "mutual",
        "pacific", "atlantic", "continental", "metropolitan",
        "associated", "consolidated", "independent", "community",
    })

    def _names_match_citation_lookup(self, parsed: ParsedCitation, cl_case_name: str) -> bool:
        """Lenient name check for citation-lookup matches.

        When the Citation Lookup API confirms a reporter citation exists,
        the case identity is already established. This check only rejects
        truly wrong names (e.g., fabricated name + real citation number).

        Uses surname containment rather than SequenceMatcher because
        briefs commonly abbreviate: 'Fink v. Gomez' for
        'David M. Fink v. James H. Gomez, Director, Diana Carloni Nourse'.
        """
        # If we couldn't parse a case name, trust the citation lookup
        if not parsed.case_name:
            return True
        if not parsed.plaintiff or parsed.plaintiff.lower() == "none":
            # eyecite failed to parse plaintiff — don't reject on broken parse
            return True

        cl_lower = cl_case_name.lower()

        # For common-prefix cases (United States v. X, State v. X), compare defendants
        # since the plaintiff is not distinctive
        if parsed.defendant:
            defendant_lower = parsed.defendant.lower()
            # Check if this is a common-prefix case
            common_prefixes = ("united states", "state of", "commonwealth", "people")
            if any(parsed.case_name.lower().startswith(prefix) for prefix in common_prefixes):
                # For common-prefix cases, the defendant must match
                defendant_surname = self._extract_surname(parsed.defendant)
                if defendant_surname:
                    # Defendant surname must appear in CL case name
                    return defendant_surname.lower() in cl_lower
                # If we can't extract defendant surname, fall back to full match check
                return defendant_lower in cl_lower

        # For regular cases, extract surnames from cited parties
        cited_surnames = []
        plaintiff_surname = self._extract_surname(parsed.plaintiff)
        if plaintiff_surname:
            cited_surnames.append(plaintiff_surname.lower())
        defendant_surname = self._extract_surname(parsed.defendant) if parsed.defendant else ""
        if defendant_surname:
            cited_surnames.append(defendant_surname.lower())

        if not cited_surnames:
            return True  # nothing to check against

        # Filter out common generic first-words (e.g. "American", "National")
        # that cause false matches against unrelated organization names
        distinctive = [s for s in cited_surnames if s not in self._NONDISTINCTIVE_SURNAMES]
        if not distinctive:
            return True  # all words too generic, trust citation lookup

        # At least one distinctive surname must appear in the CL case name
        return any(name in cl_lower for name in distinctive)

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
        result: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """Score how well a search result matches the parsed citation.

        Base weights: case name (50%), court (20%), date (20%),
        docket number (5%), reporter/WL citation (5%).

        When parsed data is missing for a component (e.g. no court in the
        citation text), we can't evaluate that component. Rather than
        penalizing the match with 0 points, we redistribute the weight
        to the components we CAN evaluate. This prevents citations like
        "Moore v. Hillman, No. 4:06-CV-43, 2006 WL 1313880" (no court
        parenthetical) from being capped at 0.80 even when everything
        else matches perfectly.

        Returns (score, list of mismatch descriptions).
        """
        mismatches: list[str] = []

        # --- Determine which components are evaluable ---
        can_eval_court = bool(parsed.court)
        can_eval_date = bool(parsed.year)

        # Base weights
        w_name = 0.50
        w_court = 0.20
        w_date = 0.20
        w_docket = 0.05
        w_cite = 0.05

        # Redistribute weight from non-evaluable components proportionally
        # to the evaluable ones. Name, docket, and citation are always
        # evaluable (name is always present for us to reach this point;
        # docket/citation are scored only when parsed data exists, but
        # their weight is small enough that we keep it fixed).
        redistributed = 0.0
        if not can_eval_court:
            redistributed += w_court
            w_court = 0.0
        if not can_eval_date:
            redistributed += w_date
            w_date = 0.0

        if redistributed > 0:
            # Distribute to name, docket, and citation proportionally
            base_sum = w_name + w_docket + w_cite
            if base_sum > 0:
                w_name += redistributed * (w_name / base_sum)
                w_docket += redistributed * (w_docket / base_sum)
                w_cite += redistributed * (w_cite / base_sum)

        # --- Warn when key verification signals are missing ---
        missing = []
        if not can_eval_court:
            missing.append("court")
        if not can_eval_date:
            missing.append("date")
        if missing:
            mismatches.append(
                f"Low confidence: {' and '.join(missing)} not available "
                f"in citation text"
            )

        # --- Score each component ---
        score = 0.0

        # Case name similarity - using multi-factor matcher
        if parsed.case_name and result_case_name:
            name_sim = self.name_matcher.calculate_similarity(
                parsed.case_name,
                result_case_name
            )
            score += w_name * name_sim

            if name_sim < 0.6:
                mismatches.append(
                    f'Name mismatch: cited "{parsed.case_name}" '
                    f'vs found "{result_case_name}"'
                )
            elif name_sim < 0.85:
                mismatches.append(
                    f'Name differs: cited "{parsed.case_name}" '
                    f'~ found "{result_case_name}" ({name_sim:.0%} similar)'
                )
        elif parsed.case_name:
            mismatches.append("Case name not returned by API")

        # Court match
        if can_eval_court and result_court:
            expected_court = lookup_court_id(parsed.court)
            if expected_court and expected_court == result_court:
                score += w_court
            elif expected_court:
                mismatches.append(
                    f"Court mismatch: cited {parsed.court} ({expected_court}) "
                    f"vs found {result_court}"
                )
            elif parsed.court.lower() == result_court.lower():
                # Direct match on raw court string (e.g. state courts)
                score += w_court
            else:
                mismatches.append(
                    f"Court mismatch: cited {parsed.court} vs found {result_court}"
                )
        elif parsed.court:
            mismatches.append(f"Court {parsed.court} could not be verified")

        # Date match — with month/day granularity when available
        if can_eval_date and result_date:
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
                                    score += w_date  # exact date
                                else:
                                    score += w_date * 0.9  # same month
                            else:
                                score += w_date * 0.9  # same month, no day to compare
                        else:
                            score += w_date * 0.75  # same year, wrong month
                            cited_date = f"{parsed.year}-{parsed.month:02d}"
                            if parsed.day:
                                cited_date += f"-{parsed.day:02d}"
                            mismatches.append(
                                f"Date close: cited {cited_date} vs filed {result_date}"
                            )
                    else:
                        score += w_date  # same year, no month info to compare
                elif year_diff == 1:
                    score += w_date * 0.5
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

        # Docket number match
        if parsed.docket_number:
            result_docket = (
                result.get("docketNumber") or result.get("docket_number") or ""
            )
            if result_docket:
                cited_dn = self._normalize_docket_number(parsed.docket_number)
                found_dn = self._normalize_docket_number(result_docket)
                if cited_dn == found_dn:
                    score += w_docket
                else:
                    mismatches.append(
                        f"Docket mismatch: cited {parsed.docket_number} "
                        f"vs found {result_docket}"
                    )

        # Reporter/WL citation match
        result_citation = result.get("citation", [])
        if isinstance(result_citation, list):
            result_citation = " ".join(str(c) for c in result_citation)
        elif not isinstance(result_citation, str):
            result_citation = str(result_citation)

        if parsed.volume and parsed.page and parsed.reporter:
            cite_str = f"{parsed.volume} {parsed.reporter} {parsed.page}"
            # Normalize spacing around periods for comparison:
            # "Cal. Rptr. 3d" should match "Cal.Rptr.3d"
            cite_normalized = re.sub(r"\.\s+", ".", cite_str.lower())
            result_normalized = re.sub(r"\.\s+", ".", result_citation.lower())
            if (cite_str.lower() in result_citation.lower()
                    or cite_normalized in result_normalized):
                score += w_cite
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
                score += w_cite
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

    # ------------------------------------------------------------------
    # Async verification
    # ------------------------------------------------------------------

    async def verify_async(
        self,
        async_client: AsyncCourtListenerClient,
        citation_text: str,
        parsed: ParsedCitation | None = None,
    ) -> VerificationResult:
        """Async version of verify(). Requires an AsyncCourtListenerClient.

        Uses the same scoring/matching logic as the sync version.
        """
        citation_text = citation_text.strip()

        if parsed is None:
            parsed = parse_citation(citation_text)

        # Step 1: Citation Lookup API
        try:
            lookup_results = await async_client.citation_lookup(citation_text)
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

                    if parsed.case_name and case_name:
                        if not self._names_match_citation_lookup(parsed, case_name):
                            return VerificationResult(
                                input_citation=citation_text,
                                status=VerificationStatus.NOT_FOUND,
                                confidence=0.0,
                                diagnostics=[
                                    f"Citation exists but belongs to a different case: "
                                    f'"{case_name}"',
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
            logger.debug("Citation lookup failed", exc_info=True)

        # Step 1b: Adjacent starting pages (skip for WL citations)
        if parsed.volume and parsed.reporter and parsed.page and not parsed.is_westlaw:
            try:
                base_page = int(parsed.page)
                for offset in (-1, 1, -2, 2):
                    alt_page = str(base_page + offset)
                    alt_cite = f"{parsed.volume} {parsed.reporter} {alt_page}"
                    try:
                        lookup_results = await async_client.citation_lookup(alt_cite)
                    except Exception:
                        logger.debug(
                            "Adjacent page lookup failed for %s",
                            alt_cite,
                            exc_info=True,
                        )
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
                            result_lower = case_name.lower()
                            result_def = ""
                            if " v. " in result_lower:
                                result_def = result_lower.split(" v. ", 1)[1].strip()
                            elif " v " in result_lower:
                                result_def = result_lower.split(" v ", 1)[1].strip()
                            if parsed.defendant and result_def:
                                def_sim = SequenceMatcher(
                                    None,
                                    parsed.defendant.lower(),
                                    result_def,
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
        return await self._search_fallback_async(async_client, citation_text, parsed)

    async def _search_fallback_async(
        self,
        async_client: AsyncCourtListenerClient,
        citation_text: str,
        parsed: ParsedCitation,
    ) -> VerificationResult:
        """Async version of _search_fallback()."""
        court_id = lookup_court_id(parsed.court) if parsed.court else None

        possible_states = []
        if not court_id and parsed.reporter:
            possible_states = get_states_for_reporter(parsed.reporter)
            if len(possible_states) == 1:
                court_id = possible_states[0]
                logger.debug(
                    f"Inferred court {court_id} from reporter {parsed.reporter}"
                )

        filed_after = None
        filed_before = None
        if parsed.year:
            filed_after = f"{parsed.year - 1}-01-01"
            filed_before = f"{parsed.year + 1}-12-31"

        candidates: list[CandidateMatch] = []

        if parsed.case_name:
            try:
                results = await async_client.search_opinions(
                    q=parsed.case_name,
                    court=court_id,
                    filed_after=filed_after,
                    filed_before=filed_before,
                )
                candidates = self._process_results(results, parsed)
            except Exception:
                logger.debug("Opinion search failed", exc_info=True)

        # Step 3: RECAP fallback
        is_state_court = court_id and not is_federal_court(court_id)
        has_credible_match = any(c.score >= 0.5 for c in candidates)

        if not has_credible_match and not is_state_court and parsed.docket_number:
            try:
                results = await async_client.search_recap(
                    docket_number=parsed.docket_number
                )
                cited_dn = self._normalize_docket_number(parsed.docket_number)
                results = [
                    r
                    for r in results
                    if self._normalize_docket_number(
                        r.get("docketNumber") or r.get("docket_number") or ""
                    )
                    == cited_dn
                ]
                recap_candidates = await self._process_recap_results_async(
                    async_client, results, parsed
                )
                candidates.extend(recap_candidates)
            except Exception:
                logger.debug("RECAP search by docket number failed", exc_info=True)

        if not has_credible_match and not is_state_court and parsed.case_name:
            try:
                results = await async_client.search_recap(
                    q=parsed.case_name,
                    court=court_id,
                )
                recap_candidates = await self._process_recap_results_async(
                    async_client, results, parsed
                )
                candidates.extend(recap_candidates)
            except Exception:
                logger.debug("RECAP search failed", exc_info=True)

        if not candidates:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                diagnostics=[
                    "No matching cases found in CourtListener opinions or RECAP"
                ],
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        has_unverified_cite = bool(
            (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
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

        if not parsed.court and not parsed.year:
            return VerificationResult(
                input_citation=citation_text,
                status=VerificationStatus.NOT_FOUND,
                confidence=0.0,
                candidates=candidates[:5],
                diagnostics=[
                    "Insufficient data to verify: citation text is missing "
                    "both court and date. A match cannot be confirmed with "
                    "name alone. Try adding the court and year parenthetical "
                    "(e.g. '(E.D. Tenn. 2020)') to the citation text.",
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

    async def _process_recap_results_async(
        self,
        async_client: AsyncCourtListenerClient,
        results: list[dict[str, Any]],
        parsed: ParsedCitation,
    ) -> list[CandidateMatch]:
        """Async version of _process_recap_results()."""
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

            if docket_id is None:
                continue
            if docket_id in seen_dockets:
                continue
            seen_dockets.add(docket_id)

            docs = r.get("recap_documents", [])

            has_date_match = False
            if parsed.year and docs:
                for doc in docs:
                    entry_date = doc.get("entry_date_filed") or doc.get(
                        "date_filed", ""
                    )
                    try:
                        if not entry_date or int(entry_date[:4]) != parsed.year:
                            continue
                        if parsed.month and len(entry_date) >= 7:
                            if int(entry_date[5:7]) != parsed.month:
                                continue
                        desc = (
                            doc.get("short_description")
                            or doc.get("description")
                            or ""
                        ).lower()
                        is_free = doc.get("is_free_on_pacer") is True
                        if not self._is_substantive_doc(desc) and not is_free:
                            continue
                        has_date_match = True
                        break
                    except (ValueError, IndexError):
                        pass

            if not has_date_match and parsed.year and docket_id:
                await self._fetch_docs_for_docket_async(
                    async_client, docket_id, parsed, docs
                )

            if docs:
                candidate = self._pick_best_recap_doc(
                    docs, parsed, case_name, court_id, docket_url, docket_id, r
                )
                if candidate:
                    candidates.append(candidate)
            else:
                candidate = self._build_docket_only_candidate(
                    parsed, case_name, court_id, docket_url, docket_id, r
                )
                candidates.append(candidate)
        return candidates

    async def _fetch_docs_for_docket_async(
        self,
        async_client: AsyncCourtListenerClient,
        docket_id: int,
        parsed: ParsedCitation,
        docs: list[dict[str, Any]],
    ) -> None:
        """Async version of _fetch_docs_for_docket()."""
        found_entries = False
        if parsed.month and parsed.day:
            exact = f"{parsed.year}-{parsed.month:02d}-{parsed.day:02d}"
            try:
                entries = await async_client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=exact,
                    date_filed_before=exact,
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
                        found_entries = True
            except Exception:
                logger.debug(
                    "Docket entries query (exact date) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )
        # Fall back to month ± 1 if exact date found nothing and month is known
        if not found_entries and parsed.month:
            m_start = max(parsed.month - 1, 1)
            m_end = min(parsed.month + 1, 12)
            _, last_day = calendar.monthrange(parsed.year, m_end)
            try:
                entries = await async_client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=f"{parsed.year}-{m_start:02d}-01",
                    date_filed_before=f"{parsed.year}-{m_end:02d}-{last_day:02d}",
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
                        found_entries = True
            except Exception:
                logger.debug(
                    "Docket entries query (month range) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )
        # Fall back to year range if narrower queries found nothing
        if not found_entries:
            try:
                entries = await async_client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=f"{parsed.year}-01-01",
                    date_filed_before=f"{parsed.year}-12-31",
                )
                for entry in entries:
                    entry_date = entry.get("date_filed", "")
                    entry_desc = entry.get("description", "")
                    for doc in entry.get("recap_documents", []):
                        doc["entry_date_filed"] = entry_date
                        doc["entry_description"] = entry_desc
                        docs.append(doc)
            except Exception:
                logger.debug(
                    "Docket entries query (year range) failed for docket %s",
                    docket_id,
                    exc_info=True,
                )

    async def verify_batch(
        self,
        citations: list[str],
        parsed_citations: list[ParsedCitation | None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[VerificationResult]:
        """Verify multiple citations concurrently.

        Creates an async client, runs all citations through verify_async
        with concurrency limited by the client's semaphore.

        Parameters
        ----------
        citations : list[str]
            Citation strings to verify.
        parsed_citations : list[ParsedCitation | None] | None
            Optional pre-parsed citations (same length as *citations*).
            When provided, skips internal parsing for non-None entries.
        progress_callback : callable, optional
            Called as progress_callback(completed, total) after each citation.

        Returns results in the same order as the input citations.
        """
        if parsed_citations is None:
            parsed_citations = [None] * len(citations)

        completed = 0

        async def _verify_one(
            client: AsyncCourtListenerClient,
            cite: str,
            parsed: ParsedCitation | None,
        ) -> VerificationResult:
            nonlocal completed
            result = await self.verify_async(client, cite, parsed=parsed)
            completed += 1
            if progress_callback:
                progress_callback(completed, len(citations))
            return result

        async with AsyncCourtListenerClient() as client:
            tasks = [
                _verify_one(client, cite, parsed)
                for cite, parsed in zip(citations, parsed_citations)
            ]
            results = await asyncio.gather(*tasks)

        return list(results)
