"""Deterministic retrieval helper for the screen-gate baseline corpus pull.

Pure functions (`classify_doctype`, `sanction_hits`, `slugify`,
`manifest_row`) are zero-network, zero-LLM, and unit-tested in
`test_pull_baseline.py`. `pull_candidate` is the single network function --
it is validated in Task 4b, not unit-tested here.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

# --- classify_doctype ---------------------------------------------------

# Precedence: merits_brief -> procedural_motion -> pleading (checked in
# that order; first hit wins). E.g. "Response in Opposition to Motion to
# Dismiss the Complaint" contains both "opposition" and "complaint" and
# must classify as merits_brief, not pleading.
_MERITS_BRIEF_TERMS = [
    "memorandum in support",
    "motion for summary judgment",
    "summary judgment",
    "response in opposition",
    "opposition to",
    "reply in support",
    "reply memorandum",
    "brief in support",
    "motion to dismiss",
]

_PROCEDURAL_MOTION_TERMS = [
    "motion to compel",
    "motion to remand",
    "motion for leave",
    "motion to strike",
    "motion to quash",
    "discovery",
    "joint statement",
]

_PLEADING_TERMS = [
    "amended complaint",
    "complaint",
    "petition",
]

_DOCTYPE_PRECEDENCE = [
    ("merits_brief", _MERITS_BRIEF_TERMS),
    ("procedural_motion", _PROCEDURAL_MOTION_TERMS),
    ("pleading", _PLEADING_TERMS),
]


def classify_doctype(description: str) -> str | None:
    """Classify a RECAP docket-entry description into a doc_type.

    Case-insensitive substring match, checked in precedence order
    merits_brief -> procedural_motion -> pleading. First hit wins.
    Returns None when no term matches.
    """
    if not description:
        return None
    lowered = description.lower()
    for doc_type, terms in _DOCTYPE_PRECEDENCE:
        for term in terms:
            if term in lowered:
                return doc_type
    return None


# --- sanction_hits --------------------------------------------------------

_SANCTION_TERMS = [
    "sanction",
    "show cause",
    "show-cause",
    "order to show cause",
    "fabricat",
    "hallucin",
    "fictitious",
    "non-existent",
    "nonexistent",
    "rule 11",
]


def sanction_hits(texts: Iterable[str]) -> list[str]:
    """Return sanction-screen terms found (case-insensitive) across texts.

    De-duplicated, preserving first-seen order (order of _SANCTION_TERMS,
    filtered to those that appear at least once across all texts).
    """
    combined = " ".join(texts).lower()
    hits: list[str] = []
    for term in _SANCTION_TERMS:
        if term in combined and term not in hits:
            hits.append(term)
    return hits


# --- slugify ---------------------------------------------------------------

_NON_ALNUM_RUN = re.compile(r"[^a-z0-9]+")


def _slug_tokens(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    collapsed = _NON_ALNUM_RUN.sub("-", lowered).strip("-")
    if not collapsed:
        return []
    return collapsed.split("-")


def slugify(case_name: str, docket_number: str = "") -> str:
    """Build a filesystem-safe slug, capped at 6 hyphen-tokens.

    Falls back to a slug of docket_number, then to "doc", when
    case_name yields nothing.
    """
    tokens = _slug_tokens(case_name)
    if not tokens:
        tokens = _slug_tokens(docket_number)
    if not tokens:
        return "doc"
    return "-".join(tokens[:6])


# --- manifest_row ------------------------------------------------------

def manifest_row(
    *,
    slug: str,
    court: str,
    docket_id: int,
    document_number: int,
    filer_type: str,
    doc_type: str,
    recap_url: str,
    is_available: bool,
    sanction_screen: str,
    notes: str = "",
) -> dict:
    """Build a manifest row dict with the exact schema keys."""
    return {
        "slug": slug,
        "court": court,
        "docket_id": docket_id,
        "document_number": document_number,
        "filer_type": filer_type,
        "doc_type": doc_type,
        "recap_url": recap_url,
        "is_available": is_available,
        "sanction_screen": sanction_screen,
        "notes": notes,
    }


# --- pull_candidate (network; not unit-tested here, see Task 4b) -------

async def pull_candidate(client, docket_id, document_number, cell_dir, meta) -> dict | None:
    """Fetch one RECAP document, save its text, and return a manifest row.

    Not unit-tested in this task -- validated against the live CourtListener
    API in Task 4b.
    """
    url = f"https://www.courtlistener.com/docket/{docket_id}/{document_number}/"
    data = await client.get_opinion_text_with_metadata(url)
    if not data or not data.get("text"):
        return None

    slug = slugify(data.get("case_name", ""), data.get("docket_number", ""))

    os.makedirs(cell_dir, exist_ok=True)
    out_path = os.path.join(cell_dir, f"{slug}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(data["text"])

    return manifest_row(
        slug=slug,
        court=meta.get("court") or data.get("court", ""),
        docket_id=docket_id,
        document_number=document_number,
        filer_type=meta["filer_type"],
        doc_type=meta["doc_type"],
        recap_url=url,
        is_available=True,
        sanction_screen=meta.get("sanction_screen", "clean"),
        notes=meta.get("notes", ""),
    )
