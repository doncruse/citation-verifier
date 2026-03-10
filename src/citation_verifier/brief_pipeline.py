"""Brief verification pipeline — wave1/wave2/merge with CLI entry point."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import AsyncCourtListenerClient
from .models import VerificationResult, VerificationStatus
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


_VR_FIELDS = [
    "citation", "status", "confidence", "cl_url",
    "matched_name", "diagnostics_cat", "diagnostics_msg",
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
    ]

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

        merged_rows.append({
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
        })

    # Write updated claims.csv
    with open(claims_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(merged_rows)

    return stats
