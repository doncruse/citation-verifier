"""
A/B test: sonnet vs haiku for citation extraction on 10 stratified
opinions from the post-floor manifest.

Question: does sonnet (per locked design) hold up now that the 25K cap
is enforced and the median opinion is ~13K chars? Or does haiku's
speed/cost win without meaningful quality loss?

Pilot context (LIMITATIONS.md): sonnet via `claude -p` hung on opinions
>~27K. Our cap is 25K so sonnet should run cleanly. extract_citations.py
defaulted to haiku as a pilot-era workaround.

For each of 10 opinions, run the extractor twice — once with each
model — and capture:
- elapsed_s
- cost_usd
- n citations returned
- n citations validated (substring in source)
- n hallucinated (not found in source)
- raw output JSON for spot-check

Output:
- ab_results.csv     one row per (opinion, model) pair
- ab_outputs/<cluster_id>__<model>.json    full extractor output

Note: claude -p runs at temp=1.0 (no flag exposed). Per-run variance
adds noise; N=10 may surface only large quality deltas.

Sample stratification: 5 federal_trial (one per district), 2 state_colr
(mix), 3 state_iac (mix). Seed=42 for reproducibility.

Total estimated cost: ~$3 (20 extractions x ~$0.15 each).
Total estimated wall time: 20-60 min sequential.
"""
from __future__ import annotations

import csv
import json
import random
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
OUT_DIR = HERE / "ab_outputs"
OUT_CSV = HERE / "ab_results.csv"

MODELS = ["sonnet", "haiku"]
SEED = 42
TIMEOUT_S = 240  # tight timeout — fail fast if sonnet hangs


def pick_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stratified sample: 5 federal_trial (one per active district),
    2 state_colr (random), 3 state_iac (random)."""
    rng = random.Random(SEED)
    sample: list[dict[str, Any]] = []

    # 5 federal_trial: one per active district
    federal_by_court: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["level"] == "federal_trial":
            federal_by_court.setdefault(r["court_id"], []).append(r)
    # 5 active federal courts (nysd is zeroed)
    for court_id in sorted(federal_by_court.keys()):
        bucket = federal_by_court[court_id]
        sample.append(rng.choice(bucket))

    # 2 state_colr: random
    colr_rows = [r for r in rows if r["level"] == "state_colr"]
    sample.extend(rng.sample(colr_rows, min(2, len(colr_rows))))

    # 3 state_iac: random
    iac_rows = [r for r in rows if r["level"] == "state_iac"]
    sample.extend(rng.sample(iac_rows, min(3, len(iac_rows))))

    return sample


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    pool = pick_sample(rows)

    print(f"A/B test: {len(pool)} opinions x {len(MODELS)} models = {len(pool)*len(MODELS)} extractions")
    print(f"Models:   {MODELS}")
    print(f"Timeout:  {TIMEOUT_S}s per extraction")
    print(f"Out:      {OUT_DIR}")
    print()
    print("Sample:")
    for r in pool:
        print(f"  {r['cluster_id']:>10}  {r['court_id']:<14}  {r['level']:<14}  "
              f"{int(r['char_count']):>6,}c  {(r['case_name'] or '(no name)')[:50]}")
    print()

    results: list[dict[str, Any]] = []
    t_run = time.time()
    for i, r in enumerate(pool, 1):
        cid = int(r["cluster_id"])
        text = (OPDIR / f"{cid}.txt").read_text(encoding="utf-8")
        for model in MODELS:
            t0 = time.time()
            print(f"  [{i}/{len(pool)}] {cid}  model={model}...", end="", flush=True)
            out = extract_citations(text, model=model, timeout_s=TIMEOUT_S)
            valid, halluc = validate_citations(out["citations"], text)
            dt = time.time() - t0
            print(f" {out['elapsed_s']:>5.1f}s  ${out['cost_usd']:.4f}  "
                  f"total={len(out['citations']):>3}  valid={len(valid):>3}  "
                  f"halluc={len(halluc):>2}  "
                  f"{out['error'][:30] if out['error'] else 'OK'}")

            # Persist full output
            outfile = OUT_DIR / f"{cid}__{model}.json"
            outfile.write_text(json.dumps({
                "cluster_id": cid,
                "court_id": r["court_id"],
                "level": r["level"],
                "case_name": r["case_name"],
                "char_count": int(r["char_count"]),
                "model": model,
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
                "model": model,
                "elapsed_s": out["elapsed_s"],
                "cost_usd": out["cost_usd"],
                "n_total": len(out["citations"]),
                "n_valid": len(valid),
                "n_halluc": len(halluc),
                "error": out["error"] or "",
            })

    # CSV
    fields = list(results[0].keys())
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"\nwrote {OUT_CSV}")

    # Aggregate summary by model
    print("\n=== AGGREGATE BY MODEL ===")
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)

    print(f"  {'model':<10} {'opinions':>10} {'total_s':>10} {'avg_s':>8} {'total_$':>10}"
          f" {'avg_$':>10} {'tot_cite':>10} {'tot_valid':>10} {'tot_halluc':>10}"
          f" {'errors':>8}")
    for model, rs in by_model.items():
        n = len(rs)
        total_s = sum(r["elapsed_s"] for r in rs)
        total_cost = sum(r["cost_usd"] for r in rs)
        total_cite = sum(r["n_total"] for r in rs)
        total_valid = sum(r["n_valid"] for r in rs)
        total_halluc = sum(r["n_halluc"] for r in rs)
        errors = sum(1 for r in rs if r["error"])
        print(
            f"  {model:<10} {n:>10} {total_s:>10.1f} {total_s/n:>8.1f} "
            f"${total_cost:>9.4f} ${total_cost/n:>9.4f} "
            f"{total_cite:>10} {total_valid:>10} {total_halluc:>10} "
            f"{errors:>8}"
        )

    # Per-opinion side-by-side
    print("\n=== PER-OPINION SIDE-BY-SIDE ===")
    print(f"  {'cluster':>10} {'court':<12} {'chars':>6}  "
          f"{'son_s':>6} {'son_$':>8} {'son_n':>6} {'son_h':>6}  "
          f"{'hai_s':>6} {'hai_$':>8} {'hai_n':>6} {'hai_h':>6}  delta_n")
    seen: dict[int, dict[str, dict[str, Any]]] = {}
    for r in results:
        seen.setdefault(r["cluster_id"], {})[r["model"]] = r
    for cid in sorted(seen.keys()):
        son = seen[cid].get("sonnet")
        hai = seen[cid].get("haiku")
        if not son or not hai:
            continue
        delta_n = son["n_valid"] - hai["n_valid"]
        print(
            f"  {cid:>10} {son['court_id']:<12} {son['char_count']:>6,}  "
            f"{son['elapsed_s']:>6.1f} ${son['cost_usd']:>7.4f} {son['n_total']:>6} {son['n_halluc']:>6}  "
            f"{hai['elapsed_s']:>6.1f} ${hai['cost_usd']:>7.4f} {hai['n_total']:>6} {hai['n_halluc']:>6}  "
            f"{delta_n:+d}"
        )

    print(f"\nTotal A/B wall time: {(time.time()-t_run)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
