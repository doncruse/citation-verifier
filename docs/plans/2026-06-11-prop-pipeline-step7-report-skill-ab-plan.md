# Proposition-Verifier Step 7: Report Lanes + SKILL Stub + A/B Re-point — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land design §10 step 7: the `report` verb (§3 row 8) rendering the §6.9 lanes (CITE_UNCONFIRMED as the amber "Check Cite" lane — never Red; Gray "Unable to verify") and §6.5 card-level crosscheck flags through the existing `report_template.py`; the thin `.claude/skills/proposition-verifier/SKILL.md` stub (§2/§9); and the A/B harness re-pointed at the executor + frozen-workdir contract, relocated to `tools/` (roadmap Tier 2 #9).

**Architecture:** A new pure helper `scoring.report_lane()` resolves the v1-schema design tension (decided below); `generate_report()` switches its per-claim routing to it and gains flag-chip rendering from a new `_crosscheck_flag_lines()` helper; `run_report()` wraps `generate_report` with brief_metadata.json loading + run.json stamping, exposed as the `report` CLI verb closing the full chain. The SKILL stub is orchestration-only prose (~35 lines); all criteria stay in the versioned templates. The rewritten `tools/ab_test_runner.py` copies a frozen corpus, strips its cassette, runs `run_assess` with a config-built executor, and scores via `scoring.score_workdir` — its old inline prompt copy (the assess-v1 source) is deleted because the byte-pinned template now owns that text.

**Tech stack:** stdlib + pytest, offline throughout. No live LLM calls anywhere in this step (live A/B runs are Step 8, user-gated).

---

## DECIDED: report color precedence under the v1 verdict schema (the known design tension)

`derive_color()` takes the three §6.9 axes, but v1 assess verdicts have **no support axis** — the `support` column is empty until assess-v2. So the report does NOT call `derive_color` per claim; with `support=""` it would return Gray for every agent-assessed VERIFIED row. Instead a sibling pure function `report_lane(cl_status, assessment, opinion_file)` in `scoring.py` applies this precedence:

| # | condition | lane | rationale |
|---|---|---|---|
| 1 | `cl_status == "WRONG_CASE"` | **Red** | existence lane; WRONG_CASE rows are never agent-assessed (`_assessable` excludes them), so the `assessment` column is ignored. **Behavior change:** today an empty-assessment WRONG_CASE row renders Yellow — that was a bug vs §6.9. |
| 2 | `cl_status == "CITE_UNCONFIRMED"` | **CheckCite** | amber lane — **never Red, even when an agent verdict exists and says Red** (the agent assessed support vs the downloaded text; the lane communicates the cite problem). Matches `derive_color` row 3. |
| 3 | `cl_status in UNLOCATABLE` **and** no `opinion_file` | **Gray** | "Unable to verify" — extends today's NOT_FOUND-only check to INSUFFICIENT_DATA and VERIFICATION_INCOMPLETE. |
| 4 | otherwise | floor-enforced **`assessment` column is authoritative**: Green/Red as written; Yellow **or empty** → Yellow | empty = located but never assessed (legacy claims.csv, or report run before apply) — exactly today's else-branch behavior, preserved. |

Rows 1–3 are `derive_color`'s existence rows verbatim; row 4 substitutes the floor-enforced `assessment` for the missing support axis. **When assess-v2 fills `support`, row 4 can become `derive_color(cl_status, support, quote_worst)`** — logged for the v2 re-record event.

Other rendering decisions locked here:
- Check-cite claims render **inside the findings walkthrough** with severity `"orange"` (CSS `badge-orange` already exists; `sev-orange` + a "Check Cite" dashboard stat are added). Their `badge_label` is **forced** to `_STATUS_BADGE_FALLBACK["CITE_UNCONFIRMED"]` ("Check cite -- case found by name, cited location unconfirmed") so an agent badge like "Not supported by cited case" can't mislabel the lane; the agent's blocks/analysis still render in the card body.
- The all-clear banner shows only when `red_count == 0 and checkcite_count == 0`.
- `crosscheck_flags` render as amber **flag chips** at the top of finding/check-cite card bodies AND inline on green verified items (§6.5: "renders as a flag on the card even when support is otherwise fine"). Flags never move a claim between lanes.
- Gray-lane card explanations become status-specific (NOT_FOUND keeps today's text; INSUFFICIENT_DATA / VERIFICATION_INCOMPLETE get their own).
- Legacy claims.csv (no `crosscheck_flags`/`support`/`cl_status` oddities) renders via the existing fallbacks: all `csv.DictReader` reads use `.get`, so missing columns yield no chips and row-4 routing — `test_brief_pipeline.py::TestGenerateReport` must keep passing unchanged.

**Source facts (verified this session):**
- `generate_report` (proposition_pipeline.py:1841): routes green→verified, `NOT_FOUND and not opinion_file`→grouped unable cards, else→finding with `severity = "red" if assessment=="red" else "yellow"`. `_STATUS_BADGE_FALLBACK` (line 291) already has the CITE_UNCONFIRMED label.
- `report_template.py`: `_build_dashboard(total, red, yellow, green, gray, findings, unable)`; `_badge` supports "orange"; no `sev-orange` CSS; findings/verified builders have no flag rendering.
- `scoring.py` exports `GREEN/YELLOW/RED/GRAY/CHECK_CITE`, `UNLOCATABLE`, `derive_color`, `_SEVERITY_RANK`. `proposition_pipeline` already imports from scoring lazily (no cycle: scoring imports only executor).
- Legacy report CLI (`__main__.py --report`, line 371) loads `brief_metadata.json` and calls `generate_report` — `run_report` mirrors that.
- Full-chain dispatch (`_dispatch_proposition_verbs`) returns 0 at extract-pending and assess-pending; apply runs after assess; report slots after apply.
- Existing pinned report tests: `test_brief_pipeline.py:657-909` (none cover WRONG_CASE-with-empty-assessment, so row 1's behavior change breaks nothing); `test_report_template.py` (template-level, no lanes).
- Nothing imports `tests/ab_test_runner.py` (docstring references only in `build_assessment_corpora.py` / `measure_withers_assessment.py`) — relocation is safe. `tools/` does not exist yet. `ab_test_cases.json`, `ab_test_configs.json`, `build_review_page.py` stay as-is.
- Frozen-corpus baselines (current ledger, Step 1 execution notes): payne **23/27**, wainwright **33/34** (56/61). `tests/data/results/` is gitignored.
- `_copy_withers(tmp_path)` helper exists in `test_proposition_pipeline.py:458`.

**Windows invocations:** always `venv/Scripts/python.exe`; ASCII-only console output (HTML entities in the report file are fine).

---

### Task 1: `report_lane()` in scoring.py

**Files:**
- Modify: `src/citation_verifier/scoring.py` (after `derive_color`)
- Test: `tests/test_scoring.py`

- [ ] **1.1 Write the failing tests** — append to `tests/test_scoring.py`:

```python
from citation_verifier.scoring import report_lane


class TestReportLane:
    """SS6.9 lane precedence under the single-color v1 verdict schema
    (Step 7 plan decision): existence lanes 1-3 beat the assessment
    column; otherwise the floor-enforced assessment is authoritative."""

    def test_wrong_case_red_even_when_unassessed(self):
        assert report_lane("WRONG_CASE", "", "") == "Red"

    def test_wrong_case_red_ignores_assessment(self):
        assert report_lane("WRONG_CASE", "Green", "opinions/a.html") == "Red"

    def test_cite_unconfirmed_is_check_cite_never_red(self):
        assert report_lane("CITE_UNCONFIRMED", "Red",
                           "opinions/a.html") == "CheckCite"

    def test_cite_unconfirmed_check_cite_even_when_green(self):
        assert report_lane("CITE_UNCONFIRMED", "Green",
                           "opinions/a.html") == "CheckCite"

    @pytest.mark.parametrize("status", [
        "NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"])
    def test_unlocatable_without_text_is_gray(self, status):
        assert report_lane(status, "", "") == "Gray"

    def test_unlocatable_with_opinion_falls_to_assessment(self):
        # Shouldn't occur in practice; documented fall-through.
        assert report_lane("NOT_FOUND", "Green", "opinions/a.html") == "Green"

    @pytest.mark.parametrize("assessment,lane", [
        ("Green", "Green"), ("Red", "Red"), ("Yellow", "Yellow"),
        ("green", "Green"), ("", "Yellow")])
    def test_verified_family_assessment_is_authoritative(
            self, assessment, lane):
        assert report_lane("VERIFIED", assessment,
                           "opinions/a.html") == lane

    def test_legacy_empty_status_unassessed_is_yellow(self):
        assert report_lane("", "", "") == "Yellow"
```

- [ ] **1.2 Run, verify fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_scoring.py -v -k ReportLane`
Expected: FAIL — `ImportError: cannot import name 'report_lane'`

- [ ] **1.3 Implement** — append to `scoring.py` directly after `derive_color`:

```python
def report_lane(cl_status: str, assessment: str = "",
                opinion_file: str = "") -> str:
    """SS6.9 lane for the report under the single-color v1 verdict schema.

    The report cannot recompute color from the three axes for
    agent-assessed claims: v1 verdicts carry no support axis (the
    `support` column is empty until assess-v2). Precedence (Step 7 plan):

      1. WRONG_CASE            -> Red   (existence lane; never assessed)
      2. CITE_UNCONFIRMED      -> CheckCite (amber lane -- never Red,
                                  even when an agent verdict says Red)
      3. UNLOCATABLE + no text -> Gray  ("Unable to verify")
      4. otherwise the floor-enforced `assessment` column is
         authoritative: Green/Red as written; Yellow or empty (located
         but never assessed -- legacy claims.csv) -> Yellow.

    Rows 1-3 are derive_color's existence rows verbatim; row 4
    substitutes `assessment` for the missing support axis. When v2
    fills `support`, row 4 can become derive_color(existence, support,
    quote_worst).
    """
    if cl_status == "WRONG_CASE":
        return RED
    if cl_status == "CITE_UNCONFIRMED":
        return CHECK_CITE
    if cl_status in UNLOCATABLE and not opinion_file:
        return GRAY
    a = (assessment or "").strip().lower()
    if a == "green":
        return GREEN
    if a == "red":
        return RED
    return YELLOW
```

- [ ] **1.4 Run, verify pass** (plus the rest of `tests/test_scoring.py -q` — no collateral).

- [ ] **1.5 Commit**

```bash
git add src/citation_verifier/scoring.py tests/test_scoring.py
git commit -m "feat: report_lane() -- SS6.9 lanes under the v1 single-color schema"
```

### Task 2: `_crosscheck_flag_lines()` helper

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (near `run_crosscheck`)
- Test: `tests/test_proposition_pipeline.py`

- [ ] **2.1 Write the failing tests:**

```python
class TestCrosscheckFlagLines:
    def test_all_three_flag_types(self):
        claim = {"crosscheck_flags": json.dumps({
            "toa_mismatch": {"variants": [
                "Bryant v. Jones, 597 F.3d 1320 (11th Cir. 2010)",
                "Bryant v. Jones, 97 F.3d 1320 (11th Cir. 2010)"]},
            "court_mismatch": {"cited": "ca6", "cited_id": "ca6",
                               "matched_id": "ca5",
                               "matched": "Fifth Circuit"},
            "pincite_flag": {"pinpoint": "999", "star_range": [770, 790],
                             "footnote_missing": "42"},
        })}
        lines = pp._crosscheck_flag_lines(claim)
        assert any("597 F.3d" in ln and "97 F.3d" in ln for ln in lines)
        assert any("ca6" in ln and "ca5" in ln for ln in lines)
        assert any("999" in ln and "770-790" in ln for ln in lines)
        assert any("n.42" in ln for ln in lines)
        assert len(lines) == 4  # pincite_flag yields two lines here

    def test_empty_and_missing_and_malformed(self):
        assert pp._crosscheck_flag_lines({}) == []
        assert pp._crosscheck_flag_lines({"crosscheck_flags": ""}) == []
        assert pp._crosscheck_flag_lines(
            {"crosscheck_flags": "not json"}) == []
        assert pp._crosscheck_flag_lines(
            {"crosscheck_flags": "[1, 2]"}) == []
```

(`pp` is the module-level alias the suite already uses.)

- [ ] **2.2 Run, verify fail** — `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k CrosscheckFlagLines` → AttributeError.

- [ ] **2.3 Implement** — place after `run_crosscheck`:

```python
def _crosscheck_flag_lines(claim: dict) -> list[str]:
    """Human-readable card flags from the crosscheck_flags JSON column
    (SS6.5: a flag renders on the card even when support is otherwise
    fine; flags never move a claim between lanes). Missing / empty /
    malformed -> [] (legacy claims.csv tolerated)."""
    raw = (claim.get("crosscheck_flags") or "").strip()
    if not raw:
        return []
    try:
        flags = json_mod.loads(raw)
    except (json_mod.JSONDecodeError, ValueError):
        return []
    if not isinstance(flags, dict):
        return []
    lines: list[str] = []
    toa = flags.get("toa_mismatch") or {}
    if toa.get("variants"):
        lines.append("TOA/body citation mismatch: "
                     + " vs ".join(toa["variants"]))
    court = flags.get("court_mismatch") or {}
    if court:
        matched_name = court.get("matched", "")
        suffix = f" ({matched_name})" if matched_name else ""
        lines.append(
            f"Court mismatch: brief cites {court.get('cited_id', '?')}, "
            f"CL match is {court.get('matched_id', '?')}{suffix}")
    pin = flags.get("pincite_flag") or {}
    if pin.get("pinpoint"):
        lo, hi = (pin.get("star_range") or ["?", "?"])[:2]
        lines.append(f"Pincite {pin['pinpoint']} outside the opinion's "
                     f"star-pagination range {lo}-{hi}")
    if pin.get("footnote_missing"):
        lines.append(f"Footnote n.{pin['footnote_missing']} not found "
                     f"in the opinion text")
    return lines
```

- [ ] **2.4 Run, verify pass; commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: _crosscheck_flag_lines -- crosscheck_flags JSON to card flag strings (SS6.5)"
```

### Task 3: lanes + flags through `generate_report` and the template

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (`generate_report` routing)
- Modify: `src/citation_verifier/report_template.py` (dashboard stat, sev-orange + flag-chip CSS, flag rendering, banner condition)
- Test: `tests/test_proposition_pipeline.py` (new `TestReportLanesRendering`)

- [ ] **3.1 Write the failing tests:**

```python
def _report_workdir(tmp_path, rows, fieldnames=None):
    """claims.csv-only workdir for generate_report lane tests."""
    wd = tmp_path / "rep"
    (wd / "opinions").mkdir(parents=True)
    (wd / "opinions" / "a.html").write_text("opinion", encoding="utf-8")
    fields = fieldnames or [
        "claim_id", "page", "proposition", "cited_for", "cited_case",
        "quoted_text", "brief_sentence", "cl_status", "cl_url",
        "retrieved_case", "supporting_language", "opinion_file",
        "quote_check", "quote_check_worst", "quote_floor",
        "crosscheck_flags", "triage_track", "prescreen_hint",
        "assessment", "support", "assessed_by", "finding_analysis",
        "badge_label", "brief_block", "opinion_block", "diagnostics",
        "syllabus",
    ]
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            base = dict.fromkeys(fields, "")
            base.update(r)
            w.writerow(base)
    return wd


def _row(claim_id, **kw):
    base = {"claim_id": claim_id, "page": "1",
            "proposition": f"Proposition {claim_id}.",
            "cited_case": f"Case {claim_id} v. Other, 1 F.3d 1 (1st Cir. 1990)",
            "quoted_text": "[]"}
    base.update(kw)
    return base


class TestReportLanesRendering:
    def test_cite_unconfirmed_is_check_cite_lane_never_red(self, tmp_path):
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status="CITE_UNCONFIRMED",
            opinion_file="opinions/a.html", assessment="Red",
            finding_analysis="Agent thought this was unsupported.",
            badge_label="Not supported by cited case")])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert 'class="sev-orange"' in html  # dashboard issue row
        assert "Check cite -- case found by name" in html  # forced badge
        assert "Not supported by cited case" not in html  # agent badge overridden
        assert "Agent thought this was unsupported." in html  # content kept
        # red stat is zero; check-cite stat is one
        assert '<div class="stat stat-red"><div class="stat-num">0</div>' in html
        assert '<div class="stat stat-orange"><div class="stat-num">1</div>' in html

    def test_wrong_case_unassessed_is_red(self, tmp_path):
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status="WRONG_CASE", assessment="")])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert 'class="sev-red"' in html
        assert "Case mismatch -- cite resolves to a different case" in html

    @pytest.mark.parametrize("status,marker", [
        ("INSUFFICIENT_DATA", "lacks the court and year"),
        ("VERIFICATION_INCOMPLETE", "could not complete"),
    ])
    def test_other_unlocatable_statuses_go_gray(self, tmp_path, status,
                                                marker):
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status=status, assessment="")])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert "Unable to verify" in html
        assert marker in html

    def test_flags_render_on_finding_card(self, tmp_path):
        flags = json.dumps({"court_mismatch": {
            "cited_id": "ca6", "matched_id": "ca5",
            "matched": "Fifth Circuit"}})
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status="VERIFIED", opinion_file="opinions/a.html",
            assessment="Yellow", finding_analysis="Analysis.",
            crosscheck_flags=flags)])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert 'class="flag-chip"' in html
        assert "brief cites ca6, CL match is ca5" in html

    def test_flags_render_on_green_verified_item(self, tmp_path):
        """SS6.5: the flag shows even when support is otherwise fine."""
        flags = json.dumps({"pincite_flag": {
            "pinpoint": "999", "star_range": [770, 790]}})
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status="VERIFIED", opinion_file="opinions/a.html",
            assessment="Green", crosscheck_flags=flags)])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert "Verified Citations" in html
        assert 'class="flag-chip"' in html
        assert "Pincite 999" in html

    def test_no_all_clear_banner_when_check_cite_present(self, tmp_path):
        wd = _report_workdir(tmp_path, [
            _row("r-01", cl_status="CITE_UNCONFIRMED",
                 opinion_file="opinions/a.html", assessment="Green"),
            _row("r-02", cl_status="VERIFIED",
                 opinion_file="opinions/a.html", assessment="Green"),
        ])
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert "No serious issues found" not in html

    def test_legacy_rows_without_new_columns_render_as_before(
            self, tmp_path):
        """Pre-two-axis claims.csv (payne-style header) -> existing
        fallbacks: green->verified, yellow->finding, NOT_FOUND->gray;
        no flag chips, no check-cite stat rows."""
        legacy_fields = [
            "page", "proposition", "cited_case", "retrieved_case",
            "supporting_language", "assessment", "cl_url", "cl_status",
            "diagnostics", "opinion_file", "quoted_text", "quote_check",
            "quote_check_worst"]
        wd = _report_workdir(tmp_path, [
            {"page": "1", "proposition": "P1.",
             "cited_case": "A v. B, 1 F.3d 1", "assessment": "Green",
             "cl_status": "VERIFIED", "opinion_file": "opinions/a.html",
             "quoted_text": "[]", "quote_check": "[]",
             "quote_check_worst": "NO_QUOTES",
             "retrieved_case": "A v. B"},
            {"page": "2", "proposition": "P2.",
             "cited_case": "C v. D, 2 F.3d 2", "assessment": "Yellow",
             "cl_status": "VERIFIED", "opinion_file": "opinions/a.html",
             "quoted_text": "[]", "quote_check": "[]",
             "quote_check_worst": "NO_QUOTES"},
            {"page": "3", "proposition": "P3.",
             "cited_case": "E v. F, 3 F.3d 3", "assessment": "",
             "cl_status": "NOT_FOUND", "opinion_file": "",
             "quoted_text": "[]", "quote_check": "[]",
             "quote_check_worst": ""},
        ], fieldnames=legacy_fields)
        pp.generate_report(wd, title="T")
        html = (wd / "report.html").read_text(encoding="utf-8")
        assert "Verified Citations" in html
        assert 'class="sev-yellow"' in html
        assert "Unable to verify" in html
        assert 'class="flag-chip"' not in html
```

- [ ] **3.2 Run, verify fail** — `-k ReportLanesRendering`. Expected failures: no sev-orange/stat-orange/flag-chip markup; WRONG_CASE renders yellow; INSUFFICIENT_DATA renders as a yellow finding.

- [ ] **3.3 Implement `generate_report` routing.** Inside the claim loop, replace the `if assessment.lower() == "green" / elif cl_status == "NOT_FOUND"... / else` branching with lane routing (add the lazy import at the top of the function body):

```python
    from .scoring import CHECK_CITE, GRAY, GREEN, report_lane
```

Status-specific gray-lane texts as a module constant near `_STATUS_BADGE_FALLBACK`:

```python
# Gray-lane card explanations per unlocatable status (SS6.9 Gray lane).
_UNLOCATABLE_EXPLANATIONS: dict[str, tuple[str, str]] = {
    # status -> (card explanation, methodology "reason")
    "NOT_FOUND": (
        "Case not found on CourtListener. Cannot verify against "
        "opinion text.",
        "Not in CourtListener database"),
    "INSUFFICIENT_DATA": (
        "The citation lacks the court and year data needed to verify "
        "it against CourtListener.",
        "Citation lacks court and year"),
    "VERIFICATION_INCOMPLETE": (
        "Verification could not complete (infrastructure error during "
        "lookup). Rerun the verify verb.",
        "Verification incomplete -- infrastructure error"),
}
```

Loop body changes (replacing the old branch heads; the existing card-building code inside each branch stays):

```python
        lane = report_lane(cl_status, assessment, opinion_file)
        flag_lines = _crosscheck_flag_lines(claim)

        if lane == GREEN:
            verified.append({
                ...existing fields...,
                "crosscheck_flags": flag_lines,
            })
        elif lane == GRAY:
            explanation, reason = _UNLOCATABLE_EXPLANATIONS.get(
                cl_status, _UNLOCATABLE_EXPLANATIONS["NOT_FOUND"])
            # existing grouped-card code, with:
            #   "explanation": supporting_lang if supporting_lang else explanation
            #   unavailable_list reason -> reason
        else:
            # finding card (existing code), with:
            severity = {"Red": "red", "Yellow": "yellow"}.get(lane, "orange")
            if lane == CHECK_CITE:
                badge_label = _STATUS_BADGE_FALLBACK["CITE_UNCONFIRMED"]
            else:
                badge_label = (claim.get("badge_label", "").strip()
                               or _STATUS_BADGE_FALLBACK.get(cl_status)
                               or ("Not supported by cited case"
                                   if severity == "red"
                                   else "Overstated -- case partially supports"))
            findings.append({..., "crosscheck_flags": flag_lines, ...})
```

- [ ] **3.4 Implement the template changes** in `report_template.py`:

1. `generate_report_html`: count by severity —

```python
    red_count = sum(1 for f in findings if f.get("severity") == "red")
    yellow_count = sum(1 for f in findings if f.get("severity") == "yellow")
    checkcite_count = sum(1 for f in findings
                          if f.get("severity") == "orange")
```

banner condition becomes `if red_count == 0 and checkcite_count == 0:`; pass `checkcite_count` to `_build_dashboard`.

2. `_build_dashboard(total, red, yellow, checkcite, green, gray, findings, unable)` — insert after the yellow stat:

```html
    <div class="stat stat-orange"><div class="stat-num">{checkcite}</div><div class="stat-label">Check cite</div></div>
```

3. New helper + rendering in `_build_findings` (chips at the top of `finding-body`) and `_build_verified` (chips after the badge):

```python
def _build_flags(flag_lines: list[str]) -> str:
    """SS6.5 card-level crosscheck flags -- amber chips."""
    if not flag_lines:
        return ""
    chips = "".join(
        f'<span class="flag-chip">&#9873; {_esc(t)}</span>'
        for t in flag_lines)
    return f'<div class="card-flags">{chips}</div>'
```

In `_build_findings`, before `{brief_block}`: `flags_block = _build_flags(f.get("crosscheck_flags", []))` rendered first inside `finding-body`. In `_build_verified`, append `{_build_flags(v.get("crosscheck_flags", []))}` after the badge inside the item div.

4. CSS additions:

```css
.stat-orange .stat-num { color: #e67e22; }
.issue-list li.sev-orange { border-left-color: #e67e22; background: #fff7ef; }
.card-flags { margin: 0.2rem 0 0.5rem; }
.flag-chip {
  display: inline-block;
  font-size: 0.75rem;
  font-weight: 600;
  background: #fff3e0;
  color: #8a4500;
  border: 1px solid #f0c27a;
  border-radius: 3px;
  padding: 0.1rem 0.5rem;
  margin: 0 0.3rem 0.2rem 0;
}
```

- [ ] **3.5 Run** `-k ReportLanesRendering` (pass) + the pinned legacy suites:

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py tests/test_brief_pipeline.py tests/test_report_template.py -q`
Expected: all PASS with zero edits to `test_brief_pipeline.py` / `test_report_template.py`. (If a `test_report_template.py` test pins `_build_dashboard`'s signature/output, update it for the new stat and say so in the commit.)

- [ ] **3.6 Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py src/citation_verifier/report_template.py tests/test_proposition_pipeline.py
git commit -m "feat: SS6.9 report lanes (Check Cite amber, Gray set) + SS6.5 card flags in generate_report"
```

### Task 4: `run_report` verb + CLI + full-chain close

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (verb after `run_apply_assessments`)
- Modify: `src/citation_verifier/__main__.py` (choices + dispatch + help text)
- Test: `tests/test_proposition_pipeline.py`

- [ ] **4.1 Write the failing tests:**

```python
class TestRunReport:
    def test_writes_report_and_stamps_run_json(self, tmp_path):
        wd = _report_workdir(tmp_path, [
            _row("r-01", cl_status="VERIFIED",
                 opinion_file="opinions/a.html", assessment="Green"),
            _row("r-02", cl_status="CITE_UNCONFIRMED",
                 opinion_file="opinions/a.html", assessment="Yellow"),
            _row("r-03", cl_status="NOT_FOUND"),
            _row("r-04", cl_status="VERIFIED",
                 opinion_file="opinions/a.html", assessment="Red",
                 finding_analysis="Bad."),
        ])
        (wd / "brief_metadata.json").write_text(
            json.dumps({"title": "My Test Brief",
                        "case_name": "Smith v. Jones"}),
            encoding="utf-8")
        stats = pp.run_report(wd)
        assert stats.path == wd / "report.html"
        assert (stats.findings, stats.check_cite,
                stats.verified, stats.unable) == (1, 1, 1, 1)
        html = stats.path.read_text(encoding="utf-8")
        assert "My Test Brief" in html
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert run["verbs"]["report"]["check_cite"] == 1

    def test_tolerates_missing_metadata(self, tmp_path):
        wd = _report_workdir(tmp_path, [_row(
            "r-01", cl_status="VERIFIED",
            opinion_file="opinions/a.html", assessment="Green")])
        stats = pp.run_report(wd)
        assert stats.path.exists()
        assert stats.verified == 1
```

Append to `TestCli`:

```python
    def test_report_verb_dispatch(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import ReportStats
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_report",
            lambda wd: ReportStats(path=Path(wd) / "report.html",
                                   findings=2, check_cite=1,
                                   verified=3, unable=1))
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "report"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[OK] report" in out
        assert "1 check-cite" in out

    def test_full_chain_reaches_report_when_verdicts_complete(
            self, tmp_path, monkeypatch):
        from citation_verifier.__main__ import verify_propositions_main
        order = []
        monkeypatch.setattr(pp, "run_merge",
                            lambda wd: order.append("merge") or
                            pp.MergeStats())
        monkeypatch.setattr(pp, "run_check_quotes",
                            lambda wd: order.append("check-quotes") or
                            pp.QuoteCheckStats())
        monkeypatch.setattr(pp, "run_crosscheck",
                            lambda wd: order.append("crosscheck") or
                            pp.CrosscheckStats())
        monkeypatch.setattr(
            pp, "run_triage",
            lambda wd, prescreen=False, executor=None,
            prompt_version="prescreen-v1": order.append("triage") or
            pp.TriageStats())
        monkeypatch.setattr(
            pp, "run_assess",
            lambda wd, executor=None, prompt_version="assess-v1":
            order.append("assess") or pp.AssessStats(eligible=1, done=1))
        monkeypatch.setattr(
            pp, "run_apply_assessments",
            lambda wd, prompt_version="assess-v1":
            order.append("apply") or pp.ApplyStats(applied=1))
        monkeypatch.setattr(
            pp, "run_report",
            lambda wd: order.append("report") or
            pp.ReportStats(path=Path(wd) / "report.html"))
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / "verification_results.csv").write_text(
            "citation,status\n", encoding="utf-8")  # verify no-ops
        rc = verify_propositions_main([str(wd), "full"])
        assert rc == 0
        assert order == ["merge", "check-quotes", "crosscheck",
                         "triage", "assess", "apply", "report"]
```

- [ ] **4.2 Run, verify fail** — `run_report`/`ReportStats` undefined; `report` not in choices.

- [ ] **4.3 Implement the verb** (after `run_apply_assessments`):

```python
@dataclass
class ReportStats:
    """Statistics from run_report (lane counts are per claims.csv ROW;
    the gray lane groups rows into per-case cards in the HTML)."""
    path: Path | None = None
    findings: int = 0     # Red + Yellow cards
    check_cite: int = 0
    verified: int = 0
    unable: int = 0


def run_report(workdir: Path) -> ReportStats:
    """Verb 8 (design SS3 row 8): claims.csv -> report.html with the
    SS6.9 lanes. Reads brief_metadata.json for the header when present
    (same convention as the legacy verify-brief --report). Idempotent --
    regenerates the HTML on every run."""
    from .scoring import CHECK_CITE, GRAY, GREEN, report_lane

    workdir = Path(workdir)
    meta: dict[str, Any] = {}
    meta_path = workdir / "brief_metadata.json"
    if meta_path.exists():
        try:
            meta = json_mod.loads(meta_path.read_text(encoding="utf-8"))
        except json_mod.JSONDecodeError:
            meta = {}
    path = generate_report(
        workdir,
        title=meta.get("title", ""),
        case_name=meta.get("case_name", ""),
        case_number=meta.get("case_number", ""),
        filed_date=meta.get("filed_date", ""),
        report_date=meta.get("report_date", ""),
    )
    stats = ReportStats(path=path)
    with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
        for c in csv.DictReader(f):
            lane = report_lane(c.get("cl_status", ""),
                               c.get("assessment", ""),
                               c.get("opinion_file", ""))
            if lane == GREEN:
                stats.verified += 1
            elif lane == GRAY:
                stats.unable += 1
            elif lane == CHECK_CITE:
                stats.check_cite += 1
            else:
                stats.findings += 1
    _update_run_json(workdir, "report", findings=stats.findings,
                     check_cite=stats.check_cite,
                     verified=stats.verified, unable=stats.unable)
    return stats
```

- [ ] **4.4 Implement the CLI.** In `verify_propositions_main`: choices become `[..., "apply-assessments", "report", "full"]`; extend the verb help with `"report = claims.csv -> report.html (SS6.9 lanes)"` and the full-chain description to `"... -> assess (-> apply -> report when verdicts are complete)"`. In `_dispatch_proposition_verbs`, after the apply-assessments block:

```python
    if args.verb in ("report", "full"):
        rstats = pp.run_report(workdir)
        print(f"[OK] report: {rstats.path} -- {rstats.findings} findings, "
              f"{rstats.check_cite} check-cite, {rstats.verified} "
              f"verified, {rstats.unable} unable-to-verify")
```

(The assess block's `return 0` on pending already keeps `full` from reaching report before verdicts land.)

- [ ] **4.5 Run** new tests + `tests/test_proposition_pipeline.py -q` (the existing `test_full_chain_runs_new_verbs_in_order` pins the pending-stop path and must still pass).

- [ ] **4.6 Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py src/citation_verifier/__main__.py tests/test_proposition_pipeline.py
git commit -m "feat: report verb + CLI -- full chain now ends verify..apply->report (SS3 row 8)"
```

### Task 5: `.claude/skills/proposition-verifier/SKILL.md` (thin stub)

**Files:**
- Create: `.claude/skills/proposition-verifier/SKILL.md`
- `verify-brief/SKILL.md` stays FROZEN — do not touch.

- [ ] **5.1 Write the stub** (orchestration only; ~40 lines; every rule about WHAT to assess lives in `src/citation_verifier/prompts/`):

```markdown
---
name: proposition-verifier
description: Use when the user wants to verify that cited cases support the propositions they're cited for -- in a brief, motion, or opinion PDF, or a prepared list of (citation, proposition) pairs. Triggers on "verify propositions", "proposition verifier", "verify this brief", "check the citations in this brief". Supersedes /verify-brief (which stays frozen for old runs in briefs/).
argument-hint: "[path to brief PDF, or path to a prepared claims.csv]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /proposition-verifier — thin trigger for the proposition pipeline

All logic lives in the pipeline (`python -m citation_verifier verify-propositions`, design `docs/plans/2026-06-11-proposition-verifier-pipeline-design.md`) and the versioned prompt templates in `src/citation_verifier/prompts/`. **Do not add assessment criteria, batching rules, or prompt text to this file** — that is template work (a new prompt version + re-record).

## Steps

1. **Startup checks:** `venv/Scripts/python.exe -m citation_verifier --help` runs, and `.env` contains `COURTLISTENER_API_TOKEN` (else point the user at courtlistener.com > Profile > API Keys). Windows: always `venv/Scripts/python.exe`.
2. **Workdir:** create `matters/<short-name>/` (ask for a name if not obvious). If the source document has a caption, write `matters/<name>/brief_metadata.json` with `{"title", "case_name", "case_number", "filed_date"}` (used for the report header). For prepared pairs, copy the user's CSV to `matters/<name>/claims.csv` (columns per design §2; missing optional columns are tolerated).
3. **Run the chain:**
   - Document input: `venv/Scripts/python.exe -m citation_verifier verify-propositions matters/<name> full --document <path>`
   - Prepared pairs: the same command without `--document`.
4. **When the CLI prints PENDING** (extract, prescreen, or assess jobs), dispatch agents (step 5), then **rerun the same `full` command** — every verb is idempotent and resumes from the jobs sidecars.
5. **Jobs-mode dispatch:** read the pending jobs file (`jobs/extract.json`, `jobs/assess.json`, or `jobs/prescreen.json`). For each job, launch one general-purpose Agent subagent whose prompt is the job's `prompt` field verbatim, plus this appendix:

   > After producing your JSON object, append it as ONE line to `<workdir>/jobs/<phase>_results.jsonl` in this envelope:
   > `{"claim_id": "<the job's claim_ids[0]>", "prompt_version": "<the job's prompt_version>", "model": "<your model>", "fields": <your JSON object>}`
   > Use only the Read tool on files in the workdir, plus that one append. No other tools.

   Run assess subagents in parallel, at most ~5 at a time. Do not edit claims.csv yourself — `apply-assessments` owns it (design §6.6).
6. **Finish:** the chain ends with `[OK] report: matters/<name>/report.html`. Open it for the user and summarize in chat: each Red finding with a one-line rationale; Yellow and Check Cite counts with brief notes; Green count; unable-to-verify cases.

## Resuming

Rerun the `full` command. Each verb no-ops when its output exists (`--force` to redo extract/verify), and the chain stops at the first pending LLM step.
```

- [ ] **5.2 Manual check:** every command in the stub exists (`verify-propositions ... full --document`, jobs filenames, envelope fields match `verdict_to_json` in `executor.py`: claim_id, prompt_version, model, fields). No Green/Yellow/Red criteria text anywhere in the file.

- [ ] **5.3 Commit**

```bash
git add .claude/skills/proposition-verifier/SKILL.md
git commit -m "feat: proposition-verifier SKILL stub -- thin orchestration wrapper (SS2/SS9); verify-brief stays frozen"
```

### Task 6: A/B harness re-point — `tools/ab_test_runner.py`

**Files:**
- Move + rewrite: `tests/ab_test_runner.py` -> `tools/ab_test_runner.py`
- Test: `tests/test_ab_runner.py` (new)
- Unchanged: `tests/ab_test_cases.json`, `tests/ab_test_configs.json`, `tests/build_review_page.py`

Contract (§9 / §3 "A/B testing per phase"): a config = {model, executor, prompt_version}; the harness runs the **assess verb over a copy of a frozen corpus workdir** and scores with `scoring.score_workdir` against `ground_truth.csv`. The old runner's inline prompt copy is deleted — `prompts/assess_v1.md` (byte-pinned) is now the single source. `include_hints` configs are **rejected with a clear error**: assess-v1 cannot consume `prescreen_hint` (deferred to assess-v2 per the step-6 plan).

- [ ] **6.1 `git mv tests/ab_test_runner.py tools/ab_test_runner.py`** (history-preserving), then rewrite the file:

```python
"""A/B harness for the assessment phase (design SS9; roadmap Tier 2 #9).

Runs the assess verb over COPIES of frozen corpus workdirs
(tests/data/assessment_corpora/) with a named config from
tests/ab_test_configs.json, then scores each copy against its
ground_truth.csv via citation_verifier.scoring. The prompt is the
pipeline's versioned template -- this harness no longer carries its own
prompt copy (the old tests/ab_test_runner.py copy WAS the assess-v1
source text; it is now byte-pinned in
src/citation_verifier/prompts/assess_v1.md).

Config keys: model (default opus), executor ("sdk" only -- live runs
need `claude login` credentials), prompt_version (default assess-v1).
include_hints configs are rejected: assess-v1 cannot consume
prescreen_hint (assess-v2 work).

Usage:
    venv/Scripts/python.exe tools/ab_test_runner.py --replay
        # offline: score the frozen cassettes (the recorded baseline)
    venv/Scripts/python.exe tools/ab_test_runner.py --config opus-baseline
        # live: copy corpora, run assess via the Agent SDK, score
    venv/Scripts/python.exe tools/ab_test_runner.py --config A B
    venv/Scripts/python.exe tools/ab_test_runner.py --compare X.jsonl Y.jsonl
    venv/Scripts/python.exe tools/ab_test_runner.py --config opus-baseline --dry-run

tests/ab_test_cases.json stays the human-review ledger; ground_truth.csv
is generated from it by tests/build_assessment_corpora.py.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

CORPORA = PROJECT_ROOT / "tests" / "data" / "assessment_corpora"
RESULTS_DIR = PROJECT_ROOT / "tests" / "data" / "results"
CONFIGS_FILE = PROJECT_ROOT / "tests" / "ab_test_configs.json"
DEFAULT_CORPORA = ("payne", "wainwright")


def load_configs(path=CONFIGS_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["configs"]


def make_executor(config, workdir):
    """Default executor factory: headless Agent SDK (design SS5)."""
    transport = config.get("executor", "sdk")
    if transport != "sdk":
        raise ValueError(
            f"unsupported executor {transport!r}: the harness runs "
            f"headless (sdk) or --replay only")
    from citation_verifier.executor import AgentSDKExecutor
    return AgentSDKExecutor(model=config.get("model", "opus"),
                            cwd=str(workdir))


def run_ab_config(config_name, config, corpora=DEFAULT_CORPORA,
                  run_root=None, executor_factory=None, replay=False):
    """Run one config over the corpora; returns {corpus: CorpusScore}.

    replay=True scores each FROZEN corpus in place via its recorded
    cassette (read-only; no LLM). Otherwise each corpus is copied to
    run_root/<corpus>, its cassette removed, assess run through the
    factory-built executor, and the copy scored.
    """
    from citation_verifier.proposition_pipeline import run_assess
    from citation_verifier.scoring import format_report, score_workdir

    if config.get("include_hints"):
        raise ValueError(
            "include_hints configs need assess-v2 (prescreen_hint "
            "consumption is deferred); see the step-6 plan notes")
    prompt_version = config.get("prompt_version", "assess-v1")
    scores = {}
    for name in corpora:
        src = CORPORA / name
        if replay:
            scores[name] = score_workdir(src,
                                         prompt_version=prompt_version)
        else:
            if run_root is None:
                raise ValueError("run_root is required for live runs")
            wd = Path(run_root) / name
            shutil.copytree(src, wd)
            cassette = wd / "jobs" / "assess_results.jsonl"
            if cassette.exists():
                cassette.unlink()  # fresh verdicts for this config
            executor = (executor_factory or make_executor)(config, wd)
            stats = run_assess(wd, executor=executor,
                               prompt_version=prompt_version)
            failures = getattr(executor, "failures", [])
            if failures:
                print(f"  WARNING {name}: {len(failures)} job "
                      f"failures: {failures[:3]}")
            if stats.pending:
                print(f"  WARNING {name}: {stats.pending} verdicts "
                      f"still pending -- scoring the rest")
            scores[name] = score_workdir(wd,
                                         prompt_version=prompt_version)
        print(format_report(f"{config_name}/{name}", scores[name]))
    return scores


def dry_run_config(config_name, config, corpora=DEFAULT_CORPORA):
    """Print how many assess jobs each corpus would run. No copies."""
    import csv
    from citation_verifier.proposition_pipeline import _assessable
    print(f"=== {config_name} (dry run) ===")
    for name in corpora:
        with open(CORPORA / name / "claims.csv", newline="",
                  encoding="utf-8") as f:
            n = sum(1 for c in csv.DictReader(f) if _assessable(c))
        print(f"  {name}: {n} assess jobs "
              f"(model={config.get('model', 'opus')}, "
              f"prompt={config.get('prompt_version', 'assess-v1')})")


def save_results(config_name, scores):
    """Per-claim score rows to a timestamped JSONL (compare format)."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"ab_{config_name}_{ts}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for corpus, score in scores.items():
            for row in score.rows:
                f.write(json.dumps({"corpus": corpus, **row}) + "\n")
    print(f"  Results saved to {out}")
    return out


def compare_results(file_a, file_b):
    """Side-by-side comparison of two saved score-row files, keyed by
    (corpus, claim_id). New format only (old case_id files predate the
    re-point)."""
    def load(path):
        rows = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                rows[(r["corpus"], r["claim_id"])] = r
        return rows

    a, b = load(file_a), load(file_b)
    name_a, name_b = Path(file_a).stem, Path(file_b).stem
    keys = sorted(set(a) | set(b))
    print(f"\n=== {name_a} vs {name_b} ===")
    disagreements = []
    for k in keys:
        ra, rb = a.get(k, {}), b.get(k, {})
        pa, pb = ra.get("predicted", "-"), rb.get("predicted", "-")
        if pa != pb:
            disagreements.append(k)
            print(f"  DIFF {k[0]}/{k[1]}: expected "
                  f"{ra.get('expected') or rb.get('expected')}, "
                  f"{name_a[:20]}={pa}, {name_b[:20]}={pb}")
    for name, rows in ((name_a, a), (name_b, b)):
        scored = [r for r in rows.values() if "correct" in r]
        correct = sum(1 for r in scored if r["correct"])
        print(f"  {name}: {correct}/{len(scored)} correct")
    print(f"  Disagreements: {len(disagreements)} of {len(keys)}")


def main():
    parser = argparse.ArgumentParser(
        description="A/B harness: assess verb over frozen corpus "
                    "workdirs, scored against ground truth (SS9)")
    parser.add_argument("--config", nargs="+",
                        help="config name(s) from tests/ab_test_configs.json")
    parser.add_argument("--corpus", nargs="+", default=list(DEFAULT_CORPORA),
                        help="corpus names under tests/data/assessment_corpora")
    parser.add_argument("--replay", action="store_true",
                        help="score the frozen cassettes offline (no LLM)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print job counts; run nothing")
    parser.add_argument("--compare", nargs=2, metavar="FILE",
                        help="compare two saved score-row JSONL files")
    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare[0], args.compare[1])
        return

    if args.replay:
        run_ab_config("replay", {}, corpora=args.corpus, replay=True)
        return

    if not args.config:
        parser.error("specify --config, --replay, or --compare")

    configs = load_configs()
    outfiles = []
    for name in args.config:
        if name not in configs:
            print(f"Unknown config: {name}. "
                  f"Available: {list(configs)}")
            sys.exit(1)
        if args.dry_run:
            dry_run_config(name, configs[name], corpora=args.corpus)
            continue
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_root = RESULTS_DIR / "ab_runs" / f"{name}_{ts}"
        run_root.mkdir(parents=True, exist_ok=True)
        scores = run_ab_config(name, configs[name], corpora=args.corpus,
                               run_root=run_root)
        outfiles.append(save_results(name, scores))
    if len(outfiles) == 2:
        compare_results(str(outfiles[0]), str(outfiles[1]))


if __name__ == "__main__":
    main()
```

- [ ] **6.2 Write the offline tests** — `tests/test_ab_runner.py`:

```python
"""Offline tests for the re-pointed A/B harness (design SS9).

The harness's executor seam is exercised with RecordedExecutor over the
frozen corpora -- no LLM, no network. Frozen corpora are read-only here
(live mode copies them to tmp_path first).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import ab_test_runner as ab  # noqa: E402


class TestReplayMode:
    def test_scores_frozen_cassettes(self, capsys):
        scores = ab.run_ab_config("baseline", {}, replay=True)
        assert (scores["payne"].correct, scores["payne"].total) == (23, 27)
        assert (scores["wainwright"].correct,
                scores["wainwright"].total) == (33, 34)
        assert "baseline/payne" in capsys.readouterr().out


class TestLiveModeOfflineSeam:
    def test_injected_executor_runs_assess_and_scores(self, tmp_path):
        from citation_verifier.executor import RecordedExecutor

        def factory(config, wd):
            # replay the ORIGINAL frozen cassette as if it were live
            return RecordedExecutor(
                ab.CORPORA / wd.name / "jobs" / "assess_results.jsonl")

        scores = ab.run_ab_config(
            "test", {"model": "opus"}, corpora=("payne",),
            run_root=tmp_path, executor_factory=factory)
        assert (scores["payne"].correct, scores["payne"].total) == (23, 27)
        # the copy got a fresh cassette written through run_assess
        copy_cassette = tmp_path / "payne" / "jobs" / "assess_results.jsonl"
        assert copy_cassette.exists()
        # frozen corpus untouched
        assert (ab.CORPORA / "payne" / "jobs" /
                "assess_results.jsonl").exists()

    def test_live_requires_run_root(self):
        with pytest.raises(ValueError, match="run_root"):
            ab.run_ab_config("x", {}, corpora=("payne",))

    def test_hint_config_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="assess-v2"):
            ab.run_ab_config("hints", {"include_hints": True},
                             corpora=("payne",), run_root=tmp_path)


class TestSaveAndCompare:
    def test_roundtrip(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(ab, "RESULTS_DIR", tmp_path)
        scores = ab.run_ab_config("baseline", {}, corpora=("payne",),
                                  replay=True)
        out = ab.save_results("baseline", scores)
        assert out.exists()
        capsys.readouterr()
        ab.compare_results(str(out), str(out))
        printed = capsys.readouterr().out
        assert "23/27 correct" in printed
        assert "Disagreements: 0" in printed


class TestDryRun:
    def test_prints_job_counts(self, capsys):
        ab.dry_run_config("opus-baseline", {"model": "opus"},
                          corpora=("payne",))
        out = capsys.readouterr().out
        assert "assess jobs" in out
```

- [ ] **6.3 Run, verify fail first** (before the rewrite lands the tests fail on import/missing functions if executed mid-task; the natural order here is 6.1 then 6.2 then run — the move+rewrite and tests land in one commit since the old file is deleted by the move).

Run: `venv/Scripts/python.exe -m pytest tests/test_ab_runner.py -v`
Expected: all PASS. Then `venv/Scripts/python.exe tools/ab_test_runner.py --replay` prints both corpus reports (payne 23/27, wainwright 33/34) and `--config opus-baseline --dry-run` prints job counts without touching anything.

- [ ] **6.4 Verify the regression + corpora suites still pass** (frozen corpora untouched):

Run: `venv/Scripts/python.exe -m pytest tests/test_assessment_regression.py tests/test_assessment_corpora.py -q`
Expected: PASS, `git status` shows no changes under `tests/data/assessment_corpora/`.

- [ ] **6.5 Commit**

```bash
git add tools/ab_test_runner.py tests/test_ab_runner.py
git rm tests/ab_test_runner.py  # already staged by git mv; confirm
git commit -m "refactor: A/B harness re-pointed at executor + frozen-workdir contract; moved to tools/ (SS9, Tier 2 #9)"
```

### Task 7: Docs, full suite, push

- [ ] **7.1 CLAUDE.md updates:**
  - `proposition_pipeline.py` row: add `run_report()` (§3 row 8: brief_metadata.json header + §6.9 lanes via `scoring.report_lane` + §6.5 flag chips from `_crosscheck_flag_lines`; `ReportStats`); CLI verb list gains `report`; `full` now chains `verify -> merge -> check-quotes -> crosscheck -> triage -> assess -> apply-assessments -> report`.
  - `scoring.py` row: add `report_lane()` (v1-schema lane precedence: WRONG_CASE Red > CITE_UNCONFIRMED CheckCite-never-Red > unlocatable-no-text Gray > assessment column authoritative; switches to derive_color when v2 fills `support`).
  - `report_template.py` row: mention Check Cite stat/lane + flag chips.
  - Tests table: `ab_test_runner.py` row moves to a new `tools/` note (`tools/ab_test_runner.py` — A/B harness over frozen corpora via the executor contract; `test_ab_runner.py` — its offline tests).
  - Skills section: add `/proposition-verifier` (thin stub; criteria live in versioned templates); note `/verify-brief` is frozen for old runs.
- [ ] **7.2** Append Execution notes to this plan (deviations, measured counts).
- [ ] **7.3 Full offline suite:**

Run: `venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_false_negatives.py --ignore=tests/test_cl_api_issues.py`
Expected: >= 745 passed + this step's new tests, 0 failures; `test_assessment_regression.py` / `test_assessment_corpora.py` unchanged.

- [ ] **7.4 Commit + push**

```bash
git add CLAUDE.md docs/plans/2026-06-11-prop-pipeline-step7-report-skill-ab-plan.md
git commit -m "docs: Step 7 execution notes + CLAUDE.md (report verb, report_lane, SKILL stub, A/B re-point)"
git push origin pipeline-redesign
```

---

## Self-review notes

- **The design tension is resolved before code** (plan §"DECIDED"): `report_lane` precedence table, with the v2 hand-off documented in its docstring. `derive_color` is untouched.
- §3 row 8 (report verb) → Tasks 3-4; §6.9 lanes (CheckCite never Red, Gray set) → Tasks 1+3; §6.5 card flags incl. on greens → Tasks 2-3; legacy fallback preservation → Task 3 row-4 routing + the pinned `test_brief_pipeline.py` suite passing unchanged.
- §2/§9 SKILL stub → Task 5: orchestration only (startup, workdir under `matters/`, verb sequence, jobs dispatch envelope matching `verdict_to_json`, report open); zero assessment criteria; verify-brief frozen.
- §9 A/B re-point → Task 6: executor + frozen-workdir contract, prompt sourced from the byte-pinned template (the harness's own copy deleted), relocated to `tools/`; `ab_test_cases.json`/`build_review_page.py` untouched; hint configs explicitly deferred to assess-v2; offline tests reproduce payne 23/27 + wainwright 33/34.
- Type consistency: `report_lane` returns the `scoring` color constants; `generate_report` maps `{Red->red, Yellow->yellow, CheckCite->orange}`; `ReportStats(path, findings, check_cite, verified, unable)` used identically in Task 4's verb, CLI print, and tests; `run_ab_config(config_name, config, corpora, run_root, executor_factory, replay)` matches every test call.
- Deferred (Step 8, per the step-6 plan): prescreen_hint consumption, assess honoring triage_track, §6.8 packing, assess-template prohibition, prescreen default decision, the Withers pincite-flag inspection, acceptance runs + retro.

## Execution notes

(to be filled during execution)
