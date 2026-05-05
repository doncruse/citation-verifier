"""Re-score v1 Reds at full opinion text to test the truncation hypothesis.

Reads the v1 gold-pair Reds from the gold-DB, fetches the full cited
opinion text (no truncation), and re-scores with sonnet/haiku/opus.
Stores results under `assessor_prompt_version='v1-fulltext'` so they
don't collide with canonical 60K verdicts.

Cache-aware: re-runs are zero-cost.

Usage:
    venv/Scripts/python.exe -m benchmark.runners.red_audit_fulltext --model sonnet
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

from benchmark.pilot_a import score as pilot_score  # noqa: E402
from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.gold_db import GoldDB  # noqa: E402

PROMPT_VERSION = "v1-fulltext"
MODEL_DB_NAME = {"sonnet": "sonnet-4.6", "haiku": "haiku-4.5", "opus": "opus-4.7"}
OPINION_CACHE_DIRS = [
    PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache",
    PROJECT_ROOT / "benchmark" / "releases" / "v1" / "citing_opinion_cache",
]


def _call_assessor_stdin(proposition: str, case_name: str, opinion_text: str,
                          model: str = "sonnet") -> dict:
    """Like pilot_a.call_assessor but pipes the prompt via stdin to avoid
    Windows CreateProcess CLI-length limit (~32K chars).

    Returns the same dict shape: {assessment, rationale, elapsed_s, cost_usd}.
    """
    import json
    import re
    import subprocess
    import time

    prompt = pilot_score.ASSESSMENT_PROMPT.format(
        proposition=proposition,
        case_name_citation=case_name,
        opinion_text=opinion_text or "(opinion text unavailable)",
    )
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=pilot_score.ASSESSOR_TIMEOUT,
            cwd=str(pilot_score._HERMETIC_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"assessment": None, "rationale": "TIMEOUT",
                "elapsed_s": pilot_score.ASSESSOR_TIMEOUT, "cost_usd": 0}
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
        for color in ("Green", "Yellow", "Red"):
            if color in response:
                assessment = color
                rationale = response[:200]
                break

    return {"assessment": assessment, "rationale": rationale,
            "elapsed_s": round(elapsed, 1), "cost_usd": cost}


def _fetch_full_opinion_text(client: CourtListenerClient, cluster_id: int | None) -> str:
    """Fetch opinion text WITHOUT pilot_a's 20K truncation.

    Reads the on-disk cache fully (no [:MAX_OPINION_CHARS] cap). Falls
    back to a fresh CL fetch if not cached, then writes the full text
    to cache.
    """
    if not cluster_id:
        return ""
    # Check all known cache dirs first (pilot_a's and build_dataset's)
    for d in OPINION_CACHE_DIRS:
        cache = d / f"{cluster_id}.txt"
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")
    # Not cached anywhere — fetch fresh and write to the first cache dir
    write_to = OPINION_CACHE_DIRS[0]
    write_to.mkdir(parents=True, exist_ok=True)
    cache = write_to / f"{cluster_id}.txt"
    try:
        cluster = client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{cluster_id}/"
        ).json()
    except Exception as exc:
        print(f"      cluster fetch failed for {cluster_id}: {exc}", file=sys.stderr, flush=True)
        return ""
    op_urls = cluster.get("sub_opinions") or []
    if not op_urls:
        return ""
    op_url = op_urls[0]
    try:
        op = client._request_with_retry("GET", op_url).json()
    except Exception as exc:
        print(f"      opinion fetch failed for {cluster_id}: {exc}", file=sys.stderr, flush=True)
        return ""
    text = (op.get("plain_text") or "").strip()
    if text:
        cache.write_text(text, encoding="utf-8")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default="benchmark/gold_db/gold.db")
    ap.add_argument("--model", default="sonnet", choices=["sonnet", "haiku", "opus"])
    ap.add_argument("--limit", type=int, default=None,
                    help="only process first N rows (for testing)")
    args = ap.parse_args()

    model_db_name = MODEL_DB_NAME[args.model]
    run_id = f"v1-red-audit-{args.model}-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    db = GoldDB(args.db_path)
    cl = CourtListenerClient()

    rows = db.conn.execute("""
        SELECT v.id AS verdict_id, v.proposition_id, v.candidate_cluster_id,
               p.text AS prop_text, c.canonical_name AS case_name
          FROM assessor_verdicts v
          JOIN propositions p ON p.proposition_id = v.proposition_id
          JOIN cases c ON c.cluster_id = v.candidate_cluster_id
         WHERE v.source = 'gold_pair' AND v.verdict = 'red'
           AND v.assessor_prompt_version = 'v1'
         ORDER BY v.id
    """).fetchall()

    if args.limit:
        rows = rows[: args.limit]

    print(f"Re-scoring {len(rows)} v1 Reds at full opinion with {model_db_name}...")
    print(f"run_id: {run_id}")
    print()

    try:
        db.start_run(run_id, kind="red_audit_fulltext",
                     notes=f"re-score v1 Reds at full opinion with {model_db_name}")
    except Exception:
        pass

    results = []
    skipped_no_opinion = 0
    cached_count = 0
    for i, r in enumerate(rows, 1):
        existing = db.get_verdict(
            r["proposition_id"], r["candidate_cluster_id"],
            model_db_name, PROMPT_VERSION, None,
        )
        if existing is not None:
            print(f"  [{i}/{len(rows)}] CACHED: {r['case_name'][:60]} -> {existing['verdict']}")
            results.append({"row": r, "verdict": existing["verdict"],
                            "rationale": existing["reasoning_excerpt"], "n_chars": None})
            cached_count += 1
            continue

        opinion = _fetch_full_opinion_text(cl, r["candidate_cluster_id"])
        if not opinion:
            print(f"  [{i}/{len(rows)}] SKIP: no opinion text for {r['case_name'][:60]}")
            skipped_no_opinion += 1
            continue

        n_chars = len(opinion)
        print(f"  [{i}/{len(rows)}] {r['case_name'][:50]} ({n_chars:,} chars)...", flush=True)

        result = _call_assessor_stdin(
            r["prop_text"], r["case_name"], opinion, model=args.model,
        )
        verdict_raw = result.get("assessment")
        if verdict_raw is None:
            verdict = "red"
            rationale = f"ASSESSOR_FAILURE: {result.get('rationale') or ''}"
        else:
            verdict = verdict_raw.lower()
            if verdict not in ("green", "yellow", "red"):
                verdict = "red"
            rationale = result.get("rationale") or ""

        db.insert_verdict(
            proposition_id=r["proposition_id"],
            candidate_cluster_id=r["candidate_cluster_id"],
            verdict=verdict,
            assessor_model=model_db_name,
            assessor_prompt_version=PROMPT_VERSION,
            opinion_window_chars=None,  # NULL = no truncation
            confidence=None,
            reasoning_excerpt=rationale[:500],
            source="gold_pair",
            run_id=run_id,
        )
        results.append({"row": r, "verdict": verdict, "rationale": rationale,
                        "n_chars": n_chars})
        print(f"      -> {verdict}")

    try:
        db.end_run(run_id)
    except KeyError:
        pass

    print()
    print("=" * 60)
    print(f"Summary: re-scored {len(results)} v1 Reds at full opinion with {model_db_name}")
    print(f"  cached (no new call): {cached_count}")
    print(f"  no opinion text (skipped): {skipped_no_opinion}")
    print()

    if results:
        counts = {"green": 0, "yellow": 0, "red": 0}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        for k, v in counts.items():
            pct = 100 * v / len(results)
            print(f"  {k}: {v} ({pct:.1f}%)")
        flipped = counts.get("green", 0) + counts.get("yellow", 0)
        print(f"  Reds flipped to Green/Yellow: {flipped}/{len(results)} ({100*flipped/len(results):.1f}%)")
    print()
    print("Per-case results:")
    for r in results:
        print(f"  {r['verdict']:6s} {r['row']['case_name'][:60]}")


if __name__ == "__main__":
    main()
