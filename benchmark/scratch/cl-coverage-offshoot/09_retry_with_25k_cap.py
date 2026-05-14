"""
Third retry — pilot opinions chosen to all sit comfortably under the
~27K-char `claude -p` cliff.

Cap-based picks:
- SCOTUS: Bush v. Gore (531 U.S. 98, cluster 118395, ~23K chars)
- State_COLR: Caceci v. Di Canio (72 N.Y.2d 52, cluster 2585895, ~16K chars)
- State_IAC: People v. Smith (1 Cal. App. 5th 266, cluster 4236900, ~25K chars)

Switches model back to sonnet (haiku change was a debugging experiment that
didn't matter — the bug isn't model-specific). Reuses pilot_opinions cache
where present, otherwise fetches.

Documented in LIMITATIONS.md — this 25K cap is a pilot-only workaround;
real run must address `claude -p` cliff differently (API key, chunking, etc.)
"""
from __future__ import annotations

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

TARGETS = [
    ("SCOTUS",     "531 U.S. 98"),         # Bush v. Gore
    ("State_COLR", "72 N.Y.2d 52"),        # Caceci v. Di Canio
    ("State_IAC",  "1 Cal. App. 5th 266"), # People v. Smith
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
    elapsed = time.time() - t0
    print(f"[{elapsed:6.1f}s] {msg}", flush=True)


def main():
    # Switch model back to sonnet for the real run — haiku was a temporary
    # debug step.
    import extract_citations as ec_mod
    ec_mod.MODEL = "sonnet"

    t0 = time.time()
    client = CourtListenerClient()
    log(t0, f"starting 25K-cap pilot retry — {len(TARGETS)} opinions, model=sonnet")

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

        # Fetch / load opinion text
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

        # Safety: enforce 25K cap explicitly
        if len(op_text) > 25_000:
            log(t0, f"  WARNING: opinion exceeds 25K cap ({len(op_text):,} chars); proceeding anyway, but expect hang")

        # Run extractor
        ex_start = time.time()
        log(t0, f"  running extractor (sonnet, model={ec_mod.MODEL})...")
        result = extract_citations(op_text)
        ex_elapsed = time.time() - ex_start
        log(t0, f"  extractor returned after {ex_elapsed:.1f}s  cost=${result['cost_usd']:.4f}")
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
        log(t0, f"  returned={len(citations)}  appears={len(buckets['appears_in_source'])}  near_miss={len(buckets['near_miss_after_normalize'])}  not_in_source={len(buckets['not_in_source'])}")

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
            "_prompt_variant": "stripped_no_sentence_context",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        log(t0, f"  wrote {ex_file.name}")

    total = time.time() - t0
    log(t0, "")
    log(t0, f"DONE — total wall time {total:.0f}s ({total/60:.1f} min)")


if __name__ == "__main__":
    main()
