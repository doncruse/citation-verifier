# Proposition-Verifier Step 5: AgentSDKExecutor + extract Verb — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land design §10 step 5: the `AgentSDKExecutor` (the headless default transport, design §5/§5.1) and the `extract` verb (design §3 row 0: document → claims.csv + citations_toa.txt + citations_body.txt through a versioned `extract-v1` template), both offline-testable; one gated live smoke for the SDK transport.

**Architecture:** `AgentSDKExecutor` lives in `executor.py` beside the other adapters and satisfies the same `LLMExecutor` protocol: it runs each job as one headless `claude-agent-sdk` `query()` (one CLI subprocess per job), drains the async generator fully (Windows segfault otherwise, §5.1), strips `ANTHROPIC*`/`CLAUDE*` from `os.environ` around the SDK import + call (the SDK's `options.env` only *merges* over inherited env — verified in `subprocess_cli.py` — so stripping must happen in our process, exactly as the PoC did), restricts to `allowed_tools=["Read"]`, and detects auth failures (stale CLI OAuth → 401) to raise `AgentSDKAuthError("run `claude login`")` immediately instead of failing N jobs. The `extract` verb mirrors `assess`'s jobs-file/JSONL/resume shape with a single job whose resume key is the synthetic row id `"extract"`; ingestion writes `claims.csv` (pipeline assigns `claim_id = <workdir.name>-NN`), `citations_toa.txt`, `citations_body.txt`.

**Tech stack:** `claude-agent-sdk` 0.2.97 (already in venv, PoC green at `tests/poc_agent_sdk_executor.py`), `anyio` (SDK dependency), stdlib elsewhere. Tests: pytest, offline (mocked SDK via injected `query_fn`; `RecordedExecutor` for extract).

**Source facts (verified this session):**
- `ClaudeAgentOptions` fields include `allowed_tools`, `max_turns`, `model`, `cwd`, `env`; but `subprocess_cli.py` builds `process_env = {**inherited_env, ..., **options.env}` — `env` cannot REMOVE inherited `ANTHROPIC_BASE_URL`, so the executor strips `os.environ` (restore in `finally`).
- SDK error types: `CLINotFoundError`, `ProcessError`, `ClaudeSDKError` (base), `CLIConnectionError`, `CLIJSONDecodeError`.
- PoC validated: `query()` yields messages ending in a `ResultMessage` with `result` (text), `is_error`, `total_cost_usd`, `num_turns`, `duration_ms`; partial consumption segfaults at shutdown on Windows; verdict JSON is parsed `text[text.find("{") : text.rfind("}")+1]`.
- Jobs-mode plumbing to mirror (assess, Step 4): `jobs/<phase>.json` via `AgentToolExecutor`, `jobs/<phase>_results.jsonl` via `append_verdict_jsonl`, resume key = (claim_id, prompt_version), `_update_run_json` stamp.
- extract-v1 template content sources: SKILL.md Phase 1a (citation list rules incl. TOA-vs-body both-variants rule) + Phase 1c (claims.csv column rules, exact-citation-text rule) + design §6.3 (`cited_for`) + §6.8 external-tool prohibition (allowed in this template — extract-v1 has no cassettes yet; assess-v1 stays untouched).
- `prompts/*.md` package-data already configured in `pyproject.toml` (Step 4).

**Scope notes:**
- Live validation of `extract` waits for a real brief run (per Step 5 brief); offline `RecordedExecutor` tests only.
- The SDK live smoke is ONE job (gated: PoC auth smoke first; stop and ask the user to `claude login` if stale). No full-corpus live run without user sign-off.
- `MessagesAPIExecutor` stays unbuilt (design: build last, optional).

---

### Task 1: `AgentSDKExecutor` (offline, mocked SDK)

**Files:**
- Modify: `src/citation_verifier/executor.py` (append after `RecordedExecutor`)
- Test: `tests/test_executor.py` (append `TestAgentSDKExecutor`)

- [x] **1.1 Write the failing tests** — append to `tests/test_executor.py`:

```python
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
```

- [x] **1.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v -k AgentSDK`
Expected: FAIL — `ImportError: cannot import name 'AgentSDKExecutor'`

- [x] **1.3 Implement** — append to `src/citation_verifier/executor.py` (add `import os`, `import re`, `from contextlib import contextmanager` at top):

```python
# ---------------------------------------------------------------------------
# AgentSDKExecutor (design SS5 / SS5.1): the headless default transport.
# ---------------------------------------------------------------------------

_SDK_ENV_PREFIXES = ("ANTHROPIC", "CLAUDE")

# Markers of a stale/absent CLI OAuth credential (SS5.1: the desktop app
# refreshes its own auth, not the CLI's -- a headless 401 means the user
# must run `claude login`). Checked case-insensitively.
_AUTH_MARKERS = ("401", "authentication", "oauth", "api key",
                 "logged out", "log in", "login")

_AUTH_HELP = ("Claude CLI credentials are stale or missing (401). "
              "Run `claude login` in a terminal, then rerun this verb. "
              "No further jobs were attempted.")


class AgentSDKAuthError(RuntimeError):
    """Headless auth failure -- stop immediately, don't burn N jobs."""


@contextmanager
def _stripped_parent_env():
    """Remove ANTHROPIC*/CLAUDE* env around the SDK import + call.

    Inside a Claude Code session the parent's ANTHROPIC_BASE_URL / CLAUDE*
    leak into the spawned CLI and break auth (design SS5.1). The SDK's
    options.env only MERGES over inherited os.environ (it cannot remove
    keys), so the strip must happen here. Restored on exit."""
    saved = {k: os.environ.pop(k) for k in list(os.environ)
             if k.startswith(_SDK_ENV_PREFIXES)}
    try:
        yield
    finally:
        os.environ.update(saved)


def _looks_like_auth_failure(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _AUTH_MARKERS)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """PoC parse rule: the JSON object between the first '{' and the last
    '}' in the result text. None when absent or invalid."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class AgentSDKExecutor:
    """Headless default (design SS5): one claude-agent-sdk query() per job.

    allowed_tools=["Read"] only; model from config. Drains the SDK's async
    generator fully (partial consumption segfaults at shutdown on Windows,
    SS5.1). Auth failures raise AgentSDKAuthError immediately; other
    per-job failures are recorded in .failures (job_id, reason) and the
    run continues -- unfinished claims stay pending for a rerun.

    Not usable inside a running event loop (it calls anyio.run per job);
    in-session runs use AgentToolExecutor (jobs mode) instead.
    """

    def __init__(self, model: str = "opus", cwd: str | Path | None = None,
                 max_turns: int = 6, query_fn: Any = None):
        self.model = model
        self.cwd = str(cwd) if cwd is not None else None
        self.max_turns = max_turns
        self._query_fn = query_fn  # test seam; None = claude_agent_sdk.query
        self.failures: list[tuple[str, str]] = []

    def run(self, jobs: list[Job]) -> Iterator[Verdict]:
        for job in jobs:
            yield from self._run_job(job)

    def _run_job(self, job: Job) -> list[Verdict]:
        import anyio

        with _stripped_parent_env():
            # Import inside the stripped env (the PoC strips before import;
            # the SDK may spawn/locate the CLI on first use).
            from claude_agent_sdk import (ClaudeAgentOptions,
                                          ClaudeSDKError, CLINotFoundError)
            query_fn = self._query_fn
            if query_fn is None:
                from claude_agent_sdk import query as query_fn
            options = ClaudeAgentOptions(
                allowed_tools=["Read"], max_turns=self.max_turns,
                model=self.model,
                **({"cwd": self.cwd} if self.cwd else {}))
            try:
                result_msg = anyio.run(self._drain, query_fn, job.prompt,
                                       options)
            except CLINotFoundError:
                raise  # fatal: no claude CLI on this machine
            except ClaudeSDKError as e:
                if _looks_like_auth_failure(str(e)):
                    raise AgentSDKAuthError(_AUTH_HELP) from e
                self.failures.append(
                    (job.job_id, f"{type(e).__name__}: {e}"))
                return []

        if result_msg is None:
            self.failures.append((job.job_id, "no ResultMessage from SDK"))
            return []
        text = getattr(result_msg, "result", "") or ""
        if getattr(result_msg, "is_error", False):
            if _looks_like_auth_failure(text):
                raise AgentSDKAuthError(_AUTH_HELP)
            self.failures.append((job.job_id, f"is_error: {text[:200]}"))
            return []
        fields = _parse_json_object(text)
        if fields is None:
            self.failures.append(
                (job.job_id, f"unparseable result: {text[:200]}"))
            return []
        elapsed_s = (getattr(result_msg, "duration_ms", 0) or 0) / 1000.0
        cost_usd = getattr(result_msg, "total_cost_usd", 0.0) or 0.0
        return [Verdict(claim_id=cid, fields=fields, model=self.model,
                        prompt_version=job.prompt_version,
                        elapsed_s=elapsed_s, cost_usd=cost_usd)
                for cid in job.claim_ids]

    @staticmethod
    async def _drain(query_fn: Any, prompt: str, options: Any) -> Any:
        """Consume the generator to exhaustion; keep the last ResultMessage.
        Never break/return from inside the async-for (SS5.1 segfault)."""
        result = None
        async for msg in query_fn(prompt=prompt, options=options):
            if type(msg).__name__ == "ResultMessage":
                result = msg
        return result
```

Note: `test_options_restrict_tools_and_model` constructs a real `ClaudeAgentOptions` (SDK import inside `_stripped_parent_env` always succeeds — the package is a venv dependency); the fake `query_fn` just receives it.

- [x] **1.4 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_executor.py -v`
Expected: all PASS (prior executor tests too)

- [x] **1.5 Commit**

```bash
git add src/citation_verifier/executor.py tests/test_executor.py
git commit -m "feat: AgentSDKExecutor -- headless SDK transport with env strip, full drain, auth stop (SS5/SS5.1)"
```

### Task 2: Live smoke (gated — ONE job)

No code changes. Validates the real transport through OUR executor (not just the PoC).

- [x] **2.1 PoC auth smoke first** (per the Step 5 brief — don't burn jobs on stale auth):

Run: `venv/Scripts/python.exe tests/poc_agent_sdk_executor.py`
Expected: `-> auth smoke: PASS`
**If FAIL: STOP. Report to the user: "CLI auth is stale — please run `claude login`, then I'll re-run the smoke."** Do not proceed to 2.2.

- [x] **2.2 One real job through AgentSDKExecutor** — temp copy of the frozen Withers corpus, one claim's verdict re-run live via the SDK and compared with the cassette. Run this inline script:

```bash
venv/Scripts/python.exe -c "
import json, shutil, tempfile
from pathlib import Path
from citation_verifier.executor import AgentSDKExecutor, load_verdicts_jsonl
from citation_verifier.proposition_pipeline import run_assess

src = Path('tests/data/assessment_corpora/withers')
tmp = Path(tempfile.mkdtemp()) / 'withers'
shutil.copytree(src, tmp)
jsonl = tmp / 'jobs' / 'assess_results.jsonl'
lines = jsonl.read_text(encoding='utf-8').splitlines()
keep = [ln for ln in lines if json.loads(ln)['claim_id'] != 'withers-01']
jsonl.write_text('\n'.join(keep) + '\n', encoding='utf-8')
ex = AgentSDKExecutor(model='opus', cwd=str(tmp))
stats = run_assess(tmp, executor=ex)
print('stats:', stats)
print('failures:', ex.failures)
new = [v for v in load_verdicts_jsonl(jsonl) if v.claim_id == 'withers-01']
old = [v for v in load_verdicts_jsonl(src / 'jobs' / 'assess_results.jsonl')
       if v.claim_id == 'withers-01']
print('live :', new[-1].fields if new else None)
print('cass :', old[-1].fields)
"
```

Expected: `stats: ... done=29, pending=0`, `failures: []`, live assessment color matches the cassette (`withers-01` recorded Yellow; PoC already showed cross-transport agreement on this row). A color mismatch is *information*, not failure — report it, don't chase it.
**Do NOT run more than this one job live. Full-corpus live runs need user sign-off (Step 5 brief).**

- [x] **2.3** Record the smoke outcome in this plan's Execution notes. Nothing to commit (temp dir).

### Task 3: `extract-v1` template + renderer

**Files:**
- Create: `src/citation_verifier/prompts/extract_v1.md`
- Modify: `src/citation_verifier/proposition_pipeline.py` (after `render_assess_prompt`)
- Test: `tests/test_proposition_pipeline.py`

- [x] **3.1 Write the failing tests** — append to `tests/test_proposition_pipeline.py`:

```python
class TestExtractPrompt:
    def test_template_loads_and_declares_version(self):
        body = pp.load_prompt_template("extract-v1")
        assert "{document_path}" in body
        assert "prompt_version" not in body  # header comments stripped

    def test_render_substitutes_document_path(self):
        prompt = pp.render_extract_prompt("extract-v1", r"C:\briefs\b.pdf")
        assert r"C:\briefs\b.pdf" in prompt
        assert "{document_path}" not in prompt

    def test_render_mentions_contract_columns(self):
        prompt = pp.render_extract_prompt("extract-v1", "doc.pdf")
        for col in ("cited_case", "proposition", "cited_for",
                    "quoted_text", "brief_sentence", "page",
                    "citations_toa", "citations_body"):
            assert col in prompt
```

(`pp` is the module-level `proposition_pipeline` import the suite already uses; match the file's existing import alias.)

- [x] **3.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k ExtractPrompt`
Expected: FAIL — template file missing / `render_extract_prompt` undefined

- [x] **3.3 Create the template** `src/citation_verifier/prompts/extract_v1.md`. Content rules sourced from SKILL.md Phase 1a/1c (exact-citation rule, TOA-both-variants rule, quoted_text/brief_sentence semantics), design §6.3 (`cited_for`), §6.8 (external-tool prohibition — allowed in this NEW template; assess-v1 stays byte-pinned):

```markdown
<!-- prompt_version: extract-v1 -->
<!-- Document-extraction prompt (design SS3 verb 0, SS2 input contract,
     SS6.3 cited_for, SS6.5 TOA/body lists). Sources: the verify-brief
     SKILL.md Phase 1a/1c rules, made deterministic as a versioned
     template. Any edit to this file is a NEW prompt version: copy to
     extract_v2.md, bump the header. Placeholder: {document_path}. -->
You are extracting case-citation claims from a legal document (brief, motion, or opinion) so each claim can be verified against the cited authority.

Read the document at: {document_path}

Use ONLY the Read tool on that file. Do not use web search, web fetch, bash, or any other tool. Do not rely on outside knowledge about any cited case.

Produce three outputs:

1. "claims" -- one entry per proposition-case pair in the document body:
   - "cited_case": the citation EXACTLY as the document cites it, starting with the case name and including the full reporter citation and year (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Append pinpoint pages after the start page. Do NOT abbreviate, omit the reporter, or use short-form case names -- when the document uses a short form (id., supra, name-only), resolve it to the full citation given at first use.
   - "proposition": one sentence, in your words, stating the legal claim the document attributes to this case.
   - "cited_for": when a signal or parenthetical attributes a NARROWER assertion to this specific case than the surrounding sentence argues, state that narrower assertion; otherwise "".
   - "quoted_text": JSON array of the exact strings the document places inside quotation marks for this claim. [] if none.
   - "brief_sentence": the document's sentence(s) containing the citation, reproduced as written -- including quoted language, signal word, and any parenthetical. Normalize whitespace; do not paraphrase. You may trim with [...] keeping the cited-case fragment and immediate context.
   - "page": the page of the document where the claim appears (printed page number if visible, else PDF page), as a string.
   Rules: same case cited for different propositions = separate entries; one proposition supported by several cases = separate entries (one per case); case citations only -- exclude statutes, regulations, constitutional provisions, treatises, and other secondary sources.

2. "citations_toa" -- every case citation listed in the Table of Authorities, one entry per case, base citation without pinpoint, exactly as written. [] if the document has no Table of Authorities.

3. "citations_body" -- every unique case citation appearing in the document body, base citation without pinpoint, exactly as written, deduplicated. If the Table of Authorities and the body give different volumes or page numbers for the same case, include BOTH variants (one in each list, or both in citations_body if the TOA is absent).

Respond with ONLY a JSON object (no markdown fences, no commentary):
{"claims": [{"page": "...", "proposition": "...", "cited_for": "", "cited_case": "...", "quoted_text": [], "brief_sentence": "..."}], "citations_toa": ["..."], "citations_body": ["..."]}
```

- [x] **3.4 Add the renderer** to `proposition_pipeline.py` directly under `render_assess_prompt` (and the version constant next to `DEFAULT_PROMPT_VERSION`):

```python
EXTRACT_PROMPT_VERSION = "extract-v1"
```

```python
def render_extract_prompt(version: str, document_path: str) -> str:
    """Render the extract prompt (design SS3 verb 0). Replace-based like
    render_assess_prompt."""
    return load_prompt_template(version).replace(
        "{document_path}", document_path)
```

- [x] **3.5 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k ExtractPrompt`
Expected: PASS

- [x] **3.6 Commit**

```bash
git add src/citation_verifier/prompts/extract_v1.md src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: versioned extract-v1 prompt template + renderer (SS3 verb 0)"
```

### Task 4: `run_extract` verb

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (new verb, placed before `run_verify` to match the §3 verb order)
- Test: `tests/test_proposition_pipeline.py`

- [x] **4.1 Write the failing tests:**

```python
def _extract_verdict_fields():
    return {
        "claims": [
            {"page": "3",
             "proposition": "Settlement evidence is irrelevant.",
             "cited_for": "",
             "cited_case": "Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",
             "quoted_text": ["consequential fact"],
             "brief_sentence": "See Tompkins v. Cyr, 202 F.3d 770, 787 "
                               "(5th Cir. 2000) (evidence must be relevant "
                               "to a 'consequential fact')."},
            {"page": "5",
             "proposition": "Bad faith is required for spoliation.",
             "cited_for": "adverse-inference standard",
             "cited_case": "King v. Ill. Cent. R.R., 337 F.3d 550 "
                           "(5th Cir. 2003)",
             "quoted_text": [],
             "brief_sentence": "King v. Ill. Cent. R.R., 337 F.3d 550, 556 "
                               "(5th Cir. 2003)."},
        ],
        "citations_toa": ["Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)"],
        "citations_body": [
            "Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",
            "King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)",
        ],
    }


def _extract_workdir(tmp_path, name="matter"):
    wd = tmp_path / name
    wd.mkdir()
    doc = wd / "brief.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")
    return wd, doc


def _extract_cassette(path, fields=None):
    from citation_verifier.executor import Verdict, append_verdict_jsonl
    append_verdict_jsonl(path, Verdict(
        claim_id="extract", fields=fields or _extract_verdict_fields(),
        model="opus", prompt_version="extract-v1"))


class TestRunExtract:
    def test_jobs_mode_writes_jobs_file_and_pends(self, tmp_path):
        wd, doc = _extract_workdir(tmp_path)
        stats = pp.run_extract(wd, doc)
        assert stats.pending is True
        assert stats.claims == 0
        assert not (wd / "claims.csv").exists()
        jobs = json.loads((wd / "jobs" / "extract.json")
                          .read_text(encoding="utf-8"))
        assert len(jobs) == 1
        assert jobs[0]["claim_ids"] == ["extract"]
        assert jobs[0]["prompt_version"] == "extract-v1"
        assert str(doc) in jobs[0]["prompt"]
        assert jobs[0]["files"] == [str(doc)]

    def test_replay_writes_claims_and_citation_lists(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette)
        stats = pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))
        assert stats.pending is False
        assert (stats.claims, stats.toa, stats.body) == (2, 1, 2)
        with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert [r["claim_id"] for r in rows] == ["matter-01", "matter-02"]
        assert rows[0]["cited_case"].startswith("Tompkins v. Cyr")
        assert json.loads(rows[0]["quoted_text"]) == ["consequential fact"]
        assert rows[1]["cited_for"] == "adverse-inference standard"
        toa = (wd / "citations_toa.txt").read_text(encoding="utf-8")
        assert toa.strip().splitlines() == [
            "Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)"]
        body = (wd / "citations_body.txt").read_text(encoding="utf-8")
        assert len(body.strip().splitlines()) == 2
        # the verdict was persisted for resume
        assert (wd / "jobs" / "extract_results.jsonl").exists()

    def test_rerun_ingests_appended_verdict(self, tmp_path):
        """Jobs-mode round trip: pend, agent appends, rerun ingests."""
        wd, doc = _extract_workdir(tmp_path)
        assert pp.run_extract(wd, doc).pending is True
        _extract_cassette(wd / "jobs" / "extract_results.jsonl")
        stats = pp.run_extract(wd, doc)
        assert stats.pending is False
        assert stats.claims == 2
        assert (wd / "claims.csv").exists()

    def test_noop_when_claims_exist(self, tmp_path):
        wd, doc = _extract_workdir(tmp_path)
        (wd / "claims.csv").write_text("claim_id\nx-01\n", encoding="utf-8")
        assert pp.run_extract(wd, doc) is None
        assert (wd / "claims.csv").read_text(
            encoding="utf-8") == "claim_id\nx-01\n"

    def test_malformed_verdict_raises(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette, fields={"claims": "not-a-list"})
        with pytest.raises(ValueError, match="extract verdict"):
            pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))
        assert not (wd / "claims.csv").exists()

    def test_claim_missing_required_field_raises(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        fields = _extract_verdict_fields()
        fields["claims"][1]["cited_case"] = ""
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette, fields=fields)
        with pytest.raises(ValueError, match="cited_case"):
            pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))

    def test_run_json_stamped(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette)
        pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert run["verbs"]["extract"]["prompt_version"] == "extract-v1"
        assert run["verbs"]["extract"]["claims"] == 2
```

(Add `import csv` / `import json` only if the test module lacks them — it already imports both.)

- [x] **4.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunExtract`
Expected: FAIL — `run_extract` undefined

- [x] **4.3 Implement** in `proposition_pipeline.py` (before `run_verify`; schema constant near `_ASSESS_V1_SCHEMA`):

```python
# extract-v1 verdict schema (documentation-shaped; run_extract validates).
_EXTRACT_V1_SCHEMA = {
    "claims": [{"page": "str", "proposition": "str", "cited_for": "str",
                "cited_case": "str", "quoted_text": ["str"],
                "brief_sentence": "str"}],
    "citations_toa": ["str"],
    "citations_body": ["str"],
}

# The single extract job's synthetic resume row id (the verdicts JSONL
# resume key is claim_id + prompt_version; extract has one job per workdir).
_EXTRACT_ROW_ID = "extract"

_CLAIMS_COLUMNS = ["claim_id", "page", "proposition", "cited_for",
                   "cited_case", "quoted_text", "brief_sentence"]


@dataclass
class ExtractStats:
    """Statistics from run_extract."""
    claims: int = 0
    toa: int = 0
    body: int = 0
    pending: bool = False


def run_extract(workdir: Path, document: str | Path, executor: Any = None,
                prompt_version: str = EXTRACT_PROMPT_VERSION,
                force: bool = False) -> ExtractStats | None:
    """Verb 0 (design SS3, LLM, optional front end): document ->
    claims.csv + citations_toa.txt + citations_body.txt.

    One job per workdir through the executor protocol (resume key =
    "extract" + prompt_version in jobs/extract_results.jsonl). Default
    executor is AgentToolExecutor (jobs mode): writes jobs/extract.json
    and pends; dispatch an agent, append the verdict, rerun to ingest.
    Idempotent: no-ops (returns None) when claims.csv already exists --
    prepared-pairs workdirs never re-extract (force=True to redo).
    """
    from .executor import AgentToolExecutor, Job, append_verdict_jsonl, \
        load_verdicts_jsonl

    workdir = Path(workdir)
    document = Path(document)
    if (workdir / "claims.csv").exists() and not force:
        return None

    results_path = workdir / "jobs" / "extract_results.jsonl"
    verdict = None
    if results_path.exists():
        for v in load_verdicts_jsonl(results_path):  # last write wins
            if (v.claim_id == _EXTRACT_ROW_ID
                    and v.prompt_version == prompt_version):
                verdict = v

    if verdict is None:
        job = Job(
            job_id=_EXTRACT_ROW_ID,
            claim_ids=[_EXTRACT_ROW_ID],
            prompt=render_extract_prompt(prompt_version, str(document)),
            prompt_version=prompt_version,
            files=[str(document)],
            schema=_EXTRACT_V1_SCHEMA,
        )
        if executor is None:
            executor = AgentToolExecutor(workdir / "jobs" / "extract.json")
        for v in executor.run([job]):
            append_verdict_jsonl(results_path, v)
            verdict = v

    if verdict is None:
        stats = ExtractStats(pending=True)
        _update_run_json(workdir, "extract", prompt_version=prompt_version,
                         pending=True)
        return stats

    stats = _write_extract_outputs(workdir, verdict.fields)
    _update_run_json(workdir, "extract", prompt_version=prompt_version,
                     claims=stats.claims, toa=stats.toa, body=stats.body)
    return stats


def _write_extract_outputs(workdir: Path,
                           fields: dict[str, Any]) -> ExtractStats:
    """Validate the extract verdict and write claims.csv (pipeline-assigned
    claim_id = <workdir.name>-NN) + the TOA/body citation lists."""
    claims = fields.get("claims")
    if not isinstance(claims, list) or not all(
            isinstance(c, dict) for c in claims):
        raise ValueError(
            "extract verdict: 'claims' must be a list of objects")
    rows = []
    for i, c in enumerate(claims, start=1):
        for required in ("cited_case", "proposition"):
            if not str(c.get(required) or "").strip():
                raise ValueError(
                    f"extract verdict: claim {i} missing {required}")
        quoted = c.get("quoted_text", [])
        rows.append({
            "claim_id": f"{workdir.name}-{i:02d}",
            "page": str(c.get("page") or ""),
            "proposition": str(c.get("proposition") or "").strip(),
            "cited_for": str(c.get("cited_for") or "").strip(),
            "cited_case": str(c.get("cited_case") or "").strip(),
            "quoted_text": (quoted if isinstance(quoted, str)
                            else json_mod.dumps(quoted, ensure_ascii=False)),
            "brief_sentence": str(c.get("brief_sentence") or "").strip(),
        })
    toa = [str(s).strip() for s in fields.get("citations_toa") or []
           if str(s).strip()]
    body = [str(s).strip() for s in fields.get("citations_body") or []
            if str(s).strip()]

    with open(workdir / "claims.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CLAIMS_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (workdir / "citations_toa.txt").write_text(
        "\n".join(toa) + ("\n" if toa else ""), encoding="utf-8")
    (workdir / "citations_body.txt").write_text(
        "\n".join(body) + ("\n" if body else ""), encoding="utf-8")
    return ExtractStats(claims=len(rows), toa=len(toa), body=len(body))
```

(`citations_from_workdir` already unions `citations_toa.txt`/`citations_body.txt` into the verify list — no change needed there.)

- [x] **4.4 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunExtract`
Expected: PASS

- [x] **4.5 Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: extract verb -- document to claims.csv + TOA/body lists via executor protocol (SS3 verb 0)"
```

### Task 5: CLI — `extract` verb, `--document`, `--executor sdk`, `--model`

**Files:**
- Modify: `src/citation_verifier/__main__.py` (`verify_propositions_main`)
- Test: `tests/test_proposition_pipeline.py` (`TestCli`)

- [x] **5.1 Write the failing tests** — append to `TestCli`:

```python
    def test_extract_verb_dispatch(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import ExtractStats
        called = {}

        def fake_extract(wd, document, executor=None,
                         prompt_version="extract-v1", force=False):
            called["wd"] = Path(wd)
            called["doc"] = str(document)
            called["executor"] = executor
            return ExtractStats(claims=2, toa=1, body=2)

        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_extract",
            fake_extract)
        wd = tmp_path / "wd"
        wd.mkdir()
        doc = tmp_path / "brief.pdf"
        doc.write_bytes(b"%PDF")
        rc = verify_propositions_main(
            [str(wd), "extract", "--document", str(doc)])
        assert rc == 0
        assert called["doc"] == str(doc)
        assert called["executor"] is None  # jobs mode default
        assert "[OK] extract" in capsys.readouterr().out

    def test_extract_verb_requires_document(self, tmp_path, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "extract"])
        assert rc == 1
        assert "--document" in capsys.readouterr().err

    def test_extract_pending_message(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import ExtractStats
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_extract",
            lambda *a, **k: ExtractStats(pending=True))
        wd = tmp_path / "wd"
        wd.mkdir()
        doc = tmp_path / "b.pdf"
        doc.write_bytes(b"%PDF")
        rc = verify_propositions_main(
            [str(wd), "extract", "--document", str(doc)])
        assert rc == 0
        assert "PENDING" in capsys.readouterr().out

    def test_assess_executor_sdk_flag(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.executor import AgentSDKExecutor
        from citation_verifier.proposition_pipeline import AssessStats
        captured = {}

        def fake_assess(wd, executor=None, prompt_version="assess-v1"):
            captured["executor"] = executor
            return AssessStats(eligible=1, done=1)

        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_assess",
            fake_assess)
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main(
            [str(wd), "assess", "--executor", "sdk", "--model", "haiku"])
        assert rc == 0
        assert isinstance(captured["executor"], AgentSDKExecutor)
        assert captured["executor"].model == "haiku"

    def test_replay_beats_executor_flag(self, tmp_path, monkeypatch):
        """--replay wins over --executor (offline determinism first)."""
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.executor import (
            RecordedExecutor, append_verdict_jsonl, Verdict)
        from citation_verifier.proposition_pipeline import AssessStats
        captured = {}
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_assess",
            lambda wd, executor=None, prompt_version="assess-v1": (
                captured.update(executor=executor) or AssessStats()))
        cassette = tmp_path / "rec.jsonl"
        append_verdict_jsonl(cassette, Verdict(
            claim_id="x", fields={}, prompt_version="assess-v1"))
        wd = tmp_path / "wd"
        wd.mkdir()
        verify_propositions_main(
            [str(wd), "assess", "--replay", str(cassette),
             "--executor", "sdk"])
        assert isinstance(captured["executor"], RecordedExecutor)
```

- [x] **5.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k "extract_verb or executor_sdk or replay_beats"`
Expected: FAIL — `extract` not in CLI choices / `--executor` unknown

- [x] **5.3 Implement in `verify_propositions_main`:**

Add `"extract"` to the verb `choices` (first position) and extend the help text. Add arguments:

```python
    parser.add_argument(
        "--document",
        help="Source document (brief/motion PDF or text) for the extract "
             "verb / full chain",
    )
    parser.add_argument(
        "--executor", choices=["jobs", "sdk"], default="jobs",
        help="LLM transport for extract/assess: jobs = write jobs file "
             "for Agent-tool subagents (in-session default); sdk = "
             "headless claude-agent-sdk (requires `claude login` "
             "credentials)",
    )
    parser.add_argument(
        "--model", default="opus",
        help="Model for the sdk executor (default opus)",
    )
```

Build the executor once (before the verb blocks, after the workdir check), honoring `--replay` first:

```python
    def _make_executor():
        if args.replay:
            from .executor import RecordedExecutor
            return RecordedExecutor(args.replay)
        if args.executor == "sdk":
            from .executor import AgentSDKExecutor
            return AgentSDKExecutor(model=args.model, cwd=str(workdir))
        return None  # jobs mode (verb default)
```

Add the extract block before the verify block (and gate `full`'s extract on `--document`):

```python
    if args.verb == "extract" or (args.verb == "full" and args.document):
        if not args.document:
            print("Error: extract requires --document <path>",
                  file=sys.stderr)
            return 1
        estats = pp.run_extract(workdir, args.document,
                                executor=_make_executor())
        if estats is None:
            print("[OK] extract: claims.csv already exists "
                  "(use --force to redo)")
        elif estats.pending:
            print("[OK] extract: PENDING -> jobs/extract.json "
                  "(dispatch an agent, append the verdict to "
                  "jobs/extract_results.jsonl, then rerun)")
            return 0  # full stops here until the verdict lands
        else:
            print(f"[OK] extract: {estats.claims} claims, "
                  f"{estats.toa} TOA citations, "
                  f"{estats.body} body citations")
```

Wire `force=args.force` through `run_extract` as well, and replace the existing assess block's replay-only executor construction with `executor=_make_executor()`. Auth errors surface cleanly:

```python
    # wrap the assess/extract calls:
    from .executor import AgentSDKAuthError
    try:
        ...verb dispatch as above...
    except AgentSDKAuthError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
```

(Implementation detail: simplest is a try/except around the whole verb-dispatch region of the function body; keep ASCII output.)

- [x] **5.4 Run the CLI test block + full proposition/executor suites**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py tests/test_executor.py tests/test_brief_pipeline.py -v`
Expected: all PASS

- [x] **5.5 Commit**

```bash
git add src/citation_verifier/__main__.py tests/test_proposition_pipeline.py
git commit -m "feat: extract CLI verb + --document/--executor/--model flags; sdk transport selectable"
```

### Task 6: Docs, regression sweep, push

- [x] **6.1** Full offline suite (everything except the two live-API suites):

Run: `venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_false_negatives.py --ignore=tests/test_cl_api_issues.py`
Expected: >= 700 passed (baseline 700 + this step's new tests), 0 failures. `test_assessment_regression.py` must not regress (Withers 14/19, A/B 56/61).

- [x] **6.2** Update CLAUDE.md: `executor.py` row (add AgentSDKExecutor + AgentSDKAuthError), `proposition_pipeline.py` row (add `run_extract`, extract-v1 template, `--document/--executor/--model` flags, extract jobs-mode flow).

- [x] **6.3** Fill in this plan's "Execution notes" (deviations, smoke outcome) — including the Step 6 constraint below.

- [x] **6.4 Commit + push**

```bash
git add CLAUDE.md docs/plans/2026-06-11-prop-pipeline-step5-sdk-executor-extract-plan.md
git commit -m "docs: Step 5 execution notes + CLAUDE.md (AgentSDKExecutor, extract verb)"
git push origin pipeline-redesign
```

---

## Subsequent steps (§10 map — Step 6 constraints logged per the Step 5 brief)

6. **crosscheck + triage verbs.** Known constraint to solve in Step 6's plan:
   the court-check needs the MATCHED court persisted from verify —
   `verification_results.csv` does not carry it today. That is (a) a schema
   addition to `_write_verification_csv` (new `matched_court` column) and
   (b) a matched-court accessor on `VerificationResult` mirroring
   `matched_case_name` (the caption-accessor bug taught us not to read
   stage-specific `raw_response_summary` keys directly). TOA-vs-body diff
   inputs (`citations_toa.txt` / `citations_body.txt`) now exist via extract.
7. Report lanes (§6.9), SKILL stub, A/B harness re-point.
8. Acceptance runs (§8); retro. The assess-v2 prompt work (multi-opinion
   packing §6.8, external-tool prohibition in the assess template) re-records
   cassettes — extract-v1 already carries the prohibition.

## Execution notes (2026-06-11, all tasks complete)

- **Live smoke green (Task 2):** PoC auth smoke PASS on first try (no
  `claude login` needed — credentials still fresh from the §5.1 refresh).
  One real `withers-01` job through `AgentSDKExecutor` (temp corpus copy,
  cassette line removed): `done=29, pending=0, failures=[]`, live verdict
  **Yellow** vs cassette **Yellow** with materially the same rationale
  (Nix v. Whiteside = perjury-duty case, not conflict-of-interest) —
  cross-transport agreement now demonstrated through the executor itself,
  not just the PoC. Cost/latency of the one job: ~75s wall (opus).
- **One deviation from the plan's code:** `_drain` matches messages by
  `type(msg).__name__.endswith("ResultMessage")` instead of `==` — the
  planned exact match failed the suite because the test doubles are named
  `FakeResultMessage`; suffix duck-typing covers both the SDK class and
  doubles without importing SDK message types. 4 tests caught it (TDD
  working as intended).
- CLI dispatch was split into `_dispatch_proposition_verbs()` so the
  `AgentSDKAuthError` handler wraps every LLM-verb call site with one
  try/except (the plan's "simplest is a try/except around the whole
  verb-dispatch region" note, realized as a function split because the
  verb blocks share early returns).
- Suite: **724 passed offline** (baseline 700 + 24 new), 0 regressions;
  `test_assessment_regression.py` unchanged (Withers 14/19, A/B 56/61).
- extract live validation deliberately deferred to the first real brief
  run (per the Step 5 brief); extract-v1 has no cassettes yet, so its
  first live run will record the inaugural one.

## Self-review notes

- §5.1 hard requirements → Task 1: env strip (`_stripped_parent_env`, tested with restore), full drain (mid-stream ResultMessage test), `allowed_tools=["Read"]` + model from config (options test), 401-stop (`AgentSDKAuthError` raised on first failure, second job never called).
- §3 verb 0 → Tasks 3-4: claims.csv + citations_toa.txt + citations_body.txt; `citations_from_workdir` already consumes the lists (verified — no change needed).
- §2 input contract → `_CLAIMS_COLUMNS` carries all seven fields incl. `cited_for` (§6.3); claim_id pipeline-assigned `<workdir.name>-NN`.
- Resume/idempotence → extract mirrors assess: JSONL resume key, jobs-mode pend + rerun-to-ingest, no-op when claims.csv exists (prepared-pairs safe).
- Type consistency: `ExtractStats(claims, toa, body, pending)` used identically in Tasks 4-5; `run_extract(wd, document, executor, prompt_version, force)` signature matches CLI fake in 5.1.
- One live job only (Task 2), gated on the PoC auth smoke; full-corpus live runs deferred to user sign-off.
