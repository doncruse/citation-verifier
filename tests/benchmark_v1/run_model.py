"""Run one model on the benchmark dataset -> outputs_{model}.csv.

Idempotent: if outputs_{model}.csv exists with N rows, resumes from row N+1
based on which `id`s are already present. Mid-run interrupts don't lose
work.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_adapter import call_model, PROMPT_TEMPLATE  # noqa: E402

DATASET = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
TIMEOUT_S = 60


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=["sonnet", "opus", "gpt-5"])
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N rows (smoke test)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output CSV; defaults to benchmark_v1/outputs_{model}.csv")
    args = ap.parse_args()

    out = args.out or PROJECT_ROOT / "benchmark_v1" / f"outputs_{args.model.replace('-', '')}.csv"
    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]

    # Resume support — skip ids already in the output file.
    existing_ids: set[str] = set()
    if out.exists():
        existing_ids = {r["id"] for r in csv.DictReader(out.open(encoding="utf-8"))}
        print(f"Resuming: {len(existing_ids)} rows already done")

    fieldnames = [
        "id", "court", "proposition", "gold_name", "gold_cite",
        "model", "model_id", "model_response", "elapsed_s", "cost_usd",
        "input_tokens", "output_tokens", "stderr",
    ]
    write_header = not out.exists()
    print(f"Running model={args.model} on {len(rows)} prompts (skipping "
          f"{len(existing_ids)} already-done)")
    with out.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
        total_cost = 0.0
        for i, row in enumerate(rows, 1):
            if row["id"] in existing_ids:
                continue
            print(f"  [{i}/{len(rows)}] {args.model}/{row['id']}...",
                  end="", flush=True)
            prompt = PROMPT_TEMPLATE.format(proposition=row["proposition"])
            r = call_model(prompt, args.model, timeout_s=TIMEOUT_S)
            total_cost += r.get("cost_usd", 0) or 0
            preview = r["response"][:60].replace("\n", " ")
            print(f" {r['elapsed_s']}s | {preview}", flush=True)
            writer.writerow({
                "id": row["id"], "court": row["court"],
                "proposition": row["proposition"],
                "gold_name": row["gold_name"], "gold_cite": row["gold_cite"],
                "model": args.model,
                **r,
            })
            f.flush()
    print(f"\nWrote {out}; total notional cost ${total_cost:.2f}")


if __name__ == "__main__":
    main()
