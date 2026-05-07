"""Sonnet@FT on the 22 v1 Reds that flipped at 60K with Opus.

The v1.3 design proposes Sonnet@FT (full opinion text, no cap) as the
default assessor. The 22 cells of interest are the ones identified by
the truncation experiment (`truncation_experiment_60k.csv`): v1 Reds
where Opus's verdict flipped to Green or Yellow when given a 60K window
instead of the original 20K.

Question for v1.3: on those 22 cells, does Sonnet@FT — the v1.3-proposed
default assessor — also reach the corrected verdict that Opus@60K reached?

This is a one-off probe of v1.3's central claim. It's deliberately narrow:
  - Only the 22 already-flipped cells.
  - Sonnet runs at full opinion text (no cap), per the v1.3 design's
    "default to no cap" rule and matching the 2026-05-04 full-text
    assessor comparison (`docs/retrospectives/2026-05-04-fulltext-assessor-comparison-and-mining-bugs.md`).
  - Opus's verdict is the existing 60K-window verdict from the
    truncation experiment. Comparison is therefore Sonnet@FT vs Opus@60K
    — different windows, but each represents the corresponding model's
    "best available read" in the artifact set.

Output: `benchmark/releases/v1/sonnet_at_ft_on_flipped_22.csv` with
columns suitable for side-by-side reading: gold info, opus_60k verdict
+ rationale, sonnet_ft verdict + rationale + chars assessed, agreement,
costs.

History: a 2026-05-07 first pass mistakenly capped Sonnet at 60K to
match Opus's window, which is the wrong artifact for the v1.3 question
(the design ships Sonnet at FT, not 60K). This file is the corrected
run; commit history has the prior version.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the truncation_experiment helpers (stdin-piped prompt to handle
# long opinion windows on Windows; see comments in that module).
from benchmark.runners.truncation_experiment import (  # noqa: E402
    call_assessor_stdin,
    tier_from_cite,
)
from benchmark.pilot_a.score import OPINIONS_CACHE  # noqa: E402

INPUT_CSV = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "truncation_experiment_60k.csv"
OUTPUT_CSV = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "sonnet_at_ft_on_flipped_22.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be processed, don't call assessor")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap rows processed (for smoke runs)")
    args = ap.parse_args()

    flipped = [
        r for r in csv.DictReader(INPUT_CSV.open(encoding="utf-8"))
        if r["flipped"] == "Y"
    ]
    print(f"Loaded {len(flipped)} flipped Red->Green/Yellow rows from "
          f"{INPUT_CSV.name}")

    # Resume support: skip ids already in OUTPUT_CSV
    done: set[tuple[str, str]] = set()
    if OUTPUT_CSV.exists():
        for r in csv.DictReader(OUTPUT_CSV.open(encoding="utf-8")):
            done.add((r["v1_model"], r["id"]))
        print(f"Resuming: {len(done)} rows already in {OUTPUT_CSV.name}")

    todo = [r for r in flipped if (r["model"], r["id"]) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"To process: {len(todo)} rows  |  window: full text (no cap)  |  model: sonnet")

    fieldnames = [
        "v1_model", "id", "court", "tier",
        "matched_cluster_id", "matched_cl_name",
        "gold_name", "gold_cite", "proposition",
        "opinion_chars_full",
        "v1_supports",            # Red (everything in this CSV)
        "opus_60k_supports", "opus_60k_rationale",  # Opus at 60K (truncation expt)
        "sonnet_ft_supports", "sonnet_ft_rationale",  # Sonnet at full text
        "sonnet_chars_assessed",  # equals opinion_chars_full when uncapped
        "agree",                  # Y if opus_60k == sonnet_ft
        "sonnet_cost_usd",
    ]

    if args.dry_run:
        for r in todo[:5]:
            cid = r["matched_cluster_id"]
            p = OPINIONS_CACHE / f"{cid}.txt"
            n = len(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else 0
            print(f"  [dry] {r['model']:6} {r['id']:25} cluster={cid:9} chars={n:>7,} "
                  f"opus->{r['new_supports']}  | {r['gold_cite'][:45]}")
        return

    write_header = not OUTPUT_CSV.exists()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    total_cost = 0.0
    agreements = 0
    with OUTPUT_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
            f.flush()

        for i, row in enumerate(todo, 1):
            cid = row["matched_cluster_id"]
            cache = OPINIONS_CACHE / f"{cid}.txt"
            if not cache.exists():
                print(f"  [{i}/{len(todo)}] {row['model']} {row['id']}: "
                      f"NO CACHE for cluster {cid}, skipping")
                continue
            full_text = cache.read_text(encoding="utf-8", errors="replace")
            n_full = len(full_text)
            # Full text, no cap. The Windows CreateProcess limit is sidestepped
            # by stdin-piping the prompt (see truncation_experiment.py).
            opinion_excerpt = full_text
            case_label = (
                f"{row['matched_cl_name'] or row['gold_name']}, "
                f"{row['extracted_citation']}"
            )
            print(f"  [{i}/{len(todo)}] v1={row['model']:6} {row['id']:25} "
                  f"opus@60K->{row['new_supports']:6} | {case_label[:50]} ({n_full:,}c)")

            a = call_assessor_stdin(
                row["proposition"], case_label, opinion_excerpt, model="sonnet",
            )
            new_supports = a.get("assessment") or ""
            cost = float(a.get("cost_usd") or 0.0)
            total_cost += cost
            agree = "Y" if new_supports == row["new_supports"] else "N"
            if agree == "Y":
                agreements += 1
            print(f"      sonnet@FT -> {new_supports:6} (agree={agree}) "
                  f"cost ${cost:.4f}, total ${total_cost:.2f}, agree {agreements}/{i}")

            writer.writerow({
                "v1_model": row["model"],
                "id": row["id"],
                "court": row["court"],
                "tier": row["tier"] or tier_from_cite(row["gold_cite"]),
                "matched_cluster_id": cid,
                "matched_cl_name": row["matched_cl_name"],
                "gold_name": row["gold_name"],
                "gold_cite": row["gold_cite"],
                "proposition": row["proposition"],
                "opinion_chars_full": n_full,
                "v1_supports": "Red",
                "opus_60k_supports": row["new_supports"],
                "opus_60k_rationale": row["new_rationale"],
                "sonnet_ft_supports": new_supports,
                "sonnet_ft_rationale": a.get("rationale", ""),
                "sonnet_chars_assessed": n_full,
                "agree": agree,
                "sonnet_cost_usd": cost,
            })
            f.flush()

    print()
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Sonnet@FT agreement with Opus@60K: {agreements}/{len(todo)} "
          f"({(agreements / len(todo) * 100) if todo else 0:.0f}%)  "
          f"cost ${total_cost:.2f}")


if __name__ == "__main__":
    main()
