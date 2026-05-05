"""Aggregate results.csv into a per-model leaderboard with bootstrap CIs.

CLI: --dedupe to drop duplicate (proposition, gold_cite) cells before
aggregating. The v1 raw mining pass produced ~10x duplication of each
parenthetical inside the source opinion (eyecite extracting the same
citation in multiple forms); the sampled 200-row dataset retained 35%
duplicates as a result. Dedup recomputes headline numbers on the unique
~130 propositions per model. Output goes to scorecards-deduped.md.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "results.csv"
DATASET = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "dataset.csv"
OUT = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "scorecards.md"
OUT_DEDUPED = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "scorecards-deduped.md"

MODELS = ["sonnet", "opus", "gpt-5"]


def canonical_dataset_ids() -> set[str]:
    """Return the set of dataset row IDs to keep after deduplicating on
    (proposition, gold_cite). For each unique pair, the first-seen row
    is canonical."""
    ds_rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    seen: dict[tuple[str, str], str] = {}
    for r in ds_rows:
        key = (r["proposition"], r["gold_cite"])
        if key not in seen:
            seen[key] = r["id"]
    return set(seen.values())


def green_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("supports") == "Green") / len(rows)


def hallucination_rate(rows: list[dict]) -> float:
    """% of answered (non-UNKNOWN) responses that are not real or wrong-name."""
    answered = [r for r in rows
                if not r.get("model_response", "").strip().upper().startswith("UNKNOWN")]
    if not answered:
        return 0.0
    bad = sum(1 for r in answered if r.get("real") != "Y" or r.get("name_match") != "Y")
    return bad / len(answered)


def unknown_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows
               if r.get("model_response", "").strip().upper().startswith("UNKNOWN")
               ) / len(rows)


def right_case_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("right_case") == "Y") / len(rows)


def bootstrap_diff(rows_a: list[dict], rows_b: list[dict],
                   metric: Callable[[list[dict]], float],
                   n: int = 5000, seed: int = 42) -> tuple[float, float]:
    """95% percentile CI on metric(a) - metric(b) via 5000-sample bootstrap."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sa = [rng.choice(rows_a) for _ in range(len(rows_a))]
        sb = [rng.choice(rows_b) for _ in range(len(rows_b))]
        diffs.append(metric(sa) - metric(sb))
    diffs.sort()
    return (diffs[int(0.025 * n)], diffs[int(0.975 * n)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dedupe", action="store_true",
                    help="drop duplicate (proposition, gold_cite) cells "
                         "before aggregating; writes scorecards-deduped.md")
    args = ap.parse_args()

    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
    out_path = OUT
    title = "Case Law Retrieval Benchmark v1 — Scorecard"
    if args.dedupe:
        keep_ids = canonical_dataset_ids()
        before = len(rows)
        rows = [r for r in rows if r["id"] in keep_ids]
        out_path = OUT_DEDUPED
        title += " (deduped)"
        print(f"Dedup: {before} cells -> {len(rows)} (kept {len(keep_ids)} unique propositions)")
    by_model = {m: [r for r in rows if r["model"] == m] for m in MODELS}

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**N per model:** {min(len(rs) for rs in by_model.values())}  ")
    lines.append(f"**Models:** Sonnet 4.6, Opus 4.7, GPT-5  ")
    lines.append(f"**Eval mode:** closed-book  ")
    lines.append(f"**Substance assessor:** Opus 4.7")
    if args.dedupe:
        lines.append("")
        lines.append(f"**Note:** This scorecard runs on the deduplicated subset. The mining pass produced ~10x duplication of each parenthetical inside its source opinion (eyecite picking up the same citation in multiple forms), and 35% of the v1 dataset rows turned out to be duplicates of others. Numbers below run on the unique (proposition, gold_cite) cells only — N is per-model unique propositions, not the original 200.")
    lines.append("")
    lines.append("**Note:** GPT-5 ran with provider-default temperature (1) — "
                 "the API rejects temperature=0. Claude models also use provider")
    lines.append("default. Temperature comparability is a known caveat, not a")
    lines.append("comparability gate.")
    lines.append("")
    lines.append("## Per-model headlines")
    lines.append("")
    lines.append("| Model | % Green | Hallucination rate | UNKNOWN rate | Right-case rate |")
    lines.append("|---|---:|---:|---:|---:|")
    for m in MODELS:
        rs = by_model[m]
        lines.append(
            f"| {m} | {green_rate(rs):.1%} | {hallucination_rate(rs):.1%} "
            f"| {unknown_rate(rs):.1%} | {right_case_rate(rs):.1%} |"
        )
    lines.append("")
    lines.append("## Pairwise diffs (Green rate, 95% CI via 5000-sample bootstrap)")
    lines.append("")
    lines.append("| Pair | Green diff | 95% CI |")
    lines.append("|---|---:|---|")
    pairs = [("opus", "sonnet"), ("opus", "gpt-5"), ("sonnet", "gpt-5")]
    for a, b in pairs:
        diff = green_rate(by_model[a]) - green_rate(by_model[b])
        lo, hi = bootstrap_diff(by_model[a], by_model[b], green_rate)
        excl_zero = "**" if (lo > 0 or hi < 0) else ""
        lines.append(
            f"| {a} − {b} | {excl_zero}{diff*100:+.1f}pp{excl_zero} "
            f"| [{lo*100:+.1f}, {hi*100:+.1f}] |"
        )
    lines.append("")
    lines.append("Bold pairs have CI excluding zero (statistically distinguishable).")
    lines.append("")
    lines.append("## Per-district breakdown (Green rate)")
    lines.append("")
    courts = sorted({r["court"] for r in rows})
    header = "| Model | " + " | ".join(courts) + " |"
    lines.append(header)
    lines.append("|---|" + "|".join(["---:"] * len(courts)) + "|")
    for m in MODELS:
        cells = []
        for c in courts:
            sub = [r for r in by_model[m] if r["court"] == c]
            cells.append(f"{green_rate(sub):.1%}")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    # Force utf-8 stdout so Unicode minus (en-dash, Greek letters) prints
    # on Windows (default cp1252 chokes on −).
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # older Python; preview will skip non-ascii
    print(out_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
