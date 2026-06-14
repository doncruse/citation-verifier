# Proposition-Verifier Step 8: assess-v2 + Acceptance Runs + Retro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Tasks 1-8 are offline; Task 9 is the gated LIVE block — do not start it without the auth smoke passing.**

**Goal:** Land the assess-v2 re-record event (design §10 step 8 + the deferral ledger from the step-4/5/6/7 plans): the two-axis `assess-v2` template with report blocks, external-tool prohibition, `cited_for` (§6.3) and `prescreen_hint` (§6.7) consumption, per-opinion job packing, executor multi-verdict support, v2-aware apply/scoring — then the gated live work: re-record the three corpora, §8 acceptance scoring, the prescreen ON/OFF A/B (decides the §6.7 default), the Withers pincite-flag inspection, and the steps-1-8 retro.

**Architecture:** `assess_v2.md` is a NEW versioned template (assess-v1 stays byte-pinned; its cassettes keep replaying). v2 jobs are packed **one job per opinion** (all claims citing that opinion share one read); the verdict contract becomes a per-claim array `{"verdicts": [{claim_id, support, badge_label, brief_block, opinion_block, finding_analysis}]}`. `AgentSDKExecutor` learns to fan a verdicts-array out as per-claim `Verdict`s (single-object fan-out preserved for v1). `apply-assessments` and `scoring.predict_workdir` route per-verdict: a verdict carrying `support` gets its color from `derive_color(cl_status, support, quote_check_worst)` (+ the §6.4 floor as a guard); v1 verdicts keep the assessment-column path. The report needs **no change**: apply writes the derived color into `assessment`, which `report_lane` row 4 already treats as authoritative. Re-recording **appends** v2 verdicts to the same cassette files (RecordedExecutor keys on claim_id + prompt_version, so one file holds both versions and the v1 baselines stay replayable).

**Tech stack:** stdlib + pytest offline; `claude-agent-sdk` (subscription auth) for Task 9 only.

---

## Decision log (user-ruled 2026-06-12, this session)

| decision | ruling |
|---|---|
| v2 verdict schema | **Two-axis + report blocks**: `{support, badge_label, brief_block, opinion_block, finding_analysis}`; color derived, never output by the agent |
| Job packing | **Per-opinion jobs only** — documented deviation from §6.8's ≤4-5-opinions multi-packing (that economy served interactive subagent dispatch; SDK jobs are cheap to spawn; per-opinion captures the shared-read win with smaller failure blast radius) |
| triage_track Haiku routing | **Deferred past acceptance** — acceptance runs all-Opus (conservative measurement of v2 itself); Haiku fast-track + escalation becomes a post-acceptance cost A/B against the fresh v2 baseline |
| Live scope | **Re-record + acceptance + prescreen A/B** (~3-5 h Opus wall-time, gated batches, smoke first) |

**Source facts (verified this session):**
- `assess_v1.md`: placeholders `{opinion_path}/{cited_case}/{proposition}/{quote_check_worst}`; output `{"assessment", "rationale"}`; no prohibition, no hint, no cited_for. BYTE-PINNED — never edit.
- `run_assess`: one job per claim, `render_assess_prompt`, `_ASSESS_V1_SCHEMA`; resume key = (claim_id, prompt_version); jobs sorted by opinion_file (a packer "slots in without reordering" — step-4 note).
- `AgentSDKExecutor._run_job`: parses ONE JSON object via `_parse_json_object`, fans identical fields to every claim_id in the job. `failures` records per-job problems.
- `run_apply_assessments`: validates `fields["assessment"] in _VALID_COLORS`, floors via `_SEVERITY_RANK`, fills `finding_analysis` only when empty.
- `scoring.predict_workdir`: agent branch reads `v.fields["assessment"]`, applies the floor.
- `tests/test_assessment_corpora.py::test_cassette_covers_agent_assessable_claims` asserts every cassette verdict has `prompt_version == "assess-v1"` and an `assessment` color — must learn dual-version cassettes.
- `tools/ab_test_runner.py` (Step 7): `run_ab_config(config_name, config, corpora, run_root, executor_factory, replay)`; rejects `include_hints` outright; `prompt_version` config key already plumbed.
- verify-brief SKILL Phase 2c (frozen) is the source text for the v2 criteria: support classification, brief/opinion block rules (incl. the empty-opinion_block rules for topic-mismatch and resolves-to-different-case), OCR handling, finding_analysis lead rules, badge-label list.
- Current baselines (offline replay): Withers 14/19 yellows (8 exact), greens 9/12 exact / 2 over-flagged, reds 3/3; A/B payne 23/27 + wainwright 33/34 = 56/61. §8 targets: yellows **≥15/19**, green over-flags **≤2/12**, reds **3/3**, A/B **≥85%** with **no NEW lenient-direction errors** vs the pinned set {payne-03 Red→Yellow, payne-58 Yellow→Green}.
- Withers frozen corpus has exactly **1 pincite flag** (step-6 note) — inspect in Task 9.6.
- Live cost datum: one single-claim opus job ≈ 75s (step-5 smoke). Per-opinion packing roughly halves job counts (multiple claims per opinion in all three corpora).

**Windows:** `venv/Scripts/python.exe`; ASCII-only console output.

---

### Task 1: `assess_v2.md` template + claim-block renderer

**Files:**
- Create: `src/citation_verifier/prompts/assess_v2.md`
- Modify: `src/citation_verifier/proposition_pipeline.py` (constants + renderers near `render_assess_prompt`)
- Test: `tests/test_proposition_pipeline.py`

- [ ] **1.1 Failing tests:**

```python
class TestAssessV2Template:
    def _claim(self, **kw):
        base = {"claim_id": "w-01",
                "cited_case": "Nix v. Whiteside, 475 U.S. 157 (1986)",
                "proposition": "Counsel must not assist perjury.",
                "cited_for": "", "brief_sentence": "", "quoted_text": "[]",
                "quote_check": "[]", "quote_check_worst": "NO_QUOTES",
                "prescreen_hint": ""}
        base.update(kw)
        return base

    def test_template_loads_and_mentions_contract(self):
        import citation_verifier.proposition_pipeline as pp
        body = pp.load_prompt_template("assess-v2")
        for marker in ("{opinion_path}", "{claims_block}", "verdicts",
                       "supported", "partial", "unsupported",
                       "unverifiable", "badge_label", "brief_block",
                       "opinion_block", "finding_analysis"):
            assert marker in body
        assert "Do not use web search" in body  # SS6.8 prohibition

    def test_claim_block_minimal(self):
        import citation_verifier.proposition_pipeline as pp
        block = pp.render_assess_v2_claim_block(self._claim())
        assert "w-01" in block and "Nix v. Whiteside" in block
        assert "NO_QUOTES" in block
        assert "Cited for" not in block        # empty -> omitted
        assert "Preliminary review hint" not in block

    def test_claim_block_full(self):
        import citation_verifier.proposition_pipeline as pp
        block = pp.render_assess_v2_claim_block(self._claim(
            cited_for="the adverse-inference standard",
            brief_sentence="See Nix, 475 U.S. at 160 (standard).",
            quoted_text='["obvious reasons to doubt"]',
            quote_check='[{"quote": "obvious reasons to doubt", '
                        '"result": "CLOSE", "similarity": 0.72, '
                        '"matched_passage": "reasons to doubt the '
                        'veracity"}]',
            quote_check_worst="CLOSE",
            prescreen_hint="Case is about perjury, not conflicts."))
        assert "Cited for" in block and "adverse-inference" in block
        assert "obvious reasons to doubt" in block
        assert "reasons to doubt the veracity" in block  # passage hint
        assert "sim=0.72" in block
        assert "Preliminary review hint" in block

    def test_low_sim_passage_hint_omitted(self):
        import citation_verifier.proposition_pipeline as pp
        block = pp.render_assess_v2_claim_block(self._claim(
            quote_check='[{"quote": "x y", "result": "FABRICATED", '
                        '"similarity": 0.4, "matched_passage": "junk"}]',
            quote_check_worst="FABRICATED"))
        assert "junk" not in block  # below the 0.65 hint floor

    def test_render_assess_v2_prompt(self):
        import citation_verifier.proposition_pipeline as pp
        prompt = pp.render_assess_v2_prompt(
            "assess-v2", "opinions/nix.html",
            [self._claim(), self._claim(claim_id="w-02")])
        assert "opinions/nix.html" in prompt
        assert prompt.count("Claim w-0") == 2
        assert "{claims_block}" not in prompt
```

- [ ] **1.2 Run, verify fail** (`-k AssessV2Template` → template missing / renderer undefined).

- [ ] **1.3 Create `src/citation_verifier/prompts/assess_v2.md`:**

```markdown
<!-- prompt_version: assess-v2 -->
<!-- Two-axis multi-claim assessment prompt (design SS6.9 axes, SS6.3
     cited_for, SS6.7 prescreen hint, SS6.8 prohibition; criteria text
     sourced from the frozen verify-brief SKILL Phase 2c). One job per
     opinion: every claim below cites the same opinion. Any edit to this
     file is a NEW prompt version: copy to assess_v3.md, bump the
     header, re-record. Placeholders: {opinion_path}, {claims_block}. -->
You are reviewing a legal brief's citations against the opinion they cite. Every claim listed below cites the SAME case; assess each claim independently against the opinion text.

Read the opinion file at: {opinion_path}

Use ONLY the Read tool on that file. Do not use web search, web fetch, bash, or any other tool. Do not rely on outside knowledge about this case or any other case.

## Claims to assess

{claims_block}

## Propositional support ("support")

Classify each claim:
- "supported" -- the opinion directly and accurately supports the proposition.
- "partial" -- the opinion touches on the topic but the brief overstates, oversimplifies, or extends the holding beyond what the case decided.
- "unsupported" -- the opinion does not support the proposition. This includes: (a) the case addresses a completely different topic; (b) the case holds the opposite of what the brief claims; (c) the brief attributes a specific principle to the case that does not appear in it.
- "unverifiable" -- the opinion text you were given cannot ground this judgment (truncated, unreadable, or plainly the wrong document).

Be strict about "partial" vs "unsupported": topically related and the holding can reasonably be extended -> "partial"; a different legal issue entirely -> "unsupported", even if the opinion uses some of the same vocabulary. When a claim lists a narrower "Cited for" assertion, judge THAT assertion -- the surrounding sentence is context only.

A "Quote check result" of FABRICATED or CLOSE is deterministic input about quotation accuracy; it does not by itself make the proposition unsupported. Judge support on substance.

## Report blocks (per claim)

**brief_block** -- reproduce the brief's own language for this citation, usually the brief sentence verbatim or lightly trimmed with [...]. Do not paraphrase. Leave empty only if there is truly nothing distinctive to show.

**opinion_block** -- the opinion language that best illuminates the comparison. Populate it ONLY when a direct quote adds contrast-value a prose description cannot:
- Reworded quote: quote the opinion's actual parallel language so the substitution is visible (the matched-passage hint is usually right here).
- Inverted holding: quote the opinion's contrary rule.
- Pinpoint off but topic present: quote the opinion's actual discussion, oriented briefly.
- Pure topic mismatch: LEAVE EMPTY -- no single passage sharpens a wholesale mismatch; the analysis carries it.
- Citation resolves to a different case: LEAVE EMPTY -- quoting the resolved case adds no contrast.
Never invent opinion language: every quote must appear in the opinion file, verbatim, ellipses for elisions. Silently correct obvious OCR artifacts (character-level misreads) when quoting the opinion; reproduce the brief exactly as written in brief_block.

**finding_analysis** -- prose assessment of the gap, for a lawyer audience. For a pure topic mismatch, LEAD with one sentence in the form "X v. Y is a [type] case about [context]. It does not address [the brief's topic]." For a resolves-to-different-case finding, LEAD with the resolution mismatch. For an inverted holding, lead with the inversion. For supported claims, one sentence naming where/how the opinion supports it is enough. Plain prose, complete sentences, no headers or bullets; paragraphs separated by blank lines; no padding.

**badge_label** -- short plain-English issue phrase. Reuse these when they fit; invent only if none fit:
"Supported" / "Overstated -- case partially supports" / "Reworded -- not a verbatim quote" / "Paraphrase presented as direct quote" / "Case on unrelated subject" / "Not supported by cited case" / "Quote not found in opinion" / "Inverts the holding" / "Citation resolves to different case"

## Output

Respond with ONLY a JSON object (no markdown fences, no commentary), one entry per claim above, in the same order:
{"verdicts": [{"claim_id": "...", "support": "supported|partial|unsupported|unverifiable", "badge_label": "...", "brief_block": "...", "opinion_block": "...", "finding_analysis": "..."}]}
```

- [ ] **1.4 Implement the renderers** (constants beside `DEFAULT_PROMPT_VERSION` import/uses):

```python
ASSESS_V2_PROMPT_VERSION = "assess-v2"

# Same floor the report uses for the deterministic passage (SS Phase 2c:
# above ~0.65 the matched passage is usually the passage to quote).
_V2_PASSAGE_HINT_MIN_SIM = 0.65


def render_assess_v2_claim_block(claim: dict) -> str:
    """One claim's entry in the v2 multi-claim prompt. Optional lines
    are omitted when empty so short claims stay short."""
    lines = [f"### Claim {claim['claim_id']}",
             f"Cited case: {claim.get('cited_case', '')}",
             f"Proposition: {claim.get('proposition', '')}"]
    if (claim.get("cited_for") or "").strip():
        lines.append("Cited for (judge this narrower assertion): "
                     + claim["cited_for"].strip())
    if (claim.get("brief_sentence") or "").strip():
        lines.append("Brief sentence: " + claim["brief_sentence"].strip())
    quoted = (claim.get("quoted_text") or "").strip()
    if quoted and quoted != "[]":
        lines.append("Quoted strings: " + quoted)
    lines.append("Quote check result: "
                 + (claim.get("quote_check_worst") or "NO_QUOTES"))
    try:
        checks = json_mod.loads(claim.get("quote_check") or "[]")
    except (json_mod.JSONDecodeError, ValueError):
        checks = []
    for qc in checks:
        sim = qc.get("similarity", 0) if isinstance(qc, dict) else 0
        if (isinstance(qc, dict) and qc.get("matched_passage")
                and sim >= _V2_PASSAGE_HINT_MIN_SIM):
            lines.append(f"Matched passage hint (deterministic, "
                         f"sim={sim:.2f}): {qc['matched_passage']}")
    if (claim.get("prescreen_hint") or "").strip():
        lines.append("Preliminary review hint: "
                     + claim["prescreen_hint"].strip())
    return "\n".join(lines)


def render_assess_v2_prompt(version: str, opinion_path: str,
                            claims: list[dict]) -> str:
    """Render the packed v2 prompt: one opinion, many claims."""
    blocks = "\n\n".join(render_assess_v2_claim_block(c) for c in claims)
    return (load_prompt_template(version)
            .replace("{opinion_path}", opinion_path)
            .replace("{claims_block}", blocks))
```

- [ ] **1.5 Run, verify pass; commit** — `feat: assess-v2 template (two-axis + report blocks) + multi-claim renderer`

### Task 2: Executor multi-verdict (verdicts array) support

**Files:** `src/citation_verifier/executor.py`; `tests/test_executor.py`.

- [ ] **2.1 Failing tests** (append to `TestAgentSDKExecutor`):

```python
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
        assert verdicts[1].fields["finding_analysis"] == "bad"
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

    def test_single_object_fanout_unchanged_for_v1(self):
        from citation_verifier.executor import AgentSDKExecutor
        qf = _fake_query_fn([[FakeResultMessage(
            '{"assessment": "Green", "rationale": "r"}')]])
        ex = AgentSDKExecutor(query_fn=qf)
        (v,) = list(ex.run([_sdk_job("w-01")]))
        assert v.fields["assessment"] == "Green"
```

- [ ] **2.2 Implement** — in `AgentSDKExecutor._run_job`, replace the final fan-out block:

```python
        fields = _parse_json_object(text)
        if fields is None:
            self.failures.append(
                (job.job_id, f"unparseable result: {text[:200]}"))
            return []
        elapsed_s = (getattr(result_msg, "duration_ms", 0) or 0) / 1000.0
        cost_usd = getattr(result_msg, "total_cost_usd", 0.0) or 0.0

        # Packed-job contract (assess-v2+): a per-claim verdicts array.
        # Entries for unknown claim_ids are recorded and dropped; claims
        # the model skipped stay pending (resume re-runs them). Cost is
        # attributed to the first emitted claim only, so summing
        # cost_usd over a cassette stays truthful.
        if isinstance(fields.get("verdicts"), list):
            out = []
            known = set(job.claim_ids)
            for entry in fields["verdicts"]:
                if not isinstance(entry, dict):
                    continue
                cid = entry.get("claim_id", "")
                if cid not in known:
                    self.failures.append(
                        (job.job_id, f"verdict for unknown claim_id "
                                     f"{cid!r} dropped"))
                    continue
                vfields = {k: v for k, v in entry.items()
                           if k != "claim_id"}
                out.append(Verdict(
                    claim_id=cid, fields=vfields, model=self.model,
                    prompt_version=job.prompt_version,
                    elapsed_s=elapsed_s if not out else 0.0,
                    cost_usd=cost_usd if not out else 0.0))
            return out

        return [Verdict(claim_id=cid, fields=fields, model=self.model,
                        prompt_version=job.prompt_version,
                        elapsed_s=elapsed_s, cost_usd=cost_usd)
                for cid in job.claim_ids]
```

(Add `import json` use already present in `tests/test_executor.py`; check the module imports.)

- [ ] **2.3 Run all executor tests; commit** — `feat: per-claim verdicts-array fan-out in AgentSDKExecutor (v2 packed jobs)`

### Task 3: `run_assess` v2 path — per-opinion packing + hint plumbing

**Files:** `src/citation_verifier/proposition_pipeline.py`; `tests/test_proposition_pipeline.py`.

Behavior: `prompt_version == "assess-v1"` keeps the existing per-claim path byte-for-byte (cassette compatibility). Any other version takes the v2 path: group the todo claims by `opinion_file`, one job per opinion (`job_id = f"assess-{<opinion stem>}"`, claim_ids = that opinion's todo claims in claims.csv order), prompt = `render_assess_v2_prompt`. `_ASSESS_V2_SCHEMA` documents the array contract. No multi-opinion packing (decision log). No char-cap splitting: a single opinion cannot be split, and no corpus opinion approaches 200K cleaned chars — assert nothing, document.

- [ ] **3.1 Failing tests:**

```python
class TestRunAssessV2:
    def test_jobs_packed_per_opinion(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        stats = pp.run_assess(wd, prompt_version="assess-v2")
        jobs = json.loads((wd / "jobs" / "assess.json")
                          .read_text(encoding="utf-8"))
        with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
            claims = [c for c in csv.DictReader(f) if pp._assessable(c)]
        opinions = {c["opinion_file"] for c in claims}
        assert len(jobs) == len(opinions)          # one job per opinion
        all_ids = [cid for j in jobs for cid in j["claim_ids"]]
        assert sorted(all_ids) == sorted(c["claim_id"] for c in claims)
        assert all(j["prompt_version"] == "assess-v2" for j in jobs)
        # multi-claim job exists (withers has shared opinions) and its
        # prompt carries every claim's id
        multi = next(j for j in jobs if len(j["claim_ids"]) > 1)
        for cid in multi["claim_ids"]:
            assert f"Claim {cid}" in multi["prompt"]
        assert stats.pending == stats.eligible

    def test_v2_replay_resume_roundtrip(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        from citation_verifier.executor import (
            RecordedExecutor, Verdict, append_verdict_jsonl)
        wd = _copy_withers(tmp_path)
        cassette = tmp_path / "v2.jsonl"
        with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
            claims = [c for c in csv.DictReader(f) if pp._assessable(c)]
        for c in claims:
            append_verdict_jsonl(cassette, Verdict(
                claim_id=c["claim_id"],
                fields={"support": "supported", "badge_label": "Supported",
                        "brief_block": "", "opinion_block": "",
                        "finding_analysis": "fine"},
                model="opus", prompt_version="assess-v2"))
        stats = pp.run_assess(wd, executor=RecordedExecutor(cassette),
                              prompt_version="assess-v2")
        assert stats.done == stats.eligible and stats.pending == 0
        # v1 + v2 lines coexist in the workdir results file
        from citation_verifier.executor import load_verdicts_jsonl
        versions = {v.prompt_version for v in load_verdicts_jsonl(
            wd / "jobs" / "assess_results.jsonl")}
        assert versions == {"assess-v1", "assess-v2"}

    def test_v1_path_unchanged(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        pp.run_assess(wd)  # default assess-v1
        jobs = json.loads((wd / "jobs" / "assess.json")
                          .read_text(encoding="utf-8"))
        assert all(len(j["claim_ids"]) == 1 for j in jobs)
```

- [ ] **3.2 Implement** in `run_assess` — replace the job-building block:

```python
    todo.sort(key=lambda c: c.get("opinion_file", ""))

    if prompt_version == DEFAULT_PROMPT_VERSION:
        jobs = [...existing v1 per-claim Job list, unchanged...]
    else:
        # v2+: one packed job per opinion (decision log: per-opinion
        # only -- documented deviation from SS6.8 multi-opinion caps).
        by_opinion: dict[str, list[dict]] = {}
        for c in todo:
            by_opinion.setdefault(c["opinion_file"], []).append(c)
        jobs = [Job(
            job_id="assess-" + Path(opinion).stem[:60],
            claim_ids=[c["claim_id"] for c in group],
            prompt=render_assess_v2_prompt(
                prompt_version, str(workdir / opinion), group),
            prompt_version=prompt_version,
            files=[opinion],
            schema=_ASSESS_V2_SCHEMA,
        ) for opinion, group in by_opinion.items()]
```

with the schema constant near `_ASSESS_V1_SCHEMA`:

```python
_ASSESS_V2_SCHEMA = {
    "verdicts": [{"claim_id": "str",
                  "support": "supported|partial|unsupported|unverifiable",
                  "badge_label": "str", "brief_block": "str",
                  "opinion_block": "str", "finding_analysis": "str"}],
}
```

- [ ] **3.3 Run, verify pass (incl. the existing TestRunAssess v1 suite); commit** — `feat: run_assess v2 path -- per-opinion packed jobs + hint-bearing claim blocks`

### Task 4: `apply-assessments` v2 routing

**Files:** `src/citation_verifier/proposition_pipeline.py`; `tests/test_proposition_pipeline.py`.

- [ ] **4.1 Failing tests:**

```python
_V2_SUPPORTS = ("supported", "partial", "unsupported", "unverifiable")


class TestApplyAssessmentsV2:
    def _wd_with_v2(self, tmp_path, support, qcw="NO_QUOTES",
                    cl_status="VERIFIED", floor=""):
        from citation_verifier.executor import Verdict, append_verdict_jsonl
        wd = _report_workdir(tmp_path, [_report_row(
            "r-01", cl_status=cl_status, opinion_file="opinions/a.html",
            quote_check_worst=qcw, quote_floor=floor)])
        (wd / "jobs").mkdir()
        append_verdict_jsonl(
            wd / "jobs" / "assess_results.jsonl",
            Verdict(claim_id="r-01",
                    fields={"support": support, "badge_label": "B",
                            "brief_block": "bb", "opinion_block": "ob",
                            "finding_analysis": "fa"},
                    model="opus", prompt_version="assess-v2"))
        return wd

    @pytest.mark.parametrize("support,qcw,color", [
        ("supported", "NO_QUOTES", "Green"),
        ("supported", "CLOSE", "Yellow"),     # derive_color quote axis
        ("partial", "VERBATIM", "Yellow"),
        ("unsupported", "VERBATIM", "Red"),
        ("unverifiable", "NO_QUOTES", "Gray"),
    ])
    def test_color_derived_from_axes(self, tmp_path, support, qcw, color):
        import citation_verifier.proposition_pipeline as pp
        wd = self._wd_with_v2(tmp_path, support, qcw=qcw)
        stats = pp.run_apply_assessments(wd, prompt_version="assess-v2")
        assert stats.applied == 1
        (row,) = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert row["assessment"] == color
        assert row["support"] == support
        assert row["badge_label"] == "B"
        assert row["brief_block"] == "bb"
        assert row["opinion_block"] == "ob"
        assert row["finding_analysis"] == "fa"
        assert row["assessed_by"] == "opus/assess-v2"

    def test_quote_floor_still_guards(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = self._wd_with_v2(tmp_path, "supported", qcw="FABRICATED",
                              floor="Yellow")
        pp.run_apply_assessments(wd, prompt_version="assess-v2")
        (row,) = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert row["assessment"] == "Yellow"

    def test_invalid_support_rejected(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = self._wd_with_v2(tmp_path, "kinda")
        stats = pp.run_apply_assessments(wd, prompt_version="assess-v2")
        assert stats.invalid == 1 and stats.applied == 0
```

(`Gray` from derive_color is written into `assessment` as-is; `report_lane` row 4 maps non-Green/Red strings to Yellow framing — acceptable: `unverifiable` agent verdicts are rare and surface as Yellow findings with the analysis explaining. Documented here, revisit if it ever fires in practice.)

- [ ] **4.2 Implement** in `run_apply_assessments` — replace the verdict-validation block:

```python
        v = verdicts.get(c["claim_id"])
        if v is None:
            stats.missing += 1
            continue
        if "support" in v.fields:                      # v2+ verdict
            from .scoring import derive_color
            support = v.fields.get("support")
            if support not in ("supported", "partial", "unsupported",
                               "unverifiable"):
                stats.invalid += 1
                stats.invalid_claims.append(c["claim_id"])
                continue
            color = derive_color(c.get("cl_status", ""), support,
                                 c.get("quote_check_worst", ""))
            c["support"] = support
            c["badge_label"] = v.fields.get("badge_label", "")
            c["brief_block"] = v.fields.get("brief_block", "")
            c["opinion_block"] = v.fields.get("opinion_block", "")
            # v2 owns the analysis (richer than v1's rationale)
            c["finding_analysis"] = v.fields.get("finding_analysis", "")
        else:                                          # v1 verdict
            color = v.fields.get("assessment")
            if color not in _VALID_COLORS:
                stats.invalid += 1
                stats.invalid_claims.append(c["claim_id"])
                continue
            c["support"] = v.fields.get("support", "")
            if not c.get("finding_analysis"):
                c["finding_analysis"] = v.fields.get("rationale", "")
        floor = c.get("quote_floor", "")
        if (floor in _SEVERITY_RANK and color in _SEVERITY_RANK
                and _SEVERITY_RANK[color] < _SEVERITY_RANK[floor]):
            color = floor
        c["assessment"] = color
        c["assessed_by"] = f"{v.model}/{v.prompt_version}"
        stats.applied += 1
```

and extend the appended-columns list with `badge_label`, `brief_block`, `opinion_block`.

- [ ] **4.3 Run (incl. existing v1 apply tests + the apply/scoring agreement test); commit** — `feat: apply-assessments routes v2 verdicts through derive_color; writes report blocks`

### Task 5: scoring v2 + corpora structural-test update

**Files:** `src/citation_verifier/scoring.py`; `tests/test_scoring.py`; `tests/test_assessment_corpora.py`.

- [ ] **5.1 Failing tests** (`tests/test_scoring.py`):

```python
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
```

In `tests/test_assessment_corpora.py`, change the cassette invariant to accept both versions:

```python
    def test_cassette_covers_agent_assessable_claims(self, name):
        verdicts = load_verdicts_jsonl(
            CORPORA / name / "jobs" / "assess_results.jsonl")
        assert all(v.prompt_version in ("assess-v1", "assess-v2")
                   for v in verdicts)
        for v in verdicts:
            if v.prompt_version == "assess-v1":
                assert v.fields.get("assessment") in (
                    "Green", "Yellow", "Red")
            else:
                assert v.fields.get("support") in (
                    "supported", "partial", "unsupported",
                    "unverifiable")
        recorded = {v.claim_id for v in verdicts
                    if v.prompt_version == "assess-v1"}
        for c in load_claims(name):
            needs_agent = (bool(c.get("opinion_file"))
                           and c.get("cl_status") != "WRONG_CASE")
            if needs_agent:
                assert c["claim_id"] in recorded, c["claim_id"]
```

(v1 coverage stays the hard invariant; v2 coverage gets its own assertion in Task 9.4 once recorded.)

- [ ] **5.2 Implement** in `predict_workdir`'s agent branch — claims metadata lookup + per-verdict routing:

```python
    if agent_claims:
        meta = {c["claim_id"]: c for c in agent_claims}
        jobs = [...unchanged...]
        for v in executor.run(jobs):
            c = meta.get(v.claim_id, {})
            if "support" in v.fields:
                color = derive_color(c.get("cl_status", ""),
                                     v.fields["support"],
                                     c.get("quote_check_worst", ""))
                rationale = v.fields.get("finding_analysis", "")
            else:
                color = v.fields["assessment"]
                rationale = v.fields.get("rationale", "")
            floor = (c.get("quote_floor") or "")
            floored = bool(
                floor in _SEVERITY_RANK and color in _SEVERITY_RANK
                and _SEVERITY_RANK[color] < _SEVERITY_RANK[floor])
            preds.append(ClaimPrediction(
                v.claim_id, floor if floored else color, "agent",
                rationale, floored=floored))
```

(`floors` dict replaced by the `meta` dict; remove the old `floors` construction.)

- [ ] **5.3 Run scoring + corpora + regression suites (all must stay green — corpora still v1-only); commit** — `feat: scoring routes v2 support verdicts through derive_color; cassettes may hold both versions`

### Task 6: A/B harness — v2 + prescreen-hint configs

**Files:** `tools/ab_test_runner.py`; `tests/ab_test_configs.json`; `tests/test_ab_runner.py`.

- [ ] **6.1 Failing tests:**

```python
class TestHintConfigs:
    def test_hints_rejected_only_for_v1(self, tmp_path):
        with pytest.raises(ValueError, match="assess-v2"):
            ab.run_ab_config("h", {"include_hints": True},
                             corpora=("payne",), run_root=tmp_path)

    def test_hints_config_runs_prescreen_then_assess(self, tmp_path):
        from citation_verifier.executor import (
            RecordedExecutor, Verdict, append_verdict_jsonl)
        import csv as csv_mod
        # synthetic recorded executors: prescreen hints + v2 verdicts
        pre = tmp_path / "pre.jsonl"
        v2 = tmp_path / "v2.jsonl"
        src_claims = list(csv_mod.DictReader(
            (ab.CORPORA / "payne" / "claims.csv").open(encoding="utf-8")))
        for c in src_claims:
            if c.get("opinion_file"):
                append_verdict_jsonl(pre, Verdict(
                    claim_id=c["claim_id"], fields={"hint": "H"},
                    model="haiku", prompt_version="prescreen-v1"))
                append_verdict_jsonl(v2, Verdict(
                    claim_id=c["claim_id"],
                    fields={"support": "supported", "badge_label": "S",
                            "brief_block": "", "opinion_block": "",
                            "finding_analysis": "f"},
                    model="opus", prompt_version="assess-v2"))

        def factory(config, wd, phase):
            return RecordedExecutor(pre if phase == "prescreen" else v2)

        scores = ab.run_ab_config(
            "v2h", {"include_hints": True, "prompt_version": "assess-v2"},
            corpora=("payne",), run_root=tmp_path / "run",
            executor_factory=factory)
        rows = list(csv_mod.DictReader(
            (tmp_path / "run" / "payne" / "claims.csv")
            .open(encoding="utf-8")))
        hinted = [r for r in rows if r.get("prescreen_hint")]
        assert hinted  # big-opinion claims got hints before assess
        assert scores["payne"].total == 27
```

(Note `executor_factory` grows a third `phase` argument — `"prescreen" | "assess"` — update the Task-6-of-step-7 test's factory signature accordingly; that test's factory becomes `lambda config, wd, phase: ...`.)

- [ ] **6.2 Implement** in `run_ab_config`: the hint-rejection check becomes v1-only, and the live branch runs triage first for hint configs:

```python
    if config.get("include_hints") and \
            config.get("prompt_version", "assess-v1") == "assess-v1":
        raise ValueError(
            "include_hints needs a hint-capable prompt: set "
            "prompt_version to assess-v2 (v1 is byte-pinned, no hint)")
    ...
            executor = (executor_factory or make_executor)(
                config, wd, "assess")
            if config.get("include_hints"):
                from citation_verifier.proposition_pipeline import run_triage
                pre_ex = (executor_factory or make_executor)(
                    config | {"model": config.get("prescreen_model",
                                                  "haiku")},
                    wd, "prescreen")
                tstats = run_triage(wd, prescreen=True, executor=pre_ex)
                if tstats.prescreen_pending:
                    print(f"  WARNING {name}: "
                          f"{tstats.prescreen_pending} prescreen hints "
                          f"pending -- assess runs without them")
            stats = run_assess(wd, executor=executor,
                               prompt_version=prompt_version)
```

and `make_executor(config, workdir, phase="assess")` gains the phase param (ignored — model comes from config; prescreen passes the overridden config).

Add the two new configs to `tests/ab_test_configs.json` (existing four entries untouched):

```json
    "opus-v2": {
      "description": "assess-v2 two-axis + blocks, per-opinion packed, no hints",
      "model": "opus",
      "prompt_version": "assess-v2",
      "include_hints": false
    },
    "opus-v2-hints": {
      "description": "assess-v2 with Haiku prescreen hints (SS6.7 A/B arm)",
      "model": "opus",
      "prompt_version": "assess-v2",
      "include_hints": true,
      "prescreen_model": "haiku"
    }
```

- [ ] **6.3 Run `tests/test_ab_runner.py` (old + new); commit** — `feat: A/B harness v2 + prescreen-hint configs (prescreen phase before assess)`

### Task 7: Withers measurement re-point note + runner coverage

**Files:** `tests/measure_withers_assessment.py` (docstring only); `tests/test_ab_runner.py`.

- [ ] **7.1** Add to the measurement script's docstring (below the Usage block): `"SUPERSEDED for reruns (2026-06-12): live Withers re-runs now go through tools/ab_test_runner.py --corpus withers --config <cfg>; offline scoring through citation_verifier.scoring. This script remains as the original methodology record; its claude -p phase is not maintained."` No code change (its `claude -p` path stays as history).
- [ ] **7.2** Runner coverage test:

```python
class TestWithersCorpusViaRunner:
    def test_replay_scores_exhibit_scale(self, capsys):
        scores = ab.run_ab_config("baseline", {}, corpora=("withers",),
                                  replay=True)
        s = scores["withers"]
        assert (s.yellows_caught, s.yellows_total) == (14, 19)
        assert (s.reds_caught, s.reds_total) == (3, 3)
        assert "yellows caught 14/19" in capsys.readouterr().out
```

- [ ] **7.3 Run; commit** — `test: withers corpus runnable through the A/B harness; measurement script superseded note`

### Task 8: SKILL stub envelope update for packed jobs + docs

**Files:** `.claude/skills/proposition-verifier/SKILL.md`; `CLAUDE.md`.

- [ ] **8.1** In the SKILL's step-5 appendix, replace the envelope paragraph with:

```markdown
   > After producing your JSON object, append it to `<workdir>/jobs/<phase>_results.jsonl` as ONE line PER claim. For single-claim jobs the line is:
   > `{"claim_id": "<the job's claim_ids[0]>", "prompt_version": "<the job's prompt_version>", "model": "<your model>", "fields": <your JSON object>}`
   > For packed assess jobs (multiple claim_ids), write one line per entry of your `verdicts` array, with `fields` = that entry minus its `claim_id`.
   > Use only the Read tool on files in the workdir, plus those appends. No other tools.
```

- [ ] **8.2** CLAUDE.md: `proposition_pipeline.py` row gains assess-v2 (per-opinion packed jobs, verdicts-array contract, `render_assess_v2_prompt`, hint/cited_for consumption, apply routes v2 through `derive_color` — `support` column now filled); `executor.py` row gains the verdicts-array fan-out; tools row gains the v2/hints configs. Mark the prescreen default decision as pending Task 9.5.
- [ ] **8.3** Full offline suite (same invocation as Step 7's 7.3) — all green. Commit + push — `docs: Step 8 offline work complete; SKILL packed-job envelope`

### Task 9: LIVE block (gated — auth smoke first, batches, stop points)

**No code beyond baselines/docs. Every sub-task reports results before the next runs.**

- [ ] **9.1 Auth smoke:** `venv/Scripts/python.exe tests/poc_agent_sdk_executor.py` → expect `-> auth smoke: PASS`. **If FAIL: STOP and ask the user to run `claude login`.**
- [ ] **9.2 One-job v2 smoke:** temp copy of the withers corpus, run `run_assess(tmp, executor=AgentSDKExecutor(model='opus', cwd=tmp), prompt_version='assess-v2')` limited to ONE opinion (delete all but one opinion's todo rows in the copy, or pre-seed the others from a synthetic cassette). Manually inspect the packed verdict: per-claim array parsed, support sensible, blocks non-degenerate. **STOP and show the user if the output looks off — template fixes before re-record are cheap; after, they're another re-record.**
- [ ] **9.3 Re-record (per corpus, withers → payne → wainwright):** copy frozen corpus to a run dir, run assess-v2 live (per-opinion jobs, all-Opus), verify `failures == []` and `pending == 0` (rerun the verb for stragglers — resume-keyed), then **append only the assess-v2 lines** to the frozen corpus's `jobs/assess_results.jsonl`. Run the structural suite after each corpus. Estimated ~35-45 packed jobs total across the three corpora.
- [ ] **9.4 Acceptance scoring:** `venv/Scripts/python.exe -m citation_verifier.scoring tests/data/assessment_corpora/{withers,payne,wainwright} --prompt-version assess-v2` plus `tools/ab_test_runner.py --replay` per version. Check §8: withers yellows ≥15/19, green over-flags ≤2/12, reds 3/3; A/B ≥85% (52/61) with no NEW lenient-direction misses beyond the pinned v1 set. Add `TestAssessV2Baselines` to `tests/test_assessment_regression.py` pinning the measured v2 numbers (v1 classes stay). Extend the corpora structural test with v2 coverage. **If targets miss: STOP and report — prompt tuning is a v3 decision, not an ad-hoc edit.**
- [ ] **9.5 Prescreen A/B:** `tools/ab_test_runner.py --config opus-v2 opus-v2-hints --corpus payne wainwright withers` (auto-compares). Decide the §6.7 default from accuracy (lenient-direction errors weighted worst) and cost; if ON wins, flip the triage default (`--prescreen` semantics + CLAUDE.md + design-decision note); else document OFF as final.
- [ ] **9.6 Withers pincite-flag inspection (offline):** find the one `pincite_flag` row in the frozen corpus, read the flagged pinpoint against the opinion text, classify genuine-catch vs star-pagination artifact, record in the corpus README + retro.
- [ ] **9.7 Baselines + retro:** update `tests/data/assessment_corpora/README.md` (v2 rows/cassette table), CLAUDE.md baselines; write `docs/retrospectives/2026-06-12-pipeline-redesign-steps1-8.md` (what the redesign set out to fix from §1, per-step outcomes, acceptance numbers v1 vs v2, open items: Haiku routing A/B, assess honoring triage_track, claims.csv consumer contract + export from TODO, web-app front end §6.10). Commit + push everything.

---

## Self-review notes

- Deferral ledger coverage: prescreen_hint consumption (Task 1/3/6 + 9.5), external-tool prohibition in the assess template (Task 1), §6.8 packing (Task 3, per the user-ruled per-opinion deviation), prescreen default decision (9.5), Withers pincite flag (9.6), §8 acceptance + retro (9.4/9.7). Deliberately NOT here (user-ruled): triage_track Haiku routing — logged in the retro's open items.
- §6.3: v2 claim block carries `cited_for` with the judge-this instruction; §6.9: agent outputs `support` only, color always derived; the report needs no change because apply writes the derived color into `assessment` (report_lane row 4).
- Cassette policy: v1 lines never touched; v2 appended; structural test split per version; regression pins both baselines.
- Type consistency: verdicts-array entries minus `claim_id` become `Verdict.fields`; apply/scoring both branch on `"support" in fields`; `executor_factory(config, wd, phase)` is the one signature change (step-7 test updated in Task 6).
- Live gates: 9.1 auth (user action if stale), 9.2 quality eyeball before the expensive batch, 9.4 stop-on-miss, 9.5 decision recorded.

## Execution notes (2026-06-12; Tasks 1-8 + 9.1-9.4 + 9.6 complete; 9.5 in flight)

- **Offline Tasks 1-8:** executed as planned, all TDD-first; one test
  surprise — the v2 replay/resume and v1-path tests passed before the
  packing implementation landed (per-claim jobs already satisfied them);
  only the packing assertion drove code. Suite 801 → 812 over the step.
- **9.1 auth smoke:** PASS first try. **9.2 one-job packed smoke** (Am.
  Auto pair): clean per-claim array, and the v2 verdicts presaged the
  acceptance result — withers-12 ("not mechanically catchable" per the
  step-3 notes) judged partial from the brief-sentence/cited_for context.
- **9.3 re-record:** 90/90 verdicts (29+27+34), all-Opus, per-opinion
  packed, appended to the frozen cassettes (dual-version files). First
  attempt crashed on a transient SDK plain-Exception ("Claude Code
  returned an error result") that bypassed the ClaudeSDKError handler —
  executor hardened (catch-all per-job failure + auth-marker escalation,
  pinned tests); second run completed with 3 transient wainwright
  failures that the hardening absorbed and one resume pass finished.
- **9.4 scorecard:** yellows **16/19** (11 exact; ≥15 PASS), reds 3/3
  PASS, A/B **55/61 = 90%** PASS (payne 23/27, wainwright 32/34),
  lenient set shrank to {payne-03} PASS — green over-flags **4/12** vs
  ≤2: stopped per plan, adjudicated row-by-row with the user, who agreed
  with the agent on all four (see TestAssessV2Baselines docstring + the
  retro). **v2 acceptance APPROVED.** Third live finding fixed en route:
  derive_color double-floored the §6.4 noise band (withers-21) — the
  quote axis passed to derive_color is now the floor-effective verdict.
- **9.6 pincite flag:** FALSE POSITIVE — Missouri v. Jenkins n.10 exists
  as `<footnotemark>10</footnotemark>`; the tag-strip hid it from the
  footnote-existence check. `_read_clean_opinion` now rewrites
  footnotemarks to `n.N` pre-strip; Withers crosscheck = 0 pincite flags.
- **First real report rendered** (`matters/withers-v2-demo/report.html`):
  21 findings / 10 verified / 3 unable / 0 check-cite through the full
  v2 chain; committed as a demo workdir.
- **9.5 prescreen A/B — COMPLETE 2026-06-13. Verdict: hints HURT; default
  OFF (now evidence-backed, was provisional).** Ran opus-v2-hints live over
  all three corpora; compared per-claim against the frozen-v2 (no-hints)
  baseline. Raw score rows preserved in `scratch/ab_runs/` (the gitignored
  originals live in tests/data/results/).
  - **8 rows moved** (no-hints → hints): 2 better (payne-03 Yellow→Red ✓,
    payne-16 Yellow→Green ✓), 4 worse (payne-02 Red→Gray, payne-58
    Yellow→Green LENIENT, withers-12 Yellow→Green LENIENT, withers-44
    Yellow→Green LENIENT), 2 lateral (both caught: withers-13 Yellow→Red,
    withers-30 Yellow→Red — the latter a *more severe* over-flag).
  - **A/B (payne+wainwright): 55/61 both** — hints fixed two and broke two,
    a wash on count.
  - **Withers yellows: 16/19 → 14/19** — hints lost withers-12 and
    withers-44, *both* in the lenient direction (Yellow→Green), the §6.7-
    worst failure. Total lenient-direction errors rose 1 → 3.
  - **Mechanism:** the Haiku 2-4 sentence topline compresses away the
    overstatement nuance the full Opus read catches; on -12/-44 a confident
    "case is about X" nudged the assessor to Green.
  - **Decision recorded** here + retro prescreen section + CLAUDE.md +
    `proposition_pipeline.PRESCREEN_MIN_CHARS` comment + `run_triage`
    docstring. Triage default was already OFF — **no flip needed**.
    Prescreen stays wired (revisit only with a redesigned hint).
  **STEP 8 COMPLETE.**
