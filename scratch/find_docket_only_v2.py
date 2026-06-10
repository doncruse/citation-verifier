"""Reverse approach: find every docket-number reference in the corpus
(outside the caption header), then inspect each for whether it's a
citation to another case (vs. an ECF reference within the same case).
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\recursing-tharp-f76108\benchmark\scratch\cl-coverage-offshoot\citing_opinions")

DOCKET_RE = re.compile(
    r"(?:No\.|Case\s+No\.|Civil\s+(?:Action\s+)?No\.)\s*"
    r"(\d{1,2}[:\-]?\d{0,2}-(?:cv|cr|mc|md|mj|po|bk|sw|cm)-\d+[A-Z0-9\-]*)",
    re.IGNORECASE,
)

HAS_REPORTER_RE = re.compile(
    r"\bWL\s+\d|\bLEXIS\s+\d|\d\s+U\.\s*S\.\s+\d|\bS\.\s*Ct\.\s+\d|"
    r"\bF\.\s*\d|\bF\.\s*Supp|\bF\.\s*App'?x|\bF\.\s*R\.\s*D\.\b"
)

# Federal district court abbreviations in parentheticals
FED_DIST_RE = re.compile(
    r"\b(?:[NSEW]\.D\.|D\.D\.C\.|D\.\s*(?:Mass|Conn|Md|N\.J|Del|Kan|Neb|Or|Nev|"
    r"Ariz|Colo|Minn|N\.M|Utah|Idaho|Alaska|Haw|Wyo|Mont|Vt|N\.H|R\.I|Me))",
    re.IGNORECASE,
)

CASE_NAME_RE = re.compile(
    r"([A-Z][A-Za-z\.\'\-]+(?:\s+[A-Z][A-Za-z\.\'\-,&]+){0,3}\s+v\.\s+[A-Z][A-Za-z\.\'\-]+(?:\s+[A-Z][A-Za-z\.\'\-,&]+){0,5})"
)


def classify(window: str) -> str:
    """Classify a docket-reference window."""
    has_rep = bool(HAS_REPORTER_RE.search(window))
    has_fed = bool(FED_DIST_RE.search(window))
    has_v = " v. " in window or " v " in window
    has_ecf = "ECF" in window or "Dkt." in window or "Docket No." in window

    if has_rep:
        return "has_reporter_or_wl"
    # No reporter
    if has_v and has_fed:
        return "DOCKET_ONLY_CITATION"  # what we're looking for
    if has_v and not has_fed:
        return "no_court_paren"
    if has_ecf and not has_v:
        return "internal_ecf_ref"
    return "other"


def main() -> None:
    files = sorted(BASE.glob("*.txt"))
    print(f"scanning {len(files)} citing opinions")

    classifications = Counter()
    docket_only_hits = []
    samples_by_class = {}

    for f in files:
        txt = f.read_text(encoding="utf-8", errors="replace")
        # Skip caption (first 2500 chars typically holds caption header)
        body_start = 2500
        for m in DOCKET_RE.finditer(txt):
            if m.start() < body_start:
                continue
            win_start = max(body_start, m.start() - 250)
            win_end = min(len(txt), m.end() + 120)
            win = txt[win_start:win_end]
            cls = classify(win)
            classifications[cls] += 1
            if cls == "DOCKET_ONLY_CITATION":
                # try to grab the case name
                case_m = None
                for cm in CASE_NAME_RE.finditer(win):
                    case_m = cm
                docket_only_hits.append({
                    "file": f.name,
                    "docket": m.group(1).strip(),
                    "case_name": case_m.group(1).strip() if case_m else "",
                    "context": win.replace("\n", " ")[-300:],
                })
            samples_by_class.setdefault(cls, []).append({
                "file": f.name,
                "docket": m.group(1).strip(),
                "context": win.replace("\n", " ")[-200:],
            })

    print("\nclassification of docket references (outside caption):")
    for cls, n in classifications.most_common():
        print(f"  {cls:<30} {n}")

    print("\n=== DOCKET_ONLY_CITATION hits ===")
    for h in docket_only_hits[:30]:
        print(f"\n[{h['file']}] docket={h['docket']}")
        print(f"  case_name guess: {h['case_name']}")
        print(f"  ctx: ...{h['context']}")

    # Show 2 samples per other class for sanity
    print("\n=== 2 samples per other class (sanity check) ===")
    for cls, samples in samples_by_class.items():
        if cls == "DOCKET_ONLY_CITATION":
            continue
        print(f"\n--- {cls} ---")
        for s in samples[:2]:
            print(f"  [{s['file']}] {s['docket']}")
            print(f"     ctx: ...{s['context']}")

    # Save full DOCKET_ONLY list
    out = Path(r"C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\recursing-tharp-f76108\scratch\docket_only_v2.csv")
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "docket", "case_name", "context"])
        w.writeheader()
        w.writerows(docket_only_hits)
    print(f"\nwrote {out} ({len(docket_only_hits)} rows)")


if __name__ == "__main__":
    main()
