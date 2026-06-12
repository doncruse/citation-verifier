"""Proposition verification pipeline — idempotent verbs over a workdir.

Evolved from brief_pipeline.py (pipeline-redesign design §2); brief_pipeline
remains importable as a deprecated alias of this module for one minor
version. Verbs land incrementally: verify/merge (§10 step 2) are here;
check-quotes/crosscheck/triage/assess/apply-assessments/report follow.
"""

from __future__ import annotations

import csv
import difflib
import json as json_mod
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import AsyncCourtListenerClient
from .models import Status, VerificationResult
from .report_template import generate_report_html
from .verifier import CitationVerifier


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MergeStats:
    """Statistics from merging verification results into claims.csv."""
    matched: int = 0
    unmatched: int = 0
    unmatched_claims: list[str] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    opinion_count: int = 0


@dataclass
class Wave1Result:
    """Output of wave1_verify_and_download."""
    results: list[VerificationResult]
    miss_indices: list[int]
    download_stats: dict[str, int] = field(default_factory=dict)


@dataclass
class Wave2Result:
    """Output of wave2_fallback_and_download."""
    results: list[VerificationResult]
    download_stats: dict[str, int] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Output of full_pipeline."""
    wave1: Wave1Result
    wave2: Wave2Result
    merge: MergeStats


# ---------------------------------------------------------------------------
# Helpers — pinpoint stripping, filenames, CSV I/O
# ---------------------------------------------------------------------------

# Matches ", 527" or ", at 527" or ", 527-30" at end of volume/page cite
_PINPOINT_RE = re.compile(
    r",\s+(?:at\s+)?\d+(?:\s*[-\u2013]\s*\d+)?\s*(?=\(|$)"
)


def _strip_pinpoint(cite: str) -> str:
    """Remove pinpoint page references from a citation string."""
    return _PINPOINT_RE.sub(" ", cite).strip()


def _normalize_for_match(cite: str) -> str:
    """Normalize a citation for matching: strip pinpoint, lowercase, collapse whitespace."""
    s = _strip_pinpoint(cite)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_quote_text(text: str) -> str:
    """Normalize quoted text for fuzzy matching.

    Strips bracketed alterations, ellipses, smart quotes, and excess whitespace.
    """
    # Smart quotes to straight
    s = text.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    # Strip bracketed alterations: [T] -> t (lowercase), [word] -> ""
    s = re.sub(r"\[([A-Z])\]", lambda m: m.group(1).lower(), s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    # Strip ellipses
    s = s.replace("\u2026", " ")  # unicode ellipsis
    s = re.sub(r"\.{3,}", " ", s)  # three+ dots
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _sanitize_filename(case_name: str) -> str:
    """Convert a case name to a safe filename (no extension)."""
    # Replace common separators with underscore
    s = re.sub(r"\s+v\.?\s+", "_v_", case_name)
    # Keep only alphanumeric, underscores, hyphens
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", s)
    # Collapse multiple underscores
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:120]  # cap length


def _find_opinion_file(workdir: Path, case_name: str) -> str:
    """Scan opinions/ for a file matching the case name. Returns relative path or ''."""
    opinions_dir = workdir / "opinions"
    if not opinions_dir.exists():
        return ""

    normalized = re.sub(r"[^a-z0-9]", "", case_name.lower())

    for f in opinions_dir.iterdir():
        if f.is_file():
            fn = re.sub(r"[^a-z0-9]", "", f.stem.lower())
            if fn and normalized and (fn in normalized or normalized in fn):
                return f"opinions/{f.name}"

    return ""


_PASSTHROUGH_FIELDS = [
    "quoted_text", "quote_check", "quote_check_worst",
    # Phase 1c extraction (brief-side text)
    "brief_sentence",
    # Phase 2c assessment output — three agent-authored blocks + badge
    "brief_block", "opinion_block", "finding_analysis", "badge_label",
    # Legacy (pre-finding_analysis) — kept so old briefs can regenerate reports
    "opinion_text", "explanation",
]

_VR_FIELDS = [
    "citation", "status", "confidence", "cl_url",
    "matched_name", "diagnostics_cat", "diagnostics_msg",
    "syllabus",
]


def _write_verification_csv(
    workdir: Path,
    citations: list[str],
    results: list[VerificationResult],
    append: bool = False,
) -> None:
    """Write or append verification results to verification_results.csv."""
    path = workdir / "verification_results.csv"
    mode = "a" if append else "w"
    write_header = not append or not path.exists()

    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_VR_FIELDS)
        if write_header:
            writer.writeheader()
        for cite, result in zip(citations, results):
            # v0.3 shape: structured Warnings replace Diagnostics; the legacy
            # diagnostic-bridge text lives in resolution_path[-1].notes
            # (Task 2 packs old Diagnostics there).
            warn_cats = [w.category.value for w in result.warnings]
            warn_msgs = [w.message for w in result.warnings]
            stage_notes = ""
            # SS11 bug 1 fix: the caption lives under stage-specific summary
            # keys; the accessor is the only sanctioned read surface.
            matched_name = result.matched_case_name
            if result.resolution_path:
                last = result.resolution_path[-1]
                if last.notes:
                    stage_notes = last.notes
            confidence = result.headline_confidence or 0.0
            # Combine warning messages and stage notes for the diagnostic
            # message column, preserving the old "; "-joined freeform shape.
            diag_msg_parts = list(warn_msgs)
            if stage_notes:
                diag_msg_parts.append(stage_notes)
            writer.writerow({
                "citation": cite,
                "status": result.status.value,
                "confidence": f"{confidence:.2f}",
                "cl_url": result.final_ids.absolute_url or "",
                "matched_name": matched_name,
                "diagnostics_cat": "; ".join(warn_cats),
                "diagnostics_msg": "; ".join(diag_msg_parts),
                # Surfaced via VerificationResult.syllabus accessor, which
                # walks resolution_path to the citation_lookup entry's
                # raw_response_summary (joined syllabus + nature_of_suit).
                # Restored from Phase 1 retro Q5 (Path A).
                "syllabus": result.syllabus or "",
            })


# ---------------------------------------------------------------------------
# Opinion downloading
# ---------------------------------------------------------------------------

# Phase 3 produces all four VERIFIED_* statuses; Phase 4 confirms each
# has a populated absolute_url and is download-eligible. WRONG_CASE,
# NOT_FOUND, and VERIFICATION_INCOMPLETE stay excluded -- downloading
# their (missing) opinion text doesn't make sense.
# Check Cite (2026-06-11): CITE_UNCONFIRMED is included -- it carries the
# winning stage's IDs, and downloading the matched case's text is exactly
# what lets the assessment agent show the brief's proposition isn't in it.
_DOWNLOADABLE_STATUSES = {
    Status.VERIFIED,
    Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP,
    Status.VERIFIED_DOCKET_ONLY,
    Status.CITE_UNCONFIRMED,
}


# Phase 4 Task 8: deterministic status -> badge-label fallback for the
# report-finding badge when the agent-authored badge_label is absent
# (legacy claims.csv or pre-agent runs). The agent-authored path is
# unchanged; this only governs the fallback render. Mapped by status
# value string (matches the cl_status column in claims.csv).
_STATUS_BADGE_FALLBACK: dict[str, str] = {
    "WRONG_CASE": "Case mismatch -- cite resolves to a different case",
    "CITE_UNCONFIRMED": "Check cite -- case found by name, cited location unconfirmed",
    "VERIFIED_PARTIAL": "Verified -- parallel cite only",
    "VERIFIED_VIA_RECAP": "Verified via RECAP",
    "VERIFIED_DOCKET_ONLY": "Docket only -- no opinion text",
    "VERIFICATION_INCOMPLETE": "Verification incomplete -- infrastructure error",
    "INSUFFICIENT_DATA": "Insufficient data -- citation lacks court and year",
}

# Threshold (chars of visible text) below which we suspect a downloaded
# "opinion" is actually a short order (vacatur, amendment notice, mandate,
# rehearing denial). When we hit one of these, we look for a sibling
# cluster on the same docket with substantive content.
_SHORT_OPINION_THRESHOLD = 3000


def _visible_text_len(data: dict[str, Any]) -> int:
    """Return the length of human-readable text in an opinion data dict."""
    text = data.get("text") or ""
    if not text:
        return 0
    if data.get("format") == "html":
        stripped = re.sub(r"<[^>]+>", " ", text)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return len(stripped)
    return len(text.strip())


async def _find_substantive_sibling(
    client: AsyncCourtListenerClient,
    matched_url: str,
    current_len: int,
) -> dict[str, Any] | None:
    """Look for a sibling cluster on the same docket with substantive content.

    Triggered when the primary cluster's opinion is suspiciously short (e.g.
    a vacatur order sitting in its own CL cluster while the real merits
    opinion lives in a separate cluster on the same docket — the Hertz 3d Cir.
    case was the motivating example).

    Returns a new opinion data dict (with source_url set to the sibling's URL)
    if a sibling has more than 2x the current text AND clears the short-opinion
    threshold; otherwise returns None.
    """
    cluster_match = re.search(r"/opinion/(\d+)/", matched_url)
    if not cluster_match:
        return None
    current_cluster_id = cluster_match.group(1)

    try:
        current_cluster = await client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{current_cluster_id}/",
        )
        if not isinstance(current_cluster, dict):
            return None
        docket_url = current_cluster.get("docket") or ""
        if not docket_url or not isinstance(docket_url, str):
            return None
        docket_id = docket_url.rstrip("/").split("/")[-1]

        resp = await client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/",
            params={"docket": docket_id},
        )
        siblings = resp.get("results", []) if isinstance(resp, dict) else []
    except Exception:
        return None

    best: dict[str, Any] | None = None
    best_len = current_len
    for sib in siblings:
        if not isinstance(sib, dict):
            continue
        sib_id = str(sib.get("id") or "")
        if not sib_id or sib_id == current_cluster_id:
            continue
        sib_abs = sib.get("absolute_url", "")
        if sib_abs and not sib_abs.startswith("http"):
            sib_abs = f"https://www.courtlistener.com{sib_abs}"
        if not sib_abs:
            continue
        try:
            sib_data = await client.get_opinion_text_with_metadata(
                sib_abs, prefer_html=True,
            )
        except Exception:
            continue
        if not isinstance(sib_data, dict):
            continue
        sib_len = _visible_text_len(sib_data)
        if sib_len > best_len * 2 and sib_len >= _SHORT_OPINION_THRESHOLD:
            sib_data["source_url"] = sib_abs
            best = sib_data
            best_len = sib_len
    return best


async def _download_opinion(
    client: AsyncCourtListenerClient,
    workdir: Path,
    result: VerificationResult,
    citation: str,
) -> str | None:
    """Download opinion text for a verified result. Returns saved filename or None."""
    matched_url = result.final_ids.absolute_url
    if not matched_url:
        return None

    opinions_dir = workdir / "opinions"
    opinions_dir.mkdir(exist_ok=True)

    try:
        data = await client.get_opinion_text_with_metadata(
            matched_url, prefer_html=True,
        )
        if not data:
            return None

        # If the matched cluster is a short order (vacatur, amendment notice,
        # rehearing denial), look for a sibling cluster on the same docket
        # carrying the substantive merits opinion and swap to that.
        if _visible_text_len(data) < _SHORT_OPINION_THRESHOLD:
            better = await _find_substantive_sibling(
                client, matched_url, _visible_text_len(data),
            )
            if better is not None:
                new_url = better["source_url"]
                m = re.search(r"/opinion/(\d+)/", new_url)
                swap_note = (
                    f"Matched cluster looked like a short order "
                    f"({_visible_text_len(data)} chars); swapped to sibling "
                    f"cluster {m.group(1) if m else '?'} on same docket with "
                    f"substantive content ({_visible_text_len(better)} chars)."
                )
                # TODO(phase-3): consider adding a `sibling_swap` WarningCategory
                # for this operational note. Phase 1's closed-set WarningCategory
                # has no slot for it (design §2.6); adding one requires a schema
                # CHANGELOG entry which is out of scope for Task 4. Until then,
                # we append to the resolving stage's notes (the legacy
                # diagnostic bridge).
                if result.resolution_path:
                    last = result.resolution_path[-1]
                    last.notes = (
                        f"{last.notes}; {swap_note}" if last.notes else swap_note
                    )
                data = better
                # Update FinalIds to reflect the swap so verification_results.csv
                # persists the new URL (CLAUDE.md: CSV is written after downloads).
                result.final_ids.absolute_url = new_url
                if m:
                    try:
                        result.final_ids.cluster_id = int(m.group(1))
                    except ValueError:
                        pass
                if better.get("case_name") and result.resolution_path:
                    result.resolution_path[-1].raw_response_summary["case_name"] = (
                        better["case_name"]
                    )

        fmt = data.get("format", "text")
        matched_case_name = ""
        if result.resolution_path:
            matched_case_name = (
                result.resolution_path[-1].raw_response_summary.get("case_name", "")
                or ""
            )
        case_name = matched_case_name or data.get("case_name", "")
        if not case_name:
            # Fall back to citation name
            case_name = citation.split(",")[0].strip()

        base = _sanitize_filename(case_name)
        if not base:
            base = "unknown"

        if fmt == "pdf":
            pdf_bytes = data.get("pdf_bytes")
            if not pdf_bytes:
                return None
            filename = f"{base}.pdf"
            (opinions_dir / filename).write_bytes(pdf_bytes)
            return filename

        text = data.get("text", "")
        if not text or not text.strip():
            return None

        ext = ".html" if fmt == "html" else ".txt"
        filename = f"{base}{ext}"
        (opinions_dir / filename).write_text(text, encoding="utf-8")
        return filename

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Wave 1: batch citation lookup + download
# ---------------------------------------------------------------------------

async def wave1_verify_and_download(
    workdir: Path,
    citations: list[str],
    progress_callback: Any = None,
) -> Wave1Result:
    """Wave 1: quick batch lookup + download opinions for hits.

    Uses verify_batch(quick_only=True) for a single API call,
    then downloads opinions for all resolved citations.
    """
    workdir = Path(workdir)
    verifier = CitationVerifier()

    results = await verifier.verify_batch(
        citations, quick_only=True, progress_callback=progress_callback,
    )

    # Identify misses for wave2
    miss_indices = [
        i for i, r in enumerate(results)
        if r.status not in _DOWNLOADABLE_STATUSES
    ]

    # Download opinions for hits (may mutate result.final_ids.absolute_url
    # if the pipeline swaps to a substantive sibling cluster — see
    # _download_opinion)
    download_stats = {"downloaded": 0, "failed": 0, "skipped": 0}

    async with AsyncCourtListenerClient() as client:
        for i, (cite, result) in enumerate(zip(citations, results)):
            if result.status not in _DOWNLOADABLE_STATUSES:
                download_stats["skipped"] += 1
                continue

            filename = await _download_opinion(client, workdir, result, cite)
            if filename:
                download_stats["downloaded"] += 1
            else:
                download_stats["failed"] += 1

    # Write verification_results.csv after downloads so any URL swaps persist
    _write_verification_csv(workdir, citations, results)

    return Wave1Result(
        results=results,
        miss_indices=miss_indices,
        download_stats=download_stats,
    )


# ---------------------------------------------------------------------------
# Wave 2: fallback search for misses + download
# ---------------------------------------------------------------------------

async def wave2_fallback_and_download(
    workdir: Path,
    citations: list[str],
    miss_indices: list[int],
    progress_callback: Any = None,
) -> Wave2Result:
    """Wave 2: full pipeline verification for citations missed in wave1.

    Uses verify_batch() without quick_only — opinion search + RECAP fallback.
    Appends results to verification_results.csv and downloads any resolved opinions.
    """
    workdir = Path(workdir)

    if not miss_indices:
        return Wave2Result(results=[], download_stats={"downloaded": 0, "failed": 0, "skipped": 0})

    miss_citations = [citations[i] for i in miss_indices]
    verifier = CitationVerifier()

    results = await verifier.verify_batch(
        miss_citations, progress_callback=progress_callback,
    )

    # Download opinions for newly resolved citations (may mutate
    # result.final_ids.absolute_url when swapping to a substantive sibling
    # cluster)
    download_stats = {"downloaded": 0, "failed": 0, "skipped": 0}

    async with AsyncCourtListenerClient() as client:
        for cite, result in zip(miss_citations, results):
            if result.status not in _DOWNLOADABLE_STATUSES:
                download_stats["skipped"] += 1
                continue

            filename = await _download_opinion(client, workdir, result, cite)
            if filename:
                download_stats["downloaded"] += 1
            else:
                download_stats["failed"] += 1

    # Append to verification_results.csv after downloads so URL swaps persist
    _write_verification_csv(workdir, miss_citations, results, append=True)

    return Wave2Result(
        results=results,
        download_stats=download_stats,
    )


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def full_pipeline(
    workdir: Path,
    citations: list[str],
    progress_callback: Any = None,
) -> PipelineResult:
    """Run wave1 + wave2 + merge in sequence."""
    w1 = await wave1_verify_and_download(workdir, citations, progress_callback)
    w2 = await wave2_fallback_and_download(workdir, citations, w1.miss_indices, progress_callback)
    m = merge_claims(workdir)
    return PipelineResult(wave1=w1, wave2=w2, merge=m)


# ---------------------------------------------------------------------------
# merge_claims (Task 3 — already implemented)
# ---------------------------------------------------------------------------

def merge_claims(workdir: Path) -> MergeStats:
    """Merge verification_results.csv into claims.csv.

    Reads both files, joins on base citation (pinpoint-stripped),
    writes updated claims.csv with verification columns added.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"
    vr_path = workdir / "verification_results.csv"

    stats = MergeStats()

    # Read verification results into a lookup by normalized citation
    vr_lookup: dict[str, dict[str, str]] = {}
    if vr_path.exists():
        with open(vr_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = _normalize_for_match(row.get("citation", ""))
                if key:
                    vr_lookup[key] = row

    # Read claims
    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    # Merge columns
    output_fields = [
        "page", "proposition", "cited_case",
        "retrieved_case", "supporting_language", "assessment",
        "cl_url", "cl_status", "diagnostics", "opinion_file",
        "syllabus",
    ]
    if claims:
        for col in _PASSTHROUGH_FIELDS:
            if col in claims[0]:
                output_fields.append(col)

    merged_rows: list[dict[str, str]] = []
    for claim in claims:
        cited = claim.get("cited_case", "")
        key = _normalize_for_match(cited)

        vr = vr_lookup.get(key, {})

        status = vr.get("status", "")
        url = vr.get("cl_url", "")
        matched_name = vr.get("matched_name", "")
        diag_msg = vr.get("diagnostics_msg", "")

        if status:
            stats.matched += 1
            stats.statuses[status] = stats.statuses.get(status, 0) + 1
        else:
            stats.unmatched += 1
            if cited:
                stats.unmatched_claims.append(cited)

        # Find opinion file
        opinion_file = ""
        if matched_name:
            opinion_file = _find_opinion_file(workdir, matched_name)
        if not opinion_file and cited:
            name_part = cited.split(",")[0].strip()
            opinion_file = _find_opinion_file(workdir, name_part)

        if opinion_file:
            stats.opinion_count += 1

        row = {
            "page": claim.get("page", ""),
            "proposition": claim.get("proposition", ""),
            "cited_case": cited,
            "retrieved_case": matched_name,
            "supporting_language": claim.get("supporting_language", ""),
            "assessment": claim.get("assessment", ""),
            "cl_url": url,
            "cl_status": status,
            "diagnostics": diag_msg,
            "opinion_file": opinion_file,
            "syllabus": vr.get("syllabus", ""),
        }
        for col in _PASSTHROUGH_FIELDS:
            if col in claim:
                row[col] = claim[col]
        merged_rows.append(row)

    # Write updated claims.csv
    with open(claims_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(merged_rows)

    return stats


# ---------------------------------------------------------------------------
# Quote checking
# ---------------------------------------------------------------------------

@dataclass
class QuoteCheckStats:
    """Statistics from check_quotes."""
    total_claims: int = 0
    checked: int = 0
    no_quotes: int = 0
    no_opinion: int = 0
    verbatim: int = 0
    close: int = 0
    fabricated: int = 0


def _best_match_with_passage(
    needle: str, haystack: str, context_chars: int = 80,
) -> tuple[float, str]:
    """Find the best fuzzy match ratio and extract the matching passage.

    Returns (ratio, passage) where passage is the best-matching text from
    the haystack with surrounding context.  The haystack should already be
    HTML-stripped clean text (check_quotes does this).  We normalize the
    needle for matching but extract the passage from the original haystack
    using haystack_lower (same length as haystack, so positions map 1:1).
    """
    if not needle or not haystack:
        return 0.0, ""
    needle_norm = _normalize_quote_text(needle).lower()
    # Only lowercase the haystack (don't normalize — preserves positions)
    haystack_lower = haystack.lower()

    if not needle_norm:
        return 0.0, ""

    # Exact substring = verbatim
    if needle_norm in haystack_lower:
        pos = haystack_lower.index(needle_norm)
        return 1.0, _extract_passage(haystack, pos, len(needle_norm), context_chars)

    # Sliding window with fine step
    best = 0.0
    best_start = 0
    window = len(needle_norm)
    step = max(1, window // 8)
    for start in range(0, max(1, len(haystack_lower) - window + 1), step):
        chunk = haystack_lower[start:start + window + window // 2]
        ratio = difflib.SequenceMatcher(
            None, needle_norm, chunk, autojunk=False,
        ).ratio()
        if ratio > best:
            best = ratio
            best_start = start
            if best > 0.95:
                break

    passage = ""
    if best >= 0.4:
        passage = _extract_passage(
            haystack, best_start, window + window // 2, context_chars,
        )
    return best, passage


def _extract_passage(
    text: str, match_start: int, match_len: int, context: int,
) -> str:
    """Extract a passage from text around a match, trimmed to sentences."""
    start = max(0, match_start - context)
    end = min(len(text), match_start + match_len + context)
    passage = text[start:end].strip()
    # Trim leading partial sentence
    if start > 0:
        dot = passage.find(". ")
        if 0 < dot < context:
            passage = passage[dot + 2:]
    # Trim trailing partial sentence
    if end < len(text):
        dot = passage.rfind(". ")
        if dot > len(passage) - context and dot > 0:
            passage = passage[:dot + 1]
    return passage.strip()


def check_quotes(workdir: Path) -> QuoteCheckStats:
    """Check quoted text in claims against opinion files.

    Reads claims.csv, checks each quoted_text entry against the opinion,
    writes quote_check and quote_check_worst columns back to claims.csv.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"
    stats = QuoteCheckStats()

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    # Cache opinion text by file path (HTML-stripped for clean matching)
    opinion_cache: dict[str, str] = {}

    for claim in claims:
        stats.total_claims += 1
        quoted_raw = claim.get("quoted_text", "[]")
        opinion_file = claim.get("opinion_file", "")

        try:
            quotes = json_mod.loads(quoted_raw) if quoted_raw else []
        except (json_mod.JSONDecodeError, TypeError):
            quotes = []

        if not quotes:
            claim["quote_check"] = "[]"
            claim["quote_check_worst"] = "NO_QUOTES"
            stats.no_quotes += 1
            continue

        if not opinion_file:
            claim["quote_check"] = "[]"
            claim["quote_check_worst"] = "NO_OPINION"
            stats.no_opinion += 1
            continue

        # Load opinion text (strip HTML for clean matching + extraction)
        if opinion_file not in opinion_cache:
            opinion_path = workdir / opinion_file
            try:
                raw = opinion_path.read_text(encoding="utf-8")
            except (FileNotFoundError, UnicodeDecodeError):
                claim["quote_check"] = "[]"
                claim["quote_check_worst"] = "NO_OPINION"
                stats.no_opinion += 1
                continue
            # Strip HTML/XML tags and collapse whitespace for clean text
            clean = re.sub(r"<[^>]+>", " ", raw)
            clean = re.sub(r"&\w+;", " ", clean)  # HTML entities
            clean = re.sub(r"\s+", " ", clean).strip()
            opinion_cache[opinion_file] = clean
        opinion_text = opinion_cache[opinion_file]

        # Check each quote
        results = []
        worst = "VERBATIM"
        _WORST_ORDER = {"VERBATIM": 0, "CLOSE": 1, "FABRICATED": 2}

        for quote in quotes:
            ratio, matched_passage = _best_match_with_passage(
                quote, opinion_text,
            )
            if ratio > 0.85:
                result = "VERBATIM"
                stats.verbatim += 1
            elif ratio >= 0.6:
                result = "CLOSE"
                stats.close += 1
            else:
                result = "FABRICATED"
                stats.fabricated += 1

            entry: dict[str, object] = {
                "quote": quote,
                "result": result,
                "similarity": round(ratio, 2),
            }
            if matched_passage:
                entry["matched_passage"] = matched_passage
            results.append(entry)

            if _WORST_ORDER.get(result, 0) > _WORST_ORDER.get(worst, 0):
                worst = result

        claim["quote_check"] = json_mod.dumps(results)
        claim["quote_check_worst"] = worst
        stats.checked += 1

    # Write updated claims.csv
    if claims:
        all_fields = list(claims[0].keys())
        for col in ("quote_check", "quote_check_worst"):
            if col not in all_fields:
                all_fields.append(col)

        with open(claims_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields)
            writer.writeheader()
            writer.writerows(claims)

    return stats


# ---------------------------------------------------------------------------
# Metadata sanity check
# ---------------------------------------------------------------------------

@dataclass
class MetadataCheckResult:
    """Results from metadata sanity check."""
    total_claims: int = 0
    name_mismatches: int = 0
    not_found: int = 0
    no_opinion: int = 0
    flagged_claims: list[dict] = field(default_factory=list)
    syllabus_items: list[dict] = field(default_factory=list)


def metadata_check(workdir: Path) -> MetadataCheckResult:
    """Check verification metadata for obvious problems before assessment.

    Flags:
    - Case name mismatches (CL returned a different case)
    - NOT_FOUND citations (no opinion available)
    - Claims with no opinion file (can't assess)

    Also surfaces syllabus data alongside propositions so the skill
    orchestrator (LLM) can flag obvious topic mismatches during triage.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"
    result = MetadataCheckResult()

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    for claim in claims:
        result.total_claims += 1
        cl_status = claim.get("cl_status", "")
        diagnostics = claim.get("diagnostics", "")
        opinion_file = claim.get("opinion_file", "")
        syllabus = claim.get("syllabus", "")

        flags = []

        # Name mismatch: diagnostics contain "name mismatch"
        if "name mismatch" in diagnostics.lower() or "Name mismatch" in diagnostics:
            result.name_mismatches += 1
            flags.append("name_mismatch")

        # NOT_FOUND
        if cl_status == "NOT_FOUND":
            result.not_found += 1
            flags.append("not_found")

        # No opinion available
        if not opinion_file and cl_status not in ("NOT_FOUND", ""):
            result.no_opinion += 1
            flags.append("no_opinion")

        if flags:
            result.flagged_claims.append({
                "cited_case": claim.get("cited_case", ""),
                "page": claim.get("page", ""),
                "proposition": claim.get("proposition", ""),
                "syllabus": syllabus,
                "flags": flags,
            })

        # Surface syllabus for LLM triage (even if no other flags)
        if syllabus:
            result.syllabus_items.append({
                "cited_case": claim.get("cited_case", ""),
                "page": claim.get("page", ""),
                "proposition": claim.get("proposition", ""),
                "syllabus": syllabus,
            })

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    workdir: Path,
    title: str = "",
    case_name: str = "",
    case_number: str = "",
    filed_date: str = "",
    report_date: str = "",
) -> Path:
    """Generate an HTML report from claims.csv assessment data.

    Reads claims.csv (must have assessment column populated),
    builds the report data structure, and writes report.html.

    Returns the path to the generated report.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    findings = []
    verified = []
    unable_by_citation: dict[str, dict] = {}
    retrieved_set: dict[str, dict[str, str]] = {}
    unavailable_list = []
    finding_counter = 0
    # Minimum similarity for a deterministic matched passage to be shown.
    # Below this, the match is typically junk pulled from an unrelated part
    # of the opinion — worse than showing nothing, because it misleads the
    # reader into thinking the matcher found something relevant.
    _MATCH_PASSAGE_MIN_SIM = 0.65

    for claim in claims:
        assessment = claim.get("assessment", "").strip()
        cl_status = claim.get("cl_status", "")
        page = claim.get("page", "")
        proposition = claim.get("proposition", "")
        cited_case = claim.get("cited_case", "")
        cl_url = claim.get("cl_url", "")
        retrieved_case = claim.get("retrieved_case", "")
        supporting_lang = claim.get("supporting_language", "")
        opinion_file = claim.get("opinion_file", "")

        # Parse case name and citation from cited_case
        parts = cited_case.split(",", 1)
        case_name_parsed = parts[0].strip() if parts else cited_case
        citation_parsed = parts[1].strip() if len(parts) > 1 else ""

        # Track retrieved opinions
        if opinion_file and retrieved_case:
            cluster_id = ""
            if cl_url:
                m = re.search(r"/opinion/(\d+)/", cl_url)
                if m:
                    cluster_id = m.group(1)
            retrieved_set[retrieved_case] = {
                "case_name": retrieved_case,
                "citation": citation_parsed,
                "cluster_id": cluster_id,
            }

        if assessment.lower() == "green":
            verified.append({
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "cl_url": cl_url,
                "proposition": proposition,
                "badge_label": "Supported",
                "supporting_language": supporting_lang,
            })
        elif cl_status == "NOT_FOUND" and not opinion_file:
            # Group by cited_case so the same unavailable case cited for
            # multiple propositions collapses into one card.
            group_key = cited_case or f"{case_name_parsed}|{citation_parsed}"
            card = unable_by_citation.get(group_key)
            if not card:
                finding_counter += 1
                card = {
                    "id": f"finding-uv-{finding_counter}",
                    "page": page,
                    "case_name": case_name_parsed,
                    "citation": citation_parsed,
                    "propositions": [],
                    "explanation": (
                        supporting_lang if supporting_lang
                        else "Case not found on CourtListener. Cannot verify against opinion text."
                    ),
                }
                unable_by_citation[group_key] = card
                unavailable_list.append({
                    "case_name": case_name_parsed,
                    "citation": citation_parsed,
                    "reason": "Not in CourtListener database",
                })
            card["propositions"].append({
                "page": page,
                "proposition": proposition,
                "quoted_text": claim.get("quoted_text", ""),
            })
        else:
            # Yellow or Red finding
            finding_counter += 1
            severity = "red" if assessment.lower() == "red" else "yellow"

            quoted_raw = claim.get("quoted_text", "").strip()
            quoted_strings: list[str] = []
            if quoted_raw and quoted_raw != "[]":
                try:
                    quoted_strings = json_mod.loads(quoted_raw)
                except (json_mod.JSONDecodeError, ValueError):
                    pass

            brief_sentence = claim.get("brief_sentence", "").strip()

            # Deterministic matched passages from quote_check. Only show
            # passages that cleared the similarity floor — below it, the
            # matcher is guessing and the passage is usually junk.
            matched_passages = []
            quote_check_raw = claim.get("quote_check", "[]")
            try:
                quote_checks = json_mod.loads(quote_check_raw) if quote_check_raw else []
            except (json_mod.JSONDecodeError, ValueError):
                quote_checks = []
            for qc in quote_checks:
                sim = qc.get("similarity", 0)
                if qc.get("matched_passage") and sim >= _MATCH_PASSAGE_MIN_SIM:
                    matched_passages.append({
                        "text": qc["matched_passage"],
                        "similarity": sim,
                        "result": qc.get("result", ""),
                    })

            # Agent-authored narrative. Prefer the new single-field schema;
            # fall back to composing from the legacy two-field schema so old
            # briefs can still regenerate their reports.
            finding_analysis = claim.get("finding_analysis", "").strip()
            if not finding_analysis:
                legacy_overview = claim.get("opinion_text", "").strip()
                legacy_explanation = claim.get("explanation", "").strip()
                parts_legacy = [p for p in (legacy_overview, legacy_explanation) if p]
                finding_analysis = "\n\n".join(parts_legacy)

            badge_label = (
                claim.get("badge_label", "").strip()
                or _STATUS_BADGE_FALLBACK.get(cl_status)
                or ("Not supported by cited case" if severity == "red"
                    else "Overstated -- case partially supports")
            )

            # Agent-authored quote blocks (optional). When present they
            # replace the deterministic fallbacks in the template.
            brief_block = claim.get("brief_block", "").strip()
            opinion_block = claim.get("opinion_block", "").strip()

            findings.append({
                "id": f"finding-{finding_counter}",
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "cl_url": cl_url,
                "severity": severity,
                "badge_label": badge_label,
                # Agent-authored blocks (preferred when present)
                "brief_block": brief_block,
                "opinion_block": opinion_block,
                # Deterministic inputs (fallback / reference)
                "brief_sentence": brief_sentence,
                "proposition": proposition,
                "quoted_strings": quoted_strings,
                "matched_passages": matched_passages,
                "finding_analysis": finding_analysis,
            })

    report_data = {
        "title": title,
        "case_name": case_name,
        "case_number": case_number,
        "filed_date": filed_date,
        "report_date": report_date,
        "findings": findings,
        "verified": verified,
        "unable_to_verify": list(unable_by_citation.values()),
        "retrieved_opinions": list(retrieved_set.values()),
        "unavailable_opinions": unavailable_list,
    }

    html = generate_report_html(report_data)
    report_path = workdir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
