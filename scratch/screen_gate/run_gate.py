"""Gate runner for the Tier-0 screening battery (PROJECT.md §6).

Runs signal_battery.screen() over the full bad + control corpus, tags each
document with its filer stratum, and reports per-signal precision/recall
*within each stratum*. The ship rule (PROJECT.md §6.3): a signal graduates to
src/ only if it separates bad from control WITHIN a stratum — a signal that
fires on half the human control briefs of the same shape is noise.

The corpus physically lives in us-legal-research today (PROJECT.md open
decision #1 — migration into CV is recommended but not yet done); this runner
reads it in place via CORPUS_ROOT. Point it elsewhere once the corpus migrates.

Usage:
    python run_gate.py            # full table to stdout
    python run_gate.py --json     # machine-readable per-document + summary
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from signal_battery import screen, SIGNALS

CORPUS_ROOT = os.environ.get(
    "SCREEN_GATE_CORPUS",
    r"C:\Users\Rebecca Fordon\Projects\us-legal-research\evals\corpora\suspect-briefs",
)

SIGNAL_NAMES = [
    "court_contradiction", "authority_drift", "statute_grammar",
    "arithmetic", "style_variance", "toa_body_diff",
]

# Corpus definition: (label, filer_type, relative_path).
# label = bad | control. filer_type = attorney | pro_se.
# Stratum labels sourced from PROJECT.md §4 and the retrieval manifests.
CORPUS = [
    # --- bad, attorney ---
    ("bad", "attorney", "bad/support-community-mph--cand-63.md"),
    ("bad", "attorney", "bad/tantaros-fox-news.txt"),
    ("bad", "attorney", "bad/tantaros-fox-news-surreply.txt"),
    ("bad", "attorney", "bad/withers-aberdeen.txt"),
    ("bad", "attorney", "bad/villalovos-vandepol.txt"),
    ("bad", "attorney", "bad/johnson-dunn.txt"),
    ("bad", "attorney", "bad/braun-day.txt"),
    # --- bad, pro se ---
    ("bad", "pro_se", "bad/reed-community-health.txt"),
    ("bad", "pro_se", "bad/stafford-taffet.txt"),
    ("bad", "pro_se", "bad/sherwood-botetourt.txt"),
    ("bad", "pro_se", "bad/burnside-verdick.txt"),
    # --- control, attorney ---
    ("control", "attorney", "control/ctrl-cand-msj.txt"),
    ("control", "attorney", "control/ctrl-nysd-mtd-opp.txt"),
    ("control", "attorney", "control/ctrl-nysd-reply.txt"),
    ("control", "attorney", "control/ctrl-msnd-msj.txt"),
    # --- control, pro se ---
    ("control", "pro_se", "control/ctrl-wawd-prose-resp.txt"),
    ("control", "pro_se", "control/ctrl-ord-prose-resp.txt"),
    ("control", "pro_se", "control/ctrl-vawd-prose-compl.txt"),
]


def run():
    docs = []
    for label, filer, rel in CORPUS:
        path = os.path.join(CORPUS_ROOT, rel)
        if not os.path.exists(path):
            docs.append({"slug": os.path.basename(rel), "label": label,
                         "filer": filer, "missing": True})
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            r = screen(fh.read())
        docs.append({
            "slug": os.path.basename(rel).rsplit(".", 1)[0],
            "label": label, "filer": filer,
            "n_cites": r["n_cites_extracted"],
            "n_flags": r["n_flags"],
            "signals_fired": r["signals_fired"],
        })
    return docs


def summarize(docs):
    """Per-signal x per-stratum firing counts and rates."""
    strata = [("bad", "attorney"), ("control", "attorney"),
              ("bad", "pro_se"), ("control", "pro_se")]
    totals = {k: sum(1 for d in docs if not d.get("missing")
                     and (d["label"], d["filer"]) == k) for k in strata}
    table = {}
    for sig in SIGNAL_NAMES:
        row = {}
        for k in strata:
            fired = sum(1 for d in docs if not d.get("missing")
                        and (d["label"], d["filer"]) == k
                        and sig in d["signals_fired"])
            row[k] = fired
        table[sig] = row
    return strata, totals, table


def print_report(docs):
    strata, totals, table = summarize(docs)

    print("=" * 78)
    print("SCREEN GATE — Tier-0 battery, per-stratum separation")
    print("=" * 78)
    missing = [d for d in docs if d.get("missing")]
    if missing:
        print(f"\n[!] MISSING {len(missing)} corpus file(s): "
              + ", ".join(d["slug"] for d in missing))

    print("\nCorpus counts (present):")
    for k in strata:
        print(f"  {k[0]:8s} {k[1]:9s}: {totals[k]}")

    print("\nPer-document flags:")
    print(f"  {'slug':34s} {'label':8s} {'filer':9s} {'cites':>5s} "
          f"{'flags':>5s}  signals")
    for d in docs:
        if d.get("missing"):
            print(f"  {d['slug']:34s} {d['label']:8s} {d['filer']:9s}  "
                  f"  MISSING")
            continue
        print(f"  {d['slug']:34s} {d['label']:8s} {d['filer']:9s} "
              f"{d['n_cites']:>5d} {d['n_flags']:>5d}  "
              f"{','.join(d['signals_fired'])}")

    print("\nPer-signal firing (fired / stratum total):")
    hdr = f"  {'signal':20s}"
    for k in strata:
        hdr += f" {k[0][:3]}-{k[1][:4]:>4s}"
    print(hdr)
    for sig in SIGNAL_NAMES:
        line = f"  {sig:20s}"
        for k in strata:
            line += f" {table[sig][k]:>2d}/{totals[k]:<2d} "
        print(line)

    print("\nSeparation read (within stratum: recall on bad vs. FP on control):")
    for filer in ("attorney", "pro_se"):
        badk, ctrlk = ("bad", filer), ("control", filer)
        nb, nc = totals[badk], totals[ctrlk]
        print(f"\n  [{filer}]  bad={nb}  control={nc}")
        for sig in SIGNAL_NAMES:
            b, c = table[sig][badk], table[sig][ctrlk]
            recall = f"{b}/{nb}" if nb else "n/a"
            fp = f"{c}/{nc}" if nc else "n/a"
            verdict = ""
            if nb and nc:
                if b > 0 and c == 0:
                    verdict = "SEPARATES"
                elif b == 0:
                    verdict = "silent-on-bad"
                elif c > 0:
                    verdict = "FIRES-ON-CONTROL"
            print(f"    {sig:20s} recall={recall:6s} fp={fp:6s}  {verdict}")

    print("\n" + "=" * 78)
    print("Ship rule (PROJECT.md §6.3): graduate only signals that SEPARATE")
    print("within a stratum. Small-n — treat as directional, not final.")
    print("=" * 78)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    docs = run()
    if args.json:
        strata, totals, table = summarize(docs)
        print(json.dumps({
            "corpus_root": CORPUS_ROOT,
            "documents": docs,
            "totals": {f"{k[0]}/{k[1]}": v for k, v in totals.items()},
            "table": {sig: {f"{k[0]}/{k[1]}": v for k, v in row.items()}
                      for sig, row in table.items()},
        }, ensure_ascii=False, indent=2))
    else:
        print_report(docs)
