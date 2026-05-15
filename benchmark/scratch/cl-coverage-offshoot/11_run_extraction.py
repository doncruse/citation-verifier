"""
Step 2 of the real run: LLM extraction of citations from every mined
opinion in `citing_opinions/_manifest.csv`.

Per the 2026-05-14 A/B test (ab_results.csv):
- Model: haiku (21% more valid citations and 42% fewer hallucinations
  than sonnet at a 17% per-opinion cost premium).
- Timeout: 600s (set in extract_citations.TIMEOUT_S). The 24K-25K char
  band has known hang behavior — 600s gives slow-but-completable
  opinions room to finish without wasting 15+ min per hang.

For each opinion in the manifest:
1. Skip if `real_extractions/<cluster_id>.json` already exists.
2. Read opinion text from `citing_opinions/<cluster_id>.txt`.
3. Run `extract_citations.extract_citations(text)` (defaults: haiku, 600s).
4. Validate against the source (citation_string substring match).
5. Persist full output JSON to `real_extractions/<cluster_id>.json`.

End-of-run summary printed + written to `extraction_summary.md`.

Wall time estimate: 78 opinions x ~100s avg + ~5 x 600s timeouts ≈ 3 hr.
Cost estimate: 78 x ~$0.09 ≈ $7.

Resumable: re-running skips opinions already on disk. Use this if any
extractions error out mid-run.

CLI:
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/11_run_extraction.py
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/11_run_extraction.py --limit 5
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/11_run_extraction.py --skip-existing
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from extract_citations import extract_citations, validate_citations  # noqa: E402

HERE = Path(__file__).parent
MANIFEST = HERE / "citing_opinions" / "_manifest.csv"
OPDIR = HERE / "citing_opinions"
EXTRACT_DIR = HERE / "real_extractions"
SUMMARY_CSV = HERE / "extraction_summary.csv"
SUMMARY_MD = HERE / "extraction_summary.md"


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 2: LLM-extract citations from all mined opinions")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process at most N opinions (default: all)")
    ap.add_argument("--force", action="store_true",
                    help="Re-extract even if output JSON already exists")
    args = ap.parse_args()

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if args.limit > 0:
        rows = rows[: args.limit]

    print(f"Step 2 — LLM extraction over {len(rows)} opinions")
    print(f"Out:  {EXTRACT_DIR}")
    print()

    results: list[dict[str, Any]] = []
    t_run = time.time()
    skip_existing = 0

    for i, r in enumerate(rows, 1):
        cid = int(r["cluster_id"])
        out_path = EXTRACT_DIR / f"{cid}.json"

        if out_path.exists() and not args.force:
            # Load existing for the summary
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                results.append({
                    "cluster_id": cid,
                    "court_id": r["court_id"],
                    "level": r["level"],
                    "case_name": r["case_name"],
                    "char_count": int(r["char_count"]),
                    "elapsed_s": existing.get("elapsed_s", 0),
                    "cost_usd": existing.get("cost_usd", 0),
                    "raw_response_chars": existing.get("raw_response_chars", 0),
                    "n_total": len(existing.get("citations_valid", []))
                              + len(existing.get("citations_hallucinated", [])),
                    "n_valid": len(existing.get("citations_valid", [])),
                    "n_halluc": len(existing.get("citations_hallucinated", [])),
                    "error": existing.get("error") or "",
                    "reused": True,
                })
                skip_existing += 1
                print(f"  [{i}/{len(rows)}] {cid}  (reusing existing extraction)")
                continue
            except Exception:
                # Corrupted file — re-extract
                pass

        txt_path = OPDIR / f"{cid}.txt"
        if not txt_path.exists():
            print(f"  [{i}/{len(rows)}] {cid}  MISSING opinion text on disk; skipping")
            continue
        text = txt_path.read_text(encoding="utf-8")

        print(f"  [{i}/{len(rows)}] {cid}  {r['court_id']:<14} {int(r['char_count']):>6,}c  "
              f"{(r['case_name'] or '(no name)')[:50]:<50}",
              end="", flush=True)
        out = extract_citations(text)
        valid, halluc = validate_citations(out["citations"], text)
        print(f"  {out['elapsed_s']:>6.1f}s ${out['cost_usd']:.4f}  "
              f"valid={len(valid):>3}  halluc={len(halluc):>2}  "
              f"{('ERR:' + out['error'][:30]) if out['error'] else 'OK'}")

        # Persist
        out_path.write_text(json.dumps({
            "cluster_id": cid,
            "court_id": r["court_id"],
            "level": r["level"],
            "case_name": r["case_name"],
            "char_count": int(r["char_count"]),
            "date_filed": r.get("date_filed", ""),
            "source_url": r.get("source_url", ""),
            "elapsed_s": out["elapsed_s"],
            "cost_usd": out["cost_usd"],
            "raw_response_chars": out["raw_response_chars"],
            "error": out["error"],
            "citations_valid": valid,
            "citations_hallucinated": halluc,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        results.append({
            "cluster_id": cid,
            "court_id": r["court_id"],
            "level": r["level"],
            "case_name": r["case_name"],
            "char_count": int(r["char_count"]),
            "elapsed_s": out["elapsed_s"],
            "cost_usd": out["cost_usd"],
            "raw_response_chars": out["raw_response_chars"],
            "n_total": len(out["citations"]),
            "n_valid": len(valid),
            "n_halluc": len(halluc),
            "error": out["error"] or "",
            "reused": False,
        })

    # CSV
    if results:
        fields = list(results[0].keys())
        with SUMMARY_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(results)
        print(f"\nwrote {SUMMARY_CSV}")

    # MD summary
    elapsed_total = time.time() - t_run
    fresh = [r for r in results if not r["reused"]]
    timeouts = [r for r in results if "TIMEOUT" in (r["error"] or "")]
    errored = [r for r in results if r["error"]]
    total_cost = sum(r["cost_usd"] for r in fresh)
    total_valid = sum(r["n_valid"] for r in results)
    total_halluc = sum(r["n_halluc"] for r in results)
    total_returned = sum(r["n_total"] for r in results)
    median_chars = sorted(r["char_count"] for r in results)[len(results)//2] if results else 0
    halluc_rate = (100 * total_halluc / total_returned) if total_returned else 0

    lines = [
        "# Step 2 — extraction summary",
        "",
        f"- Manifest opinions: {len(rows)}",
        f"- Extractions completed: {len(results)}  (reused {skip_existing}, fresh {len(fresh)})",
        f"- Fresh wall time: {elapsed_total/60:.1f} min",
        f"- Fresh cost: ${total_cost:.2f}",
        f"- Citations returned: {total_returned}",
        f"- Citations valid: {total_valid}",
        f"- Citations hallucinated: {total_halluc}  ({halluc_rate:.1f}%)",
        f"- Median opinion size: {median_chars:,} chars",
        f"- Timeouts: {len(timeouts)}",
        f"- Other errors: {len([r for r in errored if 'TIMEOUT' not in r['error']])}",
        "",
        "## By level",
        "",
        "| level | n | total_valid | total_halluc | halluc_rate |",
        "|---|---|---|---|---|",
    ]
    by_level: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_level.setdefault(r["level"], []).append(r)
    for lv, rs in sorted(by_level.items()):
        tv = sum(r["n_valid"] for r in rs)
        th = sum(r["n_halluc"] for r in rs)
        tot = sum(r["n_total"] for r in rs)
        lines.append(f"| {lv} | {len(rs)} | {tv} | {th} | "
                     f"{100*th/tot if tot else 0:.1f}% |")

    if timeouts:
        lines.append("")
        lines.append("## Timeouts (failed extractions)")
        lines.append("")
        for r in timeouts:
            lines.append(f"- {r['cluster_id']}  {r['court_id']}  "
                         f"{r['char_count']:,}c  {r['case_name'] or ''}")

    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {SUMMARY_MD}")

    print(f"\nTotal wall time: {elapsed_total/60:.1f} min")
    print(f"Fresh extractions: {len(fresh)}, reused: {skip_existing}")
    print(f"Timeouts: {len(timeouts)}, other errors: "
          f"{len([r for r in errored if 'TIMEOUT' not in r['error']])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
