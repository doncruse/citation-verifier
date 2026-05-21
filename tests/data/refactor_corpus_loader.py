"""Loader for the Phase 2.5 refactor corpus.

The corpus is consumed by Phase 3's acceptance tests via load_corpus().
Phase 2.5's own schema-shape tests also consume it via the same loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CORPUS_FILE = Path(__file__).parent / "refactor_corpus.json"

# Mirrors the six-state Status enum in src/citation_verifier/models.py.
# Duplicated here as strings so this loader stays decoupled from the
# verifier package's import surface (Phase 3 may parametrize without
# pulling in the verifier).
_VALID_STATUSES = {
    "VERIFIED",
    "VERIFIED_PARTIAL",
    "VERIFIED_VIA_RECAP",
    "VERIFIED_DOCKET_ONLY",
    "WRONG_CASE",
    "NOT_FOUND",
    "VERIFICATION_INCOMPLETE",
}

_VALID_STAGES = {
    "citation_lookup",
    "opinion_search",
    "recap_document_search",
    "recap_docket_search",
    "plain_docket_search",
    "caption_investigation",
}


@dataclass(frozen=True)
class Fixture:
    id: str
    citation: str
    expected_status: str
    expected_resolving_stage: str | None
    expected_final_ids: dict[str, Any]
    expected_warnings_subset: list[str]
    rationale: str
    source: str
    category: str
    phase3_classification_open: bool = False
    mock_spec: dict[str, Any] | None = None
    expected_warnings_exact: bool = False
    phase3_ruling: str | None = None


def load_corpus(path: Path | None = None) -> tuple[dict[str, Any], list[Fixture]]:
    """Load the corpus file. Returns (metadata, fixtures).

    metadata is the top-level dict minus the fixtures key.
    fixtures is a list of Fixture dataclasses.
    """
    target = path or _CORPUS_FILE
    with open(target, encoding="utf-8") as f:
        raw = json.load(f)
    fixtures = [Fixture(**fx) for fx in raw["fixtures"]]
    metadata = {k: v for k, v in raw.items() if k != "fixtures"}
    return metadata, fixtures


def fixtures_by_status(fixtures: list[Fixture]) -> dict[str, list[Fixture]]:
    """Group fixtures by expected_status."""
    out: dict[str, list[Fixture]] = {s: [] for s in _VALID_STATUSES}
    for fx in fixtures:
        out[fx.expected_status].append(fx)
    return out
