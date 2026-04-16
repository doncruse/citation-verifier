"""Brief verification pipeline — wave1/wave2/merge with CLI entry point."""

from __future__ import annotations

import csv
import difflib
import json as json_mod
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import AsyncCourtListenerClient
from .models import VerificationResult, VerificationStatus
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


_PASSTHROUGH_FIELDS = ["quoted_text", "quote_check", "quote_check_worst"]

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
            diag_cats = []
            diag_msgs = []
            for d in result.diagnostics:
                diag_cats.append(d.category)
                diag_msgs.append(d.message)
            writer.writerow({
                "citation": cite,
                "status": result.status.value,
                "confidence": f"{result.confidence:.2f}",
                "cl_url": result.matched_url or "",
                "matched_name": result.matched_case_name or "",
                "diagnostics_cat": "; ".join(diag_cats),
                "diagnostics_msg": "; ".join(diag_msgs),
                "syllabus": result.matched_syllabus or "",
            })


# ---------------------------------------------------------------------------
# Opinion downloading
# ---------------------------------------------------------------------------

_DOWNLOADABLE_STATUSES = {
    VerificationStatus.VERIFIED,
    VerificationStatus.LIKELY_REAL,
    VerificationStatus.POSSIBLE_MATCH,
}


async def _download_opinion(
    client: AsyncCourtListenerClient,
    workdir: Path,
    result: VerificationResult,
    citation: str,
) -> str | None:
    """Download opinion text for a verified result. Returns saved filename or None."""
    if not result.matched_url:
        return None

    opinions_dir = workdir / "opinions"
    opinions_dir.mkdir(exist_ok=True)

    try:
        data = await client.get_opinion_text_with_metadata(
            result.matched_url, prefer_html=True,
        )
        if not data:
            return None

        fmt = data.get("format", "text")
        case_name = result.matched_case_name or data.get("case_name", "")
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

    # Write verification_results.csv
    _write_verification_csv(workdir, citations, results)

    # Download opinions for hits
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

    # Append to verification_results.csv
    _write_verification_csv(workdir, miss_citations, results, append=True)

    # Download opinions for newly resolved citations
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


def _best_match_ratio(needle: str, haystack: str) -> float:
    """Find the best fuzzy match ratio for needle within haystack."""
    if not needle or not haystack:
        return 0.0
    needle_norm = _normalize_quote_text(needle).lower()
    haystack_norm = _normalize_quote_text(haystack).lower()

    if not needle_norm:
        return 0.0

    # Exact substring = verbatim
    if needle_norm in haystack_norm:
        return 1.0

    # Sliding window: compare against chunks roughly needle-sized
    best = 0.0
    window = len(needle_norm)
    step = max(1, window // 4)
    for start in range(0, max(1, len(haystack_norm) - window + 1), step):
        chunk = haystack_norm[start:start + window + window // 2]
        ratio = difflib.SequenceMatcher(None, needle_norm, chunk, autojunk=False).ratio()
        if ratio > best:
            best = ratio
            if best > 0.95:
                break
    return best


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

    # Cache opinion text by file path
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

        # Load opinion text
        if opinion_file not in opinion_cache:
            opinion_path = workdir / opinion_file
            try:
                opinion_cache[opinion_file] = opinion_path.read_text(encoding="utf-8")
            except (FileNotFoundError, UnicodeDecodeError):
                claim["quote_check"] = "[]"
                claim["quote_check_worst"] = "NO_OPINION"
                stats.no_opinion += 1
                continue
        opinion_text = opinion_cache[opinion_file]

        # Check each quote
        results = []
        worst = "VERBATIM"
        _WORST_ORDER = {"VERBATIM": 0, "CLOSE": 1, "FABRICATED": 2}

        for quote in quotes:
            ratio = _best_match_ratio(quote, opinion_text)
            if ratio > 0.85:
                result = "VERBATIM"
                stats.verbatim += 1
            elif ratio >= 0.6:
                result = "CLOSE"
                stats.close += 1
            else:
                result = "FABRICATED"
                stats.fabricated += 1

            results.append({
                "quote": quote,
                "result": result,
                "similarity": round(ratio, 2),
            })

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
    unable = []
    retrieved_set: dict[str, dict[str, str]] = {}
    unavailable_list = []
    finding_counter = 0

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
            finding_counter += 1
            unable.append({
                "id": f"finding-uv-{finding_counter}",
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "brief_text": proposition,
                "explanation": (
                    supporting_lang if supporting_lang
                    else "Case not found on CourtListener. Cannot verify against opinion text."
                ),
            })
            unavailable_list.append({
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "reason": "Not in CourtListener database",
            })
        else:
            # Yellow or Red finding
            finding_counter += 1
            severity = "red" if assessment.lower() == "red" else "yellow"

            # Prefer structured columns from new-style agents; fall back
            # to parsing supporting_language for old-style data.
            brief_text = claim.get("brief_text", "").strip() or proposition
            opinion_text = claim.get("opinion_text", "").strip() or ""
            explanation = claim.get("explanation", "").strip() or ""

            if not opinion_text and not explanation and supporting_lang:
                # Old-format fallback: parse from supporting_language
                if "Assessment:" in supporting_lang:
                    parts_sl = supporting_lang.split("Assessment:", 1)
                    opinion_text = parts_sl[0].strip()
                    explanation = parts_sl[1].strip()
                else:
                    explanation = supporting_lang

            badge_label = claim.get("badge_label", "").strip() or (
                "Not supported by cited case" if severity == "red"
                else "Overstated -- case partially supports"
            )

            findings.append({
                "id": f"finding-{finding_counter}",
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "cl_url": cl_url,
                "severity": severity,
                "badge_label": badge_label,
                "brief_text": brief_text,
                "opinion_text": opinion_text,
                "explanation": explanation,
            })

    report_data = {
        "title": title,
        "case_name": case_name,
        "case_number": case_number,
        "filed_date": filed_date,
        "report_date": report_date,
        "findings": findings,
        "verified": verified,
        "unable_to_verify": unable,
        "retrieved_opinions": list(retrieved_set.values()),
        "unavailable_opinions": unavailable_list,
    }

    html = generate_report_html(report_data)
    report_path = workdir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
