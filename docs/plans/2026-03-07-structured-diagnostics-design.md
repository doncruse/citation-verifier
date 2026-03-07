# Structured Diagnostics Refactor — Design Doc

**Date:** 2026-03-07
**Status:** Implemented (7bcee6b, 2026-03-07)

## Problem

`VerificationResult.diagnostics` is `List[str]`. The frontend uses regex on prose strings to determine which badge to show (`/^Name (mismatch|differs)/i` → "Check Name"). This is brittle — whenever diagnostic wording changes, the regex breaks silently (e.g. "Date close" wasn't matched by the "Date mismatch" pattern).

## Design

### Data model

New dataclass in `models.py`:

```python
@dataclass
class Diagnostic:
    category: str   # see categories below
    message: str    # human-readable detail (unchanged from current strings)
```

`VerificationResult.diagnostics` changes from `List[str]` to `List[Diagnostic]`.

### Categories

| Category | Covers |
|----------|--------|
| `name` | Name mismatch, name differs, name not returned by API |
| `court` | Court mismatch, court not verified |
| `date` | Date mismatch, date close, year not verified |
| `docket` | Docket number mismatch |
| `cite` | Citation/reporter mismatch, WL number mismatch, WL/reporter not confirmed |
| `recap` | Found in RECAP, docket-only match |
| `info` | Low confidence warning, quick-only, match quality ("we identified a likely match") |

### What changes

| File | Change |
|------|--------|
| `models.py` | Add `Diagnostic` dataclass; change `VerificationResult.diagnostics` type |
| `verifier.py` | Every `mismatches.append("...")` becomes `mismatches.append(Diagnostic(category, "..."))` |
| `verifier.py` | `_finalize_diagnostics()` works with `Diagnostic` objects |
| `web/app.py` | `_result_to_dict()` serializes diagnostics as `[{"category": ..., "message": ...}]` |
| `web/app.py` | Inline error dicts use `{"category": "info", "message": "..."}` format |
| `web/static/get.html` | Badge logic uses `d.category === "name"` instead of regex |
| `web/static/index.html` | Same badge logic change |
| `web/static/qc.html` | Diagnostic display uses `d.message` instead of raw string |
| `__main__.py` | CLI joins `.message` fields for display |
| `tests/test_verifier.py` | Assertions change to check `.category` and/or `.message` |
| `tests/test_async_verifier.py` | Same assertion changes |
| `.claude/skills/verify-brief/SKILL.md` | If it reads diagnostics, update to use `.message` |

### What doesn't change

- Diagnostic message text — identical wording, just lives in `.message`
- `_score_result()` conditions and scoring logic — untouched
- Verification pipeline flow — untouched
- Badge labels, colors, and behavior — same as today
- `client.py`, `parser.py`, `name_matcher.py` — untouched

### Serialization

**SSE/JSON responses** (`_result_to_dict`):
```json
"diagnostics": [
  {"category": "name", "message": "Name mismatch: cited \"Gonzalez\" vs found \"Nationstar\""},
  {"category": "date", "message": "Date close: cited 2020-11-30 vs filed 2020-09-29"}
]
```

**CLI output** (`__main__.py`): joins `.message` fields with `"; "` — no visible change.

**CSV sidecar JSON**: already writes diagnostics as a JSON field, naturally picks up new structure.

### Frontend badge logic

Before:
```js
if (/^Name (mismatch|differs)/i.test(d)) {
  badges.push({ label: 'Check Name', cls: 'badge-review' });
}
```

After:
```js
if (d.category === 'name') {
  badges.push({ label: 'Check Name', cls: 'badge-review' });
}
```

WL Cite special case:
```js
if (d.category === 'cite' && /could not be confirmed/i.test(d.message)) {
  badges.push({ label: 'WL Cite', cls: 'badge-info', tip: '...' });
} else if (d.category === 'cite') {
  badges.push({ label: 'Check Cite', cls: 'badge-review' });
}
```

### Testing

Assertions change from string checks to structured checks:
```python
# Before
assert "Name mismatch" in result.diagnostics[0]

# After
assert result.diagnostics[0].category == "name"
assert "Name mismatch" in result.diagnostics[0].message
```

### Migration notes

- The `Diagnostic` dataclass should have a `__str__` method returning `.message` for backwards compatibility in any string context (logging, f-strings).
- The refactor is a single atomic change — no phased rollout needed since all consumers are in this repo.
