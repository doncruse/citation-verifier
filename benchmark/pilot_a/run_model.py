"""Run Claude Sonnet 4.6 closed-book on Pilot A prompts.

Loads both lepard_sample.csv and fresh_dc_sample.csv, runs the standardized
prompt template once per row through `claude -p`, and writes raw outputs to
benchmark/pilot_a/model_outputs.csv.

Uses the `claude -p` subprocess pattern from tests/ab_test_runner.py to keep
authentication and infra consistent with the rest of the repo.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# IMPORTANT: claude -p reads CLAUDE.md from cwd. Running it inside this
# repo means the model loads "Citation Verifier - tool that catches
# hallucinated citations" as project context, which causes it to refuse
# the task ("you're a citation verifier, you shouldn't generate citations").
# We run from a hermetic temp dir to bypass that.
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="pilot_a_hermetic_"))

LEPARD = PROJECT_ROOT / "benchmark" / "pilot_a" / "lepard_sample.csv"
FRESH = PROJECT_ROOT / "benchmark" / "pilot_a" / "fresh_dc_sample.csv"
OUT = PROJECT_ROOT / "benchmark" / "pilot_a" / "model_outputs.csv"

PROMPT_TEMPLATE = """You are a legal research assistant. I will give you a legal proposition.
Name a US federal case that supports it.

Respond ONLY with the case name and citation, in this format:
<Case Name>, <Volume> <Reporter> <Page> (<Court> <Year>)

Do not include any explanation, parenthetical, or commentary. If you do
not know a supporting case, respond with "UNKNOWN".

Proposition: {proposition}"""

# Sonnet 4.6 per the plan ("matches what's already wired in client.py" --
# kept here even though Opus 4.7 is current; the contamination signal is
# what we want, not the absolute best model).
MODEL = "sonnet"
TIMEOUT_S = 60


def load_rows(path: Path, source_label: str) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["_source"] = source_label
            rows.append(row)
    return rows


def call_model(proposition: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(proposition=proposition)
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", MODEL,
    ]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=TIMEOUT_S, cwd=str(_HERMETIC_DIR),
        )
        elapsed = time.time() - start
        try:
            payload = json.loads(proc.stdout.strip())
            response = payload.get("result", proc.stdout)
            cost = payload.get("total_cost_usd", 0)
            usage = payload.get("usage", {})
        except json.JSONDecodeError:
            response = proc.stdout
            cost = 0
            usage = {}
        return {
            "model_response": (response or "").strip(),
            "elapsed_s": round(elapsed, 1),
            "cost_usd": cost,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "stderr": proc.stderr[:500] if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "model_response": "",
            "elapsed_s": TIMEOUT_S,
            "cost_usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "stderr": "TIMEOUT",
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="run only first N rows total (for smoke testing)")
    ap.add_argument("--smoke", action="store_true",
                    help="alias for --limit 5 (with one from each source)")
    ap.add_argument("--out", type=Path, default=OUT,
                    help="output CSV path (default: model_outputs.csv)")
    args = ap.parse_args()

    rows = []
    rows.extend(load_rows(LEPARD, "lepard"))
    rows.extend(load_rows(FRESH, "freshdc"))

    if args.smoke:
        # 3 from each source for smoke test
        lp = [r for r in rows if r["_source"] == "lepard"][:3]
        fd = [r for r in rows if r["_source"] == "freshdc"][:3]
        rows = lp + fd
    elif args.limit:
        rows = rows[: args.limit]

    print(f"Running model on {len(rows)} prompts (model={MODEL})")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "id", "source", "proposition", "gold_name", "gold_cite",
        "citing_court", "citing_year", "cited_year",
        "model_response", "elapsed_s", "cost_usd",
        "input_tokens", "output_tokens", "stderr",
    ]
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        total_cost = 0.0
        for i, row in enumerate(rows, 1):
            print(f"  [{i}/{len(rows)}] {row['_source']}/{row['id']}...",
                  end="", flush=True)
            result = call_model(row["proposition"])
            total_cost += result.get("cost_usd", 0) or 0
            preview = result["model_response"][:80].replace("\n", " ")
            print(f" {result['elapsed_s']}s | ${result['cost_usd']:.4f} "
                  f"| {preview}", flush=True)
            writer.writerow({
                "id": row["id"],
                "source": row["_source"],
                "proposition": row["proposition"],
                "gold_name": row.get("gold_name", ""),
                "gold_cite": row.get("gold_cite", ""),
                "citing_court": row.get("citing_court", ""),
                "citing_year": row.get("citing_year", ""),
                "cited_year": row.get("cited_year", ""),
                **result,
            })
            f.flush()

    print(f"\nWrote {args.out}")
    print(f"Total cost: ${total_cost:.2f}")


if __name__ == "__main__":
    main()
