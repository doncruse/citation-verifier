"""MessagesAPIExecutor (direct Messages API transport) + RecordedExecutor
skip mode. All offline -- the anthropic client is injected as a fake
(cost-audit F1 / plan 2026-07-01-messages-api-executor-plan.md)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from citation_verifier.executor import (  # noqa: E402
    Job,
    MessagesAPIAuthError,
    MessagesAPIExecutor,
    RecordedExecutor,
    RecordedVerdictMiss,
    Verdict,
    append_verdict_jsonl,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _message(text, stop_reason="end_turn", usage=None):
    return SimpleNamespace(
        content=[_text_block(text)],
        stop_reason=stop_reason,
        usage=usage or SimpleNamespace(
            input_tokens=0, output_tokens=0,
            cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )


class FakeStream:
    def __init__(self, message_or_exc):
        self._m = message_or_exc

    def __enter__(self):
        if isinstance(self._m, Exception):
            raise self._m
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._m


class FakeMessages:
    """messages.stream(...) dispenses canned messages; records params."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, **params):
        self.calls.append(params)
        return FakeStream(self.responses.pop(0))


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _batch_result(custom_id, rtype="succeeded", message=None):
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(type=rtype, message=message))


class FakeBatchClient:
    def __init__(self, results, statuses=("in_progress", "ended")):
        self._results = results
        self._statuses = list(statuses)
        self.created_requests = None
        self.messages = SimpleNamespace(batches=SimpleNamespace(
            create=self._create, retrieve=self._retrieve,
            results=self._results_fn))

    def _create(self, requests):
        self.created_requests = requests
        return SimpleNamespace(id="batch_1",
                               processing_status=self._statuses.pop(0))

    def _retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id,
                               processing_status=self._statuses.pop(0))

    def _results_fn(self, batch_id):
        return iter(self._results)


def _job(job_id="assess-x-01", claim_ids=("x-01",), prompt="PROMPT",
         files=(), version="assess-v2"):
    return Job(job_id=job_id, claim_ids=list(claim_ids), prompt=prompt,
               prompt_version=version, files=list(files))


VERDICT_JSON = json.dumps({"assessment": "Green", "rationale": "fine"})


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------

class TestRequestConstruction:
    def test_alias_resolves_and_verdict_records_full_id(self):
        ex = MessagesAPIExecutor(model="opus",
                                 client=FakeClient([_message(VERDICT_JSON)]))
        (v,) = list(ex.run([_job()]))
        assert ex.model == "claude-opus-4-8"
        assert v.model == "claude-opus-4-8"

    def test_explicit_model_id_passes_through(self):
        ex = MessagesAPIExecutor(model="claude-sonnet-4-6", client=FakeClient([]))
        assert ex.model == "claude-sonnet-4-6"

    def test_text_file_inlined_before_verbatim_prompt(self, tmp_path):
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "A.html").write_text(
            "<p>opinion body</p>", encoding="utf-8")
        client = FakeClient([_message(VERDICT_JSON)])
        ex = MessagesAPIExecutor(model="opus", cwd=tmp_path, client=client)
        list(ex.run([_job(files=["opinions/A.html"], prompt="THE PROMPT")]))
        content = client.messages.calls[0]["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert '<file path="opinions/A.html">' in content[0]["text"]
        assert "opinion body" in content[0]["text"]
        # prompt is verbatim in the final block, after the bridge note
        assert content[-1]["text"].endswith("THE PROMPT")
        assert "no tools" in content[-1]["text"]

    def test_pdf_becomes_document_block(self, tmp_path):
        (tmp_path / "brief.pdf").write_bytes(b"%PDF-1.4 fake")
        client = FakeClient([_message(VERDICT_JSON)])
        ex = MessagesAPIExecutor(model="opus", client=client)
        list(ex.run([_job(files=[str(tmp_path / "brief.pdf")])]))
        content = client.messages.calls[0]["messages"][0]["content"]
        assert content[0]["type"] == "document"
        assert content[0]["source"]["media_type"] == "application/pdf"

    def test_thinking_adaptive_for_opus_absent_for_haiku(self):
        c1 = FakeClient([_message(VERDICT_JSON)])
        list(MessagesAPIExecutor(model="opus", client=c1).run([_job()]))
        assert c1.messages.calls[0]["thinking"] == {"type": "adaptive"}
        c2 = FakeClient([_message(VERDICT_JSON)])
        list(MessagesAPIExecutor(model="haiku", client=c2).run([_job()]))
        assert "thinking" not in c2.messages.calls[0]


# ---------------------------------------------------------------------------
# Results, failures, cost
# ---------------------------------------------------------------------------

class TestResults:
    def test_packed_verdicts_fan_out(self):
        packed = json.dumps({"verdicts": [
            {"claim_id": "x-01", "support": "supported"},
            {"claim_id": "x-02", "support": "partial"},
        ]})
        ex = MessagesAPIExecutor(model="opus",
                                 client=FakeClient([_message(packed)]))
        vs = list(ex.run([_job(claim_ids=("x-01", "x-02"))]))
        assert [v.claim_id for v in vs] == ["x-01", "x-02"]
        assert vs[0].fields["support"] == "supported"
        assert vs[1].cost_usd == 0.0  # cost on first claim only

    def test_unparseable_result_records_failure_with_stop_reason(self):
        ex = MessagesAPIExecutor(
            model="opus",
            client=FakeClient([_message("no json here",
                                        stop_reason="max_tokens")]))
        assert list(ex.run([_job()])) == []
        assert len(ex.failures) == 1
        assert "max_tokens" in ex.failures[0][1]

    def test_auth_error_raises_immediately(self):
        class AuthenticationError(Exception):
            pass

        ex = MessagesAPIExecutor(
            model="opus", client=FakeClient([AuthenticationError("401")]))
        with pytest.raises(MessagesAPIAuthError):
            list(ex.run([_job()]))

    def test_other_error_recorded_and_run_continues(self):
        ex = MessagesAPIExecutor(
            model="opus", max_concurrency=1,
            client=FakeClient([RuntimeError("boom"),
                               _message(VERDICT_JSON)]))
        vs = list(ex.run([_job(job_id="j1", claim_ids=("a",)),
                          _job(job_id="j2", claim_ids=("b",))]))
        assert [v.claim_id for v in vs] == ["b"]
        assert ex.failures[0][0] == "j1"

    def test_cost_from_usage_at_published_rates(self):
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000,
                                cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)
        ex = MessagesAPIExecutor(
            model="opus", client=FakeClient([_message(VERDICT_JSON,
                                                      usage=usage)]))
        (v,) = list(ex.run([_job()]))
        assert v.cost_usd == pytest.approx(5.0 + 2.5)  # $5/M in, $25/M out

    def test_empty_jobs_no_client_needed(self):
        ex = MessagesAPIExecutor(model="opus")  # no client injected
        assert list(ex.run([])) == []


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

class TestBatchMode:
    def test_batch_maps_custom_ids_and_halves_cost(self):
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0,
                                cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)
        results = [
            _batch_result("j2", message=_message(VERDICT_JSON, usage=usage)),
            _batch_result("j1", rtype="errored"),
        ]
        client = FakeBatchClient(results)
        ex = MessagesAPIExecutor(model="opus", batch=True,
                                 poll_interval_s=0.0, client=client)
        vs = list(ex.run([_job(job_id="j1", claim_ids=("a",)),
                          _job(job_id="j2", claim_ids=("b",))]))
        assert [r["custom_id"] for r in client.created_requests] == \
            ["j1", "j2"]
        assert [v.claim_id for v in vs] == ["b"]  # results arrive unordered
        assert vs[0].cost_usd == pytest.approx(2.5)  # 50% off $5/M
        assert ("j1", "batch result: errored") in ex.failures


# ---------------------------------------------------------------------------
# RecordedExecutor skip mode (A/B harness robustness, TODO Priority-1)
# ---------------------------------------------------------------------------

class TestRecordedExecutorSkipMode:
    @pytest.fixture
    def cassette(self, tmp_path):
        path = tmp_path / "assess_results.jsonl"
        append_verdict_jsonl(path, Verdict(
            claim_id="c-01", fields={"assessment": "Green"},
            prompt_version="assess-v1"))
        return path

    def _jobs(self):
        return [_job(job_id="a", claim_ids=("c-01",), version="assess-v1"),
                _job(job_id="b", claim_ids=("c-02",), version="assess-v1"),
                _job(job_id="c", claim_ids=("c-01",), version="assess-v1")]

    def test_default_still_raises_on_gap(self, cassette):
        ex = RecordedExecutor(cassette)
        with pytest.raises(RecordedVerdictMiss):
            list(ex.run(self._jobs()))

    def test_skip_yields_present_and_records_misses(self, cassette):
        ex = RecordedExecutor(cassette, missing="skip")
        vs = list(ex.run(self._jobs()))
        assert [v.claim_id for v in vs] == ["c-01", "c-01"]
        assert ex.misses == [("c-02", "assess-v1")]

    def test_skip_tolerates_missing_results_file(self, tmp_path):
        ex = RecordedExecutor(tmp_path / "nope.jsonl", missing="skip")
        assert list(ex.run(self._jobs())) == []
        assert len(ex.misses) == 3

    def test_invalid_missing_value_rejected(self, cassette):
        with pytest.raises(ValueError):
            RecordedExecutor(cassette, missing="ignore")
