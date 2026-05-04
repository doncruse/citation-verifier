"""Score outputs_*.csv on three axes -> results.csv.

Real (citation-verifier existence) + Name match (CaseNameMatcher) +
Supports (Opus 4.7 substance assessor on real cases). Joined across
all three model output files into one (model, example) per row.

Resume-safe: re-running on a partially-completed results.csv only
scores cells that aren't yet present.

Gold-DB integration: Axis 3 (Supports) uses the gold-DB cache via
get_or_score_verdict(). Cache hits skip the Opus call entirely.
After the main loop, rolling_recheck() re-scores ~10 random cached
pairs under prompt_version='v1-drift-<run_id>' for drift detection.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load Pilot A's score.py under a distinct module name to avoid colliding
# with this file (also called score.py).
_pilot_path = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
_spec = importlib.util.spec_from_file_location("pilot_a_score", _pilot_path)
_pilot_score = importlib.util.module_from_spec(_spec)
sys.modules["pilot_a_score"] = _pilot_score
_spec.loader.exec_module(_pilot_score)
extract_citation = _pilot_score.extract_citation
fetch_opinion_text = _pilot_score.fetch_opinion_text
call_assessor = _pilot_score.call_assessor
_names_score = _pilot_score._names_score

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.gold_db import GoldDB  # noqa: E402
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark_v1" / "results.csv"
GOLD_DB_PATH = PROJECT_ROOT / "gold_db" / "gold.db"

ASSESSOR_MODEL = "opus"          # shorthand passed to call_assessor
ASSESSOR_MODEL_DB = "opus-4.7"   # canonical name stored in gold-DB
ASSESSOR_PROMPT_VERSION = "v1"
OPINION_WINDOW = 20_000          # chars; matches pilot_a MAX_OPINION_CHARS
ROLLING_RECHECK_N = 10
NAME_MATCH_THRESHOLD = 0.65


def score_cell_with_cache(
    db: GoldDB,
    client: CourtListenerClient,
    row: dict,
    run_id: str,
) -> dict:
    """Score a single (model, example) cell, using gold-DB cache for Axis 3.

    `row` must contain: proposition, matched_cluster_id, matched_cl_name,
    and extracted_citation (for the case_label passed to call_assessor).

    Returns a dict with 'supports', 'support_rationale', 'support_cost_usd'.
    On cache hit, support_cost_usd is 0.0 (no Opus call made).
    Returns empty strings if cluster_id is missing or opinion text is absent.
    """
    cluster_id_str = (row.get("matched_cluster_id") or "").strip()
    if not cluster_id_str:
        return {"supports": "", "support_rationale": "no cluster id", "support_cost_usd": 0.0}
    try:
        cluster_id = int(cluster_id_str)
    except ValueError:
        return {"supports": "", "support_rationale": f"bad cluster id: {cluster_id_str!r}", "support_cost_usd": 0.0}

    pid = db.upsert_proposition(row["proposition"], None, run_id)
    cl_name = row.get("matched_cl_name") or ""
    ext_cite = (row.get("extracted_citation") or "").strip()
    case_label = f"{cl_name or row.get('extracted_case_name', '')}, {ext_cite}"

    _cost_holder: list[float] = [0.0]

    def _score_fn():
        opinion = fetch_opinion_text(client, cluster_id) or ""
        if not opinion:
            return {"verdict": "red", "reasoning": "no opinion text", "confidence": None}
        truncated = opinion[:OPINION_WINDOW]
        a = call_assessor(row["proposition"], case_label, truncated, model=ASSESSOR_MODEL)
        _cost_holder[0] = a.get("cost_usd") or 0.0
        verdict = (a.get("assessment") or "").lower()
        if verdict not in ("green", "yellow", "red"):
            verdict = "red"
        return {
            "verdict": verdict,
            "reasoning": a.get("rationale") or "",
            "confidence": None,
        }

    record = db.get_or_score_verdict(
        proposition_id=pid,
        candidate_cluster_id=cluster_id,
        assessor_model=ASSESSOR_MODEL_DB,
        assessor_prompt_version=ASSESSOR_PROMPT_VERSION,
        opinion_window_chars=OPINION_WINDOW,
        source="model_answer",
        run_id=run_id,
        score_fn=_score_fn,
    )
    return {
        "supports": record["verdict"],
        "support_rationale": record["reasoning_excerpt"] or "",
        "support_cost_usd": _cost_holder[0],
    }


def rolling_recheck(
    db: GoldDB,
    client: CourtListenerClient,
    run_id: str,
    n: int = ROLLING_RECHECK_N,
) -> int:
    """Re-score n random already-cached pairs to detect assessor drift.

    Drift samples use assessor_prompt_version='v1-drift-<run_id>' so they
    live alongside the canonical cache without collision.  Query drift later:
        WHERE assessor_prompt_version LIKE 'v1-drift%'
    Returns the count of drift samples successfully recorded.
    """
    drift_version = f"v1-drift-{run_id}"
    rows = db.conn.execute(
        """
        SELECT v.proposition_id, v.candidate_cluster_id,
               p.text AS prop_text, c.canonical_name AS case_name
          FROM assessor_verdicts v
          JOIN propositions p ON p.proposition_id = v.proposition_id
          JOIN cases c        ON c.cluster_id     = v.candidate_cluster_id
         WHERE v.assessor_model = ?
           AND v.assessor_prompt_version = ?
         ORDER BY RANDOM()
         LIMIT ?
        """,
        (ASSESSOR_MODEL_DB, ASSESSOR_PROMPT_VERSION, n),
    ).fetchall()

    if not rows:
        print("rolling_recheck: no cached verdicts found, skipping drift check")
        return 0

    print(f"rolling_recheck: re-scoring {len(rows)} random pairs "
          f"under prompt_version={drift_version!r}")
    rechecked = 0
    for r in rows:
        opinion = fetch_opinion_text(client, r["candidate_cluster_id"]) or ""
        if not opinion:
            continue
        truncated = opinion[:OPINION_WINDOW]
        a = call_assessor(r["prop_text"], r["case_name"], truncated, model=ASSESSOR_MODEL)
        verdict = (a.get("assessment") or "").lower()
        if verdict not in ("green", "yellow", "red"):
            verdict = "red"
        rationale = a.get("rationale") or ""
        db.insert_verdict(
            proposition_id=r["proposition_id"],
            candidate_cluster_id=r["candidate_cluster_id"],
            verdict=verdict,
            assessor_model=ASSESSOR_MODEL_DB,
            assessor_prompt_version=drift_version,
            opinion_window_chars=OPINION_WINDOW,
            confidence=None,
            reasoning_excerpt=rationale[:500],
            source="probe",
            run_id=run_id,
        )
        rechecked += 1
    print(f"rolling_recheck: recorded {rechecked} drift samples")
    return rechecked


async def verify_extracted(rows: list[dict]) -> list[dict]:
    verifier = CitationVerifier()
    citation_strs, parsed, indices = [], [], []
    for i, row in enumerate(rows):
        ext = row.get("_extract") or {}
        if ext.get("citation_text") and ext.get("fcc"):
            indices.append(i)
            citation_strs.append(ext["citation_text"])
            parsed.append(parsed_citation_from_eyecite(ext["fcc"]))
    if not citation_strs:
        return rows
    # quick_only=True skips opinion-search/RECAP fallback. Citation-lookup
    # batch endpoint only.
    results = await verifier.verify_batch(citation_strs, parsed_citations=parsed,
                                          quick_only=True)
    for idx, res in zip(indices, results):
        rows[idx]["_verify"] = res
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-substance", action="store_true",
                    help="skip Opus assessor (axes 1+2 only)")
    ap.add_argument("--skip-drift", action="store_true",
                    help="skip rolling drift re-check (useful with --skip-substance)")
    ap.add_argument("--run-id", default=None,
                    help="explicit run id (default: v1-score-<YYYYMMDD-HHMM>)")
    args = ap.parse_args()

    run_id = args.run_id or (
        "v1-score-" + dt.datetime.utcnow().strftime("%Y%m%d-%H%M")
    )
    print(f"run_id: {run_id}")

    bench = PROJECT_ROOT / "benchmark_v1"
    all_rows: list[dict] = []
    for m_file in ["outputs_sonnet.csv", "outputs_opus.csv", "outputs_gpt5.csv"]:
        p = bench / m_file
        if not p.exists():
            print(f"WARN: {p} not found, skipping", file=sys.stderr)
            continue
        for r in csv.DictReader(p.open(encoding="utf-8")):
            all_rows.append(r)
    print(f"Loaded {len(all_rows)} (model, example) cells")

    # Step A: extract citation from each model response
    for row in all_rows:
        row["_extract"] = extract_citation(row.get("model_response", ""))

    # Step B: batch-verify all extracted citations (one CL call total)
    print("Verifying extracted citations...")
    all_rows = asyncio.run(verify_extracted(all_rows))

    # Resume support: load existing results, skip already-scored cells
    existing_keys: set[tuple[str, str]] = set()
    if OUT.exists():
        for r in csv.DictReader(OUT.open(encoding="utf-8")):
            existing_keys.add((r["model"], r["id"]))
        print(f"Resuming: {len(existing_keys)} cells already scored")

    fieldnames = [
        "id", "court", "model", "proposition", "gold_name", "gold_cite",
        "model_response", "extracted_case_name", "extracted_citation",
        "real", "real_status", "name_match", "matched_cl_name",
        "matched_cluster_id", "right_case",
        "supports", "support_rationale", "support_cost_usd",
    ]
    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60

    # Open gold-DB for cache-aware Axis 3 scoring.
    db = GoldDB(GOLD_DB_PATH)

    write_header = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total_support_cost = 0.0
    with OUT.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()

        for i, row in enumerate(all_rows, 1):
            key = (row["model"], row["id"])
            if key in existing_keys:
                continue
            ext = row.get("_extract") or {}
            ver = row.get("_verify")

            real = False
            real_status = ""
            cl_name = ""
            cluster_id = ""
            if ver is not None:
                real_status = ver.status.value if ver.status else ""
                real = ver.status in (VerificationStatus.VERIFIED,
                                       VerificationStatus.LIKELY_REAL)
                cl_name = ver.matched_case_name or ""
                cluster_id = str(ver.matched_cluster_id or "")

            extracted_case = ext.get("case_name", "")
            ext_cite = (ext.get("citation_text") or "").strip()
            name_match = (
                real and _names_score(extracted_case, cl_name) >= NAME_MATCH_THRESHOLD
            )

            gold_cite = (row.get("gold_cite") or "").strip()
            gold_name = (row.get("gold_name") or "").strip()
            right_case = bool(ext_cite and ext_cite in gold_cite) and (
                _names_score(extracted_case, gold_name) >= 0.6
                if (extracted_case and gold_name) else False
            )

            support = ""
            support_rationale = ""
            support_cost = 0.0
            if not args.skip_substance and real:
                # Build a row-like dict for score_cell_with_cache with all
                # fields it needs.
                score_row = {
                    "proposition": row["proposition"],
                    "matched_cluster_id": cluster_id,
                    "matched_cl_name": cl_name,
                    "extracted_case_name": extracted_case,
                    "extracted_citation": ext_cite,
                }
                print(f"  [{i}/{len(all_rows)}] {row['model']} | {cl_name[:50]}")
                scored = score_cell_with_cache(db, client, score_row, run_id)
                support = scored["supports"]
                support_rationale = scored["support_rationale"]
                support_cost = scored["support_cost_usd"]
                total_support_cost += support_cost
            elif row.get("model_response", "").strip().upper().startswith("UNKNOWN"):
                support_rationale = "model returned UNKNOWN"

            writer.writerow({
                "id": row["id"], "court": row["court"], "model": row["model"],
                "proposition": row["proposition"],
                "gold_name": gold_name, "gold_cite": gold_cite,
                "model_response": row.get("model_response", ""),
                "extracted_case_name": extracted_case,
                "extracted_citation": ext_cite,
                "real": "Y" if real else "N",
                "real_status": real_status,
                "name_match": "Y" if name_match else "N",
                "matched_cl_name": cl_name,
                "matched_cluster_id": cluster_id,
                "right_case": "Y" if right_case else "N",
                "supports": support,
                "support_rationale": support_rationale,
                "support_cost_usd": support_cost,
            })
            f.flush()

    print(f"\nWrote {OUT}")
    print(f"Assessor cost this run: ${total_support_cost:.2f}")

    # Rolling drift re-check: re-score ~10 cached pairs under a distinct
    # prompt_version to detect silent assessor drift over time.
    if not args.skip_substance and not args.skip_drift:
        rolling_recheck(db, client, run_id)

    db.close()


if __name__ == "__main__":
    main()
