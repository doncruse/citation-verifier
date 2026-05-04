"""Backfill v1's CSV outputs into gold-DB.

Reads benchmark_v1/{dataset.csv, outputs_*.csv, results.csv,
truncation_experiment_60k.csv, calibration_results.csv}, dedupes, and
populates the gold-DB. Idempotent: rerunning on a populated DB inserts
only what's missing (relies on UNIQUE constraints + ON CONFLICT
behavior of the GoldDB methods).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.gold_db import GoldDB, _normalize_proposition  # noqa: E402

# Model name mappings: outputs CSVs and results.csv use short names;
# gold-DB stores versioned names. Centralize so v2 only needs one edit.
_MODEL_NAME_MAP = {
    "sonnet": "sonnet-4.6",
    "opus":   "opus-4.7",
    "haiku":  "haiku-4.5",
    "gpt-5":  "gpt-5",
}
_OUTPUTS_FILES = [
    ("outputs_sonnet.csv", "sonnet-4.6"),
    ("outputs_opus.csv",   "opus-4.7"),
    ("outputs_gpt5.csv",   "gpt-5"),
]

_CL_URL_RE = re.compile(r"courtlistener\.com/opinion/(\d+)/")


def _cluster_id_from_url(url: str | None) -> int | None:
    if not url:
        return None
    m = _CL_URL_RE.search(url)
    return int(m.group(1)) if m else None


def _safe_int(s: str | None) -> int | None:
    if s in (None, "", "None"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _safe_float(s: str | None) -> float | None:
    if s in (None, "", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_bool(s: str | None) -> bool | None:
    if s in (None, "", "None"):
        return None
    return s.strip().lower() in ("true", "1", "yes", "y")


def backfill_v1(db: GoldDB, bench_dir: Path, run_id: str) -> dict:
    """Returns a dict of insertion attempt counts (some may have been
    deduped via UNIQUE)."""
    counts = {"cases": 0, "propositions": 0, "citation_rows": 0,
              "model_answers": 0, "verdicts": 0,
              "truncation_verdicts": 0, "calibration_verdicts": 0}

    # Idempotency: only call start_run if it hasn't already happened
    try:
        db.start_run(run_id, kind="backfill", notes=f"backfill from {bench_dir}")
    except sqlite3.IntegrityError:
        pass  # already started (idempotent re-run)

    # Register the dataset.
    db.conn.execute(
        """INSERT OR IGNORE INTO datasets (name, mining_window_start,
                  mining_window_end, mined_courts, n_rows, frozen_at, notes)
           VALUES ('v1', '2026-01-01', '2026-04-30',
                   '[\"dcd\",\"cand\",\"txsd\",\"ilnd\",\"nysd\",\"mad\"]',
                   127, ?, 'effective N=127 after eyecite dedup')""",
        (datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",),
    )
    db.conn.commit()

    # Pass 1: dataset.csv -> cases + propositions + citation_rows (deduped).
    seen_pairs: set[tuple[str, int]] = set()
    proposition_id_by_text: dict[str, str] = {}
    dataset_path = bench_dir / "dataset.csv"
    if dataset_path.exists():
        with dataset_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cited_id = _cluster_id_from_url(row.get("v_url"))
                citing_id = _safe_int(row.get("citing_cluster_id"))
                if cited_id is None or citing_id is None:
                    continue
                norm = _normalize_proposition(row.get("proposition") or "")
                if not norm:
                    continue
                pair = (norm, cited_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Citing case: court is in `court` column (e.g. 'ca9');
                # canonical name unknown at this stage (placeholder).
                db.upsert_case(
                    cluster_id=citing_id,
                    canonical_name=f"<citing-{citing_id}>",
                    court_id=row.get("court") or None,
                    year=_safe_int(row.get("citing_year")),
                    cite_string=None,
                    run_id=run_id,
                )
                counts["cases"] += 1

                # Cited case: name from CL match; court_id unknown at v1 stage
                # (system/level NULL until v1.x metadata pass).
                db.upsert_case(
                    cluster_id=cited_id,
                    canonical_name=row.get("v_matched_name") or row.get("gold_name") or "",
                    court_id=None,
                    year=_safe_int(row.get("cited_year")),
                    cite_string=row.get("gold_cite"),
                    run_id=run_id,
                )
                counts["cases"] += 1

                pid = db.upsert_proposition(
                    text=row.get("proposition"),
                    holding_verb=None,
                    run_id=run_id,
                )
                proposition_id_by_text[norm] = pid
                counts["propositions"] += 1

                db.add_citation_row(
                    citing_cluster_id=citing_id,
                    cited_cluster_id=cited_id,
                    proposition_id=pid,
                    parenthetical=row.get("proposition") or "",
                    dataset_name="v1",
                )
                counts["citation_rows"] += 1

    # Pass 2: outputs_*.csv -> model_answers (deduped per (prop, model)).
    # Seed seen_answers from existing rows so re-runs are idempotent
    # (record_model_answer has no built-in dedup).
    seen_answers: set[tuple[str, str]] = {
        (row["proposition_id"], row["model_name"])
        for row in db.conn.execute(
            "SELECT proposition_id, model_name FROM model_answers")
    }
    for model_file, model_name in _OUTPUTS_FILES:
        p = bench_dir / model_file
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                norm = _normalize_proposition(row.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid is None:
                    continue
                key = (pid, model_name)
                if key in seen_answers:
                    continue
                seen_answers.add(key)
                db.record_model_answer(
                    proposition_id=pid,
                    answer_cluster_id=None,  # filled in pass 3
                    model_name=model_name,
                    raw_response=row.get("model_response") or "",
                    parse_status="parsed",  # refined in pass 3
                    answered_cite_string=None,
                    cite_resolved_real=None,
                    name_match_score=None,
                    run_id="v1",
                )
                counts["model_answers"] += 1

    # Pass 3: results.csv -> backfill answer_cluster_id + verdicts.
    seen_verdicts: set[tuple[str, int, str]] = set()
    results_path = bench_dir / "results.csv"
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                norm = _normalize_proposition(row.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid is None:
                    continue
                model = _MODEL_NAME_MAP.get(row.get("model"), row.get("model"))
                ans_id = _safe_int(row.get("matched_cluster_id"))

                # Ensure answer case exists BEFORE the UPDATE writes
                # answer_cluster_id (FK requires referent to be present).
                if ans_id is not None:
                    db.upsert_case(
                        cluster_id=ans_id,
                        canonical_name=row.get("matched_cl_name") or "",
                        court_id=None,
                        year=None,
                        cite_string=row.get("extracted_citation"),
                        run_id="v1",
                    )
                    counts["cases"] += 1

                # Update model_answer (fill in fields we now know).
                db.conn.execute(
                    """
                    UPDATE model_answers
                       SET answer_cluster_id = COALESCE(?, answer_cluster_id),
                           cite_resolved_real = ?,
                           name_match_score   = ?,
                           parse_status       = ?
                     WHERE proposition_id = ? AND model_name = ?
                    """,
                    (ans_id,
                     _parse_bool(row.get("real")),
                     _safe_float(row.get("name_match")),
                     "parsed" if (row.get("model_response") or "").strip()
                                 .upper() != "UNKNOWN" else "unknown",
                     pid, model),
                )

                # Verdict (only when there's an actual answer case).
                supports = (row.get("supports") or "").strip().lower()
                if ans_id is not None and supports in ("green", "yellow", "red"):
                    key = (pid, ans_id, model)
                    if key in seen_verdicts:
                        continue
                    seen_verdicts.add(key)
                    db.insert_verdict(
                        proposition_id=pid,
                        candidate_cluster_id=ans_id,
                        verdict=supports,
                        assessor_model="opus-4.7",
                        assessor_prompt_version="v1",
                        opinion_window_chars=20000,
                        confidence=None,
                        reasoning_excerpt=row.get("support_rationale"),
                        source="model_answer",
                        run_id="v1",
                    )
                    counts["verdicts"] += 1
        db.conn.commit()

    # Pass 4: truncation_experiment_60k.csv -> Opus 60K verdicts.
    counts["truncation_verdicts"] = _backfill_truncation(
        db, bench_dir, run_id, proposition_id_by_text)

    # Pass 5: calibration_results.csv -> Sonnet/Haiku verdicts.
    counts["calibration_verdicts"] = _backfill_calibration(
        db, bench_dir, run_id, proposition_id_by_text)

    try:
        db.end_run(run_id)
    except KeyError:
        pass  # already ended (idempotent reruns)
    return counts


def _backfill_truncation(
    db: GoldDB, bench_dir: Path, run_id: str,
    proposition_id_by_text: dict[str, str],
) -> int:
    """Pass 4: insert Opus 60K re-scored verdicts on Reds."""
    p = bench_dir / "truncation_experiment_60k.csv"
    if not p.exists():
        return 0
    n = 0
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ans_id = _safe_int(row.get("matched_cluster_id"))
            if ans_id is None:
                continue
            norm = _normalize_proposition(row.get("proposition") or "")
            pid = proposition_id_by_text.get(norm)
            if pid is None:
                continue
            verdict = (row.get("new_supports") or "").strip().lower()
            if verdict not in ("green", "yellow", "red"):
                continue
            # Ensure case exists for FK
            db.upsert_case(
                cluster_id=ans_id,
                canonical_name=row.get("matched_cl_name") or "",
                court_id=None,
                year=None,
                cite_string=row.get("extracted_citation"),
                run_id=run_id,
            )
            db.insert_verdict(
                proposition_id=pid,
                candidate_cluster_id=ans_id,
                verdict=verdict,
                assessor_model="opus-4.7",
                assessor_prompt_version="v1",
                opinion_window_chars=60000,
                confidence=None,
                reasoning_excerpt=(row.get("new_rationale") or "")[:500],
                source="model_answer",
                run_id=run_id,
            )
            n += 1
    db.conn.commit()
    return n


def _backfill_calibration(
    db: GoldDB, bench_dir: Path, run_id: str,
    proposition_id_by_text: dict[str, str],
) -> int:
    """Pass 5: insert Sonnet/Haiku verdicts from the calibration study.

    calibration_results.csv has only (id, model_under_test, candidate_model,
    candidate_verdict). Recover matched_cluster_id from results.csv,
    proposition_id from dataset.csv via id->proposition lookup.
    """
    cal_path = bench_dir / "calibration_results.csv"
    if not cal_path.exists():
        return 0

    # Join lookup: (model, id) -> matched_cluster_id (from results.csv)
    results_lookup: dict[tuple[str, str], int] = {}
    results_path = bench_dir / "results.csv"
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                mc = _safe_int(r.get("matched_cluster_id"))
                if mc is not None:
                    results_lookup[(r["model"], r["id"])] = mc

    # Lookup id -> proposition_id (from dataset.csv normalized text)
    id_to_pid: dict[str, str] = {}
    dataset_path = bench_dir / "dataset.csv"
    if dataset_path.exists():
        with dataset_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                norm = _normalize_proposition(r.get("proposition") or "")
                pid = proposition_id_by_text.get(norm)
                if pid:
                    id_to_pid[r["id"]] = pid

    n = 0
    with cal_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("error") or "").strip():
                continue
            verdict = (row.get("candidate_verdict") or "").strip().lower()
            if verdict not in ("green", "yellow", "red"):
                continue
            mut = row.get("model_under_test")
            ans_id = results_lookup.get((mut, row["id"]))
            if ans_id is None:
                continue
            pid = id_to_pid.get(row["id"])
            if pid is None:
                continue
            cand_model = _MODEL_NAME_MAP.get(
                row.get("candidate_model"), row.get("candidate_model"))
            db.insert_verdict(
                proposition_id=pid,
                candidate_cluster_id=ans_id,
                verdict=verdict,
                assessor_model=cand_model,
                assessor_prompt_version="v1",
                opinion_window_chars=20000,
                confidence=None,
                reasoning_excerpt=(row.get("candidate_rationale") or "")[:500],
                source="model_answer",
                run_id=run_id,
            )
            n += 1
    db.conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-dir", default="benchmark_v1")
    ap.add_argument("--db-path", default="gold_db/gold.db")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    run_id = args.run_id or f"v1-backfill-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    db = GoldDB(args.db_path)
    counts = backfill_v1(db, Path(args.bench_dir), run_id)
    print("Backfill complete (insert attempts):")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    actual = {
        t: db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("cases", "propositions", "citation_rows",
                  "model_answers", "assessor_verdicts")
    }
    print("Final row counts:")
    for k, v in actual.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
