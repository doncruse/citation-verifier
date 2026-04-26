"""Build a 50-row LePaRD sample for Pilot A.

LePaRD's column naming is *opposite* to what its data card claims (verified
empirically on 2026-04-26): `source_*` is the older / **cited** case and
`dest_*` is the newer / **citing** case. We use `destination_context` (text
immediately preceding the citation in the citing opinion) as the proposition,
and (`source_name`, `source_cite`) as the gold case.

Output: scratch/pilot_a/lepard_sample.csv with columns:
    id, proposition, gold_name, gold_cite, citing_court, citing_year,
    cited_year, source_quote
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from datasets import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUT = PROJECT_ROOT / "scratch" / "pilot_a" / "lepard_sample.csv"

SAMPLE_SIZE = 50
SHUFFLE_BUFFER = 20_000
SHUFFLE_SEED = 42

# Filters: a "usable" row needs a non-trivial proposition and full gold metadata.
MIN_CONTEXT_LEN = 200      # at least ~3 sentences
MAX_CONTEXT_LEN = 6_000    # avoid pathological string-cite walls
MIN_GOLD_CITE_LEN = 10


def _trim_proposition(context: str, gold_name: str, gold_cite: str) -> str:
    """Take the last ~3 sentences of context and scrub the gold citation.

    Models trained on this data could shortcut by spotting the citation that
    LePaRD left in `destination_context`. Strip any obvious form of it.
    """
    if not context:
        return ""
    text = context.strip()

    # Pull the last few sentences (coarse). LePaRD context often runs long.
    parts = re.split(r"(?<=[.!?])\s+", text)
    tail = " ".join(parts[-4:]).strip() if len(parts) > 4 else text

    # Strip the gold citation in any form ("Foo v. Bar, 1 F.2d 2 (1923)",
    # "1 F.2d 2", etc.) so the model can't keyword-match.
    cleaned = tail
    if gold_cite:
        # Strip the full thing, then any reporter-volume-page fragment.
        cleaned = cleaned.replace(gold_cite, "[CASE]")
        m = re.search(r"\d+\s+[A-Z][\w\.\s]*?\s+\d+", gold_cite)
        if m:
            cleaned = cleaned.replace(m.group(0), "[CASE]")
    if gold_name:
        cleaned = cleaned.replace(gold_name, "[CASE]")
        # Also try short form ("Foo v. Bar")
        m = re.match(r"([A-Z][\w\.'\-]*(?:\s+[A-Z][\w\.'\-]*)*)\s+v\.\s+"
                     r"([A-Z][\w\.'\-]*(?:\s+[A-Z][\w\.'\-]*)*)",
                     gold_name)
        if m:
            cleaned = cleaned.replace(m.group(0), "[CASE]")

    return re.sub(r"\s+", " ", cleaned).strip()


def _year_from_date(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.match(r"(\d{4})", date_str)
    return m.group(1) if m else ""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading LePaRD (streaming, shuffle seed={SHUFFLE_SEED}, "
          f"buffer={SHUFFLE_BUFFER})...", flush=True)
    ds = load_dataset("rmahari/LePaRD", split="train", streaming=True)
    ds = ds.shuffle(seed=SHUFFLE_SEED, buffer_size=SHUFFLE_BUFFER)

    rows: list[dict[str, str]] = []
    seen = 0
    for row in ds:
        seen += 1
        if seen > 50_000:
            print(f"  scanned {seen} rows, only {len(rows)} usable -- aborting",
                  file=sys.stderr)
            break

        ctx = (row.get("destination_context") or "").strip()
        gold_name = (row.get("source_name") or "").strip()
        gold_cite = (row.get("source_cite") or "").strip()
        citing_court = (row.get("dest_court") or "").strip()
        citing_date = (row.get("dest_date") or "").strip()
        cited_date = (row.get("source_date") or "").strip()

        if not gold_name or len(gold_cite) < MIN_GOLD_CITE_LEN:
            continue
        if len(ctx) < MIN_CONTEXT_LEN or len(ctx) > MAX_CONTEXT_LEN:
            continue

        proposition = _trim_proposition(ctx, gold_name, gold_cite)
        if len(proposition) < 100 or len(proposition) > 1500:
            continue

        rows.append({
            "id": f"lepard-{row.get('passage_id', '')}",
            "proposition": proposition,
            "gold_name": gold_name,
            "gold_cite": gold_cite,
            "citing_court": citing_court,
            "citing_year": _year_from_date(citing_date),
            "cited_year": _year_from_date(cited_date),
            "source_quote": (row.get("quote") or "").strip()[:2000],
        })

        if len(rows) >= SAMPLE_SIZE:
            break

        if len(rows) % 10 == 0 and len(rows) > 0:
            print(f"  collected {len(rows)} (scanned {seen})", flush=True)

    print(f"\nFinal sample: {len(rows)} rows (scanned {seen} total).")
    if not rows:
        print("ERROR: no rows collected.", file=sys.stderr)
        sys.exit(1)

    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "proposition", "gold_name", "gold_cite",
                        "citing_court", "citing_year", "cited_year",
                        "source_quote"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote {OUT}")
    print(f"\nSample row 0:")
    for k, v in rows[0].items():
        sval = str(v)
        if len(sval) > 200:
            sval = sval[:200] + "..."
        print(f"  {k}: {sval}")


if __name__ == "__main__":
    main()
