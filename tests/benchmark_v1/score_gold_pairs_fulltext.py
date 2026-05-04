"""Score v1 gold-pair (proposition, cited-case) at FULL opinion text.

This is the methodologically-correct successor to score_gold_pairs.py
(Task 10), which was silently capped at 20K by pilot_a's
fetch_opinion_text. Uses citation-verifier's CourtListenerClient (with
prefer_html fallback) to get the full opinion every time, and **hard-
fails** per row when no text is available rather than silently writing
a Red verdict on empty input.

Stores verdicts under `assessor_prompt_version='v1-fulltext'`, leaving
`opinion_window_chars=NULL` (the explicit "no truncation" marker). The
(model, prompt_version, window) cache key means runs of different
models coexist without collision.

Usage:
    # Run Sonnet on all gold pairs (skips ones already scored at this key)
    venv/Scripts/python.exe -m tests.benchmark_v1.score_gold_pairs_fulltext \\
        --model sonnet

    # Run Haiku
    venv/Scripts/python.exe -m tests.benchmark_v1.score_gold_pairs_fulltext \\
        --model haiku

    # Re-score only the original Reds (for the audit pattern)
    venv/Scripts/python.exe -m tests.benchmark_v1.score_gold_pairs_fulltext \\
        --model sonnet --reds-only
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.gold_db import GoldDB  # noqa: E402

PROMPT_VERSION = "v1-fulltext"
MODEL_DB_NAME = {"sonnet": "sonnet-4.6", "haiku": "haiku-4.5", "opus": "opus-4.7"}
OPINION_CACHE_DIRS = [
    PROJECT_ROOT / "scratch" / "pilot_a" / "opinion_cache",
    PROJECT_ROOT / "benchmark_v1" / "_opinion_cache",
]


def _load_pilot():
    """Lazily load pilot_a/score.py for ASSESSMENT_PROMPT + ASSESSOR_TIMEOUT
    + _HERMETIC_DIR. We only use these constants; we do NOT call
    pilot_a's truncating fetch_opinion_text or call_assessor."""
    if "pilot_a_score" in sys.modules:
        return sys.modules["pilot_a_score"]
    p = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
    spec = importlib.util.spec_from_file_location("pilot_a_score", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pilot_a_score"] = mod
    spec.loader.exec_module(mod)
    return mod


def _call_assessor_stdin(proposition: str, case_name: str, opinion_text: str,
                         model: str = "sonnet") -> dict:
    """Call `claude -p --model X` with prompt piped via stdin to avoid
    Windows CreateProcess CLI-length limit (~32K chars).

    Returns the same dict shape pilot_a returns:
        {assessment, rationale, elapsed_s, cost_usd}
    """
    pilot = _load_pilot()
    prompt = pilot.ASSESSMENT_PROMPT.format(
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
            timeout=pilot.ASSESSOR_TIMEOUT,
            cwd=str(pilot._HERMETIC_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"assessment": None, "rationale": "TIMEOUT",
                "elapsed_s": pilot.ASSESSOR_TIMEOUT, "cost_usd": 0}
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


def _fetch_full_opinion(client: CourtListenerClient, cluster_id: int) -> str:
    """Fetch full opinion text with no truncation.

    Strategy:
      1. Check on-disk caches (no truncation) — pilot_a's and
         build_dataset's cache dirs.
      2. If not cached, call CourtListenerClient.get_opinion_text_with_metadata
         which handles plain_text + stripped HTML fallback + 429 retry.
      3. If still empty, retry with prefer_html=True (raw HTML, then PDF).
      4. Write the resulting full text to cache for future runs.

    Returns "" only if all paths failed. Caller MUST treat empty as a
    hard failure (do not write a verdict).
    """
    # 1. Cache hit
    for d in OPINION_CACHE_DIRS:
        cache = d / f"{cluster_id}.txt"
        if cache.exists():
            text = cache.read_text(encoding="utf-8", errors="replace")
            if text:
                return text

    # 2. Fresh fetch via citation-verifier's robust client
    matched_url = f"https://www.courtlistener.com/opinion/{cluster_id}/"
    try:
        result = client.get_opinion_text_with_metadata(matched_url)
    except Exception as exc:
        print(f"      WARN: get_opinion_text_with_metadata failed for {cluster_id}: {exc}",
              file=sys.stderr, flush=True)
        result = None
    text = (result or {}).get("text") or ""

    # 3. Retry with HTML fallback if plain failed
    if not text:
        try:
            result = client.get_opinion_text_with_metadata(matched_url, prefer_html=True)
        except Exception as exc:
            print(f"      WARN: prefer_html retry failed for {cluster_id}: {exc}",
                  file=sys.stderr, flush=True)
            result = None
        text = (result or {}).get("text") or ""
        if text and (result or {}).get("format") == "html":
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

    # 4. Write to cache for next time
    if text:
        write_to = OPINION_CACHE_DIRS[0]
        write_to.mkdir(parents=True, exist_ok=True)
        try:
            (write_to / f"{cluster_id}.txt").write_text(text, encoding="utf-8")
        except Exception as exc:
            print(f"      WARN: cache write failed for {cluster_id}: {exc}",
                  file=sys.stderr, flush=True)

    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default="gold_db/gold.db")
    ap.add_argument("--model", default="sonnet", choices=["sonnet", "haiku", "opus"])
    ap.add_argument("--reds-only", action="store_true",
                    help="only score pairs that were Red in the canonical Opus-20K run")
    ap.add_argument("--limit", type=int, default=None,
                    help="max pairs to score (for smoke testing)")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    model_db_name = MODEL_DB_NAME[args.model]
    run_id = args.run_id or (
        f"v1-fulltext-{args.model}-"
        f"{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    )

    db = GoldDB(args.db_path)
    client = CourtListenerClient()

    # Find gold pairs to score
    where = "v.source = 'gold_pair' AND v.assessor_prompt_version = 'v1'"
    if args.reds_only:
        where += " AND v.verdict = 'red'"

    rows = db.conn.execute(f"""
        SELECT cr.id AS row_id, cr.proposition_id, cr.cited_cluster_id,
               p.text AS prop_text, c.canonical_name AS case_name,
               v.verdict AS opus_verdict
          FROM citation_rows cr
          JOIN propositions p ON p.proposition_id = cr.proposition_id
          JOIN cases c ON c.cluster_id = cr.cited_cluster_id
          JOIN assessor_verdicts v ON v.proposition_id = cr.proposition_id
                                  AND v.candidate_cluster_id = cr.cited_cluster_id
                                  AND v.source = 'gold_pair'
          WHERE cr.dataset_name = 'v1'
            AND {where}
         ORDER BY cr.id
    """).fetchall()

    if args.limit:
        rows = rows[: args.limit]

    print(f"Score v1 gold pairs at FULL opinion text with {model_db_name}")
    print(f"  pool: {len(rows)} pairs ({'Reds only' if args.reds_only else 'all'})")
    print(f"  run_id: {run_id}")
    print()

    try:
        db.start_run(run_id, kind="gold_pair_fulltext",
                     notes=f"score gold pairs at full opinion with {model_db_name}")
    except Exception:
        pass

    results = []
    cached_count = 0
    failed_clusters = []  # cluster_ids with no opinion text (hard failures)

    for i, r in enumerate(rows, 1):
        # Cache check
        existing = db.get_verdict(
            r["proposition_id"], r["cited_cluster_id"],
            model_db_name, PROMPT_VERSION, None,
        )
        if existing is not None:
            print(f"  [{i}/{len(rows)}] CACHED ({existing['verdict']:6s}): "
                  f"{r['case_name'][:60]}")
            results.append({"row": r, "verdict": existing["verdict"],
                            "rationale": existing["reasoning_excerpt"]})
            cached_count += 1
            continue

        # Robust full-text fetch
        opinion = _fetch_full_opinion(client, r["cited_cluster_id"])
        if not opinion:
            print(f"  [{i}/{len(rows)}] FAIL (no text): {r['case_name'][:60]} "
                  f"cluster={r['cited_cluster_id']}")
            failed_clusters.append({"cluster_id": r["cited_cluster_id"],
                                    "case_name": r["case_name"],
                                    "row_id": r["row_id"]})
            continue

        n_chars = len(opinion)
        print(f"  [{i}/{len(rows)}] {r['case_name'][:50]} ({n_chars:,} chars) "
              f"opus_was={r['opus_verdict']}...", flush=True)

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
            candidate_cluster_id=r["cited_cluster_id"],
            verdict=verdict,
            assessor_model=model_db_name,
            assessor_prompt_version=PROMPT_VERSION,
            opinion_window_chars=None,
            confidence=None,
            reasoning_excerpt=rationale[:500],
            source="gold_pair",
            run_id=run_id,
        )
        results.append({"row": r, "verdict": verdict, "rationale": rationale})
        flip = ""
        if r["opus_verdict"] == "red" and verdict in ("green", "yellow"):
            flip = "  [FLIPPED]"
        elif r["opus_verdict"] == "green" and verdict == "red":
            flip = "  [REGRESSION]"
        print(f"      -> {verdict}{flip}")

    try:
        db.end_run(run_id)
    except KeyError:
        pass

    print()
    print("=" * 70)
    print(f"Scored {len(results)} pairs at full opinion with {model_db_name}")
    print(f"  cached (no new call): {cached_count}")
    print(f"  failed (no opinion text): {len(failed_clusters)}")
    print()

    # Distribution
    counts = {"green": 0, "yellow": 0, "red": 0}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    for k in ("green", "yellow", "red"):
        v = counts.get(k, 0)
        pct = 100 * v / len(results) if results else 0
        print(f"  {k}: {v} ({pct:.1f}%)")

    # Agreement vs canonical Opus-20K
    if results:
        agreed = sum(1 for r in results if r["verdict"] == r["row"]["opus_verdict"])
        flipped_to_better = sum(1 for r in results if r["row"]["opus_verdict"] == "red"
                                and r["verdict"] in ("green", "yellow"))
        regressed = sum(1 for r in results if r["row"]["opus_verdict"] == "green"
                        and r["verdict"] == "red")
        print()
        print(f"vs canonical Opus-20K:")
        print(f"  same verdict: {agreed}/{len(results)} ({100*agreed/len(results):.1f}%)")
        print(f"  Reds that flipped to G/Y: {flipped_to_better}")
        print(f"  Greens that regressed to Red: {regressed}")

    if failed_clusters:
        print()
        print(f"Failed clusters ({len(failed_clusters)}) — no opinion text after all retries:")
        for f in failed_clusters:
            print(f"  cluster={f['cluster_id']} {f['case_name'][:60]}")


if __name__ == "__main__":
    main()
