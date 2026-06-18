# DE-279 Case-Citation Validation — LQ.AI Port Plan (case_resolver.py)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Contribute LQ.AI's unbuilt DE-279 ("case citation validation") by porting this repo's name-match verification logic into `lq-ai`, so a resolved reporter citation is checked against the *asserted* case name — catching the name-swap fabrication that their current thin `verify_citations` tool misses.

**Architecture:** A new api-side module `api/app/citation/case_resolver.py` that (1) detects Bluebook citations + their asserted case names in text, (2) resolves them via the **existing** gateway-brokered `research.verify_citations` (no new CourtListener egress — ADR 0014 stays intact), (3) compares the asserted name to the resolved cluster's `case_name` with the lenient surname-containment matcher this repo uses post-resolution, and emits a per-citation verdict (`verified` / `wrong_case` / `unresolved` / `unverifiable`). Exposed as a stateless `POST /api/v1/research/validate-citations` endpoint. **This is PR-A** — api-only, which is the lightest review path (a maintainer merges; an outside contributor can't self-merge). Chat-pipeline auto-run, the `message_case_citations` table, and the web chip/Cypress E2E are **PR-B** (outlined at the end; gets its own plan once `chats.py`/`web/` are read against `main`).

**Tech Stack:** Python (FastAPI + httpx + SQLAlchemy 2.0 async), pytest + respx, ruff, mypy. The ported matcher imports only stdlib `re` + `difflib` — **zero new dependencies** (matches lq-ai's no-new-SBOM-dep posture).

## Global Constraints

- **No new runtime dependency.** The matcher port uses only `re` + `difflib`. Do **not** add `eyecite` — CourtListener does server-side citation extraction; client-side detection here is regex-only. (Richer eyecite normalizations are a documented PR-B/follow-up.)
- **No direct CourtListener calls (ADR 0014).** All CL access goes through `app.research.service.verify_citations(text)` → `GatewayClient.call_tool`. The resolver never touches `courtlistener.com`.
- **api-only PR (lightest review path).** Do not modify `gateway/**` — that triggers the `gateway/**` security-review gate; staying api-only keeps the PR off it. (You're an outside contributor — a maintainer reviews and merges; you can't self-merge.) No `gateway.yaml` changes in PR-A (the operator-config flag is a PR-B concern, since PR-A's endpoint is opt-in by virtue of being a distinct route).
- **CI gates that bite:** `ruff format --check api scripts` AND `ruff check api`; `mypy` (api standard). A new route requires: add it to `IMPLEMENTED_ROUTES` (a `set[tuple[str, str]]` of `(METHOD, path)`) in `api/tests/test_endpoints.py` AND add the path to the `EXPECTED_PATHS` frozenset + bump `assert len(actual) == 127` → `128` in `api/tests/test_openapi.py` (**verified 127 on 2026-06-18**; both the frozenset and the count are load-bearing).
- **Tests need Postgres on a throwaway port:** `DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai'` against a disposable pgvector container (`docker run -d --name lq-test-pg -p 15433:5432 -e POSTGRES_USER=lq_ai -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lq_ai pgvector/pgvector:pg16`). Run via the host venv (`cd api && .venv/bin/pytest`), not docker-compose. PR-A's resolver unit tests need **no** DB; only the endpoint test touches the app.
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Stage files explicitly (never `git add -A`).
- **Fork-and-PR only.** This is an outside contribution — never push to `legalquants/lq-ai`. `origin` = your fork (`rlfordon/lq-ai`, the only push target); `upstream` = `legalquants/lq-ai`, read-only (fetch + the PR). The Kickoff prompt below repoints the remotes so an accidental upstream push fails.

---

## Kickoff prompt (copy verbatim into a fresh session, rooted in `Projects/lq-ai`)

```text
Implement PR-A of the DE-279 case-citation-validation plan in this lq-ai repo.
This is a Windows machine and lq-ai's tooling assumes Unix — use the Windows paths
below, and surface any Windows-specific build friction (asyncpg, alembic, etc.)
instead of forcing through. This is a FORK-AND-PR contribution: never push to
legalquants/lq-ai; push only to the fork and open a PR.

Step 0 — fork, repoint remotes (so push can't hit upstream), update, set up env:
  # Outside-contributor copy: origin = legalquants/lq-ai, NO push access, and stale
  # (EXPECTED_PATHS=73, predates the research subsystem). Fork is mandatory.
  gh repo fork legalquants/lq-ai --clone=false --remote=false
  git remote rename origin upstream
  git remote add origin https://github.com/rlfordon/lq-ai.git   # origin = YOUR fork; push only goes here
  git remote set-url --push upstream no-push                     # belt-and-suspenders: block accidental upstream push
  git fetch upstream
  git reset --hard upstream/main          # gets the CourtListener/research subsystem; EXPECTED_PATHS -> 127
  git checkout -b feat/de-279-case-resolver

  cd api
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -e ".[dev]"
  docker run -d --name lq-test-pg -p 15433:5432 -e POSTGRES_USER=lq_ai -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lq_ai pgvector/pgvector:pg16

  # Confirm a GREEN baseline before changing anything (PowerShell):
  $env:DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai'
  .venv\Scripts\python.exe -m pytest -q

Then copy the plan in from the citation-verifier repo and read it in full:
  docs/plans/2026-06-18-de279-lq-ai-case-resolver-port.md
Execute Tasks 1-6 task-by-task (TDD: failing test -> watch fail -> minimal impl ->
green -> commit) using superpowers:executing-plans or subagent-driven-development.
PR-B is a separate later plan — do not start it.

Goal: a resolved reporter citation gets checked against the *asserted* case name,
catching the name-swap fabrication the thin verify_citations tool misses. New module
api/app/citation/case_resolver.py + POST /api/v1/research/validate-citations that reuses
the gateway-brokered CourtListener tool (app.research.service — no direct CL call, ADR 0014).

Hard constraints:
- api-only. Do NOT touch gateway/** (keeps the PR off the gateway/** security-review gate — lightest review path; a maintainer merges).
- No new runtime dependency (matcher port is stdlib re+difflib; no eyecite).
- New route: add to IMPLEMENTED_ROUTES (tests/test_endpoints.py) AND EXPECTED_PATHS +
  bump `len(actual) == 127` -> 128 (tests/test_openapi.py).

Gates (Windows venv; all must pass before the PR):
  .venv\Scripts\python.exe -m ruff format --check app
  .venv\Scripts\python.exe -m ruff check app
  .venv\Scripts\python.exe -m mypy app
  $env:DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai'; .venv\Scripts\python.exe -m pytest -q

Verified against main 2026-06-18 (sanity-check only if main moved a lot):
service.verify_citations(text, *, request_id=None) returns
{"citations":[{citation,status,clusters:[{id,case_name,absolute_url}]}]};
app.errors exports ResearchNotConfigured/GatewayUnreachable/GatewayTimeout;
auth/client test pattern = per-file client + db_user + bearer header
(mirror api/tests/test_research_endpoints.py); no `make openapi`.

Ship (fork-and-PR only — never pushes to legalquants):
  git push -u origin feat/de-279-case-resolver        # origin = your fork
  gh pr create --repo legalquants/lq-ai --base main --head rlfordon:feat/de-279-case-resolver --fill
List the known PR-A limitations in the PR description (inline-form detection only;
first-cluster selection; no fallback search).
```

> `gh repo fork` needs `gh` authenticated (`gh auth login`). After Step 0, `git push`
> can only reach your fork; the PR is opened against upstream but pushes nothing there.

---

## Decisions locked into this plan (flag if you disagree)

1. **Scope = faithful-to-DE-279 minimal.** PR-A resolves + name-checks. It does **not** port this repo's fuzzy fallback (opinion search by name/court/date) or RECAP docket logic. Rationale: matches their **M** estimate, keeps the review surface tight, and lands the single highest-value behavior (catching name-swaps) first. Fallback search → a later DE.
2. **Detector is regex-only, dependency-free.** It recognizes the common inline form `Name v. Name, <vol reporter page>`. It deliberately does **not** handle `id.`/short forms, slip-opinion placeholders, California `(2022) 76 Cal.App.5th`, or reversed parentheticals — those are this repo's `parser.py` strengths and are flagged as a documented follow-up, not a PR-A gap.
3. **Asserted name must come from the source text.** The name-match needs the name the author *asserted*, which CL's citation-lookup does not return. So the detector pairs each citation with its preceding `X v. Y`; the join key to CL results is the normalized citation string.
4. **Matcher = the lenient post-resolution check.** Port `CaseNameMatcher.calculate_similarity` (the 4-factor scorer) **and** the surname-containment logic from `verifier._names_match_citation_lookup` — *not* the stricter `_names_match`. DE-279 is exactly the "citation already proven to exist, only reject truly wrong names" case the lenient checker was written for.
5. **Verdict vocabulary carries the granular signal.** Four states: `verified`, `wrong_case` (resolves to a *different* case — the fabrication catch), `unresolved` (CL found nothing), `unverifiable` (resolver/gateway unavailable — graceful, never blocks). PR-B maps these onto the chip UI.

---

## File Structure

PR-A creates/modifies (all under `api/`):

| File | Responsibility |
|---|---|
| `api/app/citation/case_name_match.py` *(create)* | Verbatim port of this repo's `name_matcher.py` — the dependency-free 4-factor `CaseNameMatcher`. |
| `api/app/citation/case_resolver.py` *(create)* | Detector (`detect_case_citations`), lenient verdict (`names_match_resolved`, `extract_surname`), and orchestration (`resolve_citations`). The DE-279 core. |
| `api/app/schemas/research.py` *(modify)* | Add `ValidateCitationsRequest`, `CaseCitationVerdict`, `ValidateCitationsResponse`. |
| `api/app/api/research.py` *(modify)* | Add `POST /research/validate-citations`. |
| `api/tests/citation/test_case_name_match.py` *(create)* | Pin the ported matcher's behavior. |
| `api/tests/test_case_resolver.py` *(create)* | Pin detector + verdict + orchestration (respx/monkeypatch the gateway). |
| `api/tests/citation/test_validate_citations_endpoint.py` *(create)* | Endpoint happy-path + wrong_case + unresolved + unverifiable. |
| `api/tests/test_endpoints.py` *(modify)* | Add the new route to `IMPLEMENTED_ROUTES`. |
| `api/tests/test_openapi.py` *(modify)* | Bump path count + `EXPECTED_PATHS`. |
| `docs/citation-engine.md` *(modify)* | New "§2 Case citation validation" section; flip DE-279 reference toward "in progress". |

Interfaces produced (later tasks rely on these exact names/types):

```python
# case_name_match.py
class CaseNameMatcher:
    def calculate_similarity(self, name1: str, name2: str) -> float: ...

# case_resolver.py
@dataclass(frozen=True)
class DetectedCite:
    asserted_name: str        # "Smith v. Jones"
    plaintiff: str            # "Smith"
    defendant: str            # "Jones"
    citation: str             # "123 U.S. 456"

def detect_case_citations(text: str) -> list[DetectedCite]: ...
def extract_surname(party: str) -> str: ...
def names_match_resolved(detected: DetectedCite, cl_case_name: str) -> bool: ...

async def resolve_citations(text: str, *, request_id: str | None = None) -> list[dict]: ...
# each dict: {"citation": str, "asserted_name": str, "resolution_status": str,
#             "matched_case_name": str | None, "cluster_id": int | None,
#             "absolute_url": str | None}
```

---

### Task 1: Port the dependency-free name matcher

**Files:**
- Create: `api/app/citation/case_name_match.py`
- Test: `api/tests/citation/test_case_name_match.py`

**Interfaces:**
- Produces: `CaseNameMatcher.calculate_similarity(name1: str, name2: str) -> float`

This is a **verbatim file copy** — `src/citation_verifier/name_matcher.py` in the citation-verifier repo imports only stdlib `re` and `difflib`, so it lifts with no edits.

- [ ] **Step 1: Copy the source file verbatim**

Copy `src/citation_verifier/name_matcher.py` (citation-verifier repo) → `api/app/citation/case_name_match.py`. Keep the `CaseNameMatcher` class, `calculate_similarity`, `_normalize`, `_extract_key_words`, and the `LEGAL_ABBREVIATIONS` dict exactly as-is. Update the module docstring's first line to:

```python
"""Multi-factor case-name similarity (ported for DE-279 case citation validation).

4-factor weighted score (sequence 0.25, word-overlap 0.30, substring 0.20,
key-word 0.25) with an abbreviated-name boost to 0.85 when the short name is a
subset of the long one (skipped for "In re"). Adapted from CaseStrainer
(https://github.com/jafrank88/CaseStrainer) via Tucuxi-Inc/citation-verifier.
Imports only stdlib re + difflib — no new dependency.
"""
```

- [ ] **Step 2: Write the failing test**

```python
# api/tests/citation/test_case_name_match.py
from app.citation.case_name_match import CaseNameMatcher


def test_empty_names_score_zero():
    m = CaseNameMatcher()
    assert m.calculate_similarity("", "Smith v. Jones") == 0.0
    assert m.calculate_similarity("Smith v. Jones", "") == 0.0


def test_abbreviated_name_subset_boosts_to_085():
    m = CaseNameMatcher()
    score = m.calculate_similarity(
        "Fink v. Gomez",
        "David M. Fink v. James H. Gomez, Director, Diana Carloni Nourse",
    )
    assert score >= 0.85


def test_unrelated_names_score_low():
    m = CaseNameMatcher()
    assert m.calculate_similarity("Obergefell v. Hodges", "Brown v. Board of Education") < 0.5


def test_in_re_does_not_get_subset_boost():
    m = CaseNameMatcher()
    # "In re Wright" must NOT auto-boost against an unrelated "In re ..." caption.
    score = m.calculate_similarity("In re Wright", "In re Ramirez, Minors")
    assert score < 0.85
```

- [ ] **Step 3: Run the tests — expect PASS**

Run: `cd api && .venv/bin/pytest tests/citation/test_case_name_match.py -v`
Expected: all 4 PASS (the file is a working port; the tests pin behavior, not drive new code).

- [ ] **Step 4: Lint + type-check**

Run: `cd api && ruff format app/citation/case_name_match.py tests/citation/test_case_name_match.py && ruff check app/citation/case_name_match.py && mypy app/citation/case_name_match.py`
Expected: clean. If `mypy` flags untyped returns, add the minimal annotations (`-> str`, `-> set[str]`) without changing logic.

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/case_name_match.py api/tests/citation/test_case_name_match.py
git commit -m "feat(citation): port dependency-free case-name matcher (DE-279)"
```

---

### Task 2: Bluebook detector — pair each citation with its asserted name

**Files:**
- Create: `api/app/citation/case_resolver.py` (detector portion)
- Test: `api/tests/test_case_resolver.py` (detector tests)

**Interfaces:**
- Produces: `DetectedCite` dataclass; `detect_case_citations(text: str) -> list[DetectedCite]`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_case_resolver.py
from app.citation.case_resolver import DetectedCite, detect_case_citations


def test_detects_inline_name_and_citation():
    text = "The court relied on Obergefell v. Hodges, 576 U.S. 644 (2015), throughout."
    hits = detect_case_citations(text)
    assert len(hits) == 1
    assert hits[0].plaintiff == "Obergefell"
    assert hits[0].defendant == "Hodges"
    assert hits[0].citation == "576 U.S. 644"


def test_detects_federal_reporter_forms():
    text = "See Smith v. Jones, 12 F.3d 345 (9th Cir. 1994); Roe v. Doe, 5 F. Supp. 2d 6 (S.D.N.Y. 1998)."
    cites = {h.citation for h in detect_case_citations(text)}
    assert "12 F.3d 345" in cites
    assert "5 F. Supp. 2d 6" in cites


def test_no_false_positive_without_v():
    text = "The statute, 42 U.S.C. 1983, governs civil rights claims."
    assert detect_case_citations(text) == []
```

- [ ] **Step 2: Run it — expect FAIL** (`ModuleNotFoundError: app.citation.case_resolver`).

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -v`

- [ ] **Step 3: Implement the detector**

```python
# api/app/citation/case_resolver.py
"""DE-279 — case citation validation (Bluebook resolution + name match).

Detects inline Bluebook citations and their asserted case names, resolves the
reporter citation through the gateway-brokered CourtListener tool
(app.research.service — never a direct CL call, ADR 0014), and checks the
asserted name against the resolved cluster's case_name with the lenient
surname-containment matcher used post-resolution. Emits a per-citation verdict.

Scope (PR-A): the common inline form `Name v. Name, <vol reporter page>`. Short
forms (id.), slip-opinion placeholders, and California/reversed-parenthetical
styles are out of scope — see the citation-verifier parser for those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Reporter token alternation for the common Bluebook forms. Order matters:
# longer/compound tokens (F. Supp. 2d) must precede their prefixes (F.).
_REPORTER = (
    r"(?:U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.\s?2d|L\.\s?Ed\."
    r"|F\.\s?Supp\.\s?3d|F\.\s?Supp\.\s?2d|F\.\s?Supp\."
    r"|F\.\s?App'?x|F\.\s?4th|F\.\s?3d|F\.\s?2d|F\."
    r"|A\.\s?3d|A\.\s?2d|A\."
    r"|N\.\s?E\.\s?3d|N\.\s?E\.\s?2d|N\.\s?W\.\s?2d|N\.\s?W\."
    r"|S\.\s?E\.\s?2d|S\.\s?W\.\s?3d|S\.\s?W\.\s?2d|So\.\s?3d|So\.\s?2d"
    r"|P\.\s?3d|P\.\s?2d|Cal\.\s?(?:App\.\s?)?\d?(?:th|d)?)"
)
_CITE = rf"\d+\s+{_REPORTER}\s+\d+"

# "PartyA v. PartyB, <cite>" — name capture is greedy-but-bounded; the comma
# before the volume number terminates it. Names start with a capital letter.
_CASE_RE = re.compile(
    rf"(?P<name>[A-Z][A-Za-z0-9.,'&()\-’ ]+?\sv\.?\s[A-Z][A-Za-z0-9.,'&()\-’ ]+?)"
    rf",\s+(?P<cite>{_CITE})"
)


@dataclass(frozen=True)
class DetectedCite:
    asserted_name: str
    plaintiff: str
    defendant: str
    citation: str


def _split_parties(name: str) -> tuple[str, str]:
    """Split "X v. Y" into (plaintiff, defendant); tolerant of "v" / "v.". """
    parts = re.split(r"\sv\.?\s", name, maxsplit=1)
    if len(parts) != 2:
        return name.strip(), ""
    return parts[0].strip(" ,"), parts[1].strip(" ,")


def _normalize_cite(cite: str) -> str:
    """Collapse internal whitespace so detector and CL strings join cleanly."""
    return re.sub(r"\s+", " ", cite).strip()


def detect_case_citations(text: str) -> list[DetectedCite]:
    """Return the inline `Name v. Name, <cite>` pairs found in text."""
    hits: list[DetectedCite] = []
    for m in _CASE_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        plaintiff, defendant = _split_parties(name)
        hits.append(
            DetectedCite(
                asserted_name=name,
                plaintiff=plaintiff,
                defendant=defendant,
                citation=_normalize_cite(m.group("cite")),
            )
        )
    return hits
```

- [ ] **Step 4: Run the detector tests — expect PASS**

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -v`
Expected: the 3 detector tests PASS. (If `test_detects_federal_reporter_forms` misses a form, widen `_REPORTER` — do not loosen the `, <cite>` anchor, which is what prevents the `42 U.S.C. 1983` false positive.)

- [ ] **Step 5: Lint + type-check, then commit**

```bash
cd api && ruff format app/citation/case_resolver.py tests/test_case_resolver.py && ruff check app/citation/case_resolver.py && mypy app/citation/case_resolver.py
git add api/app/citation/case_resolver.py api/tests/test_case_resolver.py
git commit -m "feat(citation): Bluebook detector pairing asserted name with citation (DE-279)"
```

---

### Task 3: Lenient post-resolution name match

**Files:**
- Modify: `api/app/citation/case_resolver.py` (append verdict helpers)
- Test: `api/tests/test_case_resolver.py` (append)

**Interfaces:**
- Consumes: `DetectedCite` (Task 2)
- Produces: `extract_surname(party: str) -> str`; `names_match_resolved(detected: DetectedCite, cl_case_name: str) -> bool`

This ports the surname-containment logic from `verifier._names_match_citation_lookup` (the lenient, "citation already exists, only reject truly wrong names" check). Port `_GENERIC_NAME_TOKENS` from `verifier.py` — the representative subset below is enough for PR-A; widen to the full set if a test needs it.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_case_resolver.py (append)
from app.citation.case_resolver import extract_surname, names_match_resolved


def _det(name: str) -> DetectedCite:
    plaintiff, _, defendant = name.partition(" v. ")
    return DetectedCite(asserted_name=name, plaintiff=plaintiff.strip(),
                        defendant=defendant.strip(), citation="1 U.S. 1")


def test_abbreviated_brief_name_matches_full_caption():
    # The fabrication-tolerant case: brief abbreviates, CL has the full caption.
    assert names_match_resolved(
        _det("Fink v. Gomez"),
        "David M. Fink v. James H. Gomez, Director, Diana Carloni Nourse",
    ) is True


def test_swapped_name_real_citation_is_rejected():
    # The fabrication: real reporter slot, asserted name that is NOT the case.
    assert names_match_resolved(_det("Smith v. Jones"), "Obergefell v. Hodges") is False


def test_common_prefix_compares_defendant():
    assert names_match_resolved(_det("United States v. Nixon"), "United States v. Nixon") is True
    assert names_match_resolved(_det("United States v. Nixon"), "United States v. Lopez") is False


def test_extract_surname_drops_role_suffix():
    assert extract_surname("James H. Gomez, Director") == "gomez"
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError`).

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -v`

- [ ] **Step 3: Implement the verdict helpers**

```python
# api/app/citation/case_resolver.py (append)

# Representative subset of verifier._GENERIC_NAME_TOKENS — surnames this generic
# are not distinctive enough for substring containment to mean a match.
_GENERIC_NAME_TOKENS = frozenset({
    "american", "national", "state", "united", "states", "commission",
    "department", "dept", "county", "city", "board", "bank", "company",
    "co", "corp", "inc", "llc", "group", "association", "assn", "committee",
    "trust", "fund", "service", "services", "system", "authority",
})

_COMMON_PREFIXES = ("united states", "state of", "commonwealth", "people")
_DEFENDANT_GENERIC_SUFFIXES = (
    " v. united states", " v united states", " v. state", " v state",
    " v. commonwealth", " v commonwealth", " v. people", " v people",
)


def extract_surname(party: str) -> str:
    """Last distinctive token of a party string, role/title suffix dropped."""
    head = party.split(",")[0]  # drop ", Director", ", Administrator", ...
    tokens = [t for t in re.findall(r"[A-Za-z']+", head) if len(t) > 1]
    return tokens[-1].lower() if tokens else ""


def names_match_resolved(detected: DetectedCite, cl_case_name: str) -> bool:
    """Lenient name check: reject only truly-wrong asserted names.

    Ported from verifier._names_match_citation_lookup. The citation is already
    proven to exist (CL resolved it); this guards against a fabricated name in
    a real reporter slot.
    """
    if not detected.asserted_name or not cl_case_name:
        return True  # nothing to check against — trust the resolution
    cl_lower = cl_case_name.lower()
    cited_lower = detected.asserted_name.lower()

    # Common-prefix cases (United States v. X, State v. X): the plaintiff is not
    # distinctive — compare the defendant surname.
    if any(cited_lower.startswith(p) for p in _COMMON_PREFIXES) and detected.defendant:
        surname = extract_surname(detected.defendant)
        return surname in cl_lower if surname else detected.defendant.lower() in cl_lower

    # Generic-government DEFENDANT (X v. United States): require CL to share the
    # suffix, then compare plaintiff tokens (Charlotin Bug 3 posture).
    if any(cited_lower.endswith(s) for s in _DEFENDANT_GENERIC_SUFFIXES):
        if not any(s in cl_lower for s in _DEFENDANT_GENERIC_SUFFIXES):
            return False
        tokens = [
            t for t in re.findall(r"[a-z0-9]+", detected.plaintiff.lower())
            if len(t) >= 3 and t not in _GENERIC_NAME_TOKENS
        ]
        return any(t in cl_lower for t in tokens) if tokens else False

    # Regular cases: at least one distinctive party surname must appear in CL's caption.
    surnames = [s for s in (extract_surname(detected.plaintiff),
                            extract_surname(detected.defendant)) if s]
    distinctive = [s for s in surnames if len(s) >= 3 and s not in _GENERIC_NAME_TOKENS]
    if not distinctive:
        return False  # all-generic surnames — don't blind-trust
    return any(s in cl_lower for s in distinctive)
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -v`
Expected: all detector + verdict tests PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd api && ruff format app/citation/case_resolver.py tests/test_case_resolver.py && ruff check app/citation/case_resolver.py && mypy app/citation/case_resolver.py
git add api/app/citation/case_resolver.py api/tests/test_case_resolver.py
git commit -m "feat(citation): lenient post-resolution name match (DE-279)"
```

---

### Task 4: Orchestration — resolve + join + verdict

**Files:**
- Modify: `api/app/citation/case_resolver.py` (append `resolve_citations`)
- Test: `api/tests/test_case_resolver.py` (append; monkeypatch the gateway-backed service)

**Interfaces:**
- Consumes: `detect_case_citations`, `names_match_resolved`; `app.research.service.verify_citations`
- Produces: `async resolve_citations(text, *, request_id=None) -> list[dict]` (verdict dicts per the File-Structure interface block)

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_case_resolver.py (append)
import pytest

from app.citation import case_resolver
from app.errors import ResearchNotConfigured


class _FakeService:
    """Stands in for app.research.service.verify_citations (the gateway path)."""
    def __init__(self, payload):
        self._payload = payload
    async def verify_citations(self, text, *, request_id=None):
        return self._payload


@pytest.mark.asyncio
async def test_resolve_marks_matching_name_verified(monkeypatch):
    payload = {"citations": [{
        "citation": "576 U.S. 644", "status": 200,
        "clusters": [{"id": 1, "case_name": "Obergefell v. Hodges",
                      "absolute_url": "/opinion/1/x/"}],
    }]}
    monkeypatch.setattr(case_resolver, "service", _FakeService(payload))
    out = await case_resolver.resolve_citations("Obergefell v. Hodges, 576 U.S. 644 (2015).")
    assert out[0]["resolution_status"] == "verified"
    assert out[0]["matched_case_name"] == "Obergefell v. Hodges"
    assert out[0]["cluster_id"] == 1


@pytest.mark.asyncio
async def test_resolve_marks_wrong_case_when_name_differs(monkeypatch):
    payload = {"citations": [{
        "citation": "576 U.S. 644", "status": 200,
        "clusters": [{"id": 1, "case_name": "Obergefell v. Hodges",
                      "absolute_url": "/opinion/1/x/"}],
    }]}
    monkeypatch.setattr(case_resolver, "service", _FakeService(payload))
    out = await case_resolver.resolve_citations("Smith v. Jones, 576 U.S. 644 (2015).")
    assert out[0]["resolution_status"] == "wrong_case"


@pytest.mark.asyncio
async def test_resolve_marks_unresolved_when_no_cluster(monkeypatch):
    payload = {"citations": [{"citation": "999 U.S. 999", "status": 404, "clusters": []}]}
    monkeypatch.setattr(case_resolver, "service", _FakeService(payload))
    out = await case_resolver.resolve_citations("Fake v. Made-Up, 999 U.S. 999 (2099).")
    assert out[0]["resolution_status"] == "unresolved"


@pytest.mark.asyncio
async def test_resolve_unverifiable_when_research_not_configured(monkeypatch):
    class _Down:
        async def verify_citations(self, text, *, request_id=None):
            raise ResearchNotConfigured("off")
    monkeypatch.setattr(case_resolver, "service", _Down())
    out = await case_resolver.resolve_citations("Smith v. Jones, 1 U.S. 1 (1999).")
    assert out[0]["resolution_status"] == "unverifiable"
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: resolve_citations`).

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -k resolve -v`

- [ ] **Step 3: Implement the orchestration**

Add the import at the top of `case_resolver.py` (with the other imports):

```python
from app.errors import GatewayUnreachable, GatewayTimeout, ResearchNotConfigured
from app.research import service
```

Append:

```python
def _index_cl_results(payload: dict) -> dict[str, dict]:
    """Map normalized citation string -> CL result item for joining."""
    out: dict[str, dict] = {}
    for item in payload.get("citations", []):
        key = _normalize_cite(str(item.get("citation") or ""))
        if key:
            out[key] = item
    return out


def _verdict(detected: DetectedCite, cl_item: dict | None) -> dict:
    base = {
        "citation": detected.citation,
        "asserted_name": detected.asserted_name,
        "matched_case_name": None,
        "cluster_id": None,
        "absolute_url": None,
    }
    clusters = (cl_item or {}).get("clusters") or []
    if not cl_item or not clusters:
        return {**base, "resolution_status": "unresolved"}
    cluster = clusters[0]
    cl_name = cluster.get("case_name") or ""
    matched = names_match_resolved(detected, cl_name)
    return {
        **base,
        "resolution_status": "verified" if matched else "wrong_case",
        "matched_case_name": cl_name or None,
        "cluster_id": cluster.get("id"),
        "absolute_url": cluster.get("absolute_url"),
    }


async def resolve_citations(text: str, *, request_id: str | None = None) -> list[dict]:
    """Detect → resolve (gateway) → name-check. One verdict dict per detected cite.

    Resolver/gateway unavailability is graceful: every detected cite comes back
    `unverifiable` rather than raising (DE-279: a down resolver must not block).
    """
    detected = detect_case_citations(text)
    if not detected:
        return []
    try:
        payload = await service.verify_citations(text, request_id=request_id)
    except (ResearchNotConfigured, GatewayUnreachable, GatewayTimeout):
        return [
            {
                "citation": d.citation, "asserted_name": d.asserted_name,
                "resolution_status": "unverifiable",
                "matched_case_name": None, "cluster_id": None, "absolute_url": None,
            }
            for d in detected
        ]
    by_cite = _index_cl_results(payload)
    return [_verdict(d, by_cite.get(d.citation)) for d in detected]
```

> **✓ Verified against `main` (2026-06-18):** `app.research.service.verify_citations(text: str, *, request_id: str | None = None)` returns `result["payload"]` shaped `{"citations": [{citation, status, clusters: [{id, case_name, absolute_url}]}]}`. `ResearchNotConfigured`, `GatewayUnreachable`, `GatewayTimeout`, and `NotFound` all live in `app.errors`. Re-confirm only if `main` moved substantially since this date.

- [ ] **Step 4: Run — expect PASS**

Run: `cd api && .venv/bin/pytest tests/test_case_resolver.py -v`
Expected: all resolver tests PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd api && ruff format app/citation/case_resolver.py tests/test_case_resolver.py && ruff check app/citation/case_resolver.py && mypy app/citation/case_resolver.py
git add api/app/citation/case_resolver.py api/tests/test_case_resolver.py
git commit -m "feat(citation): resolve_citations orchestration + graceful resolver-down (DE-279)"
```

---

### Task 5: REST endpoint + schemas

**Files:**
- Modify: `api/app/schemas/research.py`
- Modify: `api/app/api/research.py`
- Test: `api/tests/citation/test_validate_citations_endpoint.py`

**Interfaces:**
- Consumes: `case_resolver.resolve_citations`
- Produces: `POST /api/v1/research/validate-citations` → `ValidateCitationsResponse`

- [ ] **Step 1: Add the schemas**

In `api/app/schemas/research.py`, add (match the existing pydantic style in that file):

```python
class ValidateCitationsRequest(BaseModel):
    text: str = Field(..., max_length=64000)


class CaseCitationVerdict(BaseModel):
    citation: str
    asserted_name: str
    resolution_status: str  # verified | wrong_case | unresolved | unverifiable
    matched_case_name: str | None = None
    cluster_id: int | None = None
    absolute_url: str | None = None


class ValidateCitationsResponse(BaseModel):
    verdicts: list[CaseCitationVerdict]
```

> If the file imports `BaseModel`/`Field` already (it defines `VerifyCitationsRequest` etc.), reuse those imports; don't re-import.

- [ ] **Step 2: Write the failing endpoint test**

Mirrors the **verified** auth/client pattern in `api/tests/test_research_endpoints.py` (there is no shared `authed_client` fixture — each research test file defines its own `client` + `db_user` + bearer-header helper; conftest provides only DB fixtures). The endpoint needs `ActiveUser`, so the test needs a real `User` row → it needs the test DB. `case_resolver.resolve_citations` is monkeypatched so the gateway is never touched.

```python
# api/tests/citation/test_validate_citations_endpoint.py
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation import case_resolver
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"cite-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Cite Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False, mfa_enabled=False, must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_validate_citations_returns_verdicts(client, db_user, monkeypatch):
    async def _fake(text, *, request_id=None):
        return [{
            "citation": "576 U.S. 644", "asserted_name": "Smith v. Jones",
            "resolution_status": "wrong_case",
            "matched_case_name": "Obergefell v. Hodges",
            "cluster_id": 1, "absolute_url": "/opinion/1/x/",
        }]
    monkeypatch.setattr(case_resolver, "resolve_citations", _fake)

    resp = await client.post(
        "/api/v1/research/validate-citations",
        json={"text": "Smith v. Jones, 576 U.S. 644 (2015)."},
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdicts"][0]["resolution_status"] == "wrong_case"
    assert body["verdicts"][0]["matched_case_name"] == "Obergefell v. Hodges"
```

> Patch `case_resolver.resolve_citations` (the module attribute) — the route calls `case_resolver.resolve_citations(...)`, so module-level patching takes effect. Add an unauth test (`client.post(... )` with no headers → 401) to mirror the `/research` suite's 401 gate.

- [ ] **Step 3: Run — expect FAIL** (404; route not registered).

Run: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/citation/test_validate_citations_endpoint.py -v`

- [ ] **Step 4: Add the route**

In `api/app/api/research.py`, import the new schemas alongside the existing ones and add:

```python
@router.post("/validate-citations", response_model=ValidateCitationsResponse)
async def validate_citations(
    payload: ValidateCitationsRequest, user: ActiveUser
) -> ValidateCitationsResponse:
    from app.citation import case_resolver

    verdicts = await case_resolver.resolve_citations(payload.text)
    return ValidateCitationsResponse(
        verdicts=[CaseCitationVerdict(**v) for v in verdicts]
    )
```

> Import `case_resolver` at module top with the other imports rather than inline if that matches the file's style; inline shown to avoid an import cycle if one surfaces (`citation` → `research.service` → … ). Prefer top-level and only fall back to inline if mypy/import flags a cycle.

- [ ] **Step 5: Run — expect PASS**

Run: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/citation/test_validate_citations_endpoint.py -v`

- [ ] **Step 6: Update the collision guards**

The api suite fails if a new route isn't registered in both guards.
- In `api/tests/test_endpoints.py`: add `("POST", "/api/v1/research/validate-citations")` to the `IMPLEMENTED_ROUTES` set, next to the `# WS3b — case-law research surface` block (the `("POST", "/api/v1/research/verify-citations")` entry).
- In `api/tests/test_openapi.py`: add `"/api/v1/research/validate-citations"` to the `EXPECTED_PATHS` frozenset (near the other `/research/*` entries) AND bump `assert len(actual) == 127` → `128` (verified 127 on 2026-06-18).

Run: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_endpoints.py tests/test_openapi.py -v`
Expected: PASS after both edits.

- [ ] **Step 7: Update the OpenAPI sketch (hand-maintained)**

There is **no** `make openapi` target. `docs/api/backend-openapi.yaml` is hand-maintained, and `test_openapi.py` compares the **live app's** generated paths to the in-test `EXPECTED_PATHS` frozenset (the yaml is not `safe_load`-checked by the test). For contract hygiene per the `test_openapi.py` docstring, manually add a `/api/v1/research/validate-citations` `post:` stanza to `backend-openapi.yaml` mirroring the existing `verify-citations` entry. The load-bearing checks remain `EXPECTED_PATHS` + the count (Step 6) and `IMPLEMENTED_ROUTES`.

- [ ] **Step 8: Lint, type-check, commit**

```bash
cd api && ruff format app/schemas/research.py app/api/research.py tests/citation/test_validate_citations_endpoint.py tests/test_endpoints.py tests/test_openapi.py && ruff check app && mypy app
git add api/app/schemas/research.py api/app/api/research.py api/tests/citation/test_validate_citations_endpoint.py api/tests/test_endpoints.py api/tests/test_openapi.py docs/api/backend-openapi.yaml
git commit -m "feat(api): POST /research/validate-citations — name-checked case citation validation (DE-279)"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/citation-engine.md`

- [ ] **Step 1: Add a "§2 Case citation validation" section**

After the existing type-1 cascade content, document: the detector scope (inline `Name v. Name, <cite>`), that resolution is gateway-brokered (ADR 0014, reuses the CourtListener tool provider — no new egress), the four verdict states and what each means, the **graceful resolver-down** behavior (`unverifiable`, never blocks), and that the name check is the lenient post-resolution surname-containment matcher. Note the explicit non-goals (short forms, slip-opinion placeholders, fallback opinion/RECAP search — future DEs). Cross-link DE-279.

- [ ] **Step 2: Run the full api suite + gates one more time**

```bash
cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest -q
ruff format --check app && ruff check app && mypy app
```
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add docs/citation-engine.md
git commit -m "docs(citation): document DE-279 case citation validation (§2)"
```

---

## PR-B (separate plan — outline only)

These items finish discharging DE-279's acceptance criteria but touch the chat pipeline and `web/`, so they get their own plan once those files are read against `main`:

- **`message_case_citations` table + migration** (`message_id`, `citation_string`, `normalized_form`, `courtlistener_cluster_id`, `resolution_status`, `matched_case_name`, `resolved_at`). Next migration after current head (0049 at time of writing — `alembic heads` to confirm). Verify on the throwaway pgvector, never on the dev DB.
- **Chat auto-run** — call `resolve_citations` on each chat response in parallel with type-1 verification, persist rows, write the audit action (free-form string, e.g. `research.validate_citations` — no enum change needed). Mirror `_persist_message_citations` in `api/app/citation/verification.py`, invoked from `api/app/api/chats.py`.
- **Operator flag** — `citation_engine.case_validation.enabled` in `gateway.yaml` (and the api reading it via the gateway config endpoint), so deployments without litigation use can skip it.
- **UI chip + Cypress E2E** — `verified` green, `wrong_case` red ("resolves to a different case — *<matched_case_name>*"), `unresolved` ("could not resolve"), `unverifiable` ("resolver unavailable"). Cypress exercises the failed-resolution state. (`web/**` is its own review surface.)

## Acceptance-criteria coverage (DE-279)

| DE-279 acceptance criterion | Covered by |
|---|---|
| Detector recognizes ≥95% of a curated Bluebook test set | Tasks 2 (+ widen `_REPORTER` against the curated set during review) |
| Resolution ≥98% real / ≤2% false-positive on fabricated | Tasks 3–4 (name match catches the fabrications); validate against a labeled set |
| Graceful CourtListener-down ("unverified — resolver unavailable", not blocked) | Task 4 (`unverifiable` path) |
| Documented in `docs/citation-engine.md` §2 | Task 6 |
| `message_case_citations` audit row + chat integration + Cypress | **PR-B** |

## Self-review notes

- **No new dependency** anywhere (stdlib `re`/`difflib`; respx already in dev extras). ✔
- **No `gateway/**` edits** → PR-A stays api-only / self-merge. ✔
- **Types consistent**: `DetectedCite`, `resolve_citations` dict keys, and `CaseCitationVerdict` fields match across Tasks 2/4/5. ✔
- **Open items — all verified against `main` 2026-06-18** (no longer open): `service.verify_citations` signature + payload ✓; `app.errors` exports `ResearchNotConfigured`/`GatewayUnreachable`/`GatewayTimeout` ✓; auth/client pattern = per-file `client` + `db_user` + bearer header (no shared `authed_client`) ✓; no `make openapi` (yaml hand-maintained; `test_openapi.py` authoritative) ✓; `EXPECTED_PATHS` count = 127 → 128 ✓. Re-confirm only if `main` advanced materially.
- **Known PR-A limitations to state in the PR description** (so reviewers don't read them as gaps): inline-form detection only; first-cluster selection (no parallel-citation / sibling-cluster disambiguation); citation-string join can miss on exotic spacing. Each maps to a follow-up that this repo's `parser.py` / `verifier.py` already solve.
