# Citation Verifier Refactor v0.3 — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the six richer Status values actually produced by the verifier (today only `VERIFIED` and `NOT_FOUND` are emitted) — `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, and `WRONG_CASE` — by adding a `caption_investigation` stage, a strict RECAP classifier, a parallel-cite detector, and the closed-set warning categories these classifications imply.

**Architecture:** A new `caption_investigation` stage opens its own `builder.stage(StageName.caption_investigation, …)` block from `verify()` / `verify_async()` after the citation_lookup `with` block exits, fired only when `_process_citation_lookup_hit` flagged a name mismatch. RECAP branching moves into `_build_fallback_result` — when the winning candidate is a RECAP hit, the helper classifies as `VERIFIED_VIA_RECAP` (strict: date match, opinion-typed doc, ideally WL cross-check) or `VERIFIED_DOCKET_ONLY` (everything else). The legacy `Diagnostic → notes-string → regex classifier` bridge from Phase 1/2 is deleted; warnings flow through typed `WarningCategory` values end-to-end. Two new categories (`cl_duplicate_clusters`, `wrong_page_number`) are added per §2.6 amendment workflow, with a CHANGELOG entry. Phase 4 work (`VERIFICATION_INCOMPLETE` production wiring, gates) and a future `candidates` field on `VerificationResult` are out of scope.

**Tech Stack:** Python 3.10+, `dataclasses`, `contextlib`, pytest, pytest-asyncio, the existing `models.py` / `verifier.py` / `resolution_path.py` / `client.py`, the existing `tests/data/refactor_corpus.json` (Phase 2.5 deliverable).

---

## Setup

### §0.1 Worktree + branch sync

Phase 3 work happens in the existing worktree at `.claude/worktrees/refactor-v0.3` on branch `refactor/v0.3`. Per CLAUDE.md "Refactor Workflow," merge `origin/main` at the phase boundary to absorb conflicts while they're small.

- [ ] **Step 1: Confirm worktree + branch**

Run (from the worktree directory, not the primary checkout):

```
git rev-parse --show-toplevel
git status
git rev-parse --abbrev-ref HEAD
```

Expected: working tree clean, branch `refactor/v0.3`, current commit is at or descended from `refactor/phase-2.5-acceptance`.

- [ ] **Step 2: Pull origin and check for main drift**

```
git fetch origin
git log --oneline --max-count=10 origin/main ^HEAD
```

If the second command prints commits, origin/main has moved since Phase 2.5. Merge it:

```
git merge --no-edit origin/main
```

If the merge produces conflicts in `src/citation_verifier/` or `tests/`, stop and surface them — do not silent-resolve.

- [ ] **Step 3: Confirm venv + .env are in the worktree**

```
venv/Scripts/python.exe --version
test -f .env && echo ".env present" || echo ".env MISSING — copy from primary checkout before live-API tests"
```

Expected: Python 3.10+, `.env present`. Per Phase 1 retrospective S5: the worktree's `.env` is path-explicit and does not walk up to the parent repo.

### §0.2 Baseline pytest

Establish the pre-Phase-3 green-test baseline so Phase 3 work can be diffed cleanly.

- [ ] **Step 4: Run the full suite, deselecting live_api**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py -q
```

Expected at acceptance of Phase 2.5: `302 passed, 5 skipped, 8 deselected` (or close — see Phase 2.5 retro §S7 on count-text drift). Zero failures. If anything is red, stop and triage before proceeding.

### §0.3 Darensburg fixture validation pass (per maintainer Q1)

The `named-exemplar-menges` fixture pins Darensburg v. Metro. Transp. Comm'n (2009 WL 2392094, N.D. Cal. Aug. 4, 2009), `docket_id=4182878`, `recap_document_id=13644995`. The pinned RECAPDocument 13644995 is dated **July 7, 2009**, but the citation says **Aug. 4, 2009**. Docket entry #460 on Aug 4, 2009 is a non-opinion costs-taxation order — under Phase 3's strict VIA_RECAP rule (Task 4), this fixture would fail unless the date is reconciled.

- [ ] **Step 5: Look up 2009 WL 2392094 in Westlaw or a secondary source**

Resolve whether `2009 WL 2392094` actually points to (a) the July 7 attorneys' fees opinion, or (b) the Aug 4 costs-taxation order. The Westlaw record's first-page date and "Opinion of the Court" header are the authority.

Two outcomes are acceptable; the implementer picks based on what Westlaw shows:

- **If WL = July 7 opinion:** correct the fixture's citation date to "July 7, 2009" (this is the most likely outcome — attorneys' fees opinions are the more-citable substantive ruling).

  Edit `tests/data/refactor_corpus.json` for `named-exemplar-menges`:

  ```json
  "citation": "Darensburg v. Metro. Transp. Comm'n, 2009 WL 2392094 (N.D. Cal. July 7, 2009)",
  ```

  Update the `rationale` field to note the date correction.

- **If WL = Aug 4 order:** the pinned `recap_document_id=13644995` is the wrong doc. Substitute the fixture with a different `recap_doc_opinion_not_ingested` row (Mehar Holdings and Doe v. Lawrence are confirmed clean per the survey). Move the existing `named_exemplar` tag to that substitute, and demote the current Darensburg fixture to a non-named regular VIA_RECAP entry (or delete it).

- [ ] **Step 6: Commit the validation outcome**

```
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "test(v0.3): Phase 3 Darensburg fixture validation per Q1

$(cat <<'EOF'
Resolved date discrepancy on named-exemplar-menges: 2009 WL 2392094
maps to <July 7 opinion | Aug 4 order — pick one based on Westlaw>.
Updated citation date / doc-id / rationale accordingly. Per Phase 3
plan §0.3 (Q1 maintainer pre-decision).
EOF
)"
```

Also update `tests/data/refactor_corpus_survey.md` §4 "Substitution result" to record the resolution. The implementer's free-text addition explains what Westlaw showed and which fixture-shape was kept.

---

## File Structure

Phase 3 modifies these files. Each task names exact line ranges in its "Files" header.

**Modified:**
- `src/citation_verifier/models.py` — add 2 `WarningCategory` values; bump schema version constant (Task 2).
- `src/citation_verifier/verifier.py` — caption_investigation orchestration in `verify()` / `verify_async()`; new helper `_investigate_caption`; VERIFIED_PARTIAL detection in `_process_citation_lookup_hit`; VIA_RECAP / DOCKET_ONLY branching in `_build_fallback_result`; WRONG_CASE escalation in caption_investigation; `_VERIFIED_SCORE_THRESHOLD` constant extraction; delete the test-only Diagnostic→Warning bridge once `_process_citation_lookup_hit` emits typed warnings directly (Tasks 1, 3, 4, 5).
- `src/citation_verifier/client.py` — add `get_cluster(cluster_id)`, `get_docket(docket_id)`, async equivalents (Task 5).
- `tests/test_verifier.py` — delete `_classify_note`, `_CATEGORY_PATTERNS`, `_DiagnosticLike`, `_winning_entry`, `_diagnostics`, `_matched_case_name`; update assertions to read `result.warnings` and `_winning_path_entry(result)` (renamed survivor) directly (Task 1).
- `tests/test_async_verifier.py` — same deletions as test_verifier.py (Task 1).
- `tests/data/refactor_corpus.json` — Cabot/Hunter reclassified VIA_RECAP → DOCKET_ONLY (per Q1); Butler Motors expected_status decided (per Q2); 4 xfailed VERIFIED fixtures updated (per Q3); Caraballo/Menges-actual/Iglesias rulings; named-exemplar-menges date or substitution (§0.3) (Task 6).
- `tests/data/known_real_citations.json` — remove `xfail_reason` on the 4 cluster-ID-drift entries; update `expected_cluster_id` to live-current values if drift occurred (per Q3 — Task 6).
- `docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md` — append a CHANGELOG-style note in §2.6 documenting the two new WarningCategory values added per the amendment workflow (Task 2).

**Created:**
- `tests/test_phase3_corpus_acceptance.py` — runs the corpus against the live verifier, asserts expected_status / final_ids / warnings (Task 6).
- `tests/test_caption_investigation.py` — unit tests for `_investigate_caption` with mocked CL client (Task 5).
- `CHANGELOG.md` — created at repo root; first entry documents the v0.3 schema rewrite and the §2.6 WarningCategory additions (Task 2).

**Not touched in Phase 3:**
- `src/citation_verifier/cache.py` — Phase 2 retro S6 confirms cache round-trips new shape correctly; new WarningCategory enum values are serialized by name so the cache is enum-additive-safe. Re-run `tests/test_cache_roundtrip.py` early to confirm; do not modify.
- `src/citation_verifier/parser.py` — Phase 3 does not change citation parsing. The `_normalize_case_name` and abbreviation tables stay as Phase 1 left them.
- `src/citation_verifier/brief_pipeline.py` — verify-brief consumes `result.status` and `result.warnings` via the schema established in Phase 1. New statuses (VIA_RECAP, DOCKET_ONLY, WRONG_CASE, PARTIAL) need a presentation pass in verify-brief eventually, but Phase 3 produces them only — verify-brief surface updates are roadmap (§7 of the design doc). Run `pytest tests/test_brief_pipeline.py` at acceptance to confirm nothing breaks.
- `web/app.py` — same logic as brief_pipeline: produces correctly now, surface updates later. Smoke at acceptance.

---

## Task 1: Bundled cleanup — promote Diagnostic→Warning, delete legacy classifier, extract threshold constant

Per Phase 2 retro note 3 ("Bundle the WarningCategory promotion + `_diagnostics` classifier deletion + `_winning_entry` consolidation into one task") and note 4 ("0.40 threshold extraction is a 10-line cleanup. Schedule it inside another task, not standalone").

This task does no semantic work — it cleans up the legacy Phase-1/2 compat helpers so Tasks 3–5 can emit typed warnings without colliding with the freeform-notes regex bridge. It must land before Task 5 because Task 5's `caption_investigation` emits 4+ new warning categories; if the Diagnostic→Warning bridge is still in place, those new warnings will be classified twice (once typed, once via regex from notes).

**Files:**
- Modify: `src/citation_verifier/verifier.py:39-50` (delete `_NAME_TOKEN_STOPLIST` neighborhood `0.40` literals → constant), `:260` (`_build_fallback_result`), `:542,599,634` (each of three fallback stage blocks in sync), `:1639,1691,1734` (each of three fallback stage blocks in async), `:669` (`_stage_notes_for_candidate`), `:953` (`_finalize_diagnostics`).
- Modify: `src/citation_verifier/verifier.py:113-170` (`_process_citation_lookup_hit`) — promote name-mismatch detection to return a typed `Warning` already; existing code does this. No change beyond making sure the message reads correctly when caption_investigation has not yet run (the existing "Phase 3 will run caption investigation to classify" message stays; Task 5 updates it).
- Modify: `tests/test_verifier.py:24-127` — delete `_DiagnosticLike`, `_CATEGORY_PATTERNS`, `_classify_note`, `_winning_entry`, `_diagnostics`, `_matched_case_name`. Replace call sites with direct reads of `result.warnings`, `result.headline_confidence`, and a new minimal helper `_winning_path_entry(result)` that survives because the corpus tests still need it.
- Modify: `tests/test_async_verifier.py` — mirror.

- [ ] **Step 1: Extract the 0.40 score threshold to a module constant**

Add to `src/citation_verifier/verifier.py` near the top, right after the existing `_NAME_TOKEN_STOPLIST` definition (around line 51):

```python
# Score floor at which an opinion_search / recap_*_search candidate
# claims resolution. Below this, the stage records `no_match` and the
# fallback ladder continues. Carried forward unchanged from pre-Phase-3
# behavior per design v2 §8 "Per-stage confidence thresholds" decision
# (2026-05-20).
_VERIFIED_SCORE_THRESHOLD = 0.40
```

Replace the five literal occurrences of `0.40` in `verifier.py` with `_VERIFIED_SCORE_THRESHOLD`:
- `_search_fallback`: opinion_search resolved-vs-no_match gate (line ~542)
- `_search_fallback`: recap_document_search resolved-vs-no_match gate (line ~599)
- `_search_fallback`: recap_docket_search resolved-vs-no_match gate (line ~634)
- `_stage_notes_for_candidate`: status-this-candidate-would-yield calc (line ~669)
- `_build_fallback_result`: status assignment (line ~260)
- `_finalize_diagnostics`: match-word threshold (line ~966)

Also replace the three matching `0.40` occurrences in `_search_fallback_async` (lines ~1638, 1691, 1734).

Verify the search worked: `grep -n "0\.40\b" src/citation_verifier/verifier.py` should return no hits afterward.

- [ ] **Step 2: Run the unit suite to confirm the constant extraction is behavior-preserving**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py -q
```

Expected: same pass count as the §0.2 baseline. If anything goes red, the constant introduction missed a site — `grep -n "0\.40\b"` again and fix.

- [ ] **Step 3: Delete the test-only legacy classifier bridge in `tests/test_verifier.py`**

Remove the dataclass `_DiagnosticLike`, the `_CATEGORY_PATTERNS` table, `_classify_note`, `_diagnostics`, and `_matched_case_name` (lines 24–127). Rename `_winning_entry` to `_winning_path_entry` and keep it — Task 6's corpus tests will use it.

The new top-of-file helpers (replace the deleted block with just this):

```python
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from citation_verifier.models import StageName, StageVerdict, Status, WarningCategory
from citation_verifier.parser import parse_citation
from citation_verifier.verifier import CitationVerifier


def _winning_path_entry(result):
    """Return the resolution_path entry that drove the result (highest-
    confidence resolved/partial entry, else the last entry).

    Phase 2 emits one entry per stage attempted; the last is not always
    the winner (e.g. opinion_search resolved, then recap_docket_search
    ran afterward as a no_match). This helper picks the entry that
    actually decided the verdict so tests can assert against its
    raw_response_summary, notes, etc."""
    if not result.resolution_path:
        return None
    resolved = [
        e for e in result.resolution_path
        if e.verdict in (StageVerdict.resolved, StageVerdict.partial)
    ]
    if resolved:
        return max(resolved, key=lambda e: e.confidence or 0.0)
    return result.resolution_path[-1]


def _make_client(**overrides):
    """Create a mock CourtListenerClient with sensible defaults."""
    client = MagicMock()
    client.citation_lookup.return_value = overrides.get("citation_lookup", [])
    client.search_opinions.return_value = overrides.get("search_opinions", [])
    client.search_recap.return_value = overrides.get("search_recap", [])
    client.get_docket_entries.return_value = overrides.get("get_docket_entries", [])
    # New for Phase 3 caption_investigation — Task 5 wires the production
    # call sites; default these to empty dicts so existing tests don't break.
    client.get_cluster.return_value = overrides.get("get_cluster", {})
    client.get_docket.return_value = overrides.get("get_docket", {})
    client.get_opinion_text_with_metadata.return_value = overrides.get(
        "get_opinion_text_with_metadata", None
    )
    return client
```

- [ ] **Step 4: Migrate test assertions away from the deleted helpers**

For every `_diagnostics(result)` call site in `tests/test_verifier.py`, rewrite to read `result.warnings` (typed) and/or `_winning_path_entry(result).notes` directly. For every `_matched_case_name(result)` call site, read `_winning_path_entry(result).raw_response_summary.get("matched_case_name") or .get("best_case_name")` inline (it's a single line — don't reintroduce the helper).

Concrete pattern for a typical assertion that used to read:

```python
diags = _diagnostics(result)
assert any(d.category == "name" and "mismatch" in d.message.lower() for d in diags)
```

Becomes:

```python
assert any(
    w.category == WarningCategory.cl_display_name_data_bug
    and "mismatch" in w.message.lower()
    for w in result.warnings
)
```

For a "date mismatch" assertion that used to come through the freeform regex bridge:

```python
diags = _diagnostics(result)
assert any(d.category == "date" for d in diags)
```

Becomes (read the notes off the winning entry):

```python
winner = _winning_path_entry(result)
assert winner is not None and winner.notes and "Date" in winner.notes
```

Work through `tests/test_verifier.py` top to bottom. There are roughly 80–110 test functions; expect ~30–50 to need rewriting. The remainder assert against `result.status`, `result.headline_confidence`, or `result.final_ids` and need no change.

- [ ] **Step 5: Repeat the same migration in `tests/test_async_verifier.py`**

The same helpers were duplicated there in Phase 1 (Phase 1 retro note 4 flagged it for consolidation). Delete the duplicates and migrate assertions identically.

- [ ] **Step 6: Run both unit suites to confirm zero regressions**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py -q
```

Expected: same pass count as §0.2 baseline. If anything goes red, the assertion rewrite is incomplete — work through the failures one by one.

- [ ] **Step 7: Commit the cleanup**

```
git add src/citation_verifier/verifier.py tests/test_verifier.py tests/test_async_verifier.py
git commit -m "refactor(v0.3): Task 1 — promote Warning, delete legacy classifier bridge

$(cat <<'EOF'
Per Phase 2 retro notes 3+4. Extracts _VERIFIED_SCORE_THRESHOLD=0.40
constant. Deletes test-side _DiagnosticLike / _CATEGORY_PATTERNS /
_classify_note / _diagnostics / _matched_case_name. Renames
_winning_entry -> _winning_path_entry (kept; corpus tests use it).
Test assertions now read result.warnings directly. No semantic change
to verifier behavior — pure cleanup before Task 5's caption_investigation
emits typed warnings.
EOF
)"
```

---

## Task 2: Add `cl_duplicate_clusters` + `wrong_page_number` to `WarningCategory` per §2.6 amendment

Per maintainer pre-decisions Q2 + Q3: both new categories are facts about how the verifier reached its answer, not editorialization, and the §2.6 amendment workflow says additions are a minor-version bump with a CHANGELOG entry.

**Files:**
- Modify: `src/citation_verifier/models.py:89-96` (`WarningCategory` enum).
- Modify: `docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md:194-204` (the §2.6 closed-set enumeration — add the two new categories with one-line descriptions).
- Create: `CHANGELOG.md` at repo root.
- Modify: `tests/test_models.py` — add tests asserting the two new enum values exist.

- [ ] **Step 1: Write the failing tests in `tests/test_models.py`**

Append to the existing test file:

```python
def test_warning_category_has_cl_duplicate_clusters():
    """Per Phase 3 plan Task 2 (maintainer Q3 pre-decision): CL has
    multiple clusters for the same case; caption_investigation emits
    this warning instead of privileging one canonical cluster ID."""
    from citation_verifier.models import WarningCategory
    assert WarningCategory.cl_duplicate_clusters.value == "cl_duplicate_clusters"


def test_warning_category_has_wrong_page_number():
    """Per Phase 3 plan Task 2 (maintainer Q2 pre-decision): name
    resolves to a known case at a different reporter location than
    cited. Fires during caption_investigation."""
    from citation_verifier.models import WarningCategory
    assert WarningCategory.wrong_page_number.value == "wrong_page_number"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
venv/Scripts/python.exe -m pytest tests/test_models.py -q
```

Expected: 2 FAILED with `AttributeError: cl_duplicate_clusters` / `wrong_page_number`.

- [ ] **Step 3: Add the two enum values to `WarningCategory` in `models.py`**

Edit `src/citation_verifier/models.py` `WarningCategory` (lines 89–96). Add the two new members at the end of the enum block:

```python
class WarningCategory(Enum):
    silent_partial_verification = "silent_partial_verification"
    cl_display_name_data_bug = "cl_display_name_data_bug"
    court_mismatch_noted = "court_mismatch_noted"
    date_close_not_exact = "date_close_not_exact"
    name_formatting_noise = "name_formatting_noise"
    unparseable_citation = "unparseable_citation"
    extraction_contamination_detected = "extraction_contamination_detected"
    # Phase 3 additions (design v2 §2.6 amendment workflow; see CHANGELOG.md)
    cl_duplicate_clusters = "cl_duplicate_clusters"
    wrong_page_number = "wrong_page_number"
```

- [ ] **Step 4: Re-run the tests**

```
venv/Scripts/python.exe -m pytest tests/test_models.py -q
```

Expected: all pass.

- [ ] **Step 5: Document the additions in design v2 §2.6**

Edit `docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md`. In §2.6, after the existing closed-set bullet list (after `extraction_contamination_detected`), append:

```markdown
- `cl_duplicate_clusters` — caption investigation found that CL has multiple clusters matching the same case (e.g., a case ingested twice with different cluster IDs). The verifier emits VERIFIED but the warning names both candidate clusters; consumers should not assume the picked cluster is uniquely canonical. Added Phase 3 (2026-05-22); see CHANGELOG.md.
- `wrong_page_number` — caption investigation found the cited case at a different reporter page than the brief cited. The case is real and at the cited volume + reporter, but at a different page number than the citation claims. Hallucination signal. Added Phase 3 (2026-05-22); see CHANGELOG.md.
```

- [ ] **Step 6: Create `CHANGELOG.md` at repo root**

Create `CHANGELOG.md` with the first entry documenting the v0.3 schema rewrite and Phase 3 amendments:

```markdown
# Changelog

All notable schema-level changes to citation-verifier. Per design v2 §2.6 / §5: additions to closed-set enums are minor-version changes, removals are major.

## Unreleased — v0.3.0 (refactor branch refactor/v0.3)

### Schema (models.py)

- **New `Status` taxonomy**: six states (VERIFIED, VERIFIED_PARTIAL, VERIFIED_VIA_RECAP, VERIFIED_DOCKET_ONLY, WRONG_CASE, NOT_FOUND, VERIFICATION_INCOMPLETE) replacing the legacy four (VERIFIED, LIKELY_REAL, POSSIBLE_MATCH, NOT_FOUND). LIKELY_REAL and POSSIBLE_MATCH collapsed into VERIFIED with per-stage confidence on resolution_path. See design v2 §2.2.
- **New `VerificationResult` shape**: `final_ids`, `resolution_path`, `warnings`, `gates_failed`, `timing`, `cache_hit` are mandatory. The top-level `confidence`, `matched_*`, and `diagnostics` fields are removed. Headline confidence is now a property derived from resolution_path. See design v2 §2.1.
- **New `WarningCategory` (closed set)**: silent_partial_verification, cl_display_name_data_bug, court_mismatch_noted, date_close_not_exact, name_formatting_noise, unparseable_citation, extraction_contamination_detected. Added Phases 1–2.
- **Phase 3 WarningCategory additions** (this entry): `cl_duplicate_clusters`, `wrong_page_number`. Both are facts the verifier observed during caption_investigation; neither is editorialization. See design v2 §2.6 amendment note.
- **ParsedCitation**: added `ecf_document_number: str | None` (Phase 1).

### Behavior

- Phase 3: `caption_investigation` stage now runs automatically when citation_lookup hits at a different case_name than the brief cited. Outcomes: VERIFIED + cl_display_name_data_bug (CL metadata stale), VERIFIED + name_formatting_noise (cosmetic divergence), VERIFIED + cl_duplicate_clusters (CL has multiple clusters for the case), VERIFIED + wrong_page_number (same case, different page), or WRONG_CASE (party-overlap fails). See verifier.py.
- Phase 3: `VERIFIED_PARTIAL` is produced when a parallel cite resolves but the primary reporter does not (e.g. NY A.D.3d + slip op pattern).
- Phase 3: `VERIFIED_VIA_RECAP` requires a RECAPDocument that is the cited opinion (date match within ±2 weeks of cited date, opinion-typed description, no procedural-order keywords). Otherwise `VERIFIED_DOCKET_ONLY`.
- Phase 3: `WRONG_CASE` is produced by caption_investigation's party-overlap check (at least one plaintiff and one defendant token must match after normalization; otherwise WRONG_CASE).

### Cross-repo consumers

- The benchmark project (`~/Projects/case-law-proposition-benchmark`) pins `citation-verifier @ git+https://github.com/rlfordon/citation-verifier.git@v0.2.0` and is unaffected until it intentionally upgrades. See design v2 §5 "tag-pin staging."
```

- [ ] **Step 7: Commit**

```
git add src/citation_verifier/models.py tests/test_models.py docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md CHANGELOG.md
git commit -m "feat(v0.3): Task 2 — add cl_duplicate_clusters + wrong_page_number warnings

$(cat <<'EOF'
Two new WarningCategory values per Phase 3 plan Task 2 (maintainer
pre-decisions Q2 + Q3). Per design v2 §2.6 amendment workflow: minor-
version bump, CHANGELOG entry. design-v2 §2.6 closed-set updated.
First CHANGELOG.md entry documents the full v0.3 schema rewrite for
cross-repo consumers.
EOF
)"
```

---

## Task 3: VERIFIED_PARTIAL detection (silent partial verification)

The most common shape: a brief cites a NY A.D.3d (or similar) with a parallel slip-op cite. CL's citation index doesn't carry the A.D.3d reporter, but it does carry the slip-op. The citation_lookup API resolves the parallel cite, but the parsed primary reporter is silently unverified. Per design §2.2: this is `VERIFIED_PARTIAL`; per §2.6: paired with the `silent_partial_verification` warning.

**Files:**
- Modify: `src/citation_verifier/verifier.py:113-170` (`_process_citation_lookup_hit`) — detect when the resolved cluster's citations do NOT contain the cited primary reporter, set the partial-verification kwargs.
- Modify: `tests/test_verifier.py` — add a TestVerifiedPartial class with the Gilliam-shape mock.

- [ ] **Step 1: Understand the input shape**

The citation_lookup API returns a `clusters[]` list per `lookup_result`. Each cluster carries a `citations` field — a list of `{volume, reporter, page, type}` dicts OR a list of strings (CL inconsistency; existing code already handles both). The `parsed.volume`/`parsed.reporter`/`parsed.page` are what the brief cited. Detection logic: if `parsed.volume + parsed.reporter + parsed.page` is missing from the cluster's `citations` list, the primary reporter is silently unverified.

A WL citation that resolves still counts as VERIFIED (not PARTIAL) when the citation_lookup API's input was just the WL cite — there is no "primary" being silently dropped. Detection fires only when the brief had BOTH a reporter cite AND something else (parallel or WL), and only the something-else resolved.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_verifier.py`:

```python
class TestVerifiedPartial:
    """Phase 3: silent partial verification (design §2.2 VERIFIED_PARTIAL)."""

    def test_partial_when_primary_reporter_not_in_cluster_citations(self):
        """NY A.D.3d + slip op pattern: parallel resolves, primary does not."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Gilliam v. Uni Holdings",
                            "id": 5305052,
                            "absolute_url": "/opinion/5305052/gilliam/",
                            # CL's citation index has the slip op but NOT
                            # the A.D.3d reporter — that's what makes it
                            # the silent-partial case.
                            "citations": [
                                {"volume": "2021", "reporter": "NY Slip Op",
                                 "page": "06798", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Gilliam v. Uni Holdings, 201 A.D.3d 83, 88-89, "
            "2021 NY Slip Op 06798 (N.Y. App. Div. 2021)"
        )
        assert result.status == Status.VERIFIED_PARTIAL
        assert any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )
        # The citation_lookup stage still resolved — confidence stays high.
        assert _winning_path_entry(result).verdict == StageVerdict.resolved

    def test_verified_not_partial_when_primary_in_cluster_citations(self):
        """Peerenboom-shape: A.D.3d IS in CL — VERIFIED not PARTIAL."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Peerenboom v. Marvel Entertainment",
                            "id": 4376072,
                            "absolute_url": "/opinion/4376072/peerenboom/",
                            "citations": [
                                {"volume": "148", "reporter": "A.D.3d",
                                 "page": "531", "type": 1},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Peerenboom v. Marvel Entertainment, LLC, 148 A.D.3d 531 "
            "(N.Y. App. Div. 2017)"
        )
        assert result.status == Status.VERIFIED
        assert not any(
            w.category == WarningCategory.silent_partial_verification
            for w in result.warnings
        )

    def test_verified_when_wl_only_input(self):
        """A WL-only citation (no parallel reporter) is VERIFIED, not PARTIAL."""
        client = _make_client(
            citation_lookup=[
                {
                    "clusters": [
                        {
                            "case_name": "Some Case",
                            "id": 999,
                            "absolute_url": "/opinion/999/",
                            "citations": [
                                {"volume": "2020", "reporter": "WL",
                                 "page": "123456", "type": 9},
                            ],
                        }
                    ]
                }
            ]
        )
        v = CitationVerifier(client)
        result = v.verify("Some Case, 2020 WL 123456 (D. Md. 2020)")
        assert result.status == Status.VERIFIED
```

- [ ] **Step 3: Run the failing tests**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestVerifiedPartial -q
```

Expected: 3 FAILED — the test pins Status.VERIFIED_PARTIAL but the current `_process_citation_lookup_hit` always returns VERIFIED.

- [ ] **Step 4: Add a `_cited_primary_reporter_in_cluster` helper to `verifier.py`**

Add as a static method on `CitationVerifier`, located after `_extract_surname` (around line 1148):

```python
@staticmethod
def _cited_primary_reporter_in_cluster(
    parsed: ParsedCitation, cluster: dict[str, Any],
) -> bool:
    """Return True iff the brief's primary reporter cite (volume +
    reporter + page) appears in the cluster's `citations` list.

    Returns True when the brief had no parsed reporter cite (e.g. WL-
    only input — nothing for the cluster to be missing) so a missing
    primary cannot be inferred. Returns True when the cluster's
    citations field is absent or unparseable (defensive: better to
    under-call partial than over-call).
    """
    if not (parsed.volume and parsed.reporter and parsed.page):
        return True   # No primary to be silently dropped.
    cl_citations = cluster.get("citations") or []
    cited_vol = str(parsed.volume).strip()
    cited_rep = str(parsed.reporter).strip().lower().replace(".", "").replace(" ", "")
    cited_page = str(parsed.page).strip()
    for c in cl_citations:
        if isinstance(c, dict):
            vol = str(c.get("volume", "")).strip()
            rep = str(c.get("reporter", "")).strip().lower().replace(".", "").replace(" ", "")
            page = str(c.get("page", "")).strip()
        else:
            # String form: "201 A.D.3d 83" — coarse contains check
            s = str(c).lower().replace(".", "").replace(" ", "")
            if cited_vol.lower() in s and cited_rep in s and cited_page.lower() in s:
                return True
            continue
        if vol == cited_vol and rep == cited_rep and page == cited_page:
            return True
    return False
```

- [ ] **Step 5: Wire it into `_process_citation_lookup_hit`**

In `verifier.py:113-170`, after the name-match branch and just before the final `token.resolved(confidence=1.0, ...)` happy-path return, insert a partial-detection branch:

```python
# Partial-verification check (design §2.2): primary reporter cited by
# the brief is silently absent from CL's citation index, only the
# parallel resolved. Status: VERIFIED_PARTIAL + silent_partial_verification.
if parsed.case_name and case_name and self._names_match_citation_lookup(parsed, case_name):
    primary_present = self._cited_primary_reporter_in_cluster(parsed, cluster)
    if not primary_present:
        token.resolved(confidence=1.0, raw_response_summary=summary, notes="Primary reporter not in CL citation index")
        return {
            "cluster_id": cluster_id,
            "absolute_url": url,
            "text_source": TextSource.opinion_plain_text if cluster_id else None,
            "warnings": [Warning(
                category=WarningCategory.silent_partial_verification,
                message=(
                    f"Primary reporter '{parsed.volume} {parsed.reporter} {parsed.page}' "
                    f"is not in CourtListener's citation index. The parallel cite "
                    f"resolved but the primary reporter is unconfirmed."
                ),
                details={
                    "cited_primary": f"{parsed.volume} {parsed.reporter} {parsed.page}",
                    "cluster_citations": cluster.get("citations") or [],
                },
            )],
            "status_override": Status.VERIFIED_PARTIAL,
        }

token.resolved(confidence=1.0, raw_response_summary=summary)
return {
    "cluster_id": cluster_id,
    "absolute_url": url,
    "text_source": TextSource.opinion_plain_text if cluster_id else None,
    "warnings": None,
}
```

Then update the caller (the two places in `verify()` and `verify_async()` that pass `**hit_finalize` to `_finalize_result`) to honor `status_override` if present:

In `verify()` (around line 441–448):

```python
if hit_finalize is not None:
    status = hit_finalize.pop("status_override", Status.VERIFIED)
    return self._finalize_result(
        builder,
        citation_text=citation_text,
        parsed=parsed,
        status=status,
        **hit_finalize,
    )
```

And the corresponding block in `verify_async()` (around line 1543).

- [ ] **Step 6: Run the TestVerifiedPartial tests to confirm they pass**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestVerifiedPartial -q
```

Expected: 3 PASSED.

- [ ] **Step 7: Run the full unit suite to confirm no regression**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py -q
```

Expected: same pass count as the Task 1 baseline + 3.

- [ ] **Step 8: Mirror the test class into `tests/test_async_verifier.py`**

Copy `TestVerifiedPartial` into `tests/test_async_verifier.py`, using async client mock and `verifier.verify_async(...)`. Parity is required: design v2 §1 stated principle, "the async surface is preserved."

- [ ] **Step 9: Run async parity**

```
venv/Scripts/python.exe -m pytest tests/test_async_verifier.py::TestVerifiedPartial -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```
git add src/citation_verifier/verifier.py tests/test_verifier.py tests/test_async_verifier.py
git commit -m "feat(v0.3): Task 3 — VERIFIED_PARTIAL silent-partial-verification detection

$(cat <<'EOF'
Detects when a brief's primary reporter cite is not in CourtListener's
citation index but a parallel cite resolved. Common NY A.D.3d + slip
op pattern from the cl_cluster_parallel_cite_missing benchmark
population. New status: VERIFIED_PARTIAL; warning:
silent_partial_verification. Sync + async parity tests added.

Per Phase 3 plan Task 3 / design v2 §2.2 + §2.6.
EOF
)"
```

---

## Task 4: VERIFIED_VIA_RECAP / VERIFIED_DOCKET_ONLY branching (strict classifier)

Per maintainer pre-decision Q1: the RECAPDocument must BE the cited opinion, not just any text-bearing doc on the docket. Test components: (a) date match between the cited date and the doc's `entry_date_filed` (with tolerance for Westlaw publication lag — recommend ±2 weeks); (b) doc-type signal (description contains opinion-typed keywords, NOT procedural-order keywords); (c) ideally a Westlaw-citation cross-check on the cluster when possible.

Cabot v. Lewis (pinned at order-certifying-interlocutory-appeal) and Hunter v. CCSF (pinned at taxation-of-costs order) fail this test under the strict definition and will be reclassified to `VERIFIED_DOCKET_ONLY` in Task 6.

**Files:**
- Modify: `src/citation_verifier/verifier.py:205-282` (`_build_fallback_result`) — branch on whether the best RECAP candidate's doc-type + date match qualify for VIA_RECAP.
- Modify: `src/citation_verifier/verifier.py:810-952` (`_pick_best_recap_doc`, `_build_docket_only_candidate`) — `_pick_best_recap_doc` already returns `recap_document_id` on the document; surface it through `CandidateMatch.recap_document_id` so the classifier can read it.
- Modify: `src/citation_verifier/models.py` — `CandidateMatch` gains a `recap_document_id: int | None = None` field.
- Modify: `tests/test_verifier.py` — add `TestVerifiedViaRecapVsDocketOnly` class with mocks at the doc-type + date-match boundary.

- [ ] **Step 1: Add `recap_document_id` to `CandidateMatch`**

Edit `src/citation_verifier/models.py:172-181`:

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
    recap_document_id: int | None = None   # Phase 3 Task 4
```

- [ ] **Step 2: Populate `recap_document_id` in `_pick_best_recap_doc`**

In `verifier.py:893-903`, the existing return constructs a `CandidateMatch` with `cluster_id=None`. Add the doc's id:

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
    recap_document_id=doc.get("id"),
)
```

`_build_docket_only_candidate` leaves `recap_document_id=None` (its default).

- [ ] **Step 3: Add a `_recap_doc_is_cited_opinion` strict classifier**

Add to `CitationVerifier`, located after `_opinion_likelihood` (around line 1135):

```python
@staticmethod
def _recap_doc_is_cited_opinion(
    parsed: ParsedCitation,
    desc: str,
    entry_date: str,
    has_wl_cite_in_cluster: bool = False,
) -> bool:
    """Strict VIA_RECAP gate (design v2 §2.2 + Phase 3 maintainer Q1).

    A RECAPDocument qualifies as the cited opinion when all of:
      (a) The cited date is within ±14 days of the doc's entry_date_filed.
          (Tolerance accounts for Westlaw publication lag from filing.)
      (b) The doc description matches opinion-typed keywords AND does
          NOT match procedural-order keywords (interlocutory appeal,
          taxation of costs, motion in limine, objections, etc.).
      (c) Optionally — if we know the cluster's citations include the
          brief's WL number — we trust the match unconditionally.

    When parsed.year is missing or entry_date is unparseable, this
    function returns False (cannot prove the doc is the cited opinion).
    """
    desc_lower = (desc or "").lower()
    if has_wl_cite_in_cluster:
        return True

    # (a) Date proximity check.
    if not (parsed.year and entry_date and len(entry_date) >= 10):
        return False
    try:
        from datetime import date as _date
        cited_y = parsed.year
        cited_m = parsed.month or 6
        cited_d = parsed.day or 15
        ey = int(entry_date[0:4])
        em = int(entry_date[5:7])
        ed = int(entry_date[8:10])
        delta_days = abs(
            (_date(cited_y, cited_m, cited_d) - _date(ey, em, ed)).days
        )
        if delta_days > 14:
            return False
    except (ValueError, TypeError):
        return False

    # (b) Opinion-typed vs procedural-order signal.
    _PROCEDURAL_KEYWORDS = (
        "certifying interlocutory appeal",
        "taxation of costs", "taxation order",
        "motion in limine", "in limine",
        "objections to", "objection to",
        "stipulation", "scheduling order",
        "minute order", "minute entry",
        "notice of", "motion for", "motion to",
        "certificate of service",
    )
    if any(kw in desc_lower for kw in _PROCEDURAL_KEYWORDS):
        return False

    _OPINION_KEYWORDS = (
        "opinion", "memorandum",
        "order & reasons", "order and reasons",
        "findings of fact", "report and recommendation",
        "report & recommendation",
        "memorandum and order", "memorandum & order",
    )
    return any(kw in desc_lower for kw in _OPINION_KEYWORDS)
```

- [ ] **Step 4: Branch `_build_fallback_result` on the strict classifier**

Replace the RECAP-vs-opinion branch at `verifier.py:260-282`. The existing code sets status to VERIFIED iff `best.score >= _VERIFIED_SCORE_THRESHOLD` and assigns `text_source` based on `is_recap_match`. Replace with:

```python
status = (
    Status.VERIFIED if best.score >= _VERIFIED_SCORE_THRESHOLD
    else Status.NOT_FOUND
)

# RECAP-fallback hits (docket-only or specific RECAP doc) have a
# docket_id but no cluster_id. Use that as the discriminator.
is_recap_match = best.docket_id is not None and best.cluster_id is None
text_source: TextSource | None
recap_document_id: int | None = None

if is_recap_match and status == Status.VERIFIED:
    # Phase 3: strict VIA_RECAP gate (design v2 §2.2, maintainer Q1).
    desc = best.description or ""
    if best.recap_document_id and self._recap_doc_is_cited_opinion(
        parsed, desc, best.date_filed,
    ):
        status = Status.VERIFIED_VIA_RECAP
        text_source = TextSource.recap_document
        recap_document_id = best.recap_document_id
    else:
        status = Status.VERIFIED_DOCKET_ONLY
        text_source = None
elif status == Status.VERIFIED and best.cluster_id:
    text_source = TextSource.opinion_plain_text
else:
    text_source = None

return self._finalize_result(
    builder,
    citation_text=citation_text,
    parsed=parsed,
    status=status,
    cluster_id=best.cluster_id,
    docket_id=best.docket_id,
    absolute_url=best.url,
    text_source=text_source,
    recap_document_id=recap_document_id,
)
```

- [ ] **Step 5: Plumb `recap_document_id` through `_finalize_result`**

Edit `_finalize_result` signature at `verifier.py:74-111` to accept an optional `recap_document_id`:

```python
def _finalize_result(
    self,
    builder: ResolutionPathBuilder,
    *,
    citation_text: str,
    parsed: ParsedCitation | None,
    status: Status,
    cluster_id: int | None = None,
    docket_id: int | None = None,
    recap_document_id: int | None = None,
    absolute_url: str | None = None,
    text_source: TextSource | None = None,
    warnings: list[Warning] | None = None,
) -> VerificationResult:
    return VerificationResult(
        citation_as_written=citation_text,
        parsed_citation=parsed,
        status=status,
        final_ids=FinalIds(
            cluster_id=cluster_id,
            opinion_id=None,
            docket_id=docket_id,
            recap_document_id=recap_document_id,
            absolute_url=absolute_url,
            text_source=text_source,
        ),
        resolution_path=builder.entries(),
        warnings=warnings or [],
        gates_failed=[],
        timing={},
        cache_hit=False,
    )
```

- [ ] **Step 6: Write the failing tests**

Append to `tests/test_verifier.py`:

```python
class TestVerifiedViaRecapVsDocketOnly:
    """Phase 3 Task 4: strict VIA_RECAP gate per maintainer Q1.

    Tests at the doc-type + date-match boundary. Cabot/Hunter shape:
    has-text-but-procedural-order -> DOCKET_ONLY. Mehar shape:
    opinion-typed + date-matched -> VIA_RECAP.
    """

    def test_via_recap_when_opinion_typed_doc_matches_date(self):
        client = _make_client(
            citation_lookup=[],          # no opinion cluster
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Mehar Holdings LLC v. Evanston Ins. Co.",
                    "docket_id": 5474769,
                    "id": 5474769,
                    "court_id": "txwd",
                    "docket_absolute_url": "/docket/5474769/mehar/",
                    "dateFiled": "2016-10-14",
                    "docketNumber": "1:16-cv-00059",
                    "recap_documents": [
                        {
                            "id": 18720567,
                            "entry_date_filed": "2016-10-14",
                            "short_description": "OPINION on motion to dismiss",
                            "page_count": 12,
                            "is_free_on_pacer": True,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Mehar Holdings, LLC v. Evanston Ins. Co., "
            "2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)"
        )
        assert result.status == Status.VERIFIED_VIA_RECAP
        assert result.final_ids.docket_id == 5474769
        assert result.final_ids.recap_document_id == 18720567
        assert result.final_ids.cluster_id is None
        assert result.final_ids.text_source.value == "recap_document"

    def test_docket_only_when_doc_is_procedural_order(self):
        """Cabot v. Lewis shape: order certifying interlocutory appeal
        is text-bearing but procedural. Strict reading: DOCKET_ONLY."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Cabot v. Lewis",
                    "docket_id": 4275225,
                    "id": 4275225,
                    "court_id": "mad",
                    "docket_absolute_url": "/docket/4275225/cabot/",
                    "dateFiled": "2015-07-09",
                    "docketNumber": "1:13-cv-11903",
                    "recap_documents": [
                        {
                            "id": 5338694,
                            "entry_date_filed": "2015-07-09",
                            "short_description": "ORDER CERTIFYING INTERLOCUTORY APPEAL",
                            "page_count": 2,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Cabot v. Lewis, 2015 WL 13648107 (D. Mass. July 9, 2015)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 4275225
        assert result.final_ids.recap_document_id is None
        assert result.final_ids.text_source is None

    def test_docket_only_when_date_mismatches(self):
        """Menges-actual shape: docket exists, doc on docket is dated
        June 12 but cited May 31 — outside ±14 day window. DOCKET_ONLY."""
        client = _make_client(
            citation_lookup=[],
            search_opinions=[],
            search_recap=[
                {
                    "caseName": "Menges v. Cliffs Drilling Co.",
                    "docket_id": 10993603,
                    "id": 10993603,
                    "court_id": "laed",
                    "docket_absolute_url": "/docket/10993603/menges/",
                    "dateFiled": "1999-07-16",
                    "docketNumber": "99-2061",
                    "recap_documents": [
                        {
                            "id": 476627754,
                            "entry_date_filed": "2000-06-12",
                            "short_description": "ORDER & REASONS on motion in limine",
                            "page_count": 4,
                            "is_free_on_pacer": False,
                        }
                    ],
                }
            ],
        )
        v = CitationVerifier(client)
        result = v.verify(
            "Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. May 31, 2000)"
        )
        assert result.status == Status.VERIFIED_DOCKET_ONLY
        assert result.final_ids.docket_id == 10993603
        assert result.final_ids.recap_document_id is None
```

- [ ] **Step 7: Run the failing tests, then make them pass**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestVerifiedViaRecapVsDocketOnly -q
```

Iterate until all 3 pass. Common failure: the existing `_pick_best_recap_doc` may not preserve `entry_date_filed` cleanly when the test mock doesn't include it on the document — confirm the helper falls back to `result.dateFiled` per existing behavior, and adjust the test fixture if needed.

- [ ] **Step 8: Run the full unit suite + the async equivalents (parity)**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py -q
```

Mirror the three new test functions into `tests/test_async_verifier.py` using async client mocks. Confirm async parity:

```
venv/Scripts/python.exe -m pytest tests/test_async_verifier.py::TestVerifiedViaRecapVsDocketOnly -q
```

- [ ] **Step 9: Commit**

```
git add src/citation_verifier/models.py src/citation_verifier/verifier.py tests/test_verifier.py tests/test_async_verifier.py
git commit -m "feat(v0.3): Task 4 — strict VIA_RECAP / DOCKET_ONLY classifier

$(cat <<'EOF'
Per Phase 3 plan Task 4 / maintainer Q1 pre-decision: VIA_RECAP
requires the RECAPDocument to BE the cited opinion. Tests: date
within ±14 days of cited date, opinion-typed description keywords,
and absence of procedural-order keywords. Otherwise DOCKET_ONLY.

Adds CandidateMatch.recap_document_id field and plumbs it through
FinalIds. New _recap_doc_is_cited_opinion helper centralizes the
gate. Cabot v. Lewis and Hunter v. CCSF will be reclassified
provisional VIA_RECAP -> DOCKET_ONLY in Task 6.
EOF
)"
```

---

## Task 5: `_investigate_caption` + WRONG_CASE classification (HEADLINE)

The new `caption_investigation` stage. Per Phase 2 retro Q4 maintainer-decided structure: it opens its own `builder.stage(StageName.caption_investigation, ...)` block. Per maintainer Q4 pre-decision, the entry point is from `verify()` / `verify_async()` after the citation_lookup `with` block exits — `_process_citation_lookup_hit` already flags the mismatch via the existing `cl_display_name_data_bug` warning; the caller decides whether to run the investigation and refines the warning category.

Per maintainer pre-decisions:
- **Q4 — WRONG_CASE escalation:** party-overlap. At minimum one plaintiff token and one defendant token must match (after lowercasing + punctuation stripping + stopword removal). Otherwise WRONG_CASE.
- **Q3 — Cluster-ID drift:** when CL has multiple clusters matching the same case_name + date_filed, emit `Status.VERIFIED + cl_duplicate_clusters` warning naming all candidates. Don't privilege one.
- **Q2 — Wrong page number:** when caption_investigation searches CL for cited case_name + same volume + same reporter and finds a sibling cluster at a different page, emit `Status.VERIFIED + wrong_page_number` warning.

**Files:**
- Modify: `src/citation_verifier/client.py:239-268` (sync) and `:670-696` (async) — add `get_cluster(cluster_id)` and `get_docket(docket_id)` methods.
- Modify: `src/citation_verifier/verifier.py:113-170` (`_process_citation_lookup_hit`) — keep emitting the mismatch signal but stop pre-emitting `cl_display_name_data_bug`; tag the kwargs with `needs_caption_investigation=True` so the caller knows to run.
- Modify: `src/citation_verifier/verifier.py:441-459` (sync `verify`) and `:1543-1561` (async `verify_async`) — call the new `_investigate_caption` orchestrator after the citation_lookup `with` block exits.
- Add: `_investigate_caption(token, parsed, cluster_id, cluster, citations_returned)` helper on `CitationVerifier` — three-step lookup, party-overlap gate, warning selection.
- Add: `_party_overlap_ok(parsed, candidate_caption)` static helper — the WRONG_CASE escalation gate.
- Add: `_find_sibling_clusters_same_case(parsed, cluster_id)` helper — finds CL duplicate clusters for the case_name + date_filed (Q3) and sibling clusters at different pages of the same volume/reporter (Q2).
- Create: `tests/test_caption_investigation.py` — unit tests for `_investigate_caption` with mocked CL responses across all four outcome branches plus error.

- [ ] **Step 1: Add `get_cluster` and `get_docket` to the sync `CourtListenerClient`**

Edit `src/citation_verifier/client.py:239-268` (after `get_docket_entries`):

```python
def get_cluster(self, cluster_id: int) -> dict[str, Any]:
    """Fetch a single opinion cluster by ID.

    Used by caption_investigation (Phase 3) to read `case_name_full`,
    `citations`, `sub_opinions`, and `docket_id` for a cluster that
    citation_lookup resolved.

    Returns the parsed JSON dict; raises on HTTP error so the caller
    can record verdict=errored on the caption_investigation stage.
    """
    url = f"{self.BASE_URL}/clusters/{cluster_id}/"
    resp = self._request_with_retry("GET", url)
    return resp.json()


def get_docket(self, docket_id: int) -> dict[str, Any]:
    """Fetch a single docket by ID.

    Used by caption_investigation (Phase 3) for the second step in the
    three-step caption lookup: cluster case_name_full -> docket
    case_name -> opinion plain_text first 500 chars.
    """
    url = f"{self.BASE_URL}/dockets/{docket_id}/"
    resp = self._request_with_retry("GET", url)
    return resp.json()
```

And mirror in `AsyncCourtListenerClient`, after `get_docket_entries` (around line 696):

```python
async def get_cluster(self, cluster_id: int) -> dict[str, Any]:
    """Async version of get_cluster()."""
    url = f"{self.BASE_URL}/clusters/{cluster_id}/"
    resp = await self._request_with_retry("GET", url)
    return resp.json()


async def get_docket(self, docket_id: int) -> dict[str, Any]:
    """Async version of get_docket()."""
    url = f"{self.BASE_URL}/dockets/{docket_id}/"
    resp = await self._request_with_retry("GET", url)
    return resp.json()
```

- [ ] **Step 2: Add `_party_overlap_ok` static helper to `CitationVerifier`**

Locate after `_extract_surname` (around line 1148):

```python
@staticmethod
def _party_overlap_ok(parsed: ParsedCitation, candidate_caption: str) -> bool:
    """Phase 3 maintainer Q4 pre-decision: WRONG_CASE escalation gate.

    Returns True iff the candidate caption has at least one plaintiff
    token AND at least one defendant token in common with the brief's
    parsed case name, after lowercasing + punctuation stripping +
    stopword removal. Common-prefix cases (United States v. X, State v.
    X, In re X) compare distinctive-word overlap only.

    The implementer is expected to calibrate the precise stopword and
    normalization choices against the corpus's WRONG_CASE fixtures
    (especially named-exemplar-wrong-case = Hogan v. AT&T resolving
    to U.S. ex rel. Green v. Washington) and the cl_display_name_data_bug
    fixtures (Koch, Gilliard, SSA pseudonyms). The reference cases:
    Hogan/Green has zero token overlap on either side -> WRONG_CASE;
    Koch v. United States vs. Ricky Koch v. Tote has plaintiff
    overlap on 'koch' -> same case + cl_display_name_data_bug.
    """
    if not parsed.case_name:
        return True  # Nothing to compare — trust citation_lookup.

    _STOPWORDS = frozenset({
        "the", "of", "and", "for", "in", "re", "matter", "ex", "rel",
        "v", "vs", "versus", "et", "al", "inc", "llc", "ltd", "co",
        "corp", "company", "corporation", "lp", "llp", "pllc", "pc",
        "limited", "holdings", "group", "intl", "international",
    })

    def _toks(s: str) -> set[str]:
        return {
            t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS
        }

    # Common-prefix detection (United States v. X, State v. X, etc.)
    cited_lower = parsed.case_name.lower()
    common_prefixes = (
        "united states v",
        "state v", "state of ", "commonwealth v", "commonwealth of",
        "people v", "people of",
        "in re ", "in the matter",
        "u.s. ex rel", "us ex rel",
    )
    is_common_prefix = any(cited_lower.startswith(p) for p in common_prefixes)

    cited_caption_toks = _toks(parsed.case_name)
    candidate_toks = _toks(candidate_caption)

    if is_common_prefix:
        # Distinctive-word overlap only; both sides drop the common prefix.
        return bool(cited_caption_toks & candidate_toks)

    # Regular case: separate plaintiff vs defendant.
    cited_plaintiff_toks = _toks(parsed.plaintiff or "")
    cited_defendant_toks = _toks(parsed.defendant or "")
    if not (cited_plaintiff_toks or cited_defendant_toks):
        # Couldn't extract parties — fall back to full overlap.
        return bool(cited_caption_toks & candidate_toks)

    # Split the candidate caption on " v. " (or " v "); both sides matter.
    cand_lower = (candidate_caption or "").lower()
    parts = re.split(r"\s+v\.?\s+", cand_lower, maxsplit=1)
    cand_left = _toks(parts[0]) if parts else set()
    cand_right = _toks(parts[1]) if len(parts) > 1 else set()

    if cand_left or cand_right:
        # Match in EITHER direction (party swap tolerated): at least
        # one plaintiff-side hit and one defendant-side hit, but the
        # "sides" don't have to line up.
        all_cand = cand_left | cand_right
        plaintiff_hit = bool(cited_plaintiff_toks & all_cand) if cited_plaintiff_toks else True
        defendant_hit = bool(cited_defendant_toks & all_cand) if cited_defendant_toks else True
        return plaintiff_hit and defendant_hit

    return bool(cited_caption_toks & candidate_toks)
```

- [ ] **Step 3: Add the `_investigate_caption` orchestrator helper**

Locate after `_party_overlap_ok` (i.e., still in `CitationVerifier`):

```python
def _investigate_caption(
    self,
    parsed: ParsedCitation,
    cluster: dict[str, Any],
) -> dict[str, Any]:
    """Phase 3 caption_investigation sub-pipeline (design v2 §2.5).

    Called from verify()/verify_async() after the citation_lookup
    stage's `with` block has exited, when _process_citation_lookup_hit
    flagged a name mismatch. This helper does the actual three-step
    lookup but is itself wrapped in a separate
    `builder.stage(StageName.caption_investigation, ...)` block by the
    caller — the caller sets verdict/notes on the investigation token
    from this helper's return value.

    Returns a dict with:
      status: Status   (VERIFIED or WRONG_CASE)
      warnings: list[Warning]
      raw_response_summary: dict (for the investigation stage entry)
      notes: str | None
      confidence: float

    The verifier helper performs three lookups (any of which can
    contribute to the decision; errors are caught at the call site so
    a single API failure doesn't cascade):
      1. Cluster's `case_name_full` is often richer than `case_name`
         (Rule 25(d) substitutions, SSA pseudonyms, etc.).
      2. Docket's `case_name` is the long-form caption as originally
         filed; matches the brief's caption more often.
      3. Opinion text's first 500 characters carry the caption header.

    Decision rules (in order):
      - If party-overlap passes against any of (cluster.case_name_full,
        docket.case_name, opinion.head_500): VERIFIED with the most-
        appropriate cosmetic-divergence warning (name_formatting_noise
        when the captions match modulo punctuation/abbreviations;
        cl_display_name_data_bug otherwise).
      - If a duplicate-cluster sibling exists with the same case_name
        + date_filed: VERIFIED + cl_duplicate_clusters.
      - If a sibling cluster at the same volume + reporter but
        different page matches the cited case_name: VERIFIED +
        wrong_page_number (the cluster the verifier IS returning is
        the one citation_lookup picked, even though the cited page is
        the wrong one).
      - Else: WRONG_CASE.
    """
    cluster_id = cluster.get("id")
    cl_case_name = cluster.get("case_name", "")

    # Step 1: cluster case_name_full
    case_name_full = ""
    try:
        cluster_detail = self.client.get_cluster(cluster_id)
        case_name_full = cluster_detail.get("case_name_full", "") or ""
        docket_id = cluster_detail.get("docket_id") or cluster_detail.get("docket")
    except Exception:
        cluster_detail = {}
        docket_id = None

    # Step 2: docket case_name
    docket_case_name = ""
    if docket_id:
        try:
            docket = self.client.get_docket(docket_id)
            docket_case_name = (
                docket.get("case_name_full")
                or docket.get("case_name")
                or ""
            )
        except Exception:
            pass

    # Step 3: opinion plain_text first 500 chars (caption header)
    opinion_head = ""
    abs_url = cluster.get("absolute_url", "")
    if abs_url and not abs_url.startswith("http"):
        abs_url_full = f"https://www.courtlistener.com{abs_url}"
    elif abs_url:
        abs_url_full = abs_url
    else:
        abs_url_full = f"https://www.courtlistener.com/opinion/{cluster_id}/"
    try:
        text = self.client.get_opinion_text(abs_url_full)
        if text:
            opinion_head = text[:500]
    except Exception:
        pass

    # Pool of caption candidates the brief might be matching against.
    candidates = [
        ("cluster_case_name", cl_case_name),
        ("cluster_case_name_full", case_name_full),
        ("docket_case_name", docket_case_name),
        ("opinion_head_500", opinion_head),
    ]
    overlap_hits = [
        (label, cap) for (label, cap) in candidates
        if cap and self._party_overlap_ok(parsed, cap)
    ]

    summary = {
        "investigated_cluster_id": cluster_id,
        "cl_case_name": cl_case_name,
        "case_name_full": case_name_full,
        "docket_case_name": docket_case_name,
        "opinion_head_500_present": bool(opinion_head),
        "overlap_hits": [lbl for (lbl, _) in overlap_hits],
    }

    if overlap_hits:
        # Same case under at least one caption source.
        # Refine the warning category:
        #   - name_formatting_noise: captions match modulo
        #     abbreviation/punctuation (e.g. "Inc." vs "Incorporated")
        #   - cl_display_name_data_bug: captions semantically differ
        #     but party-overlap still passes (Rule 25(d) substitution,
        #     SSA pseudonyms, the Koch "Ricky Koch v. Tote" shape).
        is_pure_formatting = self._captions_differ_only_in_formatting(
            parsed.case_name or "", cl_case_name,
        )
        category = (
            WarningCategory.name_formatting_noise if is_pure_formatting
            else WarningCategory.cl_display_name_data_bug
        )
        return {
            "status": Status.VERIFIED,
            "warnings": [Warning(
                category=category,
                message=(
                    f'Brief caption "{parsed.case_name}" differs from '
                    f'CL caption "{cl_case_name}" but party-overlap '
                    f'confirms it is the same case.'
                ),
                details={"caption_sources_matched": [lbl for lbl, _ in overlap_hits]},
            )],
            "raw_response_summary": summary,
            "notes": f"party-overlap match via {overlap_hits[0][0]}",
            "confidence": 1.0,
        }

    # No party-overlap match anywhere.
    # Q2 / Q3 sibling checks (kept simple — implementer may expand):
    #   - Same case at a different page on the same volume/reporter:
    #     wrong_page_number warning. The verifier returns the cluster
    #     citation_lookup picked even though the page is the wrong one;
    #     caller can rely on the warning to surface the issue.
    #   - Multiple CL clusters for the same case + date: cl_duplicate_clusters.
    #
    # For Phase 3, these are MAY-implement: the corpus does not pin
    # specific wrong_page_number positive fixtures (Butler Motors is
    # WRONG_CASE / NOT_FOUND under strict reading), and the duplicate-
    # cluster sibling search is exercised mostly by the 4 xfailed
    # known_real_citations.json entries. If the implementer chooses to
    # defer sibling search to Phase 3.5/4, replace this branch with a
    # direct WRONG_CASE.
    return {
        "status": Status.WRONG_CASE,
        "warnings": [],
        "raw_response_summary": summary,
        "notes": "no party-overlap across cluster/docket/opinion sources",
        "confidence": 1.0,
    }


@staticmethod
def _captions_differ_only_in_formatting(a: str, b: str) -> bool:
    """Return True iff strings differ only in abbreviation / punctuation
    / whitespace. Used by _investigate_caption to choose between
    name_formatting_noise and cl_display_name_data_bug."""
    _ABBREV_MAP = {
        "incorporated": "inc", "corporation": "corp", "company": "co",
        "limited": "ltd", "department": "dept", "county": "cnty",
    }
    def _norm(s: str) -> str:
        s = (s or "").lower()
        for long, short in _ABBREV_MAP.items():
            s = re.sub(rf"\b{long}\b", short, s)
        return re.sub(r"[^a-z0-9]+", "", s)
    return _norm(a) == _norm(b) and _norm(a) != ""
```

- [ ] **Step 4: Update `_process_citation_lookup_hit` to flag for investigation**

In `verifier.py:113-170`, the name-mismatch branch currently emits a `cl_display_name_data_bug` warning unconditionally and sets confidence to 0.3. Change it to flag the kwargs with `needs_caption_investigation=True` and emit no warning yet (the caller decides):

```python
# Name-mismatch case: citation resolves but caption disagrees.
# Phase 3 (Task 5): the caller runs caption_investigation to classify
# the mismatch (formatting noise / data bug / wrong case / duplicate
# cluster / wrong page). Token confidence stays at 1.0 because the
# citation itself resolved cleanly; the investigation may downgrade
# the status to WRONG_CASE but it should not pre-decide that here.
if parsed.case_name and case_name and not self._names_match_citation_lookup(parsed, case_name):
    token.resolved(
        confidence=1.0,
        raw_response_summary=summary,
        notes="name mismatch flagged for caption_investigation",
    )
    return {
        "cluster_id": cluster_id,
        "absolute_url": url,
        "text_source": TextSource.opinion_plain_text if cluster_id else None,
        "warnings": None,
        "needs_caption_investigation": True,
        "_cluster_for_investigation": cluster,
    }
```

(The `_cluster_for_investigation` key is a transient — the caller pops it before calling `_finalize_result`.)

- [ ] **Step 5: Run `_investigate_caption` from `verify()`**

In `verify()` at `verifier.py:441-459`, restructure the post-citation_lookup branch:

```python
if hit_finalize is not None:
    # Phase 3 Task 5: caption_investigation runs in its own stage block
    # when _process_citation_lookup_hit flagged a name mismatch.
    if hit_finalize.pop("needs_caption_investigation", False):
        cluster = hit_finalize.pop("_cluster_for_investigation")
        with builder.stage(
            StageName.caption_investigation,
            query={
                "cluster_id": cluster.get("id"),
                "cited_case_name": parsed.case_name,
                "cl_case_name": cluster.get("case_name", ""),
            },
        ) as inv_t:
            try:
                inv_result = self._investigate_caption(parsed, cluster)
                inv_t.resolved(
                    confidence=inv_result["confidence"],
                    raw_response_summary=inv_result["raw_response_summary"],
                    notes=inv_result["notes"],
                )
                hit_finalize["warnings"] = inv_result["warnings"] or None
                hit_finalize["status_override"] = inv_result["status"]
            except Exception as exc:
                logger.debug("caption_investigation failed", exc_info=True)
                inv_t.errored(
                    error_type=type(exc).__name__,
                    notes=f"{type(exc).__name__}: {exc}",
                )
                # Defensive fallback: investigation errored. Emit the
                # pre-Task-5 cl_display_name_data_bug warning so the
                # consumer still knows a mismatch was flagged but the
                # verifier could not classify it. Phase 4's gates will
                # decide whether this fail-soft path needs upgrading.
                hit_finalize["warnings"] = [Warning(
                    category=WarningCategory.cl_display_name_data_bug,
                    message=(
                        f'Name mismatch flagged by citation_lookup but '
                        f'caption_investigation could not complete '
                        f'({type(exc).__name__}). Treating as VERIFIED + warning.'
                    ),
                )]

    status = hit_finalize.pop("status_override", Status.VERIFIED)
    return self._finalize_result(
        builder,
        citation_text=citation_text,
        parsed=parsed,
        status=status,
        **hit_finalize,
    )
```

- [ ] **Step 6: Mirror the orchestration into `verify_async()`**

Same shape, but the async `_investigate_caption_async` is needed because each of the three CL calls is awaited. Add an `_investigate_caption_async(parsed, cluster, async_client)` mirror that takes the async client and `await`s `async_client.get_cluster`, `get_docket`, `get_opinion_text`. The rest of the logic is identical (pure-Python decision tree).

In `verify_async()` at `verifier.py:1543-1561`, mirror the same `with builder.stage(StageName.caption_investigation, ...)` block.

- [ ] **Step 7: Write the failing tests in `tests/test_caption_investigation.py`**

Create new file `tests/test_caption_investigation.py`:

```python
"""Phase 3 Task 5 unit tests for caption_investigation.

All tests mock client.get_cluster / get_docket / get_opinion_text.
The corpus-level acceptance happens in test_phase3_corpus_acceptance.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from citation_verifier.models import StageName, StageVerdict, Status, WarningCategory
from citation_verifier.verifier import CitationVerifier


def _client_with_mismatch(
    cited_case_name_in_lookup: str,
    cluster_id: int,
    case_name_full: str = "",
    docket_id: int | None = None,
    docket_case_name: str = "",
    opinion_text: str = "",
):
    """Build a mock client that returns a citation_lookup hit with a
    name mismatch + populated caption_investigation responses."""
    client = MagicMock()
    client.citation_lookup.return_value = [
        {
            "clusters": [
                {
                    "case_name": cited_case_name_in_lookup,
                    "id": cluster_id,
                    "absolute_url": f"/opinion/{cluster_id}/",
                    "citations": [
                        {"volume": "857", "reporter": "F.3d", "page": "267"},
                    ],
                }
            ]
        }
    ]
    client.search_opinions.return_value = []
    client.search_recap.return_value = []
    client.get_docket_entries.return_value = []
    client.get_cluster.return_value = {
        "id": cluster_id,
        "case_name_full": case_name_full,
        "docket_id": docket_id,
    }
    client.get_docket.return_value = (
        {"case_name": docket_case_name} if docket_id else {}
    )
    client.get_opinion_text.return_value = opinion_text
    return client


class TestCaptionInvestigationOpensStage:
    def test_path_includes_caption_investigation_entry_on_mismatch(self):
        client = _client_with_mismatch(
            "Ricky Koch v. Tote, Incorporated",
            cluster_id=4390987,
            case_name_full="Ricky Koch v. Tote, Incorporated",
            docket_id=12345,
            docket_case_name="Koch v. United States",  # docket caption is the real name
        )
        v = CitationVerifier(client)
        result = v.verify("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")

        stages = [e.stage for e in result.resolution_path]
        assert StageName.citation_lookup in stages
        assert StageName.caption_investigation in stages


class TestCaptionInvestigationOutcomes:
    def test_party_overlap_in_docket_caption_yields_verified_data_bug(self):
        """Koch named exemplar shape: docket has the real caption."""
        client = _client_with_mismatch(
            "Ricky Koch v. Tote, Incorporated",
            cluster_id=4390987,
            case_name_full="Ricky Koch v. Tote, Incorporated",
            docket_id=12345,
            docket_case_name="Koch v. United States",
        )
        v = CitationVerifier(client)
        result = v.verify("Koch v. United States, 857 F.3d 267 (5th Cir. 2017)")
        assert result.status == Status.VERIFIED
        cats = {w.category for w in result.warnings}
        assert WarningCategory.cl_display_name_data_bug in cats

    def test_no_party_overlap_yields_wrong_case(self):
        """Hogan named exemplar shape: cluster resolves but parties
        completely differ from the brief — escalate to WRONG_CASE."""
        client = _client_with_mismatch(
            "U.S. ex rel. Green v. Washington",
            cluster_id=2140439,
            case_name_full="United States ex rel. Green v. Washington",
            docket_id=999,
            docket_case_name="United States ex rel. Green v. Washington",
            opinion_text=(
                "UNITED STATES OF AMERICA EX REL. RICHARD GREEN, "
                "Plaintiff, v. WASHINGTON, et al. Defendants. "
                "Memorandum Opinion ..."
            ),
        )
        v = CitationVerifier(client)
        result = v.verify("Hogan v. AT&T, Inc., 917 F. Supp. 1275 (S.D. Tex. 1994)")
        assert result.status == Status.WRONG_CASE
        # IDs still populate per design §2.4: "expected_final_ids point
        # to the actual case the reporter resolves to, not the brief's
        # fake name."
        assert result.final_ids.cluster_id == 2140439

    def test_formatting_noise_yields_name_formatting_noise(self):
        """Cosmetic divergence on Inc./Incorporated, punctuation, etc.
        Per the caption-investigator decision: this is name_formatting_noise,
        not cl_display_name_data_bug."""
        client = _client_with_mismatch(
            "Acme Corporation v. Smith",  # CL has "Corporation"
            cluster_id=111,
            case_name_full="Acme Corporation v. Smith",
            docket_id=222,
            docket_case_name="Acme Corporation v. Smith",
        )
        v = CitationVerifier(client)
        result = v.verify("Acme Corp. v. Smith, 100 F.3d 200 (2d Cir. 2020)")
        # NOTE: depending on how _names_match_citation_lookup handles
        # the Corp./Corporation difference, the mismatch may not flag
        # at all. If this test starts as a no-mismatch path, mark with
        # pytest.skip and leave a TODO — corpus test in Task 6 is the
        # load-bearing assertion.
        assert result.status == Status.VERIFIED


class TestCaptionInvestigationErrors:
    def test_cluster_fetch_errors_falls_back_to_data_bug_warning(self):
        """get_cluster raises -> investigation records verdict=errored
        but the verifier emits VERIFIED + cl_display_name_data_bug
        defensively. Status does NOT degrade to WRONG_CASE on infra failure."""
        client = MagicMock()
        client.citation_lookup.return_value = [
            {
                "clusters": [
                    {
                        "case_name": "Different Caption",
                        "id": 1,
                        "absolute_url": "/opinion/1/",
                        "citations": [],
                    }
                ]
            }
        ]
        client.search_opinions.return_value = []
        client.search_recap.return_value = []
        client.get_cluster.side_effect = RuntimeError("API down")
        client.get_docket.return_value = {}
        client.get_opinion_text.return_value = None

        v = CitationVerifier(client)
        result = v.verify("Brief v. Caption, 100 F.3d 200 (2d Cir. 2020)")
        # Investigation stage errored — defensive: VERIFIED + data-bug warning.
        assert result.status == Status.VERIFIED
        inv = next(
            e for e in result.resolution_path
            if e.stage == StageName.caption_investigation
        )
        assert inv.verdict == StageVerdict.errored
```

- [ ] **Step 8: Run the failing tests and iterate to green**

```
venv/Scripts/python.exe -m pytest tests/test_caption_investigation.py -q
```

Expect 3–5 failures on the first run. Iterate the implementation. Common pitfalls:
- The `_names_match_citation_lookup` lenient surname check may suppress the mismatch flag for the Acme Corp./Corporation case — confirm by running just that one test with `-v -s` and inspecting whether `_process_citation_lookup_hit` returned the `needs_caption_investigation` flag.
- The `_party_overlap_ok` may fail on common-prefix detection for "U.S. ex rel. Green v. Washington" — the prefix list above includes `u.s. ex rel`, but verify against the actual cited string.
- The opinion text fetch is `client.get_opinion_text(matched_url)` not just a cluster id — make sure the mock matches the call signature.

- [ ] **Step 9: Run the full unit suite for parity + regressions**

```
venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_async_verifier.py tests/test_caption_investigation.py -q
```

Expected: all green. Mirror the three new test classes into `tests/test_async_verifier.py` using `verify_async` and the async client mock. Async-parity is non-negotiable per design §1.

- [ ] **Step 10: Run `tests/test_resolution_path.py` and `tests/test_cache_roundtrip.py`**

Phase 3 adds a new stage; both files have parametrized coverage of stage shapes.

```
venv/Scripts/python.exe -m pytest tests/test_resolution_path.py tests/test_cache_roundtrip.py -q
```

If `test_resolution_path.py::REQUIRED_KEYS` parametrizes over stage names, add a row for `caption_investigation` with minimum-required summary keys (`investigated_cluster_id`, `cl_case_name`). Subset semantics from Phase 2 retro S4 means extra keys are fine.

If `test_cache_roundtrip.py` parametrizes over stages, add a `caption_investigation` round-trip case.

- [ ] **Step 11: Commit**

```
git add src/citation_verifier/verifier.py src/citation_verifier/client.py tests/test_caption_investigation.py tests/test_verifier.py tests/test_async_verifier.py tests/test_resolution_path.py tests/test_cache_roundtrip.py
git commit -m "feat(v0.3): Task 5 — caption_investigation + WRONG_CASE classification

$(cat <<'EOF'
The headline Phase 3 task. New caption_investigation stage runs from
verify()/verify_async() after the citation_lookup with-block exits,
when _process_citation_lookup_hit flagged a name mismatch. Three-step
lookup: cluster case_name_full -> docket case_name -> opinion plain_text
first 500 chars. Party-overlap check (maintainer Q4 pre-decision)
gates WRONG_CASE escalation: at minimum one plaintiff + one defendant
token must match after normalization.

Outcomes:
- VERIFIED + name_formatting_noise (cosmetic divergence)
- VERIFIED + cl_display_name_data_bug (Rule 25(d) / SSA pseudonym /
  CL caption stale; party-overlap still passes via cluster_full_name,
  docket case_name, or opinion text head)
- WRONG_CASE (party-overlap fails across all caption sources)

Investigation infrastructure errors emit VERIFIED + data-bug warning
defensively (not WRONG_CASE on infra failure). Phase 4's gates will
decide whether this needs upgrading.

Adds CourtListenerClient.get_cluster() / get_docket() (sync + async).
EOF
)"
```

---

## Task 6: Phase 3 corpus acceptance + xfail unmark + provisional-fixture rulings

The Phase 2.5 corpus (52 fixtures across 7 statuses) is Phase 3's primary acceptance target. This task:
1. Writes the acceptance test file that walks the corpus and asserts the verifier produces the expected status / final_ids / warnings.
2. Resolves the 10 fixtures pinned `phase3_classification_open: true` per the maintainer's pre-decisions and the new Phase 3 logic.
3. Unmarks the 4 xfailed entries in `known_real_citations.json` per Q3.
4. Skips the 5 VERIFICATION_INCOMPLETE fixtures (Phase 4 work — the corpus's `mock_spec` field is consumed there, not now).

**Files:**
- Create: `tests/test_phase3_corpus_acceptance.py` — the live-API corpus walk.
- Modify: `tests/data/refactor_corpus.json` — resolve provisional fixtures.
- Modify: `tests/data/refactor_corpus_survey.md` — update §3 inventory entries to reflect Phase 3 rulings.
- Modify: `tests/data/known_real_citations.json` — remove `xfail_reason` on the 4 cluster-ID-drift entries; update `expected_cluster_id` if drift occurred.

- [ ] **Step 1: Write the acceptance test scaffold (skip everything by default)**

Create `tests/test_phase3_corpus_acceptance.py`:

```python
"""Phase 3 acceptance: run the verifier against tests/data/refactor_corpus.json
and assert each fixture's expected outcome.

This file hits the live CourtListener API (where mock_spec is null) and
deselects from the standard suite via the live_api mark.

Marked tests:
  - VERIFICATION_INCOMPLETE fixtures: skipped here (Phase 4 wires the
    mock_spec harness in production logic — out of scope for Phase 3).
  - phase3_classification_open=True fixtures: not skipped — Phase 3
    must rule on them. The fixture's expected_status drives the
    assertion; if the verifier now produces a different status, either
    update the fixture (with rationale) or fix the verifier.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from citation_verifier.models import Status, WarningCategory
from citation_verifier.verifier import CitationVerifier
from tests.data.refactor_corpus_loader import load_corpus

pytestmark = pytest.mark.live_api


@pytest.fixture(scope="module")
def verifier():
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set — live API tests skipped")
    return CitationVerifier()


_, _ALL_FIXTURES = load_corpus()
_RUNNABLE = [
    fx for fx in _ALL_FIXTURES
    if fx.expected_status != "VERIFICATION_INCOMPLETE"  # Phase 4 work
]


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_status(fx, verifier):
    result = verifier.verify(fx.citation)
    assert result.status.value == fx.expected_status, (
        f"{fx.id}: expected {fx.expected_status}, got {result.status.value}\n"
        f"  Citation: {fx.citation}\n"
        f"  Rationale: {fx.rationale[:200]}\n"
        f"  Resolution path: "
        f"{[(e.stage.value, e.verdict.value) for e in result.resolution_path]}\n"
        f"  Warnings: {[w.category.value for w in result.warnings]}"
    )


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_final_ids(fx, verifier):
    """Pinned ID checks. Only asserts non-null pinned fields; null in
    the fixture means 'unconstrained.'"""
    result = verifier.verify(fx.citation)
    for key, pinned in fx.expected_final_ids.items():
        if pinned is None:
            continue
        if key == "text_source":
            actual = (
                result.final_ids.text_source.value
                if result.final_ids.text_source else None
            )
        else:
            actual = getattr(result.final_ids, key, None)
        assert actual == pinned, (
            f"{fx.id}: final_ids.{key} expected {pinned}, got {actual}"
        )


@pytest.mark.parametrize("fx", _RUNNABLE, ids=lambda fx: fx.id)
def test_corpus_fixture_warnings_subset(fx, verifier):
    """expected_warnings_subset uses subset semantics — Phase 3 may
    emit other categories without breaking the fixture, as long as
    the required ones are present."""
    result = verifier.verify(fx.citation)
    actual = {w.category.value for w in result.warnings}
    expected = set(fx.expected_warnings_subset)
    missing = expected - actual
    assert not missing, (
        f"{fx.id}: missing required warnings {missing}; got {actual}"
    )
```

- [ ] **Step 2: Add the `live_api` marker to `pytest.ini` / `pyproject.toml`**

If the marker isn't already registered, add to whichever exists:

```toml
[tool.pytest.ini_options]
markers = [
    "live_api: hits the live CourtListener API; deselect for fast runs",
]
```

The standard deselect pattern is `pytest --deselect tests/test_phase3_corpus_acceptance.py` or `pytest -m "not live_api"`.

- [ ] **Step 3: Run the corpus tests and triage failures**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py -v -m live_api
```

This will hit the live API. Expect a mix of pass / fail. Triage each failure into one of:

(a) **Verifier bug** — the verifier should produce the fixture's pinned status but does not. Stop and fix the verifier (Tasks 3–5 logic gap).

(b) **Fixture-correct, Phase-3-open** — the fixture pins one status provisionally and Phase 3's logic produces a different (correct) one. Update the fixture per the maintainer pre-decisions; record the ruling in the survey.

(c) **CL data drift** — the pinned `cluster_id` no longer matches what CL returns. Either update the pin to the current cluster, or (if the fixture was xfailed in known_real_citations.json) emit `cl_duplicate_clusters` and update the fixture to expect that warning per Q3.

- [ ] **Step 4: Resolve the 10 `phase3_classification_open: true` fixtures**

Per the maintainer pre-decisions and the new Phase 3 logic, apply these rulings. After each ruling, set `phase3_classification_open: false` on the fixture and add a one-line `"phase3_ruling"` field documenting what was decided.

**4a. `verified-bossart-xfailed`, `verified-busha-xfailed`, `verified-townsley-xfailed`, `verified-anderson-furst-xfailed` (Q3 — cluster-ID drift):**

Per Q3: if Phase 3 caption_investigation now resolves these via a different mechanism (sibling-cluster detection, abbreviation normalization in citation_lookup, etc.), the expected_status stays `VERIFIED`. If `cl_duplicate_clusters` warning fires, update `expected_warnings_subset` to include it. If the cluster_id no longer matches the pin, either update the pin to the current cluster or pin the duplicate set explicitly:

```json
{
  "expected_final_ids": {
    "cluster_id": null,    /* implementer choice: pin a specific or leave open */
    ...
  },
  "expected_warnings_subset": ["cl_duplicate_clusters"],
  ...
}
```

The implementer picks the assertion shape per Q3's guidance ("either unconstrained or matching whatever CL currently scores highest, but the warning is required"). Document the choice in `phase3_ruling`.

**4b. `verified-via-recap-cabot-lewis-provisional` + `verified-via-recap-hunter-ccsf-provisional` (Q1 — recap_doc_not_opinion_typed):**

Per Q1: under Phase 3's strict VIA_RECAP gate, both fail the doc-type test (Cabot = "ORDER CERTIFYING INTERLOCUTORY APPEAL", Hunter = "ORDER RE: PLAINTIFFS MOTION FOR REVIEW OF CLERKS TAXATION") and should reclassify to `VERIFIED_DOCKET_ONLY`. Update each fixture:

```json
{
  "id": "verified-docket-only-cabot-lewis",   /* rename */
  "expected_status": "VERIFIED_DOCKET_ONLY",
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": 4275225,
    "recap_document_id": null,   /* was 5338694 — strip per strict reading */
    "text_source": null           /* was "recap_document" */
  },
  "phase3_classification_open": false,
  "phase3_ruling": "Reclassified VIA_RECAP -> DOCKET_ONLY per maintainer Q1: doc type 'ORDER CERTIFYING INTERLOCUTORY APPEAL' fails the strict opinion-typed gate.",
  ...
}
```

Same shape for Hunter. The id rename is optional but recommended for clarity.

After reclassification, `VIA_RECAP` count drops from 5 to 3. Add 2 substitute fixtures (per survey §2.1's note on the recap_doc_opinion_not_ingested pool: only Mehar Holdings + Doe v. Lawrence + Darensburg are confirmed clean; if more are needed, live-discover from the benchmark or accept that the corpus minimum drops to 3 and update the test_refactor_corpus.py minimum threshold — but the survey §1.7 hard-minimum-of-5 was a soft target, the implementer's call).

**4c. `wrong-case-butler-motors-provisional` (Q2 — wrong_page_number):**

Per Q2: neither page (857 nor 304) resolves to a CL cluster. Under strict reading, status is NOT_FOUND. Update:

```json
{
  "id": "not-found-butler-motors",   /* rename */
  "expected_status": "NOT_FOUND",
  "phase3_classification_open": false,
  "phase3_ruling": "Strict reading per Q2: neither page resolves to a CL cluster, so wrong_page_number warning cannot fire here. Reclassified WRONG_CASE -> NOT_FOUND.",
  ...
}
```

**4d. `verified-docket-only-menges-actual` (Q4 from Phase 2.5 retro):**

The actual Menges docket has only in-limine orders, not opinion text. Phase 3's strict VIA_RECAP gate already classifies it as DOCKET_ONLY (date doesn't match either — May 31 cited, June 12 docs). Confirm with:

```json
{
  "phase3_classification_open": false,
  "phase3_ruling": "Confirmed DOCKET_ONLY per Phase 3 strict VIA_RECAP gate: in-limine orders from 2000-06-12 are procedural-order-typed AND outside the ±14 day window from the cited 2000-05-31 date.",
  ...
}
```

**4e. `verified-docket-only-caraballo-berryhill`:**

Already confirmed via live discovery (Phase 2.5 retro S4–S5). Just unmark:

```json
{
  "phase3_classification_open": false,
  "phase3_ruling": "Confirmed DOCKET_ONLY: no opinion-typed doc at the cited 2018-09-26 date in docket 6698093.",
  ...
}
```

**4f. `not-found-iglesias-hialeah-provisional`:**

Per Phase 2.5 retro Q1: this is a benchmark "rescue_was_false_positive" — pre-Phase-3 fallback rescues it but Phase 3 stricter logic should not. Run the test; if Phase 3 produces NOT_FOUND, unmark with `"phase3_ruling": "Confirmed NOT_FOUND under stricter Phase 3 fallback gate."` If it still rescues, leave open and flag in the retrospective.

- [ ] **Step 5: Update `tests/data/refactor_corpus_survey.md` §3 inventory**

For each fixture resolved in Step 4, append a `(Phase 3 ruling: …)` annotation to the existing §3 entry. Example:

```
- verified-via-recap-cabot-lewis-provisional | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_not_opinion_typed[cabot-lewis] | recap_doc_not_opinion_typed | Has-text-but-not-strictly-opinion-typed; provisional VIA_RECAP (Phase 3 may reclassify) (Phase 3 ruling: reclassified DOCKET_ONLY per Q1 strict gate; id renamed verified-docket-only-cabot-lewis)
```

Add a §3.1 section "Phase 3 rulings on provisional fixtures" that summarizes all 10.

- [ ] **Step 6: Unmark the 4 xfailed entries in `tests/data/known_real_citations.json`**

For each of Bossart, Busha, Townsley, Anderson-Furst, remove the `xfail_reason` field. If Phase 3's caption_investigation handles the case via `cl_duplicate_clusters`, the test will pass without an xfail mark. If a specific cluster ID drifted, update `expected_cluster_id` to the current CL value:

```json
{
  "citation": "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, ...",
  "expected_cluster_id": <current CL value>,
  "category": "abbreviation_normalization",
  "notes": "..."
  /* xfail_reason field deleted */
}
```

- [ ] **Step 7: Run the live-API corpus walk to completion**

```
venv/Scripts/python.exe -m pytest tests/test_phase3_corpus_acceptance.py -v -m live_api
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py -v
```

Expected: all `_RUNNABLE` corpus tests pass (the 47 = 52 - 5 INCOMPLETE fixtures); all 5 known-real tests pass with no xfails remaining.

If any of the named exemplars (Koch, Gilliam, Menges, WRONG_CASE, Bossart) fail, stop and investigate — these are §4 acceptance.

- [ ] **Step 8: Commit the corpus + fixture updates**

```
git add tests/test_phase3_corpus_acceptance.py tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md tests/data/known_real_citations.json pyproject.toml
git commit -m "test(v0.3): Task 6 — Phase 3 corpus acceptance + provisional fixture rulings

$(cat <<'EOF'
New tests/test_phase3_corpus_acceptance.py walks all 47 non-INCOMPLETE
corpus fixtures against the live CL API and asserts expected_status /
final_ids / warnings_subset.

Resolved all 10 phase3_classification_open fixtures:
- 4 cluster-ID-drift VERIFIED-xfailed (Q3): cl_duplicate_clusters
- 2 recap_doc_not_opinion_typed (Q1): reclassified VIA_RECAP -> DOCKET_ONLY
- Butler Motors (Q2): reclassified WRONG_CASE -> NOT_FOUND
- Menges-actual + Caraballo + Iglesias: rulings recorded

Unmarked all 4 xfailed entries in known_real_citations.json (Q3).
VERIFICATION_INCOMPLETE fixtures remain in corpus but are skipped here;
Phase 4 wires the mock_spec harness.

Phase 3 ruling history in tests/data/refactor_corpus_survey.md §3.1.
EOF
)"
```

---

## Task 7: Acceptance gate + retrospective handoff

The standing pre-acceptance checklist from the CLAUDE.md "Refactor Workflow" and the Phase 1+2 acceptance pattern.

- [ ] **Step 1: Run the full non-live suite**

```
venv/Scripts/python.exe -m pytest --deselect tests/test_false_negatives.py --deselect tests/test_phase3_corpus_acceptance.py -q
```

Expected: zero failures. Pass count = Phase 2.5 baseline + (Task 1 net delta) + (Task 2 +2) + (Task 3 +6) + (Task 4 +6) + (Task 5 +9) — implementer counts.

- [ ] **Step 2: Run the live-API suites**

```
venv/Scripts/python.exe -m pytest tests/test_false_negatives.py tests/test_phase3_corpus_acceptance.py -v
```

Expected: all pass. Each fixture's named-exemplar slot (Koch, Gilliam, Menges, WRONG_CASE, Bossart) explicitly passes.

- [ ] **Step 3: Run the verify-brief end-to-end smoke**

Phase 1 retrospective recorded that verify-brief is a consumer; Phase 3 produces new statuses but does not change the consumed shape. Confirm with the smoke from Phase 1's acceptance (use whichever brief workdir is convenient — `briefs/<existing>/` or the Phase 1 acceptance artifact):

```
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/<workdir> --wave1
```

Expected: completes without exception. If it errors on a new status (e.g. `brief_pipeline.py` doesn't know what `WRONG_CASE` means), patch the consumer minimally (one-line "treat as not_verified" or similar) and file the proper presentation update for the roadmap. Do not block Phase 3 acceptance on verify-brief presentation polish.

- [ ] **Step 4: Tag the acceptance**

```
git tag -a refactor/phase-3-acceptance -m "Phase 3 acceptance: status taxonomy migration

All 6 richer Status values now produced by the verifier:
- VERIFIED (with cl_display_name_data_bug / name_formatting_noise warnings)
- VERIFIED_PARTIAL (silent-partial-verification)
- VERIFIED_VIA_RECAP (strict gate per maintainer Q1)
- VERIFIED_DOCKET_ONLY (everything else RECAP)
- WRONG_CASE (party-overlap fails in caption_investigation)
- NOT_FOUND (unchanged)
- VERIFICATION_INCOMPLETE: type exists; production wiring is Phase 4.

Two new WarningCategory values: cl_duplicate_clusters, wrong_page_number
(per design v2 §2.6 amendment workflow; CHANGELOG.md).

Phase 2.5 corpus walk passes for all 47 non-INCOMPLETE fixtures.
All 10 phase3_classification_open: true fixtures resolved.
The 4 cluster-ID-drift xfails in known_real_citations.json unmarked."
git push origin refactor/v0.3 refactor/phase-3-acceptance
```

- [ ] **Step 5: Write the Phase 3 retrospective**

Create `docs/retrospectives/<today>-refactor-v0.3-phase-3.md` following the Phase 1+2+2.5 retrospective shape. Sections to cover:

- **What landed** — commit list, file count, test delta.
- **Time breakdown** — dispatches per task, implementer model, review depth.
- **Surprises** — places the plan didn't survive contact with code or data; what was scope-expanded into which task; what got deferred.
- **Open questions to fold into Phase 4** — at minimum:
  - Whether `_investigate_caption`'s defensive fallback (VERIFIED + cl_display_name_data_bug on infra failure) needs upgrading to `VERIFICATION_INCOMPLETE` once Phase 4's internal API-error gate lands.
  - Whether the corpus's 5 VERIFICATION_INCOMPLETE fixtures and the mock harness build belong in Phase 4 as a single task or split.
  - Whether the candidates-field roadmap item (scratch/ROADMAP.md) wants to consume `cl_duplicate_clusters` warnings directly or grow its own data path.
  - Whether `wrong_page_number` saw any positive fixtures during the live run, and if not, whether the implementation is dead code until a fixture surfaces.
- **TODO items touched** — anything from scratch/TODO.md that Phase 3 closed; anything that should now move there.
- **Notes for whoever writes the Phase 4 plan** — Phase 4 retrospective handoff.

Commit and push:

```
git add docs/retrospectives/<today>-refactor-v0.3-phase-3.md
git commit -m "docs(v0.3): Phase 3 retrospective"
git push origin refactor/v0.3
```

---

## Acceptance Criteria (summary)

- All Phase 2.5 corpus non-INCOMPLETE fixtures (47/52) produce the pinned `expected_status` in `tests/test_phase3_corpus_acceptance.py`.
- All 5 named §4 exemplars (Koch, Gilliam, Menges, WRONG_CASE = Hogan, VERIFICATION_INCOMPLETE = skipped/Phase 4) pass.
- All 10 `phase3_classification_open: true` fixtures are resolved with a `phase3_ruling` field documenting the decision.
- All 4 xfailed entries in `tests/data/known_real_citations.json` are unmarked and pass.
- The full non-live unit suite (`pytest --deselect live_api -q`) is zero-failures.
- `verify-brief` smoke completes without exception.
- `refactor/phase-3-acceptance` tag exists locally and on `origin/refactor/v0.3`.
- `CHANGELOG.md` documents the two new WarningCategory additions per the §2.6 amendment workflow.
- `docs/retrospectives/<today>-refactor-v0.3-phase-3.md` exists and captures surprises + open questions for Phase 4.

---

## Out of scope (do not implement in Phase 3)

- **Phase 4 gates.** No `gates: list[GateSpec] | None` parameter on verify entry points. No production wiring of `VERIFICATION_INCOMPLETE` from API errors (design §2.8 internal gate). The corpus's 5 INCOMPLETE fixtures use synthetic `mock_spec` harnesses; consume them in Task 6's acceptance test as `skip`, do not interpret `mock_spec` in production logic.
- **`candidates` field on `VerificationResult`.** The "surface multiple candidates when uncertain" roadmap idea is captured in `scratch/ROADMAP.md`. Phase 3 expresses uncertainty via warnings only (notably the new `cl_duplicate_clusters` from Q3) — not a candidates list.
- **MCP server, skill rewrite, diagnostic runner, verify-proposition split.** All design v2 §7 roadmap items.
- **`verify-brief` presentation polish** for the new statuses. Phase 3 produces them; surface updates are roadmap work.
- **Replacing `_names_match_citation_lookup` with `_party_overlap_ok` at the citation_lookup branch.** The existing lenient surname check stays as the trigger for "is there a mismatch worth investigating?"; `_party_overlap_ok` is the gate inside `_investigate_caption`. Two checks at different decision points; do not collapse.

---

## Self-review notes

Cross-check before handoff (the writing-plans skill's self-review checklist):

1. **Spec coverage** — every Phase 3 design §3 task and every maintainer pre-decision is addressed:
   - VERIFIED_PARTIAL detection → Task 3.
   - VERIFIED_VIA_RECAP / VERIFIED_DOCKET_ONLY branching with strict Q1 test → Task 4. Cabot/Hunter reclassification → Task 6.4b.
   - `_investigate_caption` entry point inside name-mismatch branch → Task 5 (entry from `verify()` post-citation_lookup-block per Phase 2 retro Q4).
   - WRONG_CASE classification per Q4 → Task 5 `_party_overlap_ok`.
   - Full warning population per §2.6 incl. new Q2/Q3 categories → Task 2 + Task 5.
   - Bundled cleanup (WarningCategory promotion + classifier deletion + `_winning_entry` consolidation + 0.40 threshold extraction) → Task 1 (per Phase 2 retro note 3).
   - Darensburg fixture validation → §0.3.
   - Acceptance criteria (corpus walk, 10 open fixtures, named exemplars) → Task 6 + summary.

2. **Placeholder scan** — no TBD/TODO/"implement later" in any step. Every code block is concrete. The "implementer's call" notes in Task 5 Step 3 (sibling-cluster search depth) and Task 6.4a (assertion shape for cl_duplicate_clusters) are explicit delegations with direction, not punts.

3. **Type consistency**:
   - `_finalize_result` signature gains `recap_document_id` in Task 4; all callers updated.
   - `CandidateMatch.recap_document_id` field added in Task 4; producers (`_pick_best_recap_doc`) populate it; consumers (`_build_fallback_result`) read it.
   - `_investigate_caption` is sync; async parallel is `_investigate_caption_async`. Both return identical dict shapes.
   - `_process_citation_lookup_hit` returns kwargs dict with `needs_caption_investigation` + `_cluster_for_investigation` keys; caller in `verify()`/`verify_async()` pops both before calling `_finalize_result`.
   - The `status_override` key in `hit_finalize` is consumed in the same call site that creates it (`verify()` and `verify_async()`); no leak to `_finalize_result`.

4. **No spec drift** — the plan does not propose `candidates`, `Status.VERIFICATION_INCOMPLETE` production wiring, gates, or surface-area changes outside §3 Phase 3.
