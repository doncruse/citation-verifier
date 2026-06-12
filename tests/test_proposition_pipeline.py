"""Tests for proposition_pipeline (pipeline redesign SS10 step 2).

Covers what is NEW relative to brief_pipeline: the matched_case_name
accessor (SS11 bug 1 source fix), slug-token opinion linkage, verify/merge
verbs, and the brief_pipeline alias. Legacy behavior stays covered by
test_brief_pipeline.py through the alias.
"""
import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
)


def _entry(stage, summary, verdict=StageVerdict.resolved):
    return ResolutionPathEntry(
        stage=stage, query={}, raw_response_summary=summary,
        verdict=verdict, confidence=1.0, notes="", elapsed_ms=0,
    )


def _result(path_entries):
    return VerificationResult(
        citation_as_written="Test v. Case, 1 U.S. 1 (1800)",
        parsed_citation=None,
        status=Status.VERIFIED,
        final_ids=FinalIds(
            cluster_id=None, opinion_id=None, docket_id=None,
            recap_document_id=None, absolute_url=None, text_source=None,
        ),
        resolution_path=path_entries,
        warnings=[],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )


class TestMatchedCaseNameAccessor:
    def test_citation_lookup_key(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Nix v. Whiteside"})])
        assert r.matched_case_name == "Nix v. Whiteside"

    def test_search_stage_key(self):
        r = _result([_entry(StageName.opinion_search,
                            {"best_case_name": "Donovan v. Carls Drug Co."})])
        assert r.matched_case_name == "Donovan v. Carls Drug Co."

    def test_caption_investigation_key_wins_as_latest(self):
        r = _result([
            _entry(StageName.citation_lookup,
                   {"matched_case_name": "Brief's Name"}),
            _entry(StageName.caption_investigation,
                   {"cl_case_name": "CL's Actual Caption"}),
        ])
        assert r.matched_case_name == "CL's Actual Caption"

    def test_sibling_swap_case_name_key(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Original",
                             "case_name": "Swapped Sibling"})])
        assert r.matched_case_name == "Swapped Sibling"

    def test_walks_back_past_summaryless_entries(self):
        r = _result([
            _entry(StageName.citation_lookup,
                   {"matched_case_name": "Found Here"}),
            _entry(StageName.opinion_search, {"candidate_count": 0},
                   verdict=StageVerdict.no_match),
        ])
        assert r.matched_case_name == "Found Here"

    def test_empty_path_returns_empty(self):
        assert _result([]).matched_case_name == ""


class TestBriefPipelineAlias:
    def test_module_identity(self):
        import citation_verifier.brief_pipeline as bp
        import citation_verifier.proposition_pipeline as pp
        assert bp is pp

    def test_patch_through_alias_reaches_real_globals(self):
        import citation_verifier.proposition_pipeline as pp
        with patch("citation_verifier.brief_pipeline.CitationVerifier") as m:
            assert pp.CitationVerifier is m


class TestMatchedNameInCsv:
    def test_write_verification_csv_uses_accessor(self, tmp_path):
        """SS11 bug 1 regression: batch-path results carry the caption under
        matched_case_name, which the old writer (reading only case_name)
        dropped -- matched_name came out blank in verification_results.csv."""
        from citation_verifier.proposition_pipeline import (
            _write_verification_csv)
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Nix v. Whiteside",
                             "clusters_returned": 1})])
        _write_verification_csv(tmp_path, ["Nix v. Whiteside, 475 U.S. 157"],
                                [r])
        rows = list(csv.DictReader(
            (tmp_path / "verification_results.csv").open(encoding="utf-8")))
        assert rows[0]["matched_name"] == "Nix v. Whiteside"


def _mk_merge_workdir(tmp_path, opinion_name, vr_row):
    wd = tmp_path / "wd"
    (wd / "opinions").mkdir(parents=True)
    (wd / "opinions" / opinion_name).write_text("text", encoding="utf-8")
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "claim_id", "page", "proposition", "cited_for", "cited_case",
            "quoted_text", "brief_sentence"])
        w.writeheader()
        w.writerow({"claim_id": "t-01", "page": "1", "proposition": "P",
                    "cited_for": "", "cited_case": vr_row["citation"],
                    "quoted_text": "[]", "brief_sentence": ""})
    with (wd / "verification_results.csv").open("w", newline="",
                                                encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "citation", "status", "confidence", "cl_url", "matched_name",
            "diagnostics_cat", "diagnostics_msg", "syllabus"])
        w.writeheader()
        w.writerow(vr_row)
    return wd


_MIDWEST_VR = {
    "citation": "Midwest Employers Cas. Co. v. Williams, "
                "161 F.3d 877 (5th Cir. 1998)",
    "status": "VERIFIED", "confidence": "1.00", "cl_url": "",
    "matched_name": "", "diagnostics_cat": "", "diagnostics_msg": "",
    "syllabus": "",
}


class TestSlugTokenLinkage:
    # The motivating fixture from the 2026-06-11 measurement run: CL's
    # caption is far longer than the cited name, so name-containment failed.
    OPINION = ("MIDWEST_EMPLOYERS_CASUALTY_CO_Plaintiff-Appellant-Appellee"
               "_v_Jo_Ann_WILLIAMS_Defendant-Appellee-Appellant.html")

    def test_links_via_cl_url_slug_when_matched_name_blank(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        vr = dict(_MIDWEST_VR)
        vr["cl_url"] = ("https://www.courtlistener.com/opinion/758697/"
                        "midwest-employers-casualty-co-v-jo-ann-williams/")
        wd = _mk_merge_workdir(tmp_path, self.OPINION, vr)
        stats = merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == f"opinions/{self.OPINION}"
        assert stats.opinion_count == 1

    def test_links_via_matched_name_tokens(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        vr = dict(_MIDWEST_VR)
        vr["matched_name"] = "Midwest Employers Casualty Co. v. Williams"
        wd = _mk_merge_workdir(tmp_path, self.OPINION, vr)
        merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == f"opinions/{self.OPINION}"

    def test_no_link_below_threshold(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        wd = _mk_merge_workdir(tmp_path, "Completely_Unrelated_v_Case.html",
                               dict(_MIDWEST_VR))
        merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == ""

    def test_claim_id_and_cited_for_survive_merge(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        vr = dict(_MIDWEST_VR)
        vr["matched_name"] = "Midwest Employers Casualty Co. v. Williams"
        wd = _mk_merge_workdir(tmp_path, self.OPINION, vr)
        merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["claim_id"] == "t-01"
        assert "cited_for" in claims[0]


class TestWithersCorpusLinkage:
    """The committed frozen corpus IS the bug's regression data: its
    verification_results.csv has blank matched_name on batch rows, and its
    claims.csv carries the slug-workaround links the new merge must
    reproduce from scratch."""

    def test_reproduces_frozen_corpus_links(self, tmp_path):
        import shutil
        from citation_verifier.proposition_pipeline import merge_claims
        src = Path(__file__).parent / "data" / "assessment_corpora" / "withers"
        wd = tmp_path / "withers"
        shutil.copytree(src, wd)
        expected = {c["claim_id"]: c["opinion_file"] for c in
                    csv.DictReader((src / "claims.csv").open(encoding="utf-8"))}
        merge_claims(wd)
        got = {c["claim_id"]: c["opinion_file"] for c in
               csv.DictReader((wd / "claims.csv").open(encoding="utf-8"))}
        assert got == expected


def _claims_only_workdir(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "claim_id", "page", "proposition", "cited_for",
            "cited_case", "quoted_text", "brief_sentence"])
        w.writeheader()
        w.writerow({"claim_id": "t-01", "page": "1", "proposition": "P",
                    "cited_for": "", "cited_case": "A v. B, 1 U.S. 1",
                    "quoted_text": "[]", "brief_sentence": ""})
        w.writerow({"claim_id": "t-02", "page": "2", "proposition": "Q",
                    "cited_for": "", "cited_case": "A v. B, 1 U.S. 1",
                    "quoted_text": "[]", "brief_sentence": ""})
    return wd


class TestVerbs:
    def test_citations_from_claims_dedup(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            citations_from_workdir)
        wd = _claims_only_workdir(tmp_path)
        assert citations_from_workdir(wd) == ["A v. B, 1 U.S. 1"]

    def test_citations_union_extract_lists(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            citations_from_workdir)
        wd = _claims_only_workdir(tmp_path)
        (wd / "citations_toa.txt").write_text(
            "A v. B, 1 U.S. 1\nC v. D, 2 U.S. 2\n", encoding="utf-8")
        assert citations_from_workdir(wd) == [
            "A v. B, 1 U.S. 1", "C v. D, 2 U.S. 2"]

    @patch("citation_verifier.proposition_pipeline."
           "wave2_fallback_and_download")
    @patch("citation_verifier.proposition_pipeline."
           "wave1_verify_and_download")
    def test_verify_verb_chains_waves_and_writes_run_json(
            self, mock_w1, mock_w2, tmp_path):
        import asyncio
        from citation_verifier.proposition_pipeline import (
            Wave1Result, Wave2Result, run_verify)
        wd = _claims_only_workdir(tmp_path)

        async def w1(*a, **k):
            (wd / "verification_results.csv").write_text(
                "citation,status\n", encoding="utf-8")
            return Wave1Result(results=[], miss_indices=[0])

        async def w2(*a, **k):
            return Wave2Result(results=[])

        mock_w1.side_effect = w1
        mock_w2.side_effect = w2
        asyncio.run(run_verify(wd))
        assert mock_w1.called and mock_w2.called
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert "verify" in run["verbs"]
        assert run["git_hash"]

    @patch("citation_verifier.proposition_pipeline."
           "wave1_verify_and_download")
    def test_verify_verb_noops_when_results_exist(self, mock_w1, tmp_path):
        import asyncio
        from citation_verifier.proposition_pipeline import run_verify
        wd = _claims_only_workdir(tmp_path)
        (wd / "verification_results.csv").write_text(
            "citation,status\n", encoding="utf-8")
        assert asyncio.run(run_verify(wd)) is None
        assert not mock_w1.called

    def test_merge_verb_requires_results(self, tmp_path):
        from citation_verifier.proposition_pipeline import run_merge
        wd = _claims_only_workdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            run_merge(wd)

    def test_merge_verb_runs_and_stamps_run_json(self, tmp_path):
        from citation_verifier.proposition_pipeline import run_merge
        wd = _claims_only_workdir(tmp_path)
        with (wd / "verification_results.csv").open(
                "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "citation", "status", "confidence", "cl_url",
                "matched_name", "diagnostics_cat", "diagnostics_msg",
                "syllabus"])
            w.writeheader()
        stats = run_merge(wd)
        assert stats.unmatched == 2
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert "merge" in run["verbs"]


class TestExtractQuotedSpans:
    def test_two_word_span_extracted(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = ('The court treated stipulations as "judicial admissions" '
                'binding on the parties.')
        assert extract_quoted_spans(text) == ["judicial admissions"]

    def test_smart_quotes(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = "Held that “good cause shown” is required."
        assert extract_quoted_spans(text) == ["good cause shown"]

    def test_single_word_skipped(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        assert extract_quoted_spans('The "factors" test applies.') == []

    def test_single_quoted_spans_skipped(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        assert extract_quoted_spans("It's 'two words' here.") == []

    def test_multiple_spans_in_order(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = '"first span here" and then "second span" follows'
        assert extract_quoted_spans(text) == ["first span here",
                                              "second span"]

    def test_empty_and_none_safe(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        assert extract_quoted_spans("") == []
        assert extract_quoted_spans(None) == []


class TestCheckQuotesExtensions:
    def _wd(self, tmp_path, proposition, opinion_text, quoted_text="[]"):
        wd = tmp_path / "wd"
        (wd / "opinions").mkdir(parents=True)
        (wd / "opinions" / "A.html").write_text(opinion_text,
                                                encoding="utf-8")
        with (wd / "claims.csv").open("w", newline="",
                                      encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "claim_id", "proposition", "cited_case", "quoted_text",
                "opinion_file", "cl_status"])
            w.writeheader()
            w.writerow({"claim_id": "t-01", "proposition": proposition,
                        "cited_case": "A v. B", "quoted_text": quoted_text,
                        "opinion_file": "opinions/A.html",
                        "cl_status": "VERIFIED"})
        return wd

    def test_derives_quotes_from_proposition(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'Stipulations are "judicial admissions" here.',
                      "nothing relevant in this opinion text at all")
        stats = check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert json.loads(claims[0]["quoted_text"]) == [
            "judicial admissions"]
        assert claims[0]["quote_check_worst"] == "FABRICATED"
        assert claims[0]["quote_floor"] == "Yellow"
        assert stats.derived_quotes == 1

    def test_verbatim_quote_no_floor(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'The court said "exact words match" plainly.',
                      "Indeed the court said exact words match in text.")
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["quote_check_worst"] == "VERBATIM"
        assert claims[0]["quote_floor"] == ""

    def test_existing_quoted_text_not_overwritten(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'Also has "another quote" inside.',
                      "supplied span appears right here in the opinion",
                      quoted_text=json.dumps(["supplied span appears"]))
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert json.loads(claims[0]["quoted_text"]) == [
            "supplied span appears"]

    def test_quote_floor_bands(self):
        from citation_verifier.proposition_pipeline import _quote_floor
        fab = {"result": "FABRICATED", "similarity": 0.2}
        close_low = {"result": "CLOSE", "similarity": 0.64}
        close_near_verbatim = {"result": "CLOSE", "similarity": 0.80}
        verbatim = {"result": "VERBATIM", "similarity": 1.0}
        assert _quote_floor([fab]) == "Yellow"
        assert _quote_floor([close_low]) == "Yellow"
        # near-verbatim CLOSE band [0.75, 0.85): transcription noise, no floor
        assert _quote_floor([close_near_verbatim]) == ""
        assert _quote_floor([verbatim]) == ""
        assert _quote_floor([verbatim, close_near_verbatim, fab]) == "Yellow"
        assert _quote_floor([]) == ""

    def test_no_quotes_anywhere_still_no_quotes(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path, "No quotation marks at all.", "text")
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["quote_check_worst"] == "NO_QUOTES"
        assert claims[0]["quote_floor"] == ""


class TestPromptTemplate:
    def test_renders_identical_to_established_prompt(self):
        """assess-v1 fidelity: the template must render byte-identical to
        the prompt every recorded cassette was produced with."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import measure_withers_assessment as mwa
        from citation_verifier.proposition_pipeline import (
            render_assess_prompt)
        opinion = Path("C:/some/workdir/opinions/Nix_v_Whiteside.html")
        expected = mwa.build_prompt(
            opinion, "Nix v. Whiteside, 475 U.S. 157 (1986)",
            'The rules are there to protect "the integrity" of the process.',
            "CLOSE")
        got = render_assess_prompt(
            "assess-v1", str(opinion),
            "Nix v. Whiteside, 475 U.S. 157 (1986)",
            'The rules are there to protect "the integrity" of the process.',
            "CLOSE")
        assert got == expected

    def test_version_header_mismatch_raises(self, tmp_path, monkeypatch):
        import citation_verifier.proposition_pipeline as pp
        bad = tmp_path / "assess_v9.md"
        bad.write_text("<!-- prompt_version: assess-v1 -->\nbody",
                       encoding="utf-8")
        monkeypatch.setattr(pp, "_PROMPTS_DIR", tmp_path)
        with pytest.raises(ValueError):
            pp.load_prompt_template("assess-v9")


def _copy_withers(tmp_path):
    import shutil
    src = Path(__file__).parent / "data" / "assessment_corpora" / "withers"
    wd = tmp_path / "withers"
    shutil.copytree(src, wd)
    return wd


WITHERS_CASSETTE = (Path(__file__).parent / "data" / "assessment_corpora"
                    / "withers" / "jobs" / "assess_results.jsonl")


class TestAssessVerb:
    def test_jobs_mode_writes_jobs_and_reports_pending(self, tmp_path):
        from citation_verifier.proposition_pipeline import run_assess
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        stats = run_assess(wd)
        assert stats.eligible == 29
        assert stats.done == 0
        assert stats.pending == 29
        assert stats.skipped_deterministic == 5
        jobs = json.loads((wd / "jobs" / "assess.json").read_text(
            encoding="utf-8"))
        assert len(jobs) == 29
        # prompts are fully rendered: cite + absolute opinion path inside
        sample = jobs[0]
        assert sample["prompt_version"] == "assess-v1"
        assert "Read the opinion file at:" in sample["prompt"]
        assert str(wd) in sample["prompt"]

    def test_resume_ingests_partial_verdicts(self, tmp_path):
        from citation_verifier.executor import (
            Verdict, append_verdict_jsonl)
        from citation_verifier.proposition_pipeline import run_assess
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        run_assess(wd)
        append_verdict_jsonl(
            wd / "jobs" / "assess_results.jsonl",
            Verdict(claim_id="withers-01",
                    fields={"assessment": "Yellow", "rationale": "r"},
                    model="opus", prompt_version="assess-v1"))
        stats = run_assess(wd)
        assert stats.done == 1
        assert stats.pending == 28
        jobs = json.loads((wd / "jobs" / "assess.json").read_text(
            encoding="utf-8"))
        assert len(jobs) == 28
        assert not any("withers-01" in j["claim_ids"] for j in jobs)

    def test_recorded_executor_completes_offline(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor
        from citation_verifier.proposition_pipeline import run_assess
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        ex = RecordedExecutor(WITHERS_CASSETTE)
        stats = run_assess(wd, executor=ex)
        assert stats.done == 29
        assert stats.pending == 0
        from citation_verifier.executor import load_verdicts_jsonl
        assert len(load_verdicts_jsonl(
            wd / "jobs" / "assess_results.jsonl")) == 29

    def test_idempotent_when_complete(self, tmp_path):
        from citation_verifier.proposition_pipeline import run_assess
        wd = _copy_withers(tmp_path)  # cassette already complete
        stats = run_assess(wd)
        assert stats.done == 29
        assert stats.pending == 0
        assert not (wd / "jobs" / "assess.json").exists()


class TestApplyAssessments:
    def test_applies_verdicts_with_floor(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            run_apply_assessments)
        wd = _copy_withers(tmp_path)
        stats = run_apply_assessments(wd)
        assert stats.applied == 29
        assert stats.invalid == 0
        claims = {c["claim_id"]: c for c in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        # withers-09: recorded verdict Green, quote_floor Yellow -> floored
        assert claims["withers-09"]["quote_floor"] == "Yellow"
        assert claims["withers-09"]["assessment"] == "Yellow"
        assert claims["withers-09"]["assessed_by"] == "opus/assess-v1"
        # support column exists, empty for v1 (single-color schema)
        assert claims["withers-09"]["support"] == ""
        # rationale lands in finding_analysis when it was empty
        assert claims["withers-09"]["finding_analysis"]

    def test_matches_scoring_predictions(self, tmp_path):
        """The two floor implementations (apply-assessments and offline
        scoring) must agree on every agent-assessed claim."""
        from citation_verifier.proposition_pipeline import (
            run_apply_assessments)
        from citation_verifier.scoring import (
            RecordedExecutor, predict_workdir)
        wd = _copy_withers(tmp_path)
        run_apply_assessments(wd)
        claims = {c["claim_id"]: c for c in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        ex = RecordedExecutor(WITHERS_CASSETTE)
        for p in predict_workdir(wd, ex, "assess-v1"):
            if p.mode == "agent":
                assert claims[p.claim_id]["assessment"] == p.predicted, \
                    p.claim_id

    def test_invalid_verdict_reported_not_applied(self, tmp_path):
        from citation_verifier.executor import (
            Verdict, append_verdict_jsonl)
        from citation_verifier.proposition_pipeline import (
            run_apply_assessments)
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        append_verdict_jsonl(
            wd / "jobs" / "assess_results.jsonl",
            Verdict(claim_id="withers-01",
                    fields={"assessment": "Purple", "rationale": "r"},
                    model="opus", prompt_version="assess-v1"))
        stats = run_apply_assessments(wd)
        assert stats.invalid == 1
        assert stats.applied == 0
        claims = {c["claim_id"]: c for c in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        assert claims["withers-01"].get("assessment", "") == ""

    def test_requires_results_jsonl(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            run_apply_assessments)
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        with pytest.raises(FileNotFoundError):
            run_apply_assessments(wd)


class TestCli:
    def test_merge_verb_dispatch(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import MergeStats
        called = {}

        def fake_merge(wd):
            called["wd"] = Path(wd)
            return MergeStats(matched=2, opinion_count=1)

        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_merge", fake_merge)
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "merge"])
        assert rc == 0
        assert called["wd"] == wd
        assert "[OK]" in capsys.readouterr().out

    def test_verify_verb_noop_message(self, tmp_path, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        wd = _claims_only_workdir(tmp_path)
        (wd / "verification_results.csv").write_text(
            "citation,status\n", encoding="utf-8")
        rc = verify_propositions_main([str(wd), "verify"])
        assert rc == 0
        assert "already done" in capsys.readouterr().out

    def test_unknown_verb_errors(self, tmp_path):
        from citation_verifier.__main__ import verify_propositions_main
        wd = tmp_path / "wd"
        wd.mkdir()
        with pytest.raises(SystemExit):
            verify_propositions_main([str(wd), "frobnicate"])

    def test_missing_workdir_errors(self, tmp_path):
        from citation_verifier.__main__ import verify_propositions_main
        rc = verify_propositions_main([str(tmp_path / "nope"), "merge"])
        assert rc == 1

    def test_assess_replay_then_apply(self, tmp_path, capsys):
        """Offline end-to-end through the CLI: assess --replay ingests the
        recorded cassette, apply-assessments writes the colors."""
        from citation_verifier.__main__ import verify_propositions_main
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        rc = verify_propositions_main(
            [str(wd), "assess", "--replay", str(WITHERS_CASSETTE)])
        assert rc == 0
        assert "29 done, 0 pending" in capsys.readouterr().out
        rc = verify_propositions_main([str(wd), "apply-assessments"])
        assert rc == 0
        assert "29 applied" in capsys.readouterr().out
        claims = {c["claim_id"]: c for c in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        assert claims["withers-09"]["assessment"] == "Yellow"

    def test_assess_jobs_mode_reports_pending(self, tmp_path, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        wd = _copy_withers(tmp_path)
        (wd / "jobs" / "assess_results.jsonl").unlink()
        rc = verify_propositions_main([str(wd), "assess"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "29 pending" in out
        assert "PENDING" in out

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
            RecordedExecutor, Verdict, append_verdict_jsonl)
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
        import citation_verifier.proposition_pipeline as pp
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
        import citation_verifier.proposition_pipeline as pp
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
        import citation_verifier.proposition_pipeline as pp
        wd, doc = _extract_workdir(tmp_path)
        assert pp.run_extract(wd, doc).pending is True
        _extract_cassette(wd / "jobs" / "extract_results.jsonl")
        stats = pp.run_extract(wd, doc)
        assert stats.pending is False
        assert stats.claims == 2
        assert (wd / "claims.csv").exists()

    def test_noop_when_claims_exist(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd, doc = _extract_workdir(tmp_path)
        (wd / "claims.csv").write_text("claim_id\nx-01\n", encoding="utf-8")
        assert pp.run_extract(wd, doc) is None
        assert (wd / "claims.csv").read_text(
            encoding="utf-8") == "claim_id\nx-01\n"

    def test_malformed_verdict_raises(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette, fields={"claims": "not-a-list"})
        with pytest.raises(ValueError, match="extract verdict"):
            pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))
        assert not (wd / "claims.csv").exists()

    def test_claim_missing_required_field_raises(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        fields = _extract_verdict_fields()
        fields["claims"][1]["cited_case"] = ""
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette, fields=fields)
        with pytest.raises(ValueError, match="cited_case"):
            pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))

    def test_run_json_stamped(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        from citation_verifier.executor import RecordedExecutor
        wd, doc = _extract_workdir(tmp_path)
        cassette = tmp_path / "rec.jsonl"
        _extract_cassette(cassette)
        pp.run_extract(wd, doc, executor=RecordedExecutor(cassette))
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert run["verbs"]["extract"]["prompt_version"] == "extract-v1"
        assert run["verbs"]["extract"]["claims"] == 2


class TestMatchedCourtAccessors:
    def test_matched_court_from_download_stash(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Doe v. Memphis",
                             "matched_court": "United States Court of "
                                              "Appeals for the Sixth Circuit",
                             "matched_court_id": "ca6"})])
        assert r.matched_court.endswith("Sixth Circuit")
        assert r.matched_court_id == "ca6"

    def test_later_stage_supersedes(self):
        r = _result([
            _entry(StageName.citation_lookup, {"matched_court_id": "ca5"}),
            _entry(StageName.opinion_search, {"matched_court_id": "ca6"}),
        ])
        assert r.matched_court_id == "ca6"

    def test_empty_when_no_stage_recorded_court(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "X v. Y"})])
        assert r.matched_court == ""
        assert r.matched_court_id == ""


class TestVerificationCsvCourtColumns:
    def test_matched_court_columns_written(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Doe v. Memphis",
                             "matched_court": "Sixth Circuit",
                             "matched_court_id": "ca6"})])
        pp._write_verification_csv(tmp_path, ["Doe v. Memphis, 1 F.3d 1"],
                                   [r])
        with open(tmp_path / "verification_results.csv", newline="",
                  encoding="utf-8") as f:
            (row,) = list(csv.DictReader(f))
        assert row["matched_court"] == "Sixth Circuit"
        assert row["matched_court_id"] == "ca6"


class TestExtractPrompt:
    def test_template_loads_and_declares_version(self):
        import citation_verifier.proposition_pipeline as pp
        body = pp.load_prompt_template("extract-v1")
        assert "{document_path}" in body
        assert "prompt_version" not in body  # header comments stripped

    def test_render_substitutes_document_path(self):
        import citation_verifier.proposition_pipeline as pp
        prompt = pp.render_extract_prompt("extract-v1", r"C:\briefs\b.pdf")
        assert r"C:\briefs\b.pdf" in prompt
        assert "{document_path}" not in prompt

    def test_render_mentions_contract_columns(self):
        import citation_verifier.proposition_pipeline as pp
        prompt = pp.render_extract_prompt("extract-v1", "doc.pdf")
        for col in ("cited_case", "proposition", "cited_for",
                    "quoted_text", "brief_sentence", "page",
                    "citations_toa", "citations_body"):
            assert col in prompt
