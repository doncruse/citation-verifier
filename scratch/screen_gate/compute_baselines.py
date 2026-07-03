"""Aggregate the baseline/ tree into per-doc metrics.csv and per-cell
median+MAD baselines.json. Cell = '<filer_type>__<doc_type>'.

Usage: python compute_baselines.py <baseline_root>
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys

from metrics import compute_metrics

FILERS = ["attorney", "pro_se"]
DOCTYPES = ["merits_brief", "pleading", "procedural_motion"]
CELLS = [f"{f}__{d}" for f in FILERS for d in DOCTYPES]

METRIC_KEYS = ["n_cites", "words", "cite_density", "parenthetical_richness",
               "string_cite_rate", "gerund_paren_rate", "has_toa",
               "proposition_repeat_rate", "cite_prop_cv"]
# has_toa is boolean -> excluded from median/MAD (reported as a rate separately)
NUMERIC_KEYS = [k for k in METRIC_KEYS if k != "has_toa"]


def mad(values):
    """Median absolute deviation."""
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    med = statistics.median(vals)
    return statistics.median([abs(v - med) for v in vals])


def cell_baseline(rows):
    """rows: per-doc metric dicts. -> {metric: {median, mad, n}} for numeric keys."""
    out = {}
    for k in NUMERIC_KEYS:
        vals = [float(r[k]) for r in rows if k in r]
        if not vals:
            continue
        out[k] = {"median": statistics.median(vals), "mad": mad(vals),
                  "n": len(vals)}
    return out


def load_manifest_rows(cell_dir):
    """Read every manifest-*.jsonl in a cell dir -> list of manifest dicts."""
    rows = []
    for fn in os.listdir(cell_dir):
        if fn.startswith("manifest-") and fn.endswith(".jsonl"):
            with open(os.path.join(cell_dir, fn), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
    return rows


def build(baseline_root):
    metric_rows, by_cell = [], {c: [] for c in CELLS}
    for cell in CELLS:
        cell_dir = os.path.join(baseline_root, cell)
        if not os.path.isdir(cell_dir):
            continue
        for man in load_manifest_rows(cell_dir):
            slug = man["slug"]
            txt_path = os.path.join(cell_dir, f"{slug}.txt")
            if not os.path.exists(txt_path):
                continue
            raw = open(txt_path, encoding="utf-8", errors="replace").read()
            m = compute_metrics(raw)
            row = {"slug": slug, "cell": cell,
                   "filer_type": man.get("filer_type", ""),
                   "doc_type": man.get("doc_type", ""), **m}
            metric_rows.append(row)
            by_cell[cell].append(m)

    baselines = {c: cell_baseline(rows) for c, rows in by_cell.items() if rows}

    with open(os.path.join(baseline_root, "metrics.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["slug", "cell", "filer_type",
                                           "doc_type"] + METRIC_KEYS)
        w.writeheader()
        w.writerows(metric_rows)
    with open(os.path.join(baseline_root, "baselines.json"), "w",
              encoding="utf-8") as fh:
        json.dump(baselines, fh, indent=2)
    return metric_rows, baselines


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    rows, bl = build(root)
    print(f"wrote metrics for {len(rows)} docs across {len(bl)} cells -> "
          f"{root}/metrics.csv, {root}/baselines.json")
    for cell in CELLS:
        n = sum(1 for r in rows if r["cell"] == cell)
        print(f"  {cell:28s}: {n}")
