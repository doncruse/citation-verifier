"""Find docket-only citation patterns across all 82 citing opinions.

A "docket-only citation" looks like a citation to ANOTHER case (not the
citing opinion's own caption) where the identifier is a docket number
and a court+date parenthetical, with NO reporter cite (no F. Supp.,
F.3d, U.S., WL, LEXIS, etc.) attached.

Strategy:
  1. Find every '(<court> <date>)' parenthetical that names a federal
     district court (S.D.N.Y., D.D.C., N.D. Cal., etc.) or generic court.
  2. Look ~120 chars before the parenthetical for a "No.<docket>" or
     "Case No.<docket>" form.
  3. Look ~120 chars before for any case name (something with " v. ").
  4. Exclude windows that contain WL / LEXIS / a reporter cite — those
     ARE captured by the extractor.
  5. Exclude the citing opinion's own caption (typically appears near
     the top of the file with "Plaintiff," "Defendant," etc.).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

BASE = Path(r"C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\recursing-tharp-f76108\benchmark\scratch\cl-coverage-offshoot\citing_opinions")

# Docket number form: 1:23-cv-04567 / 23-cv-4567 / 2:21-cr-00123-AB
DOCKET_RE = re.compile(
    r"(?:No\.|Case\s+No\.|Civil\s+(?:Action\s+)?(?:No\.|Case\s+No\.))\s*"
    r"(\d{1,2}[:\-]?\d{0,2}-(?:cv|cr|mc|md|mj|po|bk|sw|cm)-\d+(?:-[A-Z0-9\-]+)?)",
    re.IGNORECASE,
)

# Court+date parenthetical with a federal district indicator.
# Simpler approach: match any parenthetical containing a federal-district
# pattern (compass-direction + ".D." or "D.D.C.") plus a 4-digit year.
FEDDIST_PAREN_RE = re.compile(
    r"\([^)]{0,80}?(?:[NSEW]\.\s*D\.|D\.\s*D\.\s*C\.|D\.\s*Mass\.|D\.\s*Conn\.|D\.\s*N\.\s*J\.|D\.\s*Md\.|D\.\s*Del\.|D\.\s*Kan\.|D\.\s*Neb\.|D\.\s*Or\.|D\.\s*Nev\.|D\.\s*Ariz\.|D\.\s*Colo\.|D\.\s*Minn\.|D\.\s*N\.\s*M\.|D\.\s*Utah|D\.\s*Idaho|D\.\s*Alaska|D\.\s*Haw\.|D\.\s*Wyo\.|D\.\s*Mont\.|D\.\s*Vt\.|D\.\s*N\.\s*H\.|D\.\s*R\.\s*I\.|D\.\s*Me\.)[^)]{0,40}?\d{4}\s*\)"
)

# Reporter/WL/LEXIS indicators — if present in window, NOT docket-only
HAS_REPORTER_RE = re.compile(
    r"\bWL\s+\d|\bLEXIS\s+\d|\bU\.S\.\s+\d|\bS\.\s*Ct\.\s+\d|\bF\.\s*\d|\bF\.\s*Supp\.|\bF\.\s*App'?x"
)

# Find case-name "v." within window
CASE_NAME_RE = re.compile(
    r"([A-Z][A-Za-z\.\'\-]*(?:\s+[A-Z][A-Za-z\.\'\-]*){0,4}\s+v\.\s+[A-Z][A-Za-z\.\'\-]*(?:\s+[A-Z][A-Za-z\.\'\-,&]*){0,4})"
)


def find_hits(text: str, filename: str) -> list[dict]:
    hits = []
    # Skip the first 2000 chars to avoid caption header (where the
    # citing opinion's own docket lives)
    body_start = 2000
    for m in FEDDIST_PAREN_RE.finditer(text):
        if m.start() < body_start:
            continue
        # Window from 200 chars before to end of parenthetical
        win_start = max(0, m.start() - 200)
        win = text[win_start : m.end()]

        # Must contain a docket number ref
        dkt_m = DOCKET_RE.search(win)
        if not dkt_m:
            continue
        # Must NOT contain a reporter/WL/LEXIS cite in the window
        if HAS_REPORTER_RE.search(win):
            continue
        # Must contain a case name 'X v. Y' before the docket
        # Look for the latest 'v.' before the parenthetical
        case_m = None
        for cm in CASE_NAME_RE.finditer(win):
            case_m = cm
        if not case_m:
            continue

        hits.append({
            "file": filename,
            "case_name": case_m.group(1).strip(),
            "docket": dkt_m.group(1).strip(),
            "court_date": text[m.start() : m.end()],
            "window": win.replace("\n", " ")[-300:],
        })
    return hits


def main() -> None:
    files = sorted(BASE.glob("*.txt"))
    print(f"scanning {len(files)} citing opinions")
    all_hits = []
    for f in files:
        txt = f.read_text(encoding="utf-8", errors="replace")
        all_hits.extend(find_hits(txt, f.name))
    print(f"total candidate docket-only citations: {len(all_hits)}\n")

    # Bucket by file to see distribution
    from collections import Counter
    per_file = Counter(h["file"] for h in all_hits)
    print(f"files with >=1 hit: {len(per_file)}")
    for fn, n in per_file.most_common(10):
        print(f"  {fn}: {n}")

    # Show 25 random/spread examples
    print("\n=== sample hits ===")
    seen_files = set()
    shown = 0
    for h in all_hits:
        # Prefer to show one per file first
        if h["file"] in seen_files and shown < 15:
            continue
        seen_files.add(h["file"])
        print(f"\n[{h['file']}]")
        print(f"  case:   {h['case_name']}")
        print(f"  docket: {h['docket']}")
        print(f"  paren:  {h['court_date']}")
        print(f"  ctx:    ...{h['window'][-250:]}")
        shown += 1
        if shown >= 25:
            break

    # Save full list to CSV
    out = Path(r"C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\recursing-tharp-f76108\scratch\docket_only_candidates.csv")
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "case_name", "docket", "court_date", "window"])
        w.writeheader()
        w.writerows(all_hits)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
