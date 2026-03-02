# verify-brief Skill Iteration 1: Post-Test Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix codebase and skill issues discovered during first test run of `/verify-brief` against the Kettering v. Collier brief.

**Architecture:** Two codebase changes (sync client method, CLI stderr fix) followed by a skill rewrite. The sync `get_opinion_text()` mirrors the existing async version using `requests`. The skill changes are all in one file (`SKILL.md`).

**Tech Stack:** Python 3.10+, requests, aiohttp, pytest

**Feedback file:** `briefs/kettering-v-collier/skill-test-feedback.md`

---

### Task 1: Add sync `get_opinion_text()` to `CourtListenerClient`

**Context:** The async client (`AsyncCourtListenerClient`) has `get_opinion_text()` (line 404) and `get_opinion_text_with_metadata()` (line 417) but the sync client doesn't. During the test run, Claude tried the sync client first and failed. The web app's `/api/download-texts` endpoint (web/app.py:514-613) uses the async version — the sync version will let the skill use simple Python without async boilerplate.

**Files:**
- Modify: `src/citation_verifier/client.py` (add methods after line 205, before `class AsyncCourtListenerClient`)
- Test: `tests/test_client_opinion_text.py` (new)

**Step 1: Write failing tests**

Create `tests/test_client_opinion_text.py` with mocked HTTP responses. Test both opinion URLs and RECAP docket URLs, plus the None/error cases. Pattern from existing tests: mock `_request_with_retry` return values.

```python
"""Tests for CourtListenerClient.get_opinion_text() and get_opinion_text_with_metadata()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from citation_verifier.client import CourtListenerClient


class TestSyncGetOpinionText:
    """Tests for sync get_opinion_text() mirroring the async version."""

    def _make_client(self):
        return CourtListenerClient(api_token="test-token")

    def test_opinion_url_returns_plain_text(self):
        """Opinion URL -> cluster API -> sub_opinions -> opinion API -> plain_text."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            # First call: cluster API
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Obergefell v. Hodges",
                "date_filed": "2015-06-26",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/123/"
                ],
                "citations": [
                    {"volume": "576", "reporter": "U.S.", "page": "644"}
                ],
                "docket": "https://www.courtlistener.com/api/rest/v4/dockets/999/",
            }
            # Second call: opinion API
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "This is the opinion text.",
                "html_with_citations": "",
            }
            # Third call: docket API (for metadata)
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "docket_number": "14-556",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/scotus/",
            }
            # Fourth call: court API
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "Supreme Court of the United States",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp, docket_resp, court_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/opinion/123/obergefell-v-hodges/"
            )
            assert result == "This is the opinion text."

    def test_opinion_url_falls_back_to_html(self):
        """Falls back to stripped html_with_citations when plain_text is empty."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Test Case",
                "date_filed": "2020-01-01",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/456/"
                ],
                "citations": [],
                "docket": "",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "",
                "html_with_citations": "<p>This is <b>HTML</b> content.</p>",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/opinion/456/test-case/"
            )
            assert result is not None
            assert "HTML" in result
            assert "<p>" not in result  # HTML tags stripped

    def test_returns_none_for_empty_url(self):
        client = self._make_client()
        assert client.get_opinion_text("") is None

    def test_returns_none_for_unrecognized_url(self):
        client = self._make_client()
        assert client.get_opinion_text("https://example.com/something") is None

    def test_with_metadata_returns_dict(self):
        """get_opinion_text_with_metadata returns full metadata dict."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            cluster_resp = MagicMock()
            cluster_resp.json.return_value = {
                "case_name": "Obergefell v. Hodges",
                "date_filed": "2015-06-26",
                "sub_opinions": [
                    "https://www.courtlistener.com/api/rest/v4/opinions/123/"
                ],
                "citations": [
                    {"volume": "576", "reporter": "U.S.", "page": "644"}
                ],
                "docket": "https://www.courtlistener.com/api/rest/v4/dockets/999/",
            }
            opinion_resp = MagicMock()
            opinion_resp.json.return_value = {
                "plain_text": "Opinion text here.",
            }
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "docket_number": "14-556",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/scotus/",
            }
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "Supreme Court of the United States",
            }
            mock_req.side_effect = [cluster_resp, opinion_resp, docket_resp, court_resp]

            result = client.get_opinion_text_with_metadata(
                "https://www.courtlistener.com/opinion/123/obergefell-v-hodges/"
            )
            assert result is not None
            assert result["text"] == "Opinion text here."
            assert result["case_name"] == "Obergefell v. Hodges"
            assert result["court"] == "Supreme Court of the United States"
            assert result["date_filed"] == "2015-06-26"
            assert result["docket_number"] == "14-556"
            assert "576 U.S. 644" in result["citations"]

    def test_docket_url_returns_text(self):
        """RECAP docket URL -> docket-entries API -> recap-document -> plain_text."""
        client = self._make_client()
        with patch.object(client, "_request_with_retry") as mock_req:
            entry_resp = MagicMock()
            entry_resp.json.return_value = {
                "results": [
                    {
                        "recap_documents": [
                            {"id": 789, "plain_text": "Docket entry text."}
                        ]
                    }
                ]
            }
            doc_resp = MagicMock()
            doc_resp.json.return_value = {
                "plain_text": "Full document text from RECAP.",
            }
            docket_resp = MagicMock()
            docket_resp.json.return_value = {
                "case_name": "Smith v. Jones",
                "docket_number": "1:20-cv-01234",
                "date_filed": "2020-03-15",
                "court": "https://www.courtlistener.com/api/rest/v4/courts/ohsd/",
            }
            court_resp = MagicMock()
            court_resp.json.return_value = {
                "full_name": "U.S. District Court for the Southern District of Ohio",
            }
            mock_req.side_effect = [entry_resp, doc_resp, docket_resp, court_resp]

            result = client.get_opinion_text(
                "https://www.courtlistener.com/docket/5555/42/smith-v-jones/"
            )
            assert result == "Full document text from RECAP."
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client_opinion_text.py -v`
Expected: AttributeError — `CourtListenerClient` has no `get_opinion_text` method.

**Step 3: Implement sync `get_opinion_text()` and `get_opinion_text_with_metadata()`**

Add to `CourtListenerClient` class in `client.py`, after `get_docket_entries()` (line 204) and before the `AsyncCourtListenerClient` class (line 207). Port the async logic using sync `_request_with_retry` (which returns `requests.Response` — call `.json()` on it).

Key difference from async: `_request_with_retry` returns a `requests.Response` object, so we need `.json()` calls. The async version's `_request_with_retry` already returns parsed JSON.

```python
    def get_opinion_text(self, matched_url: str) -> str | None:
        """Fetch the plain text of an opinion or RECAP document (sync).

        Mirrors AsyncCourtListenerClient.get_opinion_text().
        """
        result = self.get_opinion_text_with_metadata(matched_url)
        return result.get("text") if result else None

    def get_opinion_text_with_metadata(
        self, matched_url: str,
    ) -> dict[str, Any] | None:
        """Fetch opinion text with metadata (sync).

        Returns dict with: text, case_name, court, date_filed,
        docket_number, citations, source_url. Returns None if not found.
        """
        if not matched_url:
            return None

        if "/opinion/" in matched_url:
            return self._resolve_opinion_text_with_metadata(matched_url)

        docket_match = re.search(r"/docket/(\d+)/", matched_url)
        if not docket_match:
            return None

        docket_id = docket_match.group(1)
        docket_entry_match = re.search(r"/docket/\d+/(\d+)/", matched_url)

        try:
            text = None

            if docket_entry_match:
                entry_number = docket_entry_match.group(1)
                resp = self._request_with_retry(
                    "GET",
                    f"{self.BASE_URL}/docket-entries/",
                    params={"docket": docket_id, "entry_number": entry_number},
                )
                entry_data = resp.json()
                for entry in entry_data.get("results", []):
                    for doc in entry.get("recap_documents", []):
                        doc_id = doc.get("id")
                        if not doc_id:
                            continue
                        doc_resp = self._request_with_retry(
                            "GET",
                            f"{self.BASE_URL}/recap-documents/{doc_id}/",
                        )
                        t = doc_resp.json().get("plain_text", "")
                        if t and t.strip():
                            text = t
                            break
                    if text:
                        break

            if not text:
                resp = self._request_with_retry(
                    "GET",
                    f"{self.BASE_URL}/docket-entries/",
                    params={"docket": docket_id, "page_size": "5"},
                )
                entry_data = resp.json()
                for entry in entry_data.get("results", []):
                    for doc in entry.get("recap_documents", []):
                        doc_id = doc.get("id")
                        if not doc_id:
                            continue
                        doc_resp = self._request_with_retry(
                            "GET",
                            f"{self.BASE_URL}/recap-documents/{doc_id}/",
                        )
                        t = doc_resp.json().get("plain_text", "")
                        if t and t.strip():
                            text = t
                            break
                    if text:
                        break

            if not text:
                return None

            docket_resp = self._request_with_retry(
                "GET", f"{self.BASE_URL}/dockets/{docket_id}/",
            )
            docket = docket_resp.json()
            court_url = docket.get("court", "")
            court_name = ""
            if court_url:
                court_id = court_url.rstrip("/").split("/")[-1]
                try:
                    court_data = self._request_with_retry(
                        "GET", f"{self.BASE_URL}/courts/{court_id}/",
                    )
                    court_name = court_data.json().get("full_name", "")
                except Exception:
                    pass

            return {
                "text": text,
                "case_name": docket.get("case_name", ""),
                "court": court_name,
                "date_filed": docket.get("date_filed", ""),
                "docket_number": docket.get("docket_number", ""),
                "citations": [],
                "source_url": matched_url,
            }

        except Exception:
            pass

        return None

    def _resolve_opinion_text_with_metadata(
        self, matched_url: str,
    ) -> dict[str, Any] | None:
        """Resolve an opinion URL to plain text + metadata (sync)."""
        cluster_match = re.search(r"/opinion/(\d+)/", matched_url)
        if not cluster_match:
            return None

        cluster_id = cluster_match.group(1)

        try:
            cluster_resp = self._request_with_retry(
                "GET", f"{self.BASE_URL}/clusters/{cluster_id}/"
            )
            cluster = cluster_resp.json()

            text = None
            for op_url in cluster.get("sub_opinions", []):
                op_id = op_url.rstrip("/").split("/")[-1]
                opinion_resp = self._request_with_retry(
                    "GET", f"{self.BASE_URL}/opinions/{op_id}/"
                )
                opinion = opinion_resp.json()

                t = opinion.get("plain_text", "")
                if t and t.strip():
                    text = t
                    break

                html = opinion.get("html_with_citations", "") or opinion.get("html", "")
                if html:
                    stripped = re.sub(r"<[^>]+>", " ", html)
                    stripped = re.sub(r"\s+", " ", stripped).strip()
                    if stripped:
                        text = stripped
                        break

            if not text:
                return None

            citations = []
            for cite in cluster.get("citations", []):
                if isinstance(cite, str):
                    continue
                if isinstance(cite, dict):
                    vol = cite.get("volume", "")
                    rep = cite.get("reporter", "")
                    pg = cite.get("page", "")
                    if vol and rep and pg:
                        citations.append(f"{vol} {rep} {pg}")

            court_name = ""
            docket_number = ""
            docket_url = cluster.get("docket", "")
            if docket_url:
                docket_id = docket_url.rstrip("/").split("/")[-1]
                try:
                    docket_resp = self._request_with_retry(
                        "GET", f"{self.BASE_URL}/dockets/{docket_id}/",
                    )
                    docket = docket_resp.json()
                    docket_number = docket.get("docket_number", "")
                    court_url = docket.get("court", "")
                    if court_url:
                        court_id = court_url.rstrip("/").split("/")[-1]
                        court_data = self._request_with_retry(
                            "GET", f"{self.BASE_URL}/courts/{court_id}/",
                        )
                        court_name = court_data.json().get("full_name", "")
                except Exception:
                    pass

            return {
                "text": text,
                "case_name": cluster.get("case_name", ""),
                "court": court_name,
                "date_filed": cluster.get("date_filed", ""),
                "docket_number": docket_number,
                "citations": citations,
                "source_url": matched_url,
            }

        except Exception:
            pass

        return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client_opinion_text.py -v`
Expected: All tests PASS.

**Step 5: Run existing tests to verify nothing is broken**

Run: `pytest tests/test_verifier.py tests/test_async_verifier.py -v`
Expected: All 133 tests PASS. We only added new methods — no existing signatures changed.

**Step 6: Commit**

```bash
git add src/citation_verifier/client.py tests/test_client_opinion_text.py
git commit -m "feat: add sync get_opinion_text() to CourtListenerClient

Port async get_opinion_text() and get_opinion_text_with_metadata() to the
sync client using requests. Enables the verify-brief skill to fetch opinion
texts without async boilerplate."
```

---

### Task 2: Send progress messages to stderr when `--json` is used

**Context:** The CLI prints "Verifying 1/20..." to stdout, which corrupts JSON output when `--json` is used. During the test run, Claude had to `grep -v` the progress lines, which mangled the JSON.

**Files:**
- Modify: `src/citation_verifier/__main__.py` (lines 127-154)
- Test: Manual (no existing CLI tests; change is 2 lines)

**Step 1: Fix the progress callback to use stderr in JSON mode**

In `__main__.py`, the progress callback and cache message both print to stdout. When `json_mode` is True, redirect to stderr. Also wrap JSON output in an array so multiple results are valid JSON.

```python
# Change 1: Cache message (line 129) — use stderr in JSON mode
    if cache and len(citations) > len(to_verify) and to_verify:
        msg = (
            f"  Cache: {len(citations) - len(to_verify)} cached, "
            f"{len(to_verify)} to verify"
        )
        print(msg, file=sys.stderr if args.json_mode else sys.stdout)

# Change 2: Progress callback (lines 145-146) — use stderr in JSON mode
        def _progress(done: int, total: int) -> None:
            print(
                f"  Verifying {done}/{total}...",
                file=sys.stderr if args.json_mode else sys.stdout,
                flush=True,
            )
```

**Step 2: Verify manually**

Run: `echo "Obergefell v. Hodges, 576 U.S. 644 (2015)" > /tmp/test_cite.txt && python -m citation_verifier --file /tmp/test_cite.txt --json 2>/dev/null`
Expected: Clean JSON on stdout, progress on stderr only.

**Step 3: Run existing tests**

Run: `pytest tests/test_verifier.py tests/test_async_verifier.py -v`
Expected: All PASS (no tests exercise CLI directly).

**Step 4: Commit**

```bash
git add src/citation_verifier/__main__.py
git commit -m "fix: send CLI progress messages to stderr when --json is used

Progress and cache messages were printing to stdout, corrupting JSON output.
Now uses stderr for status messages when --json flag is active."
```

---

### Task 3: Rewrite verify-brief skill with all fixes

**Context:** Six issues from the test run feedback (`briefs/kettering-v-collier/skill-test-feedback.md`). All changes are in `~/.claude/skills/verify-brief/SKILL.md`.

**Files:**
- Modify: `~/.claude/skills/verify-brief/SKILL.md`

**Changes to make (all in one edit):**

1. **Phase 2 — Use Python API instead of CLI:**
   - Replace "run `python -m citation_verifier --file ... --json`" with a Python code snippet using `CitationVerifier().verify()` in a loop
   - Include exact code: import, instantiate, loop, collect results, write JSON
   - This avoids the stdout corruption issue entirely

2. **Phase 2.5 & 5 — AskUserQuestion reliability fixes:**
   - **Always use single questions** — one AskUserQuestion call per question, never batches
   - **Never call AskUserQuestion in parallel** with other tool calls — it must be the only tool in the response
   - Add defensive callout:
     > **IMPORTANT:** If AskUserQuestion returns without clear answer text (empty string, ".", or "User has answered your questions: ."), do NOT assume defaults. Re-ask the question with simpler phrasing.
   - Simplify question patterns: yes/no or 2-3 option choices, one at a time

3. **Phase 3 — Document correct async pattern (preferred) + sync fallback:**
   - Provide exact async Python snippet as the primary approach — `asyncio.run()` wrapper with `async with AsyncCourtListenerClient() as client:` and `asyncio.gather()` for parallel fetches
   - Also provide sync `CourtListenerClient().get_opinion_text(url)` as a simpler fallback for small case counts
   - Add note: "Async is ~2x faster (0.5s rate limit, overlapping response waits) for 5+ cases. Sync is simpler for 1-4 cases."
   - Borrow the metadata header format from web app's `download_texts` (case name, citations, court, date, docket number, source URL, separator line)

4. **Phase 4 — Explicit Read tool instruction + subagent guidance:**
   - Add bold callout: **"Read each opinion file using the Read tool. Do NOT write Python scripts, grep commands, or keyword searches."**
   - Add parallel subagent guidance: "For briefs with 5+ unique cases, dispatch one Agent subagent per case (or batch of 2-3 cases). Each subagent reads the opinion(s) and assesses propositions independently."
   - Add chunk guidance: "For opinions > 80K characters, read in 2000-line chunks using Read tool's offset/limit parameters."

5. **Model recommendations — Add table after Phases section:**
   ```
   | Phase | Recommended Model | Rationale |
   |-------|-------------------|-----------|
   | 1 (Extract) | Opus | Legal comprehension for proposition extraction |
   | 2 (Verify) | Haiku | Mechanical: run verifier, parse results, update CSV |
   | 2.5 (Review) | Haiku | Present results, collect user input |
   | 3 (Retrieve) | Haiku | Mechanical: API calls, save files |
   | 4 (Assess) | Opus (subagents) | Deep comprehension of opinion text |
   | 5 (Report) | Sonnet | Formatting and summarization |
   ```

6. **Parallelism notes:**
   - Phase 3: "Sequential. CL API 1-second rate limit makes parallelism counterproductive."
   - Phase 4: "Parallelizable via subagents. Each case's opinion(s) can be assessed independently."

**Step 1: Write the updated skill**

Full replacement of `SKILL.md` with all six fixes incorporated. See the skill content below.

**Step 2: Verify skill loads**

Run in Claude Code: `/verify-brief` — confirm it loads without errors and shows the updated phases.

**Step 3: Commit**

```bash
git add ~/.claude/skills/verify-brief/SKILL.md
git commit -m "fix: iterate verify-brief skill based on Kettering test feedback

Phase 2: Use Python API instead of CLI (avoids stdout corruption).
Phase 2.5/5: Handle empty AskUserQuestion responses explicitly.
Phase 3: Use sync get_opinion_text(), sequential with rate limiting.
Phase 4: Explicit Read tool instruction, parallel subagent guidance.
Add model recommendations per phase and parallelism notes."
```

---

## Web App Notes (Borrowing / Future Cleanup)

Code borrowed from web app for this iteration:
- **Metadata header format** (web/app.py:576-593): case name, citations, court, date filed, docket number, source URL, separator — used in Phase 3 skill instructions
- **Filename sanitization pattern** (web/app.py:379-387): referenced in Phase 3 slug generation

Future cleanup candidates (not in this iteration):
- `web/app.py:875-924` (`qc_opinion_text`): Hand-rolls opinion text fetching. Could be replaced with `CourtListenerClient.get_opinion_text_with_metadata()` (now available on sync client)
- `web/app.py:514-613` (`download_texts`): Uses async client to fetch + zip texts. The core fetch logic is now also in the sync client

---

## Verification Checklist

After all three tasks:

1. `pytest tests/test_client_opinion_text.py -v` — new tests pass
2. `pytest tests/test_verifier.py tests/test_async_verifier.py -v` — 133 existing tests still pass
3. `python -m citation_verifier --file /tmp/test.txt --json 2>/dev/null` — clean JSON output
4. Web app unaffected — we only ADDED methods to the sync client, changed no signatures, modified no web app files
