# Apostrophes in legal abbreviations truncate case name extraction (Dep't, Nat'l, Comm'n, etc.)

## Summary

eyecite's case name extraction regexes use character classes like `[\w\-.]+` that don't include apostrophes. Legal abbreviations with internal apostrophes — `Dep't`, `Nat'l`, `Comm'n`, `Att'y`, `P'ship`, etc. — are truncated at the apostrophe, losing the suffix.

## Reproduction

```python
from eyecite import get_citations
from eyecite.models import FullCaseCitation

text = "Att'y Grievance Comm'n v. Glenn, 341 Md. 448 (2003)."
c = [c for c in get_citations(text) if isinstance(c, FullCaseCitation)][0]
print(c.metadata.plaintiff)
# Expected: "Att'y Grievance Comm'n"
# Actual:   "Att' Grievance Comm'"   (suffixes after apostrophes dropped)

text2 = "Keaau Dev. P'ship LLC v. Lawrence, 571 P.3d 958 (2025)."
c2 = [c for c in get_citations(text2) if isinstance(c, FullCaseCitation)][0]
print(c2.metadata.plaintiff)
# Expected: "Keaau Dev. P'ship LLC"
# Actual:   "Keaau Dev. P' LLC"
```

## Affected abbreviations

These are all standard Indigo Book legal abbreviations — very common in case citations:

| Cited as | Extracted as | Full form |
|----------|-------------|-----------|
| `Att'y` | `Att'` | Attorney |
| `Dep't` | `Dep'` | Department |
| `Gov't` | `Gov'` | Government |
| `Comm'n` | `Comm'` | Commission |
| `Comm'r` | `Comm'` | Commissioner |
| `P'ship` | `P'` | Partnership |
| `Nat'l` | `Nat'` | National |
| `Int'l` | `Int'` | International |
| `Sec'y` | `Sec'` | Secretary |
| `Ass'n` | `Ass'` | Association |
| `Adm'r` | `Adm'` | Administrator |

## Root cause

Three regexes in `eyecite/regexes.py` use character classes that exclude apostrophes:

| Regex | Character class | Purpose |
|-------|----------------|---------|
| `SHORT_CITE_ANTECEDENT_REGEX` | `[\w\-.]+` | Short cite antecedents |
| `SUPRA_ANTECEDENT_REGEX` | `[\w\-.]+` | Supra cite antecedents |
| `PRE_FULL_CITATION_REGEX` | `[a-z\-.]+` | Backward scan for case names |

## Suggested fix

Add straight and curly apostrophes to the character classes:

- `[\w\-.]+` → `[\w\-.'\u2019]+`
- `[a-z\-.]+` → `[a-z\-.'\u2019]+`

Including `\u2019` (right single quotation mark) handles PDFs that use Unicode smart quotes.

This should be low risk — the regexes already allow periods and hyphens, so apostrophes are consistent. The change is additive: existing matches are unaffected, only previously-truncated words are now captured fully.

## Impact

I found 8 case names directly affected in my corpus of 19 court opinion PDFs that I've been running through eyecite. These abbreviations are extremely common in legal citations generally — this likely affects a significant number of extractions.

Happy to submit a PR for this if you'd like.
