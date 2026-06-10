"""Build the fallback-test corpus from the coverage study's lookup misses.

Source: case-law-proposition-benchmark/scratch/cl-coverage-offshoot/
coverage_per_citation.csv (250 cited citations from 78 recent opinions; see
coverage_memo.docx). Rows with lookup_status=NOT_FOUND are real cases that
citation-lookup could NOT resolve — i.e., exactly the inputs that exercise
the opinion-search/RECAP fallback in a full verify().

Reconstructs a verifiable citation string per row and writes
tests/data/fallback_corpus.json. Offline — no API calls.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[2]
    / "case-law-proposition-benchmark/scratch/cl-coverage-offshoot/coverage_per_citation.csv"
)
_OUT = Path(__file__).parent / "data" / "fallback_corpus.json"


def _standalone(cite: str) -> bool:
    """Full volume-reporter-page (or WL) cite — not an 'id.'/'at' short form."""
    s = cite.strip()
    # "650 F.2d at 321" (pinpoint-only short cite) — no page of its own
    if re.search(r"\bat\b", s) and not re.search(r"\d+\s*,", s):
        # allow "22 F.4th 450, 459" (full cite + pinpoint) which has a comma
        if not re.search(r"[A-Za-z.]\s*\d+\s*$", s.split(" at ")[0].strip()):
            return False
    if "WL" in s:
        return bool(re.search(r"\d{4}\s+WL\s+\d+", s))
    # require volume reporter page
    return bool(re.search(r"^\d+\s+[A-Za-z. 0-9]+?\s+\d+", s))


def _reconstruct(row: dict) -> str | None:
    """Best-effort full citation: 'Name, cite (court year)'."""
    cite = row["citation_string"].strip().rstrip(",")
    name = row["cited_case_name"].strip().strip('"')
    if not name or not _standalone(cite):
        return None
    paren_bits = [b for b in (row.get("court_hint", "").strip(),
                              row.get("year", "").strip()) if b]
    paren = f" ({' '.join(paren_bits)})" if paren_bits else ""
    return f"{name}, {cite}{paren}"


def main() -> None:
    rows = list(csv.DictReader(open(_SRC, encoding="utf-8")))
    misses = [r for r in rows if r["lookup_status"] == "NOT_FOUND"]
    corpus, dropped = [], []
    seen = set()
    for r in misses:
        full = _reconstruct(r)
        if not full:
            dropped.append(r["citation_string"])
            continue
        if full.lower() in seen:
            continue
        seen.add(full.lower())
        corpus.append({
            "citation": full,
            "cited_tier": r["cited_tier"],
            "citing_cluster": r["citing_cluster"],
            "source": "coverage-study lookup miss (quick_only NOT_FOUND)",
        })
    _OUT.write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    print(f"lookup misses: {len(misses)}")
    print(f"reconstructed: {len(corpus)} -> {_OUT.name}")
    print(f"dropped (short-form/unparseable): {len(dropped)}")
    for d in dropped:
        print(f"   - {d[:60]}")
    import collections
    print("by tier:", dict(collections.Counter(e["cited_tier"] for e in corpus)))


if __name__ == "__main__":
    main()
