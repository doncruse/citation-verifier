"""Aggregate calibration_results.csv -> calibration.md.

Compute per-candidate-model:
- Overall agreement with Opus
- Confusion matrix vs Opus
- Per-class precision and recall (Opus = ground truth)
- Cohen's kappa
- Cost and elapsed time

Decision rule (per docs/plans/benchmark-roadmap.md v1.2):
    >=90% overall agreement AND >=85% on Red

The "85% on Red" line is read two ways and we report both:
  - Red recall: of Opus-Red cells, what % did the candidate also say Red?
  - Red precision: of candidate-Red cells, what % did Opus also say Red?
The roadmap's stated rationale (Reds = hallucinations) favors precision.
We use recall for the headline pass/fail (most natural reading of
"agreement on Red") and report precision alongside.

Running this script is idempotent and works on partial data, so it can
be re-run after each calibration batch finishes to watch progress.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = PROJECT_ROOT / "benchmark_v1"
IN_CSV = BENCH / "calibration_results.csv"
OUT_MD = BENCH / "calibration.md"

CLASSES = ["Green", "Yellow", "Red"]


def load_rows() -> list[dict]:
    if not IN_CSV.exists():
        return []
    return list(csv.DictReader(IN_CSV.open(encoding="utf-8")))


def per_model(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["candidate_model"]].append(r)
    return groups


def overall_agreement(rows: list[dict]) -> tuple[int, int]:
    """(matches, scorable) — only over rows with both verdicts present."""
    scorable = [r for r in rows if r["opus_verdict"] and r["candidate_verdict"]]
    matches = sum(1 for r in scorable if r["opus_verdict"] == r["candidate_verdict"])
    return matches, len(scorable)


def confusion_matrix(rows: list[dict]) -> dict[tuple[str, str], int]:
    cm: dict[tuple[str, str], int] = Counter()
    for r in rows:
        if r["opus_verdict"] and r["candidate_verdict"]:
            cm[(r["opus_verdict"], r["candidate_verdict"])] += 1
    return cm


def per_class_metrics(cm: dict[tuple[str, str], int]) -> dict[str, dict]:
    """For each class c: precision = TP / (TP + FP), recall = TP / (TP + FN)
    where TP = cm[(c, c)], FP = cm[(other, c)] summed, FN = cm[(c, other)] summed.
    """
    out: dict[str, dict] = {}
    for c in CLASSES:
        tp = cm.get((c, c), 0)
        fp = sum(cm.get((o, c), 0) for o in CLASSES if o != c)
        fn = sum(cm.get((c, o), 0) for o in CLASSES if o != c)
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        out[c] = {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec}
    return out


def cohen_kappa(cm: dict[tuple[str, str], int]) -> float | None:
    """Cohen's kappa between Opus and the candidate."""
    n = sum(cm.values())
    if not n:
        return None
    po = sum(cm.get((c, c), 0) for c in CLASSES) / n
    p_opus = {c: sum(cm.get((c, o), 0) for o in CLASSES) / n for c in CLASSES}
    p_cand = {c: sum(cm.get((o, c), 0) for o in CLASSES) / n for c in CLASSES}
    pe = sum(p_opus[c] * p_cand[c] for c in CLASSES)
    if pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def render_confusion_md(cm: dict[tuple[str, str], int]) -> str:
    """Render the 3x3 confusion matrix as a markdown table.
    Rows = Opus verdict; Columns = candidate verdict."""
    lines = ["| Opus \\\\ Candidate | " + " | ".join(CLASSES) + " | row total |",
             "|---" + "|---:" * (len(CLASSES) + 1) + "|"]
    for o in CLASSES:
        row_total = sum(cm.get((o, c), 0) for c in CLASSES)
        cells = [str(cm.get((o, c), 0)) for c in CLASSES]
        lines.append(f"| **{o}** | " + " | ".join(cells) + f" | {row_total} |")
    col_totals = [sum(cm.get((o, c), 0) for o in CLASSES) for c in CLASSES]
    grand = sum(col_totals)
    lines.append(
        "| **col total** | "
        + " | ".join(str(t) for t in col_totals)
        + f" | **{grand}** |"
    )
    return "\n".join(lines)


def fmt_pct(num: int, den: int) -> str:
    if not den:
        return "n/a"
    return f"{num / den:.1%} ({num}/{den})"


def fmt_metric(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1%}"


def render_report(rows: list[dict]) -> str:
    if not rows:
        return "# Calibration report\n\nNo calibration data yet.\n"

    sections: list[str] = []
    sections.append("# Assessor calibration — Sonnet 4.6 / Haiku 4.5 vs Opus 4.7\n")
    sections.append(
        "Compares Sonnet 4.6 and Haiku 4.5 substance-assessor verdicts "
        "against v1's published Opus 4.7 verdicts on the deduped 257-cell "
        "subset (canonical examples only). Direct API, `temperature=0`, "
        "same `ASSESSMENT_PROMPT` as v1.\n"
    )
    sections.append(
        "**Decision rule (from `benchmark-roadmap.md` v1.2):** overall "
        "agreement ≥ 90% AND Red recall ≥ 85% → candidate "
        "may replace Opus. Red precision is reported alongside per the "
        "roadmap's stated rationale (Reds are the hallucinations we catch).\n"
    )

    groups = per_model(rows)
    summary_rows: list[str] = []
    for model_name in sorted(groups):
        model_rows = groups[model_name]
        m, n = overall_agreement(model_rows)
        cm = confusion_matrix(model_rows)
        metrics = per_class_metrics(cm)
        kappa = cohen_kappa(cm)
        red = metrics["Red"]
        red_recall = red["recall"]
        red_precision = red["precision"]
        passes_overall = bool(n) and (m / n) >= 0.90
        passes_red = red_recall is not None and red_recall >= 0.85
        decision = "PASS" if (passes_overall and passes_red) else "FAIL"
        summary_rows.append(
            f"| {model_name} | {fmt_pct(m, n)} | {fmt_metric(red_recall)} | "
            f"{fmt_metric(red_precision)} | {fmt_metric(kappa)} | {decision} |"
        )

    sections.append("## Summary\n")
    sections.append(
        "| Model | Overall agreement | Red recall | Red precision | Cohen's κ | Decision |"
    )
    sections.append("|---|---|---:|---:|---:|---:|")
    sections.extend(summary_rows)

    for model_name in sorted(groups):
        model_rows = groups[model_name]
        sections.append(f"\n## {model_name}\n")
        n_total = len(model_rows)
        n_errored = sum(1 for r in model_rows if r.get("error"))
        n_no_verdict = sum(
            1 for r in model_rows if not r.get("candidate_verdict")
        )
        cm = confusion_matrix(model_rows)
        metrics = per_class_metrics(cm)
        kappa = cohen_kappa(cm)
        m, n = overall_agreement(model_rows)
        cost = sum(float(r.get("cost_usd") or 0) for r in model_rows)
        elapsed = sum(float(r.get("elapsed_s") or 0) for r in model_rows)

        sections.append(f"- Cells in calibration set: {n_total}")
        sections.append(f"- Errored: {n_errored}; missing verdict (parse fail): {n_no_verdict}")
        sections.append(f"- Scorable (both verdicts present): {n}")
        sections.append(f"- Overall agreement: {fmt_pct(m, n)}")
        sections.append(f"- Cohen's κ: {fmt_metric(kappa)}")
        sections.append(f"- API cost: ${cost:.2f}; total elapsed: {elapsed/60:.1f} min\n")

        sections.append("### Confusion matrix (Opus = rows; candidate = columns)\n")
        sections.append(render_confusion_md(cm))

        sections.append("\n### Per-class metrics\n")
        sections.append("| Class | Precision | Recall | TP | FP | FN |")
        sections.append("|---|---:|---:|---:|---:|---:|")
        for c in CLASSES:
            mc = metrics[c]
            sections.append(
                f"| **{c}** | {fmt_metric(mc['precision'])} | {fmt_metric(mc['recall'])} | "
                f"{mc['tp']} | {mc['fp']} | {mc['fn']} |"
            )

    sections.append(
        "\n---\n"
        "Generated by `tests/benchmark_v1/calibrate_assessor_report.py`. "
        "Re-run to refresh from `calibration_results.csv` (resume-safe).\n"
    )
    return "\n".join(sections) + "\n"


def main() -> int:
    rows = load_rows()
    md = render_report(rows)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Rows aggregated: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
