# Newline before court/year parenthetical causes metadata loss in PDF-extracted text

## Summary

When a newline separates a citation from its court/year parenthetical — extremely common in PDF-extracted text — eyecite loses the court and year metadata. `match_on_tokens()` stops scanning at a `ParagraphToken` boundary and never sees the parenthetical on the next line.

## Reproduction

```python
from eyecite import get_citations
from eyecite.models import FullCaseCitation

# Same line: works
c = [c for c in get_citations('Citation 123 F.3d 456 (N.D. Ohio 2006).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year == '2006'   # ✓
assert c.metadata.court == 'ohnd'  # ✓

# Newline before parenthetical: metadata lost
c = [c for c in get_citations('Citation 123 F.3d 456\n(N.D. Ohio 2006).')
     if isinstance(c, FullCaseCitation)][0]
assert c.metadata.year is None    # ✗
assert c.metadata.court is None   # ✗
```

Also affects pin cites with newlines:
```python
# "962 F.3d 979, 984 (7th Cir.\n2020)" — year lost
# "728 F.2d 911,\n915 (7th Cir. 1984)" — court and year lost
```

## Impact

I'm building a citation verification tool ([rlfordon/citation-verifier](https://github.com/rlfordon/citation-verifier)) that extracts citations from court opinion PDFs using eyecite. In my corpus of 19 PDFs (536 total citations), **101 citations (19%) lost court/year metadata** due to this issue. Every single PDF was affected. All common reporters hit: F.2d, F.3d, F.4th, F. Supp. 2d/3d, N.E.2d/3d, S.W.2d/3d, P.3d, Cal. App., WL.

This is because PDF text extractors (pdfplumber, pdfminer, etc.) preserve line breaks from the page layout, and court opinions frequently break lines between a citation and its parenthetical.

## Root cause

In `eyecite/helpers.py`, `match_on_tokens()` stops at `ParagraphToken` boundaries. A single `\n` in the input becomes a `ParagraphToken`, so the parenthetical on the next line is never reached.

## Possible approaches

A few options with different trade-offs — curious what you'd prefer:

1. **Option flag**: Add a parameter like `allow_newline_before_paren=True` (default `False` for backward compat)
2. **Peek past boundary**: Always scan one token past a `ParagraphToken` if the next non-whitespace starts with `(`
3. **Single vs double newline**: Treat `\n` as a line break (continue scanning) and `\n\n` as a true paragraph boundary (stop scanning)

## Workaround

I currently run a post-extraction repair pass that finds citations with `year=None`, looks at the text after the citation span for orphaned parentheticals, and patches the metadata. It works but is fragile and duplicates logic that should live in eyecite.

Happy to submit a PR if you'd like — just let me know which approach you'd prefer.
