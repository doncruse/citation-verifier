"""Score every v1 (proposition, gold-case) pair with Opus.

Establishes the calibration baseline: how often does Opus agree that the
gold case supports the gold proposition? Cache-aware via gold-DB.

Real-data run: ~127 Opus calls. Cache-aware: reruns are zero-cost.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.gold_db import GoldDB  # noqa: E402

OPINION_WINDOW = 60000  # post v1.1 standard
ASSESSOR_MODEL = "opus-4.7"
PROMPT_VERSION = "v1"


def _load_pilot_assessor():
    """Import call_assessor + fetch_opinion_text from pilot_a/score.py
    without name collision (both files are called score.py)."""
    p = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
    spec = importlib.util.spec_from_file_location("pilot_a_score", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pilot_a_score"] = mod
    spec.loader.exec_module(mod)
    return mod


def _default_assessor(proposition: str, case_name: str, opinion_text: str) -> dict:
    """Real Opus assessor (calls Anthropic API).

    pilot_a's call_assessor returns a dict with keys
    {assessment, rationale, elapsed_s, cost_usd}. On timeout it returns
    assessment=None; we propagate this as a 'red' verdict with
    rationale='TIMEOUT' so the row still goes in (preserving the audit
    trail) rather than silently skipping.
    """
    pilot = _load_pilot_assessor()
    result = pilot.call_assessor(
        proposition, case_name, opinion_text, model="opus",
    )
    assessment = result.get("assessment")
    rationale = result.get("rationale") or ""
    if assessment is None:
        # Timeout or parse failure — preserve in DB as 'red' with reason.
        verdict = "red"
        rationale = f"ASSESSOR_FAILURE: {rationale}"
    else:
        verdict = assessment.lower()
        # Defensive: ensure verdict is a known value
        if verdict not in ("green", "yellow", "red"):
            verdict = "red"
            rationale = f"UNEXPECTED_VERDICT={assessment!r}: {rationale}"
    return {"verdict": verdict, "confidence": None, "reasoning": rationale}


def score_gold_pairs(
    db: GoldDB,
    run_id: str,
    assessor_fn: Callable[[str, str, str], dict] | None = None,
) -> int:
    """Score every v1 citation_row's (proposition, cited-case) pair.

    Returns the number of NEW verdicts recorded (cache hits skipped).
    `assessor_fn` is injectable for testing; defaults to the real Opus
    assessor that calls the Anthropic API.
    """
    if assessor_fn is None:
        assessor_fn = _default_assessor

    try:
        db.start_run(run_id, kind="calibration",
                     notes="gold-pair self-score baseline")
    except sqlite3.IntegrityError:
        pass  # already started (idempotent re-run)

    rows = db.conn.execute("""
        SELECT cr.proposition_id, cr.cited_cluster_id, p.text AS prop_text,
               c.canonical_name AS case_name
          FROM citation_rows cr
          JOIN propositions p ON p.proposition_id = cr.proposition_id
          JOIN cases c ON c.cluster_id = cr.cited_cluster_id
         WHERE cr.dataset_name = 'v1'
    """).fetchall()

    new_verdicts = 0
    for r in rows:
        # Cache check first to avoid expensive opinion fetch on hits
        cached = db.get_verdict(r["proposition_id"], r["cited_cluster_id"],
                                ASSESSOR_MODEL, PROMPT_VERSION, OPINION_WINDOW)
        if cached is not None:
            continue

        # Fetch opinion text via Pilot A's helper.
        # When testing, assessor_fn may be a MagicMock and we don't actually
        # need opinion text — pass a placeholder to satisfy the API.
        if assessor_fn is _default_assessor:
            pilot = _load_pilot_assessor()
            opinion_text = pilot.fetch_opinion_text(r["cited_cluster_id"])
            if not opinion_text:
                print(f"WARN: no opinion text for cluster {r['cited_cluster_id']}, skipping",
                      file=sys.stderr)
                continue
            truncated = opinion_text[:OPINION_WINDOW]
        else:
            truncated = ""  # mock won't read it

        result = assessor_fn(r["prop_text"], r["case_name"], truncated)

        db.insert_verdict(
            proposition_id=r["proposition_id"],
            candidate_cluster_id=r["cited_cluster_id"],
            verdict=result["verdict"],
            assessor_model=ASSESSOR_MODEL,
            assessor_prompt_version=PROMPT_VERSION,
            opinion_window_chars=OPINION_WINDOW,
            confidence=result.get("confidence"),
            reasoning_excerpt=(result.get("reasoning") or "")[:500],
            source="gold_pair",
            run_id=run_id,
        )
        new_verdicts += 1
        if new_verdicts % 10 == 0:
            print(f"  scored {new_verdicts} new pairs...", flush=True)

    try:
        db.end_run(run_id)
    except KeyError:
        pass
    return new_verdicts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default="gold_db/gold.db")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    run_id = args.run_id or f"v1-goldpair-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    db = GoldDB(args.db_path)
    n = score_gold_pairs(db, run_id)
    print(f"Done. {n} new verdicts recorded.")
    print("Distribution:")
    for r in db.conn.execute("""
        SELECT verdict, COUNT(*) FROM assessor_verdicts
         WHERE source='gold_pair'
         GROUP BY verdict
    """):
        print(f"  {r[0]}: {r[1]}")


if __name__ == "__main__":
    main()
