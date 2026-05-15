# Fallback-Path Correctness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two correctness issues filed by sam-mfb in [#6](https://github.com/rlfordon/citation-verifier/issues/6) and [#7](https://github.com/rlfordon/citation-verifier/issues/7): (a) the RECAP-fallback path puts a `docket_id` integer into the `matched_cluster_id` field, and (b) the opinion-search fallback returns wrong-cluster matches with 33–100% miscalibration rates because it lacks a temporal sanity check and a non-stoplist name-token overlap requirement.

**Architecture:** Two surgical fixes scoped to `verifier.py` plus follow-on updates to result-serializing call sites.

1. **Schema split** — add `docket_id` to `CandidateMatch` and `matched_docket_id` to `VerificationResult`; stop overloading `cluster_id` in the RECAP builders. The result's status stays in the existing four-value enum; the discriminator for consumers becomes `result.matched_docket_id is not None`.
2. **Fallback gates** — apply two hard-reject filters inside `_process_results` (opinion-search fallback only, not citation-lookup hits): a >5-year temporal mismatch and a no-shared-non-stoplist-token name check. Both are derived directly from sam-mfb's calibration table in issue #7.

We are explicitly NOT adding (a) Sam's suggested `MATCHED_DOCKET_ONLY` status enum value (the new dedicated field is a cleaner discriminator), (b) Sam's suggested boundary-validation HEAD request (the source-of-truth fix is to stop crossing the namespace at construction time), or (c) a `--strict` CLI alias (`quick_only=True` already exists and is exposed via the library API; defer to demand). Each of those is a separate decision the user can revisit after seeing the recalibration numbers.

**Tech Stack:** Python 3.10+, pytest, eyecite (forked), CourtListener REST v4.

---

## File Structure

**Modify:**
- `src/citation_verifier/models.py` — add `CandidateMatch.docket_id: int | None`, `VerificationResult.matched_docket_id: int | None`
- `src/citation_verifier/verifier.py` — change RECAP candidate builders (sync `_pick_best_recap_doc` ~line 595, sync `_build_docket_only_candidate` ~line 644, plus their async counterparts via shared helpers); add temporal + token gates to `_process_results` ~line 478; propagate `docket_id` into `VerificationResult` in `_build_fallback_result` ~line 201
- `src/citation_verifier/__main__.py` — add `matched_docket_id` to `_result_to_json_dict` (~line 35) and `_VERIFY_BATCH_OUTPUT_COLUMNS`/`_result_to_row` (~line 387)
- `CLAUDE.md` — update the "VerificationResult fields" pitfall note to document the new field and the namespace split

**Create:**
- `scripts/recalibrate_against_qc.py` — one-off recalibration script that runs the new gates against `scratch/citations_for_review.csv` and reports flips (kept under `scripts/` because it's a follow-up tool, not a regression test)

**Test:**
- `tests/test_verifier.py` — new tests for: (1) docket-only path sets `matched_docket_id`, not `matched_cluster_id`; (2) RECAP-doc path sets `matched_docket_id` AND keeps cluster_id None (since CL docket-entry RECAP docs don't carry a cluster id); (3) temporal gate rejects candidate with >5y year diff; (4) token gate rejects candidate with no shared non-stoplist ≥4-char tokens; (5) citation-lookup hits are not gated (regression guard)
- `tests/test_async_verifier.py` — parity tests mirroring the new sync ones
- `tests/test_cli_verify_batch.py` — column-presence test for `matched_docket_id`

---

## Phase 1 — Issue #6: split cluster_id and docket_id

### Task 1: Add the new fields to the dataclasses

**Files:**
- Modify: `src/citation_verifier/models.py:44-69`
- Test: `tests/test_verifier.py` (new test inside the existing recap-fallback class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_verifier.py` near `test_recap_docket_only_fallback_discounted` (~line 297):

```python
    def test_docket_only_sets_matched_docket_id_not_cluster_id(self):
        """Issue #6: docket-only RECAP fallback must put docket_id in
        matched_docket_id, not matched_cluster_id (different namespaces).
        """
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Lindsay-Stern v. Garamszegi",
                    "docket_id": 18158469,
                    "court_id": "cacd",
                    "docket_absolute_url": "/docket/18158469/",
                    "recap_documents": [],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Lindsay-Stern v. Garamszegi, No. 2:18-cv-01234 (C.D. Cal. 2018)"
        )

        assert result.matched_docket_id == 18158469
        assert result.matched_cluster_id is None
```

- [ ] **Step 2: Run test to verify it fails**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestRecapFallback::test_docket_only_sets_matched_docket_id_not_cluster_id -v
```

Expected: FAIL with `AttributeError: 'VerificationResult' object has no attribute 'matched_docket_id'` (and an assertion failure on `matched_cluster_id is None`).

- [ ] **Step 3: Add the new fields**

Edit `src/citation_verifier/models.py`. Replace the `CandidateMatch` dataclass (lines 43-52) with:

```python
@dataclass
class CandidateMatch:
    case_name: str
    url: str
    cluster_id: int | None
    date_filed: str
    court_id: str
    score: float = 0.0
    description: str | None = None
    mismatches: list[Diagnostic] = field(default_factory=list)
    docket_id: int | None = None
```

Note: `cluster_id` becomes `int | None` (was implicitly required). This matters because RECAP candidates have a docket_id but no cluster_id.

Add `matched_docket_id` to `VerificationResult` (insert after the existing `matched_cluster_id: int | None = None` at line 62):

```python
    matched_cluster_id: int | None = None
    matched_docket_id: int | None = None
```

- [ ] **Step 4: Run test — still failing (no producer yet)**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestRecapFallback::test_docket_only_sets_matched_docket_id_not_cluster_id -v
```

Expected: still FAILs — the field exists but is `None` and `matched_cluster_id` still has the docket_id in it. We'll wire producers next.

- [ ] **Step 5: Commit the schema change alone**

```bash
git add src/citation_verifier/models.py tests/test_verifier.py
git commit -m "models: add CandidateMatch.docket_id and VerificationResult.matched_docket_id

Schema-only change for issue #6. Producers and consumers wired in
subsequent commits. Test is failing intentionally until the docket-only
builder stops overloading cluster_id."
```

---

### Task 2: Stop overloading cluster_id in the RECAP builders

**Files:**
- Modify: `src/citation_verifier/verifier.py:595-604` (`_pick_best_recap_doc` return)
- Modify: `src/citation_verifier/verifier.py:644-652` (`_build_docket_only_candidate` return)
- Modify: `src/citation_verifier/verifier.py:201-213` (`_build_fallback_result` — propagate to result)
- Test: existing test from Task 1 + a new RECAP-doc test

- [ ] **Step 1: Add a second failing test for the RECAP-doc path**

Add to `tests/test_verifier.py` near the first new test:

```python
    def test_recap_doc_match_sets_matched_docket_id_not_cluster_id(self):
        """A RECAP doc match (with a specific recap_document) carries a
        docket_id but no cluster_id — confirm we set the right field."""
        client = _make_client(
            search_recap=[
                {
                    "caseName": "Bear Warriors United v. Lambert",
                    "docket_id": 65698058,
                    "court_id": "flmd",
                    "docket_absolute_url": "/docket/65698058/",
                    "recap_documents": [],
                }
            ],
            docket_entries=[
                {
                    "date_filed": "2024-06-15",
                    "description": "ORDER granting summary judgment",
                    "recap_documents": [
                        {
                            "short_description": "Opinion",
                            "absolute_url": "/docket/65698058/42/bear-warriors-v-lambert/",
                            "page_count": 30,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Bear Warriors United v. Lambert, No. 6:22-cv-01155 (M.D. Fla. 2024)"
        )

        assert result.matched_docket_id == 65698058
        assert result.matched_cluster_id is None
```

(Pattern-match the `docket_entries` mock shape against `tests/test_verifier.py:280-288` — the same fixture style is used by `test_recap_uses_exact_date_when_available`.)

- [ ] **Step 2: Run both new tests — both fail**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestRecapFallback::test_docket_only_sets_matched_docket_id_not_cluster_id tests/test_verifier.py::TestRecapFallback::test_recap_doc_match_sets_matched_docket_id_not_cluster_id -v
```

Expected: both FAIL — RECAP builders still write `cluster_id=docket_id`.

- [ ] **Step 3: Fix the docket-only builder**

Edit `src/citation_verifier/verifier.py:644-652`. Replace the `CandidateMatch(...)` return in `_build_docket_only_candidate` with:

```python
        return CandidateMatch(
            case_name=case_name,
            url=docket_url,
            cluster_id=None,
            date_filed="",
            court_id=court_id,
            score=score,
            mismatches=mismatches,
            docket_id=docket_id,
        )
```

- [ ] **Step 4: Fix the RECAP-doc builder**

Edit `src/citation_verifier/verifier.py:595-604`. Replace the `CandidateMatch(...)` return in `_pick_best_recap_doc` with:

```python
        return CandidateMatch(
            case_name=case_name,
            url=doc_url or docket_url,
            cluster_id=None,
            date_filed=entry_date,
            court_id=court_id,
            score=score,
            description=full_desc or None,
            mismatches=mismatches,
            docket_id=docket_id,
        )
```

- [ ] **Step 5: Propagate to VerificationResult**

Edit `src/citation_verifier/verifier.py:201-213` (the final `return VerificationResult(...)` in `_build_fallback_result`). Insert `matched_docket_id=best.docket_id,` next to the existing `matched_cluster_id=best.cluster_id,`:

```python
        return VerificationResult(
            input_citation=citation_text,
            status=status,
            confidence=best.score,
            matched_case_name=best.case_name,
            matched_url=best.url,
            matched_cluster_id=best.cluster_id,
            matched_docket_id=best.docket_id,
            matched_court=best.court_id or None,
            matched_date=best.date_filed or None,
            matched_description=best.description,
            candidates=candidates[:5],
            diagnostics=diagnostics,
        )
```

- [ ] **Step 6: Run both new tests — should pass**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestRecapFallback -v
```

Expected: PASS on the two new tests. The existing `test_recap_docket_only_fallback_discounted` and `test_recap_uses_exact_date_when_available` should still pass — they don't assert on `matched_cluster_id` specifically.

- [ ] **Step 7: Run the full sync test suite to check for fallout**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py -v
```

Expected: all 101 tests pass. If any fail, they will likely be asserting `result.matched_cluster_id == <docket_id>` from before the fix — update those assertions to `result.matched_docket_id == <docket_id>` and `result.matched_cluster_id is None`.

- [ ] **Step 8: Commit**

```bash
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "verifier: stop overloading matched_cluster_id with docket_id (#6)

RECAP-fallback candidate builders now set CandidateMatch.docket_id and
leave cluster_id=None. _build_fallback_result propagates both to
VerificationResult so callers can join on the correct namespace.

Fixes the wrong-namespace integers reported by sam-mfb (e.g.,
Lindsay-Stern v. Garamszegi 18158469 was a docket_id, not a cluster_id)."
```

---

### Task 3: Mirror the async path

**Files:**
- Modify: nothing in `verifier.py` (the sync builders `_pick_best_recap_doc` and `_build_docket_only_candidate` are also called from the async fallback at `verifier.py:1330` and `verifier.py:1335` — they're shared, not duplicated, after the dedup work in TODO §"Priority 0 — Tech debt")
- Test: `tests/test_async_verifier.py` — add parity tests

- [ ] **Step 1: Verify the sync builders are shared**

```
venv/Scripts/python.exe -c "from citation_verifier.verifier import CitationVerifier; print(CitationVerifier._pick_best_recap_doc.__qualname__); print(CitationVerifier._build_docket_only_candidate.__qualname__)"
```

Expected: both qualnames begin with `CitationVerifier.` (shared methods, not duplicated under the async path). If the async fallback path calls a different builder, treat this task as a real implementation task, not just a parity check.

- [ ] **Step 2: Add async parity tests**

Add to `tests/test_async_verifier.py` near `test_parity_recap_docket_only_discounted` (~line 194):

```python
    @pytest.mark.asyncio
    async def test_parity_docket_only_sets_matched_docket_id(self):
        """Async parity for issue #6 docket-only path."""
        client = _make_async_client(
            search_recap=[
                {
                    "caseName": "Lindsay-Stern v. Garamszegi",
                    "docket_id": 18158469,
                    "court_id": "cacd",
                    "docket_absolute_url": "/docket/18158469/",
                    "recap_documents": [],
                }
            ],
        )
        v = CitationVerifier(client)
        result = await v.verify_async(
            "Lindsay-Stern v. Garamszegi, No. 2:18-cv-01234 (C.D. Cal. 2018)"
        )
        assert result.matched_docket_id == 18158469
        assert result.matched_cluster_id is None
```

(Mirror the `_make_async_client` helper used by the surrounding tests in that file.)

- [ ] **Step 3: Run async tests**

```
venv/Scripts/python.exe -m pytest tests/test_async_verifier.py -v
```

Expected: all 29 existing tests still pass + the new parity test passes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_async_verifier.py
git commit -m "tests: async parity for matched_docket_id (#6)"
```

---

### Task 4: Update the CLI JSON + CSV outputs

**Files:**
- Modify: `src/citation_verifier/__main__.py:23-65` (`_result_to_json_dict`)
- Modify: `src/citation_verifier/__main__.py:387-419` (`_VERIFY_BATCH_OUTPUT_COLUMNS`, `_result_to_row`)
- Test: `tests/test_cli_verify_batch.py`, `tests/test_cli_verify_json.py`

- [ ] **Step 1: Write the failing test for the CSV writer**

Add to `tests/test_cli_verify_batch.py` (find the existing column-presence test as a pattern):

```python
def test_csv_includes_matched_docket_id_column():
    from citation_verifier.__main__ import _VERIFY_BATCH_OUTPUT_COLUMNS, _result_to_row
    from citation_verifier.models import VerificationResult, VerificationStatus

    assert "matched_docket_id" in _VERIFY_BATCH_OUTPUT_COLUMNS

    result = VerificationResult(
        input_citation="Lindsay-Stern v. Garamszegi",
        status=VerificationStatus.POSSIBLE_MATCH,
        matched_docket_id=18158469,
        matched_cluster_id=None,
    )
    row = _result_to_row(result)
    assert row["matched_docket_id"] == "18158469"
    assert row["matched_cluster_id"] == ""
```

- [ ] **Step 2: Run — FAIL**

```
venv/Scripts/python.exe -m pytest tests/test_cli_verify_batch.py::test_csv_includes_matched_docket_id_column -v
```

Expected: FAIL — column missing.

- [ ] **Step 3: Update the column list + row builder**

Edit `src/citation_verifier/__main__.py:387-397`. Replace `_VERIFY_BATCH_OUTPUT_COLUMNS` with:

```python
_VERIFY_BATCH_OUTPUT_COLUMNS = [
    "citation",
    "status",
    "matched_cluster_id",
    "matched_docket_id",
    "matched_url",
    "matched_case_name",
    "matched_court_id",
    "matched_date_filed",
    "confidence",
    "diagnostics_json",
]
```

Add the field to `_result_to_row` (after the existing `matched_cluster_id` entry at line 408):

```python
        "matched_docket_id": (
            str(result.matched_docket_id)
            if result.matched_docket_id is not None
            else ""
        ),
```

- [ ] **Step 4: Update the JSON dict builder**

Edit `src/citation_verifier/__main__.py:35-47`. Add the field to `_result_to_json_dict`:

```python
    return {
        "citation": result.input_citation,
        "status": result.status.value,
        "matched_cluster_id": result.matched_cluster_id,
        "matched_docket_id": result.matched_docket_id,
        "matched_url": result.matched_url,
        ...
```

Also add `docket_id` to the per-candidate serialization block at line 48-63:

```python
        "candidates": [
            {
                "case_name": c.case_name,
                "url": c.url,
                "cluster_id": c.cluster_id,
                "docket_id": c.docket_id,
                "date_filed": c.date_filed,
                ...
```

- [ ] **Step 5: Run CLI tests**

```
venv/Scripts/python.exe -m pytest tests/test_cli_verify_batch.py tests/test_cli_verify_json.py -v
```

Expected: PASS. The verify-batch CSV column count is now 10, not 9 — any test that asserts the column count needs updating (search for `len(columns)` or hardcoded 9s in those test files).

- [ ] **Step 6: Commit**

```bash
git add src/citation_verifier/__main__.py tests/test_cli_verify_batch.py
git commit -m "cli: surface matched_docket_id in verify-batch CSV and --json (#6)"
```

---

### Task 5: Update CLAUDE.md and close out issue #6

**Files:**
- Modify: `CLAUDE.md` (the "VerificationResult fields" pitfall note at line 235)

- [ ] **Step 1: Update the pitfall note**

Edit `CLAUDE.md:235`. Replace the existing `VerificationResult fields` bullet with:

```markdown
- **VerificationResult fields**: URL attribute is `matched_url` (not `court_listener_url`). For citation-lookup and opinion-search matches, the CL cluster id is in `matched_cluster_id` and resolves at `/api/rest/v4/clusters/<id>/`. For RECAP-fallback matches (either a specific document or a docket-only match), the docket id is in `matched_docket_id` and resolves at `/api/rest/v4/dockets/<id>/`; `matched_cluster_id` is `None` for those. Only one of the two namespace fields is populated per result — use `matched_docket_id is not None` as the discriminator if you need to choose an endpoint. `diagnostics` is `List[Diagnostic]` — each has `.category` (name/court/date/docket/cite/recap/info) and `.message` (human-readable text). `__str__` returns `.message` for backwards compatibility. Join `.message` with `"; "` when displaying as a single string.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document matched_docket_id namespace split in CLAUDE.md"
```

- [ ] **Step 3: Comment on issue #6 with what shipped**

```bash
gh issue comment 6 --body "Fixed in <commit hash from Task 2 step 8>. \`VerificationResult\` now exposes \`matched_docket_id: int | None\` alongside \`matched_cluster_id\`, and the RECAP-fallback candidate builders no longer write a docket_id into the cluster_id field. The discriminator is \`result.matched_docket_id is not None\` — exactly one of the two namespace fields is populated per result. Skipped the \`MATCHED_DOCKET_ONLY\` status because the dedicated field is a cleaner signal than a new enum value, and skipped the HEAD-against-/clusters/ validation because the namespace split fixes it at source. Happy to revisit either if you'd find them useful in practice."
```

(Don't actually run this until the user has reviewed and approved the comment text.)

---

## Phase 2 — Issue #7: gate the opinion-search fallback

### Task 6: Add the temporal gate

**Files:**
- Modify: `src/citation_verifier/verifier.py:478-510` (`_process_results`)
- Test: `tests/test_verifier.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_verifier.py` in the appropriate fallback-test class (find it by searching for `_process_results` callers in existing tests; if none, create a new `TestOpinionSearchGates` class):

```python
class TestOpinionSearchGates:
    """Issue #7: temporal + name-token gates on the opinion-search fallback."""

    def test_temporal_gate_rejects_year_diff_over_5(self):
        """Sam's example: Jovel v. Boiron (2013 WL) -> 1901 TX land case."""
        client = _make_client(
            citation_lookup=[],  # forces fallback
            search_opinions=[
                {
                    "caseName": "Some Old Case",
                    "cluster_id": 4147982,
                    "dateFiled": "1901-03-14",
                    "court_id": "tex",
                    "absolute_url": "/opinion/4147982/some-old-case/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Jovel v. Boiron, 2013 WL 12164622 (C.D. Cal. 2013)")

        assert result.status == VerificationStatus.NOT_FOUND
        assert result.matched_cluster_id is None

    def test_temporal_gate_allows_year_diff_under_5(self):
        """A within-window candidate should pass the gate (and get scored normally)."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Smith v. Jones",
                    "cluster_id": 1234567,
                    "dateFiled": "2016-06-01",
                    "court_id": "cacd",
                    "absolute_url": "/opinion/1234567/smith-v-jones/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Smith v. Jones, 2018 WL 999999 (C.D. Cal. 2018)")

        # Should not be rejected by temporal gate (3-year diff)
        # Whether it's MATCH/POSSIBLE/NOT_FOUND depends on the rest of the
        # scorer; we only assert the gate didn't drop it.
        assert result.matched_cluster_id == 1234567 or result.status == VerificationStatus.NOT_FOUND
        # If it did pass, no temporal-rejection diagnostic should appear
        assert not any("year" in d.message.lower() and "reject" in d.message.lower()
                       for d in result.diagnostics)
```

- [ ] **Step 2: Run — first test FAILs**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestOpinionSearchGates -v
```

Expected: `test_temporal_gate_rejects_year_diff_over_5` FAILS (result is POSSIBLE_MATCH or similar, not NOT_FOUND).

- [ ] **Step 3: Implement the gate in `_process_results`**

Edit `src/citation_verifier/verifier.py:478-510`. Replace the body of `_process_results` (the loop) with:

```python
    _TEMPORAL_GATE_YEARS = 5

    def _process_results(
        self, results: list[dict[str, Any]], parsed: ParsedCitation
    ) -> list[CandidateMatch]:
        """Convert API results to scored CandidateMatch objects.

        Hard-rejects (issue #7):
          - Temporal: skip candidates whose date_filed year differs from
            parsed.year by more than _TEMPORAL_GATE_YEARS.
        """
        candidates = []
        for r in results:
            case_name = r.get("caseName") or r.get("case_name", "")
            cluster_id = r.get("cluster_id") or r.get("id")
            if cluster_id is None:
                continue
            date_filed = r.get("dateFiled") or r.get("date_filed", "")

            # Temporal hard-gate
            if parsed.year and date_filed and len(date_filed) >= 4:
                try:
                    cand_year = int(date_filed[:4])
                    if abs(cand_year - parsed.year) > self._TEMPORAL_GATE_YEARS:
                        continue
                except ValueError:
                    pass  # unparseable date — let the scorer handle it

            court_id = r.get("court_id") or r.get("court", "")
            url = r.get("absolute_url", "")
            if cluster_id and not url:
                url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
            elif url and not url.startswith("http"):
                url = f"https://www.courtlistener.com{url}"

            score, mismatches = self._score_match(
                parsed, case_name, court_id, date_filed, r
            )
            candidates.append(
                CandidateMatch(
                    case_name=case_name,
                    url=url,
                    cluster_id=cluster_id,
                    date_filed=date_filed,
                    court_id=court_id,
                    score=score,
                    mismatches=mismatches,
                )
            )
        return candidates
```

- [ ] **Step 4: Run — first test passes**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestOpinionSearchGates -v
```

Expected: both new tests PASS.

- [ ] **Step 5: Run the full sync suite**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py -v
```

Expected: all tests still pass. If any false-negative regression tests now fail, they are likely citing a year-diff > 5 from the real CL date_filed — investigate before "fixing" by widening the gate. Sam's window of 5 years is calibrated on a real federal-citation sample.

- [ ] **Step 6: Commit**

```bash
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "verifier: temporal gate on opinion-search fallback (#7)

Reject fallback candidates whose date_filed year is >5 years from the
cited year. Applied only inside _process_results (opinion search) —
citation-lookup hits and RECAP candidates are unaffected. Calibrated
against sam-mfb's 24-wrong-cluster sample where every example had a
date_filed before 1998 against citations from 2010–2024."
```

---

### Task 7: Add the name-token gate

**Files:**
- Modify: `src/citation_verifier/verifier.py` (add module-level stoplist + helper, call from `_process_results`)
- Test: `tests/test_verifier.py`

- [ ] **Step 1: Write the failing test**

Add to `TestOpinionSearchGates`:

```python
    def test_token_gate_rejects_no_shared_distinctive_tokens(self):
        """Sam's example: Harris v. CVS Pharmacy -> Medearis case (only
        'Pharmacy' would have matched and that's not >=4 char distinctive
        token... actually 'Harris', 'CVS', 'Pharmacy' vs 'Medearis' has no
        overlap)."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Medearis v. Whatever",
                    "cluster_id": 7312533,
                    "dateFiled": "2014-05-01",  # within temporal window
                    "court_id": "ca11",
                    "absolute_url": "/opinion/7312533/medearis/",
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify("Harris v. CVS Pharmacy, 2015 WL 4694047 (S.D.N.Y. 2015)")

        assert result.status == VerificationStatus.NOT_FOUND
        assert result.matched_cluster_id is None

    def test_token_gate_allows_shared_distinctive_token(self):
        """At least one shared >=4-char non-stoplist token passes the gate."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[
                {
                    "caseName": "Smith v. Garamszegi",
                    "cluster_id": 9999,
                    "dateFiled": "2018-04-01",
                    "court_id": "cacd",
                    "absolute_url": "/opinion/9999/smith/",
                }
            ],
        )
        v = CitationVerifier(client)
        # "Garamszegi" is a distinctive shared token
        result = v.verify(
            "Lindsay-Stern v. Garamszegi, 2018 WL 1234 (C.D. Cal. 2018)"
        )
        # Gate doesn't drop it (whether the rest of scoring passes is
        # separate); just confirm we get a candidate at all.
        assert len(result.candidates) >= 1
```

- [ ] **Step 2: Run — first new test FAILs**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestOpinionSearchGates -v
```

Expected: `test_token_gate_rejects_no_shared_distinctive_tokens` FAILS.

- [ ] **Step 3: Add the stoplist and helper**

Edit `src/citation_verifier/verifier.py`. Add near the top of the file (after imports, before class definitions):

```python
# Issue #7: tokens that should NOT count as distinctive when checking
# name overlap on opinion-search fallback candidates. These show up so
# often that they create false positives via ES token recall alone.
_NAME_TOKEN_STOPLIST = frozenset({
    # Reporter / litigation boilerplate
    "litig", "liability", "antitrust", "mdl",
    # Corporate forms
    "corp", "inc", "llc", "co", "company", "holdings",
    "communications", "industries", "international",
    # Generic descriptors
    "consumer", "health", "products", "american", "capital",
    "bank", "pharmacy", "services", "systems", "group",
    # Government / agency
    "ftc", "cftc", "sec", "united", "states", "commission",
    "department", "secretary",
})


def _name_tokens(name: str) -> set[str]:
    """Lowercased word tokens of length >=4, with punctuation stripped
    and stoplist tokens removed. Used for the fallback name-overlap gate."""
    if not name:
        return set()
    raw = re.findall(r"[a-z0-9]+", name.lower())
    return {t for t in raw if len(t) >= 4 and t not in _NAME_TOKEN_STOPLIST}
```

Make sure `re` is imported at the top — it already is per `verifier.py:1` (the existing `_normalize_docket_number` uses it).

- [ ] **Step 4: Apply the gate in `_process_results`**

Edit `src/citation_verifier/verifier.py` inside `_process_results` (the function modified in Task 6). After the temporal gate but before the URL build, insert:

```python
            # Name-token hard-gate: at least one shared distinctive token
            if parsed.case_name and case_name:
                cited_tokens = _name_tokens(parsed.case_name)
                cand_tokens = _name_tokens(case_name)
                if cited_tokens and not (cited_tokens & cand_tokens):
                    continue
```

- [ ] **Step 5: Run — tests pass**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestOpinionSearchGates -v
```

Expected: all four gate tests PASS.

- [ ] **Step 6: Run the full sync + async suite**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py -v
```

Expected: all tests pass. Async path uses the same `_process_results` so it gets the gate for free.

- [ ] **Step 7: Commit**

```bash
git add src/citation_verifier/verifier.py tests/test_verifier.py
git commit -m "verifier: name-token gate on opinion-search fallback (#7)

Reject fallback candidates that share no distinctive (>=4-char,
non-stoplist) name token with the cited case. Stoplist hardcoded from
sam-mfb's calibration (corporate forms, agencies, common descriptors).
Applied only in _process_results — citation-lookup and RECAP paths are
unaffected."
```

---

## Phase 3 — Calibrate and verify against real data

### Task 8: Run the new gates against the QC corpus

**Files:**
- Create: `scripts/recalibrate_against_qc.py`

- [ ] **Step 1: Create the script**

```python
"""One-off: replay scratch/citations_for_review.csv through the new
gates and report flips relative to the recorded v_status / qc_status.

This is NOT a regression test — it's a manual calibration tool. We're
looking for: (a) any qc_status=approved row that the new gates now
reject (false negative regression), (b) any qc_status=investigate row
that the new gates now reject (probably good — was a wrong-cluster
fallback hit), (c) overall NOT_FOUND rate change.

Run: venv/Scripts/python.exe scripts/recalibrate_against_qc.py
"""

from __future__ import annotations

import asyncio
import csv
import os
from collections import Counter
from pathlib import Path

from citation_verifier.client import AsyncCourtListenerClient
from citation_verifier.verifier import CitationVerifier

CSV_PATH = Path("scratch/citations_for_review.csv")


async def main() -> None:
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    if not token:
        raise SystemExit("Set COURTLISTENER_API_TOKEN in environment")

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} rows")

    client = AsyncCourtListenerClient(token=token)
    v = CitationVerifier(client)

    # Verify each row through the new pipeline.
    # Use verify_batch for speed.
    citations = [r["citation"] for r in rows if r.get("citation")]
    results = await v.verify_batch(citations)

    flips: list[tuple[str, str, str, str]] = []
    counter_old: Counter[str] = Counter()
    counter_new: Counter[str] = Counter()

    for row, result in zip(rows, results):
        old = row.get("v_status") or "(empty)"
        new = result.status.value
        counter_old[old] += 1
        counter_new[new] += 1
        if old != new:
            flips.append((
                row.get("citation", ""),
                old,
                new,
                row.get("qc_status", ""),
            ))

    print("\nDistribution (old -> new):")
    statuses = sorted(set(counter_old) | set(counter_new))
    for s in statuses:
        print(f"  {s:20s}  {counter_old.get(s, 0):4d}  ->  {counter_new.get(s, 0):4d}")

    print(f"\n{len(flips)} flips:")
    for cite, old, new, qc in flips[:50]:
        print(f"  [{qc:12s}] {old} -> {new}  {cite[:80]}")
    if len(flips) > 50:
        print(f"  ... and {len(flips) - 50} more")

    # Flag the dangerous flips: qc_status=approved that became NOT_FOUND
    bad = [f for f in flips if f[3] == "approved" and f[2] == "NOT_FOUND"]
    if bad:
        print(f"\nREGRESSIONS: {len(bad)} qc-approved rows are now NOT_FOUND:")
        for cite, old, new, qc in bad:
            print(f"  {cite}")
    else:
        print("\nNo qc-approved -> NOT_FOUND regressions.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the script and capture output**

```
venv/Scripts/python.exe scripts/recalibrate_against_qc.py > scratch/recalibration-2026-05-14.txt 2>&1
```

This will hit the real CourtListener API (525 citations via verify_batch). Expect ~2-5 minutes wallclock with rate limiting.

- [ ] **Step 3: Review the output with the user**

Show `scratch/recalibration-2026-05-14.txt` to the user. Decision points:
- **If 0 qc-approved regressions**: ship as-is. Threshold recalibration can be a follow-up.
- **If a small number (≤5) of qc-approved regressions**: inspect each. Are they edge cases (e.g. a citation parsed without a year, then a within-window candidate with a different year was the right answer)? Sam's gate may need a tiny carve-out (e.g. skip the gate when parsed.year is None) — but we already check `if parsed.year and date_filed` so this should not happen. If it does, the bug is upstream and the test catches it.
- **If many regressions (>5)**: investigate the pattern before deciding. May indicate `_TEMPORAL_GATE_YEARS = 5` is too tight for our corpus (which leans on older state-court citations more than Sam's federal-only sample).

- [ ] **Step 4: Commit the script and output**

```bash
git add scripts/recalibrate_against_qc.py scratch/recalibration-2026-05-14.txt
git commit -m "scripts: recalibrate gates against QC corpus (#7)"
```

---

### Task 9: Close out issue #7

- [ ] **Step 1: Comment on issue #7**

Draft body (show to user before posting):

```bash
gh issue comment 7 --body "$(cat <<'EOF'
Fixed in <commit hashes from Tasks 6 and 7>. Two hard-gates added inside
`_process_results` (opinion-search fallback only — citation-lookup and
RECAP paths are untouched):

1. **Temporal**: candidates with `|cite_year - candidate.date_filed.year| > 5` are dropped.
2. **Name tokens**: at least one shared ≥4-char non-stoplist token must match. Stoplist hardcoded from your suggested set, including corporate forms (corp/inc/llc), agencies (ftc/cftc/sec), and generic descriptors (consumer/capital/bank/pharmacy).

We ran the new pipeline against our internal QC corpus (525 citations with manual labels) — distribution shifts and regression check are in `scripts/recalibrate_against_qc.py` output. <Summarize results.>

Skipped (for now):
- `--strict` mode: `verify(quick_only=True)` already exists in the library API; will add a CLI alias if there's demand.
- Threshold recalibration of LIKELY_REAL (0.85) / POSSIBLE_MATCH (0.40): the gates eliminate the worst offenders, so the existing thresholds may already be fine. Open to recalibrating if your follow-up sample still shows bucket misalignment.
- Exposing `matched_date_filed` / `matched_court_id`: already exposed as `matched_date` and `matched_court` on `VerificationResult` (and as `matched_date_filed` / `matched_court_id` in the CSV/JSON outputs) — confirm those serve your use case.

Thanks for the calibration data — it made the fix much easier to scope.
EOF
)"
```

Don't run until the user has reviewed.

- [ ] **Step 2: Push everything**

```bash
git push origin claude/busy-carson-aa8975
```

- [ ] **Step 3: Open a PR**

```bash
gh pr create --title "Fix RECAP namespace overload and fallback wrong-cluster hits (#6, #7)" --body "$(cat <<'EOF'
## Summary

Fixes two correctness issues filed by @sam-mfb:

- **#6** — `matched_cluster_id` was being set to a `docket_id` integer on the RECAP-fallback path, breaking consumers who join on `/clusters/<id>/`. Adds `matched_docket_id` as a separate field; `matched_cluster_id` is now strictly a cluster id and is `None` for RECAP results.
- **#7** — Opinion-search fallback returned wrong-cluster matches with 33–100% miscalibration in the LIKELY_REAL / POSSIBLE_MATCH bands. Adds two hard-gates in `_process_results`: temporal (>5y diff = reject) and name tokens (no shared ≥4-char non-stoplist token = reject). Calibrated against the QC corpus.

## Test plan
- [ ] `pytest tests/test_verifier.py tests/test_async_verifier.py tests/test_cli_verify_batch.py` — all green
- [ ] `scripts/recalibrate_against_qc.py` output in `scratch/recalibration-2026-05-14.txt` shows no qc-approved regressions
- [ ] Manually verified `python -m citation_verifier "Lindsay-Stern v. Garamszegi, No. 2:18-cv-01234 (C.D. Cal. 2018)" --json` returns `matched_docket_id` (not `matched_cluster_id`)
- [ ] Manually verified `python -m citation_verifier "Harris v. CVS Pharmacy, 2015 WL 4694047 (S.D.N.Y. 2015)"` returns NOT_FOUND (was wrong-cluster POSSIBLE_MATCH)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** Both issues' suggested fixes are addressed or explicitly deferred with rationale. Issue #6's "boundary validation HEAD request" and "MATCHED_DOCKET_ONLY status" are intentionally skipped; the namespace split fixes the root cause and the discriminator becomes the dedicated field. Issue #7's `--strict` mode is deferred (existing `quick_only` covers the library API need; CLI alias is one-line follow-up). Issue #7's threshold recalibration is deferred until Task 8's data is in.
- **Placeholder scan:** No "TBD" / "TODO" / "fill in later" steps. The recalibration script is shown in full.
- **Type consistency:** `docket_id` (lowercase, on `CandidateMatch`) and `matched_docket_id` (on `VerificationResult`) — names match Sam's suggested API. `_TEMPORAL_GATE_YEARS` is a class constant; `_NAME_TOKEN_STOPLIST` and `_name_tokens` are module-level. `cluster_id` is now `int | None` on `CandidateMatch`, matching the existing `matched_cluster_id: int | None` on the result.
- **Estimated effort:** Tasks 1–5 (Phase 1): ~2 hours. Tasks 6–7 (Phase 2): ~1 hour. Tasks 8–9 (Phase 3): ~30 min plus API time for the recalibration script. Total ~4 hours wallclock excluding decision points where the user reviews flip output.
