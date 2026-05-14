"""
Retry the failed pilot extractions with:

1. **Smaller SCOTUS pick** — Obergefell at 207K chars is exceptional. Swap for
   Knick v. Township of Scott (588 U.S. 180, cluster 4631843, ~46K chars) —
   still substantial citation density (takings clause) but in the
   23-50K-char band where our successful extractions sit.

2. **flush=True on every print** — so the background output file gets per-
   opinion updates instead of buffering everything until process exit.

3. **Live time-stamps** — each line shows wall-clock seconds since start, so
   we can tell exactly how long each opinion took even after the fact.

Targets:
- Knick v. Township of Scott (SCOTUS, ~46K) — fetched from CL
- People v. Lemcke (State_COLR_CA, ~79K) — re-uses pilot_opinions cache
- Ram v. OneWest Bank (State_IAC_CA, ~40K) — re-uses pilot_opinions cache

Outputs: overwrites pilot_extractions/{cluster_id}.json for each.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv(usecwd=False), override=True)

HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OPINIONS_DIR = HERE / "pilot_opinions"
EXTRACTIONS_DIR = HERE / "pilot_extractions"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))
from citation_verifier.client import CourtListenerClient  # noqa: E402
from extract_citations import extract_citations  # noqa: E402

# (tier_label, seed_cite_or_cluster_id, expected_chars_hint)
TARGETS = [
    ("SCOTUS",        "588 U.S. 180"),   # Knick v. Township of Scott — replacing Obergefell
    ("State_COLR_CA", "11 Cal. 5th 644"),  # People v. Lemcke — retry from pilot
    ("State_IAC_CA",  "234 Cal. App. 4th 1"),  # Ram v. OneWest — retry from pilot
]


_SMART_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
})


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_SMART_QUOTE_MAP)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def classify(citation: str, opinion_text: str) -> str:
    cite = (citation or "").strip()
    if not cite:
        return "empty"
    if cite in opinion_text:
        return "appears_in_source"
    if normalize(cite) in normalize(opinion_text):
        return "near_miss_after_normalize"
    return "not_in_source"


def log(t0: float, msg: str) -> None:
    """Time-stamped print, always flushed."""
    elapsed = time.time() - t0
    print(f"[{elapsed:6.1f}s] {msg}", flush=True)


def main():
    t0 = time.time()
    client = CourtListenerClient()
    log(t0, f"starting retry pilot — {len(TARGETS)} opinions")

    for tier_label, seed_cite in TARGETS:
        log(t0, "")
        log(t0, f"=== {tier_label} — seed: {seed_cite} ===")

        # Resolve to cluster
        try:
            rs = client.citation_lookup(seed_cite)
        except Exception as e:
            log(t0, f"  LOOKUP_ERROR: {type(e).__name__}: {e}")
            continue
        if not rs or not rs[0].get("clusters"):
            log(t0, f"  no clusters for {seed_cite}")
            continue
        cluster = rs[0]["clusters"][0]
        cluster_id = cluster["id"]
        case_name = cluster["case_name"]
        court_id = cluster.get("court_id") or ""
        absolute_url = cluster.get("absolute_url") or ""
        if absolute_url and not absolute_url.startswith("http"):
            absolute_url = f"https://www.courtlistener.com{absolute_url}"
        log(t0, f"  cluster={cluster_id}  case={case_name}  court={court_id}")

        # Fetch / load opinion text (use cache if available)
        op_file = OPINIONS_DIR / f"{cluster_id}.txt"
        if op_file.exists():
            op_text = op_file.read_text(encoding="utf-8")
            log(t0, f"  using cached opinion ({len(op_text):,} chars)")
        else:
            log(t0, f"  fetching opinion text...")
            op_text = client.get_opinion_text(absolute_url) or ""
            if not op_text:
                log(t0, f"  NO_OPINION_TEXT — skipping")
                continue
            op_file.write_text(op_text, encoding="utf-8")
            log(t0, f"  fetched and cached ({len(op_text):,} chars)")

        # Run extractor
        ex_start = time.time()
        log(t0, f"  running extractor (this may take a few minutes)...")
        result = extract_citations(op_text)
        ex_elapsed = time.time() - ex_start
        log(t0, f"  extractor returned after {ex_elapsed:.1f}s — cost ${result['cost_usd']:.4f}")
        if result.get("error"):
            log(t0, f"  EXTRACT_ERROR: {result['error'][:200]}")

        # Classify
        citations = result.get("citations", [])
        buckets = {"appears_in_source": [], "near_miss_after_normalize": [], "not_in_source": []}
        for c in citations:
            if not isinstance(c, dict):
                continue
            cls = classify(c.get("citation_string", ""), op_text)
            if cls in buckets:
                c["_classification"] = cls
                buckets[cls].append(c)
        log(t0, f"  returned={len(citations)}  appears_in_source={len(buckets['appears_in_source'])}  near_miss={len(buckets['near_miss_after_normalize'])}  not_in_source={len(buckets['not_in_source'])}")

        # Save
        ex_file = EXTRACTIONS_DIR / f"{cluster_id}.json"
        ex_file.write_text(json.dumps({
            "tier_label": tier_label,
            "seed_cite": seed_cite,
            "cluster_id": cluster_id,
            "case_name": case_name,
            "court_id": court_id,
            "char_count": len(op_text),
            "elapsed_s": result["elapsed_s"],
            "cost_usd": result["cost_usd"],
            "raw_response_chars": result["raw_response_chars"],
            "error": result["error"],
            "citations_appears_in_source": buckets["appears_in_source"],
            "citations_near_miss_after_normalize": buckets["near_miss_after_normalize"],
            "citations_not_in_source": buckets["not_in_source"],
            "citations_all": citations,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        log(t0, f"  wrote {ex_file.name}")

    total = time.time() - t0
    log(t0, "")
    log(t0, f"DONE — total wall time {total:.0f}s ({total/60:.1f} min)")


if __name__ == "__main__":
    main()
