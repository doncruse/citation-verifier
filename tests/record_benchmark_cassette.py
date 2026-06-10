"""Record a cassette of CourtListener responses for the benchmark real-cite
corpus, plus a baseline verdict per citation.

One-time (and periodic) LIVE run. After this, the offline regression test
(test_benchmark_regression.py) replays the cassette through the current
interpretation logic with no network, so any verdict change caused by a
scoring/gating edit surfaces deterministically.

    python tests/record_benchmark_cassette.py [--limit N]

Writes:
  tests/data/benchmark_cassette.json   (method+args -> CL response)
  tests/data/benchmark_baseline.json   (citation -> recorded verdict)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from citation_verifier.models import Status
from tests.cassette_client import CassetteClient

_DATA = Path(__file__).parent / "data"
_CORPUS = _DATA / "benchmark_real_citations.json"
_CASSETTE = _DATA / "benchmark_cassette.json"
_BASELINE = _DATA / "benchmark_baseline.json"

_FOUND = {
    Status.VERIFIED, Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP, Status.VERIFIED_DOCKET_ONLY,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap citations (0=all)")
    ap.add_argument(
        "--from-cassette", action="store_true",
        help="recompute the baseline by REPLAYING the existing cassette "
             "(offline, no API calls). Use after an interpretation-logic "
             "change to refresh expected verdicts without re-recording.",
    )
    ap.add_argument(
        "--corpus-name", default="benchmark",
        help="corpus prefix: reads data/<name>_*.json for corpus/cassette/"
             "baseline (default 'benchmark'; use 'fallback' for the coverage-"
             "study lookup-miss corpus built by build_fallback_corpus.py)",
    )
    args = ap.parse_args()

    global _CORPUS, _CASSETTE, _BASELINE
    if args.corpus_name != "benchmark":
        n = args.corpus_name
        _CORPUS = _DATA / f"{n}_corpus.json"
        _CASSETTE = _DATA / f"{n}_cassette.json"
        _BASELINE = _DATA / f"{n}_baseline.json"

    corpus = json.loads(_CORPUS.read_text(encoding="utf-8"))
    if args.limit:
        corpus = corpus[: args.limit]

    if args.from_cassette:
        cassette = json.loads(_CASSETTE.read_text(encoding="utf-8"))
        real = CourtListenerClient.__new__(CourtListenerClient)  # no network
        client = CassetteClient(real, cassette, mode="replay")
    else:
        cassette = {}
        client = CassetteClient(CourtListenerClient(), cassette, mode="record")
    verifier = CitationVerifier(client=client)

    baseline: dict = {}
    counts = {"found": 0, "not_found": 0, "incomplete": 0, "error": 0,
              "cluster_match": 0}
    for i, entry in enumerate(corpus, 1):
        cite = entry["citation"]
        try:
            r = verifier.verify(cite)
            status = r.status.value
            cluster = r.final_ids.cluster_id
            resolved_stages = [
                e.stage.value for e in r.resolution_path
                if e.verdict.value in ("resolved", "partial")
            ]
            baseline[cite] = {
                "status": status,
                "cluster_id": cluster,
                "docket_id": r.final_ids.docket_id,
                "confidence": r.headline_confidence,
                "winning_stage": resolved_stages[-1] if resolved_stages else None,
                "expected_cluster_id": entry.get("expected_cluster_id"),
            }
            if r.status is Status.VERIFICATION_INCOMPLETE:
                counts["incomplete"] += 1
            elif r.status in _FOUND:
                counts["found"] += 1
                if cluster and cluster == entry.get("expected_cluster_id"):
                    counts["cluster_match"] += 1
            else:
                counts["not_found"] += 1
        except Exception as exc:  # noqa: BLE001 - record, don't abort the run
            baseline[cite] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            counts["error"] += 1
        if i % 25 == 0:
            print(f"  {i}/{len(corpus)} ...", flush=True)

    if not args.from_cassette:
        _CASSETTE.write_text(json.dumps(cassette, indent=0), encoding="utf-8")
    _BASELINE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    n = len(corpus)
    print(f"\nRecorded {n} citations -> {_CASSETTE.name} ({len(cassette)} cached calls)")
    print(f"  found (resolved):      {counts['found']}/{n}")
    print(f"    of which cluster-id matches benchmark: {counts['cluster_match']}")
    print(f"  NOT_FOUND:             {counts['not_found']}/{n}")
    print(f"  VERIFICATION_INCOMPLETE (transient): {counts['incomplete']}/{n}")
    print(f"  ERROR (parse/other):   {counts['error']}/{n}")


if __name__ == "__main__":
    main()
