"""Unit tests for scorecard bootstrap math."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scorecard as sc  # noqa: E402


def test_green_rate_returns_zero_for_empty():
    assert sc.green_rate([]) == 0.0


def test_green_rate_counts_green_only():
    rs = [
        {"supports": "Green"},
        {"supports": "Yellow"},
        {"supports": ""},
        {"supports": "Green"},
    ]
    assert sc.green_rate(rs) == 0.5


def test_hallucination_excludes_unknown():
    rs = [
        {"real": "Y", "name_match": "Y", "model_response": "Foo v. Bar"},
        {"real": "N", "name_match": "N", "model_response": "Made-up case"},
        {"real": "N", "name_match": "N", "model_response": "UNKNOWN"},  # excluded
    ]
    # 1 of 2 answered = 50%
    assert sc.hallucination_rate(rs) == 0.5


def test_bootstrap_diff_returns_ci_tuple():
    a = [{"supports": "Green"}] * 100
    b = [{"supports": "Red"}] * 100
    lo, hi = sc.bootstrap_diff(a, b, sc.green_rate, n=200, seed=42)
    # Diff should be ~ +1.0 with tight CI
    assert lo > 0.5 and hi < 1.5


def test_bootstrap_diff_zero_overlap_when_identical():
    a = [{"supports": "Green"}] * 50 + [{"supports": "Yellow"}] * 50
    b = [{"supports": "Green"}] * 50 + [{"supports": "Yellow"}] * 50
    lo, hi = sc.bootstrap_diff(a, b, sc.green_rate, n=500, seed=42)
    assert lo < 0 < hi  # CI straddles 0


def test_unknown_rate_counts_unknown():
    rs = [
        {"model_response": "Foo v. Bar"},
        {"model_response": "UNKNOWN"},
        {"model_response": "  unknown "},  # whitespace + lowercase
        {"model_response": "Other"},
    ]
    assert sc.unknown_rate(rs) == 0.5
