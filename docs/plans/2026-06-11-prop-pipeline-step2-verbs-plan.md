# Proposition-Verifier Step 2: Pipeline Skeleton + verify/merge Verbs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `proposition_pipeline.py` (evolved from `brief_pipeline.py`, which becomes a deprecated alias), fix the empty-`matched_name` batch-path bug at the source, replace name-containment opinion linkage with slug-token matching, and expose `verify`/`merge` as idempotent verbs (importable + CLI).

**Architecture:** §10 step 2 of `docs/plans/2026-06-11-proposition-verifier-pipeline-design.md` (§2 rename/contract, §3 verb table rows 1-2, §4 schema, §11 bug 1). The module *moves* wholesale (same function names, same behavior except the two fixes) so the 38 tests in `test_brief_pipeline.py` keep passing against the alias unchanged. New behavior gets new tests in `test_proposition_pipeline.py`, including an offline validation of the slug linkage against the frozen Withers corpus (whose committed `verification_results.csv` has the empty-`matched_name` symptom — perfect regression data).

**Tech Stack:** Python stdlib; pytest with `unittest.mock.patch` (existing test style). No network in any new test.

**Root-cause facts (verified in source, 2026-06-11):**

- Producers write the matched caption under **different keys** in `resolution_path[*].raw_response_summary`: citation-lookup hits → `matched_case_name` (verifier.py:251), opinion/RECAP search stages → `best_case_name` (verifier.py:1064, 1116, 1157), caption investigation → `cl_case_name` (verifier.py:2332), sibling-swap → `case_name` (brief_pipeline.py:374).
- Both consumers read only `case_name`: `_write_verification_csv` (brief_pipeline.py:170) and `__main__._matched_case_name` (__main__.py:65). So `matched_name` is empty unless a sibling swap happened — that is the §11 bug, and it affects the single-citation CLI too, not just the batch path.
- `tests/test_brief_pipeline.py` patches `citation_verifier.brief_pipeline.CitationVerifier` / `.AsyncCourtListenerClient` **as module attributes** — the alias must make `citation_verifier.brief_pipeline` *be* the new module (`sys.modules` aliasing), or those patches would no longer reach the executing code.
- Direct `brief_pipeline` importers: `tests/test_brief_pipeline.py`, `tests/measure_withers_assessment.py`, `tests/measure_withers_baseline.py`, `src/citation_verifier/__main__.py`.
- The frozen Withers corpus (`tests/data/assessment_corpora/withers/`) contains `verification_results.csv` with blank `matched_name` for the batch rows and `claims.csv` whose `opinion_file` links were fixed by the measurement script's cl_url-slug workaround (threshold 0.25 Jaccard on tokens > 2 chars). The new merge must reproduce those links deterministically from the same inputs.
- `models.py` already has the accessor pattern to copy: `VerificationResult.syllabus` walks `resolution_path` reading `raw_response_summary` keys (models.py:275-293).

---

### Task 1: `VerificationResult.matched_case_name` accessor (the source fix)

**Files:**
- Modify: `src/citation_verifier/models.py` (next to the `syllabus` property)
- Test: `tests/test_proposition_pipeline.py` (new file)

- [ ] **Step 1.1: Write failing tests**

```python
# tests/test_proposition_pipeline.py
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
    FinalIds, PathEntry, StageName, StageStatus, Status, VerificationResult,
)


def _entry(stage, summary, status=StageStatus.resolved):
    return PathEntry(
        stage=stage, status=status, query={}, confidence=1.0,
        raw_response_summary=summary, notes="", elapsed_ms=0, cache_hit=False,
    )


def _result(path_entries):
    return VerificationResult(
        citation="Test v. Case, 1 U.S. 1 (1800)",
        status=Status.VERIFIED,
        headline_confidence=1.0,
        final_ids=FinalIds(),
        warnings=[],
        resolution_path=path_entries,
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
                   status=StageStatus.no_match),
        ])
        assert r.matched_case_name == "Found Here"

    def test_empty_path_returns_empty(self):
        assert _result([]).matched_case_name == ""
```

(Adjust the `PathEntry`/`StageStatus` constructor fields to the real
dataclass signature in `models.py`/`resolution_path.py` — check
`resolution_path.py:32` for field names; the test must construct entries
the way `cache.py:110` deserializes them.)

- [ ] **Step 1.2: Run, verify fail** — `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -q` → AttributeError: no `matched_case_name`.

- [ ] **Step 1.3: Implement the accessor in `models.py`** (mirror the `syllabus` property's placement and docstring style):

```python
# Producers stash the matched caption under stage-specific keys; this
# accessor is the single consumer-facing surface (SS11 bug 1 fix):
#   case_name          sibling-swap (brief_pipeline download phase)
#   matched_case_name  citation_lookup hits
#   cl_case_name       caption_investigation
#   best_case_name     opinion_search / recap_* stages
_MATCHED_NAME_KEYS = ("case_name", "matched_case_name",
                      "cl_case_name", "best_case_name")

@property
def matched_case_name(self) -> str:
    """Matched CL caption from the latest resolution stage that has one.

    Walks resolution_path backwards so refinement stages
    (caption_investigation, sibling swap) supersede the original hit.
    """
    for entry in reversed(self.resolution_path):
        for key in _MATCHED_NAME_KEYS:
            value = entry.raw_response_summary.get(key)
            if value:
                return value
    return ""
```

(`_MATCHED_NAME_KEYS` is a module-level constant in `models.py`.)

- [ ] **Step 1.4: Run, verify pass.** Also run `tests/test_verifier.py -q` (no collateral).

- [ ] **Step 1.5: Commit** — `feat: VerificationResult.matched_case_name accessor (SS11 bug 1 source fix)`

### Task 2: Module move + `sys.modules` alias

**Files:**
- Create: `src/citation_verifier/proposition_pipeline.py` (move of brief_pipeline.py content)
- Rewrite: `src/citation_verifier/brief_pipeline.py` (alias)

- [ ] **Step 2.1: `git mv src/citation_verifier/brief_pipeline.py src/citation_verifier/proposition_pipeline.py`**, then update its module docstring first line to:

```python
"""Proposition verification pipeline — idempotent verbs over a workdir.

Evolved from brief_pipeline.py (pipeline redesign SS2); brief_pipeline
remains importable as a deprecated alias of this module for one minor
version. Verbs land incrementally: verify/merge (SS10 step 2) are here;
check-quotes/crosscheck/triage/assess/apply-assessments/report follow.
"""
```

- [ ] **Step 2.2: Recreate `brief_pipeline.py` as the alias:**

```python
"""Deprecated alias: brief_pipeline is now proposition_pipeline (SS2).

sys.modules aliasing (not re-export) so that attribute patches against
citation_verifier.brief_pipeline (e.g. test_brief_pipeline's
@patch("citation_verifier.brief_pipeline.CitationVerifier")) reach the
globals the executing code actually reads. Remove after one minor version.
"""
import sys

from . import proposition_pipeline as _pp

sys.modules[__name__] = _pp
```

- [ ] **Step 2.3: Verify the alias preserves identity and patching** — add to `tests/test_proposition_pipeline.py`:

```python
class TestBriefPipelineAlias:
    def test_module_identity(self):
        import citation_verifier.brief_pipeline as bp
        import citation_verifier.proposition_pipeline as pp
        assert bp is pp

    def test_patch_through_alias_reaches_real_globals(self):
        import citation_verifier.proposition_pipeline as pp
        with patch("citation_verifier.brief_pipeline.CitationVerifier") as m:
            assert pp.CitationVerifier is m
```

- [ ] **Step 2.4: Run the full mocked suite** — `tests/test_brief_pipeline.py tests/test_proposition_pipeline.py tests/test_verifier.py -q` → all pass with zero edits to test_brief_pipeline.py.

- [ ] **Step 2.5: Commit** — `refactor: brief_pipeline -> proposition_pipeline; alias via sys.modules (SS2)`

### Task 3: Wire the accessor into the CSV writer + CLI consumer

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (`_write_verification_csv`)
- Modify: `src/citation_verifier/__main__.py` (`_matched_case_name`)
- Test: `tests/test_proposition_pipeline.py`

- [ ] **Step 3.1: Failing test — the batch-path regression:**

```python
class TestMatchedNameInCsv:
    def test_write_verification_csv_uses_accessor(self, tmp_path):
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
```

- [ ] **Step 3.2: Fix `_write_verification_csv`** — replace the `matched_name` extraction block (currently `last.raw_response_summary.get("case_name", "")`) with `matched_name = result.matched_case_name`. Keep `stage_notes` logic as-is.

- [ ] **Step 3.3: Fix `__main__._matched_case_name`** — body becomes `return result.matched_case_name or None`; update its docstring (the `_build_result` reference is stale).

- [ ] **Step 3.4: Run** new test + `tests/test_brief_pipeline.py` + `tests/test_cli_verify_batch.py` (CLI consumer touched). All pass.

- [ ] **Step 3.5: Commit** — `fix: matched_name no longer blank on batch path; CSV + CLI read the accessor (SS11 bug 1)`

### Task 4: Slug-token opinion linkage in merge

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (`merge_claims`, new `_slug_tokens`/`_link_opinion_file`; `claim_id`/`cited_for` passthrough)
- Test: `tests/test_proposition_pipeline.py`

- [ ] **Step 4.1: Failing tests** (the Midwest case from the measurement run is the motivating fixture):

```python
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


class TestSlugTokenLinkage:
    OPINION = ("MIDWEST_EMPLOYERS_CASUALTY_CO_Plaintiff-Appellant-Appellee"
               "_v_Jo_Ann_WILLIAMS_Defendant-Appellee-Appellant.html")

    def test_links_via_cl_url_slug_when_matched_name_blank(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        wd = _mk_merge_workdir(tmp_path, self.OPINION, {
            "citation": "Midwest Employers Cas. Co. v. Williams, "
                        "161 F.3d 877 (5th Cir. 1998)",
            "status": "VERIFIED", "confidence": "1.00",
            "cl_url": "https://www.courtlistener.com/opinion/758697/"
                      "midwest-employers-casualty-co-v-jo-ann-williams/",
            "matched_name": "", "diagnostics_cat": "",
            "diagnostics_msg": "", "syllabus": ""})
        stats = merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == f"opinions/{self.OPINION}"
        assert stats.opinion_count == 1

    def test_links_via_matched_name_tokens(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        wd = _mk_merge_workdir(tmp_path, self.OPINION, {
            "citation": "Midwest Employers Cas. Co. v. Williams, "
                        "161 F.3d 877 (5th Cir. 1998)",
            "status": "VERIFIED", "confidence": "1.00", "cl_url": "",
            "matched_name": "Midwest Employers Casualty Co. v. Williams",
            "diagnostics_cat": "", "diagnostics_msg": "", "syllabus": ""})
        merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == f"opinions/{self.OPINION}"

    def test_no_link_below_threshold(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        wd = _mk_merge_workdir(tmp_path, "Completely_Unrelated_v_Case.html", {
            "citation": "Midwest Employers Cas. Co. v. Williams, "
                        "161 F.3d 877 (5th Cir. 1998)",
            "status": "VERIFIED", "confidence": "1.00", "cl_url": "",
            "matched_name": "", "diagnostics_cat": "",
            "diagnostics_msg": "", "syllabus": ""})
        merge_claims(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["opinion_file"] == ""

    def test_claim_id_and_cited_for_survive_merge(self, tmp_path):
        from citation_verifier.proposition_pipeline import merge_claims
        wd = _mk_merge_workdir(tmp_path, self.OPINION, {
            "citation": "Midwest Employers Cas. Co. v. Williams, "
                        "161 F.3d 877 (5th Cir. 1998)",
            "status": "VERIFIED", "confidence": "1.00", "cl_url": "",
            "matched_name": "Midwest Employers Casualty Co. v. Williams",
            "diagnostics_cat": "", "diagnostics_msg": "", "syllabus": ""})
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
```

Note: the frozen claims.csv contains post-merge columns (quote_check etc.);
merge re-runs over it and must preserve passthrough columns AND `claim_id`.
If `got != expected` only on rows where the new linkage finds a *correct*
link the workaround missed, STOP and inspect: an improvement is acceptable
but must be deliberate — update the frozen corpus and its README in the
same commit, and re-run the Step 1 regression suite to prove cassette
claim_ids still align.

- [ ] **Step 4.2: Run, verify fail** (current merge links by name containment; the slug case fails).

- [ ] **Step 4.3: Implement.** In `proposition_pipeline.py`:

```python
def _slug_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 2}


_LINK_THRESHOLD = 0.25  # Jaccard; from the 2026-06-11 measurement workaround


def _link_opinion_file(workdir: Path, matched_name: str, cited_case: str,
                       cl_url: str) -> str:
    """Slug-token opinion linkage (replaces name-containment, SS10 step 2).

    Scores every opinions/ file stem by Jaccard token overlap against three
    sources in priority order -- the cl_url slug, the CL matched name, the
    cited case-name part -- and returns the best file at or above threshold
    from the first source that produces one.
    """
    opinions_dir = workdir / "opinions"
    if not opinions_dir.exists():
        return ""
    stems = {f.name: _slug_tokens(f.stem)
             for f in opinions_dir.iterdir() if f.is_file()}
    if not stems:
        return ""

    slug = cl_url.rstrip("/").rsplit("/", 1)[-1] if cl_url else ""
    name_part = cited_case.split(",")[0] if cited_case else ""
    for source in (slug, matched_name, name_part):
        st = _slug_tokens(source)
        if not st:
            continue
        best, best_score = "", 0.0
        for fname, ft in stems.items():
            if not ft:
                continue
            score = len(st & ft) / len(st | ft)
            if score > best_score:
                best, best_score = fname, score
        if best and best_score >= _LINK_THRESHOLD:
            return f"opinions/{best}"
    return ""
```

In `merge_claims`: replace the `_find_opinion_file` block with

```python
        opinion_file = _link_opinion_file(workdir, matched_name, cited, url)
```

and extend the schema: `output_fields` starts
`["claim_id", "page", "proposition", "cited_for", "cited_case", ...]` —
include `claim_id`/`cited_for` only when present in the input claims (so
legacy claims.csv without them still merge); carry their values through in
the row dict (`row["claim_id"] = claim.get("claim_id", "")` etc.).
Keep `_find_opinion_file` defined (other callers/tests may reference it)
but unused by merge.

- [ ] **Step 4.4: Run** new tests + `test_brief_pipeline.py::TestMergeClaims` + `TestMergePassthroughColumns`. If a legacy merge test asserted containment-based linkage behavior that slug-linkage changes, examine it: the *contract* (file gets linked) should still hold; only update a test if it pinned the mechanism rather than the outcome, and say so in the commit message.

- [ ] **Step 4.5: Run the Step 1 offline regression** (`tests/test_assessment_regression.py tests/test_assessment_corpora.py -q`) — the frozen corpus must be byte-identical (merge test ran on a copy).

- [ ] **Step 4.6: Commit** — `feat: slug-token opinion linkage in merge (replaces name-containment); claim_id/cited_for passthrough`

### Task 5: `verify` and `merge` verbs + run.json + idempotence

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py`
- Test: `tests/test_proposition_pipeline.py`

- [ ] **Step 5.1: Failing tests:**

```python
class TestVerbs:
    def _claims_only_workdir(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        with (wd / "claims.csv").open("w", newline="",
                                      encoding="utf-8") as f:
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

    def test_citations_from_claims_dedup(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            citations_from_workdir)
        wd = self._claims_only_workdir(tmp_path)
        assert citations_from_workdir(wd) == ["A v. B, 1 U.S. 1"]

    @patch("citation_verifier.proposition_pipeline."
           "wave2_fallback_and_download")
    @patch("citation_verifier.proposition_pipeline."
           "wave1_verify_and_download")
    def test_verify_verb_chains_waves_and_writes_run_json(
            self, mock_w1, mock_w2, tmp_path):
        from citation_verifier.proposition_pipeline import (
            Wave1Result, Wave2Result, run_verify)
        import asyncio
        wd = self._claims_only_workdir(tmp_path)
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
        from citation_verifier.proposition_pipeline import run_verify
        import asyncio
        wd = self._claims_only_workdir(tmp_path)
        (wd / "verification_results.csv").write_text(
            "citation,status\n", encoding="utf-8")
        asyncio.run(run_verify(wd))
        assert not mock_w1.called

    def test_merge_verb_requires_results(self, tmp_path):
        from citation_verifier.proposition_pipeline import run_merge
        wd = self._claims_only_workdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            run_merge(wd)
```

- [ ] **Step 5.2: Run, verify fail.**

- [ ] **Step 5.3: Implement** in `proposition_pipeline.py`:

```python
import subprocess
from datetime import datetime, timezone


def _update_run_json(workdir: Path, verb: str, **info: Any) -> None:
    """Reproducibility record (design SS3): git hash + per-verb stamps."""
    path = workdir / "run.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json_mod.loads(path.read_text(encoding="utf-8"))
        except json_mod.JSONDecodeError:
            data = {}
    if not data.get("git_hash"):
        try:
            data["git_hash"] = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=str(Path(__file__).parent),
            ).stdout.strip() or "unknown"
        except Exception:
            data["git_hash"] = "unknown"
    verbs = data.setdefault("verbs", {})
    verbs[verb] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **info,
    }
    path.write_text(json_mod.dumps(data, indent=2), encoding="utf-8")


def citations_from_workdir(workdir: Path) -> list[str]:
    """Unique citations to verify: claims.csv cited_case (order-preserving
    dedup), unioned with citations_toa.txt / citations_body.txt when the
    extract verb has produced them (one citation per line)."""
    workdir = Path(workdir)
    seen: dict[str, None] = {}
    with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cite = (row.get("cited_case") or "").strip()
            if cite:
                seen.setdefault(cite)
    for name in ("citations_toa.txt", "citations_body.txt"):
        p = workdir / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    seen.setdefault(line)
    return list(seen)


async def run_verify(workdir: Path, citations: list[str] | None = None,
                     force: bool = False, progress_callback: Any = None,
                     ) -> PipelineResult | None:
    """Verb 1 (design SS3): wave1 + wave2 + downloads. Idempotent --
    no-ops when verification_results.csv already exists (rerun with
    force=True to redo). Returns None on the no-op path."""
    workdir = Path(workdir)
    if (workdir / "verification_results.csv").exists() and not force:
        return None
    if citations is None:
        citations = citations_from_workdir(workdir)
    w1 = await wave1_verify_and_download(workdir, citations,
                                         progress_callback)
    w2 = await wave2_fallback_and_download(workdir, citations,
                                           w1.miss_indices,
                                           progress_callback)
    _update_run_json(workdir, "verify", citations=len(citations),
                     wave1_misses=len(w1.miss_indices))
    return PipelineResult(wave1=w1, wave2=w2,
                          merge=MergeStats())  # merge is its own verb


def run_merge(workdir: Path) -> MergeStats:
    """Verb 2 (design SS3): join claims <-> results + slug linkage.
    Requires verification_results.csv (run_verify first)."""
    workdir = Path(workdir)
    vr = workdir / "verification_results.csv"
    if not vr.exists():
        raise FileNotFoundError(
            f"{vr} missing -- run the verify verb first")
    stats = merge_claims(workdir)
    _update_run_json(workdir, "merge", matched=stats.matched,
                     linked=stats.opinion_count)
    return stats
```

(`PipelineResult.merge` keeps its field; the verb returns an empty
`MergeStats` placeholder — `full_pipeline` continues to exist unchanged
for the legacy callers.)

- [ ] **Step 5.4: Run, verify pass;** run full mocked suite.

- [ ] **Step 5.5: Commit** — `feat: verify/merge verbs (idempotent, run.json) on proposition_pipeline (SS3 rows 1-2)`

### Task 6: CLI — `verify-propositions <workdir> <verb>`

**Files:**
- Modify: `src/citation_verifier/__main__.py`
- Test: `tests/test_proposition_pipeline.py`

- [ ] **Step 6.1: Failing test** (call main() with argv, mocking the verb):

```python
class TestCli:
    def test_verify_propositions_merge_verb(self, tmp_path, monkeypatch,
                                            capsys):
        from citation_verifier.__main__ import main
        from citation_verifier.proposition_pipeline import MergeStats
        called = {}
        def fake_merge(wd):
            called["wd"] = Path(wd)
            return MergeStats(matched=2, opinion_count=1)
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_merge", fake_merge)
        wd = tmp_path / "wd"; wd.mkdir()
        main(["verify-propositions", str(wd), "merge"])
        assert called["wd"] == wd
        assert "[OK]" in capsys.readouterr().out

    def test_unknown_verb_errors(self, tmp_path):
        from citation_verifier.__main__ import main
        wd = tmp_path / "wd"; wd.mkdir()
        with pytest.raises(SystemExit):
            main(["verify-propositions", str(wd), "frobnicate"])
```

(Check `__main__.main`'s signature first — if it reads `sys.argv` instead
of taking an argv parameter, follow the existing pattern used by
`tests/test_cli_verify_batch.py` for invoking it.)

- [ ] **Step 6.2: Implement.** Add a `verify-propositions` subparser:
positional `workdir`, positional `verb` with
`choices=["verify", "merge", "full"]`, flags `--force`, `--quick-only`
(reserved), `--citations-file PATH` (optional explicit list, one per
line). Dispatch:

```python
    elif args.command == "verify-propositions":
        from . import proposition_pipeline as pp
        wd = Path(args.workdir)
        if args.verb == "merge":
            stats = pp.run_merge(wd)
            print(f"[OK] merge: {stats.matched} matched, "
                  f"{stats.opinion_count} opinion files linked")
        else:  # verify | full
            citations = None
            if args.citations_file:
                citations = [ln.strip() for ln in
                             Path(args.citations_file).read_text(
                                 encoding="utf-8").splitlines() if ln.strip()]
            result = asyncio.run(pp.run_verify(
                wd, citations=citations, force=args.force))
            if result is None:
                print("[OK] verify: already done (use --force to rerun)")
            else:
                print(f"[OK] verify: wave1 misses="
                      f"{len(result.wave1.miss_indices)}")
            if args.verb == "full":
                stats = pp.run_merge(wd)
                print(f"[OK] merge: {stats.matched} matched, "
                      f"{stats.opinion_count} opinion files linked")
```

ASCII-only output. The existing `verify-brief` subcommand stays untouched.

- [ ] **Step 6.3: Run** new tests + `tests/test_cli_verify_batch.py` + smoke: `venv/Scripts/python.exe -m citation_verifier verify-propositions --help`.

- [ ] **Step 6.4: Commit** — `feat: verify-propositions CLI verbs (verify/merge/full)`

### Task 7: Docs + full suite + push

- [ ] **Step 7.1:** CLAUDE.md — update the `brief_pipeline.py` row: now `proposition_pipeline.py` (verbs `verify`/`merge` + legacy wave/quote/report functions; `brief_pipeline` is a deprecated sys.modules alias); note the matched_case_name accessor under Common Pitfalls (`VerificationResult.matched_case_name` is the only sanctioned way to read the matched caption — the raw_response_summary keys vary by stage).
- [ ] **Step 7.2:** Append execution notes to this plan if anything deviated.
- [ ] **Step 7.3:** Full offline suite: `venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_false_negatives.py --ignore=tests/test_cl_api_issues.py -p no:cacheprovider` → all pass.
- [ ] **Step 7.4:** Commit docs; push `pipeline-redesign`.

---

## Self-review notes

- §11 bug 1 "fixed at the source": Task 1 (accessor) + Task 3 (both consumers). The fix deliberately lands as a *read-side* accessor rather than normalizing every producer's summary keys — the summaries are per-stage free-form by design (§2.5 of the refactor design), and a single accessor fixes all four key variants including future ones in one place.
- §3 row 1-2 verbs + idempotence + run.json: Task 5. `status` verb and the remaining verbs are later steps.
- §2 module/alias/CLI rename: Tasks 2 and 6 (workdirs `matters/` is a convention, not code — the verbs take any path).
- Slug linkage §10 step 2: Task 4, validated against the frozen Withers corpus offline.
- Out of scope, per §10: quote-check extensions (step 3), executors/assess (step 4-5), extract, crosscheck/triage, report lanes.

## Execution notes (2026-06-11, all tasks complete)

- Constructor reality differed from the plan sketch: the path-entry type is
  `ResolutionPathEntry(stage, query, raw_response_summary, verdict,
  confidence, notes, elapsed_ms)` with `StageVerdict` (not
  PathEntry/StageStatus), and `VerificationResult` uses
  `citation_as_written`/`gates_failed`/`timing`/`cache_hit`. Tests written
  against the real signatures.
- The CLI has no argparse subparsers — dispatch is per-command main
  functions in the `__main__` block. Added `verify_propositions_main(argv)`
  and a `verify-propositions` dispatch line; tests call the function
  directly (same pattern as the other CLI suites).
- `TestWithersCorpusLinkage` passed on the first implementation run: the
  new slug linkage reproduces the frozen corpus's opinion_file links
  exactly (no improvements/regressions to adjudicate).
- All 38 legacy `test_brief_pipeline.py` tests pass through the
  `sys.modules` alias with zero edits.

## Subsequent steps (§10 map)

3. Quote-check extensions (>=2-word spans, CLOSE/FABRICATED floors) — TDD off the withers frozen corpus.
4. AgentToolExecutor (jobs mode) + assess/apply-assessments; prompt templates extracted.
5. AgentSDKExecutor + extract verb. 6. crosscheck + triage. 7. Report lanes, SKILL stub, A/B re-point. 8. Acceptance runs; retro.
