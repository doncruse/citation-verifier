"""Tests for the LLM executor protocol and RecordedExecutor (design SS5).

Offline only -- no network, no LLM. RecordedExecutor is the assessment-side
mirror of tests/cassette_client.py.
"""
import json

import pytest

from citation_verifier.executor import (
    Job,
    RecordedExecutor,
    RecordedVerdictMiss,
    Verdict,
    append_verdict_jsonl,
    load_verdicts_jsonl,
)


def _verdict(claim_id="w-01", version="assess-v1", assessment="Yellow"):
    return Verdict(
        claim_id=claim_id,
        fields={"assessment": assessment, "rationale": "test rationale"},
        model="opus",
        prompt_version=version,
        elapsed_s=1.5,
        cost_usd=0.02,
    )


class TestVerdictSerde:
    def test_round_trip_through_jsonl(self, tmp_path):
        path = tmp_path / "results.jsonl"
        v1 = _verdict("w-01")
        v2 = _verdict("w-02", assessment="Green")
        append_verdict_jsonl(path, v1)
        append_verdict_jsonl(path, v2)
        loaded = load_verdicts_jsonl(path)
        assert loaded == [v1, v2]

    def test_jsonl_lines_are_flat_json_objects(self, tmp_path):
        path = tmp_path / "results.jsonl"
        append_verdict_jsonl(path, _verdict())
        line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert line["claim_id"] == "w-01"
        assert line["prompt_version"] == "assess-v1"
        assert line["fields"]["assessment"] == "Yellow"

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_verdicts_jsonl(tmp_path / "nope.jsonl")

    def test_job_defaults(self):
        job = Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                  prompt_version="assess-v1")
        assert job.files == []
        assert job.schema is None
        assert job.max_chars is None


class TestRecordedExecutor:
    @pytest.fixture
    def cassette(self, tmp_path):
        path = tmp_path / "assess_results.jsonl"
        append_verdict_jsonl(path, _verdict("w-01", assessment="Yellow"))
        append_verdict_jsonl(path, _verdict("w-02", assessment="Green"))
        return path

    def test_replays_recorded_verdicts(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01", "w-02"], prompt="ignored",
                    prompt_version="assess-v1")]
        verdicts = list(ex.run(jobs))
        assert [v.claim_id for v in verdicts] == ["w-01", "w-02"]
        assert verdicts[0].fields["assessment"] == "Yellow"
        assert verdicts[1].fields["assessment"] == "Green"

    def test_unknown_claim_raises_miss(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-99"], prompt="p",
                    prompt_version="assess-v1")]
        with pytest.raises(RecordedVerdictMiss):
            list(ex.run(jobs))
        assert ex.misses == [("w-99", "assess-v1")]

    def test_prompt_version_mismatch_raises_miss(self, cassette):
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                    prompt_version="assess-v2")]
        with pytest.raises(RecordedVerdictMiss):
            list(ex.run(jobs))

    def test_duplicate_claim_id_last_write_wins(self, cassette):
        append_verdict_jsonl(cassette, _verdict("w-01", assessment="Red"))
        ex = RecordedExecutor(cassette)
        jobs = [Job(job_id="j1", claim_ids=["w-01"], prompt="p",
                    prompt_version="assess-v1")]
        (v,) = list(ex.run(jobs))
        assert v.fields["assessment"] == "Red"
