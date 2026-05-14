"""
Probe: reservoir-sample N parentheticals from the CL bulk file, look up the
cited opinion's cluster + court via the API, tier-classify with lookup_court().

Goal: see whether stratified 50/50/50/50 across SCOTUS / Circuit / State COLR /
State IAC is achievable from CL's parenthetical corpus, and what the per-tier
yield / quality looks like before committing to a real pipeline.

NOT trying to verify citations -- just capture proposition + cited case as
written.

Outputs:
- sample.csv            : raw sample of N parentheticals
- classified.csv        : sample joined with cited-cluster metadata + tier
- tier_distribution.csv : counts by (system, level)
- score_distribution.csv: score histogram on the classified sample
"""

import csv
import bz2
import os
import random
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Make sure we can import citation_verifier.gold_db
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from citation_verifier.gold_db import lookup_court  # noqa: E402

load_dotenv(ROOT / ".env")
TOKEN = os.environ["COURTLISTENER_API_TOKEN"]
HEADERS = {"Authorization": f"Token {TOKEN}"}
API = "https://www.courtlistener.com/api/rest/v4"

HERE = Path(__file__).parent
BULK = HERE / "parentheticals-2026-03-31.csv.bz2"

SAMPLE_SIZE = 500
SEED = 20260513


def reservoir_sample(bulk_path: Path, k: int, seed: int):
    """Stream-decompress and reservoir-sample k rows. Returns list of dicts."""
    rng = random.Random(seed)
    reservoir = []
    n = 0
    with bz2.open(bulk_path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n += 1
            if len(reservoir) < k:
                reservoir.append(row)
            else:
                j = rng.randint(0, n - 1)
                if j < k:
                    reservoir[j] = row
            if n % 200000 == 0:
                print(f"  ... read {n:,} rows", flush=True)
    print(f"  total rows read: {n:,}")
    return reservoir, n


def lookup_opinion_cluster(opinion_id: str, session: requests.Session) -> dict | None:
    """Return {'cluster_id': int, 'court_id': str, 'case_name': str, 'date_filed': str}."""
    r = session.get(f"{API}/opinions/{opinion_id}/", headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    op = r.json()
    cluster_url = op.get("cluster")
    if not cluster_url:
        return None
    rc = session.get(cluster_url, headers=HEADERS, timeout=15)
    if rc.status_code == 404:
        return None
    rc.raise_for_status()
    cl = rc.json()
    docket_url = cl.get("docket")
    court_id = None
    if docket_url:
        rd = session.get(docket_url, headers=HEADERS, timeout=15)
        if rd.status_code == 200:
            d = rd.json()
            court = d.get("court")
            if isinstance(court, str) and court.startswith("http"):
                # Extract court id from URL
                court_id = court.rstrip("/").split("/")[-1]
            elif isinstance(court, str):
                court_id = court
    return {
        "cluster_id": cl.get("id"),
        "court_id": court_id,
        "case_name": cl.get("case_name"),
        "date_filed": cl.get("date_filed"),
    }


def main():
    print(f"reservoir-sampling {SAMPLE_SIZE} rows from {BULK.name} (seed={SEED})")
    sample, total = reservoir_sample(BULK, SAMPLE_SIZE, SEED)

    # Save raw sample
    with open(HERE / "sample.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sample[0].keys()))
        w.writeheader()
        w.writerows(sample)
    print(f"saved sample.csv ({len(sample)} rows)")

    # Look up cited cluster + court for each sampled row
    print(f"\nlooking up cited-opinion cluster + court via API ({len(sample)} rows, ~1/sec)...")
    sess = requests.Session()
    enriched = []
    start = time.time()
    for i, row in enumerate(sample, 1):
        opid = row["described_opinion_id"]
        try:
            meta = lookup_opinion_cluster(opid, sess)
        except Exception as e:
            meta = None
            err = f"{type(e).__name__}: {e}"
        else:
            err = ""
        if meta:
            sys_lvl = lookup_court(meta["court_id"]) if meta["court_id"] else (None, None)
            enriched.append({
                **row,
                "cited_cluster_id": meta["cluster_id"],
                "cited_court_id": meta["court_id"],
                "cited_case_name": meta["case_name"],
                "cited_date_filed": meta["date_filed"],
                "system": sys_lvl[0] if sys_lvl else None,
                "level": sys_lvl[1] if sys_lvl else None,
                "lookup_error": err,
            })
        else:
            enriched.append({
                **row,
                "cited_cluster_id": None,
                "cited_court_id": None,
                "cited_case_name": None,
                "cited_date_filed": None,
                "system": None,
                "level": None,
                "lookup_error": err or "not_found_or_no_cluster",
            })
        if i % 25 == 0 or i == len(sample):
            elapsed = time.time() - start
            rate = i / elapsed
            eta = (len(sample) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(sample)}] elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s")

    # Save enriched
    with open(HERE / "classified.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(enriched[0].keys()))
        w.writeheader()
        w.writerows(enriched)
    print(f"saved classified.csv ({len(enriched)} rows)")

    # Tier distribution
    from collections import Counter
    tier_counter = Counter((r["system"], r["level"]) for r in enriched)
    with open(HERE / "tier_distribution.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["system", "level", "n", "pct"])
        for (s, l), n in sorted(tier_counter.items(), key=lambda x: -x[1]):
            pct = 100 * n / len(enriched)
            w.writerow([s, l, n, f"{pct:.1f}"])
    print("\ntier distribution:")
    for (s, l), n in sorted(tier_counter.items(), key=lambda x: -x[1]):
        pct = 100 * n / len(enriched)
        print(f"  {s!s:>10}/{l!s:<8} {n:>4} ({pct:.1f}%)")

    # Score distribution
    scores = [float(r["score"]) for r in enriched if r["score"]]
    bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    hist = [0] * (len(bins) - 1)
    for s in scores:
        for i in range(len(bins) - 1):
            if bins[i] <= s < bins[i + 1]:
                hist[i] += 1
                break
    with open(HERE / "score_distribution.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score_range", "n"])
        for i, n in enumerate(hist):
            w.writerow([f"[{bins[i]:.1f},{bins[i+1]:.2f})", n])
    print(f"\nscore distribution (n={len(scores)}):")
    for i, n in enumerate(hist):
        print(f"  [{bins[i]:.1f},{bins[i+1]:.2f}) {n:>4}")

    # Yield stats
    print()
    print(f"total parentheticals in bulk file: {total:,}")
    print(f"sampled: {len(sample)}")
    classified = sum(1 for r in enriched if r["system"] is not None)
    tier_target = sum(1 for r in enriched if (r["system"], r["level"]) in {
        ("federal", "colr"), ("federal", "iac"),
        ("state", "colr"), ("state", "iac"),
    })
    print(f"classified ((system, level) populated): {classified} ({100*classified/len(enriched):.1f}%)")
    print(f"in 4-tier target set: {tier_target} ({100*tier_target/len(enriched):.1f}%)")


if __name__ == "__main__":
    main()
