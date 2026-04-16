# Unified Brief Verifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Combine the best of `/verify-brief` (fast pipeline, Python library, batch verify, opinion download) with `/proposition-verifier` (report format, assessment calibration, quote presentation) into a single `/verify-brief` skill.

**Architecture:** Keep `brief_pipeline.py` as the mechanical engine (batch verify, download, merge, quote check). Replace the skill's assessment prompts with proposition-verifier's stricter calibration. Add a triage gate: quote check + metadata check determine which claims need expensive Opus assessment vs. auto-Green. For flagged claims, grep opinion files first for targeted excerpts; only fall back to Haiku full-read when greps miss on large opinions. Replace the report template with proposition-verifier's collapsible-details format. Add `--report` and `--metadata-check` CLI commands to `brief_pipeline.py`.

**Tech Stack:** Python 3.10+, `citation_verifier` package, Claude Code agents (Opus for assessment, Haiku for summaries), HTML/CSS/JS for reports.

---

## Context for the implementer

This plan merges two skills that were A/B tested on the same brief (Brooks v. Lowe's, 2026-04-15):

- **`/verify-brief`** — Uses `brief_pipeline.py` for mechanical work. Fast (~9 min), batch API calls, finds more cases (including NY state via RECAP). But: report is a flat table, assessment prompts are too lenient (Collins and Abel were Yellow when they should have been Red), quote presentation shows similarity scores instead of actual text comparisons.

- **`/proposition-verifier`** — Uses CourtListener MCP for retrieval. Slower (~31 min), but: report uses collapsible `<details>` with paired blockquotes ("What the brief claims" / "What the opinion actually says"), assessments are stricter, quote differences are shown as exact text comparisons. The debrief document also identified a key architectural insight: quote verification is cheap and deterministic (grep for the string), while propositional assessment is expensive and judgmental — they should be separate workflows with different triage logic.

**Key files to understand before starting:**
- `src/citation_verifier/brief_pipeline.py` — wave1/wave2/merge/check_quotes (the mechanical engine, stays)
- `.claude/skills/verify-brief/SKILL.md` — the skill prompt (gets rewritten)
- `.claude/skills/proposition-verifier/SKILL.md` — the report format and assessment criteria to adopt
- `briefs-2/gov.uscourts.lawd.207038.49.1_proposition_report.html` — the target report format
- `briefs/gov.uscourts.lawd.207038.49.1/report.html` — the old report format being replaced
- `tests/test_brief_pipeline.py` — existing tests for the pipeline

**What stays the same:**
- `brief_pipeline.py` functions: `wave1_verify_and_download`, `wave2_fallback_and_download`, `merge_claims`, `check_quotes`
- The CLI entry point structure (`verify-brief` subcommand)
- The working directory layout (`briefs/<name>/`)

**What changes:**
1. Preserve syllabus data from citation-lookup API response through the pipeline
2. New `generate_report()` function in `brief_pipeline.py` with `--report` CLI flag
3. New `metadata_check()` function in `brief_pipeline.py` with `--metadata-check` CLI flag (uses syllabus for topic-mismatch detection)
4. Rewritten SKILL.md with new phases, assessment prompts, and report generation
5. Proposition-verifier skill removed (merged into verify-brief)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/citation_verifier/models.py` | Modify | Add `matched_syllabus` field to `VerificationResult` |
| `src/citation_verifier/verifier.py` | Modify | Extract `syllabus` from cluster in `_process_citation_lookup_hit` |
| `src/citation_verifier/brief_pipeline.py` | Modify | Add `generate_report()`, `metadata_check()`, write syllabus to CSV |
| `src/citation_verifier/report_template.py` | Create | HTML template as a Python string (keeps `brief_pipeline.py` readable) |
| `.claude/skills/verify-brief/SKILL.md` | Rewrite | New phases, assessment prompts, report generation |
| `.claude/skills/proposition-verifier/SKILL.md` | Delete | Merged into verify-brief |
| `src/citation_verifier/__main__.py` | Modify | Add `--report` and `--metadata-check` CLI flags |
| `tests/test_brief_pipeline.py` | Modify | Add tests for `generate_report()` and `metadata_check()` |
| `tests/test_report_template.py` | Create | Tests for HTML template rendering |
| `tests/test_verifier.py` | Modify | Verify syllabus is preserved in VerificationResult |

---

## Task 1: Report template module

The proposition-verifier report HTML is the target format. Extract it into a Python module that takes structured data and returns HTML. This is the foundation — everything else feeds into it.

**Files:**
- Create: `src/citation_verifier/report_template.py`
- Test: `tests/test_report_template.py`

- [ ] **Step 1: Write the test for report generation**

```python
# tests/test_report_template.py
"""Tests for HTML report generation."""
import pytest
from citation_verifier.report_template import generate_report_html


@pytest.fixture
def sample_report_data():
    """Minimal report data for testing."""
    return {
        "title": "Test Brief",
        "case_name": "Smith v. Jones",
        "case_number": "No. 1:24-CV-00001 (S.D. Ohio)",
        "filed_date": "January 1, 2026",
        "report_date": "April 15, 2026",
        "findings": [
            {
                "id": "finding-1",
                "page": "3",
                "case_name": "Tompkins v. Cyr",
                "citation": "202 F.3d 770, 787 (5th Cir. 2000)",
                "cl_url": "https://www.courtlistener.com/opinion/19782/tompkins-v-cyr/",
                "severity": "red",
                "badge_label": "Not supported by cited case",
                "brief_text": "Courts hold that prior settlement evidence is irrelevant.",
                "opinion_text": "This case is about anti-abortion protesters.",
                "explanation": "Complete subject matter mismatch.",
            },
        ],
        "verified": [
            {
                "page": "6",
                "case_name": "King v. Illinois Cent. R.R.",
                "citation": "337 F.3d 550, 556 (5th Cir. 2003)",
                "cl_url": "https://www.courtlistener.com/opinion/8437633/",
                "proposition": "Spoliation requires bad faith.",
                "badge_label": "Supported",
                "supporting_language": "An adverse inference is predicated on bad conduct.",
            },
        ],
        "unable_to_verify": [
            {
                "id": "finding-uv-1",
                "page": "7",
                "case_name": "Menges v. Cliffs Drilling Co.",
                "citation": "2000 WL 765082 (E.D. La. 2000)",
                "brief_text": "Plaintiff did not have a duty to delay surgery.",
                "explanation": "WestLaw-only citation, not in CourtListener.",
            },
        ],
        "retrieved_opinions": [
            {"case_name": "Tompkins v. Cyr", "citation": "202 F.3d 770", "cluster_id": "19782"},
            {"case_name": "King v. Illinois Cent. R.R.", "citation": "337 F.3d 550", "cluster_id": "8437633"},
        ],
        "unavailable_opinions": [
            {"case_name": "Menges v. Cliffs Drilling Co.", "citation": "2000 WL 765082", "reason": "WestLaw-only"},
        ],
    }


class TestReportGeneration:
    def test_returns_valid_html(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_case_metadata(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Smith v. Jones" in html
        assert "No. 1:24-CV-00001" in html

    def test_contains_red_finding(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Tompkins v. Cyr" in html
        assert "Not supported by cited case" in html
        assert "anti-abortion protesters" in html

    def test_contains_verified_section(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "King v. Illinois Cent. R.R." in html
        assert "Spoliation requires bad faith" in html

    def test_contains_unable_to_verify(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Menges v. Cliffs Drilling Co." in html
        assert "Unable to verify" in html

    def test_contains_methodology(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "Methodology" in html
        assert "retrieved from CourtListener" in html
        assert "not available on CourtListener" in html

    def test_dashboard_counts(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        # Should have counts for findings, verified, unable
        assert "Serious issues" in html or "serious issue" in html.lower()

    def test_expand_collapse_controls(self, sample_report_data):
        html = generate_report_html(sample_report_data)
        assert "expandAll" in html
        assert "collapseAll" in html

    def test_empty_findings(self, sample_report_data):
        """Report with no issues should show all-clear banner."""
        sample_report_data["findings"] = []
        html = generate_report_html(sample_report_data)
        assert "No serious issues found" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_report_template.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation_verifier.report_template'`

- [ ] **Step 3: Write the report template module**

Create `src/citation_verifier/report_template.py`. This is the proposition-verifier's HTML structure as a Python template. The function takes the data dict from the test fixture and returns an HTML string.

```python
# src/citation_verifier/report_template.py
"""HTML report template for brief verification results.

Generates an interactive HTML report in the proposition-verifier style:
collapsible findings, paired blockquotes, methodology disclosure.
"""

from __future__ import annotations


def generate_report_html(data: dict) -> str:
    """Generate a complete HTML report from structured verification data.

    Args:
        data: Dict with keys: title, case_name, case_number, filed_date,
              report_date, findings (list of issue dicts), verified (list),
              unable_to_verify (list), retrieved_opinions (list),
              unavailable_opinions (list).

    Returns:
        Complete HTML document as a string.
    """
    findings = data.get("findings", [])
    verified = data.get("verified", [])
    unable = data.get("unable_to_verify", [])
    retrieved = data.get("retrieved_opinions", [])
    unavailable = data.get("unavailable_opinions", [])

    total_checked = len(findings) + len(verified) + len(unable)
    red_count = sum(1 for f in findings if f.get("severity") == "red")
    yellow_count = sum(1 for f in findings if f.get("severity") == "yellow")
    green_count = len(verified)
    gray_count = len(unable)

    # Build sections
    dashboard_html = _build_dashboard(
        total_checked, red_count, yellow_count, green_count, gray_count,
        findings, unable,
    )
    findings_html = _build_findings(findings)
    verified_html = _build_verified(verified)
    unable_html = _build_unable_to_verify(unable)
    methodology_html = _build_methodology(retrieved, unavailable)

    # All-clear banner
    all_clear = ""
    if red_count == 0:
        if yellow_count > 0:
            all_clear = (
                '<div style="background:#d4edda;border:1px solid #c3e6cb;'
                'border-radius:6px;padding:1rem;margin-bottom:1rem;">'
                f'<strong>No serious issues found.</strong> {yellow_count} minor '
                f'note{"s" if yellow_count != 1 else ""} below.</div>'
            )
        else:
            all_clear = (
                '<div style="background:#d4edda;border:1px solid #c3e6cb;'
                'border-radius:6px;padding:1rem;margin-bottom:1rem;">'
                '<strong>No serious issues found.</strong> All citations verified.</div>'
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proposition Verification Report — {_esc(data.get("case_name", ""))}</title>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=Source+Sans+3:wght@300;400;600&display=swap" rel="stylesheet">
<style>
{_CSS}
</style>
<script>
function expandAll() {{ document.querySelectorAll('details').forEach(d => d.open = true); }}
function collapseAll() {{ document.querySelectorAll('details').forEach(d => d.open = false); }}
</script>
</head>
<body>

<h1>Proposition Verification Report</h1>
<div class="meta">
  <span><strong>Brief:</strong> {_esc(data.get("title", ""))}</span><br>
  <span><strong>Case:</strong> <em>{_esc(data.get("case_name", ""))}</em>, {_esc(data.get("case_number", ""))}</span><br>
  <span><strong>Filed:</strong> {_esc(data.get("filed_date", ""))}</span>
  <span><strong>Report generated:</strong> {_esc(data.get("report_date", ""))}</span>
</div>

{all_clear}
{dashboard_html}
{findings_html}
{unable_html}
{verified_html}
{methodology_html}

</body>
</html>"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _badge(label: str, severity: str) -> str:
    """Render a severity badge."""
    css_class = {
        "red": "badge-red",
        "yellow": "badge-yellow",
        "orange": "badge-orange",
        "green": "badge-green",
        "blue": "badge-blue",
        "gray": "badge-gray",
    }.get(severity, "badge-gray")
    return f'<span class="badge {css_class}">{_esc(label)}</span>'


def _build_dashboard(
    total: int, red: int, yellow: int, green: int, gray: int,
    findings: list[dict], unable: list[dict],
) -> str:
    """Build the summary dashboard."""
    issue_items = []
    for f in findings:
        sev = f.get("severity", "yellow")
        anchor = f.get("id", "")
        case = f.get("case_name", "")
        citation = f.get("citation", "")
        badge_label = f.get("badge_label", "")
        explanation = f.get("explanation", "")
        # Truncate explanation for the dashboard
        short_expl = explanation[:120] + "..." if len(explanation) > 120 else explanation
        issue_items.append(
            f'<li class="sev-{sev}"><a href="#{anchor}">'
            f'{_badge(badge_label, sev)} '
            f'p. {_esc(f.get("page", ""))} &mdash; '
            f'<em>{_esc(case)}</em>, {_esc(citation)} &mdash; '
            f'{_esc(short_expl)}</a></li>'
        )
    for u in unable:
        anchor = u.get("id", "")
        case = u.get("case_name", "")
        citation = u.get("citation", "")
        issue_items.append(
            f'<li class="sev-gray"><a href="#{anchor}">'
            f'{_badge("Unable to verify", "gray")} '
            f'p. {_esc(u.get("page", ""))} &mdash; '
            f'<em>{_esc(case)}</em>, {_esc(citation)} &mdash; '
            f'{_esc(u.get("explanation", "")[:120])}</a></li>'
        )

    issues_html = "\n".join(issue_items) if issue_items else "<li>None</li>"

    return f"""<div class="dashboard">
  <h2 style="border:none; margin-top:0; padding:0;">Summary</h2>
  <div class="stats">
    <div class="stat"><div class="stat-num">{total}</div><div class="stat-label">Claims checked</div></div>
    <div class="stat stat-red"><div class="stat-num">{red}</div><div class="stat-label">Serious issues</div></div>
    <div class="stat stat-yellow"><div class="stat-num">{yellow}</div><div class="stat-label">Minor notes</div></div>
    <div class="stat stat-green"><div class="stat-num">{green}</div><div class="stat-label">Verified</div></div>
    <div class="stat stat-gray"><div class="stat-num">{gray}</div><div class="stat-label">Unable to verify</div></div>
  </div>
  <h3>Issues</h3>
  <ul class="issue-list">
    {issues_html}
  </ul>
</div>"""


def _build_findings(findings: list[dict]) -> str:
    """Build the findings walkthrough section."""
    if not findings:
        return ""

    items = []
    for f in findings:
        sev = f.get("severity", "yellow")
        badge_label = f.get("badge_label", "")
        cl_url = f.get("cl_url", "")
        case_link = (
            f'<a href="{_esc(cl_url)}"><span class="case-name">{_esc(f.get("case_name", ""))}</span></a>'
            if cl_url else
            f'<span class="case-name">{_esc(f.get("case_name", ""))}</span>'
        )

        brief_block = ""
        if f.get("brief_text"):
            brief_block = (
                '<div class="bq-label">What the brief claims:</div>'
                f'<div class="bq-brief">{_esc(f["brief_text"])}</div>'
            )

        opinion_block = ""
        if f.get("opinion_text"):
            opinion_block = (
                '<div class="bq-label">What the opinion actually says:</div>'
                f'<div class="bq-opinion">{f["opinion_text"]}</div>'
            )

        explanation_block = ""
        if f.get("explanation"):
            explanation_block = (
                f'<div class="explanation"><strong>Assessment:</strong> '
                f'{f["explanation"]}</div>'
            )

        items.append(f"""<details id="{_esc(f.get("id", ""))}">
  <summary>
    <strong>p. {_esc(f.get("page", ""))}</strong> &mdash;
    {case_link}, {_esc(f.get("citation", ""))}
    &mdash; {_badge(badge_label, sev)}
  </summary>
  <div class="finding-body">
    {brief_block}
    {opinion_block}
    {explanation_block}
  </div>
</details>""")

    controls = (
        '<div class="controls">'
        '<button onclick="expandAll()">Expand All</button> | '
        '<button onclick="collapseAll()">Collapse All</button>'
        '</div>'
    )

    return f"""<h2>Findings</h2>
{controls}
{"".join(items)}"""


def _build_unable_to_verify(unable: list[dict]) -> str:
    """Build the unable-to-verify section."""
    if not unable:
        return ""

    items = []
    for u in unable:
        brief_block = ""
        if u.get("brief_text"):
            brief_block = (
                '<div class="bq-label">What the brief claims:</div>'
                f'<div class="bq-brief">{_esc(u["brief_text"])}</div>'
            )
        items.append(f"""<details id="{_esc(u.get("id", ""))}">
  <summary>
    <strong>p. {_esc(u.get("page", ""))}</strong> &mdash;
    <span class="case-name">{_esc(u.get("case_name", ""))}</span>, {_esc(u.get("citation", ""))}
    &mdash; {_badge("Unable to verify -- opinion text unavailable", "gray")}
  </summary>
  <div class="finding-body">
    {brief_block}
    <div class="explanation">{_esc(u.get("explanation", ""))}</div>
  </div>
</details>""")

    return "\n".join(items)


def _build_verified(verified: list[dict]) -> str:
    """Build the collapsed verified-citations section."""
    if not verified:
        return ""

    items = []
    for v in verified:
        cl_url = v.get("cl_url", "")
        case_link = (
            f'<a href="{_esc(cl_url)}"><em>{_esc(v.get("case_name", ""))}</em></a>'
            if cl_url else
            f'<em>{_esc(v.get("case_name", ""))}</em>'
        )
        supp = ""
        if v.get("supporting_language"):
            supp = (
                f' &mdash; <span style="color:#555;font-size:0.85em;">'
                f'"{_esc(v["supporting_language"])}"</span>'
            )
        badge_label = v.get("badge_label", "Supported")
        items.append(
            f'<div class="verified-item">'
            f'<span class="checkmark">&#10003;</span> '
            f'<strong>p. {_esc(v.get("page", ""))}</strong> &mdash; '
            f'{case_link}, {_esc(v.get("citation", ""))} &mdash; '
            f'{_esc(v.get("proposition", ""))} '
            f'{_badge(badge_label, "green")}'
            f'{supp}'
            f'</div>'
        )

    return f"""<h2>Verified Citations</h2>
<details>
  <summary>{len(verified)} citation-proposition pair{"s" if len(verified) != 1 else ""} verified &mdash; click to expand</summary>
  <div class="finding-body">
    {"".join(items)}
  </div>
</details>"""


def _build_methodology(
    retrieved: list[dict], unavailable: list[dict],
) -> str:
    """Build the methodology & limitations section."""
    retrieved_items = "\n".join(
        f'<li><em>{_esc(r.get("case_name", ""))}</em>, '
        f'{_esc(r.get("citation", ""))} (cluster {_esc(r.get("cluster_id", ""))})</li>'
        for r in retrieved
    )
    unavailable_items = "\n".join(
        f'<li><em>{_esc(u.get("case_name", ""))}</em>, '
        f'{_esc(u.get("citation", ""))} &mdash; {_esc(u.get("reason", ""))}</li>'
        for u in unavailable
    )

    unavailable_section = ""
    if unavailable_items:
        unavailable_section = f"""<p>The following opinions were <strong>not available on CourtListener</strong> and could not be verified against opinion text:</p>
  <ul>
    {unavailable_items}
  </ul>"""

    return f"""<div class="methodology">
  <h2>Methodology &amp; Limitations</h2>
  <ul>
    <li><strong>Quote verification</strong> is near-deterministic but limited by the quality of CourtListener's text. Minor discrepancies may reflect OCR artifacts in the source database rather than errors in the brief.</li>
    <li><strong>Propositional support</strong> assessment is an AI judgment. It reflects Claude's reading of the opinion text and should be verified by counsel. Reasonable lawyers may disagree about whether a case "supports" a given proposition.</li>
    <li>This report checks whether cited cases say what the brief claims they say. It does not assess the overall legal merit of the brief's arguments or whether the cited cases are the best authorities available.</li>
    <li>Cases marked "unable to verify" should be checked through other sources (Westlaw, Lexis, etc.).</li>
  </ul>
  <h3>Verification method disclosure</h3>
  <p>The following opinions were <strong>retrieved from CourtListener</strong> and verified against their full text:</p>
  <ul>
    {retrieved_items}
  </ul>
  {unavailable_section}
  <p>No opinions in this report were assessed from training knowledge. All assessments are based on retrieved opinion text.</p>
</div>"""


# ---------------------------------------------------------------------------
# CSS — matches proposition-verifier report style
# ---------------------------------------------------------------------------

_CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Source Sans 3', sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: #2d2d2d;
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
  background: #fafaf8;
}
h1, h2, h3 { font-family: 'Lora', serif; }
h1 { font-size: 1.6rem; margin-bottom: 0.3rem; color: #1a1a1a; }
h2 { font-size: 1.25rem; margin: 2rem 0 0.8rem; color: #333; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
h3 { font-size: 1.05rem; margin: 1rem 0 0.5rem; }

.meta { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
.meta span { display: inline-block; margin-right: 1.5rem; }

.dashboard { background: #fff; border: 1px solid #e0e0e0; border-radius: 6px; padding: 1.2rem 1.5rem; margin-bottom: 2rem; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.stat { text-align: center; }
.stat-num { font-size: 1.8rem; font-weight: 600; }
.stat-label { font-size: 0.8rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
.stat-red .stat-num { color: #c0392b; }
.stat-yellow .stat-num { color: #d4a017; }
.stat-green .stat-num { color: #27ae60; }
.stat-gray .stat-num { color: #888; }

.issue-list { list-style: none; padding: 0; }
.issue-list li {
  padding: 0.5rem 0.7rem;
  margin-bottom: 0.4rem;
  border-left: 4px solid #ccc;
  background: #fefefe;
  font-size: 0.9rem;
}
.issue-list li.sev-red { border-left-color: #c0392b; background: #fdf2f2; }
.issue-list li.sev-yellow { border-left-color: #d4a017; background: #fefcf0; }
.issue-list li.sev-gray { border-left-color: #999; background: #f5f5f5; }
.issue-list a { color: inherit; text-decoration: none; }
.issue-list a:hover { text-decoration: underline; }

.badge {
  display: inline-block;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  vertical-align: middle;
}
.badge-red { background: #f8d7da; color: #721c24; }
.badge-yellow { background: #fff3cd; color: #856404; }
.badge-orange { background: #ffe0b2; color: #8a4500; }
.badge-green { background: #d4edda; color: #155724; }
.badge-blue { background: #d1ecf1; color: #0c5460; }
.badge-gray { background: #e9ecef; color: #495057; }

.bq-brief {
  border-left: 4px solid #e67e22;
  background: #fef9f3;
  padding: 0.7rem 1rem;
  margin: 0.5rem 0;
  font-size: 0.9rem;
}
.bq-opinion {
  border-left: 4px solid #27ae60;
  background: #f0faf4;
  padding: 0.7rem 1rem;
  margin: 0.5rem 0;
  font-size: 0.9rem;
}
.bq-label { font-weight: 600; font-size: 0.8rem; color: #666; margin-bottom: 0.2rem; }

details { margin-bottom: 0.8rem; }
summary {
  cursor: pointer;
  padding: 0.6rem 0.8rem;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  font-size: 0.9rem;
  list-style: none;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: "\\25B6\\00a0"; font-size: 0.7rem; color: #888; }
details[open] > summary::before { content: "\\25BC\\00a0"; }
details[open] > summary { border-radius: 4px 4px 0 0; border-bottom: none; }
.finding-body {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-top: none;
  border-radius: 0 0 4px 4px;
  padding: 1rem;
}
.case-name { font-family: 'Lora', serif; font-style: italic; }
.explanation { margin-top: 0.7rem; font-size: 0.9rem; line-height: 1.5; }

.controls { margin-bottom: 0.5rem; font-size: 0.8rem; }
.controls button {
  background: none;
  border: none;
  color: #2980b9;
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0.2rem 0.4rem;
}
.controls button:hover { text-decoration: underline; }

.verified-item {
  padding: 0.3rem 0;
  font-size: 0.85rem;
  border-bottom: 1px solid #f0f0f0;
}
.checkmark { color: #27ae60; font-weight: bold; }

.methodology { font-size: 0.85rem; color: #555; margin-top: 2rem; }
.methodology h2 { font-size: 1.1rem; }
.methodology ul { padding-left: 1.2rem; }
.methodology li { margin-bottom: 0.5rem; }

@media print {
  details { open: true; }
  details[open] > summary { border-bottom: 1px solid #e0e0e0; }
  body { max-width: 100%; padding: 1rem; font-size: 12px; }
  .controls { display: none; }
  .dashboard { box-shadow: none; }
}"""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_report_template.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/report_template.py tests/test_report_template.py
git commit -m "feat: add report_template module with proposition-verifier HTML format"
```

---

## Task 2: Plumb syllabus data through the pipeline

The citation-lookup API returns full cluster objects that include `syllabus`, `nature_of_suit`, and other metadata. Currently `_process_citation_lookup_hit` only extracts 5 fields and throws the rest away. Add `matched_syllabus` to `VerificationResult`, populate it from the cluster, and write it to `verification_results.csv` so the metadata check can use it for topic-mismatch detection.

Note: `VerificationResult` already has `matched_description` (used for RECAP docket-entry descriptions). `matched_syllabus` is a separate field — it comes from the cluster (Step 1 citation lookup), not from docket entries (Step 3 RECAP).

**Files:**
- Modify: `src/citation_verifier/models.py`
- Modify: `src/citation_verifier/verifier.py`
- Modify: `src/citation_verifier/brief_pipeline.py`
- Modify: `tests/test_verifier.py`

- [ ] **Step 1: Write the test for syllabus preservation**

```python
# Add to tests/test_verifier.py

class TestSyllabusPreservation:
    """Verify that syllabus data from citation-lookup is preserved."""

    @patch("citation_verifier.verifier.CourtListenerClient")
    def test_citation_lookup_preserves_syllabus(self, mock_client_cls):
        """When citation-lookup returns a cluster with syllabus, it's on the result."""
        mock_client = mock_client_cls.return_value
        mock_client.citation_lookup.return_value = [
            {
                "citation": "202 F.3d 770",
                "clusters": [
                    {
                        "case_name": "Tompkins v. Cyr",
                        "id": 19782,
                        "absolute_url": "/opinion/19782/tompkins-v-cyr/",
                        "court": "ca5",
                        "date_filed": "2000-01-26",
                        "syllabus": "RICO; anti-abortion protesters; harassment; emotional distress",
                        "nature_of_suit": "440 Civil Rights: Other",
                    }
                ],
            }
        ]

        verifier = CitationVerifier()
        result = verifier.verify("Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)")

        assert result.matched_syllabus is not None
        assert "RICO" in result.matched_syllabus or "abortion" in result.matched_syllabus

    @patch("citation_verifier.verifier.CourtListenerClient")
    def test_citation_lookup_no_syllabus(self, mock_client_cls):
        """When cluster has no syllabus, field is None."""
        mock_client = mock_client_cls.return_value
        mock_client.citation_lookup.return_value = [
            {
                "citation": "337 F.3d 550",
                "clusters": [
                    {
                        "case_name": "King v. Illinois Central Railroad",
                        "id": 8437633,
                        "absolute_url": "/opinion/8437633/king/",
                        "court": "ca5",
                        "date_filed": "2003-07-16",
                    }
                ],
            }
        ]

        verifier = CitationVerifier()
        result = verifier.verify("King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)")

        assert result.matched_syllabus is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestSyllabusPreservation -v`
Expected: FAIL — `AttributeError: 'VerificationResult' object has no attribute 'matched_syllabus'`

- [ ] **Step 3: Add matched_syllabus to VerificationResult**

In `src/citation_verifier/models.py`, add after `matched_description`:

```python
    matched_syllabus: str | None = None
```

- [ ] **Step 4: Populate syllabus in _process_citation_lookup_hit**

In `src/citation_verifier/verifier.py`, in `_process_citation_lookup_hit`, build the syllabus string from available cluster fields. The citation-lookup API may return `syllabus`, `nature_of_suit`, or both. Combine them:

```python
        # Build syllabus from available metadata
        syllabus_parts = []
        if cluster.get("syllabus"):
            syllabus_parts.append(cluster["syllabus"])
        if cluster.get("nature_of_suit"):
            syllabus_parts.append(cluster["nature_of_suit"])
        syllabus = "; ".join(syllabus_parts) if syllabus_parts else None
```

Then add `matched_syllabus=syllabus` to both `VerificationResult(...)` constructor calls in that method (the VERIFIED return and the POSSIBLE_MATCH return).

- [ ] **Step 5: Add syllabus to verification_results.csv**

In `src/citation_verifier/brief_pipeline.py`, add `"syllabus"` to `_VR_FIELDS`:

```python
_VR_FIELDS = [
    "citation", "status", "confidence", "cl_url",
    "matched_name", "diagnostics_cat", "diagnostics_msg",
    "syllabus",
]
```

And in `_write_verification_csv`, add to the row dict:

```python
                "syllabus": result.matched_syllabus or "",
```

- [ ] **Step 6: Pass syllabus through merge_claims into claims.csv**

`syllabus` comes from `verification_results.csv`, not from `claims.csv`, so it's handled like the other VR fields (`cl_status`, `cl_url`, `matched_name`) — read from the VR lookup during merge, not a passthrough.

In `merge_claims`, add `"syllabus"` to `output_fields` (after `"opinion_file"`), and in the merge loop add it to the row dict:

```python
            row = {
                ...
                "opinion_file": opinion_file,
                "syllabus": vr.get("syllabus", ""),
            }
```

- [ ] **Step 7: Run tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_verifier.py::TestSyllabusPreservation tests/test_brief_pipeline.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/citation_verifier/models.py src/citation_verifier/verifier.py src/citation_verifier/brief_pipeline.py tests/test_verifier.py
git commit -m "feat: preserve syllabus from citation-lookup API for metadata triage"
```

---

## Task 3: Metadata sanity check function

Add `metadata_check()` to `brief_pipeline.py`. This reads `claims.csv` (which now includes the `syllabus` column from the merge) and for each claim checks:
- Case name mismatches (CL returned a different case)
- NOT_FOUND citations
- No opinion file available
- **Syllabus vs. proposition topic mismatch** — surfaces the syllabus alongside the proposition so the skill orchestrator (LLM) can flag obvious mismatches during triage

The function doesn't do NLP to detect topic mismatches — it collects the data. The LLM reads the output during the Phase 2a triage step and makes the judgment call.

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py`
- Modify: `tests/test_brief_pipeline.py`

- [ ] **Step 1: Write the test for metadata_check**

```python
# Add to tests/test_brief_pipeline.py

from citation_verifier.brief_pipeline import metadata_check, MetadataCheckResult


class TestMetadataCheck:
    def test_surfaces_syllabus_for_triage(self, tmp_path):
        """Syllabus data is included in output for LLM triage."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '3,"Prior settlement evidence is irrelevant.","Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)",'
            'VERIFIED,"Tompkins v. Cyr",https://cl/1/,opinions/Tompkins.txt,"",'
            '"RICO; anti-abortion protesters; harassment; emotional distress"\n'
        )
        result = metadata_check(tmp_path)
        # Names match so no name_mismatch flag, but syllabus is surfaced
        assert result.name_mismatches == 0
        assert len(result.syllabus_items) == 1
        assert "RICO" in result.syllabus_items[0]["syllabus"]
        assert "settlement" in result.syllabus_items[0]["proposition"]

    def test_flags_name_mismatch(self, tmp_path):
        """When CL returns a different case name, flag it."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '3,"Some proposition.","State v. Carter, 100 So.3d 1 (La. 2020)",'
            'VERIFIED,"Stull v. Combustion Engineering",https://cl/1/,opinions/Stull.txt,'
            '"name: Name mismatch",""\n'
        )
        result = metadata_check(tmp_path)
        assert result.name_mismatches == 1
        assert "State v. Carter" in result.flagged_claims[0]["cited_case"]

    def test_flags_not_found(self, tmp_path):
        """NOT_FOUND citations are flagged for mandatory assessment."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '7,"Plaintiff has no duty.","Menges v. Cliffs, 2000 WL 765082 (E.D. La. 2000)",'
            'NOT_FOUND,"",,,,""\n'
        )
        result = metadata_check(tmp_path)
        assert result.not_found == 1

    def test_no_flags_on_clean_data(self, tmp_path):
        """Clean data with no syllabus produces no flags."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,cl_status,retrieved_case,cl_url,opinion_file,diagnostics,syllabus\n"
            '6,"Bad faith required.","King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)",'
            'VERIFIED,"King v. Illinois Central Railroad",https://cl/1/,opinions/King.txt,"",""\n'
        )
        result = metadata_check(tmp_path)
        assert result.name_mismatches == 0
        assert result.not_found == 0
        assert len(result.flagged_claims) == 0
        assert len(result.syllabus_items) == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestMetadataCheck -v`
Expected: FAIL — `ImportError: cannot import name 'metadata_check'`

- [ ] **Step 3: Implement metadata_check**

Add to `src/citation_verifier/brief_pipeline.py`:

```python
@dataclass
class MetadataCheckResult:
    """Results from metadata sanity check."""
    total_claims: int = 0
    name_mismatches: int = 0
    not_found: int = 0
    no_opinion: int = 0
    flagged_claims: list[dict] = field(default_factory=list)
    syllabus_items: list[dict] = field(default_factory=list)


def metadata_check(workdir: Path) -> MetadataCheckResult:
    """Check verification metadata for obvious problems before assessment.

    Flags:
    - Case name mismatches (CL returned a different case)
    - NOT_FOUND citations (no opinion available)
    - Claims with no opinion file (can't assess)

    Also surfaces syllabus data alongside propositions. The skill orchestrator
    (LLM) reads these during triage and flags obvious topic mismatches —
    e.g., proposition about "settlement evidence" + syllabus about "RICO,
    anti-abortion protesters" = clear mismatch.

    These claims get mandatory Opus assessment. Clean claims can go through
    the cheaper triage path.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"
    result = MetadataCheckResult()

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    for claim in claims:
        result.total_claims += 1
        cl_status = claim.get("cl_status", "")
        diagnostics = claim.get("diagnostics", "")
        opinion_file = claim.get("opinion_file", "")
        syllabus = claim.get("syllabus", "")

        flags = []

        # Name mismatch: diagnostics contain "name" category mentions
        if "name mismatch" in diagnostics.lower() or "Name mismatch" in diagnostics:
            result.name_mismatches += 1
            flags.append("name_mismatch")

        # NOT_FOUND
        if cl_status == "NOT_FOUND":
            result.not_found += 1
            flags.append("not_found")

        # No opinion available
        if not opinion_file and cl_status not in ("NOT_FOUND", ""):
            result.no_opinion += 1
            flags.append("no_opinion")

        if flags:
            result.flagged_claims.append({
                "cited_case": claim.get("cited_case", ""),
                "page": claim.get("page", ""),
                "proposition": claim.get("proposition", ""),
                "syllabus": syllabus,
                "flags": flags,
            })

        # Surface syllabus for LLM triage (even if no other flags)
        if syllabus:
            result.syllabus_items.append({
                "cited_case": claim.get("cited_case", ""),
                "page": claim.get("page", ""),
                "proposition": claim.get("proposition", ""),
                "syllabus": syllabus,
            })

    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestMetadataCheck -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add metadata_check with syllabus surfacing for triage"
```

---

## Task 4: Add --report and --metadata-check CLI flags

Wire the new functions into the CLI so the skill can call them as pipeline steps.

**Files:**
- Modify: `src/citation_verifier/__main__.py`
- Modify: `src/citation_verifier/brief_pipeline.py` (add `generate_report` wrapper)

- [ ] **Step 1: Write the test for generate_report**

Add to `tests/test_brief_pipeline.py`:

```python
from citation_verifier.brief_pipeline import generate_report


class TestGenerateReport:
    def test_generates_html_file(self, tmp_path):
        """generate_report reads claims.csv and produces report.html."""
        # Set up minimal claims.csv with assessment data
        claims = tmp_path / "claims.csv"
        claims.write_text(
            "page,proposition,cited_case,retrieved_case,supporting_language,assessment,"
            "cl_url,cl_status,diagnostics,opinion_file,quoted_text,quote_check,quote_check_worst\n"
            '3,"Bad faith required.","King v. Ill. Cent. R.R., 337 F.3d 550 (5th Cir. 2003)",'
            '"King v. Illinois Central Railroad","An adverse inference requires bad conduct.","Green",'
            '"https://cl/opinion/8437633/","VERIFIED","",opinions/King.txt,"[]","[]","NO_QUOTES"\n'
        )
        (tmp_path / "opinions").mkdir()
        (tmp_path / "opinions" / "King.txt").write_text("opinion text")

        report_path = generate_report(
            tmp_path,
            title="Test Brief",
            case_name="Smith v. Jones",
            case_number="No. 1:24-CV-00001",
        )

        assert report_path.exists()
        html = report_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "Smith v. Jones" in html
        assert "King v. Ill" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestGenerateReport -v`
Expected: FAIL — `ImportError: cannot import name 'generate_report'`

- [ ] **Step 3: Implement generate_report in brief_pipeline.py**

Add to `src/citation_verifier/brief_pipeline.py`:

```python
from .report_template import generate_report_html


def generate_report(
    workdir: Path,
    title: str = "",
    case_name: str = "",
    case_number: str = "",
    filed_date: str = "",
    report_date: str = "",
) -> Path:
    """Generate an HTML report from claims.csv assessment data.

    Reads claims.csv (must have assessment column populated),
    builds the report data structure, and writes report.html.

    Returns the path to the generated report.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    findings = []
    verified = []
    unable = []
    retrieved_set = {}  # case_name -> {citation, cluster_id}
    unavailable_list = []
    finding_counter = 0

    for claim in claims:
        assessment = claim.get("assessment", "").strip()
        cl_status = claim.get("cl_status", "")
        page = claim.get("page", "")
        proposition = claim.get("proposition", "")
        cited_case = claim.get("cited_case", "")
        cl_url = claim.get("cl_url", "")
        retrieved_case = claim.get("retrieved_case", "")
        supporting_lang = claim.get("supporting_language", "")
        opinion_file = claim.get("opinion_file", "")

        # Parse case name and citation from cited_case
        parts = cited_case.split(",", 1)
        case_name_parsed = parts[0].strip() if parts else cited_case
        citation_parsed = parts[1].strip() if len(parts) > 1 else ""

        # Track retrieved opinions
        if opinion_file and retrieved_case:
            cluster_id = ""
            if cl_url:
                # Extract cluster ID from URL like /opinion/19782/...
                import re as _re
                m = _re.search(r"/opinion/(\d+)/", cl_url)
                if m:
                    cluster_id = m.group(1)
            retrieved_set[retrieved_case] = {
                "case_name": retrieved_case,
                "citation": citation_parsed,
                "cluster_id": cluster_id,
            }

        if assessment.lower() == "green":
            verified.append({
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "cl_url": cl_url,
                "proposition": proposition,
                "badge_label": "Supported",
                "supporting_language": supporting_lang,
            })
        elif cl_status == "NOT_FOUND" and not opinion_file:
            finding_counter += 1
            unable.append({
                "id": f"finding-uv-{finding_counter}",
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "brief_text": proposition,
                "explanation": (
                    supporting_lang if supporting_lang
                    else "Case not found on CourtListener. Cannot verify against opinion text."
                ),
            })
            unavailable_list.append({
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "reason": "Not in CourtListener database",
            })
        else:
            # Yellow or Red finding
            finding_counter += 1
            severity = "red" if assessment.lower() == "red" else "yellow"

            # Parse supporting_language for brief_text and opinion_text
            # The assessment agent writes these as structured text
            brief_text = proposition
            opinion_text = supporting_lang
            explanation = ""

            # If supporting_language has structured format, parse it
            if supporting_lang:
                # Try to split on common patterns
                if "Assessment:" in supporting_lang:
                    parts_sl = supporting_lang.split("Assessment:", 1)
                    opinion_text = parts_sl[0].strip()
                    explanation = parts_sl[1].strip()
                else:
                    explanation = supporting_lang

            badge_label = (
                "Not supported by cited case" if severity == "red"
                else "Overstated -- case partially supports"
            )

            findings.append({
                "id": f"finding-{finding_counter}",
                "page": page,
                "case_name": case_name_parsed,
                "citation": citation_parsed,
                "cl_url": cl_url,
                "severity": severity,
                "badge_label": badge_label,
                "brief_text": brief_text,
                "opinion_text": opinion_text,
                "explanation": explanation,
            })

    report_data = {
        "title": title,
        "case_name": case_name,
        "case_number": case_number,
        "filed_date": filed_date,
        "report_date": report_date,
        "findings": findings,
        "verified": verified,
        "unable_to_verify": unable,
        "retrieved_opinions": list(retrieved_set.values()),
        "unavailable_opinions": unavailable_list,
    }

    html = generate_report_html(report_data)
    report_path = workdir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
```

- [ ] **Step 4: Add CLI flags to __main__.py**

In `src/citation_verifier/__main__.py`, add to the `verify_brief_main` function's argument group:

```python
group.add_argument(
    "--metadata-check", action="store_true",
    help="Run metadata sanity check on merged claims",
)
group.add_argument(
    "--report", action="store_true",
    help="Generate HTML report from assessed claims",
)
```

And add the handler blocks before the wave1 handler:

```python
if args.metadata_check:
    from .brief_pipeline import metadata_check
    result = metadata_check(workdir)
    print(f"Metadata check: {result.total_claims} claims")
    print(f"  Name mismatches: {result.name_mismatches}")
    print(f"  NOT_FOUND: {result.not_found}")
    print(f"  No opinion: {result.no_opinion}")
    if result.flagged_claims:
        print(f"  Flagged for mandatory assessment ({len(result.flagged_claims)}):")
        for fc in result.flagged_claims:
            print(f"    - p.{fc['page']}: {fc['cited_case']} [{', '.join(fc['flags'])}]")
    if result.syllabus_items:
        print(f"  Syllabus check ({len(result.syllabus_items)}):")
        for si in result.syllabus_items:
            print(f'    - p.{si["page"]}: "{si["proposition"][:80]}" / Syllabus: "{si["syllabus"][:80]}"')
    return 0

if args.report:
    from .brief_pipeline import generate_report
    # Read metadata from a brief_metadata.json if it exists, else use defaults
    import json as json_mod
    meta_path = workdir / "brief_metadata.json"
    meta = {}
    if meta_path.exists():
        meta = json_mod.loads(meta_path.read_text(encoding="utf-8"))
    report_path = generate_report(
        workdir,
        title=meta.get("title", ""),
        case_name=meta.get("case_name", ""),
        case_number=meta.get("case_number", ""),
        filed_date=meta.get("filed_date", ""),
        report_date=meta.get("report_date", ""),
    )
    print(f"Report generated: {report_path}")
    return 0
```

- [ ] **Step 5: Run tests to verify everything passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py tests/test_report_template.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/citation_verifier/__main__.py src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add --report and --metadata-check CLI flags to verify-brief"
```

---

## Task 5: Rewrite the verify-brief SKILL.md

This is the core of the merge. Replace the current skill prompt with the unified pipeline that uses verify-brief's mechanical engine and proposition-verifier's report format, assessment calibration, and quote presentation.

**Files:**
- Rewrite: `.claude/skills/verify-brief/SKILL.md`

- [ ] **Step 1: Read both existing skills for reference**

Read `.claude/skills/verify-brief/SKILL.md` and `.claude/skills/proposition-verifier/SKILL.md` to confirm the current state matches what's expected. (Already done during planning — but the implementer should verify.)

- [ ] **Step 2: Write the new SKILL.md**

Replace `.claude/skills/verify-brief/SKILL.md` with the content below. Key changes from the old skill:

1. **New Phase 1d** — metadata sanity check before summaries
2. **Triage gate** — metadata flags + quote check results determine which claims get expensive Opus assessment vs. cheap Haiku triage
3. **Stricter assessment prompts** — proposition-verifier calibration (Collins/Abel = Red, not Yellow)
4. **Assessment output format** — structured to feed directly into the report template (brief_text, opinion_text, explanation fields)
5. **Phase 4 uses --report CLI** — deterministic report generation from claims.csv
6. **Proposition-verifier report format** — collapsible details, paired blockquotes, methodology section
7. **Badge mapping** from proposition-verifier (semantic labels, not just colors)
8. **Gray status for CL coverage gaps** instead of Red

```markdown
---
name: verify-brief
description: Use when user wants to verify citations in a legal brief, check if cited cases support the propositions they're cited for, or analyze a brief for hallucinated or misrepresented case law. Triggers on "verify brief", "check citations in brief", "analyze brief citations".
argument-hint: "[path to brief PDF or Word doc]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /verify-brief — Legal Brief Citation Verifier

Multi-phase pipeline: extract citations from a brief, verify against CourtListener, download opinion texts, check quotes, triage, assess whether each citation supports its proposition, generate an interactive report.

**Requirements:** `citation_verifier` package installed, `COURTLISTENER_API_TOKEN` in `.env`.

## Startup Checks

1. `venv/Scripts/python.exe -m citation_verifier --help` — if fails, tell user to install
2. Check `.env` has `COURTLISTENER_API_TOKEN` — if missing, guide to https://www.courtlistener.com/ > Profile > API Keys

## Working Directory

Create `briefs/<brief-name>/` in the project root. Ask user for a short name if not obvious.

```
briefs/<brief-name>/
├── brief.pdf (or .txt)       # Source brief
├── brief_metadata.json       # Case name, number, filed date (for report header)
├── citations_to_verify.txt   # Phase 1a output
├── claims.csv                # Master table (evolves through phases)
├── verification_results.csv  # Pipeline output
├── opinions/                 # Downloaded opinion texts (.html/.txt/.pdf)
└── report.html               # Phase 4 output
```

After creating the working directory, write `brief_metadata.json`:
```json
{
  "title": "Brief title as it appears on the document",
  "case_name": "Plaintiff v. Defendant",
  "case_number": "No. X:XX-CV-XXXXX (Court)",
  "filed_date": "Month Day, Year"
}
```

## Phases

### Phase 1a: Extract Citation List

Read the brief (PDF via Read tool, or text). Extract every **case citation** — one per line in `citations_to_verify.txt`.

Rules:
- Case citations only (with reporter volume and page)
- Exclude: statutes, regulations, constitutional provisions, treatises, secondary sources, Federalist Papers
- Deduplicate — same case with different pinpoints = one line (use base citation without pinpoint)
- Format: `Case Name, Vol Reporter Page (Year)` — exactly as the brief cites it, minus pinpoint
- **Citation inconsistencies**: If the Table of Authorities and the body text cite different reporter volumes or page numbers for the same case, include BOTH variants in `citations_to_verify.txt` (on separate lines) so the verifier can look up both. Note the discrepancy for the user.

Report: "Extracted X unique case citations."

### Phase 1b: Wave 1 — Batch Verify + Download

Run the pipeline CLI:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --wave1
```

This does a single batch API call and downloads opinion texts for all hits. Takes ~1-2 minutes.

### Phase 1c: Propositions + Wave 2 (Concurrent)

Launch **two concurrent agents**:

**Agent 1 (Opus) — Extract propositions:**
- Read the brief
- Reference the citation list from `citations_to_verify.txt`
- Extract every proposition-case pair into `claims.csv` with columns: `page,proposition,cited_case,quoted_text`
- CRITICAL: The `cited_case` column MUST start with the exact full citation text from `citations_to_verify.txt` (including case name, reporter, and year). Append pinpoint pages after the start page (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Do NOT abbreviate, omit the reporter, or use short-form case names.
- `quoted_text`: JSON array of any text that appears inside quotation marks in the brief's sentence for this claim. Extract the exact quoted words from the brief. If the claim has no quoted text, use `[]`. Example: `["no desire to deter", "but-for causation"]`
- Same case cited for different propositions = separate rows
- Same proposition supported by multiple cases = separate rows
- Exclude non-case sources

**Agent 2 (background bash) — Wave 2 fallback (only if wave1 had misses):**
Check wave1 output first. If wave1 reported "Misses for wave 2: 0", skip wave2 entirely. Otherwise:
```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --wave2
```

**After both finish — Merge:**
```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --merge
```

This joins `claims.csv` with `verification_results.csv`, linking each claim to its verification status, opinion file, and syllabus metadata (from the citation-lookup API). The syllabus column is used in Phase 1d for topic-mismatch triage.

If merge reports unmatched claims, fix the `cited_case` values in `claims.csv` to match exactly what's in `citations_to_verify.txt` (with pinpoint pages appended), then re-run `--merge`.

### Phase 1d: Quote Check + Metadata Check

Run sequentially:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --check-quotes
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --metadata-check
```

The quote check verifies every quoted string against the opinion file. The metadata check flags name mismatches, NOT_FOUND citations, and surfaces syllabus data for each claim.

Report the results of both, including the syllabus items. For any claim that has syllabus data, print:
```
  Syllabus check:
    - p.3: "Prior settlement evidence is irrelevant" / Syllabus: "RICO; anti-abortion protesters; harassment"
    - p.6: "Bad faith required for spoliation" / Syllabus: "spoliation; bad faith; adverse inference"
```

Review these for obvious topic mismatches. A proposition about "settlement evidence" paired with a syllabus about "RICO, anti-abortion protesters" is an immediate red flag — add it to the mandatory assessment list.

These results determine the triage for Phase 2.

### Phase 2: Triage + Assess

This phase has three steps: triage, grep/summarize, and Opus assessment. The triage happens first so we only do expensive work on claims that need it.

#### Step 2a: Triage

Split claims into two tracks based on Phase 1d results (quote check + metadata check + syllabus review). **Every claim gets checked against the opinion text** — the triage determines *how deep*, not *whether*.

**Full Opus assessment** (any of these flags):
- `quote_check_worst` is `FABRICATED` or `CLOSE`
- Metadata check flagged `name_mismatch`
- Syllabus vs. proposition topic mismatch (LLM judgment from the syllabus items above)
- Claim has quoted text (`quoted_text` is not `[]`)
- Case is the lead authority in a section of the brief (first citation in a paragraph that introduces an argument)

**Fast track** (all of these must be true):
- `quote_check_worst` is `NO_QUOTES` or `VERBATIM`
- No metadata flags or syllabus concerns
- Not a lead authority

Fast-track claims still get verified — they go through the grep step (Step 2b) and get a Haiku confirmation. The difference is they don't get a full Opus assessment unless the grep or Haiku step raises a concern. See Step 2b for the fast-track flow.

Report: "Triage: X claims for full Opus assessment, Y claims for fast-track verification."

#### Step 2b: Grep + opinion research (all claims)

For each opinion file, grep for each claim's key terms. This serves two purposes: gathering excerpts for Opus assessment (full-assessment claims) and verifying topical relevance (fast-track claims).

**For all claims citing an opinion, run grep searches:**

1. **Grep for the brief's exact quoted language** (if any). Use a distinctive 4-6 word substring from the quote, not the whole thing (handles line breaks and minor formatting).
2. **Grep for 2-3 key legal terms from the proposition.** Example: if the proposition is about "prior settlement evidence is irrelevant," grep for `settlement`, `prior verdict`, `collateral source`.
3. **Grep for the brief's parenthetical language** if the citation has one.

For each grep hit, use the Read tool to read ~100 lines around the hit (50 before, 50 after) to capture the full paragraph and surrounding context.

**When greps find relevant passages:**

- For **full-assessment claims**: save the excerpts to `opinions/{case_name}_excerpts.txt` with grep terms noted. These go to the Opus assessment agent in Step 2c.
- For **fast-track claims**: the excerpts go to a Haiku confirmation agent (see below).

**When greps find nothing (all searches return 0 hits):**

This strongly suggests the opinion doesn't discuss the proposition's topic at all — but the opinion might use different terminology. This applies to both tracks:

- For **full-assessment claims on large opinions (>= 20K chars)**: launch a Haiku full-read as a safety net (see prompt below).
- For **fast-track claims**: the grep miss is itself a red flag. Escalate the claim to full Opus assessment — if the opinion doesn't even contain the proposition's key terms, something may be wrong.
- For **any claim on opinions < 20K chars**: skip grep entirely. Opus reads the full opinion directly in Step 2c (fast-track claims get Haiku confirmation from the full text instead).

**Haiku full-read** (only for large opinions with grep misses):

Launch an **Explore** agent (runs on Haiku; include "very thorough" in the prompt):

> Very thorough search needed. Read the ENTIRE opinion file at `{opinion_path}` using the Read tool. This is a legal opinion.
>
> I searched for the following terms and found NOTHING:
> {list of grep terms that returned 0 hits}
>
> Propositions to check (these are claims a brief makes about this case):
> {numbered list of propositions from ALL claims citing this opinion — both full-assessment and escalated fast-track}
>
> **Your job:** Determine whether this opinion discusses these topics AT ALL, even using different terminology. The grep misses suggest it might not, but confirm by reading.
>
> **Output format — follow exactly:**
>
> CASE SUMMARY:
> [1-2 sentences: what this case is actually about — its core dispute and holding]
>
> KEY HOLDINGS:
> [Bullet list of actual holdings]
>
> PROPOSITION ANALYSIS:
> For each proposition, write:
> - Proposition N: FOUND or NOT FOUND
>   - If FOUND: quote the relevant passage verbatim (with page/section reference if visible). Explain why the grep terms missed it (different terminology, etc.).
>   - If NOT FOUND: confirm the opinion does not discuss this topic. State what the opinion actually covers instead. Be specific.
>
> Be precise. Only summarize — do NOT assess whether propositions are supported.

Save the agent's output to `opinions/{case_name}_summary.txt`.

**Haiku fast-track confirmation** (for fast-track claims with grep hits):

For fast-track claims where grep found relevant passages, launch an **Explore** agent (Haiku) to confirm the proposition is supported:

> Read the following excerpts from `{opinion_path}`. These are passages found by searching for terms related to the proposition.
>
> Excerpts:
> {the grep excerpts — ~100 lines of context per hit}
>
> Proposition the brief attributes to this case:
> "{proposition text}"
>
> **Question:** Based on these excerpts, does the opinion support this proposition? Answer one of:
> - SUPPORTED: [one sentence explaining how, with a key quote from the excerpts]
> - UNCLEAR: [the excerpts touch on the topic but it's not clear whether they support the specific proposition — needs full Opus assessment]
> - NOT SUPPORTED: [the excerpts discuss a different aspect of the topic, or contradict the proposition]
>
> Be precise. If in doubt, say UNCLEAR.

- If Haiku says SUPPORTED → mark Green with the supporting quote
- If Haiku says UNCLEAR or NOT SUPPORTED → escalate to full Opus assessment in Step 2c

**Batching:** Run all Haiku agents (full-reads and fast-track confirmations) concurrently in background.

Report: "Opinion research: X claims grep-searched, Y fast-track confirmed by Haiku, Z escalated to Opus, W sent to Haiku full-read."

#### Step 2c: Opus assessment subagents

Group all full-assessment claims (original + escalated from fast-track) by opinion file. For each opinion, launch an Opus subagent (general-purpose agent).

**Subagent input — opinion source (in priority order):**
1. If opinion < 20K chars: read the **full opinion** directly
2. If `opinions/{case}_excerpts.txt` exists (grep hits): read the **excerpts**
3. If `opinions/{case}_summary.txt` exists (Haiku full-read): read the **summary**

Also provide:
- List of claims: `[{row_index, page, proposition, cited_case, quoted_text, quote_check_worst, quote_check}]`

**Subagent instructions:**

> Read the opinion text (or summary). For each claim, assess two things independently:
>
> **1. Quote accuracy** (only for claims with quoted text):
> Does the quoted language actually appear in the opinion? Classify:
> - **Verbatim** — exact match (after normalizing punctuation/whitespace)
> - **Cosmetic near match** — same words, minor formatting differences
> - **Reworded** — recognizably derived from a passage, but with word substitutions or reordering. Show BOTH the brief's version and the opinion's actual text.
> - **Paraphrase in quotes** — the brief uses quotation marks around language that is the author's summary, not the court's words. Identify the closest actual passage.
> - **Not found** — the quoted text does not appear and no similar passage exists
>
> **2. Propositional support:**
> Does the case support the proposition it's cited for? Classify:
> - **Supported** — the opinion directly and accurately supports the proposition
> - **Partially supported** — the opinion touches on the topic but the brief overstates, oversimplifies, or extends the holding. Explain the gap.
> - **Not supported** — the opinion does NOT support the proposition. This includes:
>   - The case addresses a completely different topic
>   - The case holds the OPPOSITE of what the brief claims
>   - The brief attributes a specific principle to the case that doesn't appear in it
>   - The case's dicta or background discussion touches the topic but the holding does not
>
> Be strict on the distinction between "partially supported" and "not supported":
> - If the case is topically related and its holding can reasonably be extended to the proposition, that's "partially supported"
> - If the case's holding is about a different legal issue entirely and would require a leap of logic to reach the proposition, that's "not supported" — even if the case happens to use some of the same legal terminology
>
> **Assessment calibration examples:**
> - Brief says "courts exclude prior settlement evidence" and cites a case about anti-abortion protesters → **Not supported** (completely different topic)
> - Brief says "bias evidence must demonstrate actual bias" and cites a case that holds bias evidence is broadly admissible → **Not supported** (inverts the holding)
> - Brief says a case "excludes irrelevant evidence" but the case actually favored admission → **Not supported** (opposite holding)
> - Brief overstates "must be excluded" when the case says "may be excluded at the court's discretion" → **Partially supported** (same topic, overstated standard)
> - Brief cites a general Rule 403 case for a spoliation-specific proposition → **Partially supported** if the legal principle genuinely applies, **Not supported** if the brief implies the case specifically addressed spoliation when it didn't
>
> Do NOT use any external tools — only use Read to access opinion files provided in the workdir.
>
> **Output format — JSON array:**
> ```json
> [
>   {
>     "row_index": 7,
>     "assessment": "Red",
>     "badge_label": "Not supported by cited case",
>     "brief_text": "The brief's claim or quoted text, verbatim from the brief",
>     "opinion_text": "What the opinion actually says — the relevant passage or a specific explanation of what the case is about. Use the opinion's own words where possible. This will appear in a green blockquote in the report.",
>     "explanation": "A 1-3 sentence assessment explaining why this is Red/Yellow. Written for a lawyer audience — specific, not vague."
>   }
> ]
> ```
>
> **Assessment → color mapping:**
> - Green: Supported + (Verbatim or No quotes) → `"assessment": "Green"`
> - Yellow: Partially supported, OR Supported but reworded/paraphrase-in-quotes → `"assessment": "Yellow"`
>   - Use badge_label: "Overstated -- case partially supports" or "Reworded -- not a verbatim quote" or "Paraphrase presented as direct quote"
> - Red: Not supported, OR quote Not found → `"assessment": "Red"`
>   - Use badge_label: "Not supported by cited case" or "Quote not found in opinion" or "Citation resolves to different case"

**Batching:** Max 4-5 opinions per subagent. If more than 5 opinions need assessment, split into multiple subagents and run in parallel.

After all subagents return, update `claims.csv` with `assessment`, `supporting_language` (the subagent's full JSON response for that claim, which `generate_report` will parse), `badge_label`, `brief_text`, and `opinion_text` columns.

**Special cases (no subagent needed):**
- NOT_FOUND with no opinion text → assessment: "Red", badge_label: "Unable to verify", route to `unable_to_verify` in the report (Gray, not Red)
- VERIFIED but no opinion file → assessment: "Yellow", badge_label: "Case verified but opinion text not available for review"

### Phase 3: Generate Report

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --report
```

This reads `claims.csv` and `brief_metadata.json` and generates `report.html` in the proposition-verifier format:
- Dashboard with severity counts and clickable issue list
- Collapsible findings with paired blockquotes ("What the brief claims" / "What the opinion actually says")
- Collapsed verified section with green checkmarks
- Methodology section listing which opinions were retrieved vs. unavailable

Open the report in the user's browser and give a chat summary:
- Stats: X Green, Y Yellow, Z Red, W Unable to verify
- List all Red with proposition + brief rationale
- List all Yellow with brief notes
- Green count only

## Resuming

If `claims.csv` already exists, detect state and resume:

| State | Resume at |
|-------|-----------|
| No `claims.csv` | Phase 1a |
| Has `cited_case` but no `cl_status` | Phase 1b (wave1) |
| Has `cl_status` but no `quote_check_worst` | Phase 1d (quote check + metadata check) |
| Has `quote_check_worst` but no `assessment` | Phase 2 (triage + assess) |
| Has `assessment` | Phase 3 (report) |

**Phase 2 sub-steps** (when resuming at Phase 2):
1. Triage: classify claims as full-assessment or fast-track based on quote_check + metadata + syllabus
2. Grep all claims: search opinion files for key terms, gather excerpts
3. Haiku confirmation for fast-track claims with grep hits; Haiku full-read when greps miss on large opinions; escalate to Opus if Haiku says UNCLEAR
4. Opus assessment: assess all full-assessment claims (original + escalated) using excerpts/summaries/full text

Announce: "Found existing work. Resuming at Phase N."
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/verify-brief/SKILL.md
git commit -m "feat: rewrite verify-brief skill with unified pipeline and proposition-verifier report format"
```

---

## Task 6: Delete the proposition-verifier skill

Now that verify-brief incorporates proposition-verifier's strengths, remove the standalone skill to avoid confusion.

**Files:**
- Delete: `.claude/skills/proposition-verifier/SKILL.md`

- [ ] **Step 1: Verify the new skill has all proposition-verifier capabilities**

Check that the rewritten SKILL.md covers:
- Side-by-side blockquote report format ✓ (via report_template.py)
- Stricter assessment calibration ✓ (calibration examples in prompt)
- Quote accuracy as separate workflow ✓ (Phase 1d + assessment prompt)
- Badge mapping with semantic labels ✓ (badge_label in assessment output)
- Methodology section ✓ (via report_template.py)
- Gray status for CL coverage gaps ✓ (unable_to_verify section)

- [ ] **Step 2: Delete the skill**

```bash
rm -rf .claude/skills/proposition-verifier/
```

- [ ] **Step 3: Commit**

```bash
git add -A .claude/skills/proposition-verifier/
git commit -m "chore: remove proposition-verifier skill (merged into verify-brief)"
```

---

## Task 7: Update CLAUDE.md

Update the project documentation to reflect the merged skill and new CLI commands.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Files table**

Add `report_template.py` to the core library table:

```
| `report_template.py` | HTML report template (proposition-verifier style) |
```

- [ ] **Step 2: Update the Claude Code Skills section**

Replace the two skill entries with one:

```markdown
- **`/verify-brief`** — Multi-phase legal brief citation verifier. Uses `brief_pipeline.py` for mechanical work (batch verify, download, merge, quote check, metadata check, report generation). LLM orchestrates extraction (Phase 1a/1c) and assessment (Phase 2 via triage + Opus subagents). Generates proposition-verifier-style interactive HTML report with collapsible findings, paired blockquotes, and methodology disclosure. Output: `claims.csv` + `report.html` in `briefs/<name>/`. CLI: `python -m citation_verifier verify-brief <workdir> [--wave1|--wave2|--merge|--check-quotes|--metadata-check|--report|--full]`.
```

Remove the separate `/proposition-verifier` bullet if it exists.

- [ ] **Step 3: Update the brief_pipeline.py description in the Files table**

```
| `brief_pipeline.py` | Brief verification pipeline: `wave1_verify_and_download()`, `wave2_fallback_and_download()`, `merge_claims()`, `check_quotes()`, `metadata_check()`, `generate_report()`. CLI: `python -m citation_verifier verify-brief <workdir> [--wave1\|--wave2\|--merge\|--check-quotes\|--metadata-check\|--report\|--full]` |
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for unified verify-brief skill"
```

---

## Task 8: End-to-end smoke test

Run the unified skill on a brief we've already verified to confirm it produces the expected report format.

**Files:** None (manual test)

- [ ] **Step 1: Run unit tests**

```bash
venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py tests/test_report_template.py -v
```
Expected: All tests PASS

- [ ] **Step 2: Run report generation on existing Brooks data**

The Brooks v. Lowe's workdir already has assessed `claims.csv`. Test the report generator:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/gov.uscourts.lawd.207038.49.1 --report
```

Expected: `briefs/gov.uscourts.lawd.207038.49.1/report.html` is overwritten with the new proposition-verifier-style format.

- [ ] **Step 3: Open and visually inspect the report**

Check:
- Dashboard shows correct counts
- Red findings have collapsible details with paired blockquotes
- Verified section is collapsed
- Methodology section lists retrieved opinions
- Expand All / Collapse All buttons work
- CL links are clickable

- [ ] **Step 4: Compare against the proposition-verifier report**

Open `briefs-2/gov.uscourts.lawd.207038.49.1_proposition_report.html` side-by-side. The new report should have the same visual structure, typography, and interaction patterns.

- [ ] **Step 5: Commit if report.html needs manual adjustment**

If the `generate_report` function needs tweaks based on visual inspection (parsing issues, missing fields, layout problems), fix them and re-run. Then:

```bash
git add -A
git commit -m "fix: adjust report template based on visual inspection"
```

---

## Summary of changes

| What | Before | After |
|------|--------|-------|
| Skills | Two separate (`/verify-brief` + `/proposition-verifier`) | One unified `/verify-brief` |
| Report format | Flat tables with quote tags | Collapsible details, paired blockquotes, methodology |
| Assessment calibration | Lenient (Collins/Abel = Yellow) | Strict with calibration examples (Collins/Abel = Red) |
| Quote presentation | Similarity scores + CLOSE/FABRICATED tags | Exact text comparisons side-by-side |
| CL coverage gaps | Red (NOT_FOUND) | Gray (Unable to verify) |
| Triage | All claims get Opus | Every claim gets checked: fast-track (grep + Haiku confirm) or full Opus. Haiku full-read only when greps miss on large opinions. Fast-track escalates to Opus if grep misses or Haiku says UNCLEAR. |
| CLI report generation | Manual in skill prompt | `--report` flag, deterministic from claims.csv |
| Metadata sanity check | None | `--metadata-check` flag with syllabus surfacing for topic-mismatch triage |
| Syllabus data | Thrown away by pipeline | Preserved from citation-lookup API, written to CSV, surfaced in metadata check |
