"""Offline regression: the frozen corpora + recorded cassettes must keep
reproducing the two committed acceptance baselines (design SS8).

  1. Withers: 14/19 yellows caught (8 exact), greens 9 exact / 2
     over-flagged, reds 1 Red + 2 Gray. History: the 2026-06-11
     measurement run scored 12/19 (cross-checked row-for-row against
     tests/data/withers_assessment_results.csv); the SS6.4 quote rules
     (>=2-word span extraction + the banded quote_floor) added
     withers-09 (Am. Auto -- the 2-word "judicial admissions" quote,
     CLOSE@0.64) and withers-38 (Anderson -- CLOSE@0.73), with zero new
     green over-flags thanks to the near-verbatim CLOSE band
     (see proposition_pipeline._quote_floor).
  2. A/B opus baseline (ab_opus-baseline_20260323-002228.jsonl) scored
     against the CURRENT ab_test_cases.json ledger: payne 23/27,
     wainwright 33/34 -> 56/61 (91.8%, >= the 85% target). Note: the
     recording's own `correct` flags say payne 21/27 -- two payne cases
     (ids 16, 75) had expected_assessment revised in the ledger after the
     recording, both to agree with the model's answer. The ledger is
     authoritative (design SS7: one scoring path).

No network, no LLM: RecordedExecutor replay only. A prompt-template change
bumps the version key and makes these tests fail loudly via
RecordedVerdictMiss -- that is the cassette policy working as intended:
re-record live, update the numbers deliberately.
"""
from pathlib import Path

from citation_verifier.scoring import score_workdir

CORPORA = Path(__file__).parent / "data" / "assessment_corpora"

_RANK = {"Green": 0, "Yellow": 1, "Red": 2}


class TestWithersBaseline:
    def test_reproduces_assessment_baseline(self):
        s = score_workdir(CORPORA / "withers")
        assert s.yellows_total == 19
        assert s.yellows_caught == 14   # 12 measured + SS6.4 floors (+2)
        assert s.yellows_exact == 8
        assert s.greens_total == 12
        assert s.greens_exact == 9
        assert s.greens_overflagged == 2
        assert s.reds_total == 3
        assert s.reds_caught == 3  # 1 Red via WRONG_CASE + 2 Gray

    def test_known_misses_are_stable(self):
        """The remaining 5: -12 has no quotation marks in its proposition
        (not mechanically catchable); the rest are the judgment-call /
        author-hedged band (design SS1)."""
        s = score_workdir(CORPORA / "withers")
        missed = sorted(r["claim_id"] for r in s.rows
                        if r["expected"] == "yellow" and not r["correct"])
        assert missed == ["withers-05", "withers-12", "withers-32",
                          "withers-44", "withers-49"]


class TestABOpusBaseline:
    def test_payne(self):
        s = score_workdir(CORPORA / "payne")
        assert (s.correct, s.total) == (23, 27)

    def test_wainwright(self):
        s = score_workdir(CORPORA / "wainwright")
        assert (s.correct, s.total) == (33, 34)

    def test_lenient_direction_errors_pinned(self):
        """SS8.2 target: no NEW lenient-direction (Red->Yellow->Green)
        errors vs. the recorded runs. The recorded opus baseline itself
        contains exactly two; they are the allowed set."""
        lenient = []
        for name in ("payne", "wainwright"):
            s = score_workdir(CORPORA / name)
            for r in s.rows:
                if (not r["correct"]
                        and _RANK[r["predicted"]] < _RANK[r["expected"]]):
                    lenient.append(
                        (r["claim_id"], r["expected"], r["predicted"]))
        assert sorted(lenient) == [
            ("payne-03", "Red", "Yellow"),
            ("payne-58", "Yellow", "Green"),
        ]
