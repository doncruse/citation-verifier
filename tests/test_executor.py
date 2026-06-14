"""Tests for the LLM executor protocol and RecordedExecutor (design SS5).

Offline only -- no network, no LLM. RecordedExecutor is the assessment-side
mirror of tests/cassette_client.py.
"""
import json

import pytest

from citation_verifier.executor import (
    AgentToolExecutor,
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


class TestAgentToolExecutor:
    def _jobs(self):
        return [
            Job(job_id="assess-w-01", claim_ids=["w-01"], prompt="P1",
                prompt_version="assess-v1", files=["opinions/A.html"]),
            Job(job_id="assess-w-02", claim_ids=["w-02"], prompt="P2",
                prompt_version="assess-v1"),
        ]

    def test_writes_jobs_file_and_yields_nothing(self, tmp_path):
        path = tmp_path / "jobs" / "assess.json"
        ex = AgentToolExecutor(path)
        verdicts = list(ex.run(self._jobs()))
        assert verdicts == []
        assert ex.pending == ["w-01", "w-02"]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert [j["job_id"] for j in data] == ["assess-w-01", "assess-w-02"]
        assert data[0]["prompt"] == "P1"
        assert data[0]["prompt_version"] == "assess-v1"
        assert data[0]["files"] == ["opinions/A.html"]

    def test_rerun_replaces_jobs_file(self, tmp_path):
        path = tmp_path / "assess.json"
        ex = AgentToolExecutor(path)
        list(ex.run(self._jobs()))
        list(ex.run(self._jobs()[:1]))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert ex.pending == ["w-01"]


class FakeResultMessage:
    """Duck-typed stand-in for claude_agent_sdk ResultMessage."""
    def __init__(self, result, is_error=False, total_cost_usd=0.02,
                 duration_ms=1500, num_turns=2):
        self.result = result
        self.is_error = is_error
        self.total_cost_usd = total_cost_usd
        self.duration_ms = duration_ms
        self.num_turns = num_turns


class FakeOtherMessage:
    """Non-result message (AssistantMessage etc.) the executor must skip."""


def _fake_query_fn(per_call_messages, drained=None, env_seen=None):
    """Returns a query_fn(prompt=, options=) yielding canned messages.

    per_call_messages: list of message-lists, one per invocation.
    drained: list appended to AFTER the last yield -- only reached when the
        consumer drains the generator fully (early break never resumes past
        the final yield).
    env_seen: dict capturing os.environ keys of interest at call time.
    """
    calls = []

    def query_fn(*, prompt, options):
        calls.append({"prompt": prompt, "options": options})
        messages = per_call_messages[len(calls) - 1]

        async def gen():
            for m in messages:
                yield m
            if drained is not None:
                drained.append(True)
        if env_seen is not None:
            import os
            env_seen["ANTHROPIC_BASE_URL"] = os.environ.get(
                "ANTHROPIC_BASE_URL", "<absent>")
        return gen()

    query_fn.calls = calls
    return query_fn


def _sdk_job(claim_id="w-01", version="assess-v1"):
    return Job(job_id=f"assess-{claim_id}", claim_ids=[claim_id],
               prompt=f"PROMPT {claim_id}", prompt_version=version,
               files=["opinions/A.html"])


class TestAgentSDKExecutor:
    def test_happy_path_yields_verdict(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[
            FakeOtherMessage(),
            FakeResultMessage('{"assessment": "Yellow", "rationale": "r"}'),
        ]])
        ex = AgentSDKExecutor(model="opus", query_fn=qf)
        (v,) = list(ex.run([_sdk_job()]))
        assert v.claim_id == "w-01"
        assert v.fields == {"assessment": "Yellow", "rationale": "r"}
        assert v.model == "opus"
        assert v.prompt_version == "assess-v1"
        assert v.cost_usd == 0.02
        assert v.elapsed_s == 1.5
        assert ex.failures == []

    def test_options_restrict_tools_and_model(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage('{"a": 1}')]])
        ex = AgentSDKExecutor(model="haiku", max_turns=3, query_fn=qf)
        list(ex.run([_sdk_job()]))
        opts = qf.calls[0]["options"]
        assert opts.allowed_tools == ["Read"]
        assert opts.model == "haiku"
        assert opts.max_turns == 3

    def test_generator_drained_fully(self):
        """ResultMessage mid-stream: the executor must keep consuming
        (early return segfaults at shutdown on Windows, design SS5.1)."""
        from citation_verifier.executor import AgentSDKExecutor
        drained = []
        qf = _fake_query_fn([[
            FakeResultMessage('{"a": 1}'),
            FakeOtherMessage(),
            FakeOtherMessage(),
        ]], drained=drained)
        ex = AgentSDKExecutor(query_fn=qf)
        list(ex.run([_sdk_job()]))
        assert drained == [True]

    def test_strips_parent_env_and_restores(self, monkeypatch):
        from citation_verifier.executor import AgentSDKExecutor
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://parent-proxy")
        env_seen = {}
        qf = _fake_query_fn([[FakeResultMessage('{"a": 1}')]],
                            env_seen=env_seen)
        ex = AgentSDKExecutor(query_fn=qf)
        list(ex.run([_sdk_job()]))
        assert env_seen["ANTHROPIC_BASE_URL"] == "<absent>"
        import os
        assert os.environ["ANTHROPIC_BASE_URL"] == "http://parent-proxy"

    def test_auth_error_raises_and_stops(self):
        from citation_verifier.executor import (
            AgentSDKAuthError, AgentSDKExecutor)
        qf = _fake_query_fn([
            [FakeResultMessage(
                "API Error: 401 OAuth token has expired", is_error=True)],
            [FakeResultMessage('{"a": 1}')],  # must never be reached
        ])
        ex = AgentSDKExecutor(query_fn=qf)
        with pytest.raises(AgentSDKAuthError, match="claude login"):
            list(ex.run([_sdk_job("w-01"), _sdk_job("w-02")]))
        assert len(qf.calls) == 1

    def test_non_auth_error_recorded_and_continues(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([
            [FakeResultMessage("rate limited, try later", is_error=True)],
            [FakeResultMessage('{"assessment": "Green", "rationale": "r"}')],
        ])
        ex = AgentSDKExecutor(query_fn=qf)
        verdicts = list(ex.run([_sdk_job("w-01"), _sdk_job("w-02")]))
        assert [v.claim_id for v in verdicts] == ["w-02"]
        assert len(ex.failures) == 1
        assert ex.failures[0][0] == "assess-w-01"

    def test_unparseable_result_recorded_no_verdict(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage("I could not find a JSON")]])
        ex = AgentSDKExecutor(query_fn=qf)
        assert list(ex.run([_sdk_job()])) == []
        assert ex.failures[0][0] == "assess-w-01"

    def test_no_result_message_recorded(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeOtherMessage()]])
        ex = AgentSDKExecutor(query_fn=qf)
        assert list(ex.run([_sdk_job()])) == []
        assert ex.failures[0][0] == "assess-w-01"

    def test_json_extracted_from_surrounding_prose(self):
        """PoC parse rule: text between first '{' and last '}'."""
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(
            'Here is my verdict:\n{"assessment": "Red", "rationale": "x"}\n')]])
        ex = AgentSDKExecutor(query_fn=qf)
        (v,) = list(ex.run([_sdk_job()]))
        assert v.fields["assessment"] == "Red"

    # --- packed-job verdicts array (assess-v2, Step 8) ---

    def _packed_job(self):
        return Job(job_id="assess-op1", claim_ids=["w-01", "w-02"],
                   prompt="P", prompt_version="assess-v2",
                   files=["opinions/A.html"])

    def test_verdicts_array_fans_out_per_claim(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(json.dumps({"verdicts": [
            {"claim_id": "w-01", "support": "supported",
             "badge_label": "Supported", "brief_block": "",
             "opinion_block": "", "finding_analysis": "ok"},
            {"claim_id": "w-02", "support": "unsupported",
             "badge_label": "Not supported by cited case",
             "brief_block": "b", "opinion_block": "o",
             "finding_analysis": "bad"},
        ]}))]])
        ex = AgentSDKExecutor(query_fn=qf)
        verdicts = list(ex.run([self._packed_job()]))
        assert [v.claim_id for v in verdicts] == ["w-01", "w-02"]
        assert verdicts[0].fields["support"] == "supported"
        assert "claim_id" not in verdicts[0].fields
        assert verdicts[1].fields["finding_analysis"] == "bad"
        assert verdicts[0].prompt_version == "assess-v2"
        assert ex.failures == []

    def test_unknown_claim_id_in_array_recorded_not_emitted(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(json.dumps({"verdicts": [
            {"claim_id": "w-01", "support": "supported"},
            {"claim_id": "w-99", "support": "supported"},
        ]}))]])
        ex = AgentSDKExecutor(query_fn=qf)
        verdicts = list(ex.run([self._packed_job()]))
        assert [v.claim_id for v in verdicts] == ["w-01"]
        assert any("w-99" in reason for _, reason in ex.failures)

    def test_missing_claim_stays_pending_silently(self):
        """An array missing a claim emits the rest; resume re-runs it."""
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(json.dumps({"verdicts": [
            {"claim_id": "w-02", "support": "partial"},
        ]}))]])
        ex = AgentSDKExecutor(query_fn=qf)
        verdicts = list(ex.run([self._packed_job()]))
        assert [v.claim_id for v in verdicts] == ["w-02"]

    def test_plain_exception_from_sdk_recorded_and_continues(self):
        """Live finding (Step 8 re-record): the SDK can raise a plain
        Exception ('Claude Code returned an error result: ...') from its
        message stream on transient API blips. One flaky job must not
        kill a 50-job batch -- record the failure, keep going; the
        resume key re-runs it next invocation."""
        from citation_verifier.executor import AgentSDKExecutor

        def exploding_query_fn(*, prompt, options):
            async def gen():
                raise Exception(
                    "Claude Code returned an error result: success")
                yield  # pragma: no cover
            return gen()

        calls = []

        def second_ok(*, prompt, options):
            calls.append(prompt)
            async def gen():
                yield FakeResultMessage('{"assessment": "Green", '
                                        '"rationale": "r"}')
            return gen()

        dispatch = [exploding_query_fn, second_ok]

        def qf(*, prompt, options):
            return dispatch.pop(0)(prompt=prompt, options=options)

        ex = AgentSDKExecutor(query_fn=qf)
        verdicts = list(ex.run([_sdk_job("w-01"), _sdk_job("w-02")]))
        assert [v.claim_id for v in verdicts] == ["w-02"]
        assert len(ex.failures) == 1
        assert "error result" in ex.failures[0][1]

    def test_plain_exception_with_auth_marker_still_raises(self):
        from citation_verifier.executor import (
            AgentSDKAuthError, AgentSDKExecutor)

        def exploding_query_fn(*, prompt, options):
            async def gen():
                raise Exception("401 OAuth token has expired")
                yield  # pragma: no cover
            return gen()

        ex = AgentSDKExecutor(query_fn=exploding_query_fn)
        with pytest.raises(AgentSDKAuthError):
            list(ex.run([_sdk_job("w-01")]))

    def test_single_object_fanout_unchanged_for_v1(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(
            '{"assessment": "Green", "rationale": "r"}')]])
        ex = AgentSDKExecutor(query_fn=qf)
        (v,) = list(ex.run([_sdk_job("w-01")]))
        assert v.fields["assessment"] == "Green"
