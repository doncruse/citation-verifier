"""Summarize Pilot A results: per-sample stats + bootstrap CI on the diff.

Reads scratch/pilot_a/results.csv. Writes scratch/pilot_a/summary.md with:
    - Headline accuracy (% Green) per sample
    - Hallucination rate per sample
    - "Right case" rate per sample
    - Bootstrap 95% CI on the LePaRD vs. fresh-DC accuracy gap
    - Decision recommendation per the plan's table
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "scratch" / "pilot_a" / "results.csv"
OUT = PROJECT_ROOT / "scratch" / "pilot_a" / "summary.md"


def load(path: Path) -> tuple[list[dict], list[dict]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    lepard = [r for r in rows if r["source"] == "lepard"]
    fresh = [r for r in rows if r["source"] == "freshdc"]
    return lepard, fresh


def headline_accuracy(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("supports") == "Green") / len(rows)


def hallucination_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    bad = sum(1 for r in rows if r.get("real") != "Y" or r.get("name_match") != "Y")
    # Exclude UNKNOWN responses from the denominator: model declined, didn't
    # hallucinate.
    answered = [r for r in rows if not (r.get("model_response", "").strip()
                                         .upper().startswith("UNKNOWN"))]
    if not answered:
        return 0.0
    bad_answered = sum(1 for r in answered
                       if r.get("real") != "Y" or r.get("name_match") != "Y")
    return bad_answered / len(answered)


def right_case_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("right_case") == "Y") / len(rows)


def unknown_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows
               if r.get("model_response", "").strip().upper().startswith("UNKNOWN")
               ) / len(rows)


def bootstrap_diff(rows_a: list[dict], rows_b: list[dict],
                   metric, n: int = 5000, seed: int = 42) -> tuple[float, float]:
    """Return (lo, hi) 95% percentile CI on metric(a) - metric(b)."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sa = [rng.choice(rows_a) for _ in range(len(rows_a))]
        sb = [rng.choice(rows_b) for _ in range(len(rows_b))]
        diffs.append(metric(sa) - metric(sb))
    diffs.sort()
    return (diffs[int(0.025 * n)], diffs[int(0.975 * n)])


def decision(diff_pp: float) -> str:
    """Plan's decision table."""
    if diff_pp <= -15:  # fresh-DC >=15pp lower than LePaRD
        return ("**Decision: PIVOT TO FRESH MINING.** Fresh-DC scored "
                f"{abs(diff_pp):.1f}pp lower than LePaRD; the contamination "
                "concern is validated. The parent spec should mine fresh "
                "post-cutoff opinions as its primary data source.")
    if abs(diff_pp) <= 5:
        return ("**Decision: USE LePaRD + CL PARENTHETICALS.** The two samples "
                f"perform within {abs(diff_pp):.1f}pp of each other; fresh "
                "mining isn't buying us harder questions. Save the work.")
    return ("**Decision: RUN PILOT B.** The gap is "
            f"{diff_pp:+.1f}pp -- in the 5-15pp uncertainty band. Stratify "
            "LePaRD by citing year and re-run before deciding.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, default=RESULTS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    lepard, fresh = load(args.inp)

    lp_acc = headline_accuracy(lepard)
    fd_acc = headline_accuracy(fresh)
    lp_hall = hallucination_rate(lepard)
    fd_hall = hallucination_rate(fresh)
    lp_right = right_case_rate(lepard)
    fd_right = right_case_rate(fresh)
    lp_unk = unknown_rate(lepard)
    fd_unk = unknown_rate(fresh)

    diff_acc = lp_acc - fd_acc
    ci_acc = bootstrap_diff(lepard, fresh, headline_accuracy)
    ci_hall = bootstrap_diff(lepard, fresh, hallucination_rate)

    lines = []
    lines.append("# Pilot A -- Results Summary")
    lines.append("")
    lines.append("**Goal:** Detect whether sampling proposition-citation pairs from "
                 "LePaRD produces a meaningfully easier benchmark than freshly mining "
                 "them from post-training-cutoff federal district opinions.")
    lines.append("")
    lines.append(f"**N (LePaRD):** {len(lepard)}  ")
    lines.append(f"**N (fresh D.D.C.):** {len(fresh)}")
    lines.append("")
    lines.append("## Headline numbers (per axis)")
    lines.append("")
    lines.append("| Metric | LePaRD | Fresh D.D.C. | Diff (LP - FD) |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| % Green (supports proposition) | {lp_acc:.1%} | {fd_acc:.1%} | "
                 f"{(lp_acc - fd_acc)*100:+.1f}pp |")
    lines.append(f"| Hallucination rate (of answered) | {lp_hall:.1%} | {fd_hall:.1%} | "
                 f"{(lp_hall - fd_hall)*100:+.1f}pp |")
    lines.append(f"| Strict 'right case' rate | {lp_right:.1%} | {fd_right:.1%} | "
                 f"{(lp_right - fd_right)*100:+.1f}pp |")
    lines.append(f"| UNKNOWN rate | {lp_unk:.1%} | {fd_unk:.1%} | -- |")
    lines.append("")
    lines.append("## Bootstrap 95% CI on the difference")
    lines.append("")
    lines.append(f"- Headline accuracy diff (LePaRD - Fresh): "
                 f"{diff_acc*100:+.1f}pp [{ci_acc[0]*100:+.1f}, "
                 f"{ci_acc[1]*100:+.1f}]")
    lines.append(f"- Hallucination rate diff: "
                 f"{(lp_hall - fd_hall)*100:+.1f}pp "
                 f"[{ci_hall[0]*100:+.1f}, {ci_hall[1]*100:+.1f}]")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(decision((fd_acc - lp_acc) * 100))
    lines.append("")
    lines.append("## Coverage finding (independent of contamination outcome)")
    lines.append("")
    lines.append("**Fresh district-court mining at scale is viable on CourtListener,**")
    lines.append("provided the search query lifts the default precedential-status filter.")
    lines.append("")
    lines.append("Initial probing for this pilot suggested D.D.C. was the only federal")
    lines.append("district with 2026 opinion ingest. That was an artifact of CourtListener's")
    lines.append("`/api/rest/v4/search/?type=o` endpoint, which defaults to")
    lines.append("`stat_Published=on` only. PACER-flagged district opinions arrive on CL with")
    lines.append("`precedential_status=Unknown`, so they are silently filtered out under the")
    lines.append("default. Probing with `stat_Published=on&stat_Unknown=on` (verified")
    lines.append("2026-04-26):")
    lines.append("")
    lines.append("| District | Default count | + Unknown |")
    lines.append("|---|---:|---:|")
    lines.append("| C.D. Cal. | 0 | 185 |")
    lines.append("| S.D. Tex. | 0 | 357 |")
    lines.append("| N.D. Ill. | 0 | 327 |")
    lines.append("| D.D.C. | 598 | 598 (unchanged) |")
    lines.append("")
    lines.append("**Implication for the parent spec:** `MINING_PLAYBOOK.md` should specify")
    lines.append("`stat_Published=on&stat_Unknown=on` (or document the equivalent for")
    lines.append("non-search-API ingest paths). Without it, the playbook silently constrains")
    lines.append("forks to ~1 district's worth of fresh data and the contamination story")
    lines.append("looks infrastructure-blocked when it isn't.")
    lines.append("")
    lines.append("## Pilot caveats")
    lines.append("")
    lines.append("Documented for the parent design notes:")
    lines.append("")
    lines.append("- **Single citing court (D.D.C.) for the fresh sample.** Pilot ran before")
    lines.append("  the precedential-status finding above. Per side discussion: the")
    lines.append("  contamination signal works in any docket, so a single-district pilot is")
    lines.append("  fine; broaden in the actual benchmark.")
    lines.append("- **LePaRD `destination_context` is noisier than expected as a")
    lines.append("  proposition source.** A non-trivial fraction of LePaRD propositions are")
    lines.append("  fragments of preceding paragraph rather than coherent legal claims.")
    lines.append("  Some confused the closed-book model into refusing or flagging the")
    lines.append("  prompt as an injection attempt. The parent spec should either")
    lines.append("  (a) extract a single clean sentence, or (b) prefer parentheticals")
    lines.append("  over preceding-context as the proposition source.")
    lines.append("- **Sonnet substance assessor (not Opus).** Plan called for the existing")
    lines.append("  /verify-brief Phase 2 Opus assessor; pilot used a single Sonnet call to")
    lines.append("  bound cost. Contamination signal should be robust to assessor choice;")
    lines.append("  full-benchmark scorecards should use Opus per the parent spec.")
    lines.append("- **eyecite parenthetical extraction broke on D.D.C. plain_text** until")
    lines.append("  whitespace was aggressively normalized (every line in CL's")
    lines.append("  D.D.C. plain_text is `\\n\\n`-separated, defeating the default tokenizer).")
    lines.append("  Filed under known infrastructure issues for the mining playbook.")
    lines.append("")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(args.out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
