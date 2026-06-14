"""Tests for the two-axis scoring module (design SS6.9 / SS8)."""
import csv

import pytest

from citation_verifier.executor import (
    RecordedExecutor,
    Verdict,
    append_verdict_jsonl,
)
from citation_verifier.scoring import (
    derive_color,
    predict_workdir,
    report_lane,
    score_workdir,
)


class TestDeriveColor:
    """The SS6.9 color table: color is a documented function of
    (existence, support, quote)."""

    @pytest.mark.parametrize("existence", [
        "NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"])
    def test_unlocatable_is_gray(self, existence):
        assert derive_color(existence, "supported", "VERBATIM") == "Gray"

    def test_wrong_case_is_red(self):
        assert derive_color("WRONG_CASE", "supported", "VERBATIM") == "Red"

    def test_cite_unconfirmed_is_check_cite_never_red(self):
        assert derive_color("CITE_UNCONFIRMED", "unsupported",
                            "FABRICATED") == "CheckCite"

    @pytest.mark.parametrize("quote", ["VERBATIM", "NO_QUOTES", None, ""])
    def test_verified_supported_clean_quotes_is_green(self, quote):
        assert derive_color("VERIFIED", "supported", quote) == "Green"

    @pytest.mark.parametrize("quote", ["CLOSE", "FABRICATED"])
    def test_verified_supported_bad_quote_floors_to_yellow(self, quote):
        assert derive_color("VERIFIED", "supported", quote) == "Yellow"

    def test_verified_partial_support_is_yellow(self):
        assert derive_color("VERIFIED_PARTIAL", "partial", "VERBATIM") == "Yellow"

    def test_verified_unsupported_is_red(self):
        assert derive_color("VERIFIED", "unsupported", "VERBATIM") == "Red"

    def test_verified_unverifiable_support_is_gray(self):
        assert derive_color("VERIFIED", "unverifiable", None) == "Gray"

    @pytest.mark.parametrize("existence", [
        "VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
        "VERIFIED_DOCKET_ONLY"])
    def test_all_verified_family_members_use_support_axis(self, existence):
        assert derive_color(existence, "unsupported", None) == "Red"


class TestReportLane:
    """SS6.9 lane precedence under the single-color v1 verdict schema
    (Step 7 plan decision): existence lanes 1-3 beat the assessment
    column; otherwise the floor-enforced assessment is authoritative."""

    def test_wrong_case_red_even_when_unassessed(self):
        assert report_lane("WRONG_CASE", "", "") == "Red"

    def test_wrong_case_red_ignores_assessment(self):
        assert report_lane("WRONG_CASE", "Green", "opinions/a.html") == "Red"

    def test_cite_unconfirmed_is_check_cite_never_red(self):
        assert report_lane("CITE_UNCONFIRMED", "Red",
                           "opinions/a.html") == "CheckCite"

    def test_cite_unconfirmed_check_cite_even_when_green(self):
        assert report_lane("CITE_UNCONFIRMED", "Green",
                           "opinions/a.html") == "CheckCite"

    @pytest.mark.parametrize("status", [
        "NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"])
    def test_unlocatable_without_text_is_gray(self, status):
        assert report_lane(status, "", "") == "Gray"

    def test_unlocatable_with_opinion_falls_to_assessment(self):
        # Shouldn't occur in practice; documented fall-through.
        assert report_lane("NOT_FOUND", "Green", "opinions/a.html") == "Green"

    @pytest.mark.parametrize("assessment,lane", [
        ("Green", "Green"), ("Red", "Red"), ("Yellow", "Yellow"),
        ("green", "Green"), ("", "Yellow")])
    def test_verified_family_assessment_is_authoritative(
            self, assessment, lane):
        assert report_lane("VERIFIED", assessment,
                           "opinions/a.html") == lane

    def test_legacy_empty_status_unassessed_is_yellow(self):
        assert report_lane("", "", "") == "Yellow"


def make_workdir(tmp_path):
    """Synthetic 4-claim corpus exercising every deterministic lane."""
    wd = tmp_path / "corpus"
    (wd / "opinions").mkdir(parents=True)
    (wd / "jobs").mkdir()
    (wd / "opinions" / "A.html").write_text("opinion A", encoding="utf-8")
    claims = [
        # agent lane: located with opinion text
        {"claim_id": "t-01", "cl_status": "VERIFIED",
         "opinion_file": "opinions/A.html"},
        # deterministic: WRONG_CASE -> Red
        {"claim_id": "t-02", "cl_status": "WRONG_CASE", "opinion_file": ""},
        # deterministic: not located, no text -> Gray
        {"claim_id": "t-03", "cl_status": "NOT_FOUND", "opinion_file": ""},
        # deterministic: located but no opinion text -> Yellow
        {"claim_id": "t-04", "cl_status": "VERIFIED", "opinion_file": ""},
    ]
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["claim_id", "cl_status",
                                          "opinion_file"])
        w.writeheader()
        w.writerows(claims)
    gt = [
        {"claim_id": "t-01", "scale": "internal", "expected": "Yellow"},
        {"claim_id": "t-02", "scale": "internal", "expected": "Red"},
        {"claim_id": "t-03", "scale": "internal", "expected": "Green"},
        {"claim_id": "t-04", "scale": "internal", "expected": "Yellow"},
    ]
    with (wd / "ground_truth.csv").open("w", newline="",
                                        encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["claim_id", "scale", "expected"])
        w.writeheader()
        w.writerows(gt)
    append_verdict_jsonl(
        wd / "jobs" / "assess_results.jsonl",
        Verdict(claim_id="t-01",
                fields={"assessment": "Yellow", "rationale": "r"},
                model="opus", prompt_version="assess-v1"))
    return wd


class TestPredictWorkdir:
    def test_lanes_and_agent_replay(self, tmp_path):
        wd = make_workdir(tmp_path)
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Yellow"
        assert preds["t-01"].mode == "agent"
        assert preds["t-02"].predicted == "Red"
        assert preds["t-02"].mode == "deterministic"
        assert preds["t-03"].predicted == "Gray"
        assert preds["t-04"].predicted == "Yellow"
        assert preds["t-04"].mode == "deterministic"


class TestPredictWorkdirV2:
    def test_v2_verdict_color_derived(self, tmp_path):
        wd = make_workdir(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        append_verdict_jsonl(
            wd / "jobs" / "assess_results.jsonl",
            Verdict(claim_id="t-01",
                    fields={"support": "unsupported",
                            "finding_analysis": "fa"},
                    model="opus", prompt_version="assess-v2"))
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p
                 for p in predict_workdir(wd, ex, "assess-v2")}
        assert preds["t-01"].predicted == "Red"
        assert preds["t-01"].mode == "agent"
        assert preds["t-01"].rationale == "fa"


class TestScoreWorkdir:
    def test_internal_scale_exact_match(self, tmp_path):
        wd = make_workdir(tmp_path)
        report = score_workdir(wd)
        assert report.total == 4
        # t-01 Yellow==Yellow, t-02 Red==Red, t-04 Yellow==Yellow correct;
        # t-03 Gray vs Green incorrect
        assert report.correct == 3
        wrong = [r for r in report.rows if not r["correct"]]
        assert [r["claim_id"] for r in wrong] == ["t-03"]

    def test_withers_scale_mapping(self, tmp_path):
        wd = make_workdir(tmp_path)
        # rewrite ground truth on the exhibit scale
        gt = [
            # exhibit yellow caught by our Yellow
            {"claim_id": "t-01", "scale": "withers_exhibit",
             "expected": "yellow"},
            # exhibit red caught by Red-via-WRONG_CASE
            {"claim_id": "t-02", "scale": "withers_exhibit",
             "expected": "red"},
            # exhibit green, we said Gray -> unable (not over-flagged,
            # not exact)
            {"claim_id": "t-03", "scale": "withers_exhibit",
             "expected": "green"},
            # exhibit green, we said Yellow -> over-flagged
            {"claim_id": "t-04", "scale": "withers_exhibit",
             "expected": "green"},
        ]
        with (wd / "ground_truth.csv").open("w", newline="",
                                            encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["claim_id", "scale",
                                              "expected"])
            w.writeheader()
            w.writerows(gt)
        report = score_workdir(wd)
        assert report.yellows_total == 1
        assert report.yellows_caught == 1
        assert report.reds_total == 1
        assert report.reds_caught == 1
        assert report.greens_total == 2
        assert report.greens_exact == 0
        assert report.greens_overflagged == 1


def _set_claim_column(wd, claim_id, column, value):
    rows = list(csv.DictReader((wd / "claims.csv").open(encoding="utf-8")))
    fields = list(rows[0].keys())
    if column not in fields:
        fields.append(column)
    for r in rows:
        r.setdefault(column, "")
        if r["claim_id"] == claim_id:
            r[column] = value
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _replace_cassette(wd, assessment):
    (wd / "jobs" / "assess_results.jsonl").unlink()
    append_verdict_jsonl(
        wd / "jobs" / "assess_results.jsonl",
        Verdict(claim_id="t-01",
                fields={"assessment": assessment, "rationale": "r"},
                model="opus", prompt_version="assess-v1"))


class TestQuoteFloor:
    """SS6.4: quote_floor sets the minimum severity for agent verdicts;
    deterministic lanes are unaffected."""

    def test_floor_raises_replayed_green_to_yellow(self, tmp_path):
        wd = make_workdir(tmp_path)
        _set_claim_column(wd, "t-01", "quote_floor", "Yellow")
        _replace_cassette(wd, "Green")
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Yellow"
        assert preds["t-01"].floored is True

    def test_floor_never_lowers(self, tmp_path):
        wd = make_workdir(tmp_path)
        _set_claim_column(wd, "t-01", "quote_floor", "Yellow")
        _replace_cassette(wd, "Red")
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Red"
        assert preds["t-01"].floored is False

    def test_no_floor_column_unchanged(self, tmp_path):
        wd = make_workdir(tmp_path)
        _replace_cassette(wd, "Green")
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Green"
