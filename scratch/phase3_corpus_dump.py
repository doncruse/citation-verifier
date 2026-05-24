"""Phase 3 corpus dump — one-shot live API run to record what verifier
returns for each fixture. Used during Task 6 fixture triage."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow loading tests/ as a package even though scratch/ isn't on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from citation_verifier.verifier import CitationVerifier
from tests.data.refactor_corpus_loader import load_corpus


def main() -> None:
    _, fixtures = load_corpus()
    verifier = CitationVerifier()
    runnable = [fx for fx in fixtures if fx.expected_status != "VERIFICATION_INCOMPLETE"]

    out = []
    for fx in runnable:
        result = verifier.verify(fx.citation)
        out.append({
            "id": fx.id,
            "citation": fx.citation,
            "expected_status": fx.expected_status,
            "actual_status": result.status.value,
            "expected_final_ids": fx.expected_final_ids,
            "actual_final_ids": {
                "cluster_id": result.final_ids.cluster_id,
                "opinion_id": result.final_ids.opinion_id,
                "docket_id": result.final_ids.docket_id,
                "recap_document_id": result.final_ids.recap_document_id,
                "absolute_url": result.final_ids.absolute_url,
                "text_source": (
                    result.final_ids.text_source.value
                    if result.final_ids.text_source else None
                ),
            },
            "expected_warnings": fx.expected_warnings_subset,
            "actual_warnings": [
                {"category": w.category.value, "message": w.message[:200]}
                for w in result.warnings
            ],
            "resolution_path": [
                {
                    "stage": e.stage.value,
                    "verdict": e.verdict.value,
                    "confidence": e.confidence,
                    "notes": (e.notes or "")[:200],
                }
                for e in result.resolution_path
            ],
            "category": fx.category,
            "phase3_classification_open": fx.phase3_classification_open,
            "rationale": fx.rationale[:300],
        })
        print(f"  {fx.id}: {result.status.value}")

    dest = Path("scratch/phase3_corpus_dump.json")
    dest.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {len(out)} entries to {dest}")


if __name__ == "__main__":
    main()
