"""Record a cassette of CourtListener responses for the benchmark real-cite
corpus, plus a baseline verdict per citation.

One-time (and periodic) LIVE run. After this, the offline regression test
(test_benchmark_regression.py) replays the cassette through the current
interpretation logic with no network, so any verdict change caused by a
scoring/gating edit surfaces deterministically.

    python tests/record_benchmark_cassette.py [--limit N]

Writes:
  tests/data/benchmark_cassette.json.gz  (method+args -> CL response, gzip)
  tests/data/benchmark_baseline.json     (citation -> recorded verdict)

Recording CHECKPOINTS every few citations and RESUMES automatically: if the
cassette/baseline already exist, citations with a recorded non-transient
verdict are skipped and only the remainder (plus ERROR /
VERIFICATION_INCOMPLETE retries) hit the network. Use --fresh to discard
previous progress and start over.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running directly (`python tests/record_benchmark_cassette.py`):
# the `tests.` import below needs the repo root on sys.path, which pytest's
# conftest provides but a direct invocation does not.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from citation_verifier.models import Status
from tests.cassette_client import CassetteClient, dump_cassette, load_cassette

_DATA = Path(__file__).parent / "data"
_CORPUS = _DATA / "benchmark_real_citations.json"
# Cassettes are gzip-compressed (.json.gz): ~90 MB of JSON -> a few MB,
# binary diffs instead of 150k-line text churn, fast multi-machine sync.
_CASSETTE = _DATA / "benchmark_cassette.json.gz"
_BASELINE = _DATA / "benchmark_baseline.json"

_FOUND = {
    Status.VERIFIED, Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP, Status.VERIFIED_DOCKET_ONLY,
}
_FOUND_VALUES = {s.value for s in _FOUND}
# Check Cite (2026-06-11): counted in its own bucket, NOT in found. For a
# fake corpus, `found` remains the FP headline; CITE_UNCONFIRMED on a fake
# is a success (the tool tells the user to check; the check reveals it).
_CHECK_CITE_VALUE = Status.CITE_UNCONFIRMED.value

# Write progress to disk every N verified citations. Cassettes can reach
# tens of MB (opinion texts), so per-citation dumps would be wasteful; a
# crash loses at most N citations' worth of API calls.
_CHECKPOINT_EVERY = 10

# Verdicts that should be retried on resume rather than trusted: ERROR is a
# crash/parse failure, VERIFICATION_INCOMPLETE means stages errored
# transiently (network, 429, 5xx).
_TRANSIENT = {"ERROR", Status.VERIFICATION_INCOMPLETE.value}


def _should_skip_on_resume(baseline_entry: dict | None) -> bool:
    """A citation is skipped on resume iff it has a non-transient verdict."""
    return bool(baseline_entry) and baseline_entry.get("status") not in _TRANSIENT


def _recompute_counts(baseline: dict) -> dict:
    """Summary counts derived from the (possibly resumed) baseline."""
    counts = {"found": 0, "not_found": 0, "incomplete": 0, "error": 0,
              "cluster_match": 0, "check_cite": 0}
    for entry in baseline.values():
        status = entry.get("status")
        if status == "ERROR":
            counts["error"] += 1
        elif status == Status.VERIFICATION_INCOMPLETE.value:
            counts["incomplete"] += 1
        elif status == _CHECK_CITE_VALUE:
            counts["check_cite"] += 1
        elif status in _FOUND_VALUES:
            counts["found"] += 1
            cluster = entry.get("cluster_id")
            if cluster and cluster == entry.get("expected_cluster_id"):
                counts["cluster_match"] += 1
        else:
            counts["not_found"] += 1
    return counts


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file + rename so a crash mid-write can't corrupt the
    previous checkpoint."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _checkpoint(cassette: dict | None, baseline: dict) -> None:
    if cassette is not None:
        dump_cassette(_CASSETTE, cassette)  # gzip + atomic
    _atomic_write(_BASELINE, json.dumps(baseline, indent=2))


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
    ap.add_argument(
        "--fresh", action="store_true",
        help="ignore an existing cassette/baseline and re-record everything "
             "(default: resume, skipping citations already recorded)",
    )
    args = ap.parse_args()

    global _CORPUS, _CASSETTE, _BASELINE
    if args.corpus_name != "benchmark":
        n = args.corpus_name
        _CORPUS = _DATA / f"{n}_corpus.json"
        _CASSETTE = _DATA / f"{n}_cassette.json.gz"
        _BASELINE = _DATA / f"{n}_baseline.json"

    corpus = json.loads(_CORPUS.read_text(encoding="utf-8"))
    if args.limit:
        corpus = corpus[: args.limit]

    baseline: dict = {}
    if args.from_cassette:
        cassette = load_cassette(_CASSETTE)
        real = CourtListenerClient.__new__(CourtListenerClient)  # no network
        client = CassetteClient(real, cassette, mode="replay")
    else:
        cassette = {}
        if not args.fresh and _CASSETTE.exists() and _BASELINE.exists():
            cassette = load_cassette(_CASSETTE)
            baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
            done = sum(
                1 for e in corpus
                if _should_skip_on_resume(baseline.get(e["citation"]))
            )
            print(f"Resuming: {done}/{len(corpus)} already recorded "
                  f"({len(cassette)} cached calls); --fresh to start over.")
        client = CassetteClient(CourtListenerClient(), cassette, mode="record")
    verifier = CitationVerifier(client=client)

    recorded_since_checkpoint = 0
    for i, entry in enumerate(corpus, 1):
        cite = entry["citation"]
        if not args.from_cassette and _should_skip_on_resume(baseline.get(cite)):
            continue
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
        except Exception as exc:  # noqa: BLE001 - record, don't abort the run
            baseline[cite] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        recorded_since_checkpoint += 1
        if not args.from_cassette and recorded_since_checkpoint >= _CHECKPOINT_EVERY:
            _checkpoint(cassette, baseline)
            recorded_since_checkpoint = 0
        if i % 25 == 0:
            print(f"  {i}/{len(corpus)} ...", flush=True)

    _checkpoint(cassette if not args.from_cassette else None, baseline)

    counts = _recompute_counts(
        {e["citation"]: baseline[e["citation"]]
         for e in corpus if e["citation"] in baseline}
    )
    n = len(corpus)
    print(f"\nRecorded {n} citations -> {_CASSETTE.name} ({len(cassette)} cached calls)")
    print(f"  found (resolved):      {counts['found']}/{n}")
    print(f"    of which cluster-id matches benchmark: {counts['cluster_match']}")
    print(f"  CITE_UNCONFIRMED (check cite): {counts['check_cite']}/{n}")
    print(f"  NOT_FOUND:             {counts['not_found']}/{n}")
    print(f"  VERIFICATION_INCOMPLETE (transient): {counts['incomplete']}/{n}")
    print(f"  ERROR (parse/other):   {counts['error']}/{n}")


if __name__ == "__main__":
    main()
