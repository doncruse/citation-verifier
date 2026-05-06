"""Charts for the Rachel meeting (case-law benchmark walkthrough).

Generates 5 PNGs in this directory. Each chart is sized for slide / chat
sharing (10x6, 150 dpi). Run from repo root:

    python benchmark/scratch/rachel-meeting/generate_charts.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).parent

# Consistent model colors across charts
COLORS = {
    "Sonnet 4.6": "#E89A3C",   # amber
    "Opus 4.7":   "#7B5EA7",   # violet
    "GPT-5":      "#3D9970",   # green
    "Haiku 4.5":  "#6CB4EE",   # light blue
    "Human":      "#888888",   # gray
}

plt.rcParams.update({
    "font.size": 12,
    "axes.titlesize": 15,
    "axes.titleweight": "bold",
    "axes.labelsize": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.facecolor": "white",
})


def chart1_v1_scorecard():
    """v1 headline: % Green, hallucination rate, UNKNOWN rate per model."""
    models = ["Sonnet 4.6", "Opus 4.7", "GPT-5"]
    pct_green = [31.5, 36.2, 46.2]
    halluc = [12.9, 20.0, 16.5]
    unknown = [52.3, 26.9, 6.9]

    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    metrics = [
        ("% Green (correct)", pct_green, "% of 130 propositions"),
        ("Hallucination rate", halluc, "% of named cases that are fake"),
        ("UNKNOWN rate", unknown, "% of model responses with no case"),
    ]
    for ax, (title, vals, ylabel) in zip(axes, metrics):
        bars = ax.bar(models, vals, color=[COLORS[m] for m in models], width=0.6)
        ax.set_title(title)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_ylim(0, max(60, max(vals) * 1.15))
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 1, f"{v}%",
                    ha="center", va="bottom", fontsize=11, fontweight="bold")
        ax.tick_params(axis="x", labelsize=10)

    fig.suptitle(
        "v1 results: closed-book case-finding on 130 propositions (deduped)",
        fontsize=15, fontweight="bold", y=1.02,
    )
    fig.text(0.5, -0.04,
             "Sonnet's low hallucination rate is partly a denominator effect — its 52% UNKNOWN excludes most responses from the tally.",
             ha="center", fontsize=9, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "01_v1_scorecard.png")
    plt.close(fig)


def chart2_calibration():
    """v1.1 calibration: Sonnet/Haiku vs Opus at 20K, against the bar."""
    metrics = ["Overall\nagreement", "Red recall", "Red precision", "Cohen's κ"]
    sonnet = [68.9, 52.2, 87.8, 0.50]
    haiku = [65.4, 55.1, 67.9, 0.41]

    # Two side-by-side panels: % metrics on left, kappa on right
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5),
                                    gridspec_kw={"width_ratios": [3, 1]})

    x = np.arange(3)
    width = 0.35
    bar1 = ax1.bar(x - width/2, sonnet[:3], width, label="Sonnet 4.6",
                   color=COLORS["Sonnet 4.6"])
    bar2 = ax1.bar(x + width/2, haiku[:3], width, label="Haiku 4.5",
                   color=COLORS["Haiku 4.5"])
    ax1.set_xticks(x)
    ax1.set_xticklabels(metrics[:3])
    ax1.set_ylabel("%")
    ax1.set_ylim(0, 100)
    ax1.set_title("Agreement metrics vs. Opus assessor (n=514)")

    # Bar lines: 90% overall, 85% Red recall
    ax1.axhline(90, xmin=0.02, xmax=0.34, color="red", linestyle="--",
                linewidth=1.5, alpha=0.7)
    ax1.text(0, 92, "90% bar", color="red", fontsize=9)
    ax1.axhline(85, xmin=0.36, xmax=0.68, color="red", linestyle="--",
                linewidth=1.5, alpha=0.7)
    ax1.text(1, 87, "85% bar", color="red", fontsize=9)

    for bars in [bar1, bar2]:
        for bar in bars:
            v = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2, v + 1.5, f"{v:.1f}",
                     ha="center", fontsize=9)

    ax1.legend(loc="lower right")

    # Kappa panel
    ax2.bar(["Sonnet 4.6", "Haiku 4.5"], [sonnet[3], haiku[3]],
            color=[COLORS["Sonnet 4.6"], COLORS["Haiku 4.5"]], width=0.5)
    ax2.set_title("Cohen's κ")
    ax2.set_ylim(0, 1.0)
    ax2.axhline(0.81, color="green", linestyle=":", linewidth=1, alpha=0.5)
    ax2.text(1.5, 0.83, "near-perfect", fontsize=8, color="green", ha="right")
    ax2.axhline(0.61, color="orange", linestyle=":", linewidth=1, alpha=0.5)
    ax2.text(1.5, 0.63, "substantial", fontsize=8, color="orange", ha="right")
    for i, v in enumerate([sonnet[3], haiku[3]]):
        ax2.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=10,
                 fontweight="bold")
    ax2.tick_params(axis="x", labelsize=9)

    fig.suptitle(
        "v1.1 calibration: cheaper-assessor candidates failed the bar (at 20K-truncated input)",
        fontsize=14, fontweight="bold", y=1.01,
    )
    fig.text(0.5, -0.05,
             "Conclusion: Opus stays as primary assessor. But measured at 20K-truncated input — see truncation experiment.",
             ha="center", fontsize=9, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "02_v1_1_calibration.png")
    plt.close(fig)


def chart3_truncation():
    """Truncation experiment: % of v1 Reds that flip at 60K, by model + tier."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: by model — corrected Green rate (20K vs 60K)
    models = ["Sonnet 4.6", "Opus 4.7", "GPT-5"]
    green_20k = [31.5, 36.2, 46.2]
    green_60k = [31.5, 39.3, 52.4]
    x = np.arange(len(models))
    w = 0.35
    bar1 = ax1.bar(x - w/2, green_20k, w, label="At 20K",
                   color=[COLORS[m] for m in models], alpha=0.55, edgecolor="black")
    bar2 = ax1.bar(x + w/2, green_60k, w, label="At 60K",
                   color=[COLORS[m] for m in models], edgecolor="black")
    ax1.set_xticks(x)
    ax1.set_xticklabels(models, fontsize=10)
    ax1.set_ylabel("% Green")
    ax1.set_ylim(0, 65)
    ax1.set_title("Per-model corrected Green rate (full opinion text)")
    for bars in [bar1, bar2]:
        for bar in bars:
            v = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2, v + 0.8, f"{v:.1f}%",
                     ha="center", fontsize=9)
    ax1.legend(loc="upper left")

    # Right: by tier — Reds flip rate (excl. SKIPs; raw data from
    # benchmark/releases/v1/truncation_experiment_60k.csv).
    tiers = ["SCOTUS", "Circuit", "District"]
    flip_pct = [43, 41, 0]
    flip_n = [(3, 7), (16, 39), (0, 8)]
    bars = ax2.bar(tiers, flip_pct, color=["#7B5EA7", "#5fa8d3", "#888"],
                   width=0.55, edgecolor="black")
    ax2.set_ylabel("% of Reds that flipped")
    ax2.set_title("Reds flipping by court tier (60K re-assessment)")
    ax2.set_ylim(0, 60)
    for bar, v, (k, n) in zip(bars, flip_pct, flip_n):
        # Percentage above the bar
        ax2.text(bar.get_x() + bar.get_width()/2, v + 2, f"{v}%",
                 ha="center", fontsize=11, fontweight="bold")
        # n-fraction inside the bar if there's room, else just below the % label
        if v > 8:
            ax2.text(bar.get_x() + bar.get_width()/2, v / 2, f"({k}/{n})",
                     ha="center", fontsize=9, color="white")
        else:
            ax2.text(bar.get_x() + bar.get_width()/2, v + 6, f"({k}/{n})",
                     ha="center", fontsize=9, color="#555")

    fig.suptitle(
        "v1.1 truncation re-test: 22 of 59 v1 Reds (37%) flipped to Green/Yellow at 60K",
        fontsize=14, fontweight="bold", y=1.01,
    )
    fig.text(0.5, -0.04,
             "20K window was hiding supporting passages in 37% of long opinions. SCOTUS and circuit Reds flip at the same rate — knowledge effect, not syllabus artifact.",
             ha="center", fontsize=9, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "03_truncation_experiment.png")
    plt.close(fig)


def chart4_sonnet_ft():
    """Gold-pair self-score: Sonnet@FT vs Haiku@FT vs Opus@20K reference (117 pairs)."""
    fig, ax = plt.subplots(figsize=(11, 5.5))

    assessors = ["Opus 4.7\n@ 20K", "Sonnet 4.6\n@ full text", "Haiku 4.5\n@ full text"]
    green = [71.8, 90.6, 41.9]
    yellow = [9.4, 5.1, 3.4]
    red = [18.8, 4.3, 54.7]

    x = np.arange(len(assessors))
    w = 0.6
    p1 = ax.bar(x, green, w, label="Green (supports)", color="#3D9970",
                edgecolor="black")
    p2 = ax.bar(x, yellow, w, bottom=green, label="Yellow (partial / dicta)",
                color="#FFC107", edgecolor="black")
    p3 = ax.bar(x, red, w, bottom=[g+y for g, y in zip(green, yellow)],
                label="Red (no support)", color="#D62728", edgecolor="black")

    ax.set_xticks(x)
    ax.set_xticklabels(assessors, fontsize=11)
    ax.set_ylabel("% of 117 v1 gold pairs")
    ax.set_ylim(0, 100)
    ax.set_title("Gold-pair self-score: assessor verdicts on parenthetical-supplied gold pairs")
    ax.legend(loc="upper right", framealpha=0.95)

    for i in range(len(assessors)):
        ax.text(i, green[i]/2, f"{green[i]:.1f}%", ha="center",
                color="white", fontsize=10, fontweight="bold")
        if yellow[i] > 4:
            ax.text(i, green[i] + yellow[i]/2, f"{yellow[i]:.1f}%",
                    ha="center", fontsize=9)
        if red[i] > 4:
            ax.text(i, green[i] + yellow[i] + red[i]/2, f"{red[i]:.1f}%",
                    ha="center", color="white", fontsize=10, fontweight="bold")

    # Annotation: bar for assessor candidacy
    ax.axhline(90, xmin=0, xmax=1, color="black", linestyle=":", linewidth=1, alpha=0.4)
    ax.text(2.4, 91, "90% Green target", fontsize=8.5, color="#444", ha="right")

    fig.text(0.5, -0.03,
             "Sonnet at full text matches expected Opus@FT performance — leading v2 assessor candidate at ~5× lower cost. Haiku ruled out.",
             ha="center", fontsize=9, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "04_sonnet_ft_gold_pairs.png")
    plt.close(fig)


def chart5_stratification():
    """v1 actual cited-tier distribution vs v1.3 target."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    tiers = ["SCOTUS", "Federal\nCOA", "Federal\nDistrict", "State /\nOther"]
    v1_actual = [19, 60, 9, 12]
    v1_3_target = [25, 25, 25, 25]
    colors = ["#7B5EA7", "#5fa8d3", "#888888", "#E89A3C"]

    x = np.arange(len(tiers))
    bars1 = ax1.bar(x, v1_actual, color=colors, edgecolor="black", width=0.65)
    ax1.set_xticks(x)
    ax1.set_xticklabels(tiers, fontsize=10)
    ax1.set_ylabel("% of cited cases")
    ax1.set_ylim(0, 70)
    ax1.set_title("v1 actual: cited-case distribution\n(driven by what districts cite, not by design)")
    for bar, v in zip(bars1, v1_actual):
        ax1.text(bar.get_x() + bar.get_width()/2, v + 1, f"{v}%",
                 ha="center", fontsize=11, fontweight="bold")

    bars2 = ax2.bar(x, v1_3_target, color=colors, edgecolor="black", width=0.65)
    ax2.set_xticks(x)
    ax2.set_xticklabels(tiers, fontsize=10)
    ax2.set_ylabel("% of cited cases")
    ax2.set_ylim(0, 70)
    ax2.set_title("v1.3 target: stratified 25/25/25/25\n(state contingent on smoke test)")
    for bar, v in zip(bars2, v1_3_target):
        ax2.text(bar.get_x() + bar.get_width()/2, v + 1, f"{v}%",
                 ha="center", fontsize=11, fontweight="bold")

    fig.suptitle(
        "Stratification fix: v1 was 60% circuit by accident; v1.3 stratifies by design",
        fontsize=14, fontweight="bold", y=1.01,
    )
    fig.text(0.5, -0.04,
             "v1 hint that district-case retrieval is much harder (Sonnet 0/0, Opus 1/5 Green, GPT-5 0/9 Green) is buried in low n. v1.3 fixes that.",
             ha="center", fontsize=9, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(OUT / "05_stratification.png")
    plt.close(fig)


if __name__ == "__main__":
    print("Generating charts...")
    chart1_v1_scorecard()
    chart2_calibration()
    chart3_truncation()
    chart4_sonnet_ft()
    chart5_stratification()
    pngs = sorted(OUT.glob("*.png"))
    print(f"Wrote {len(pngs)} charts:")
    for p in pngs:
        print(f"  {p.relative_to(Path.cwd())}")
