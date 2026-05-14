"""
Step 3 (pilot): run the LLM citation extractor on 5 opinions across tiers
and report per-opinion stats.

Goal: confirm before scaling that
(a) Sonnet via `claude -p` returns the right citations,
(b) hallucination rate is low (post-validation catches them),
(c) coverage looks reasonable vs eyecite (qualitative spot-check),
(d) per-opinion cost and wall time are within budget for ~250 opinions.

Inputs: 5 hand-picked clusters, one per tier where possible.
Outputs:
- pilot_opinions/<cluster_id>.txt      raw opinion text
- pilot_extractions/<cluster_id>.json  extractor output (validated + hallucinated)
- pilot_summary.csv                    one row per opinion with stats
- pilot_summary.md                     narrative summary

Note: the picks below are seed citations — the script resolves each to a CL
cluster via citation-lookup and fetches the opinion text from there. Pick is
deliberately diverse to surface tier-specific extraction quirks; not a random
sample.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Load env first. .env lives at the main project root, which may be the
# parent of a git worktree — let dotenv walk up to find it.
from dotenv import load_dotenv, find_dotenv
ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)

sys.path.insert(0, str(ROOT / "src"))
from citation_verifier.client import CourtListenerClient  # noqa: E402

HERE = Path(__file__).parent
OPINIONS_DIR = HERE / "pilot_opinions"
EXTRACTIONS_DIR = HERE / "pilot_extractions"
SUMMARY_CSV = HERE / "pilot_summary.csv"
SUMMARY_MD = HERE / "pilot_summary.md"

OPINIONS_DIR.mkdir(exist_ok=True)
EXTRACTIONS_DIR.mkdir(exist_ok=True)

# Local import of the extractor module
sys.path.insert(0, str(HERE))
from extract_citations import extract_citations, validate_citations  # noqa: E402

# Seed citations — one per tier where possible. We resolve to CL cluster IDs
# at runtime so the pilot doesn't bake stale IDs into the script.
PILOT_SEEDS = [
    ("SCOTUS", "576 U.S. 644"),                  # Obergefell v. Hodges
    ("Circuit_DC", "789 F.3d 146"),              # Brown v. Whole Foods Mkt. Grp.
    ("Circuit_9th", "947 F.3d 240"),             # Wojcicki v. SCANA
    ("State_COLR_CA", "11 Cal. 5th 644"),        # People v. Lemcke (recent)
    ("State_IAC_CA", "234 Cal. App. 4th 1"),     # Marriage of Smith
]


def resolve_to_cluster(client: CourtListenerClient, cite: str) -> tuple[int | None, str, str, str]:
    """Given a citation string, return (cluster_id, case_name, court_id, absolute_url)."""
    try:
        rs = client.citation_lookup(cite)
    except Exception as e:
        return None, "", "", f"LOOKUP_ERROR: {type(e).__name__}: {e}"
    if not rs or not rs[0].get("clusters"):
        return None, "", "", "NO_CLUSTERS"
    cl = rs[0]["clusters"][0]
    return cl["id"], cl["case_name"], cl.get("court_id") or "", cl.get("absolute_url") or ""


def main():
    client = CourtListenerClient()
    rows = []
    for tier_label, seed_cite in PILOT_SEEDS:
        print(f"\n=== {tier_label} — seed: {seed_cite} ===")

        cluster_id, case_name, court_id, url_or_err = resolve_to_cluster(client, seed_cite)
        if not cluster_id:
            print(f"  skip: {url_or_err}")
            rows.append({
                "tier_label": tier_label,
                "seed_cite": seed_cite,
                "cluster_id": "",
                "cited_case_name": "",
                "cited_court_id": "",
                "char_count": 0,
                "elapsed_s": 0,
                "cost_usd": 0.0,
                "n_returned": 0,
                "n_valid": 0,
                "n_hallucinated": 0,
                "error": url_or_err,
            })
            continue

        print(f"  cluster={cluster_id}  case={case_name}  court={court_id}")

        # Fetch opinion text
        if not url_or_err.startswith("http"):
            url_or_err = f"https://www.courtlistener.com{url_or_err}"
        op_text = client.get_opinion_text(url_or_err)
        if not op_text:
            print("  skip: no opinion text")
            rows.append({
                "tier_label": tier_label,
                "seed_cite": seed_cite,
                "cluster_id": cluster_id,
                "cited_case_name": case_name,
                "cited_court_id": court_id,
                "char_count": 0,
                "elapsed_s": 0,
                "cost_usd": 0.0,
                "n_returned": 0,
                "n_valid": 0,
                "n_hallucinated": 0,
                "error": "NO_OPINION_TEXT",
            })
            continue

        # Persist opinion
        op_file = OPINIONS_DIR / f"{cluster_id}.txt"
        op_file.write_text(op_text, encoding="utf-8")
        print(f"  opinion {len(op_text):,} chars  saved to {op_file.name}")

        # Run extractor
        print("  running extractor...", end="", flush=True)
        result = extract_citations(op_text)
        print(f"  done in {result['elapsed_s']}s, cost ${result['cost_usd']:.4f}")
        if result["error"]:
            print(f"  EXTRACT_ERROR: {result['error'][:200]}")

        # Validate
        valid, halluc = validate_citations(result["citations"], op_text)
        print(f"  returned={len(result['citations'])}  valid={len(valid)}  hallucinated={len(halluc)}")

        # Save extraction
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
            "citations_valid": valid,
            "citations_hallucinated": halluc,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        rows.append({
            "tier_label": tier_label,
            "seed_cite": seed_cite,
            "cluster_id": cluster_id,
            "cited_case_name": case_name,
            "cited_court_id": court_id,
            "char_count": len(op_text),
            "elapsed_s": result["elapsed_s"],
            "cost_usd": result["cost_usd"],
            "n_returned": len(result["citations"]),
            "n_valid": len(valid),
            "n_hallucinated": len(halluc),
            "error": result["error"] or "",
        })

    # Save summary CSV
    fieldnames = list(rows[0].keys())
    with open(SUMMARY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {SUMMARY_CSV.name}")

    # Save narrative summary
    lines = ["# Pilot extraction summary", ""]
    total_cost = sum(r["cost_usd"] for r in rows)
    total_time = sum(r["elapsed_s"] for r in rows)
    total_valid = sum(r["n_valid"] for r in rows)
    total_halluc = sum(r["n_hallucinated"] for r in rows)
    total_returned = sum(r["n_returned"] for r in rows)
    lines.append(f"- Opinions processed: {len(rows)}")
    lines.append(f"- Total wall time: {total_time:.1f}s ({total_time/60:.1f} min)")
    lines.append(f"- Total cost: ${total_cost:.4f}")
    lines.append(f"- Citations returned: {total_returned}  |  valid: {total_valid}  |  hallucinated: {total_halluc}")
    if total_returned > 0:
        lines.append(f"- Hallucination rate: {100*total_halluc/total_returned:.1f}%")
    lines.append("")
    lines.append("## Per-opinion stats")
    lines.append("")
    lines.append("| tier | cluster | case | chars | s | $ | returned | valid | halluc |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        case_short = (r["cited_case_name"] or "")[:40]
        lines.append(
            f"| {r['tier_label']} | {r['cluster_id']} | {case_short} | "
            f"{r['char_count']:,} | {r['elapsed_s']} | ${r['cost_usd']:.4f} | "
            f"{r['n_returned']} | {r['n_valid']} | {r['n_hallucinated']} |"
        )
    lines.append("")
    lines.append("## Projection to 250 opinions")
    lines.append("")
    if len(rows) > 0:
        avg_time = total_time / len(rows)
        avg_cost = total_cost / len(rows)
        lines.append(f"- Est. wall time: 250 × {avg_time:.1f}s = {250*avg_time/60:.0f} min ({250*avg_time/3600:.1f} hr)")
        lines.append(f"- Est. cost: 250 × ${avg_cost:.4f} = ${250*avg_cost:.2f}")
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {SUMMARY_MD.name}")

    print(f"\nTotal: {len(rows)} opinions  {total_time:.0f}s  ${total_cost:.4f}  "
          f"valid={total_valid}  halluc={total_halluc}")


if __name__ == "__main__":
    main()
