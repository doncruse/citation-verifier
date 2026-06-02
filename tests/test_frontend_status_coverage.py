"""Phase 5 Task 3 -- static coverage check for frontend status switches.

Each of web/static/get.html, index.html, qc.html has JS switch statements
that map Status enum values to badge classes and label text. When a new
Status value is added in models.py, these switches must add a `case`
block; otherwise the new status renders as the default branch ('Searching'
or empty), which is what Phase 4 Addendum A3 caught manually.

This test loads each HTML, extracts the JS switch statements via regex,
and asserts every Status enum member appears as a case in each one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from citation_verifier.models import Status


_PROJECT_ROOT = Path(__file__).parent.parent
_STATIC_DIR = _PROJECT_ROOT / "web" / "static"


# Pages and the switch-function names each must cover. Each page has its
# own naming -- get.html only has statusBadges; index.html has all three;
# qc.html has statusLabel and badgeClass.
_PAGES_AND_SWITCHES = [
    ("get.html", ["statusBadges"]),
    ("index.html", ["statusLabel", "badgeClass", "statusBadges"]),
    ("qc.html", ["statusLabel", "badgeClass"]),
]


def _extract_switch_body(html: str, fn_name: str) -> str:
    """Return the body of the function ``fn_name``'s switch statement.

    Locates ``function fn_name(...) {`` in the source, walks the function
    body with a brace counter to find its matching ``}``, then locates the
    ``switch (...) {`` inside and walks again to find that block's body.
    Brace-balanced (not regex) so nested block-scoped ``case 'X': { ... }``
    bodies don't trip it up.
    """
    start_pat = re.compile(
        r"function\s+" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\{"
    )
    m = start_pat.search(html)
    if not m:
        raise AssertionError(
            f"Could not locate function {fn_name!r} in HTML. "
            f"The matcher may need updating if the source structure changed."
        )
    body_start = m.end()  # right after the opening brace
    fn_body = _extract_brace_body(html, body_start)

    switch_match = re.search(r"switch\s*\([^)]+\)\s*\{", fn_body)
    if not switch_match:
        raise AssertionError(
            f"Function {fn_name!r} has no switch statement in its body."
        )
    switch_body_start = switch_match.end()
    return _extract_brace_body(fn_body, switch_body_start)


def _extract_brace_body(source: str, start: int) -> str:
    """Given ``source`` and an offset ``start`` that is just past an opening
    ``{``, return everything up to (not including) the matching ``}``.
    Tracks string literals so braces inside ``'...'`` / ``"..."`` /
    template literals aren't counted."""
    depth = 1
    i = start
    n = len(source)
    while i < n and depth > 0:
        ch = source[i]
        if ch in ("'", '"', "`"):
            # Skip a string literal (no escape handling beyond \\)
            quote = ch
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    i += 2
                    continue
                i += 1
            i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            # Line comment
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            # Block comment
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
        i += 1
    raise AssertionError(
        f"Unbalanced braces starting at offset {start}; reached EOF."
    )


@pytest.mark.parametrize("filename,switch_fns", _PAGES_AND_SWITCHES)
def test_every_status_has_case_in_every_switch(filename, switch_fns):
    html_path = _STATIC_DIR / filename
    assert html_path.exists(), f"Static file not found: {html_path}"
    html = html_path.read_text(encoding="utf-8")

    for fn_name in switch_fns:
        body = _extract_switch_body(html, fn_name)
        for status in Status:
            pattern = re.compile(
                r"case\s+['\"]" + re.escape(status.value) + r"['\"]\s*:",
            )
            assert pattern.search(body), (
                f"Status {status.value!r} has no 'case' block in "
                f"{filename}::{fn_name}(). When you added this status to "
                f"src/citation_verifier/models.py::Status, you also need to "
                f"add a 'case {status.value!r}:' to {filename}'s {fn_name}() "
                f"switch -- the default branch renders as a stale 'Searching' "
                f"badge (Phase 4 Addendum A3)."
            )


def test_qc_filter_chips_cover_actionable_v03_statuses():
    """The QC page's filter chips drive which rows the reviewer sees. After
    the v0.3 schema change, WRONG_CASE and VERIFICATION_INCOMPLETE became the
    most important triage categories. Both must have chips in qc.html.
    The other v0.3-new statuses (PARTIAL/VIA_RECAP/DOCKET_ONLY) should also
    have chips so the reviewer can filter to them deliberately.
    """
    html_path = _STATIC_DIR / "qc.html"
    html = html_path.read_text(encoding="utf-8")
    chip_pat = re.compile(r"data-filter\s*=\s*['\"]([A-Z_]+)['\"]")
    chips = set(chip_pat.findall(html))
    chips.discard("ALL")  # chip-set master toggle, not a status
    expected_min_chips = {s.value for s in Status} | {"SKIPPED"}
    missing = expected_min_chips - chips
    assert not missing, (
        f"QC page filter chips missing the following statuses: {sorted(missing)}. "
        f"Add a <span class='chip' data-filter='STATUS'> for each missing status "
        f"in qc.html. Currently has: {sorted(chips)}."
    )


_GET_HTML_MISS_BUCKET = (
    "NOT_FOUND",
    "ERROR",
    "VERIFICATION_INCOMPLETE",
    "INSUFFICIENT_DATA",
)


def test_get_html_miss_bucket_covers_undownloadable_statuses():
    """The "still missing" / deep-search-retry bucket in get.html's runSSE
    handler must cover every status that doesn't produce a matched_url.

    Otherwise the page reports them as "found" (because the bucket check
    is the only thing that takes a status *out* of the found tally) while
    showing no download checkbox -- the displayed found-count exceeds the
    available-to-download count, which is exactly what tripped the user
    after INSUFFICIENT_DATA shipped (commit f7c9203) without a matching
    frontend update. VERIFICATION_INCOMPLETE was the original case from
    audit row C4; INSUFFICIENT_DATA joined the bucket later.
    """
    html = (_STATIC_DIR / "get.html").read_text(encoding="utf-8")
    for needle in _GET_HTML_MISS_BUCKET:
        assert needle in html, (
            f"get.html must reference {needle} for the not-found / "
            f"deep-search retry trigger to work."
        )
    lines = html.split("\n")
    for i, line in enumerate(lines):
        if "NOT_FOUND" in line and "ERROR" in line:
            window = "\n".join(lines[max(0, i-2):i+3])
            if all(s in window for s in _GET_HTML_MISS_BUCKET):
                return  # found the retry-condition site
    pytest.fail(
        "get.html has each status name somewhere, but not all of "
        f"{_GET_HTML_MISS_BUCKET} appear in the same retry-condition "
        "expression. The frontend's not-found bucket must cover every "
        "status that produces no matched_url, otherwise the found-count "
        "drifts above the downloadable-count."
    )
