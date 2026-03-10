"""Brief verification pipeline — wave1/wave2/merge with CLI entry point."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MergeStats:
    """Statistics from merging verification results into claims.csv."""
    matched: int = 0
    unmatched: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    opinion_count: int = 0


# --- Pinpoint stripping ---

# Matches ", 527" or ", at 527" or ", 527-30" at end of volume/page cite
_PINPOINT_RE = re.compile(
    r",\s+(?:at\s+)?\d+(?:\s*[-\u2013]\s*\d+)?\s*(?=\(|$)"
)


def _strip_pinpoint(cite: str) -> str:
    """Remove pinpoint page references from a citation string.

    E.g. 'Egan, 484 U.S. 518, 527 (1988)' -> 'Egan, 484 U.S. 518 (1988)'
    """
    return _PINPOINT_RE.sub(" ", cite).strip()


def _normalize_for_match(cite: str) -> str:
    """Normalize a citation for matching: strip pinpoint, lowercase, collapse whitespace."""
    s = _strip_pinpoint(cite)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _find_opinion_file(workdir: Path, case_name: str) -> str:
    """Scan opinions/ for a file matching the case name. Returns relative path or ''."""
    opinions_dir = workdir / "opinions"
    if not opinions_dir.exists():
        return ""

    # Normalize case name for comparison
    normalized = re.sub(r"[^a-z0-9]", "", case_name.lower())

    for f in opinions_dir.iterdir():
        if f.is_file():
            fn = re.sub(r"[^a-z0-9]", "", f.stem.lower())
            if fn and normalized and (fn in normalized or normalized in fn):
                return f"opinions/{f.name}"

    return ""


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

        # Find opinion file
        opinion_file = ""
        if matched_name:
            opinion_file = _find_opinion_file(workdir, matched_name)
        if not opinion_file and cited:
            # Try with cited case name
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
