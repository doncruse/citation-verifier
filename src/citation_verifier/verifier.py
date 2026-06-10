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
    Diagnostic,
    FinalIds,
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
from .name_matcher import CaseNameMatcher
from .parser import parse_citation
from .resolution_path import ResolutionPathBuilder, _StageToken  # _StageToken imported for type hints only
from .state_reporter_map import get_states_for_reporter

logger = logging.getLogger(__name__)


# Issue #7: tokens that should NOT count as distinctive when checking
# name overlap on opinion-search fallback candidates. These show up so
# often that they create false positives via ES token recall alone.
_NAME_TOKEN_STOPLIST = frozenset({
    # Reporter / litigation boilerplate
    "litig", "liability", "antitrust",
    # Corporate forms
    "corp", "company", "holdings",
    "communications", "industries", "international",
    # Generic descriptors
    "consumer", "health", "products", "american", "capital",
    "bank", "pharmacy", "services", "systems", "group",
    # Government / agency
    "cftc", "united", "states", "commission",
    "department", "secretary",
})

# Score floor at which an opinion_search / recap_*_search candidate
# claims resolution. Below this, the stage records `no_match` and the
# fallback ladder continues. Carried forward unchanged from pre-Phase-3
# behavior per design v2 §8 "Per-stage confidence thresholds" decision
# (2026-05-20).
_VERIFIED_SCORE_THRESHOLD = 0.40

# Lever 2 (Tier 1 Step 2): multiplier applied to the case-name similarity
# when a candidate matches only ONE cited party and the other cited party is
# absent (surname-coincidence inflation, e.g. Thompson v. Best ->
# Thompson v. Thompson). Tuned (2026-06-09) so the two measured opinion-search
# false positives drop below _VERIFIED_SCORE_THRESHOLD while retaining enough
# name signal that a real opinion whose CL *display name* lists a different
# party (cl_display_name_data_bug) still resolves on its corroborating
# court/date/cite. See docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
_PARTY_MISMATCH_NAME_FACTOR = 0.25


def _name_tokens(name: str) -> set[str]:
    """Lowercased word tokens of length >=4, with punctuation stripped
    and stoplist tokens removed. Used for the fallback name-overlap gate."""
    if not name:
        return set()
    raw = re.findall(r"[a-z0-9]+", name.lower())
    return {t for t in raw if len(t) >= 4 and t not in _NAME_TOKEN_STOPLIST}


class CitationVerifier:
    """Two-step citation verifier using CourtListener APIs."""

    def __init__(self, client: CourtListenerClient | None = None):
        self.client = client or CourtListenerClient()
        self.name_matcher = CaseNameMatcher()

    @staticmethod
    def _promote_to_incomplete_if_only_errored(
        status: Status,
        resolution_path: list[ResolutionPathEntry],
    ) -> Status:
        """Design §2.8 internal gate: API errors must not silently degrade
        to NOT_FOUND. If any stage entry has verdict=errored AND no entry
        has verdict in (resolved, partial), promote to VERIFICATION_INCOMPLETE.

        A resolved or partial stage trumps later errors — the verification
        question was answered at that stage, and a downstream error during
        a refinement / fallback is not a verifier-integrity failure.

        Pre-promoted statuses (anything other than NOT_FOUND) are not
        re-evaluated: an already-resolved status carries its own truth.
        """
        if status != Status.NOT_FOUND:
            return status
        has_errored = any(
            e.verdict == StageVerdict.errored for e in resolution_path
        )
        has_resolved = any(
            e.verdict in (StageVerdict.resolved, StageVerdict.partial)
            for e in resolution_path
        )
        if has_errored and not has_resolved:
            return Status.VERIFICATION_INCOMPLETE
        return status

    @staticmethod
    def _promote_to_insufficient_data_if_no_anchors(
        status: Status,
        parsed: ParsedCitation | None,
    ) -> Status:
        """Promote NOT_FOUND to INSUFFICIENT_DATA when the parsed citation
        lacks both court and year. Distinguishes "we couldn't tell because
        the input was too weak" from "we tried and found nothing convincing".

        Only NOT_FOUND is promoted — other statuses each carry more
        actionable signal than INSUFFICIENT_DATA would: WRONG_CASE has a
        cluster URL, INCOMPLETE means rerun, VERIFIED resolved despite the
        weak metadata. Runs AFTER the INCOMPLETE promotion so the
        infrastructure-failure signal wins when both apply.

        See scratch/TODO.md (Priority 1: INSUFFICIENT_DATA short-circuit)
        and the matching _search_fallback short-circuit at the same
        court+year-missing condition.
        """
        if status != Status.NOT_FOUND:
            return status
        if parsed is None:
            return status
        if parsed.court is None and parsed.year is None:
            return Status.INSUFFICIENT_DATA
        return status

    # ------------------------------------------------------------------
    # Shared helpers (pure logic, no I/O)
    # ------------------------------------------------------------------

    def _finalize_result(
        self,
        builder: ResolutionPathBuilder,
        *,
        citation_text: str,
        parsed: ParsedCitation | None,
        status: Status,
        cluster_id: int | None = None,
        docket_id: int | None = None,
        recap_document_id: int | None = None,
        absolute_url: str | None = None,
        text_source: TextSource | None = None,
        warnings: list[Warning] | None = None,
    ) -> VerificationResult:
        """Terminal helper: wrap the accumulated resolution_path into a result.

        Phase 2 of the v0.3 refactor. Replaces Phase 1's _build_result.
        The caller has already recorded each stage attempt via
        builder.stage(...) context managers; this helper just collects the
        entries, packs the FinalIds, and returns the VerificationResult.
        """
        path = builder.entries()
        # Phase 4 Task 2: design §2.8 internal gate. Promote NOT_FOUND to
        # VERIFICATION_INCOMPLETE when only errored stages exist.
        status = self._promote_to_incomplete_if_only_errored(status, path)
        # Promote NOT_FOUND to INSUFFICIENT_DATA when parsed.court and
        # parsed.year are both None — input was too weak to anchor the
        # fallback search on. Runs after the INCOMPLETE promotion so the
        # infrastructure-failure signal wins when both conditions apply.
        status = self._promote_to_insufficient_data_if_no_anchors(status, parsed)
        # When promoting to INCOMPLETE or INSUFFICIENT_DATA, null out any
        # partial IDs the caller may have set — neither is an authoritative
        # answer, and consumers must not mistake either for partial
        # verification (design §2.8).
        if status in (Status.VERIFICATION_INCOMPLETE, Status.INSUFFICIENT_DATA):
            cluster_id = None
            docket_id = None
            recap_document_id = None
            absolute_url = None
            text_source = None
        return VerificationResult(
            citation_as_written=citation_text,
            parsed_citation=parsed,
            status=status,
            final_ids=FinalIds(
                cluster_id=cluster_id,
                opinion_id=None,
                docket_id=docket_id,
                recap_document_id=recap_document_id,
                absolute_url=absolute_url,
                text_source=text_source,
            ),
            resolution_path=path,
            warnings=warnings or [],
            gates_failed=[],
            timing={},
            cache_hit=False,
        )

    def _process_citation_lookup_hit(
        self,
        builder: ResolutionPathBuilder,
        token: _StageToken,
        citation_text: str,
        parsed: ParsedCitation,
        cluster: dict[str, Any],
        clusters_returned: int,
    ) -> dict[str, Any]:
        """Process a single cluster from the Citation Lookup API.

        The caller has already opened a builder.stage() block and yielded
        the token; this helper sets the token's resolved-verdict state and
        returns a dict of finalize kwargs (cluster_id, absolute_url,
        text_source, warnings) so the caller can invoke ``_finalize_result``
        *after* the ``with`` block exits (the path entry is appended in the
        block's ``finally``).
        """
        case_name = cluster.get("case_name", "")
        cluster_id = cluster.get("id")
        url = cluster.get("absolute_url", "")
        if url and not url.startswith("http"):
            url = f"https://www.courtlistener.com{url}"
        elif cluster_id and not url:
            url = f"https://www.courtlistener.com/opinion/{cluster_id}/"

        summary = {
            "matched_cluster_id": cluster_id,
            "matched_case_name": case_name,
            "clusters_returned": clusters_returned,
        }
        # Path A of Phase 1 retro Q5 (CSV syllabus column): surface syllabus
        # + nature_of_suit metadata when CL returns them, so consumers
        # (notably brief_pipeline / the verify-brief skill's topic-mismatch
        # triage) can use them without re-querying the cluster endpoint.
        # Keys omitted when absent so empty strings don't pollute the summary.
        if cluster.get("syllabus"):
            summary["syllabus"] = cluster["syllabus"]
        if cluster.get("nature_of_suit"):
            summary["nature_of_suit"] = cluster["nature_of_suit"]

        # Name-mismatch case: citation resolves but caption disagrees.
        # Phase 3 (Task 5): the caller runs caption_investigation to classify
        # the mismatch (formatting noise / data bug / wrong case / duplicate
        # cluster / wrong page). Token confidence stays at 1.0 because the
        # citation itself resolved cleanly; the investigation may downgrade
        # the status to WRONG_CASE but it should not pre-decide that here.
        if parsed.case_name and case_name and not self._names_match_citation_lookup(parsed, case_name):
            token.resolved(
                confidence=1.0,
                raw_response_summary=summary,
                notes="name mismatch flagged for caption_investigation",
            )
            return {
                "cluster_id": cluster_id,
                "absolute_url": url,
                "text_source": TextSource.opinion_plain_text if cluster_id else None,
                "warnings": None,
                "needs_caption_investigation": True,
                "_cluster_for_investigation": cluster,
            }

        # Partial-verification check (design §2.2): primary reporter cited by
        # the brief is silently absent from CL's citation index, only the
        # parallel resolved. Status: VERIFIED_PARTIAL + silent_partial_verification.
        if parsed.case_name and case_name and self._names_match_citation_lookup(parsed, case_name):
            primary_present = self._cited_primary_reporter_in_cluster(parsed, cluster)
            if not primary_present:
                token.resolved(confidence=1.0, raw_response_summary=summary, notes="Primary reporter not in CL citation index")
                return {
                    "cluster_id": cluster_id,
                    "absolute_url": url,
                    "text_source": TextSource.opinion_plain_text if cluster_id else None,
                    "warnings": [Warning(
                        category=WarningCategory.silent_partial_verification,
                        message=(
                            f"Primary reporter '{parsed.volume} {parsed.reporter} {parsed.page}' "
                            f"is not in CourtListener's citation index. The parallel cite "
                            f"resolved but the primary reporter is unconfirmed."
                        ),
                        details={
                            "cited_primary": f"{parsed.volume} {parsed.reporter} {parsed.page}",
                            "cluster_citations": cluster.get("citations") or [],
                        },
                    )],
                    "status_override": Status.VERIFIED_PARTIAL,
                }

        token.resolved(confidence=1.0, raw_response_summary=summary)
        return {
            "cluster_id": cluster_id,
            "absolute_url": url,
            "text_source": TextSource.opinion_plain_text if cluster_id else None,
            "warnings": None,
        }

    def _build_search_params(
        self, parsed: ParsedCitation
    ) -> tuple[str | None, str | None, str | None]:
        """Infer court ID and build date range for fuzzy search.

        Returns (court_id, filed_after, filed_before).
        """
        court_id = lookup_court_id(parsed.court) if parsed.court else None

        # If no court was parsed but we have a reporter, we can infer possible
        # states from regional/state-specific reporters.
        if not court_id and parsed.reporter:
            possible_states = get_states_for_reporter(parsed.reporter)
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

        return court_id, filed_after, filed_before

    def _build_fallback_result(
        self,
        builder: ResolutionPathBuilder,
        citation_text: str,
        parsed: ParsedCitation,
        candidates: list[CandidateMatch],
        court_id: str | None,
        _doc_detail_fn: Callable[[int], dict[str, Any] | None] | None = None,
    ) -> VerificationResult:
        """Pick the winning candidate across pooled stages and finalize.

        Per-stage path entries were already appended in ``_search_fallback``.
        This helper does NOT append any new entries; it only chooses
        ``final_ids`` and ``status`` from the pooled candidates.

        Parameters
        ----------
        _doc_detail_fn : callable or None
            Optional callable ``(doc_id: int) -> dict | None`` used to fetch
            /recap-documents/{id}/ when the search response omits
            ``is_free_on_pacer`` (the field is absent from the RECAP search
            index and only populated on the detail endpoint). When the
            keyword/date gate path (b) fails but a candidate doc_id exists
            and ``is_free_on_pacer`` is not yet confirmed True, this callable
            is invoked to get the real ``is_free_on_pacer`` (and ``page_count``
            when also missing) before re-applying the score gate (path c). A
            failed fetch (callable returns None or raises) is treated as a
            non-fatal refinement failure — the result falls through to
            DOCKET_ONLY. Async callers set this to None and use
            ``_build_fallback_result_async`` instead.
        """
        if not candidates:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        # When a reporter/WL citation was given but couldn't be verified
        # via lookup, require court corroboration before calling it a match.
        has_unverified_cite = bool(
            (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
        )
        if has_unverified_cite and court_id and best.court_id != court_id:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        # When both court and date are missing from the parsed citation,
        # we don't have enough signal to verify reliably.
        if not parsed.court and not parsed.year:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        # Per Phase 1 mapping (design §3): LIKELY_REAL and POSSIBLE_MATCH
        # collapse into VERIFIED; the distinguishing number lives on the
        # resolution_path entry. NOT_FOUND stays NOT_FOUND. Existing
        # behavior (preserved): even on NOT_FOUND, propagate the best
        # candidate's cluster_id/docket_id/url to final_ids so callers can
        # link to the closest match.
        status = Status.VERIFIED if best.score >= _VERIFIED_SCORE_THRESHOLD else Status.NOT_FOUND

        # RECAP-fallback hits (docket-only or specific RECAP doc) have a
        # docket_id but no cluster_id. Use that as the discriminator.
        is_recap_match = best.docket_id is not None and best.cluster_id is None
        text_source: TextSource | None
        recap_document_id: int | None = None

        if is_recap_match and status == Status.VERIFIED:
            # Phase 3: strict VIA_RECAP gate (design v2 §2.2, maintainer Q1).
            # Phase 4 Task 4: also pass page_count + is_free_on_pacer for Q2 score gate.
            desc = best.description or ""
            gate_passed = best.recap_document_id and self._recap_doc_is_cited_opinion(
                parsed, desc, best.date_filed,
                page_count=best.page_count,
                is_free_on_pacer=best.is_free_on_pacer,
            )

            # Phase 4 Task 4 doc-detail refinement: search_recap may return
            # docs where is_free_on_pacer=None (field absent from the search
            # index; only populated on /recap-documents/{id}/ detail endpoint).
            # When the gate fails AND is_free_on_pacer is not True (i.e. the
            # search did not confirm it), fetch the doc detail to get the real
            # is_free_on_pacer (and page_count when also missing) before
            # deciding whether path (c) can fire.
            # Condition: gate failed, a candidate doc id exists, is_free not
            # already confirmed True (so we might gain information by fetching).
            if not gate_passed and best.recap_document_id and not best.is_free_on_pacer and _doc_detail_fn:
                try:
                    detail = _doc_detail_fn(best.recap_document_id)
                    if detail:
                        real_page_count = int(detail.get("page_count") or 0)
                        real_is_free = bool(detail.get("is_free_on_pacer"))
                        if real_page_count != best.page_count or real_is_free != best.is_free_on_pacer:
                            best.page_count = real_page_count
                            best.is_free_on_pacer = real_is_free
                            gate_passed = self._recap_doc_is_cited_opinion(
                                parsed, desc, best.date_filed,
                                page_count=best.page_count,
                                is_free_on_pacer=best.is_free_on_pacer,
                            )
                except Exception:
                    logger.debug(
                        "doc-detail fetch for recap_document_id=%s failed; "
                        "leaving DOCKET_ONLY",
                        best.recap_document_id,
                        exc_info=True,
                    )

            if gate_passed:
                status = Status.VERIFIED_VIA_RECAP
                text_source = TextSource.recap_document
                recap_document_id = best.recap_document_id
            else:
                status = Status.VERIFIED_DOCKET_ONLY
                text_source = None
        elif status == Status.VERIFIED and best.cluster_id:
            text_source = TextSource.opinion_plain_text
        else:
            text_source = None

        return self._finalize_result(
            builder,
            citation_text=citation_text,
            parsed=parsed,
            status=status,
            cluster_id=best.cluster_id,
            docket_id=best.docket_id,
            absolute_url=best.url,
            text_source=text_source,
            recap_document_id=recap_document_id,
        )

    async def _build_fallback_result_async(
        self,
        builder: ResolutionPathBuilder,
        citation_text: str,
        parsed: ParsedCitation,
        candidates: list[CandidateMatch],
        court_id: str | None,
        async_client: AsyncCourtListenerClient,
    ) -> VerificationResult:
        """Async mirror of ``_build_fallback_result``.

        Identical logic except the doc-detail fetch awaits
        ``async_client.get_recap_document_metadata()``. Called from
        ``_search_fallback_async`` and ``verify_batch`` when a RECAP
        candidate needs refinement.
        """
        if not candidates:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        has_unverified_cite = bool(
            (parsed.volume and parsed.reporter and parsed.page) or parsed.wl_number
        )
        if has_unverified_cite and court_id and best.court_id != court_id:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        if not parsed.court and not parsed.year:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        status = Status.VERIFIED if best.score >= _VERIFIED_SCORE_THRESHOLD else Status.NOT_FOUND

        is_recap_match = best.docket_id is not None and best.cluster_id is None
        text_source: TextSource | None
        recap_document_id: int | None = None

        if is_recap_match and status == Status.VERIFIED:
            desc = best.description or ""
            gate_passed = best.recap_document_id and self._recap_doc_is_cited_opinion(
                parsed, desc, best.date_filed,
                page_count=best.page_count,
                is_free_on_pacer=best.is_free_on_pacer,
            )

            # Async doc-detail refinement (same logic as sync path).
            if not gate_passed and best.recap_document_id and not best.is_free_on_pacer:
                try:
                    detail = await async_client.get_recap_document_metadata(
                        best.recap_document_id
                    )
                    if detail:
                        real_page_count = int(detail.get("page_count") or 0)
                        real_is_free = bool(detail.get("is_free_on_pacer"))
                        if real_page_count != best.page_count or real_is_free != best.is_free_on_pacer:
                            best.page_count = real_page_count
                            best.is_free_on_pacer = real_is_free
                            gate_passed = self._recap_doc_is_cited_opinion(
                                parsed, desc, best.date_filed,
                                page_count=best.page_count,
                                is_free_on_pacer=best.is_free_on_pacer,
                            )
                except Exception:
                    logger.debug(
                        "async doc-detail fetch for recap_document_id=%s failed; "
                        "leaving DOCKET_ONLY",
                        best.recap_document_id,
                        exc_info=True,
                    )

            if gate_passed:
                status = Status.VERIFIED_VIA_RECAP
                text_source = TextSource.recap_document
                recap_document_id = best.recap_document_id
            else:
                status = Status.VERIFIED_DOCKET_ONLY
                text_source = None
        elif status == Status.VERIFIED and best.cluster_id:
            text_source = TextSource.opinion_plain_text
        else:
            text_source = None

        return self._finalize_result(
            builder,
            citation_text=citation_text,
            parsed=parsed,
            status=status,
            cluster_id=best.cluster_id,
            docket_id=best.docket_id,
            absolute_url=best.url,
            text_source=text_source,
            recap_document_id=recap_document_id,
        )

    def _docket_date_ranges(
        self, parsed: ParsedCitation
    ) -> list[tuple[str, str, str]]:
        """Return progressive date ranges for docket-entry queries.

        Returns list of (label, after, before) tuples for the 3-step
        fallback: exact date -> month +/- 1 -> full year.
        """
        ranges: list[tuple[str, str, str]] = []
        if parsed.month and parsed.day:
            exact = f"{parsed.year}-{parsed.month:02d}-{parsed.day:02d}"
            ranges.append(("exact date", exact, exact))
        if parsed.month:
            m_start = max(parsed.month - 1, 1)
            m_end = min(parsed.month + 1, 12)
            _, last_day = calendar.monthrange(parsed.year, m_end)
            ranges.append((
                "month range",
                f"{parsed.year}-{m_start:02d}-01",
                f"{parsed.year}-{m_end:02d}-{last_day:02d}",
            ))
        ranges.append((
            "year range",
            f"{parsed.year}-01-01",
            f"{parsed.year}-12-31",
        ))
        return ranges

    @staticmethod
    def _extract_docket_entry_docs(
        entries: list[dict[str, Any]], docs: list[dict[str, Any]]
    ) -> bool:
        """Flatten docket entries into docs list (mutates in place).

        Returns True if any documents were found.
        """
        found = False
        for entry in entries:
            entry_date = entry.get("date_filed", "")
            entry_desc = entry.get("description", "")
            for doc in entry.get("recap_documents", []):
                doc["entry_date_filed"] = entry_date
                doc["entry_description"] = entry_desc
                docs.append(doc)
                found = True
        return found

    def _has_recap_date_match(
        self, parsed: ParsedCitation, docs: list[dict[str, Any]]
    ) -> bool:
        """Check if any substantive doc in docs matches the cited date."""
        if not (parsed.year and docs):
            return False
        for doc in docs:
            entry_date = doc.get("entry_date_filed") or doc.get("date_filed", "")
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
                return True
            except (ValueError, IndexError):
                pass
        return False

    # ------------------------------------------------------------------
    # Sync verification
    # ------------------------------------------------------------------

    def verify(
        self,
        citation_text: str,
        parsed: ParsedCitation | None = None,
        quick_only: bool = False,
    ) -> VerificationResult:
        """Verify a citation string through the resolution pipeline.

        Stages attempted, in order:
          1. citation_lookup       (always)
          2. opinion_search        (if (1) misses and not quick_only)
          3. recap_document_search (if (2) doesn't yield a credible match
                                     and parsed.docket_number is present
                                     and court is federal)
          4. recap_docket_search   (if (2) doesn't yield a credible match
                                     and parsed.case_name is present
                                     and court is federal)

        Each stage attempted produces one ResolutionPathEntry. Stages not
        attempted (quick_only short-circuit, state-court guard, already-have-
        credible-match guard, missing-input guard) are absent from the path.

        Parameters
        ----------
        citation_text : str
            Raw citation string used for the citation-lookup API call
            and stored in ``VerificationResult.citation_as_written``.
        parsed : ParsedCitation | None
            Pre-parsed citation metadata.  When provided the internal
            ``parse_citation()`` call is skipped, preserving fields
            (court, month, day) that would otherwise be lost in a
            text round-trip.
        quick_only : bool
            When True, only run Step 1 (citation lookup).  If the
            citation is not found in the lookup API, return NOT_FOUND
            immediately without falling through to Steps 1B/2/3.
        """
        citation_text = citation_text.strip()
        if parsed is None:
            parsed = parse_citation(citation_text)

        builder = ResolutionPathBuilder()

        # Stage 1: Citation Lookup API
        hit_finalize: dict[str, Any] | None = None
        with builder.stage(
            StageName.citation_lookup,
            query={"text": citation_text[:200]},
        ) as t:
            try:
                lookup_results = self.client.citation_lookup(citation_text)
                clusters_returned = sum(
                    len(lr.get("clusters", [])) for lr in lookup_results
                )
                for lr in lookup_results:
                    clusters = lr.get("clusters", [])
                    for cluster in clusters:
                        hit_finalize = self._process_citation_lookup_hit(
                            builder, t, citation_text, parsed, cluster, clusters_returned,
                        )
                        break
                    if hit_finalize is not None:
                        break
                if hit_finalize is None:
                    # No clusters in any of the lookup results.
                    # In quick_only mode, the legacy "Quick search only" note
                    # is preserved on the (terminal) citation_lookup entry so
                    # the _diagnostics compat helper keeps working.
                    if quick_only:
                        t.no_match(
                            raw_response_summary={"clusters_returned": 0},
                            notes="Quick search only: not in citation lookup API",
                        )
                    else:
                        t.no_match(raw_response_summary={"clusters_returned": 0})
            except Exception as exc:
                logger.debug("Citation lookup failed", exc_info=True)
                t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

        if hit_finalize is not None:
            # Phase 3 Task 5: caption_investigation runs in its own stage block
            # when _process_citation_lookup_hit flagged a name mismatch.
            if hit_finalize.pop("needs_caption_investigation", False):
                cluster = hit_finalize.pop("_cluster_for_investigation")
                with builder.stage(
                    StageName.caption_investigation,
                    query={
                        "cluster_id": cluster.get("id"),
                        "cited_case_name": parsed.case_name,
                        "cl_case_name": cluster.get("case_name", ""),
                    },
                ) as inv_t:
                    try:
                        inv_result = self._investigate_caption(parsed, cluster)
                        inv_t.resolved(
                            confidence=inv_result["confidence"],
                            raw_response_summary=inv_result["raw_response_summary"],
                            notes=inv_result["notes"],
                        )
                        hit_finalize["warnings"] = inv_result["warnings"] or None
                        hit_finalize["status_override"] = inv_result["status"]
                    except Exception as exc:
                        logger.debug("caption_investigation failed", exc_info=True)
                        inv_t.errored(
                            error_type=type(exc).__name__,
                            notes=f"{type(exc).__name__}: {exc}",
                        )
                        # Defensive fallback: investigation errored. Emit the
                        # pre-Task-5 cl_display_name_data_bug warning so the
                        # consumer still knows a mismatch was flagged but the
                        # verifier could not classify it. Per design §2.8:
                        # refinement-stage failures do not trigger
                        # VERIFICATION_INCOMPLETE — the underlying verification
                        # (cluster exists, citation maps to it) still stands.
                        hit_finalize["warnings"] = [Warning(
                            category=WarningCategory.cl_display_name_data_bug,
                            message=(
                                f"Citation_lookup resolved the cluster, but caption_investigation "
                                f"could not complete ({type(exc).__name__}). The citation is verified "
                                f"(the cluster exists); the case-name divergence between the brief "
                                f"and CL's caption is unclassified. Per design §2.8, refinement-stage "
                                f"failures do not trigger VERIFICATION_INCOMPLETE."
                            ),
                        )]

            status = hit_finalize.pop("status_override", Status.VERIFIED)
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=status,
                **hit_finalize,
            )

        if quick_only:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        # Stage 2+: Fuzzy search fallback (instrumented in Task 3)
        return self._search_fallback(builder, citation_text, parsed)

    def _search_fallback(
        self,
        builder: ResolutionPathBuilder,
        citation_text: str,
        parsed: ParsedCitation,
    ) -> VerificationResult:
        """Search CourtListener using parsed citation metadata.

        Phase 2 / Task 3: each of opinion_search, recap_document_search, and
        recap_docket_search is wrapped in its own ``builder.stage(...)``
        block. ``_build_fallback_result`` no longer touches the builder; it
        only picks the winning candidate from the pooled stages and
        finalizes the result.
        """
        court_id, filed_after, filed_before = self._build_search_params(parsed)

        # Insufficient-data short-circuit: without both court and date we
        # don't have enough signal to verify reliably. Record a no_match
        # opinion_search entry with the legacy diagnostic message and
        # return NOT_FOUND without running any fallback API calls. (The
        # same guard fires post-search in ``_build_fallback_result`` for
        # other callers, but skipping the stages here keeps the resolved
        # opinion_search entry off the path so ``headline_confidence``
        # correctly reads None.)
        if not parsed.court and not parsed.year:
            with builder.stage(
                StageName.opinion_search,
                query={
                    "q": parsed.case_name,
                    "court": court_id,
                    "filed_after": filed_after,
                    "filed_before": filed_before,
                },
            ) as t:
                t.no_match(
                    raw_response_summary={"candidate_count": 0},
                    notes=(
                        "Insufficient data to verify: citation text is missing "
                        "both court and date. A match cannot be confirmed with "
                        "name alone. Try adding the court and year parenthetical "
                        "(e.g. '(E.D. Tenn. 2020)') to the citation text."
                    ),
                )
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        opinion_candidates: list[CandidateMatch] = []
        recap_candidates: list[CandidateMatch] = []

        # Stage: opinion_search
        if parsed.case_name:
            with builder.stage(
                StageName.opinion_search,
                query={
                    "q": parsed.case_name,
                    "court": court_id,
                    "filed_after": filed_after,
                    "filed_before": filed_before,
                },
            ) as t:
                try:
                    results = self.client.search_opinions(
                        q=parsed.case_name,
                        court=court_id,
                        filed_after=filed_after,
                        filed_before=filed_before,
                    )
                    opinion_candidates = self._process_results(results, parsed)
                    if opinion_candidates:
                        best = max(opinion_candidates, key=lambda c: c.score)
                        summary = {
                            "candidate_count": len(opinion_candidates),
                            "best_score": best.score,
                            "best_case_name": best.case_name,
                            "best_cluster_id": best.cluster_id,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"candidate_count": 0})
                except Exception as exc:
                    logger.debug("Opinion search failed", exc_info=True)
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Guards for RECAP: federal-only, no credible match yet.
        is_state_court = self._is_state_court_citation(parsed, court_id)
        has_credible_match = any(c.score >= 0.5 for c in opinion_candidates)

        # Stage: recap_document_search (by docket_number)
        if not has_credible_match and not is_state_court and parsed.docket_number:
            with builder.stage(
                StageName.recap_document_search,
                query={"docket_number": parsed.docket_number},
            ) as t:
                try:
                    results = self.client.search_recap(
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
                    rd_candidates = self._process_recap_results(results, parsed)
                    recap_candidates.extend(rd_candidates)
                    if rd_candidates:
                        best = max(rd_candidates, key=lambda c: c.score)
                        summary = {
                            "docket_count": len(rd_candidates),
                            "best_score": best.score,
                            "best_docket_id": best.docket_id,
                            "best_case_name": best.case_name,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"docket_count": 0})
                except Exception as exc:
                    logger.debug(
                        "RECAP search by docket number failed", exc_info=True
                    )
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Stage: recap_docket_search (by case_name)
        if not has_credible_match and not is_state_court and parsed.case_name:
            with builder.stage(
                StageName.recap_docket_search,
                query={"q": parsed.case_name, "court": court_id},
            ) as t:
                try:
                    results = self.client.search_recap(
                        q=parsed.case_name,
                        court=court_id,
                    )
                    rd_candidates = self._process_recap_results(results, parsed)
                    recap_candidates.extend(rd_candidates)
                    if rd_candidates:
                        best = max(rd_candidates, key=lambda c: c.score)
                        summary = {
                            "docket_count": len(rd_candidates),
                            "best_score": best.score,
                            "best_docket_id": best.docket_id,
                            "best_case_name": best.case_name,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"docket_count": 0})
                except Exception as exc:
                    logger.debug("RECAP search failed", exc_info=True)
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Aggregate across stages and finalize. The per-stage entries are
        # already appended above; _build_fallback_result does NOT touch the
        # builder — it only picks the winning candidate and finalizes.
        # Pass the doc-detail fetch callable so the gate can refine
        # page_count + is_free_on_pacer when search_recap omits them.
        candidates = opinion_candidates + recap_candidates
        return self._build_fallback_result(
            builder, citation_text, parsed, candidates, court_id,
            _doc_detail_fn=self.client.get_recap_document_metadata,
        )

    def _stage_notes_for_candidate(self, best: CandidateMatch) -> str | None:
        """Build the joined-diagnostic-message notes string for a stage's
        best candidate.

        Computes the status the candidate would yield in isolation (per the
        same 0.40 threshold used by ``_build_fallback_result``) and runs
        ``_finalize_diagnostics`` to produce the joined-message string. The
        legacy ``_diagnostics`` test helper reads these notes off the
        winning stage entry.
        """
        status = Status.VERIFIED if best.score >= _VERIFIED_SCORE_THRESHOLD else Status.NOT_FOUND
        diagnostics = self._finalize_diagnostics(best.mismatches, best.score, status)
        if not diagnostics:
            return None
        return "; ".join(d.message for d in diagnostics)

    @staticmethod
    def _is_state_court_citation(
        parsed: ParsedCitation, court_id: str | None
    ) -> bool:
        """True when the citation is to a state court, which must skip RECAP
        (RECAP is federal PACER data only).

        ``court_id`` is the federal-mapped id (``lookup_court_id``), which is
        ``None`` for state courts, so it cannot be the sole signal — keying
        the guard off it alone was the Tier 1 Step 4 leak. Two more signals
        survive when ``court_id`` is None:

        - the raw parsed court id: eyecite returns state CL ids directly
          (e.g. ``indctapp``), and ``is_federal_court`` knows they are not
          federal;
        - the reporter: a regional/state reporter (N.E.2d, P.3d, A.2d, ...)
          is never a federal citation. This catches multi-state reporters
          (N.E.2d -> ill/ind/mass/ny/ohio) where the single-state court
          inference in ``_infer_court_and_dates`` does not fire, so the
          earlier reporter-only path missed them. Federal/neutral reporters
          (F.3d, U.S., S. Ct., WL) map to no states and are not flagged.
        """
        court = court_id or parsed.court
        if court and not is_federal_court(court):
            return True
        if parsed.reporter and get_states_for_reporter(parsed.reporter):
            return True
        return False

    def _recap_result_gated(
        self, parsed: ParsedCitation, case_name: str, date_filed: str
    ) -> bool:
        """Hard-gate a RECAP search result before it becomes a candidate.

        Mirrors the two hard-gates the opinion-search path applies in
        ``_process_results`` (issue #7), with ONE deliberate difference: the
        temporal gate is one-sided.

        - Name-token gate: require at least one shared distinctive
          (>=4-char, non-stoplist) token between the cited caption and the
          docket caption. A zero-overlap match (e.g. cited "South Pointe
          Wholesale v. Vilardi" -> docket "Thompson v. Martuscello") is
          surname/score-inflation noise, not a real match.

        - One-sided temporal gate: a RECAP ``dateFiled`` is the case
          *filing* date, not the opinion date. An opinion cannot predate
          its own case, so a cite whose year is far *before* the filing
          year is impossible -> reject (In re Hudson: 1812 cite vs a
          2018-filed docket). A cite *after* the filing year is a
          legitimate opinion issued later in a long-running case -> keep
          (Oracle v. Google: 2016 opinion in a 2010-filed case). A
          symmetric +/-N gate here would be a false-negative bug; see
          docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
        """
        if parsed.case_name and case_name:
            cited_tokens = _name_tokens(parsed.case_name)
            cand_tokens = _name_tokens(case_name)
            if cited_tokens and not (cited_tokens & cand_tokens):
                return True

        if parsed.year and date_filed and len(date_filed) >= 4:
            try:
                filing_year = int(date_filed[:4])
                if filing_year - parsed.year > self._TEMPORAL_GATE_YEARS:
                    return True
            except ValueError:
                pass  # unparseable date — let the scorer handle it

        # PACER-era floor: RECAP is electronic PACER docket data, which does
        # not predate ~1990. A cite older than that reaching the RECAP
        # fallback means opinion search already failed; a bare-surname match
        # on a modern docket is impossible, not a real resolution. This
        # catches the case the date-diff above misses when the docket's
        # dateFiled is null (In re Hudson 1812 -> a null-date appellate
        # docket). The oldest real RECAP cite in the false-negative corpus
        # is 2006, so the floor has ample margin.
        if parsed.year and parsed.year < self._RECAP_PACER_ERA_FLOOR:
            return True

        return False

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

            # Hard-gate before the (expensive) docket-entries fetch: skip
            # dockets with no name overlap or an impossible cite-before-filing
            # date. Parity with the opinion-search path's gates (Lever 1).
            date_filed = r.get("dateFiled") or r.get("date_filed", "")
            if self._recap_result_gated(parsed, case_name, date_filed):
                continue

            docs = r.get("recap_documents", [])

            if not self._has_recap_date_match(parsed, docs):
                if parsed.year and docket_id:
                    self._fetch_docs_for_docket(docket_id, parsed, docs)

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

    def _fetch_docs_for_docket(
        self, docket_id: int, parsed: ParsedCitation, docs: list[dict[str, Any]]
    ) -> None:
        """Query docket-entries API for documents matching the cited date.

        Tries progressive date ranges: exact -> month +/- 1 -> year.
        Appends found documents to the *docs* list (mutates in place).
        """
        for label, after, before in self._docket_date_ranges(parsed):
            try:
                entries = self.client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=after,
                    date_filed_before=before,
                )
                if self._extract_docket_entry_docs(entries, docs):
                    return
            except Exception:
                logger.debug(
                    "Docket entries query (%s) failed for docket %s",
                    label,
                    docket_id,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Shared result processing (used by both sync and async)
    # ------------------------------------------------------------------

    _TEMPORAL_GATE_YEARS = 5

    # RECAP/PACER electronic dockets do not predate ~1990. A citation older
    # than this that falls through to the RECAP path cannot legitimately
    # resolve to a PACER docket (used only by the one-sided RECAP temporal
    # gate; the opinion-search path is unaffected). See
    # docs/retrospectives/2026-06-10-tier1-step1-measurement.md.
    _RECAP_PACER_ERA_FLOOR = 1990

    def _process_results(
        self, results: list[dict[str, Any]], parsed: ParsedCitation
    ) -> list[CandidateMatch]:
        """Convert API results to scored CandidateMatch objects.

        Hard-rejects (issue #7):
          - Temporal: skip candidates whose date_filed year differs from
            parsed.year by more than _TEMPORAL_GATE_YEARS.
          - Name-token: skip candidates that share no distinctive
            (>=4-char, non-stoplist) token with parsed.case_name.
        """
        candidates = []
        for r in results:
            case_name = r.get("caseName") or r.get("case_name", "")
            cluster_id = r.get("cluster_id") or r.get("id")
            if cluster_id is None:
                continue
            date_filed = r.get("dateFiled") or r.get("date_filed", "")

            # Temporal hard-gate
            if parsed.year and date_filed and len(date_filed) >= 4:
                try:
                    cand_year = int(date_filed[:4])
                    if abs(cand_year - parsed.year) > self._TEMPORAL_GATE_YEARS:
                        continue
                except ValueError:
                    pass  # unparseable date — let the scorer handle it

            # Name-token hard-gate: at least one shared distinctive token
            if parsed.case_name and case_name:
                cited_tokens = _name_tokens(parsed.case_name)
                cand_tokens = _name_tokens(case_name)
                if cited_tokens and not (cited_tokens & cand_tokens):
                    continue

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
        entry_desc = doc.get("entry_description") or ""
        # Full description for display (entry-level description is richer)
        full_desc = entry_desc or desc
        # Truncated description for diagnostic note
        diag_desc = desc
        if diag_desc and len(diag_desc) > 80:
            diag_desc = diag_desc[:80] + "..."

        recap_note = "Found in RECAP (not in opinions database)"
        if entry_date:
            recap_note += f". Document dated {entry_date}"
        if diag_desc:
            recap_note += f": {diag_desc}"
        mismatches.insert(0, Diagnostic("recap", recap_note))

        return CandidateMatch(
            case_name=case_name,
            url=doc_url or docket_url,
            cluster_id=None,
            date_filed=entry_date,
            court_id=court_id,
            score=score,
            description=full_desc or None,
            mismatches=mismatches,
            docket_id=docket_id,
            recap_document_id=doc.get("id"),          # Phase 3 Task 4
            page_count=int(doc.get("page_count") or 0),    # Phase 4 Task 4 (Q2)
            is_free_on_pacer=bool(doc.get("is_free_on_pacer")),  # Phase 4 Task 4 (Q2)
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
        # Remove date/citation/name-missing diagnostics — they're redundant
        # when we already can't verify a specific document.
        # Keep court/name diagnostics — those are still useful.
        _drop_categories = {"date", "cite"}
        mismatches = [
            m for m in mismatches
            if m.category not in _drop_categories
            and m.message != "Case name not returned by API"
        ]
        mismatches.insert(
            0,
            Diagnostic(
                "recap",
                "We found a possible docket match in RECAP, "
                "but no specific document could be verified",
            ),
        )
        return CandidateMatch(
            case_name=case_name,
            url=docket_url,
            cluster_id=None,
            date_filed="",
            court_id=court_id,
            score=score,
            mismatches=mismatches,
            docket_id=docket_id,
        )

    @staticmethod
    def _finalize_diagnostics(
        mismatches: list[Diagnostic],
        score: float,
        status: Status,
    ) -> list[Diagnostic]:
        """Finalize diagnostics by appending match language for non-verified results.

        When score >= 0.40, appends "However, we identified a likely/possible match"
        to the last diagnostic or as a standalone message.
        """
        diagnostics = list(mismatches)
        if score >= _VERIFIED_SCORE_THRESHOLD:
            # In Phase 1, LIKELY_REAL and POSSIBLE_MATCH collapse to VERIFIED;
            # the distinction is now on the score itself.
            match_word = "likely" if score >= 0.85 else "possible"
            if diagnostics:
                last = diagnostics[-1]
                if last.message.endswith("could be verified"):
                    diagnostics[-1] = Diagnostic(
                        last.category,
                        last.message + f". However, we identified a {match_word} match.",
                    )
                else:
                    diagnostics[-1] = Diagnostic(
                        last.category,
                        last.message + f", but we identified a {match_word} match.",
                    )
            else:
                diagnostics.append(Diagnostic("info", f"We identified a {match_word} match."))
        return diagnostics

    @staticmethod
    def _normalize_docket_number(dn: str) -> str:
        """Normalize a docket number for comparison.

        Strips division prefix ('2:'), judge suffixes ('-JCC', '-JPH-MJD'),
        trailing hyphens, and leading zeros from numeric segments so that
        '17-cv-12676' and '2:17-cv-00012676' compare as equal.

        Expands shorthand prefixes and suffixes:
        - 'C15-1228' / 'C-15-1228' / 'C 09-02727' → '15-cv-1228' etc.
        - 'CR15-1228' → '15-cr-1228'
        - '03 C 7956' → '3-cv-7956'
        - '20-20720-Civ' / '24-61529-CIV' → '20-cv-20720' etc.
        """
        # Strip optional division prefix (e.g. "2:" or "4:")
        dn = re.sub(r"^\d+:", "", dn)
        # Strip trailing hyphens (e.g. "24-cv-00953-DC-" → "24-cv-00953-DC")
        dn = dn.rstrip("-").strip()
        # Expand -CIV/-Civ/-CV suffix BEFORE judge-suffix stripping
        # (otherwise "-CIV" gets consumed as a judge suffix)
        # "20-20720-Civ" → "20-cv-20720", "24-61529-CIV" → "24-cv-61529"
        m = re.match(
            r"^(\d+)-(\d+)-(?:CIV|CV)$", dn, flags=re.IGNORECASE
        )
        if m:
            dn = f"{m.group(1)}-cv-{m.group(2)}"
        # Strip trailing space-separated alpha tokens (judge initials after
        # space, e.g. "C 09-02727 WHA" → "C 09-02727"). Repeat the group so
        # paired District + Magistrate initials are both removed
        # ("1:13-CV-1483 AWI SAB" → "1:13-CV-1483").
        dn = re.sub(r"(\s+[A-Za-z]{2,4})+$", "", dn)
        # Strip all trailing hyphen-separated judge-initial segments
        # (e.g. "-JPH-MJD", "-DC", "-WHO")
        dn = re.sub(r"(-[A-Za-z]{2,4})+$", "", dn)
        # Expand space-separated format: "03 C 7956" → "3-cv-7956"
        m = re.match(
            r"^(\d+)\s+C\s+(\d[\d-]*)$", dn, flags=re.IGNORECASE
        )
        if m:
            dn = f"{m.group(1)}-cv-{m.group(2)}"
        # Expand C/CV prefix with space: "C 09-02727" → "9-cv-2727"
        m = re.match(
            r"^C(?:V|R)?\s+(\d[\d-]*)$", dn, flags=re.IGNORECASE
        )
        if m:
            prefix = "cr" if dn[1:2].upper() == "R" else "cv"
            parts = m.group(1)
            seg = re.match(r"^(\d+)-?(.*)", parts)
            if seg:
                rest = f"-{seg.group(2)}" if seg.group(2) else ""
                dn = f"{seg.group(1)}-{prefix}{rest}"
        # Expand shorthand prefix with optional hyphen:
        # CR15-1228 / CR-15-1228 → 15-cr-1228
        # C15-1228  / C-15-1228  → 15-cv-1228
        dn = re.sub(r"^CR-?(\d+)", r"\1-cr", dn, flags=re.IGNORECASE)
        dn = re.sub(r"^C-?(\d+)", r"\1-cv", dn, flags=re.IGNORECASE)
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
    def _date_within_window(parsed: ParsedCitation, entry_date: str, days: int = 14) -> bool:
        """Return True iff the doc's entry_date is within ±days of parsed's cited date.

        When parsed.year is missing or entry_date is unparseable, returns False.
        Missing month defaults to June (6); missing day defaults to 15.
        """
        if not (parsed.year and entry_date and len(entry_date) >= 10):
            return False
        try:
            from datetime import date as _date
            cited_y = parsed.year
            cited_m = parsed.month or 6
            cited_d = parsed.day or 15
            ey = int(entry_date[0:4])
            em = int(entry_date[5:7])
            ed = int(entry_date[8:10])
            delta_days = abs(
                (_date(cited_y, cited_m, cited_d) - _date(ey, em, ed)).days
            )
            return delta_days <= days
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _recap_doc_is_cited_opinion(
        parsed: ParsedCitation,
        desc: str,
        entry_date: str,
        has_wl_cite_in_cluster: bool = False,
        page_count: int = 0,
        is_free_on_pacer: bool = False,
    ) -> bool:
        """Strict VIA_RECAP gate (design v2 §2.2 + Phase 3 Q1 + Phase 4 Q2).

        A RECAPDocument qualifies as the cited opinion when:
          (a) has_wl_cite_in_cluster is True, OR
          (b) The description matches opinion-typed keywords AND the date
              is within ±14 days of cited date AND no procedural-order
              keywords match, OR
          (c) The score-based gate fires: page_count >= 5 AND
              is_free_on_pacer AND no procedural-order keywords match
              (substantive long-form opinion regardless of description
              wording; the score-based fallback handles "ORDER GRANTING ..."
              style descriptions that are substantive but keyword-poor).

        Note: "motion to" and "motion for" are intentionally excluded from
        the substring procedural keywords because they appear inside opinion
        descriptions like "OPINION on motion to dismiss". They ARE rejected
        when they anchor the description (e.g. "MOTION FOR RECONSIDERATION
        OF OPINION") — a description that starts with "motion to "/"motion
        for " is a party filing, not the court's opinion, regardless of
        what the rest of the string says.

        When parsed.year is missing or entry_date is unparseable, path (b)
        cannot fire (date window returns False). Path (c) does not require
        a date and can fire on page_count + is_free_on_pacer alone.
        """
        desc_lower = (desc or "").lstrip().lower()

        # Anchored procedural guard: a description that STARTS with a motion
        # prefix is a party filing, not an opinion — even if the rest of the
        # string mentions "opinion" (e.g. "MOTION FOR RECONSIDERATION OF
        # OPINION"). Mirrors the anchoring _is_substantive_doc applies to its
        # _NON_SUBSTANTIVE_PATTERNS tuple.
        if desc_lower.startswith("motion to ") or desc_lower.startswith("motion for "):
            return False

        # Procedural-keyword guard runs first; never accept a doc whose
        # description matches a procedural type, regardless of score.
        _PROCEDURAL_KEYWORDS = (
            "certifying interlocutory appeal",
            "taxation of costs", "taxation order",
            "motion in limine", "in limine",
            "objections to", "objection to",
            "stipulation", "scheduling order",
            "minute order", "minute entry",
            "notice of",
            "certificate of service",
            "stipulated protective order",
        )
        if any(kw in desc_lower for kw in _PROCEDURAL_KEYWORDS):
            return False

        # Path (a): WL cite in cluster → unconditional trust.
        if has_wl_cite_in_cluster:
            return True

        # Path (b): opinion keyword + date window.
        _OPINION_KEYWORDS = (
            "opinion", "memorandum",
            "order & reasons", "order and reasons",
            "findings of fact", "report and recommendation",
            "report & recommendation",
            "memorandum and order", "memorandum & order",
        )
        has_opinion_keyword = any(kw in desc_lower for kw in _OPINION_KEYWORDS)

        if has_opinion_keyword and CitationVerifier._date_within_window(parsed, entry_date, days=14):
            return True

        # Path (c) — score-based fallback for substantive-but-keyword-poor docs.
        # page_count >= 5 AND is_free_on_pacer strongly suggests a substantive
        # opinion even when the description wording doesn't match opinion keywords
        # (e.g. "ORDER GRANTING Motion for Reconsideration" — Mehar Holdings).
        if page_count >= 5 and is_free_on_pacer:
            return True

        return False

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

    @staticmethod
    def _cited_primary_reporter_in_cluster(
        parsed: ParsedCitation, cluster: dict[str, Any],
    ) -> bool:
        """Return True iff the brief's primary reporter cite (volume +
        reporter + page) appears in the cluster's `citations` list.

        Returns True when the brief had no parsed reporter cite (e.g. WL-
        only input — nothing for the cluster to be missing) so a missing
        primary cannot be inferred. Returns True when the cluster's
        citations field is absent or unparseable (defensive: better to
        under-call partial than over-call).
        """
        if not (parsed.volume and parsed.reporter and parsed.page):
            return True   # No primary to be silently dropped.
        if "citations" not in cluster:
            return True   # Absent citations field — defensive: don't over-call partial.
        cl_citations = cluster.get("citations") or []
        if not cl_citations:
            return True   # Empty list is also indeterminate — be conservative.
        cited_vol = str(parsed.volume).strip()
        cited_rep = str(parsed.reporter).strip().lower().replace(".", "").replace(" ", "")
        cited_page = str(parsed.page).strip()
        for c in cl_citations:
            if isinstance(c, dict):
                vol = str(c.get("volume", "")).strip()
                rep = str(c.get("reporter", "")).strip().lower().replace(".", "").replace(" ", "")
                page = str(c.get("page", "")).strip()
            else:
                # String form: "201 A.D.3d 83" — coarse contains check
                s = str(c).lower().replace(".", "").replace(" ", "")
                if cited_vol.lower() in s and cited_rep in s and cited_page.lower() in s:
                    return True
                continue
            if vol == cited_vol and rep == cited_rep and page == cited_page:
                return True
        return False

    @staticmethod
    def _party_overlap_ok(parsed: ParsedCitation, candidate_caption: str) -> bool:
        """Phase 3 maintainer Q4 pre-decision: WRONG_CASE escalation gate.

        Returns True iff the candidate caption has at least one plaintiff
        token AND at least one defendant token in common with the brief's
        parsed case name, after lowercasing + punctuation stripping +
        stopword removal. Common-prefix cases (United States v. X, State v.
        X, In re X) compare distinctive-word overlap only.

        The implementer is expected to calibrate the precise stopword and
        normalization choices against the corpus's WRONG_CASE fixtures
        (especially named-exemplar-wrong-case = Hogan v. AT&T resolving
        to U.S. ex rel. Green v. Washington) and the cl_display_name_data_bug
        fixtures (Koch, Gilliard, SSA pseudonyms). The reference cases:
        Hogan/Green has zero token overlap on either side -> WRONG_CASE;
        Koch v. United States vs. Ricky Koch v. Tote has plaintiff
        overlap on 'koch' -> same case + cl_display_name_data_bug.
        """
        if not parsed.case_name:
            return True  # Nothing to compare — trust citation_lookup.

        _STOPWORDS = frozenset({
            "the", "of", "and", "for", "in", "re", "matter", "ex", "rel",
            "v", "vs", "versus", "et", "al", "inc", "llc", "ltd", "co",
            "corp", "company", "corporation", "lp", "llp", "pllc", "pc",
            "limited", "holdings", "group", "intl", "international",
        })
        # Prefix words to strip from common-prefix case names before token
        # comparison, so "United States v. Smith" and "United States v. Johnson"
        # don't compare only on "united"/"states" tokens.
        _PREFIX_WORDS = frozenset({
            "united", "states", "state", "commonwealth", "people", "government",
            "usa", "u.s.", "u.s",
        })

        def _toks(s: str) -> set[str]:
            return {
                t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
                if len(t) >= 3 and t not in _STOPWORDS
            }

        # Common-prefix detection (United States v. X, State v. X, etc.)
        cited_lower = parsed.case_name.lower()
        common_prefixes = (
            "united states v",
            "state v", "state of ", "commonwealth v", "commonwealth of",
            "people v", "people of",
            "in re ", "in the matter",
            "u.s. ex rel", "us ex rel",
        )
        is_common_prefix = any(cited_lower.startswith(p) for p in common_prefixes)

        cited_caption_toks = _toks(parsed.case_name)
        candidate_toks = _toks(candidate_caption)

        if is_common_prefix:
            # Distinctive-word overlap only; strip the common prefix tokens
            # from both sides so "United States v. Smith" and "United States
            # v. Johnson" don't falsely match on "united"/"states".
            cited_distinctive = cited_caption_toks - _PREFIX_WORDS
            cand_distinctive = candidate_toks - _PREFIX_WORDS
            # For "In re" cases there may be no "v." so compare full distinctive tokens.
            return bool(cited_distinctive & cand_distinctive)

        # Regular case: separate plaintiff vs defendant.
        cited_plaintiff_toks = _toks(parsed.plaintiff or "")
        cited_defendant_toks = _toks(parsed.defendant or "")
        if not (cited_plaintiff_toks or cited_defendant_toks):
            # Couldn't extract parties — fall back to full overlap.
            return bool(cited_caption_toks & candidate_toks)

        # Split the candidate caption on " v. " (or " v "); both sides matter.
        cand_lower = (candidate_caption or "").lower()
        parts = re.split(r"\s+v\.?\s+", cand_lower, maxsplit=1)
        cand_left = _toks(parts[0]) if parts else set()
        cand_right = _toks(parts[1]) if len(parts) > 1 else set()

        if cand_left or cand_right:
            # Match in EITHER direction (party swap tolerated): at least
            # one plaintiff-side hit and one defendant-side hit, but the
            # "sides" don't have to line up.
            all_cand = cand_left | cand_right
            plaintiff_hit = bool(cited_plaintiff_toks & all_cand) if cited_plaintiff_toks else True
            defendant_hit = bool(cited_defendant_toks & all_cand) if cited_defendant_toks else True
            return plaintiff_hit and defendant_hit

        return bool(cited_caption_toks & candidate_toks)

    @staticmethod
    def _captions_differ_only_in_formatting(a: str, b: str) -> bool:
        """Return True iff strings differ only in abbreviation / punctuation
        / whitespace. Used by _investigate_caption to choose between
        name_formatting_noise and cl_display_name_data_bug."""
        _ABBREV_MAP = {
            "incorporated": "inc", "corporation": "corp", "company": "co",
            "limited": "ltd", "department": "dept", "county": "cnty",
        }

        def _norm(s: str) -> str:
            s = (s or "").lower()
            for long, short in _ABBREV_MAP.items():
                s = re.sub(rf"\b{long}\b", short, s)
            return re.sub(r"[^a-z0-9]+", "", s)

        return _norm(a) == _norm(b) and _norm(a) != ""

    def _investigate_caption(
        self,
        parsed: ParsedCitation,
        cluster: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 3 caption_investigation sub-pipeline (design v2 §2.5).

        Called from verify()/verify_async() after the citation_lookup
        stage's `with` block has exited, when _process_citation_lookup_hit
        flagged a name mismatch. This helper does the actual three-step
        lookup but is itself wrapped in a separate
        `builder.stage(StageName.caption_investigation, ...)` block by the
        caller — the caller sets verdict/notes on the investigation token
        from this helper's return value.

        Returns a dict with:
          status: Status   (VERIFIED or WRONG_CASE)
          warnings: list[Warning]
          raw_response_summary: dict (for the investigation stage entry)
          notes: str | None
          confidence: float

        The verifier helper performs three lookups (any of which can
        contribute to the decision; errors are caught at the call site so
        a single API failure doesn't cascade):
          1. Cluster's `case_name_full` is often richer than `case_name`
             (Rule 25(d) substitutions, SSA pseudonyms, etc.).
          2. Docket's `case_name` is the long-form caption as originally
             filed; matches the brief's caption more often.
          3. Opinion text's first 500 characters carry the caption header.

        Decision rules (in order):
          - If party-overlap passes against any of (cluster.case_name_full,
            docket.case_name, opinion.head_500): VERIFIED with the most-
            appropriate cosmetic-divergence warning (name_formatting_noise
            when the captions match modulo punctuation/abbreviations;
            cl_display_name_data_bug otherwise).
          - Else: WRONG_CASE.

        Q2/Q3 sibling checks (wrong_page_number, cl_duplicate_clusters) are
        deferred to Phase 3.5/4. When no party-overlap is found, this
        function returns WRONG_CASE directly without searching for siblings.
        See docs/plans/ Phase 3 plan Task 5 note on MAY-implement status.
        """
        cluster_id = cluster.get("id")
        cl_case_name = cluster.get("case_name", "")

        # Step 1: cluster case_name_full
        case_name_full = ""
        docket_id = None
        try:
            cluster_detail = self.client.get_cluster(cluster_id)
            case_name_full = cluster_detail.get("case_name_full", "") or ""
            docket_id = cluster_detail.get("docket_id") or cluster_detail.get("docket")
        except Exception:
            cluster_detail = {}

        # Step 2: docket case_name
        docket_case_name = ""
        if docket_id:
            try:
                docket = self.client.get_docket(docket_id)
                docket_case_name = (
                    docket.get("case_name_full")
                    or docket.get("case_name")
                    or ""
                )
            except Exception:
                pass

        # Step 3: opinion plain_text first 500 chars (caption header)
        opinion_head = ""
        abs_url = cluster.get("absolute_url", "")
        if abs_url and not abs_url.startswith("http"):
            abs_url_full = f"https://www.courtlistener.com{abs_url}"
        elif abs_url:
            abs_url_full = abs_url
        else:
            abs_url_full = f"https://www.courtlistener.com/opinion/{cluster_id}/"
        try:
            text = self.client.get_opinion_text(abs_url_full)
            if text:
                opinion_head = text[:500]
        except Exception:
            pass

        # Pool of caption candidates the brief might be matching against.
        candidates = [
            ("cluster_case_name", cl_case_name),
            ("cluster_case_name_full", case_name_full),
            ("docket_case_name", docket_case_name),
            ("opinion_head_500", opinion_head),
        ]
        overlap_hits = [
            (label, cap) for (label, cap) in candidates
            if cap and self._party_overlap_ok(parsed, cap)
        ]

        summary = {
            "investigated_cluster_id": cluster_id,
            "cl_case_name": cl_case_name,
            "case_name_full": case_name_full,
            "docket_case_name": docket_case_name,
            "opinion_head_500_present": bool(opinion_head),
            "overlap_hits": [lbl for (lbl, _) in overlap_hits],
        }

        if overlap_hits:
            # Same case under at least one caption source.
            # Refine the warning category:
            #   - name_formatting_noise: captions match modulo
            #     abbreviation/punctuation (e.g. "Inc." vs "Incorporated")
            #   - cl_display_name_data_bug: captions semantically differ
            #     but party-overlap still passes (Rule 25(d) substitution,
            #     SSA pseudonyms, the Koch "Ricky Koch v. Tote" shape).
            is_pure_formatting = self._captions_differ_only_in_formatting(
                parsed.case_name or "", cl_case_name,
            )
            category = (
                WarningCategory.name_formatting_noise if is_pure_formatting
                else WarningCategory.cl_display_name_data_bug
            )
            return {
                "status": Status.VERIFIED,
                "warnings": [Warning(
                    category=category,
                    message=(
                        f'Brief caption "{parsed.case_name}" differs from '
                        f'CL caption "{cl_case_name}" but party-overlap '
                        f'confirms it is the same case.'
                    ),
                    details={"caption_sources_matched": [lbl for lbl, _ in overlap_hits]},
                )],
                "raw_response_summary": summary,
                "notes": f"party-overlap match via {overlap_hits[0][0]}",
                "confidence": 1.0,
            }

        # No party-overlap match anywhere.
        # Q2 / Q3 sibling checks (wrong_page_number, cl_duplicate_clusters)
        # are deferred to Phase 3.5/4. The corpus does not pin specific
        # wrong_page_number positive fixtures (Butler Motors is NOT_FOUND
        # under strict reading), and the duplicate-cluster sibling search is
        # exercised mostly by the 4 xfailed known_real_citations.json entries
        # which require live API access. Direct WRONG_CASE per plan guidance.
        return {
            "status": Status.WRONG_CASE,
            "warnings": [],
            "raw_response_summary": summary,
            "notes": "no party-overlap across cluster/docket/opinion sources",
            "confidence": 1.0,
        }

    async def _investigate_caption_async(
        self,
        parsed: ParsedCitation,
        cluster: dict[str, Any],
        async_client: AsyncCourtListenerClient,
    ) -> dict[str, Any]:
        """Async mirror of _investigate_caption().

        Awaits async_client.get_cluster, get_docket, and get_opinion_text
        instead of the sync client. The decision tree is identical.
        """
        cluster_id = cluster.get("id")
        cl_case_name = cluster.get("case_name", "")

        # Step 1: cluster case_name_full
        case_name_full = ""
        docket_id = None
        try:
            cluster_detail = await async_client.get_cluster(cluster_id)
            case_name_full = cluster_detail.get("case_name_full", "") or ""
            docket_id = cluster_detail.get("docket_id") or cluster_detail.get("docket")
        except Exception:
            pass

        # Step 2: docket case_name
        docket_case_name = ""
        if docket_id:
            try:
                docket = await async_client.get_docket(docket_id)
                docket_case_name = (
                    docket.get("case_name_full")
                    or docket.get("case_name")
                    or ""
                )
            except Exception:
                pass

        # Step 3: opinion plain_text first 500 chars (caption header)
        opinion_head = ""
        abs_url = cluster.get("absolute_url", "")
        if abs_url and not abs_url.startswith("http"):
            abs_url_full = f"https://www.courtlistener.com{abs_url}"
        elif abs_url:
            abs_url_full = abs_url
        else:
            abs_url_full = f"https://www.courtlistener.com/opinion/{cluster_id}/"
        try:
            text = await async_client.get_opinion_text(abs_url_full)
            if text:
                opinion_head = text[:500]
        except Exception:
            pass

        # Pool of caption candidates
        candidates = [
            ("cluster_case_name", cl_case_name),
            ("cluster_case_name_full", case_name_full),
            ("docket_case_name", docket_case_name),
            ("opinion_head_500", opinion_head),
        ]
        overlap_hits = [
            (label, cap) for (label, cap) in candidates
            if cap and self._party_overlap_ok(parsed, cap)
        ]

        summary = {
            "investigated_cluster_id": cluster_id,
            "cl_case_name": cl_case_name,
            "case_name_full": case_name_full,
            "docket_case_name": docket_case_name,
            "opinion_head_500_present": bool(opinion_head),
            "overlap_hits": [lbl for (lbl, _) in overlap_hits],
        }

        if overlap_hits:
            is_pure_formatting = self._captions_differ_only_in_formatting(
                parsed.case_name or "", cl_case_name,
            )
            category = (
                WarningCategory.name_formatting_noise if is_pure_formatting
                else WarningCategory.cl_display_name_data_bug
            )
            return {
                "status": Status.VERIFIED,
                "warnings": [Warning(
                    category=category,
                    message=(
                        f'Brief caption "{parsed.case_name}" differs from '
                        f'CL caption "{cl_case_name}" but party-overlap '
                        f'confirms it is the same case.'
                    ),
                    details={"caption_sources_matched": [lbl for lbl, _ in overlap_hits]},
                )],
                "raw_response_summary": summary,
                "notes": f"party-overlap match via {overlap_hits[0][0]}",
                "confidence": 1.0,
            }

        return {
            "status": Status.WRONG_CASE,
            "warnings": [],
            "raw_response_summary": summary,
            "notes": "no party-overlap across cluster/docket/opinion sources",
            "confidence": 1.0,
        }

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

        cl_lower = cl_case_name.lower()

        if not parsed.plaintiff or parsed.plaintiff.lower() == "none":
            # No plaintiff parsed — could be "In re" case or other non-adversarial
            # style. Fall back to distinctive-word check on full case name.
            _skip = {"in", "re", "the", "matter", "of", "a", "an", "and", "for", "v", "v."}
            words = [w.rstrip(",.") for w in parsed.case_name.lower().split() if len(w) > 2]
            distinctive = [
                w for w in words
                if w not in _skip and w not in self._NONDISTINCTIVE_SURNAMES
            ]
            if not distinctive:
                return True  # nothing to check, trust citation lookup
            return any(w in cl_lower for w in distinctive)

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

        # For generic-government-DEFENDANT cases (X v. United States, X v. State,
        # X v. Commonwealth, X v. People), the defendant is not distinctive.
        # Require that CL's caption also has a generic-government suffix; if not,
        # reject so caption_investigation fires and can emit cl_display_name_data_bug.
        # If CL does have the suffix, compare plaintiff tokens for the match.
        _DEFENDANT_GENERIC_SUFFIXES = (
            " v. united states", " v united states",
            " v. state", " v state",
            " v. commonwealth", " v commonwealth",
            " v. people", " v people",
        )
        cited_lower = parsed.case_name.lower()
        if any(cited_lower.endswith(s) for s in _DEFENDANT_GENERIC_SUFFIXES):
            cl_has_suffix = any(s in cl_lower for s in _DEFENDANT_GENERIC_SUFFIXES)
            if not cl_has_suffix:
                return False
            # CL also has a generic-government defendant — compare plaintiff tokens.
            cited_plaintiff = (parsed.plaintiff or cited_lower.split(" v")[0]).lower()
            cited_plaintiff_norm = re.sub(r"[^a-z0-9 ]+", "", cited_plaintiff).strip()
            tokens = [t for t in re.findall(r"[a-z0-9]+", cited_plaintiff_norm) if len(t) >= 3]
            if tokens:
                return any(t in cl_lower for t in tokens)
            return True  # no distinctive tokens; trust citation lookup

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
    ) -> tuple[float, list[Diagnostic]]:
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

        Returns (score, list of mismatch Diagnostics).
        """
        mismatches: list[Diagnostic] = []

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
            mismatches.append(Diagnostic(
                "info",
                f"Low confidence: {' and '.join(missing)} not available "
                f"in citation text",
            ))

        # --- Score each component ---
        score = 0.0

        # Whether the candidate has at least one cited party on each side
        # (True when there is nothing to compare). Drives the Lever 2
        # party-mismatch penalty and the no-corroboration cap below.
        party_overlap = (
            self._party_overlap_ok(parsed, result_case_name)
            if (parsed.case_name and result_case_name) else True
        )
        # Whether the cited reporter/WL cite or docket number was positively
        # found on the candidate's record (set in the citation/docket blocks
        # below). Either match is an escape hatch that lets a real record
        # survive the cap even when its CL display name shows a different
        # party (cl_display_name_data_bug): a matching docket number or
        # reporter cite vouches for the record regardless of the caption.
        cite_corroborated = False
        docket_corroborated = False
        # Whether the cited docket number is PRESENT on both the citation and
        # the candidate record but DIFFERS (an active contradiction, as
        # opposed to merely absent). Drives the Lever 3 contradiction arm of
        # the no-corroboration cap below. NOTE: we deliberately do NOT track a
        # reporter/WL contradiction here — a cited reporter that CL lists
        # under a different *parallel* reporter (e.g. cited 144 S. Ct. 967,
        # CL has 601 U.S. 346) is the SAME case, not a contradiction, and
        # capping on it produced a real false negative (Muldrow, found by the
        # benchmark replay). Docket numbers have no benign "parallel" form.
        docket_contradicted = False

        # Case name similarity - using multi-factor matcher
        if parsed.case_name and result_case_name:
            name_sim = self.name_matcher.calculate_similarity(
                parsed.case_name,
                result_case_name
            )

            # Party-mismatch penalty (Lever 2): when the candidate caption
            # matches only ONE cited party and the other is absent, the name
            # similarity is surname-coincidence inflation, not a real match
            # (Johnson v. Mitchell -> Scudder v. Mitchell; Thompson v. Best ->
            # Thompson v. Thompson). Discount the name contribution only —
            # court/date/cite still score, so a real opinion whose CL display
            # name lists a different party survives on those signals. The
            # threshold-bucket diagnostics below intentionally read the
            # original (un-penalized) name_sim so their wording is unchanged.
            scored_name_sim = name_sim
            if not party_overlap:
                scored_name_sim *= _PARTY_MISMATCH_NAME_FACTOR
                mismatches.append(Diagnostic(
                    "name",
                    f'Party mismatch: found "{result_case_name}" shares only '
                    f'one party with cited "{parsed.case_name}"',
                ))
            score += w_name * scored_name_sim

            if name_sim < 0.6:
                mismatches.append(Diagnostic(
                    "name",
                    f'Name mismatch: cited "{parsed.case_name}" '
                    f'vs found "{result_case_name}"',
                ))
            elif name_sim < 0.85:
                mismatches.append(Diagnostic(
                    "name",
                    f'Name differs: cited "{parsed.case_name}" '
                    f'~ found "{result_case_name}" ({name_sim:.0%} similar)',
                ))
        elif parsed.case_name:
            mismatches.append(Diagnostic("name", "Case name not returned by API"))

        # Court match
        if can_eval_court and result_court:
            expected_court = lookup_court_id(parsed.court)
            if expected_court and expected_court == result_court:
                score += w_court
            elif expected_court:
                mismatches.append(Diagnostic(
                    "court",
                    f"Court mismatch: cited {parsed.court} ({expected_court}) "
                    f"vs found {result_court}",
                ))
            elif parsed.court.lower() == result_court.lower():
                # Direct match on raw court string (e.g. state courts)
                score += w_court
            else:
                mismatches.append(Diagnostic(
                    "court",
                    f"Court mismatch: cited {parsed.court} vs found {result_court}",
                ))
        elif parsed.court:
            mismatches.append(Diagnostic("court", f"Court {parsed.court} could not be verified"))

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
                            mismatches.append(Diagnostic(
                                "date",
                                f"Date close: cited {cited_date} vs filed {result_date}",
                            ))
                    else:
                        score += w_date  # same year, no month info to compare
                elif year_diff == 1:
                    score += w_date * 0.5
                    mismatches.append(Diagnostic(
                        "date",
                        f"Date close: cited {parsed.year} vs filed {result_date}",
                    ))
                else:
                    mismatches.append(Diagnostic(
                        "date",
                        f"Date mismatch: cited {parsed.year} vs filed {result_date}",
                    ))
            except (ValueError, IndexError):
                pass
        elif parsed.year:
            mismatches.append(Diagnostic("date", f"Year {parsed.year} could not be verified"))

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
                    docket_corroborated = True
                else:
                    docket_contradicted = True
                    mismatches.append(Diagnostic(
                        "docket",
                        f"Docket mismatch: cited {parsed.docket_number} "
                        f"vs found {result_docket}",
                    ))

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
                cite_corroborated = True
            elif not result_citation.strip():
                mismatches.append(Diagnostic(
                    "cite",
                    f"Reporter citation {cite_str} could not be confirmed "
                    f"(CourtListener has no reporter citations on file for this case)",
                ))
            else:
                mismatches.append(Diagnostic(
                    "cite",
                    f"Citation mismatch: cited {cite_str} "
                    f"but CourtListener has {result_citation}",
                ))
        elif parsed.wl_number:
            if parsed.wl_number in result_citation:
                score += w_cite
                cite_corroborated = True
            elif not result_citation.strip():
                mismatches.append(Diagnostic(
                    "cite",
                    f"WL number {parsed.wl_number} could not be confirmed "
                    f"(CourtListener has no citations on file for this case)",
                ))
            else:
                mismatches.append(Diagnostic(
                    "cite",
                    f"WL number {parsed.wl_number} not found "
                    f"in CourtListener citations: {result_citation}",
                ))

        # No-corroboration cap (Levers 2 + 3): the candidate is the wrong
        # record when a strong negative signal fires and nothing positively
        # vouches for it. Strong negatives:
        #   - party mismatch (Lever 2): caption matches only one cited party;
        #   - docket-number contradiction (Lever 3): the cited docket number is
        #     present on both sides but DIFFERS — the fake names a real case
        #     but a fabricated pinpoint (Lopez v. Bank of Am. -> the real BofA
        #     docket at a different docket number).
        # A reporter/WL *mismatch* is intentionally NOT a strong negative: a
        # cited reporter that CL lists under a different parallel reporter is
        # the same case (Muldrow: cited 144 S. Ct. 967, CL has 601 U.S. 346),
        # so capping on it is a false negative. Docket numbers have no benign
        # parallel form, so a docket contradiction is reliable.
        # Court+date agreement alone is coincidence (these fakes are crafted
        # to name a plausible real court and year). The escape hatch is a
        # positive docket-number or reporter/WL match, which vouches for the
        # record even when its CL display name or a typo'd pinpoint disagrees.
        # Contradiction is gated on PRESENT-and-differing, never absent, so a
        # real cite that CL simply has no docket/cite on file for is untouched.
        strong_negative = not party_overlap or docket_contradicted
        if strong_negative and not cite_corroborated and not docket_corroborated:
            score = min(score, _VERIFIED_SCORE_THRESHOLD - 0.01)

        return round(score, 4), mismatches

    # ------------------------------------------------------------------
    # Async verification
    # ------------------------------------------------------------------

    async def verify_async(
        self,
        async_client: AsyncCourtListenerClient,
        citation_text: str,
        parsed: ParsedCitation | None = None,
        quick_only: bool = False,
    ) -> VerificationResult:
        """Async version of verify(). Requires an AsyncCourtListenerClient.

        Uses the same scoring/matching logic as the sync version.
        """
        citation_text = citation_text.strip()

        if parsed is None:
            parsed = parse_citation(citation_text)

        builder = ResolutionPathBuilder()

        # Stage 1: Citation Lookup API
        hit_finalize: dict[str, Any] | None = None
        with builder.stage(
            StageName.citation_lookup,
            query={"text": citation_text[:200]},
        ) as t:
            try:
                lookup_results = await async_client.citation_lookup(citation_text)
                clusters_returned = sum(
                    len(lr.get("clusters", [])) for lr in lookup_results
                )
                for lr in lookup_results:
                    clusters = lr.get("clusters", [])
                    for cluster in clusters:
                        hit_finalize = self._process_citation_lookup_hit(
                            builder, t, citation_text, parsed, cluster, clusters_returned,
                        )
                        break
                    if hit_finalize is not None:
                        break
                if hit_finalize is None:
                    if quick_only:
                        t.no_match(
                            raw_response_summary={"clusters_returned": 0},
                            notes="Quick search only: not in citation lookup API",
                        )
                    else:
                        t.no_match(raw_response_summary={"clusters_returned": 0})
            except Exception as exc:
                logger.debug("Citation lookup failed", exc_info=True)
                t.errored(error_type=type(exc).__name__, notes=f"{type(exc).__name__}: {exc}")

        if hit_finalize is not None:
            # Phase 3 Task 5: caption_investigation (async mirror of sync verify()).
            if hit_finalize.pop("needs_caption_investigation", False):
                cluster = hit_finalize.pop("_cluster_for_investigation")
                with builder.stage(
                    StageName.caption_investigation,
                    query={
                        "cluster_id": cluster.get("id"),
                        "cited_case_name": parsed.case_name,
                        "cl_case_name": cluster.get("case_name", ""),
                    },
                ) as inv_t:
                    try:
                        inv_result = await self._investigate_caption_async(
                            parsed, cluster, async_client
                        )
                        inv_t.resolved(
                            confidence=inv_result["confidence"],
                            raw_response_summary=inv_result["raw_response_summary"],
                            notes=inv_result["notes"],
                        )
                        hit_finalize["warnings"] = inv_result["warnings"] or None
                        hit_finalize["status_override"] = inv_result["status"]
                    except Exception as exc:
                        logger.debug("caption_investigation failed", exc_info=True)
                        inv_t.errored(
                            error_type=type(exc).__name__,
                            notes=f"{type(exc).__name__}: {exc}",
                        )
                        # Defensive fallback: investigation errored. Emit the
                        # pre-Task-5 cl_display_name_data_bug warning so the
                        # consumer still knows a mismatch was flagged but the
                        # verifier could not classify it. Per design §2.8:
                        # refinement-stage failures do not trigger
                        # VERIFICATION_INCOMPLETE — the underlying verification
                        # (cluster exists, citation maps to it) still stands.
                        hit_finalize["warnings"] = [Warning(
                            category=WarningCategory.cl_display_name_data_bug,
                            message=(
                                f"Citation_lookup resolved the cluster, but caption_investigation "
                                f"could not complete ({type(exc).__name__}). The citation is verified "
                                f"(the cluster exists); the case-name divergence between the brief "
                                f"and CL's caption is unclassified. Per design §2.8, refinement-stage "
                                f"failures do not trigger VERIFICATION_INCOMPLETE."
                            ),
                        )]

            status = hit_finalize.pop("status_override", Status.VERIFIED)
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=status,
                **hit_finalize,
            )

        if quick_only:
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        # Step 2: Fuzzy search fallback
        return await self._search_fallback_async(builder, async_client, citation_text, parsed)

    async def _search_fallback_async(
        self,
        builder: ResolutionPathBuilder,
        async_client: AsyncCourtListenerClient,
        citation_text: str,
        parsed: ParsedCitation,
    ) -> VerificationResult:
        """Async version of _search_fallback().

        Phase 2 / Task 4: mirrors `_search_fallback`'s per-stage
        `builder.stage(...)` instrumentation one-for-one. The
        builder.stage() context manager is sync; only the I/O calls
        inside the block are awaited.
        """
        court_id, filed_after, filed_before = self._build_search_params(parsed)

        # Insufficient-data short-circuit (mirror of sync): without both
        # court and date we don't have enough signal to verify reliably.
        if not parsed.court and not parsed.year:
            with builder.stage(
                StageName.opinion_search,
                query={
                    "q": parsed.case_name,
                    "court": court_id,
                    "filed_after": filed_after,
                    "filed_before": filed_before,
                },
            ) as t:
                t.no_match(
                    raw_response_summary={"candidate_count": 0},
                    notes=(
                        "Insufficient data to verify: citation text is missing "
                        "both court and date. A match cannot be confirmed with "
                        "name alone. Try adding the court and year parenthetical "
                        "(e.g. '(E.D. Tenn. 2020)') to the citation text."
                    ),
                )
            return self._finalize_result(
                builder,
                citation_text=citation_text,
                parsed=parsed,
                status=Status.NOT_FOUND,
            )

        opinion_candidates: list[CandidateMatch] = []
        recap_candidates: list[CandidateMatch] = []

        # Stage: opinion_search
        if parsed.case_name:
            with builder.stage(
                StageName.opinion_search,
                query={
                    "q": parsed.case_name,
                    "court": court_id,
                    "filed_after": filed_after,
                    "filed_before": filed_before,
                },
            ) as t:
                try:
                    results = await async_client.search_opinions(
                        q=parsed.case_name,
                        court=court_id,
                        filed_after=filed_after,
                        filed_before=filed_before,
                    )
                    opinion_candidates = self._process_results(results, parsed)
                    if opinion_candidates:
                        best = max(opinion_candidates, key=lambda c: c.score)
                        summary = {
                            "candidate_count": len(opinion_candidates),
                            "best_score": best.score,
                            "best_case_name": best.case_name,
                            "best_cluster_id": best.cluster_id,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"candidate_count": 0})
                except Exception as exc:
                    logger.debug("Opinion search failed", exc_info=True)
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Guards for RECAP: federal-only, no credible match yet.
        is_state_court = self._is_state_court_citation(parsed, court_id)
        has_credible_match = any(c.score >= 0.5 for c in opinion_candidates)

        # Stage: recap_document_search (by docket_number)
        if not has_credible_match and not is_state_court and parsed.docket_number:
            with builder.stage(
                StageName.recap_document_search,
                query={"docket_number": parsed.docket_number},
            ) as t:
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
                    rd_candidates = await self._process_recap_results_async(
                        async_client, results, parsed
                    )
                    recap_candidates.extend(rd_candidates)
                    if rd_candidates:
                        best = max(rd_candidates, key=lambda c: c.score)
                        summary = {
                            "docket_count": len(rd_candidates),
                            "best_score": best.score,
                            "best_docket_id": best.docket_id,
                            "best_case_name": best.case_name,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"docket_count": 0})
                except Exception as exc:
                    logger.debug(
                        "RECAP search by docket number failed", exc_info=True
                    )
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Stage: recap_docket_search (by case_name)
        if not has_credible_match and not is_state_court and parsed.case_name:
            with builder.stage(
                StageName.recap_docket_search,
                query={"q": parsed.case_name, "court": court_id},
            ) as t:
                try:
                    results = await async_client.search_recap(
                        q=parsed.case_name,
                        court=court_id,
                    )
                    rd_candidates = await self._process_recap_results_async(
                        async_client, results, parsed
                    )
                    recap_candidates.extend(rd_candidates)
                    if rd_candidates:
                        best = max(rd_candidates, key=lambda c: c.score)
                        summary = {
                            "docket_count": len(rd_candidates),
                            "best_score": best.score,
                            "best_docket_id": best.docket_id,
                            "best_case_name": best.case_name,
                        }
                        notes = self._stage_notes_for_candidate(best)
                        if best.score >= _VERIFIED_SCORE_THRESHOLD:
                            t.resolved(
                                confidence=best.score,
                                raw_response_summary=summary,
                                notes=notes,
                            )
                        else:
                            t.no_match(raw_response_summary=summary, notes=notes)
                    else:
                        t.no_match(raw_response_summary={"docket_count": 0})
                except Exception as exc:
                    logger.debug("RECAP search failed", exc_info=True)
                    t.errored(
                        error_type=type(exc).__name__,
                        notes=f"{type(exc).__name__}: {exc}",
                    )

        # Aggregate across stages and finalize. The per-stage entries are
        # already appended above; _build_fallback_result_async does NOT touch
        # the builder — it only picks the winning candidate and finalizes.
        # Uses the async doc-detail fetch to refine page_count + is_free_on_pacer
        # when search_recap omits them (those fields only populate on the
        # /recap-documents/{id}/ detail endpoint).
        candidates = opinion_candidates + recap_candidates
        return await self._build_fallback_result_async(
            builder, citation_text, parsed, candidates, court_id, async_client,
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

            # Hard-gate before the (expensive) docket-entries fetch: skip
            # dockets with no name overlap or an impossible cite-before-filing
            # date. Parity with the opinion-search path's gates (Lever 1).
            date_filed = r.get("dateFiled") or r.get("date_filed", "")
            if self._recap_result_gated(parsed, case_name, date_filed):
                continue

            docs = r.get("recap_documents", [])

            if not self._has_recap_date_match(parsed, docs):
                if parsed.year and docket_id:
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
        for label, after, before in self._docket_date_ranges(parsed):
            try:
                entries = await async_client.get_docket_entries(
                    docket_id=docket_id,
                    date_filed_after=after,
                    date_filed_before=before,
                )
                if self._extract_docket_entry_docs(entries, docs):
                    return
            except Exception:
                logger.debug(
                    "Docket entries query (%s) failed for docket %s",
                    label,
                    docket_id,
                    exc_info=True,
                )

    async def _batch_citation_lookup(
        self,
        async_client: AsyncCourtListenerClient,
        citations: list[str],
    ) -> dict[int, dict]:
        """Batch citation lookup via CL's citation-lookup API.

        Joins citations into a text block, POSTs to the API, and maps
        results back to citation indices using start_index/end_index.

        Chunks the text block by both character count (50K, to stay under
        the 64K request size limit) and citation count (150, because CL's
        citation-lookup response silently truncates beyond ~200 entries —
        observed 2026-05-02 on a 437-citation batch where citations past
        the cutoff returned no entries even though they resolve when sent
        alone). Each chunk is retried up to 3 times; on total failure the
        chunk falls back to individual citation_lookup() calls.

        Returns ``{index: cluster}`` for citations with hits.
        """
        if not citations:
            return {}

        CHUNK_SIZE = 50_000
        MAX_CITATIONS_PER_CHUNK = 150
        MAX_ATTEMPTS = 3

        # Build text block and track per-citation offsets
        lines: list[str] = []
        offsets: list[tuple[int, int, int]] = []  # (orig_index, start, end)
        pos = 0
        for i, cite in enumerate(citations):
            start = pos
            lines.append(cite)
            pos += len(cite)
            end = pos
            offsets.append((i, start, end))
            lines.append("\n")
            pos += 1  # newline

        # Split into chunks bounded by both char count and citation count
        chunks: list[tuple[str, list[tuple[int, int, int]]]] = []
        chunk_text = ""
        chunk_offsets: list[tuple[int, int, int]] = []
        for i, cite in enumerate(citations):
            line = cite + "\n"
            if chunk_text and (
                len(chunk_text) + len(line) > CHUNK_SIZE
                or len(chunk_offsets) >= MAX_CITATIONS_PER_CHUNK
            ):
                chunks.append((chunk_text, chunk_offsets))
                chunk_text = ""
                chunk_offsets = []
            start = len(chunk_text)
            chunk_text += line
            end = start + len(cite)
            chunk_offsets.append((offsets[i][0], start, end))
        if chunk_text:
            chunks.append((chunk_text, chunk_offsets))

        results: dict[int, dict] = {}

        for chunk_text, chunk_offsets in chunks:
            response = None
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await async_client.citation_lookup(chunk_text)
                    break
                except Exception:
                    logger.debug(
                        "Batch citation lookup attempt %d failed",
                        attempt + 1,
                        exc_info=True,
                    )
                    if attempt < MAX_ATTEMPTS - 1:
                        await asyncio.sleep(1.0 * (2 ** attempt))

            if response is None:
                # Fallback: individual citation_lookup for this chunk
                for orig_idx, _, _ in chunk_offsets:
                    try:
                        individual = await async_client.citation_lookup(
                            citations[orig_idx]
                        )
                        for lr in individual:
                            clusters = lr.get("clusters", [])
                            if clusters:
                                results[orig_idx] = clusters[0]
                                break
                    except Exception:
                        logger.debug(
                            "Individual citation lookup fallback failed "
                            "for index %d",
                            orig_idx,
                            exc_info=True,
                        )
                continue

            # Map results back using start_index / end_index
            for entry in response:
                start_idx = entry.get("start_index", -1)
                clusters = entry.get("clusters", [])
                if not clusters or start_idx < 0:
                    continue
                # Find which citation this start_index falls within
                for orig_idx, offset_start, offset_end in chunk_offsets:
                    if offset_start <= start_idx < offset_end:
                        if orig_idx not in results:
                            results[orig_idx] = clusters[0]
                        break

        return results

    async def verify_batch(
        self,
        citations: list[str],
        parsed_citations: list[ParsedCitation | None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        quick_only: bool = False,
        *,
        client: AsyncCourtListenerClient | None = None,
    ) -> list[VerificationResult]:
        """Verify multiple citations concurrently.

        Uses a batch citation-lookup call to resolve most citations in
        a single API request.  Citations with a batch hit go directly
        to ``_process_citation_lookup_hit()`` (no per-citation API call).
        Citations without a hit fall through to the search fallback
        pipeline (opinion search + RECAP).

        Parameters
        ----------
        citations : list[str]
            Citation strings to verify.
        parsed_citations : list[ParsedCitation | None] | None
            Optional pre-parsed citations (same length as *citations*).
            When provided, skips internal parsing for non-None entries.
        progress_callback : callable, optional
            Called as progress_callback(completed, total) after each citation.
        quick_only : bool
            When True, only run the citation lookup.  Citations without
            a batch hit return NOT_FOUND immediately.
        client : AsyncCourtListenerClient, optional
            Caller-owned client (e.g. one carrying a per-request BYOK token
            from a web route). When supplied, the caller owns its lifecycle
            and ``verify_batch`` will not open/close its own client.
            When ``None`` (default), an internal client is opened.

        Returns results in the same order as the input citations.
        """
        if parsed_citations is None:
            parsed_citations = [None] * len(citations)

        total = len(citations)

        # Parse all citations upfront
        parsed_list: list[ParsedCitation] = []
        stripped: list[str] = []
        for cite, pre_parsed in zip(citations, parsed_citations):
            s = cite.strip()
            stripped.append(s)
            parsed_list.append(pre_parsed if pre_parsed is not None else parse_citation(s))

        if client is not None:
            return await self._run_batch(
                client, stripped, parsed_list, total,
                progress_callback, quick_only,
            )
        async with AsyncCourtListenerClient() as owned_client:
            return await self._run_batch(
                owned_client, stripped, parsed_list, total,
                progress_callback, quick_only,
            )

    async def _run_batch(
        self,
        client: AsyncCourtListenerClient,
        stripped: list[str],
        parsed_list: list[ParsedCitation],
        total: int,
        progress_callback: Callable[[int, int], None] | None,
        quick_only: bool,
    ) -> list[VerificationResult]:
        """Inner batch driver shared by both the owned-client and
        caller-supplied-client paths of ``verify_batch``.
        """
        completed = 0
        results: list[VerificationResult | None] = [None] * total

        # Batch citation lookup (single API call for all citations)
        batch_hits = await self._batch_citation_lookup(client, stripped)

        # Process batch hits.  Each citation gets a fresh builder; the
        # citation_lookup stage is opened so the resulting result carries
        # a resolution_path entry like the sync surface does.  If the
        # hit flags a name-mismatch, run caption_investigation in its
        # own stage block (mirror of verify_async at verifier.py:2428-2482).
        for idx, cluster in batch_hits.items():
            builder = ResolutionPathBuilder()
            hit_finalize: dict[str, Any] | None = None
            with builder.stage(
                StageName.citation_lookup,
                query={"text": stripped[idx][:200], "via": "batch"},
            ) as t:
                hit_finalize = self._process_citation_lookup_hit(
                    builder, t, stripped[idx], parsed_list[idx], cluster,
                    clusters_returned=1,
                )

            if hit_finalize is not None and hit_finalize.pop(
                "needs_caption_investigation", False
            ):
                inv_cluster = hit_finalize.pop("_cluster_for_investigation")
                with builder.stage(
                    StageName.caption_investigation,
                    query={
                        "cluster_id": inv_cluster.get("id"),
                        "cited_case_name": parsed_list[idx].case_name,
                        "cl_case_name": inv_cluster.get("case_name", ""),
                    },
                ) as inv_t:
                    try:
                        inv_result = await self._investigate_caption_async(
                            parsed_list[idx], inv_cluster, client
                        )
                        inv_t.resolved(
                            confidence=inv_result["confidence"],
                            raw_response_summary=inv_result["raw_response_summary"],
                            notes=inv_result["notes"],
                        )
                        hit_finalize["warnings"] = inv_result["warnings"] or None
                        hit_finalize["status_override"] = inv_result["status"]
                    except Exception as exc:
                        logger.debug("caption_investigation failed", exc_info=True)
                        inv_t.errored(
                            error_type=type(exc).__name__,
                            notes=f"{type(exc).__name__}: {exc}",
                        )
                        # Same defensive fallback as verify_async: surface the
                        # mismatch as a cl_display_name_data_bug warning rather
                        # than promoting to VERIFICATION_INCOMPLETE.  See
                        # design §2.8 — refinement-stage failures preserve the
                        # underlying verification (the cluster exists, the
                        # citation maps to it).
                        hit_finalize["warnings"] = [Warning(
                            category=WarningCategory.cl_display_name_data_bug,
                            message=(
                                f"Citation_lookup resolved the cluster, but caption_investigation "
                                f"could not complete ({type(exc).__name__}). The citation is verified "
                                f"(the cluster exists); the case-name divergence between the brief "
                                f"and CL's caption is unclassified. Per design §2.8, refinement-stage "
                                f"failures do not trigger VERIFICATION_INCOMPLETE."
                            ),
                        )]

            status = (hit_finalize or {}).pop("status_override", Status.VERIFIED)
            results[idx] = self._finalize_result(
                builder,
                citation_text=stripped[idx],
                parsed=parsed_list[idx],
                status=status,
                **(hit_finalize or {}),
            )
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        # Identify misses
        miss_indices = [i for i in range(total) if i not in batch_hits]

        if quick_only:
            # No fallback — return NOT_FOUND for misses
            for idx in miss_indices:
                builder = ResolutionPathBuilder()
                with builder.stage(
                    StageName.citation_lookup,
                    query={"text": stripped[idx][:200], "via": "batch"},
                ) as t:
                    t.no_match(
                        raw_response_summary={"clusters_returned": 0, "via": "batch"},
                        notes="Quick search only: not in citation lookup API",
                    )
                results[idx] = self._finalize_result(
                    builder,
                    citation_text=stripped[idx],
                    parsed=parsed_list[idx],
                    status=Status.NOT_FOUND,
                )
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
        else:
            # Search fallback for misses (opinion search + RECAP).
            # Each citation gets a fresh builder. The citation_lookup
            # stage records a no_match (Task 5 will refine batch
            # instrumentation) before delegating to the search fallback.
            async def _fallback(idx: int) -> None:
                nonlocal completed
                builder = ResolutionPathBuilder()
                with builder.stage(
                    StageName.citation_lookup,
                    query={"text": stripped[idx][:200], "via": "batch"},
                ) as t:
                    t.no_match(
                        raw_response_summary={"clusters_returned": 0, "via": "batch"},
                    )
                results[idx] = await self._search_fallback_async(
                    builder, client, stripped[idx], parsed_list[idx]
                )
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

            tasks = [_fallback(idx) for idx in miss_indices]
            await asyncio.gather(*tasks)

        return list(results)  # type: ignore[arg-type]
