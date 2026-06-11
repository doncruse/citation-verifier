"""Offline regression test over the benchmark real-citation corpus.

Replays the recorded cassette (tests/data/benchmark_cassette.json.gz) through
the CURRENT interpretation logic with no network. Its job is to catch the failure
mode this whole false-positive-tightening effort risks: that a scoring/gating
change quietly starts *rejecting real cases*.

Guard: every citation the verifier resolved at record time must still resolve.
Verdict changes are reported; only new false negatives fail the test.

Runs in the normal (offline) suite. Skips cleanly if no cassette has been
recorded yet (see tests/record_benchmark_cassette.py). Re-record periodically
to refresh against CourtListener data drift.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from citation_verifier.models import Status
from tests.cassette_client import CassetteClient, CassetteMiss, load_cassette

_DATA = Path(__file__).parent / "data"
_CASSETTE = _DATA / "benchmark_cassette.json.gz"
_BASELINE = _DATA / "benchmark_baseline.json"

_FOUND = {
    "VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP", "VERIFIED_DOCKET_ONLY",
    # Check Cite (2026-06-11): for a REAL-case corpus, "found" guards
    # case-location; CITE_UNCONFIRMED still locates the case. See
    # test_fallback_regression.py for the fuller rationale.
    "CITE_UNCONFIRMED",
}


@pytest.fixture(scope="module")
def replay_setup():
    if not (_CASSETTE.exists() and _BASELINE.exists()):
        pytest.skip("no benchmark cassette recorded — run record_benchmark_cassette.py")
    cassette = load_cassette(_CASSETTE)
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    # CassetteClient needs a real client only for pass-through attrs; in replay
    # mode it never calls the network. Construct without a token requirement.
    client = CassetteClient(CourtListenerClient.__new__(CourtListenerClient),
                            cassette, mode="replay")
    return CitationVerifier(client=client), baseline


def _replay_status(verifier, citation):
    try:
        return verifier.verify(citation).status.value
    except CassetteMiss:
        return "CASSETTE_MISS"


def test_no_new_false_negatives_vs_baseline(replay_setup):
    """Every citation that resolved at record time must still resolve now."""
    verifier, baseline = replay_setup
    regressions = []
    for citation, base in baseline.items():
        if base.get("status") not in _FOUND:
            continue  # only guard cites that were resolved at baseline
        now = _replay_status(verifier, citation)
        if now not in _FOUND:
            regressions.append((citation, base["status"], now))

    assert not regressions, (
        f"{len(regressions)} real citation(s) that resolved at baseline now "
        f"fail (new false negatives):\n" + "\n".join(
            f"  {c[:60]}: {was} -> {now}" for c, was, now in regressions[:25]
        )
    )


def test_corpus_was_substantially_resolvable(replay_setup):
    """Sanity: the recorded baseline actually found most of the corpus, so the
    regression guard above is meaningful (not guarding an empty set)."""
    _, baseline = replay_setup
    verdicts = [b.get("status") for b in baseline.values()]
    found = sum(1 for s in verdicts if s in _FOUND)
    assert found >= 0.5 * len(verdicts), (
        f"baseline only resolved {found}/{len(verdicts)} — re-record or "
        f"investigate before trusting this as a regression guard"
    )
