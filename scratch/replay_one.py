"""Replay individual Charlotin citations against the recorded cassette.

Diagnostic helper for the 2026-06-11 FP triage follow-up (Bugs 2/3
investigation). Offline — replays tests/data/charlotin_cassette.json.

    venv/Scripts/python.exe scratch/replay_one.py "<citation>" [...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from tests.cassette_client import CassetteClient, load_cassette

_CASSETTE = Path(__file__).parents[1] / "tests" / "data" / "charlotin_cassette.json.gz"


def main() -> None:
    cites = sys.argv[1:]
    if cites and cites[0] == "--targets":
        cites = json.loads(Path(cites[1]).read_text(encoding="utf-8"))
    cassette = load_cassette(_CASSETTE)
    real = CourtListenerClient.__new__(CourtListenerClient)
    client = CassetteClient(real, cassette, mode="replay")
    verifier = CitationVerifier(client=client)
    for cite in cites:
        print("=" * 70)
        print("CITE:", cite)
        try:
            r = verifier.verify(cite)
        except Exception as exc:  # noqa: BLE001
            print("  EXC:", type(exc).__name__, str(exc)[:200])
            continue
        p = r.parsed_citation
        print(f"  parsed: name={p.case_name!r} pl={p.plaintiff!r} def={p.defendant!r}")
        print(f"  status={r.status.value} conf={r.headline_confidence}")
        print(f"  cluster={r.final_ids.cluster_id} docket={r.final_ids.docket_id}")
        for e in r.resolution_path:
            print(f"  stage={e.stage.value} verdict={e.verdict.value} conf={e.confidence}")
            print(f"    notes={e.notes!r}")
            print(f"    summary={json.dumps(e.raw_response_summary, default=str)[:400]}")
        for w in r.warnings:
            print(f"  warning={w.category.value}: {w.message[:160]}")


if __name__ == "__main__":
    main()
