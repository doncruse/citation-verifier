"""Score outputs_*.csv on three axes -> results.csv.

Real (citation-verifier existence) + Name match (CaseNameMatcher) +
Supports (Opus 4.7 substance assessor on real cases). Joined across
all three model output files into one (model, example) per row.

Resume-safe: re-running on a partially-completed results.csv only
scores cells that aren't yet present.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
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
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark_v1" / "results.csv"

ASSESSOR_MODEL = "opus"  # spec calls for Opus 4.7
NAME_MATCH_THRESHOLD = 0.65


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
    args = ap.parse_args()

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

    write_header = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
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
                cluster_id = ver.matched_cluster_id or ""

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

            support = None
            support_rationale = ""
            support_cost = 0.0
            if not args.skip_substance and real:
                opinion_text = fetch_opinion_text(client, cluster_id)
                if opinion_text:
                    case_label = f"{cl_name or extracted_case}, {ext_cite}"
                    print(f"  [{i}/{len(all_rows)}] {row['model']} | {case_label[:60]}")
                    a = call_assessor(row["proposition"], case_label, opinion_text,
                                       model=ASSESSOR_MODEL)
                    support = a["assessment"]
                    support_rationale = a["rationale"]
                    support_cost = a["cost_usd"]
                else:
                    support_rationale = "no opinion text"
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
                "supports": support or "",
                "support_rationale": support_rationale,
                "support_cost_usd": support_cost,
            })
            f.flush()

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
