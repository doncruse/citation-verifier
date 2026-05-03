"""Re-assess v1 Reds with a larger opinion truncation window.

Hypothesis: the v1 assessor reads only the first 20K chars (~5-7 pages) of
each cited opinion. Some Red verdicts may be truncation artifacts -- the
supporting passage lives later in the opinion. SCOTUS opinions almost
always have a syllabus near the front; circuit opinions sometimes have
headnotes (often stripped); district opinions essentially never. If the
SCOTUS-leans-easy pattern in Table 4 is partly a truncation artifact,
bumping the window should flip some Reds.

Method: re-run the same Opus assessor on each v1 Red, with the opinion
text expanded to MAX_OPINION_CHARS_NEW. Same prompt, same model, same
proposition -- only the truncation length changes. Skips Reds whose
cached opinion already fits in the original 20K window (no signal to
extract). Output is a sidecar CSV.

Resume-safe: re-running skips rows already in the output file.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Borrow the cache path + prompt template from pilot_a/score.py (same
# module v1 score.py uses). We intentionally do NOT use pilot_a's
# call_assessor: it passes the prompt as a CLI argument, which exceeds
# the ~32K Windows CreateProcess limit at 60K-char opinion windows.
_pilot_path = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
_spec = importlib.util.spec_from_file_location("pilot_a_score", _pilot_path)
_pilot = importlib.util.module_from_spec(_spec)
sys.modules["pilot_a_score"] = _pilot
_spec.loader.exec_module(_pilot)
ASSESSMENT_PROMPT = _pilot.ASSESSMENT_PROMPT
OPINIONS_CACHE = _pilot.OPINIONS_CACHE
MAX_OPINION_CHARS_OLD = _pilot.MAX_OPINION_CHARS  # 20_000
ASSESSOR_TIMEOUT = _pilot.ASSESSOR_TIMEOUT

MAX_OPINION_CHARS_NEW = 60_000  # 3x the v1 window, ~15K tokens
ASSESSOR_MODEL = "opus"          # match v1

# Bypass repo CLAUDE.md so the assessor isn't biased by project context
# (matches pilot_a/score.py's _HERMETIC_DIR pattern).
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="trunc_exp_"))


def call_assessor_stdin(proposition: str, case_name_citation: str,
                        opinion_text: str, model: str = ASSESSOR_MODEL) -> dict:
    """Same contract as pilot_a/score.py:call_assessor, but pipes the
    prompt to stdin instead of passing it as a CLI arg. Required for
    long opinion excerpts on Windows.
    """
    prompt = ASSESSMENT_PROMPT.format(
        proposition=proposition,
        case_name_citation=case_name_citation,
        opinion_text=opinion_text or "(opinion text unavailable)",
    )
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=ASSESSOR_TIMEOUT, cwd=str(_HERMETIC_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"assessment": None, "rationale": "TIMEOUT",
                "elapsed_s": ASSESSOR_TIMEOUT, "cost_usd": 0}
    elapsed = time.time() - start

    try:
        payload = json.loads(proc.stdout.strip())
        response = (payload.get("result") or "").strip()
        cost = payload.get("total_cost_usd", 0)
    except json.JSONDecodeError:
        response = proc.stdout.strip()
        cost = 0

    assessment = None
    rationale = ""
    try:
        match = re.search(r"\{[^{}]*assessment[^{}]*\}", response)
        if match:
            j = json.loads(match.group(0))
            assessment = j.get("assessment")
            rationale = j.get("rationale", "")
    except json.JSONDecodeError:
        pass
    if not assessment:
        for color in ("Red", "Yellow", "Green"):
            if color in response:
                assessment = color
                rationale = response[:200]
                break

    return {
        "assessment": assessment,
        "rationale": rationale,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": cost,
    }

RESULTS_IN = PROJECT_ROOT / "benchmark_v1" / "results.csv"
DATASET_IN = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
RESULTS_OUT = PROJECT_ROOT / "benchmark_v1" / f"truncation_experiment_{MAX_OPINION_CHARS_NEW // 1000}k.csv"


def deduped_keep_ids() -> set[str]:
    """Mirror scorecard.py --dedupe: keep first-seen row per
    (proposition, gold_cite) key, scanning dataset.csv in id order.
    Returns the set of dataset row ids to keep.
    """
    seen: dict[tuple[str, str], str] = {}
    for r in csv.DictReader(DATASET_IN.open(encoding="utf-8")):
        key = (r["proposition"], r["gold_cite"])
        if key not in seen:
            seen[key] = r["id"]
    return set(seen.values())


def tier_from_cite(gold_cite: str) -> str:
    """Coarse tier inference from the gold reporter."""
    c = gold_cite or ""
    if re.search(r"\bU\.?\s?S\.?\b", c) or "S. Ct." in c or "S.Ct." in c:
        return "SCOTUS"
    if re.search(r"\bF\.?\s?(2d|3d|4th)\b", c):
        return "Circuit"
    if "F. Supp." in c or "F.Supp." in c:
        return "District"
    return "Other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of rows processed (for smoke runs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be processed, don't call assessor")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="re-assess all 101 raw Reds, not just the 67 first-seen "
                         "rows that scorecard.py --dedupe keeps")
    args = ap.parse_args()

    # 1. Load v1 Reds. Default mirrors scorecard.py --dedupe: keep only the
    # first-seen row per (proposition, gold_cite). The report's headline
    # numbers (Tables 1-5) come from the deduped subset, so we want our
    # flip rate to apply to the same denominator.
    keep = None if args.no_dedupe else deduped_keep_ids()
    reds: list[dict] = []
    for r in csv.DictReader(RESULTS_IN.open(encoding="utf-8")):
        if r["supports"] != "Red" or not r["matched_cluster_id"]:
            continue
        if keep is not None and r["id"] not in keep:
            continue
        reds.append(r)
    label = "raw" if args.no_dedupe else "deduped"
    print(f"Loaded {len(reds)} Red rows from {RESULTS_IN.name} ({label})")

    # 2. Resume support
    done: set[tuple[str, str]] = set()
    if RESULTS_OUT.exists():
        for r in csv.DictReader(RESULTS_OUT.open(encoding="utf-8")):
            done.add((r["model"], r["id"]))
        print(f"Resuming: {len(done)} rows already in {RESULTS_OUT.name}")

    fieldnames = [
        "model", "id", "court", "tier",
        "matched_cluster_id", "matched_cl_name", "extracted_citation",
        "gold_name", "gold_cite", "proposition",
        "opinion_chars_full", "truncated_in_v1",
        "original_supports", "original_rationale",
        "new_supports", "new_rationale",
        "flipped", "cost_usd",
    ]

    write_header = not RESULTS_OUT.exists()
    RESULTS_OUT.parent.mkdir(parents=True, exist_ok=True)

    todo = [r for r in reds if (r["model"], r["id"]) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"To process: {len(todo)} rows  |  truncation: {MAX_OPINION_CHARS_OLD:,} -> {MAX_OPINION_CHARS_NEW:,} chars")

    if args.dry_run:
        for r in todo[:10]:
            cid = r["matched_cluster_id"]
            cache = OPINIONS_CACHE / f"{cid}.txt"
            n = len(cache.read_text(encoding="utf-8", errors="replace")) if cache.exists() else 0
            print(f"  {r['model']:8s} {r['id']:24s} cluster={cid:9s} chars={n:>7,}  tier={tier_from_cite(r['gold_cite'])}")
        print(f"... ({len(todo)} total)")
        return

    total_cost = 0.0
    flips = 0
    skipped_fits = 0
    with RESULTS_OUT.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
            f.flush()

        for i, row in enumerate(todo, 1):
            cid = row["matched_cluster_id"]
            cache = OPINIONS_CACHE / f"{cid}.txt"
            if not cache.exists():
                # Shouldn't happen given preflight, but be defensive.
                print(f"  [{i}/{len(todo)}] {row['model']} {row['id']}: no cached opinion, skipping")
                continue
            full_text = cache.read_text(encoding="utf-8", errors="replace")
            n_full = len(full_text)
            truncated_in_v1 = n_full > MAX_OPINION_CHARS_OLD

            tier = tier_from_cite(row["gold_cite"])

            base = {
                "model": row["model"], "id": row["id"], "court": row["court"],
                "tier": tier,
                "matched_cluster_id": cid,
                "matched_cl_name": row["matched_cl_name"],
                "extracted_citation": row["extracted_citation"],
                "gold_name": row["gold_name"], "gold_cite": row["gold_cite"],
                "proposition": row["proposition"],
                "opinion_chars_full": n_full,
                "truncated_in_v1": "Y" if truncated_in_v1 else "N",
                "original_supports": "Red",
                "original_rationale": row["support_rationale"],
            }

            if not truncated_in_v1:
                # The new window contains the same text the v1 assessor saw.
                # Re-running would cost the same dollars and (in expectation)
                # return the same verdict. Mark and skip.
                skipped_fits += 1
                writer.writerow({**base,
                    "new_supports": "SKIP",
                    "new_rationale": "opinion fits within 20K, no new text exposed",
                    "flipped": "N",
                    "cost_usd": 0.0,
                })
                f.flush()
                print(f"  [{i}/{len(todo)}] {row['model']} {row['id']}: opinion fits in 20K ({n_full:,} chars), skipped")
                continue

            opinion_excerpt = full_text[:MAX_OPINION_CHARS_NEW]
            case_label = f"{row['matched_cl_name'] or row['extracted_case_name']}, {row['extracted_citation']}"
            print(f"  [{i}/{len(todo)}] {row['model']} {row['id']} | {case_label[:55]}  ({n_full:,} chars)")

            a = call_assessor_stdin(row["proposition"], case_label, opinion_excerpt,
                                    model=ASSESSOR_MODEL)
            new_supports = a["assessment"] or ""
            new_rationale = a["rationale"]
            cost = float(a.get("cost_usd") or 0.0)
            total_cost += cost
            flipped = new_supports in ("Green", "Yellow")
            if flipped:
                flips += 1
            print(f"      -> {new_supports or '?'}  (cost ${cost:.4f}, total ${total_cost:.2f}, flips {flips})")

            writer.writerow({**base,
                "new_supports": new_supports,
                "new_rationale": new_rationale,
                "flipped": "Y" if flipped else "N",
                "cost_usd": cost,
            })
            f.flush()

    # Summary
    print()
    print(f"Wrote {RESULTS_OUT}")
    print(f"Processed: {len(todo)}  |  skipped-fits: {skipped_fits}  |  flips: {flips}  |  cost: ${total_cost:.2f}")

    # Per-tier breakdown across the full output file (incl. resumed rows)
    tier_counts: dict[str, dict[str, int]] = {}
    for r in csv.DictReader(RESULTS_OUT.open(encoding="utf-8")):
        if r["new_supports"] == "SKIP":
            continue
        t = r["tier"]
        tier_counts.setdefault(t, {"n": 0, "Green": 0, "Yellow": 0, "Red": 0, "?": 0})
        tier_counts[t]["n"] += 1
        v = r["new_supports"] if r["new_supports"] in ("Green", "Yellow", "Red") else "?"
        tier_counts[t][v] += 1
    print()
    print(f"Re-assessed Reds at {MAX_OPINION_CHARS_NEW:,} chars (excluding fits-in-20K skips):")
    print(f"  {'tier':<10} {'n':>4}  {'->Green':>8} {'->Yellow':>9} {'->Red':>7} {'?':>4}  flip%")
    for t in ("SCOTUS", "Circuit", "District", "Other"):
        c = tier_counts.get(t)
        if not c:
            continue
        flip_pct = (c["Green"] + c["Yellow"]) / c["n"] * 100 if c["n"] else 0
        print(f"  {t:<10} {c['n']:>4}  {c['Green']:>8} {c['Yellow']:>9} {c['Red']:>7} {c['?']:>4}  {flip_pct:>5.1f}%")


if __name__ == "__main__":
    main()
