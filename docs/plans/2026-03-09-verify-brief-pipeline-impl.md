# Verify-Brief Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move all mechanical verify-brief work into `src/citation_verifier/brief_pipeline.py`, update client.py to support HTML downloads, rewrite the skill to orchestrate only LLM-hard phases.

**Architecture:** Pipeline module with three public async functions (wave1, wave2, merge) plus CLI entry point. Client gains `prefer_html` parameter. Skill shrinks from 280 lines to ~120, referencing pipeline CLI commands instead of embedded code.

**Tech Stack:** Python 3.10+, asyncio, existing citation_verifier library (CitationVerifier, AsyncCourtListenerClient, verify_batch)

**Design doc:** `docs/plans/2026-03-09-verify-brief-pipeline-design.md`

---

### Task 1: Add `prefer_html` to `get_opinion_text_with_metadata()` (sync client)

**Files:**
- Modify: `src/citation_verifier/client.py:222-280` (sync `get_opinion_text_with_metadata`)
- Modify: `src/citation_verifier/client.py:330-365` (`_resolve_opinion_text_with_metadata`)
- Test: `tests/test_client_html.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_client_html.py
"""Tests for HTML opinion text retrieval."""
import pytest
from unittest.mock import patch, MagicMock
from citation_verifier.client import CourtListenerClient


class TestPreferHtml:
    """get_opinion_text_with_metadata with prefer_html=True."""

    def _mock_cluster(self, sub_opinion_id="123", case_name="Test v. Case",
                      plain_text="", html_with_citations="", html=""):
        """Build mock responses for cluster -> opinion chain."""
        cluster_resp = MagicMock()
        cluster_resp.json.return_value = {
            "sub_opinions": [f"https://www.courtlistener.com/api/rest/v4/opinions/{sub_opinion_id}/"],
            "case_name": case_name,
            "citations": [],
            "date_filed": "2020-01-01",
            "docket_number": "1:20-cv-00001",
        }
        opinion_resp = MagicMock()
        opinion_resp.json.return_value = {
            "plain_text": plain_text,
            "html_with_citations": html_with_citations,
            "html": html,
        }
        return [cluster_resp, opinion_resp]

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_prefer_html_returns_html_when_available(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text version",
            html_with_citations='<p>HTML with <a href="/opinion/456/">cited case</a></p>',
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert "<a href" in result["text"]
        assert result["format"] == "html"

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_prefer_html_falls_back_to_plain_text(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text only",
            html_with_citations="",
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert result["text"] == "Plain text only"
        assert result["format"] == "text"

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_default_prefer_html_false_returns_plain_text(self, mock_req):
        mock_req.side_effect = self._mock_cluster(
            plain_text="Plain text version",
            html_with_citations='<p>HTML version</p>',
        )
        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
        )
        assert result is not None
        assert "<p>" not in result["text"]
        assert result["format"] == "text"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_client_html.py -v`
Expected: FAIL — `prefer_html` parameter not accepted, no `format` key in result.

**Step 3: Implement**

Modify `client.py:_resolve_opinion_text_with_metadata()` to:
- Accept `prefer_html: bool = False` parameter
- When `prefer_html=True`, check `html_with_citations` first, return raw HTML with `format: "html"`
- When `prefer_html=False` (default), keep current behavior (plain_text, fall back to stripped HTML)
- Always include `format` key in returned dict (`"html"`, `"text"`)

Modify `get_opinion_text_with_metadata()` signature to pass through `prefer_html`.

Do the same for the async version (`client.py:632`).

**Step 4: Run tests**

Run: `pytest tests/test_client_html.py -v && pytest tests/test_verifier.py -v`
Expected: All pass. Existing tests unaffected (default `prefer_html=False`).

**Step 5: Commit**

```bash
git add src/citation_verifier/client.py tests/test_client_html.py
git commit -m "feat: add prefer_html option to get_opinion_text_with_metadata"
```

---

### Task 2: Add PDF download fallback to client

**Files:**
- Modify: `src/citation_verifier/client.py` (sync and async clients)
- Test: `tests/test_client_html.py` (append)

**Step 1: Write the failing test**

```python
class TestPdfFallback:
    """Download PDF when no text or HTML available."""

    @patch.object(CourtListenerClient, "_request_with_retry")
    def test_returns_pdf_bytes_when_no_text(self, mock_req):
        cluster_resp = MagicMock()
        cluster_resp.json.return_value = {
            "sub_opinions": ["https://www.courtlistener.com/api/rest/v4/opinions/123/"],
            "case_name": "Test v. Case",
            "citations": [],
            "date_filed": "2020-01-01",
            "docket_number": "1:20-cv-00001",
            "filepath_pdf_with_extracted_text": "recap/gov.uscourts.test/test.pdf",
        }
        opinion_resp = MagicMock()
        opinion_resp.json.return_value = {
            "plain_text": "",
            "html_with_citations": "",
            "html": "",
        }
        pdf_resp = MagicMock()
        pdf_resp.content = b"%PDF-1.4 fake pdf content"
        pdf_resp.status_code = 200
        mock_req.side_effect = [cluster_resp, opinion_resp, pdf_resp]

        client = CourtListenerClient.__new__(CourtListenerClient)
        result = client.get_opinion_text_with_metadata(
            "https://www.courtlistener.com/opinion/789/test/",
            prefer_html=True,
        )
        assert result is not None
        assert result["format"] == "pdf"
        assert result["pdf_bytes"] == b"%PDF-1.4 fake pdf content"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_client_html.py::TestPdfFallback -v`
Expected: FAIL — no PDF fallback logic, no `pdf_bytes` key.

**Step 3: Implement**

In `_resolve_opinion_text_with_metadata()`, after failing to find text or HTML:
- Check cluster for `filepath_pdf_with_extracted_text`
- Download PDF from CL storage URL
- Return dict with `format: "pdf"`, `pdf_bytes: bytes`, and `text: None`

**Step 4: Run tests**

Run: `pytest tests/test_client_html.py -v && pytest tests/test_verifier.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/citation_verifier/client.py tests/test_client_html.py
git commit -m "feat: add PDF download fallback when no text/HTML available"
```

---

### Task 3: Create `brief_pipeline.py` — data structures and `merge_claims()`

**Files:**
- Create: `src/citation_verifier/brief_pipeline.py`
- Test: `tests/test_brief_pipeline.py` (new)

Start with the simplest function (merge) that has no API dependencies.

**Step 1: Write the failing test**

```python
# tests/test_brief_pipeline.py
"""Tests for the brief verification pipeline."""
import csv
import pytest
from pathlib import Path
from citation_verifier.brief_pipeline import merge_claims, MergeStats


@pytest.fixture
def workdir(tmp_path):
    """Set up a workdir with claims.csv and verification_results.csv."""
    # claims.csv — Phase 1 output
    claims = tmp_path / "claims.csv"
    claims.write_text(
        "page,proposition,cited_case\n"
        '21,"Courts defer to executive on security clearances.","Dep\'t of Navy v. Egan, 484 U.S. 518, 527 (1988)"\n'
        '22,"Same principle applies broadly.","Dep\'t of Navy v. Egan, 484 U.S. 518 (1988)"\n'
        '30,"Free speech applies.","Garcetti v. Ceballos, 547 U.S. 410 (2006)"\n'
        '35,"The Federalist No. 72","The Federalist No. 72"\n'
    )
    # verification_results.csv
    vr = tmp_path / "verification_results.csv"
    vr.write_text(
        "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
        '"Dep\'t of Navy v. Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,'
        'https://www.courtlistener.com/opinion/111990/egan/,'
        'Department of the Navy v. Egan,,\n'
        '"Garcetti v. Ceballos, 547 U.S. 410 (2006)",VERIFIED,1.0,'
        'https://www.courtlistener.com/opinion/145625/garcetti/,'
        'Garcetti v. Ceballos,,\n'
    )
    # opinions/
    opinions = tmp_path / "opinions"
    opinions.mkdir()
    (opinions / "Dept_of_Navy_v_Egan.txt").write_text("opinion text here")
    return tmp_path


class TestMergeClaims:
    def test_basic_merge(self, workdir):
        stats = merge_claims(workdir)
        assert stats.matched == 3  # 2 Egan rows + 1 Garcetti
        assert stats.unmatched == 1  # Federalist

        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        assert len(merged) == 4

        # Egan pinpoint row matched
        egan_row = merged[0]
        assert egan_row["cl_status"] == "VERIFIED"
        assert "egan" in egan_row["cl_url"].lower()
        assert egan_row["retrieved_case"] == "Department of the Navy v. Egan"

        # Non-case citation has empty verification fields
        fed_row = merged[3]
        assert fed_row["cl_status"] == ""

    def test_pinpoint_stripping(self, workdir):
        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        # Both Egan rows (with and without pinpoint) should match
        assert merged[0]["cl_url"] == merged[1]["cl_url"]

    def test_opinion_file_linked(self, workdir):
        stats = merge_claims(workdir)
        merged = list(csv.DictReader((workdir / "claims.csv").open()))
        # Egan has opinion file, Garcetti doesn't (no file created in fixture)
        assert merged[0]["opinion_file"] != ""
        assert merged[2]["opinion_file"] == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brief_pipeline.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement `brief_pipeline.py`**

Create `src/citation_verifier/brief_pipeline.py` with:
- `MergeStats` dataclass: `matched`, `unmatched`, `statuses` (dict), `opinion_count`
- `_strip_pinpoint(cite: str) -> str`: regex to strip pinpoint pages from citations
- `_find_opinion_file(workdir: Path, case_name: str) -> str`: scan opinions/ for matching file
- `merge_claims(workdir: Path) -> MergeStats`: read claims.csv + verification_results.csv, join on base citation, write updated claims.csv

The output `claims.csv` columns: `page, proposition, cited_case, retrieved_case, supporting_language, assessment, cl_url, cl_status, diagnostics, opinion_file`

**Step 4: Run tests**

Run: `pytest tests/test_brief_pipeline.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add brief_pipeline.py with merge_claims()"
```

---

### Task 4: Implement `wave1_verify_and_download()`

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py`
- Test: `tests/test_brief_pipeline.py` (append)

**Step 1: Write the failing test**

```python
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from citation_verifier.brief_pipeline import wave1_verify_and_download, Wave1Result
from citation_verifier.models import VerificationResult, VerificationStatus, Diagnostic


class TestWave1:
    def _make_result(self, status, url="", case_name=""):
        return VerificationResult(
            input_citation="test",
            status=status,
            confidence=1.0 if status == VerificationStatus.VERIFIED else 0.0,
            matched_url=url,
            matched_case_name=case_name,
            matched_cluster_id="123" if url else None,
            diagnostics=[],
        )

    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave1_downloads_verified_cases(self, mock_verifier_cls, mock_client_cls, tmp_path):
        citations = ["Case A, 100 U.S. 1 (2000)", "Case B, 200 U.S. 2 (2001)"]

        # verify_batch returns both as VERIFIED
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            self._make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Case A"),
            self._make_result(VerificationStatus.VERIFIED, "https://cl/opinion/2/", "Case B"),
        ])

        # Client returns text for both
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(side_effect=[
            {"text": "Opinion A text", "case_name": "Case A", "format": "text",
             "citations": [], "court": "", "date_filed": "", "docket_number": ""},
            {"text": "Opinion B text", "case_name": "Case B", "format": "text",
             "citations": [], "court": "", "date_filed": "", "docket_number": ""},
        ])

        (tmp_path / "citations_to_verify.txt").write_text("Case A, 100 U.S. 1 (2000)\nCase B, 200 U.S. 2 (2001)\n")
        result = asyncio.run(wave1_verify_and_download(tmp_path, citations))

        assert isinstance(result, Wave1Result)
        assert len(result.miss_indices) == 0
        assert (tmp_path / "opinions").exists()
        assert result.download_stats["downloaded"] == 2

    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave1_identifies_misses(self, mock_verifier_cls, mock_client_cls, tmp_path):
        citations = ["Found, 100 U.S. 1 (2000)", "Missing, 200 U.S. 2 (2001)"]

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            self._make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Found"),
            self._make_result(VerificationStatus.NOT_FOUND),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Opinion text", "case_name": "Found", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        (tmp_path / "citations_to_verify.txt").write_text("Found, 100 U.S. 1 (2000)\nMissing, 200 U.S. 2 (2001)\n")
        result = asyncio.run(wave1_verify_and_download(tmp_path, citations))

        assert result.miss_indices == [1]
        assert result.download_stats["downloaded"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brief_pipeline.py::TestWave1 -v`
Expected: FAIL — `wave1_verify_and_download` not defined.

**Step 3: Implement**

Add to `brief_pipeline.py`:
- `Wave1Result` dataclass: `results`, `miss_indices`, `download_stats`
- `_sanitize_filename(case_name: str) -> str`: safe filename from case name
- `_download_opinion(client, workdir, result, expected_name) -> str | None`: download with HTML > text > PDF priority, sanity check case name, return saved path or None
- `_write_verification_csv(workdir, citations, results, append=False)`: write/append verification_results.csv
- `async def wave1_verify_and_download(workdir, citations) -> Wave1Result`:
  1. Call `verify_batch(citations, quick_only=True)`
  2. Download opinions for VERIFIED, LIKELY_REAL, POSSIBLE_MATCH
  3. Write verification_results.csv
  4. Return Wave1Result with miss indices

Key details:
- Use `verify_batch(quick_only=True)` — single API call, no fallback
- Download using `AsyncCourtListenerClient` with `prefer_html=True`
- Sanity check: use `name_matcher.case_name_similarity()` to compare downloaded case name to expected. If < 0.4, add warning diagnostic.
- Save as `.html` or `.txt` or `.pdf` based on `format` from client response

**Step 4: Run tests**

Run: `pytest tests/test_brief_pipeline.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add wave1_verify_and_download to brief pipeline"
```

---

### Task 5: Implement `wave2_fallback_and_download()`

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py`
- Test: `tests/test_brief_pipeline.py` (append)

**Step 1: Write the failing test**

```python
from citation_verifier.brief_pipeline import wave2_fallback_and_download, Wave2Result


class TestWave2:
    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_wave2_runs_fallback_for_misses(self, mock_verifier_cls, mock_client_cls, tmp_path):
        citations = ["Found, 100 U.S. 1 (2000)", "Miss1, 200 U.S. 2 (2001)", "Miss2, 300 U.S. 3 (2002)"]
        miss_indices = [1, 2]

        # verify_batch (full pipeline, not quick_only) resolves Miss1
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.verify_batch = AsyncMock(return_value=[
            self._make_result(VerificationStatus.LIKELY_REAL, "https://cl/opinion/10/", "Miss One"),
            self._make_result(VerificationStatus.NOT_FOUND),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Resolved opinion", "case_name": "Miss One", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        # Pre-existing verification_results.csv from wave1
        (tmp_path / "verification_results.csv").write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Found, 100 U.S. 1 (2000)",VERIFIED,1.0,https://cl/opinion/1/,Found,,\n'
        )
        (tmp_path / "opinions").mkdir(exist_ok=True)

        result = asyncio.run(wave2_fallback_and_download(tmp_path, citations, miss_indices))

        assert isinstance(result, Wave2Result)
        assert result.download_stats["downloaded"] == 1
        # verification_results.csv should now have 3 rows (1 from wave1 + 2 from wave2)
        vr = list(csv.DictReader((tmp_path / "verification_results.csv").open()))
        assert len(vr) == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brief_pipeline.py::TestWave2 -v`
Expected: FAIL — `wave2_fallback_and_download` not defined.

**Step 3: Implement**

Add to `brief_pipeline.py`:
- `Wave2Result` dataclass: `results`, `download_stats`
- `async def wave2_fallback_and_download(workdir, citations, miss_indices) -> Wave2Result`:
  1. Extract miss citations by index
  2. Call `verify_batch(miss_citations)` — full pipeline (NOT quick_only)
  3. Download opinions for any that resolve
  4. Append to verification_results.csv
  5. Return Wave2Result

**Step 4: Run tests**

Run: `pytest tests/test_brief_pipeline.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add wave2_fallback_and_download to brief pipeline"
```

---

### Task 6: Add `full_pipeline()` and CLI entry point

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py`
- Modify: `src/citation_verifier/__main__.py`
- Test: `tests/test_brief_pipeline.py` (append)

**Step 1: Write the failing test**

```python
class TestFullPipeline:
    @patch("citation_verifier.brief_pipeline.AsyncCourtListenerClient")
    @patch("citation_verifier.brief_pipeline.CitationVerifier")
    def test_full_pipeline_runs_wave1_wave2_merge(self, mock_verifier_cls, mock_client_cls, tmp_path):
        """full_pipeline runs wave1 + wave2 + merge in sequence."""
        # Set up citations_to_verify.txt and claims.csv
        (tmp_path / "citations_to_verify.txt").write_text("Case A, 100 U.S. 1 (2000)\n")
        (tmp_path / "claims.csv").write_text(
            "page,proposition,cited_case\n"
            '1,"Some proposition.","Case A, 100 U.S. 1 (2000)"\n'
        )

        mock_verifier = mock_verifier_cls.return_value
        # wave1 (quick_only) finds it
        mock_verifier.verify_batch = AsyncMock(return_value=[
            self._make_result(VerificationStatus.VERIFIED, "https://cl/opinion/1/", "Case A"),
        ])

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(return_value={
            "text": "Opinion text", "case_name": "Case A", "format": "text",
            "citations": [], "court": "", "date_filed": "", "docket_number": "",
        })

        from citation_verifier.brief_pipeline import full_pipeline, PipelineResult
        result = asyncio.run(full_pipeline(tmp_path, ["Case A, 100 U.S. 1 (2000)"]))

        assert isinstance(result, PipelineResult)
        # claims.csv should be merged
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["cl_status"] == "VERIFIED"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brief_pipeline.py::TestFullPipeline -v`
Expected: FAIL — `full_pipeline` not defined.

**Step 3: Implement**

Add to `brief_pipeline.py`:
- `PipelineResult` dataclass: `wave1: Wave1Result`, `wave2: Wave2Result`, `merge: MergeStats`
- `async def full_pipeline(workdir, citations) -> PipelineResult`:
  1. `w1 = await wave1_verify_and_download(workdir, citations)`
  2. `w2 = await wave2_fallback_and_download(workdir, citations, w1.miss_indices)`
  3. `m = merge_claims(workdir)`
  4. Return `PipelineResult(w1, w2, m)`

Add CLI subcommand to `__main__.py`:
- `python -m citation_verifier verify-brief <workdir> [--wave1 | --wave2 | --merge | --full]`
- `--wave1`: reads `citations_to_verify.txt` from workdir, runs wave1, prints stats
- `--wave2`: reads wave1 results to find misses, runs wave2, prints stats
- `--merge`: merges claims.csv with verification_results.csv, prints stats
- `--full` (default): runs all three sequentially

**Step 4: Run tests**

Run: `pytest tests/test_brief_pipeline.py -v && python -m citation_verifier verify-brief --help`
Expected: All pass, help text shows subcommand.

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py src/citation_verifier/__main__.py tests/test_brief_pipeline.py
git commit -m "feat: add full_pipeline() and verify-brief CLI subcommand"
```

---

### Task 7: Rewrite the skill

**Files:**
- Modify: `.claude/skills/verify-brief/SKILL.md`

**Step 1: Read the current skill**

Read `.claude/skills/verify-brief/SKILL.md` to understand current structure.

**Step 2: Rewrite**

Replace the entire skill with the revised version. Key changes:

- **Phase 1a (Haiku):** Extract citation list. Prompt specifies: case citations only, one per line, exclude statutes/treatises/regulations.
- **Phase 1b (pipeline):** Run `python -m citation_verifier verify-brief <workdir> --wave1`
- **Phase 1c (Opus + pipeline concurrent):** Launch two concurrent agents:
  - Opus agent: read brief, extract propositions → `claims.csv` with columns `page,proposition,cited_case`. Instructed to reference citation list from 1a.
  - Background bash: `python -m citation_verifier verify-brief <workdir> --wave2`
  - After both: `python -m citation_verifier verify-brief <workdir> --merge`
- **Phase 2 (Opus subagents):** Assess Wave 1 cases. Structured contract:
  - Input per subagent: opinion file path, list of `{row_index, proposition, cited_case}`
  - Output: JSON array of `{row_index, assessment, supporting_language}`
  - Assessment criteria: Green/Yellow/Red (definitions from current skill)
  - POSSIBLE_MATCH: subagent reads opinion and decides
  - No opinion text: auto-Yellow
  - CRITICAL instruction: Read opinions with Read tool, do NOT grep/script
- **Phase 3 (Opus subagents):** Same as Phase 2 for Wave 2 cases. NOT_FOUND with no opinion → auto-Red.
- **Phase 4:** Always generate report.html + summary. No AskUserQuestion.
- **Resume logic:** based on claims.csv state
- **Remove:** all code snippets, AskUserQuestion, Phase 2.5, verification.json, model recommendation table

**Step 3: Verify skill loads**

Run `/verify-brief --help` or similar to verify the skill is parseable.

**Step 4: Commit**

```bash
git add .claude/skills/verify-brief/SKILL.md
git commit -m "refactor: rewrite verify-brief skill to use pipeline module"
```

---

### Task 8: Integration test with the law-firm EOS appeal brief

**Files:**
- Test manually against `briefs/law-firm-eos-appeal/`

**Step 1: Clean test setup**

```bash
# Back up existing results
cp -r briefs/law-firm-eos-appeal/opinions briefs/law-firm-eos-appeal/opinions.bak
cp briefs/law-firm-eos-appeal/claims.csv briefs/law-firm-eos-appeal/claims.csv.bak
cp briefs/law-firm-eos-appeal/verification_results.csv briefs/law-firm-eos-appeal/verification_results.csv.bak

# Remove generated files to test from scratch
rm -f briefs/law-firm-eos-appeal/verification_results.csv
rm -rf briefs/law-firm-eos-appeal/opinions
```

**Step 2: Test wave1**

```bash
python -m citation_verifier verify-brief briefs/law-firm-eos-appeal --wave1
```

Expected: verification_results.csv created, opinions/ populated with .html/.txt files, stats printed. Should complete in ~2 minutes (batch lookup + downloads).

**Step 3: Test wave2**

```bash
python -m citation_verifier verify-brief briefs/law-firm-eos-appeal --wave2
```

Expected: fallback citations resolved, appended to verification_results.csv, additional opinions downloaded.

**Step 4: Restore claims.csv and test merge**

```bash
cp briefs/law-firm-eos-appeal/claims.csv.bak briefs/law-firm-eos-appeal/claims.csv
python -m citation_verifier verify-brief briefs/law-firm-eos-appeal --merge
```

Expected: claims.csv updated with verification columns, stats show matched/unmatched counts.

**Step 5: Compare results**

Compare verification_results.csv to the .bak to confirm same cases found. Check that HTML files were downloaded where available.

**Step 6: Clean up and commit**

```bash
rm briefs/law-firm-eos-appeal/*.bak
rm -rf briefs/law-firm-eos-appeal/opinions.bak
git add briefs/law-firm-eos-appeal/
git commit -m "test: verify pipeline integration with law-firm EOS appeal"
```

---

### Task 9: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update Architecture section**

Add `brief_pipeline.py` to the files table. Update the verify-brief skill description to mention the pipeline module.

**Step 2: Update the verify_batch documentation**

Ensure it mentions `quick_only=True` for wave1.

**Step 3: Add brief_pipeline to the files table**

| `brief_pipeline.py` | Brief verification pipeline (wave1/wave2/merge, CLI entry point) |

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with brief_pipeline module"
```
