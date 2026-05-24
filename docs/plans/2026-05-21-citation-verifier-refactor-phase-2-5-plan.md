# Citation Verifier Refactor — Phase 2.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble a structured fixture corpus (~40–50 citations) covering every state in the new six-status taxonomy, sourced primarily from the maintainer's case-law-proposition-benchmark project (which has 250 ground-truthed citations with hand-classified coverage diagnoses).

**Architecture:** A single new JSON file, `tests/data/refactor_corpus.json`, with a versioned schema and a per-fixture `expected_status` field. A thin Python loader in `tests/data/refactor_corpus_loader.py`. Schema-shape and minimum-count tests in `tests/test_refactor_corpus.py`. A companion survey markdown documenting provenance and selection criteria. **Phase 2.5 ships data; it does not ship any verifier-side detection logic** — Phase 3 consumes the corpus to validate the new classification paths.

**Tech Stack:** Python 3.10+, `pytest`, `json`, `dataclasses` for the loader, the Windows venv at `venv/Scripts/python.exe`, the benchmark project at `~/Projects/case-law-proposition-benchmark` as the read-only source.

---

## Background and prior context

Read these in order before starting:

1. **`docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md` §3 Phase 2.5** — the spec this plan implements.
2. **`docs/plans/2026-05-20-citation-verifier-refactor-design-v2.md` §4** — the named exemplars that MUST be in the corpus (Koch, Gilliam, Menges, a WRONG_CASE example, a simulated VERIFICATION_INCOMPLETE).
3. **`docs/retrospectives/2026-05-20-refactor-v0.3-phase-1.md`** — Phase 1 lessons. The `headline_confidence` accessor and `resolution_path` shape are now load-bearing; the fixture format references them.
4. **`docs/retrospectives/2026-05-21-refactor-v0.3-phase-2.md`** — Phase 2 lessons. Phase 2's `ResolutionPathBuilder` and per-stage `raw_response_summary` shapes are what Phase 3 will use; the corpus should reference stage names (`citation_lookup`, `opinion_search`, etc.) but should NOT pin a particular `caption_investigation` shape (Q4 open).
5. **`CLAUDE.md` → "Refactor Workflow" section** — per-session conventions (worktree path, venv, push every session, no merge to main, etc.). Follow it; do not restate it here.
6. **`tests/data/known_real_citations.json` and `tests/data/known_fake_citations.json`** — existing fixture files. The Phase 2.5 corpus is a **new file**, not an extension of these (rationale in §2 below).

## Scope discipline

**Phase 2.5 produces data only.** Do NOT, during this phase:

- Implement any new `StageName`, `WarningCategory`, or `Status` enum values beyond what Phase 1 already shipped.
- Implement `caption_investigation` logic, WRONG_CASE detection, VERIFIED_PARTIAL detection, RECAP-text classification, or gate evaluation.
- Modify `src/citation_verifier/verifier.py`, `src/citation_verifier/resolution_path.py`, `src/citation_verifier/models.py`, or any other production code in `src/`.
- Add new `Warning` categories. Phase 1 shipped a small closed set; Phase 3 will extend it. The fixture format references categories by string name with subset semantics so adding categories later doesn't break the corpus.
- Build a mock harness that runs the verifier against synthetic API errors. Phase 2.5 *declares* mock specs in the fixture file; Phase 3 implements the harness that consumes them.
- Cluster-ID drift fixes (the four xfailed cases in `tests/data/known_real_citations.json`). Phase 3's caption_investigation work is the natural place to revisit those.

**Phase 2.5 ships:** one JSON file, one loader, one test file, one survey markdown, one retrospective. That's the entire delivery.

---

## §0 Setup

- [ ] **0.1 Pull latest origin/main and merge into refactor branch**

```bash
git fetch origin
git checkout refactor/v0.3
git merge origin/main --no-edit
```

Expected: clean merge, or trivial conflicts in `CLAUDE.md`'s refactor workflow section (resolve in favor of the branch's version).

- [ ] **0.2 Confirm the worktree's venv and .env are intact**

```bash
ls venv/Scripts/python.exe
ls .env
```

Expected: both files present. If `.env` is missing, copy from the primary checkout per Phase 1 retrospective S5.

- [ ] **0.3 Confirm Phase 2 baseline tests still pass**

```bash
venv/Scripts/python.exe -m pytest -q --deselect tests/test_false_negatives.py
```

Expected: 284 passed, 5 skipped, 4 xfailed (matching Phase 2 acceptance state). Zero failures.

- [ ] **0.4 Confirm the benchmark project is readable from this session**

```bash
ls "/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/unified_review.csv"
ls "/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/manual_corrections.csv"
ls "/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/recap_diagnosis.csv"
```

Expected: three files exist. **If any path is missing or unreadable, STOP and surface as a blocker** — the benchmark is the primary data source and Phase 2.5 cannot proceed without it. Do not invent fixtures to compensate.

- [ ] **0.5 Read the source files' headers and row counts**

```bash
venv/Scripts/python.exe -c "
import csv
base = '/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot'
for fn in ['unified_review.csv', 'manual_corrections.csv', 'recap_diagnosis.csv']:
    with open(f'{base}/{fn}', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    print(f'{fn}: {len(rows)} rows, {len(header)} cols')
"
```

Expected output:

```
unified_review.csv: 250 rows, 38 cols
manual_corrections.csv: 16 rows, 8 cols
recap_diagnosis.csv: 7 rows, 18 cols
```

---

## §1 Design choices to lock in before coding

This section is not tasks — it documents the decisions baked into the plan so the engineer can sanity-check them before implementation.

### §1.1 File: new file, not extending existing fixtures

`tests/data/known_real_citations.json` and `tests/data/known_fake_citations.json` are not extended. Reasons:

- They have different schemas (`expected_cluster_id` vs `expected_status`) and different consumer patterns (regression test vs documented-hallucination corpus). Mixing six-status fixtures into either forces a schema migration on the consumer test files.
- The Phase 2.5 corpus needs fields the existing files don't have: `expected_status`, `expected_resolving_stage`, `expected_warnings_subset`, `mock_spec` (for VERIFICATION_INCOMPLETE), and a `category` taxonomy aligned to the six statuses rather than to legacy categories like "abbreviation_normalization."
- The new file declares its purpose as the **Phase 3 acceptance corpus**. The existing files keep their existing jobs.

**Cross-references** between files: when a corpus fixture is sourced from one of the existing files, the corpus fixture's `source` field cites the existing file (e.g., `"source": "tests/data/known_fake_citations.json#hogan-att"`). When a corpus fixture is sourced from the benchmark, the `source` field cites the benchmark file + diagnosis label (e.g., `"source": "benchmark/unified_review.csv#cl_cluster_parallel_cite_missing[0]"`).

### §1.2 Single JSON file, not split per status

One file (`tests/data/refactor_corpus.json`) with a top-level `fixtures: []` list and per-fixture `expected_status`. Reasons:

- ~40–50 entries total fit comfortably in one file.
- One loader, one schema-shape test, one counts assertion. Per-status splits would multiply boilerplate.
- Phase 3 parametrization is straightforward (`pytest.mark.parametrize` over the full list, group/filter by status field).

If the file grows past ~100 fixtures in later phases, splitting per status is fine — but Phase 2.5 starts unified.

### §1.3 Status taxonomy: the diagnosis → status translation

The benchmark offshoot already classified every row by `diagnosis`. The translation to the new six-status taxonomy:

| benchmark `diagnosis` | rows | maps to | notes |
|---|---|---|---|
| `in_cl_via_citation_lookup` | 170 | `VERIFIED` | The happy path. Source for the bulk of VERIFIED fixtures. |
| `cl_cluster_citations_empty` | 24 | `VERIFIED` (via opinion_search fallback) | Cluster exists but `citations[]` empty in CL's index; primary lookup misses, fuzzy fallback resolves. Resolving stage is `opinion_search`, not `citation_lookup`. |
| `cl_cluster_parallel_cite_missing` | 5 | `VERIFIED_PARTIAL` | NY A.D.3d cases where the slip-op parallel cite is in CL but the A.D.3d primary cite is not. The Gilliam exemplar pattern. |
| `cl_docket_only_no_cluster` | 7 | `VERIFIED_VIA_RECAP` or `VERIFIED_DOCKET_ONLY` | Sub-classification by `recap_diagnosis.csv` `subreason` — see §1.4 below. |
| `caption_divergence_rule_25d` | 3 | `VERIFIED` + `cl_display_name_data_bug` warning | Rule 25(d) automatic-substitution diverges the caption; same case, different display name. The Koch-pattern. |
| `ssa_pseudonym` | 2 | `VERIFIED` + `cl_display_name_data_bug` warning | SSA cases use plaintiff pseudonyms; CL stores the real name. Same case, different display name. |
| `not_in_cl` | 3 | `NOT_FOUND` | The case truly isn't in CL via any path. |
| `cl_cluster_extraction_mismatch` | 1 | `VERIFIED` + `unparseable_citation` warning (pipeline-side normalization bug) | Probably skipped — the case is real but the fixture would primarily exercise parser normalization, not status classification. |
| `verifier_audit_date_bug` | 1 | `VERIFIED` (with notes) | Real verifier bug; useful as a regression placeholder but not load-bearing for Phase 2.5. Probably skipped. |
| `duplicate_of_fuller_sibling` | 13 | (excluded) | These are short-form citations whose fuller sibling is also in the corpus; procedural dedup, not a status signal. Skip. |
| `excluded_incomplete_citation` | 15 | (excluded) | Pre-filter casualties; not useful as status fixtures. Skip. |
| `extraction_artifact_no_name` | 1 | (excluded) | Pipeline artifact, not status. Skip. |
| `rescue_was_false_positive` | 5 | `NOT_FOUND` (under stricter post-Phase 3 logic) | Cases where the fallback ladder rescued them but the rescue was wrong. The pre-Phase-3 verifier would return VERIFIED with low confidence; the post-Phase-3 verifier should return NOT_FOUND. Mark with `phase3_classification_open: true` and include as exploratory fixtures, not load-bearing. |

### §1.4 RECAP sub-classification (VERIFIED_VIA_RECAP vs VERIFIED_DOCKET_ONLY)

`recap_diagnosis.csv` sub-classifies the 7 `cl_docket_only_no_cluster` rows by `subreason`:

| `subreason` | rows | maps to | rationale |
|---|---|---|---|
| `recap_doc_opinion_not_ingested` | 3 | `VERIFIED_VIA_RECAP` | Available opinion-typed RECAP doc with `plain_text` exists. The verifier can return a usable opinion-text source. `text_source: "recap_document"`. |
| `recap_doc_unavailable` | 2 | `VERIFIED_DOCKET_ONLY` | Docket exists but no available RECAP document. No opinion text retrievable. `text_source: null`. |
| `recap_doc_not_opinion_typed` | 2 | **open (Phase 3 decides)** | Available doc text exists but isn't opinion-typed (e.g., "ORDER CERTIFYING INTERLOCUTORY APPEAL"). Phase 3 must decide whether "has-text-but-not-opinion-typed" is VERIFIED_VIA_RECAP or VERIFIED_DOCKET_ONLY. Mark fixtures with `phase3_classification_open: true`. |

The Phase 3 implementer reads §1.4 from the survey notes when implementing RECAP classification.

### §1.5 The named exemplars from §4

The design's §4 lists five must-include exemplars. None are in the benchmark; they come from the skill's prior development and the maintainer's research notes. Each will be looked up live via CourtListener in §3–§7.

| Exemplar | Cite | Expected status | Source for cluster/doc ID |
|---|---|---|---|
| Koch | `857 F.3d 267` (Koch v. United States — CL displays as "Ricky Koch v. Tote, Incorporated") | `VERIFIED` + `cl_display_name_data_bug` warning | Live lookup via `citation_lookup` — confirm cluster ID and that CL's `case_name` ≠ "Koch v. United States". |
| Gilliam | `201 A.D.3d 83, 88–89` parallel `2021 NY Slip Op 06798` | `VERIFIED_PARTIAL` | Live lookup on `2021 NY Slip Op 06798` (resolves); A.D.3d primary cite does not. |
| Menges | `Menges v. Cliffs Drilling, 2000 WL 765082` | `VERIFIED_VIA_RECAP` | Live lookup. If RECAP doesn't have a usable opinion-typed document for this WL cite, substitute from `recap_diagnosis.csv` `recap_doc_opinion_not_ingested` rows and document the substitution in the survey. |
| WRONG_CASE | (pick from `known_fake_citations.json` `wrong_name_real_citation` entries) | `WRONG_CASE` | The existing file already has ground-truth: Hogan v. AT&T (real cluster 2140439 = U.S. ex rel. Green v. Washington), TIG Ins. Co. v. Carter (= Ogden v. Gibraltar Savings Ass'n), Gallagher v. Wilton Enterprises (= Kenro v. Fax Daily). |
| VERIFICATION_INCOMPLETE | (synthetic) | `VERIFICATION_INCOMPLETE` | A `mock_spec` field declares the simulated failure mode (e.g. `{"stage": "citation_lookup", "failure_mode": "http_500"}`). Phase 3 builds the mock harness. |

### §1.6 The fixture record shape

Every fixture has these fields (required unless marked optional):

```json
{
  "id": "verified-obergefell",
  "citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)",
  "expected_status": "VERIFIED",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": 2812209,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": [],
  "rationale": "Landmark Supreme Court case; primary lookup resolves cleanly. Anchor fixture for the standard VERIFIED happy path.",
  "source": "tests/data/known_real_citations.json#obergefell",
  "category": "happy_path",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

**Field semantics:**

- `id`: stable kebab-case slug. Phase 3 tests parametrize on `id`. Never change once shipped.
- `citation`: input string passed verbatim to `verifier.verify()` (or `verify_batch()`).
- `expected_status`: one of `VERIFIED | VERIFIED_PARTIAL | VERIFIED_VIA_RECAP | VERIFIED_DOCKET_ONLY | WRONG_CASE | NOT_FOUND | VERIFICATION_INCOMPLETE` (matches `Status` enum values in `models.py`).
- `expected_resolving_stage`: one of the stage names from §2.5 of the design doc — `citation_lookup | opinion_search | recap_document_search | recap_docket_search | plain_docket_search | caption_investigation`. May be `null` for `NOT_FOUND` and `VERIFICATION_INCOMPLETE`.
- `expected_final_ids`: at least the IDs the Phase 3 test will assert. Fields the fixture doesn't pin are `null`. All fields are mandatory keys (per design §2.1 — every field present, nullable rather than absent).
- `expected_warnings_subset`: list of `WarningCategory` string names that MUST be present in the verifier's `warnings` output. **Subset semantics** — Phase 3 may add other categories without breaking the fixture (per design §2.6 amendment workflow). If the fixture wants to express "no warnings at all," set it to `[]` AND set `expected_warnings_exact: true` (optional bool, default false). The latter is rare; most fixtures use subset semantics.
- `rationale`: one-or-two-sentence why-this-fixture. Surfaces during test failures.
- `source`: provenance string. See §1.1 for format.
- `category`: free-form sub-pattern label that groups fixtures within a status (e.g., `parallel_cite_ny_adv`, `rule_25d_substitution`, `wrong_case_real_reporter`, `infrastructure_failure_http_500`).
- `phase3_classification_open`: if `true`, the fixture's `expected_status` is provisional and Phase 3 may rule otherwise. Used for `recap_doc_not_opinion_typed`, `rescue_was_false_positive`, and the wrong-page-number sub-case of WRONG_CASE.
- `mock_spec`: only populated for `VERIFICATION_INCOMPLETE` fixtures. Schema:

```json
{
  "stage": "citation_lookup",
  "failure_mode": "http_500",
  "attempt_idx": 0,
  "details": "First call to citation-lookup endpoint returns HTTP 500 with empty body; retry count exhausted."
}
```

`failure_mode` is one of: `http_500`, `http_502`, `http_503`, `http_429_no_retry_after`, `timeout`, `connection_error`, `json_malformed`. Phase 3 builds the mock harness that maps each `failure_mode` to a specific stub behavior.

### §1.7 Per-status target counts

| Status | Target | Hard minimum |
|---|---|---|
| `VERIFIED` | 10 | 5 |
| `VERIFIED_PARTIAL` | 6 | 5 |
| `VERIFIED_VIA_RECAP` | 5 | 5 |
| `VERIFIED_DOCKET_ONLY` | 5 | 5 |
| `WRONG_CASE` | 5 | 5 |
| `NOT_FOUND` | 6 | 5 |
| `VERIFICATION_INCOMPLETE` | 5 | 5 |
| **Total** | **~42** | **35** |

Design §3 Phase 2.5 says "5–10 per status; ~40–60 total." Hitting the lower end of each band is the floor; aim for the upper end where source material is rich (VERIFIED is the easiest to extend; VERIFIED_VIA_RECAP/DOCKET_ONLY are capped at what `recap_diagnosis.csv` provides).

### §1.8 Open questions Phase 3 will need that Phase 2.5 must not foreclose

(From the Phase 1 + Phase 2 retrospectives.)

- **Q4 from Phase 2** — `caption_investigation` entry point (sibling stage vs sub-step of citation_lookup). The fixture format references `caption_investigation` only as a *possible* value of `expected_resolving_stage`; no fixture in Phase 2.5 pins it (Phase 3 will).
- **Q5 from Phase 2** — `cl_display_name_data_bug` warning's exact promotion criteria (when does a name mismatch stay VERIFIED vs escalate to WRONG_CASE?). Phase 2.5 fixtures use the category name; Phase 3 implements the classifier that emits it.
- **Q3 from Phase 2** — `partial` verdict's emission band (per `StageVerdict`). Phase 2.5 fixtures don't pin `verdict` per stage entry; they only pin `expected_resolving_stage`. Phase 3 decides the verdict semantics.
- **Q2 from Phase 1** — `WarningCategory` enum may grow. The fixture's subset semantics on `expected_warnings_subset` accommodates this.
- **Q5 from Phase 1** — `syllabus` field placement. Phase 2.5 fixtures don't reference syllabus.

---

## Files

- **Create:** `tests/data/refactor_corpus.json` — the corpus
- **Create:** `tests/data/refactor_corpus_loader.py` — the loader + a small dataclass for type-safety
- **Create:** `tests/data/refactor_corpus_survey.md` — provenance + selection criteria narrative
- **Create:** `tests/test_refactor_corpus.py` — schema validation + minimum-count tests + named-exemplar presence tests
- **Create:** `docs/retrospectives/2026-05-22-refactor-v0.3-phase-2-5.md` — retrospective at acceptance
- **Do NOT modify:** anything in `src/`, anything in existing tests, anything in `docs/plans/`. (`CLAUDE.md` Refactor Workflow may receive a one-line update if §0.1's merge surfaces a conflict — that's the only existing-file edit anticipated.)

---

## Task 1: Scaffold the corpus file, the loader, and the schema-shape tests

**Files:**
- Create: `tests/data/refactor_corpus.json` (initially with an empty `fixtures` list)
- Create: `tests/data/refactor_corpus_loader.py`
- Create: `tests/test_refactor_corpus.py`

**Why first:** TDD discipline — the schema tests fail until the file is populated (Tasks 3–7). The loader and counts tests are the "loaded by Phase 3's tests" acceptance criterion.

- [ ] **Step 1: Write the empty corpus file**

Create `tests/data/refactor_corpus.json` with this exact content:

```json
{
  "schema_version": "1",
  "description": "Phase 2.5 corpus for citation-verifier refactor v0.3 status taxonomy. Each fixture declares an input citation and the expected verifier result under the six-status taxonomy in models.Status. Consumed by Phase 3 acceptance tests. See tests/data/refactor_corpus_survey.md for provenance and selection criteria.",
  "selection_criteria": [
    "Each of the six statuses has at least 5 fixtures (hard minimum).",
    "The named exemplars from design v2 §4 (Koch, Gilliam, Menges, WRONG_CASE, VERIFICATION_INCOMPLETE) are all present and tagged with category 'named_exemplar'.",
    "Primary source: ~/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/ — 250 ground-truthed citations with hand-classified diagnoses.",
    "Secondary sources: tests/data/known_real_citations.json (anchors), tests/data/known_fake_citations.json (WRONG_CASE + hallucinated NOT_FOUND).",
    "VERIFICATION_INCOMPLETE fixtures are synthetic (mock_spec field declares the simulated failure mode; Phase 3 builds the mock harness).",
    "Provisional classifications use phase3_classification_open: true so Phase 3 can rule without re-curating.",
    "expected_warnings_subset uses subset semantics — Phase 3 may add other warning categories without breaking the fixture."
  ],
  "fixtures": []
}
```

- [ ] **Step 2: Write the loader**

Create `tests/data/refactor_corpus_loader.py`:

```python
"""Loader for the Phase 2.5 refactor corpus.

The corpus is consumed by Phase 3's acceptance tests via load_corpus().
Phase 2.5's own schema-shape tests also consume it via the same loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CORPUS_FILE = Path(__file__).parent / "refactor_corpus.json"

# Mirrors the six-state Status enum in src/citation_verifier/models.py.
# Duplicated here as strings so this loader stays decoupled from the
# verifier package's import surface (Phase 3 may parametrize without
# pulling in the verifier).
_VALID_STATUSES = {
    "VERIFIED",
    "VERIFIED_PARTIAL",
    "VERIFIED_VIA_RECAP",
    "VERIFIED_DOCKET_ONLY",
    "WRONG_CASE",
    "NOT_FOUND",
    "VERIFICATION_INCOMPLETE",
}

_VALID_STAGES = {
    "citation_lookup",
    "opinion_search",
    "recap_document_search",
    "recap_docket_search",
    "plain_docket_search",
    "caption_investigation",
}


@dataclass(frozen=True)
class Fixture:
    id: str
    citation: str
    expected_status: str
    expected_resolving_stage: str | None
    expected_final_ids: dict[str, Any]
    expected_warnings_subset: list[str]
    rationale: str
    source: str
    category: str
    phase3_classification_open: bool = False
    mock_spec: dict[str, Any] | None = None
    expected_warnings_exact: bool = False


def load_corpus(path: Path | None = None) -> tuple[dict[str, Any], list[Fixture]]:
    """Load the corpus file. Returns (metadata, fixtures).

    metadata is the top-level dict minus the fixtures key.
    fixtures is a list of Fixture dataclasses.
    """
    target = path or _CORPUS_FILE
    with open(target, encoding="utf-8") as f:
        raw = json.load(f)
    fixtures = [Fixture(**fx) for fx in raw["fixtures"]]
    metadata = {k: v for k, v in raw.items() if k != "fixtures"}
    return metadata, fixtures


def fixtures_by_status(fixtures: list[Fixture]) -> dict[str, list[Fixture]]:
    """Group fixtures by expected_status."""
    out: dict[str, list[Fixture]] = {s: [] for s in _VALID_STATUSES}
    for fx in fixtures:
        out[fx.expected_status].append(fx)
    return out
```

- [ ] **Step 3: Write the schema-shape and counts tests**

Create `tests/test_refactor_corpus.py`:

```python
"""Phase 2.5 acceptance tests for the refactor corpus.

These tests do NOT call the verifier. They validate the corpus file's
schema, count fixtures per status, and verify the named exemplars from
design v2 §4 are present. Phase 3's tests run the verifier against
each fixture.
"""

from __future__ import annotations

import pytest

from tests.data.refactor_corpus_loader import (
    Fixture,
    _VALID_STAGES,
    _VALID_STATUSES,
    fixtures_by_status,
    load_corpus,
)


@pytest.fixture(scope="module")
def corpus():
    metadata, fixtures = load_corpus()
    return metadata, fixtures


def test_metadata_has_required_fields(corpus):
    metadata, _ = corpus
    assert metadata["schema_version"] == "1"
    assert metadata["description"]
    assert isinstance(metadata["selection_criteria"], list)
    assert len(metadata["selection_criteria"]) >= 4


def test_ids_are_unique(corpus):
    _, fixtures = corpus
    ids = [fx.id for fx in fixtures]
    assert len(ids) == len(set(ids)), "Duplicate fixture ids"


def test_status_values_are_valid(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        assert fx.expected_status in _VALID_STATUSES, fx.id


def test_resolving_stage_values_are_valid(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        if fx.expected_resolving_stage is not None:
            assert fx.expected_resolving_stage in _VALID_STAGES, fx.id


def test_unresolved_statuses_have_null_stage(corpus):
    """NOT_FOUND and VERIFICATION_INCOMPLETE don't resolve — stage must be null."""
    _, fixtures = corpus
    for fx in fixtures:
        if fx.expected_status in {"NOT_FOUND", "VERIFICATION_INCOMPLETE"}:
            assert fx.expected_resolving_stage is None, (
                f"{fx.id}: unresolved status must have null expected_resolving_stage"
            )


def test_final_ids_are_dict(corpus):
    """expected_final_ids must always be a dict (possibly with null values),
    never absent. Per design §2.1: every field present, nullable rather
    than absent."""
    _, fixtures = corpus
    required_keys = {
        "cluster_id",
        "opinion_id",
        "docket_id",
        "recap_document_id",
        "text_source",
    }
    for fx in fixtures:
        assert isinstance(fx.expected_final_ids, dict), fx.id
        assert required_keys.issubset(fx.expected_final_ids.keys()), (
            f"{fx.id}: expected_final_ids missing keys: "
            f"{required_keys - fx.expected_final_ids.keys()}"
        )


def test_text_source_values_are_valid(corpus):
    """text_source values must be from the closed set in design §2.4."""
    _, fixtures = corpus
    valid = {"opinion_plain_text", "opinion_html", "recap_document", None}
    for fx in fixtures:
        ts = fx.expected_final_ids["text_source"]
        assert ts in valid, f"{fx.id}: text_source={ts!r} not in {valid}"


def test_mock_spec_only_for_verification_incomplete(corpus):
    """mock_spec is populated only for VERIFICATION_INCOMPLETE fixtures."""
    _, fixtures = corpus
    valid_modes = {
        "http_500",
        "http_502",
        "http_503",
        "http_429_no_retry_after",
        "timeout",
        "connection_error",
        "json_malformed",
    }
    for fx in fixtures:
        if fx.expected_status == "VERIFICATION_INCOMPLETE":
            assert fx.mock_spec is not None, f"{fx.id}: mock_spec required"
            assert fx.mock_spec["stage"] in _VALID_STAGES, fx.id
            assert fx.mock_spec["failure_mode"] in valid_modes, fx.id
        else:
            assert fx.mock_spec is None, (
                f"{fx.id}: mock_spec only valid for VERIFICATION_INCOMPLETE"
            )


def test_rationale_and_source_nonempty(corpus):
    _, fixtures = corpus
    for fx in fixtures:
        assert fx.rationale.strip(), fx.id
        assert fx.source.strip(), fx.id


@pytest.mark.parametrize("status", sorted(_VALID_STATUSES))
def test_minimum_fixtures_per_status(corpus, status):
    """Design §3 Phase 2.5 acceptance: each status has at least 5 fixtures."""
    _, fixtures = corpus
    grouped = fixtures_by_status(fixtures)
    assert len(grouped[status]) >= 5, (
        f"{status}: only {len(grouped[status])} fixtures (need >= 5)"
    )


@pytest.mark.parametrize(
    "exemplar_id, expected_status",
    [
        ("named-exemplar-koch", "VERIFIED"),
        ("named-exemplar-gilliam", "VERIFIED_PARTIAL"),
        ("named-exemplar-menges", "VERIFIED_VIA_RECAP"),
        ("named-exemplar-wrong-case", "WRONG_CASE"),
        ("named-exemplar-verification-incomplete", "VERIFICATION_INCOMPLETE"),
    ],
)
def test_named_exemplars_present(corpus, exemplar_id, expected_status):
    """Design §4 acceptance: the named exemplars are in the corpus."""
    _, fixtures = corpus
    by_id = {fx.id: fx for fx in fixtures}
    assert exemplar_id in by_id, f"Missing named exemplar: {exemplar_id}"
    assert by_id[exemplar_id].expected_status == expected_status
    assert by_id[exemplar_id].category == "named_exemplar"
```

- [ ] **Step 4: Run the tests; confirm they fail on the empty corpus**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected: the metadata, ID-uniqueness, value-validity, mock-spec, and rationale tests pass (file is well-formed but empty). The 7 `test_minimum_fixtures_per_status` cases FAIL (zero fixtures < 5). The 5 `test_named_exemplars_present` cases FAIL (no exemplars yet). **This is the desired state for TDD** — the failing tests are what the next tasks will turn green.

- [ ] **Step 5: Commit the scaffold**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_loader.py tests/test_refactor_corpus.py
git commit -m "$(cat <<'EOF'
test(v0.3): scaffold Phase 2.5 corpus + schema tests

Empty refactor_corpus.json + loader + schema-shape tests.
12 schema-shape tests pass on the empty file. The 7
test_minimum_fixtures_per_status and 5 test_named_exemplars_present
tests fail intentionally — they turn green as Tasks 3-7 populate
fixtures.
EOF
)"
```

- [ ] **Step 6: Push**

```bash
git push origin refactor/v0.3
```

---

## Task 2: Write the survey markdown (provenance + selection criteria narrative)

**Files:**
- Create: `tests/data/refactor_corpus_survey.md`

**Why now:** the survey doc documents the diagnosis→status mapping and the named-exemplar sourcing. Writing it before Task 3–7 forces the engineer to think through the mapping once, then mechanically populate from it. Also serves as the "selection criteria documented inline so future additions follow the same shape" deliverable (design §3 Phase 2.5 task list).

- [ ] **Step 1: Write the survey markdown**

Create `tests/data/refactor_corpus_survey.md` with this content (copy verbatim — sections come from §1 of this plan, which the engineer has already vetted):

```markdown
# Phase 2.5 Refactor Corpus — Survey and Selection Criteria

## Purpose

This document is the audit trail for `tests/data/refactor_corpus.json`.
It records the diagnosis→status mapping, the source rows used for each
fixture, and the selection criteria so future additions follow the same
shape.

If the corpus needs to grow in Phase 3+ (e.g., when a regression
surfaces), the rule is: identify which source pool the new fixture
comes from (benchmark, existing fixture, synthetic), classify the
status using the §2 mapping table, populate per the §1.6 record shape
in `docs/plans/2026-05-21-citation-verifier-refactor-phase-2-5-plan.md`,
and add a row to §3 below.

## §1 Selection criteria

1. **Coverage:** every status has at least 5 fixtures with meaningful
   sub-case variety (per §2 mapping table).
2. **Named exemplars from design v2 §4 are present:** Koch (VERIFIED +
   cl_display_name_data_bug), Gilliam (VERIFIED_PARTIAL), Menges
   (VERIFIED_VIA_RECAP), a WRONG_CASE example, a synthetic
   VERIFICATION_INCOMPLETE. Tagged with `category: "named_exemplar"`.
3. **Rationale-rich, not bulk:** each fixture's `rationale` explains
   why it earns a slot. Many fixtures map to "the same kind of edge
   case" — pick one or two; do not stuff all 24
   `cl_cluster_citations_empty` rows into the corpus.
4. **Provenance traceable:** every fixture's `source` field cites a
   specific row in the benchmark (`benchmark/unified_review.csv#<diagnosis>[<idx>]`),
   a specific entry in an existing fixture file
   (`tests/data/known_*.json#<id>`), or `design_v2_doc#section_4` for
   the named exemplars.
5. **Phase 3 doesn't get foreclosed:** fixtures with provisional
   `expected_status` use `phase3_classification_open: true`. The
   classification gets confirmed (or revised) when Phase 3's logic
   lands.

## §2 Diagnosis → status mapping

(Sourced from `~/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/`.
The `diagnosis` column on `unified_review.csv` is the load-bearing
classifier; `recap_diagnosis.csv` `subreason` sub-classifies the
`cl_docket_only_no_cluster` rows.)

| benchmark `diagnosis` | rows | maps to status | notes |
|---|---|---|---|
| `in_cl_via_citation_lookup` | 170 | `VERIFIED` | Standard happy path. Sample ~6 from this pool by tier diversity (SCOTUS/Circuit/District/State_COLR/State_IAC). |
| `cl_cluster_citations_empty` | 24 | `VERIFIED` (via opinion_search) | Resolving stage is `opinion_search`, not `citation_lookup`. Sample 2 with a brief note explaining the fallback path. |
| `cl_cluster_parallel_cite_missing` | 5 | `VERIFIED_PARTIAL` | All 5 are NY A.D.3d / slip-op cases. Include all 5; this is the Gilliam-shape population. |
| `cl_docket_only_no_cluster` | 7 | `VERIFIED_VIA_RECAP` or `VERIFIED_DOCKET_ONLY` | Sub-classify via `recap_diagnosis.csv` subreason — see §2.1. |
| `caption_divergence_rule_25d` | 3 | `VERIFIED` + `cl_display_name_data_bug` | Include all 3. |
| `ssa_pseudonym` | 2 | `VERIFIED` + `cl_display_name_data_bug` | Include both. |
| `not_in_cl` | 3 | `NOT_FOUND` | Include all 3. |
| `cl_cluster_extraction_mismatch` | 1 | (excluded) | Tests parser normalization, not status. Skip. |
| `verifier_audit_date_bug` | 1 | (excluded) | Real verifier bug; placeholder for future regression work, not a status fixture. Skip. |
| `duplicate_of_fuller_sibling` | 13 | (excluded) | Dedup artifact. Skip. |
| `excluded_incomplete_citation` | 15 | (excluded) | Pre-filter casualties. Skip. |
| `extraction_artifact_no_name` | 1 | (excluded) | Pipeline artifact. Skip. |
| `rescue_was_false_positive` | 5 | `NOT_FOUND` (provisional) | Mark `phase3_classification_open: true`. Pre-Phase-3 verifier rescues these incorrectly; Phase 3 should reject them. Include 1–2 as exploratory. |

### §2.1 RECAP sub-classification (`cl_docket_only_no_cluster` rows)

| `recap_diagnosis.csv` `subreason` | rows | maps to status | notes |
|---|---|---|---|
| `recap_doc_opinion_not_ingested` | 3 | `VERIFIED_VIA_RECAP` | Opinion-typed doc with text exists; opinion cluster not ingested. Phase 3 verifier will return the RECAP doc as the text source. Include all 3. |
| `recap_doc_unavailable` | 2 | `VERIFIED_DOCKET_ONLY` | No available RECAP document. `text_source: null`. Include both. |
| `recap_doc_not_opinion_typed` | 2 | **provisional (Phase 3 decides)** | Has text but isn't opinion-typed. Mark `phase3_classification_open: true`. Include both — Phase 3 needs them to settle the classification. |

## §3 Fixture inventory (filled in by Tasks 3–7)

(After each populate task, append a one-line entry here per fixture
added, in this format:

```
- <id> | <status> | <source> | <category> | <rationale (truncated)>
```

This is the index used by future contributors.)

(empty — populated by Tasks 3–7 below)

## §4 Named exemplars — sourcing notes

### Koch (VERIFIED + cl_display_name_data_bug)
- Citation: `Koch v. United States, 857 F.3d 267 (5th Cir. 2017)` (the
  caption as a brief would cite).
- Expected CL behavior: `citation_lookup` resolves `857 F.3d 267`; the
  returned `case_name` is "Ricky Koch v. Tote, Incorporated" (or
  similar Tote-named variant). The verifier's name matcher flags a
  mismatch; Phase 3's `caption_investigation` confirms it's the same
  case (CL data-bug, not a wrong case).
- **How to populate:** run a one-off `citation_lookup` against
  `857 F.3d 267` via the venv'd Python; record cluster_id, opinion_id,
  absolute_url, and the divergent CL case_name in the fixture.

### Gilliam (VERIFIED_PARTIAL)
- Citation: `Gilliam v. <opposing>, 201 A.D.3d 83, 88–89, 2021 NY Slip Op 06798 (N.Y. App. Div. 2021)`
- Expected: A.D.3d primary cite does NOT resolve via `citation_lookup`
  (NY A.D.3d coverage is the cl_cluster_parallel_cite_missing pattern);
  the `2021 NY Slip Op 06798` parallel does resolve. Status:
  `VERIFIED_PARTIAL`.
- **How to populate:** look up the Gilliam slip-op cite via
  CourtListener. If the exact Gilliam case isn't readily found, the
  5 cl_cluster_parallel_cite_missing rows (Gold/Wallace, Hersko/Hersko,
  Dondorfer, Kumar, Walker) are analogous Gilliam-shapes and one of
  them can carry the `named_exemplar` tag instead. Document the
  substitution here if so.

### Menges (VERIFIED_VIA_RECAP)
- Citation: `Menges v. Cliffs Drilling, 2000 WL 765082 (E.D. La. May 31, 2000)`
  (illustrative; verify exact details).
- Expected: WL cite. `citation_lookup` misses (no opinion cluster in
  CL); RECAP has the actual docket and a usable opinion-typed
  `RECAPDocument`. Status: `VERIFIED_VIA_RECAP`.
- **How to populate:** look up `2000 WL 765082` via CL search +
  RECAP search. If Menges doesn't have a usable RECAP doc with text,
  substitute from the 3 `recap_doc_opinion_not_ingested` rows
  (Mehar Holdings / Doe v. Lawrence / Darensburg v. MTC are all
  confirmed RECAP-text-available). Document the substitution here.

### WRONG_CASE (pick from `known_fake_citations.json`)
- Best candidate: `Hogan v. AT&T, Inc., 917 F. Supp. 1275, 1280 (S.D. Tex. 1994)`
  — actual case at this reporter: `U.S. ex rel. Green v. Washington`,
  cluster `2140439` (D.D.C., not S.D. Tex). Real reporter, completely
  different parties. Clean WRONG_CASE.
- Alternative: `TIG Ins. Co. v. Carter, 640 S.W.2d 232 (Tex. 1982)`
  — actual case: `Ogden v. Gibraltar Savings Ass'n`.
- Alternative: `Gallagher v. Wilton Enterprises, 962 F. Supp. 1162 (E.D. Pa. 1997)`
  — actual case: `Kenro, Inc. v. Fax Daily, Inc.`.
- All three have ground-truth populated in `known_fake_citations.json`.
- **Not Butler Motors** (wrong page number, same case). Phase 3 may
  classify that as `NOT_FOUND` or as a separate status — include it
  with `phase3_classification_open: true` but do NOT use it as the
  named exemplar.

### VERIFICATION_INCOMPLETE (synthetic)
- Five mock specs covering the documented failure modes — HTTP 500,
  HTTP 429 with exhausted retries, timeout, connection_error,
  json_malformed.
- One is tagged `category: "named_exemplar"` (suggest the HTTP 500 on
  citation_lookup; it's the canonical "primary lookup errored" case).
- Phase 3 builds the mock harness; Phase 2.5 only declares the specs.
```

- [ ] **Step 2: Confirm the file is well-formed**

```bash
venv/Scripts/python.exe -c "
from pathlib import Path
p = Path('tests/data/refactor_corpus_survey.md')
assert p.exists(); assert p.stat().st_size > 4000
print(f'survey: {p.stat().st_size} bytes OK')
"
```

Expected: prints the byte count above 4000.

- [ ] **Step 3: Commit**

```bash
git add tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
docs(v0.3): Phase 2.5 corpus survey + selection criteria

Audit trail for refactor_corpus.json. Documents the
benchmark-diagnosis -> six-status mapping, the named-exemplar
sourcing (Koch, Gilliam, Menges, WRONG_CASE, VERIFICATION_INCOMPLETE),
and the selection criteria so Phase 3+ additions follow the same
shape. §3 inventory is empty; Tasks 3-7 populate it.
EOF
)"
git push origin refactor/v0.3
```

---

## Task 3: Populate `VERIFIED` + `NOT_FOUND` fixtures (bulk from existing sources)

**Files:**
- Modify: `tests/data/refactor_corpus.json`
- Modify: `tests/data/refactor_corpus_survey.md` (append to §3 inventory)

**Goal:** add 10 VERIFIED + 6 NOT_FOUND fixtures from already-classified sources. After this task, the `test_minimum_fixtures_per_status` cases for VERIFIED and NOT_FOUND turn green.

- [ ] **Step 1: Extract the 6 benchmark in-CL-via-lookup candidates**

Run this one-off survey script (does not write production code; just produces the candidate list):

```bash
venv/Scripts/python.exe -c "
import csv
from pathlib import Path
base = Path('/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot')
with open(base/'unified_review.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

# Goal: 6 happy-path VERIFIED fixtures with tier diversity.
# Pick 1 SCOTUS, 1 Circuit, 1 District, 1 State_COLR, 1 State_IAC,
# plus 1 more from any tier — prefer one that exercises
# abbreviation_normalization (case name with Cnty./Dep't/Corp.).
by_tier = {}
for r in rows:
    if r['diagnosis'] == 'in_cl_via_citation_lookup':
        by_tier.setdefault(r['cited_tier'], []).append(r)

for tier, group in by_tier.items():
    print(f'--- {tier}: {len(group)} candidates; showing first 3 ---')
    for r in group[:3]:
        print(f'  cite={r[\"citation_string\"]!r} name={r[\"cited_case_name\"]!r} url={r[\"p4_matched_url\"][:80]}')
"
```

Pick 6 rows by hand: one per tier (5 tiers) plus one bonus. Record their `citation_string`, `cited_case_name`, `p4_matched_url`, and `p4_matched_name` (which carries the matched cluster ID via the URL).

- [ ] **Step 2: Extract the cluster ID from each chosen URL**

For each chosen row, the URL has the form `https://www.courtlistener.com/opinion/<cluster_id>/<slug>/`. Extract the integer cluster_id.

- [ ] **Step 3: Edit `refactor_corpus.json` and add the VERIFIED fixtures**

Add ~10 fixture objects to the `fixtures: []` list:

- 4 from `tests/data/known_real_citations.json` — the Obergefell anchor (not xfailed) plus the 4 currently-xfailed ones. (Including the xfailed ones is intentional: Phase 3's caption_investigation may rescue them; the fixtures pin the expected post-Phase-3 outcome. Mark them with `phase3_classification_open: true` and a rationale that names the xfail.)
- 6 from the benchmark in_cl_via_citation_lookup sample (Step 1 selections).

One fully-worked template (the rest follow this shape):

```json
{
  "id": "verified-obergefell",
  "citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)",
  "expected_status": "VERIFIED",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": 2812209,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": [],
  "rationale": "Landmark SCOTUS case; primary lookup resolves cleanly. Anchor fixture for the standard VERIFIED happy path.",
  "source": "tests/data/known_real_citations.json#obergefell",
  "category": "happy_path",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For the `cl_cluster_citations_empty` candidates (use 2 of them, e.g. Occidental Permian and Sundown Energy from `manual_corrections.csv`), set:

```json
{
  ...
  "expected_resolving_stage": "opinion_search",
  "rationale": "Cluster exists in CL but citations[] is empty; primary lookup misses, opinion_search fuzzy fallback resolves. Sub-case of VERIFIED via fallback path.",
  "source": "benchmark/unified_review.csv#cl_cluster_citations_empty[0]",
  "category": "fallback_opinion_search",
  ...
}
```

For the xfailed `known_real_citations.json` entries, set:

```json
{
  ...
  "rationale": "Pre-Phase-3 xfail (CL cluster-ID drift). Phase 3's caption_investigation may rescue. expected_final_ids.cluster_id pinned to the originally-canonical ID; Phase 3 confirms or updates.",
  "source": "tests/data/known_real_citations.json#bossart",
  "category": "fallback_recap",
  "phase3_classification_open": true,
  ...
}
```

- [ ] **Step 4: Add the 6 NOT_FOUND fixtures**

- 3 from benchmark `not_in_cl` rows. Source format: `benchmark/unified_review.csv#not_in_cl[<idx>]`.
- 3 from `known_fake_citations.json` `hallucinated_case` entries (Bloomberg, Head, Gibbs are the clearest fabricated-from-thin-air examples).

Template:

```json
{
  "id": "not-found-bloomberg",
  "citation": "Bloomberg L.P. v. Bd. of Govs. of the Fed. Reserve Sys., 649 F. 3d 651, 657 (D.C. Cir. 2011)",
  "expected_status": "NOT_FOUND",
  "expected_resolving_stage": null,
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": null
  },
  "expected_warnings_subset": [],
  "rationale": "Court-confirmed hallucinated citation from a sanctioned AI-generated brief (Gonzalez v. TTRA, S.D. Tex. 2025). Plausible D.C. Cir. format, no case exists.",
  "source": "tests/data/known_fake_citations.json#bloomberg",
  "category": "hallucinated_case",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For the `rescue_was_false_positive` exploratory inclusion (1–2 fixtures), add `"phase3_classification_open": true` and the rationale: "Pre-Phase-3 fallback rescues this incorrectly; Phase 3 stricter logic should return NOT_FOUND. Carries `phase3_classification_open: true` until confirmed."

- [ ] **Step 5: Append the inventory rows to the survey markdown**

After each fixture, add a one-line entry to `tests/data/refactor_corpus_survey.md` §3:

```
- verified-obergefell | VERIFIED | tests/data/known_real_citations.json#obergefell | happy_path | Landmark SCOTUS anchor
- not-found-bloomberg | NOT_FOUND | tests/data/known_fake_citations.json#bloomberg | hallucinated_case | Court-confirmed AI hallucination
... (one row per fixture)
```

- [ ] **Step 6: Run schema-shape + counts tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected:
- All `test_*` schema-shape tests pass.
- `test_minimum_fixtures_per_status[VERIFIED]` passes (≥5).
- `test_minimum_fixtures_per_status[NOT_FOUND]` passes (≥5).
- The other 5 `test_minimum_fixtures_per_status` cases still fail.
- All 5 `test_named_exemplars_present` cases still fail.

- [ ] **Step 7: Commit**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
test(v0.3): Phase 2.5 corpus — VERIFIED + NOT_FOUND fixtures

10 VERIFIED + 6 NOT_FOUND fixtures from known_real_citations.json,
known_fake_citations.json, and the benchmark
in_cl_via_citation_lookup / not_in_cl pools. Schema-shape tests
green; per-status minimum counts green for these two statuses.
Other status minimums still fail (Tasks 4-7 populate).
EOF
)"
git push origin refactor/v0.3
```

---

## Task 4: Populate `VERIFIED` (display-name-bug sub-case) + `VERIFIED_PARTIAL` + Koch and Gilliam exemplars

**Files:**
- Modify: `tests/data/refactor_corpus.json`
- Modify: `tests/data/refactor_corpus_survey.md` (append to §3 inventory)

**Goal:** add 5 `VERIFIED` + `cl_display_name_data_bug` fixtures (Rule 25(d) + SSA pseudonym + Koch) and 6 `VERIFIED_PARTIAL` fixtures (NY A.D.3d slip-op parallels + Gilliam). After this task, `VERIFIED_PARTIAL` turns green and two named exemplars (Koch, Gilliam) are present.

- [ ] **Step 1: Read the 3 Rule 25(d) + 2 SSA pseudonym rows from manual_corrections.csv**

```bash
venv/Scripts/python.exe -c "
import csv
from pathlib import Path
base = Path('/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot')
with open(base/'manual_corrections.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
for r in rows:
    if r['diagnosis_override'] in {'caption_divergence_rule_25d', 'ssa_pseudonym'}:
        print(r['diagnosis_override'], '|', r['citation_string'], '|', r['cl_matched_name_override'], '|', r['corrected_url'])
"
```

Expected: 5 rows print (3 Rule 25(d) + 2 SSA). Cross-reference each `citation_string` back to `unified_review.csv` to get the original `cited_case_name` (the brief's claimed caption).

- [ ] **Step 2: Add the 5 `cl_display_name_data_bug` VERIFIED fixtures + the Koch named exemplar**

Template for one:

```json
{
  "id": "verified-rule-25d-gilliard",
  "citation": "Gilliard v. McWilliams, 2019 WL 3304707",
  "expected_status": "VERIFIED",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": 4642011,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": ["cl_display_name_data_bug"],
  "rationale": "Rule 25(d) automatic substitution caused brief caption to diverge from CL's display caption. Same case; CL's display name is the cl_display_name_data_bug pattern.",
  "source": "benchmark/manual_corrections.csv#caption_divergence_rule_25d[0]",
  "category": "rule_25d_substitution",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For Koch, the named exemplar (look up live via CL — see survey doc §4):

```json
{
  "id": "named-exemplar-koch",
  "citation": "Koch v. United States, 857 F.3d 267 (5th Cir. 2017)",
  "expected_status": "VERIFIED",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": <LOOKED_UP>,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": ["cl_display_name_data_bug"],
  "rationale": "Design v2 §4 named exemplar. CL's case_name for 857 F.3d 267 is 'Ricky Koch v. Tote, Incorporated' (or similar); the brief cites it as 'Koch v. United States'. Caption investigation confirms it IS the right case; CL's display name is the bug.",
  "source": "design_v2_doc#section_4",
  "category": "named_exemplar",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

**Looking up Koch's cluster_id:** run one citation-lookup against `857 F.3d 267`:

```bash
venv/Scripts/python.exe -c "
from citation_verifier.client import CourtListenerClient
import os
from dotenv import load_dotenv
load_dotenv()
client = CourtListenerClient(api_token=os.environ['COURTLISTENER_API_TOKEN'])
result = client.lookup_citation('857 F.3d 267')
import json
print(json.dumps(result, indent=2, default=str)[:2000])
"
```

Read the printed `cluster_id` and `case_name`. Confirm the case_name is NOT "Koch v. United States" (this is the data bug). Plug the cluster_id into the fixture.

If the lookup fails or CL has fixed the data bug since the design doc was written, document in the survey doc and pick an analogous fixture from `caption_divergence_rule_25d` rows instead (re-tag with `category: "named_exemplar"`).

- [ ] **Step 3: Add the 5 `VERIFIED_PARTIAL` fixtures (NY A.D.3d slip-op parallels) + Gilliam exemplar**

The 5 candidates from `manual_corrections.csv`:

| citation_string | cl_matched_name | corrected_url |
|---|---|---|
| `230 AD3d 1113` | `Gold v. Wallace` | `/opinion/10114438/gold-v-wallace/` |
| `224 AD3d 810` | `Hersko v. Hersko` | `/opinion/9477252/hersko-v-hersko/` |
| `235 AD3d 71` | `People v. Dondorfer` | `/opinion/10298541/people-v-dondorfer/` |
| `242 AD3d 1231` | `People v. Kumar` | `/opinion/10717850/people-v-kumar/` |
| `228 AD3d 1318` | `People v. Walker` | `/opinion/9880367/people-v-walker/` |

Each fixture's citation should include both the A.D.3d cite (which won't resolve) and the slip-op cite (which will). Look up the corresponding NY Slip Op cite for each: it's the field that DID resolve. Pull from `p4_matched_url` in `unified_review.csv` or by hitting CL.

Template:

```json
{
  "id": "verified-partial-gold-wallace",
  "citation": "Gold v. Wallace, 230 A.D.3d 1113 (N.Y. App. Div. 2024) (citing 2024 NY Slip Op <NN>)",
  "expected_status": "VERIFIED_PARTIAL",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": 10114438,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": ["silent_partial_verification"],
  "rationale": "NY A.D.3d primary cite is not in CL's citation index. The parallel NY Slip Op cite resolves; status VERIFIED_PARTIAL.",
  "source": "benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[0]",
  "category": "parallel_cite_ny_adv",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For Gilliam, the named exemplar. **Note:** the design doc names Gilliam specifically (`201 A.D.3d 83, 88–89` parallel `2021 NY Slip Op 06798`). Look up `2021 NY Slip Op 06798` via CL:

```bash
venv/Scripts/python.exe -c "
from citation_verifier.client import CourtListenerClient
import os
from dotenv import load_dotenv
load_dotenv()
client = CourtListenerClient(api_token=os.environ['COURTLISTENER_API_TOKEN'])
result = client.lookup_citation('2021 NY Slip Op 06798')
import json
print(json.dumps(result, indent=2, default=str)[:2000])
"
```

If Gilliam resolves, plug the cluster_id into the Gilliam fixture. If the exact Gilliam slip-op doesn't resolve, pick one of the 5 parallel_cite fixtures above and re-tag it with `category: "named_exemplar"` and `id: "named-exemplar-gilliam"`. Document the substitution in the survey doc §4.

- [ ] **Step 4: Append inventory rows to the survey markdown §3**

(Same format as Task 3 Step 5.)

- [ ] **Step 5: Run schema-shape + counts tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected:
- All schema-shape tests still pass.
- `test_minimum_fixtures_per_status[VERIFIED]` still green (now ~15).
- `test_minimum_fixtures_per_status[VERIFIED_PARTIAL]` newly green.
- `test_named_exemplars_present[named-exemplar-koch-VERIFIED]` newly green.
- `test_named_exemplars_present[named-exemplar-gilliam-VERIFIED_PARTIAL]` newly green.
- Other counts and exemplars still fail.

- [ ] **Step 6: Commit**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
test(v0.3): Phase 2.5 corpus — display-name-bug VERIFIED + VERIFIED_PARTIAL

5 VERIFIED + cl_display_name_data_bug fixtures (Rule 25(d) + SSA
pseudonym) + Koch named exemplar; 5 VERIFIED_PARTIAL fixtures (NY
A.D.3d slip-op parallel pattern) + Gilliam named exemplar.

Koch / Gilliam cluster IDs resolved live via citation_lookup;
substitutions (if any) documented in
tests/data/refactor_corpus_survey.md §4.
EOF
)"
git push origin refactor/v0.3
```

---

## Task 5: Populate `VERIFIED_VIA_RECAP` + `VERIFIED_DOCKET_ONLY` + Menges exemplar

**Files:**
- Modify: `tests/data/refactor_corpus.json`
- Modify: `tests/data/refactor_corpus_survey.md`

**Goal:** add 5 `VERIFIED_VIA_RECAP` (the 3 `recap_doc_opinion_not_ingested` rows + Menges + 1 follow-up) and 5 `VERIFIED_DOCKET_ONLY` (2 `recap_doc_unavailable` + 2 `recap_doc_not_opinion_typed` + 1 follow-up). After this, both statuses turn green and the Menges named exemplar is present.

- [ ] **Step 1: Read `recap_diagnosis.csv` and confirm the sub-classification**

```bash
venv/Scripts/python.exe -c "
import csv
from pathlib import Path
base = Path('/c/Users/Rebecca Fordon/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot')
with open(base/'recap_diagnosis.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
for r in rows:
    print(r['subreason'], '|', r['citation_string'], '|', r['cited_case_name'], '|', r['docket_url'][-80:], '|', r['has_plain_text'])
"
```

Expected: 7 rows, 3 `recap_doc_opinion_not_ingested` (Mehar Holdings, Doe v. Lawrence, Darensburg), 2 `recap_doc_unavailable` (Dias deapocalypse bey v. Clapprood, Hazari LLC), 2 `recap_doc_not_opinion_typed` (Cabot v. Lewis, Hunter v. City and County of San Francisco).

- [ ] **Step 2: Add the 3 `VERIFIED_VIA_RECAP` fixtures from `recap_doc_opinion_not_ingested` rows**

Template (Mehar Holdings example):

```json
{
  "id": "verified-via-recap-mehar-holdings",
  "citation": "Mehar Holdings, LLC v. Evanston Ins. Co., 2016 WL 5957681 (W.D. Tex. Oct. 14, 2016)",
  "expected_status": "VERIFIED_VIA_RECAP",
  "expected_resolving_stage": "recap_docket_search",
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": 5474769,
    "recap_document_id": 18720567,
    "text_source": "recap_document"
  },
  "expected_warnings_subset": [],
  "rationale": "WL cite. citation_lookup misses (no opinion cluster in CL). RECAP archive has the docket with an opinion-typed RECAPDocument carrying plain_text. Status: VERIFIED_VIA_RECAP. Sub-case: recap_doc_opinion_not_ingested.",
  "source": "benchmark/recap_diagnosis.csv#recap_doc_opinion_not_ingested[0]",
  "category": "recap_doc_opinion_not_ingested",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

Repeat for Doe v. Lawrence (`2025 WL 2808055`, docket 69539673, doc 454203499) and Darensburg (`2009 WL 2392094`, docket 4182878, doc 13644995).

- [ ] **Step 3: Add the Menges named exemplar**

Look up `2000 WL 765082` via the verifier's `verify_batch` flow. Capture the resolved IDs:

```bash
venv/Scripts/python.exe -c "
import asyncio, os, json
from dotenv import load_dotenv
load_dotenv()
from citation_verifier import CitationVerifier

async def main():
    verifier = CitationVerifier()
    result = await verifier.verify_batch(['Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. May 31, 2000)'])
    for r in result.values() if isinstance(result, dict) else result:
        print('status:', r.status)
        print('final_ids:', r.final_ids)
        print('path:', [(p.stage, p.verdict) for p in r.resolution_path])

asyncio.run(main())
"
```

(If the exact API differs, adapt; the goal is to confirm Menges resolves via RECAP. The above is illustrative.)

If Menges resolves cleanly via RECAP, build the named exemplar fixture with the looked-up IDs:

```json
{
  "id": "named-exemplar-menges",
  "citation": "Menges v. Cliffs Drilling Co., 2000 WL 765082 (E.D. La. May 31, 2000)",
  "expected_status": "VERIFIED_VIA_RECAP",
  "expected_resolving_stage": "recap_docket_search",
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": <LOOKED_UP>,
    "recap_document_id": <LOOKED_UP>,
    "text_source": "recap_document"
  },
  "expected_warnings_subset": [],
  "rationale": "Design v2 §4 named exemplar. WL cite; no opinion cluster in CL. RECAP archive has the docket with an opinion-typed RECAPDocument carrying plain_text. Walks the citation_lookup -> opinion_search -> recap_docket_search fallback ladder.",
  "source": "design_v2_doc#section_4",
  "category": "named_exemplar",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

If Menges doesn't resolve via RECAP (CL data may have changed since the design doc was written), promote one of the 3 `recap_doc_opinion_not_ingested` fixtures to the named exemplar instead. Document in the survey doc §4.

- [ ] **Step 4: Add 1 follow-up `VERIFIED_VIA_RECAP` fixture**

The corpus needs 5 fixtures in this status. With the 3 `recap_doc_opinion_not_ingested` rows + Menges, we have 4. Add 1 more — pull from the `cl_cluster_citations_empty` pool (24 rows, several involve RECAP-rescued cases) by selecting one where the row's final URL is `/docket/.../` (RECAP) rather than `/opinion/.../` (cluster). Document in the survey.

Alternative: if the survey doesn't surface a clean RECAP-via-cluster-empty candidate, accept 4 fixtures in this status and document the gap. The hard minimum is 5; the design doc says "5–10," so 5 is required.

- [ ] **Step 5: Add the 4 `VERIFIED_DOCKET_ONLY` fixtures from recap_diagnosis**

Template (Hazari LLC example, `recap_doc_unavailable`):

```json
{
  "id": "verified-docket-only-hazari-llc",
  "citation": "Hazari LLC v. Everest Indem. Ins. Co., 2020 WL 1969530 (S.D. Tex. Apr. 24, 2020)",
  "expected_status": "VERIFIED_DOCKET_ONLY",
  "expected_resolving_stage": "recap_docket_search",
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": 16348672,
    "recap_document_id": null,
    "text_source": null
  },
  "expected_warnings_subset": [],
  "rationale": "Docket exists in CL but no available RECAP document (is_available=false on the cited entry). No retrievable opinion text. Status: VERIFIED_DOCKET_ONLY.",
  "source": "benchmark/recap_diagnosis.csv#recap_doc_unavailable[0]",
  "category": "recap_doc_unavailable",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For the 2 `recap_doc_not_opinion_typed` rows (Cabot v. Lewis, Hunter v. CCSF):

```json
{
  "id": "verified-docket-only-cabot-lewis-provisional",
  "citation": "Cabot v. Lewis, 2015 WL 13648107, at *1 (D. Mass. July 9, 2015)",
  "expected_status": "VERIFIED_DOCKET_ONLY",
  "expected_resolving_stage": "recap_docket_search",
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": 4275225,
    "recap_document_id": null,
    "text_source": null
  },
  "expected_warnings_subset": [],
  "rationale": "Docket has an available RECAP document with plain_text, but the document is not opinion-typed (description: 'ORDER CERTIFYING INTERLOCUTORY APPEAL'). Phase 3 must decide whether 'has-text-but-not-opinion-typed' is VIA_RECAP or DOCKET_ONLY. Provisional classification: DOCKET_ONLY.",
  "source": "benchmark/recap_diagnosis.csv#recap_doc_not_opinion_typed[0]",
  "category": "recap_doc_not_opinion_typed",
  "phase3_classification_open": true,
  "mock_spec": null
}
```

- [ ] **Step 6: Add 1 follow-up `VERIFIED_DOCKET_ONLY` fixture to hit 5**

We have 4 (2 + 2). Pull 1 more from the broader `cl_docket_only_no_cluster` pool — there are 7 rows in `unified_review.csv` with this diagnosis; pick one not already in recap_diagnosis. Look up its docket ID via the URL.

- [ ] **Step 7: Append inventory rows + commit**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
test(v0.3): Phase 2.5 corpus — VERIFIED_VIA_RECAP + VERIFIED_DOCKET_ONLY

5 VERIFIED_VIA_RECAP fixtures (3 recap_doc_opinion_not_ingested
rows + Menges named exemplar + 1 follow-up); 5 VERIFIED_DOCKET_ONLY
fixtures (2 recap_doc_unavailable + 2 recap_doc_not_opinion_typed
[provisional, phase3_classification_open] + 1 follow-up).

Menges cluster/docket/document IDs resolved live; any
substitution documented in survey doc §4.
EOF
)"
git push origin refactor/v0.3
```

- [ ] **Step 8: Run tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected: `VERIFIED_VIA_RECAP` and `VERIFIED_DOCKET_ONLY` minimums green. Menges named exemplar present. 2 status minimums (WRONG_CASE, VERIFICATION_INCOMPLETE) and 2 named exemplars still fail.

---

## Task 6: Populate `WRONG_CASE` + the named exemplar

**Files:**
- Modify: `tests/data/refactor_corpus.json`
- Modify: `tests/data/refactor_corpus_survey.md`

**Goal:** add 5 `WRONG_CASE` fixtures from `known_fake_citations.json` `wrong_name_real_citation` entries plus 1 follow-up. After this, `WRONG_CASE` turns green and the WRONG_CASE named exemplar is present.

- [ ] **Step 1: Add the 4 wrong_name_real_citation fixtures + 1 named exemplar tag**

The four candidates from `known_fake_citations.json`:

1. **Hogan v. AT&T, 917 F. Supp. 1275, 1280 (S.D. Tex. 1994)** — actual cluster `2140439` = "U.S. ex rel. Green v. Washington, 917 F. Supp. 1275 (D.D.C. 1994)". Cleanest WRONG_CASE — different parties, different court.

2. **TIG Ins. Co. v. Carter, 640 S.W.2d 232, 237 (Tex. 1982)** — actual case "Ogden v. Gibraltar Savings Ass'n". (cluster ID not provided in known_fake; look up if needed)

3. **Gallagher v. Wilton Enterprises, 962 F. Supp. 1162 (E.D. Pa. 1997)** — actual case "Kenro, Inc. v. Fax Daily, Inc." (S.D. Ind. 1997).

4. **Butler Motors, Inc. v. Benosky, 181 N.E.3d 857 (Ind. Ct. App. 2021)** — same case, wrong page number. Real case at `181 N.E.3d 304`. Mark `phase3_classification_open: true` — Phase 3 may classify this as NOT_FOUND (page number doesn't match) rather than WRONG_CASE (parties match).

Template (Hogan — the cleanest, suggest tagging as the named exemplar):

```json
{
  "id": "named-exemplar-wrong-case",
  "citation": "Hogan v. AT&T, Inc., 917 F. Supp. 1275, 1280 (S.D. Tex. 1994)",
  "expected_status": "WRONG_CASE",
  "expected_resolving_stage": "citation_lookup",
  "expected_final_ids": {
    "cluster_id": 2140439,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": "opinion_plain_text"
  },
  "expected_warnings_subset": [],
  "rationale": "Design v2 §4 named exemplar. Real reporter (917 F. Supp. 1275) resolves to 'U.S. ex rel. Green v. Washington', not 'Hogan v. AT&T'. Court-confirmed hallucination from Gonzalez v. TTRA sanctions order (S.D. Tex. 2025). Classic WRONG_CASE shape: real reporter, completely different parties.",
  "source": "tests/data/known_fake_citations.json#hogan-att",
  "category": "named_exemplar",
  "phase3_classification_open": false,
  "mock_spec": null
}
```

For the others, replace `category: "named_exemplar"` with `category: "wrong_case_real_reporter"`. Butler Motors gets `phase3_classification_open: true` and a rationale that explains why.

`expected_final_ids.cluster_id` for these is the cluster ID of the *actual* case at the cited reporter (not the brief's fake one). This matches design §2.4: "for WRONG_CASE: the IDs point to the case the reporter actually resolves to."

- [ ] **Step 2: Add 1 follow-up WRONG_CASE fixture to hit the floor**

We have 4 with the wrong_name_real_citation candidates. We need 5. Pull 1 more from `tests/data/known_fake_citations.json` entries or look one up. The simplest path: add the Shell Petroleum hallucinated_case row, which `notes` documents resolves to a different case ('Faghri v. University of Connecticut'). Verify by hitting CL on `608 F. Supp. 2d 269`; if it does resolve to a different case, build a WRONG_CASE fixture. Otherwise leave it as a NOT_FOUND (Phase 3 confirms).

- [ ] **Step 3: Append inventory rows + commit**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
test(v0.3): Phase 2.5 corpus — WRONG_CASE fixtures + named exemplar

5 WRONG_CASE fixtures from known_fake_citations.json
wrong_name_real_citation entries (Hogan named exemplar + 3 others +
Butler Motors provisional). Butler Motors marked
phase3_classification_open because Phase 3 may classify the
wrong-page-number sub-case as NOT_FOUND.

expected_final_ids.cluster_id pins the actual case the reporter
resolves to (per design §2.4), not the brief's fake citation.
EOF
)"
git push origin refactor/v0.3
```

- [ ] **Step 4: Run tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected: `WRONG_CASE` minimum green. Named exemplar present. Only `VERIFICATION_INCOMPLETE` and its named exemplar still failing.

---

## Task 7: Populate `VERIFICATION_INCOMPLETE` synthetic fixtures + the named exemplar

**Files:**
- Modify: `tests/data/refactor_corpus.json`
- Modify: `tests/data/refactor_corpus_survey.md`

**Goal:** add 5 synthetic `VERIFICATION_INCOMPLETE` fixtures with `mock_spec` declarations. Phase 3 implements the mock harness; Phase 2.5 only declares specs. After this task, all 7 status minimums and all 5 named exemplars are green.

- [ ] **Step 1: Add 5 VERIFICATION_INCOMPLETE fixtures with diverse mock_spec failure modes**

Each fixture uses a real-looking citation as input (helps the mock harness select the right behavior) but the `expected_status` is `VERIFICATION_INCOMPLETE` because the mocked infrastructure failure prevents resolution. Use citations from known_real_citations so the mock harness has a known cluster to substitute with, but the assertion is "this should NOT resolve to that cluster — it should be VERIFICATION_INCOMPLETE."

Template 1 (the named exemplar — HTTP 500 on citation_lookup):

```json
{
  "id": "named-exemplar-verification-incomplete",
  "citation": "Obergefell v. Hodges, 576 U.S. 644 (2015)",
  "expected_status": "VERIFICATION_INCOMPLETE",
  "expected_resolving_stage": null,
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": null
  },
  "expected_warnings_subset": [],
  "rationale": "Design v2 §4 named exemplar. Simulated HTTP 500 from CourtListener on the primary citation_lookup endpoint. Per design §2.8 internal gate, the verifier must produce VERIFICATION_INCOMPLETE rather than silently degrade to NOT_FOUND. The citation itself is real (Obergefell) — the mock harness substitutes the failure response.",
  "source": "design_v2_doc#section_4",
  "category": "named_exemplar",
  "phase3_classification_open": false,
  "mock_spec": {
    "stage": "citation_lookup",
    "failure_mode": "http_500",
    "attempt_idx": 0,
    "details": "First (and only) attempted call to /api/rest/v4/citation-lookup/ returns HTTP 500 with empty body. Retry policy exhausted."
  }
}
```

Template 2 (HTTP 429 with no Retry-After, exhausted retries):

```json
{
  "id": "verification-incomplete-rate-limit-exhausted",
  "citation": "Bossart v. King Cnty., 2025 WL 459154 (W.D. Wash. Feb. 11, 2025)",
  "expected_status": "VERIFICATION_INCOMPLETE",
  "expected_resolving_stage": null,
  "expected_final_ids": {
    "cluster_id": null,
    "opinion_id": null,
    "docket_id": null,
    "recap_document_id": null,
    "text_source": null
  },
  "expected_warnings_subset": [],
  "rationale": "Simulated HTTP 429 from CourtListener on every retry attempt for citation_lookup, with no parseable Retry-After or wait_until field. The verifier's existing 429-retry logic in client.py exhausts after 3 attempts and the stage records verdict=errored. Status: VERIFICATION_INCOMPLETE.",
  "source": "design_v2_doc#section_2_8",
  "category": "infrastructure_failure_rate_limit",
  "phase3_classification_open": false,
  "mock_spec": {
    "stage": "citation_lookup",
    "failure_mode": "http_429_no_retry_after",
    "attempt_idx": 2,
    "details": "All 3 retries return HTTP 429 with empty body."
  }
}
```

Templates 3–5: timeout, connection_error, json_malformed. Vary the `stage` so we exercise multi-stage VERIFICATION_INCOMPLETE — at least one fixture should have `stage: "opinion_search"` (citation_lookup returns clean no_match, then the fallback errors).

For the `opinion_search` variant:

```json
{
  "id": "verification-incomplete-opinion-search-timeout",
  "citation": "Anderson v. Furst, No. 17-cv-12676, 2018 WL 4407750 (E.D. Mich. Sept. 17, 2018)",
  "expected_status": "VERIFICATION_INCOMPLETE",
  "expected_resolving_stage": null,
  "expected_final_ids": { "cluster_id": null, "opinion_id": null, "docket_id": null, "recap_document_id": null, "text_source": null },
  "expected_warnings_subset": [],
  "rationale": "citation_lookup returns clean no_match (Anderson WL cite not in CL index). opinion_search fallback times out. Per design §2.8: a single late-stage timeout cannot silently degrade to NOT_FOUND. The resolution_path must record citation_lookup with verdict=no_match AND opinion_search with verdict=errored.",
  "source": "design_v2_doc#section_2_8",
  "category": "infrastructure_failure_timeout",
  "phase3_classification_open": false,
  "mock_spec": {
    "stage": "opinion_search",
    "failure_mode": "timeout",
    "attempt_idx": 0,
    "details": "opinion_search returns clean response for citation_lookup but the subsequent fuzzy-fallback search exceeds the 15s client timeout."
  }
}
```

- [ ] **Step 2: Append inventory + commit**

```bash
git add tests/data/refactor_corpus.json tests/data/refactor_corpus_survey.md
git commit -m "$(cat <<'EOF'
test(v0.3): Phase 2.5 corpus — VERIFICATION_INCOMPLETE specs

5 synthetic VERIFICATION_INCOMPLETE fixtures, each with a mock_spec
field declaring the simulated infrastructure failure. Covers
HTTP 500, HTTP 429 with exhausted retries, timeout (citation_lookup
and opinion_search variants), connection_error, json_malformed.
The named exemplar is HTTP 500 on citation_lookup. Phase 3 builds
the mock harness consuming these specs.
EOF
)"
git push origin refactor/v0.3
```

- [ ] **Step 3: Run all tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_refactor_corpus.py -v
```

Expected: **all green**. 7/7 `test_minimum_fixtures_per_status` cases pass. 5/5 `test_named_exemplars_present` cases pass.

---

## Task 8: Acceptance gate + retrospective + tag

**Files:**
- Create: `docs/retrospectives/2026-05-22-refactor-v0.3-phase-2-5.md`

- [ ] **Step 1: Full repo test run (excluding live API)**

```bash
venv/Scripts/python.exe -m pytest -q --deselect tests/test_false_negatives.py
```

Expected: matching the Phase 2 baseline (284 passed, 5 skipped, 4 xfailed) **plus** the new `tests/test_refactor_corpus.py` cases (count depends on parametrization — at least 7 status minimums + 5 named exemplars + ~10 schema-shape tests = ~22 new passes). Zero failures.

- [ ] **Step 2: Print corpus summary**

```bash
venv/Scripts/python.exe -c "
from tests.data.refactor_corpus_loader import load_corpus, fixtures_by_status
metadata, fixtures = load_corpus()
print(f'schema_version: {metadata[\"schema_version\"]}')
print(f'total fixtures: {len(fixtures)}')
print()
print('per status:')
for status, lst in sorted(fixtures_by_status(fixtures).items()):
    print(f'  {status:30s} {len(lst):3d}')
print()
print('named exemplars:')
for fx in fixtures:
    if fx.category == 'named_exemplar':
        print(f'  {fx.id} -> {fx.expected_status}')
"
```

Expected: ~42 fixtures total, ≥5 per status, all 5 named exemplars listed.

- [ ] **Step 3: Write the retrospective**

Create `docs/retrospectives/2026-05-22-refactor-v0.3-phase-2-5.md` with sections matching Phase 1/2's retrospective shape:

```markdown
# Phase 2.5 Retrospective — citation-verifier v0.3 corpus assembly

**Branch:** `refactor/v0.3`
**Plan:** `docs/plans/2026-05-21-citation-verifier-refactor-phase-2-5-plan.md`
**Acceptance tag:** `refactor/phase-2.5-acceptance`
**Phase duration:** <one session / multiple>

## What landed

<list of commits from Task 1 through Task 8>

## Surprises (what the plan didn't survive contact with data)

<S1, S2, ... — any source-row substitutions, named-exemplar lookup
failures, RECAP classification edge cases that Phase 3 will need
to know about>

## Open questions to fold into Phase 3's plan

<Q1, Q2, ... — anything about the corpus's coverage gaps,
provisional classifications that Phase 3 must rule on,
mock_spec semantics that need refinement>

## TODO items touched during Phase 2.5

<from scratch/TODO.md, if any>

## Notes for whoever writes the Phase 3 plan

1. **Read tests/data/refactor_corpus_survey.md first.** The §2 mapping
   table is the contract between the data and Phase 3's classification
   logic.
2. **`phase3_classification_open: true` fixtures need rulings.** List
   them and decide.
3. **Mock harness shape.** Phase 2.5 declared mock_spec fields. Phase 3
   builds the harness — recommend implementing as a pytest fixture
   that monkey-patches the AsyncCourtListenerClient methods based on
   the spec.
4. **The recap_doc_not_opinion_typed gray area.** Phase 3 must decide
   whether "has-text-but-not-opinion-typed" maps to VERIFIED_VIA_RECAP
   or VERIFIED_DOCKET_ONLY. Two fixtures wait for this ruling.
```

- [ ] **Step 4: Commit the retrospective**

```bash
git add docs/retrospectives/2026-05-22-refactor-v0.3-phase-2-5.md
git commit -m "$(cat <<'EOF'
docs(v0.3): Phase 2.5 retrospective

What landed, surprises, open questions for Phase 3. See
docs/plans/2026-05-21-citation-verifier-refactor-phase-2-5-plan.md
for the plan and tests/data/refactor_corpus_survey.md for the
data audit trail.
EOF
)"
```

- [ ] **Step 5: Tag the acceptance**

```bash
git tag refactor/phase-2.5-acceptance
git push origin refactor/v0.3
git push origin refactor/phase-2.5-acceptance
```

- [ ] **Step 6: Confirm the tag**

```bash
git tag --list refactor/phase-*
```

Expected output includes `refactor/phase-1-acceptance`, `refactor/phase-2-acceptance`, `refactor/phase-2.5-acceptance`.

---

## Acceptance checklist (from design v2 §3 Phase 2.5)

- [x] **The fixture file exists.** `tests/data/refactor_corpus.json` — yes (Task 1, populated by Tasks 3–7).
- [x] **The fixture file is loaded by Phase 3's tests.** The loader is `tests/data/refactor_corpus_loader.py`. Phase 2.5's own `tests/test_refactor_corpus.py` exercises the loader, satisfying "loaded by tests."
- [x] **Each of the six statuses has at least five fixtures.** Enforced by `test_minimum_fixtures_per_status` (parametrized across all six). Plus VERIFICATION_INCOMPLETE counts as the seventh `Status` enum value; the test runs over all of them.
- [x] **The named exemplars from §4 are all present.** Enforced by `test_named_exemplars_present` (parametrized across the five exemplars).

---

## Self-review

### Spec coverage

Per design v2 §3 Phase 2.5 task list:

- "Survey the benchmark and its offshoot for citations matching each of the six new statuses (and meaningful sub-cases — caption-investigation paths, parallel-cite paths, RECAP paths, docket-only paths, wrong-case paths, infrastructure-failure paths for VERIFICATION_INCOMPLETE)." → Task 2 (survey doc) + Tasks 3–7 (population).
- "Build a structured fixture file (suggested: tests/data/refactor_corpus.json or split per status) cataloging the curated citations with: input string, expected status, expected key warnings, expected resolving stage, ground-truth IDs where applicable, a one-line rationale for inclusion." → Task 1 (scaffold) + Tasks 3–7 (population). All required fields in the §1.6 record shape.
- "Aim for 5–10 fixtures per status; ~40–60 total." → §1.7 targets; counts test enforces minimum 5.
- "Document the corpus's selection criteria so future additions follow the same shape." → Task 2 + the top-level `selection_criteria` field in the JSON.

### Type/method consistency

- The Fixture dataclass field names match the JSON keys exactly (`expected_status`, `expected_resolving_stage`, etc.).
- The validation tests reference the same field names.
- The fixture template in §1.6 matches what every example fixture in Tasks 3–7 produces.
- `_VALID_STATUSES` covers all 7 Status values (including VERIFICATION_INCOMPLETE — design §2.2 lists six "states" but the enum has 7 values counting VERIFICATION_INCOMPLETE; the survey doc's "six-status taxonomy" framing is from the design's prose, which is the same six core resolution states + the seventh failure-mode status). The plan and tests should treat all 7 as valid.

Wait — actually look at this carefully. Design §2.2 enumerates six total: VERIFIED, VERIFIED_PARTIAL, VERIFIED_VIA_RECAP, VERIFIED_DOCKET_ONLY, WRONG_CASE, NOT_FOUND. Then §2.2 ends with VERIFICATION_INCOMPLETE as a seventh state under "Unresolved states." That's seven status values total. The "six-status taxonomy" framing in §3 Phase 2.5 is a colloquial shortcut; the per-status minimum count needs to apply to all seven. The plan's §1.7 reflects this (7 rows totaling ~42 fixtures).

### Placeholder scan

- No "TBD" or "implement later" in any step.
- Every code/JSON template is complete.
- Looked-up cluster IDs use the placeholder `<LOOKED_UP>` with explicit lookup instructions; this is the one acceptable placeholder pattern because the value can only be obtained at execution time.

---

## Execution handoff

Plan complete and saved to `docs/plans/2026-05-21-citation-verifier-refactor-phase-2-5-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks. Phase 2.5 is data-dense and benefits from a controller-checks-each-task discipline. Suggested split: setup + Task 1 inline; Tasks 2–7 each via subagent with light spot-checks; Task 8 inline by controller.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
