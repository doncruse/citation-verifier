"""Offline regression over the FALLBACK corpus (coverage-study lookup misses).

Counterpart to test_benchmark_regression.py, but aimed at the other half of
the pipeline: every citation here is a real case that citation-lookup could
NOT resolve (per the May-2026 coverage study), so a full verify() exercises
the opinion-search / RECAP fallback — exactly the scoring and gating that
Levers 1-3 and Step 4 changed. The benchmark corpus resolves ~entirely at
citation-lookup and cannot catch fallback regressions; this one can.

Guards:
  1. No new false negatives — every cite that resolved at record time still
     resolves.
  2. No silent path migration — a cite that resolved via a given stage keeps
     resolving via that stage (a fallback-scoring change that flips e.g.
     opinion_search -> recap_docket_search shows up here even when the
     overall verdict is unchanged).

Skips cleanly if the cassette hasn't been recorded yet:
    python -m tests.record_benchmark_cassette --corpus-name fallback
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from tests.cassette_client import CassetteClient, CassetteMiss, load_cassette

_DATA = Path(__file__).parent / "data"
_CASSETTE = _DATA / "fallback_cassette.json.gz"
_BASELINE = _DATA / "fallback_baseline.json"

_FOUND = {
    "VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP", "VERIFIED_DOCKET_ONLY",
}


@pytest.fixture(scope="module")
def replay_setup():
    if not (_CASSETTE.exists() and _BASELINE.exists()):
        pytest.skip(
            "no fallback cassette recorded — run "
            "record_benchmark_cassette.py --corpus-name fallback"
        )
    cassette = load_cassette(_CASSETTE)
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    client = CassetteClient(
        CourtListenerClient.__new__(CourtListenerClient), cassette, mode="replay"
    )
    return CitationVerifier(client=client), baseline


def _replay(verifier, citation):
    try:
        r = verifier.verify(citation)
    except CassetteMiss:
        return "CASSETTE_MISS", None
    resolved = [
        e.stage.value for e in r.resolution_path
        if e.verdict.value in ("resolved", "partial")
    ]
    return r.status.value, (resolved[-1] if resolved else None)


def test_no_new_fallback_false_negatives(replay_setup):
    verifier, baseline = replay_setup
    regressions = []
    for citation, base in baseline.items():
        if base.get("status") not in _FOUND:
            continue
        now, _stage = _replay(verifier, citation)
        if now not in _FOUND:
            regressions.append((citation, base["status"], now))
    assert not regressions, (
        f"{len(regressions)} fallback-resolved citation(s) now fail:\n" + "\n".join(
            f"  {c[:60]}: {was} -> {now}" for c, was, now in regressions[:25]
        )
    )


def test_no_silent_resolution_path_migration(replay_setup):
    """Stage drift is a behavior change even when the verdict label isn't."""
    verifier, baseline = replay_setup
    migrations = []
    for citation, base in baseline.items():
        if base.get("status") not in _FOUND or not base.get("winning_stage"):
            continue
        now, stage = _replay(verifier, citation)
        if now in _FOUND and stage != base["winning_stage"]:
            migrations.append((citation, base["winning_stage"], stage))
    assert not migrations, (
        f"{len(migrations)} citation(s) changed winning stage:\n" + "\n".join(
            f"  {c[:60]}: {was} -> {now}" for c, was, now in migrations[:25]
        )
    )


def test_fallback_corpus_exercises_fallback_stages(replay_setup):
    """Sanity: this corpus must actually hit fallback stages — if most of it
    resolves at citation_lookup, it's not testing what it claims to."""
    _, baseline = replay_setup
    resolved = [b for b in baseline.values() if b.get("status") in _FOUND]
    if not resolved:
        pytest.skip("nothing resolved at baseline — corpus needs triage")
    via_fallback = [
        b for b in resolved if b.get("winning_stage") not in (None, "citation_lookup")
    ]
    assert len(via_fallback) >= 0.5 * len(resolved), (
        f"only {len(via_fallback)}/{len(resolved)} resolved via fallback stages "
        f"— corpus no longer exercises the fallback; re-derive it"
    )
