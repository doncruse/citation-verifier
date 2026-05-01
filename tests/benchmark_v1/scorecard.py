"""Aggregate results.csv into a per-model leaderboard with bootstrap CIs."""
from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "benchmark_v1" / "results.csv"
OUT = PROJECT_ROOT / "benchmark_v1" / "scorecards.md"

MODELS = ["sonnet", "opus", "gpt-5"]


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
    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
    by_model = {m: [r for r in rows if r["model"] == m] for m in MODELS}

    lines: list[str] = []
    lines.append("# Case Law Retrieval Benchmark v1 — Scorecard")
    lines.append("")
    lines.append(f"**N per model:** {min(len(rs) for rs in by_model.values())}  ")
    lines.append(f"**Models:** Sonnet 4.6, Opus 4.7, GPT-5  ")
    lines.append(f"**Eval mode:** closed-book  ")
    lines.append(f"**Substance assessor:** Opus 4.7")
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

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
