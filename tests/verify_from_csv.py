"""Iterative CSV-based citation verification workflow.

Reads citations from a CSV master file, verifies a sample against the
CourtListener API, and writes results back to the same CSV.  Supports
incremental batches with human QC between runs.

Usage:
    python tests/verify_from_csv.py                      # 50 random pending
    python tests/verify_from_csv.py --sample-size 10     # smaller batch
    python tests/verify_from_csv.py --seed 43             # reproducible sample
    python tests/verify_from_csv.py --all                 # verify everything pending
    python tests/verify_from_csv.py --rerun-only          # only qc_status=rerun rows
    python tests/verify_from_csv.py --dry-run             # preview without API calls
"""

import argparse
import csv
import json
import random
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from citation_verifier.models import ParsedCitation
from citation_verifier.verifier import CitationVerifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_git_hash() -> str | None:
    """Get the current git short hash, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


NEW_COLUMNS = [
    "v_status", "v_confidence", "v_url", "v_matched_name",
    "v_git_hash", "qc_status", "qc_notes",
]


def _ensure_columns(fieldnames: list[str]) -> list[str]:
    """Append any missing new columns to the field list."""
    for col in NEW_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
    return fieldnames


def _is_actionable(row: dict) -> bool:
    """Return True if this row should be (re-)verified."""
    if row.get("qc_status") == "rerun":
        return True
    if row.get("qc_status") in ("duplicate", "ignore", "investigate", "data"):
        return False
    if not row.get("v_status"):
        return True
    return False


def _parsed_citation_from_row(row: dict) -> ParsedCitation:
    """Build a ParsedCitation from CSV column values.

    This mirrors the pattern in parser.py:parsed_citation_from_eyecite()
    but reads from a dict of strings instead of an eyecite object.
    """
    def _int_or_none(val: str | None) -> int | None:
        if not val:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    case_name = row.get("case_name") or None
    plaintiff = row.get("plaintiff") or None
    defendant = row.get("defendant") or None

    # Build case_name from plaintiff/defendant if missing
    if not case_name and plaintiff and defendant:
        case_name = f"{plaintiff} v. {defendant}"

    volume = row.get("volume") or None
    reporter = row.get("reporter") or None
    page = row.get("page") or None
    court = row.get("court") or None
    year = _int_or_none(row.get("year"))
    month = _int_or_none(row.get("month"))
    day = _int_or_none(row.get("day"))
    docket_number = row.get("docket_number") or None
    is_westlaw = row.get("is_westlaw", "").upper() in ("TRUE", "1", "YES")
    wl_number = row.get("wl_number") or None

    return ParsedCitation(
        raw_text=row.get("citation_text", ""),
        case_name=case_name,
        plaintiff=plaintiff,
        defendant=defendant,
        volume=volume,
        reporter=reporter,
        page=page,
        court=court,
        year=year,
        month=month,
        day=day,
        docket_number=docket_number,
        is_westlaw=is_westlaw,
        wl_number=wl_number,
    )


def _stratified_sample(
    rows: list[dict], sample_size: int
) -> list[dict]:
    """Stratified sample: 40% likely_fake, 40% likely_real, 20% uncertain."""
    buckets: dict[str, list[dict]] = {
        "likely_fake": [],
        "likely_real": [],
        "uncertain": [],
    }
    for row in rows:
        cls = row.get("classification", "uncertain")
        bucket = buckets.get(cls, buckets["uncertain"])
        bucket.append(row)

    targets = {
        "likely_fake": int(sample_size * 0.4),
        "likely_real": int(sample_size * 0.4),
        "uncertain": sample_size,  # will be clamped below
    }
    # Adjust uncertain to fill remainder
    targets["uncertain"] = sample_size - targets["likely_fake"] - targets["likely_real"]

    sampled: list[dict] = []
    overflow: list[dict] = []
    for cls in ("likely_fake", "likely_real", "uncertain"):
        pool = buckets[cls]
        target = targets[cls]
        if len(pool) <= target:
            sampled.extend(pool)
            # deficit will be filled from overflow
        else:
            chosen = random.sample(pool, target)
            sampled.extend(chosen)
            overflow.extend(r for r in pool if r not in chosen)

    # Fill any remaining slots from overflow
    remaining = sample_size - len(sampled)
    if remaining > 0 and overflow:
        sampled.extend(random.sample(overflow, min(remaining, len(overflow))))

    return sampled[:sample_size]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iterative CSV-based citation verification"
    )
    parser.add_argument(
        "--csv", type=str,
        default=str(Path(__file__).parent.parent / "scratch" / "citations_for_review.csv"),
        help="Path to master CSV (default: scratch/citations_for_review.csv)",
    )
    parser.add_argument("--sample-size", type=int, default=50,
                        help="Number of citations to verify (default: 50)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed (default: random)")
    parser.add_argument("--all", action="store_true",
                        help="Verify all pending rows (ignore --sample-size)")
    parser.add_argument("--rerun-only", action="store_true",
                        help="Only verify rows where qc_status=rerun")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be verified without calling the API")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: {csv_path} not found")
        return

    # Seed
    if args.seed is not None:
        random.seed(args.seed)
        seed_label = str(args.seed)
    else:
        seed_val = random.randrange(10000)
        random.seed(seed_val)
        seed_label = str(seed_val)

    # Read CSV
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        all_rows = list(reader)

    fieldnames = _ensure_columns(fieldnames)
    print(f"Loaded {len(all_rows)} citations from {csv_path.name}")

    # Filter to actionable rows
    if args.rerun_only:
        actionable = [r for r in all_rows if r.get("qc_status") == "rerun"]
        print(f"Found {len(actionable)} rows marked for re-run")
    else:
        actionable = [r for r in all_rows if _is_actionable(r)]
        print(f"Found {len(actionable)} actionable rows "
              f"({len(all_rows) - len(actionable)} already verified/skipped)")

    if not actionable:
        print("Nothing to verify.")
        return

    # Sample
    if args.all:
        to_verify = actionable
    else:
        to_verify = _stratified_sample(actionable, args.sample_size)

    # Summarize stratification
    by_cls: dict[str, int] = {}
    for r in to_verify:
        cls = r.get("classification", "uncertain")
        by_cls[cls] = by_cls.get(cls, 0) + 1
    strat_str = ", ".join(f"{v} {k}" for k, v in sorted(by_cls.items()))
    print(f"Selected {len(to_verify)} citations (seed={seed_label}): {strat_str}")

    if args.dry_run:
        print(f"\n{'='*80}")
        print("DRY RUN - would verify these citations:")
        print(f"{'='*80}")
        for i, row in enumerate(to_verify, 1):
            status_note = ""
            if row.get("qc_status") == "rerun":
                status_note = " [RERUN]"
            print(f"  {i:3d}. [{row.get('classification', '?'):12s}] "
                  f"{row.get('citation_text', '?')}{status_note}")
            print(f"       Source: {row.get('pdf', '?')}")
        return

    # Verify
    git_hash = _get_git_hash()
    verifier = CitationVerifier()
    results_for_sidecar: list[dict] = []

    # Build a lookup set of rows being verified (by index in all_rows)
    verify_indices: set[int] = set()
    for row in to_verify:
        for i, r in enumerate(all_rows):
            if r is row:
                verify_indices.add(i)
                break

    total = len(to_verify)
    print(f"\nVerifying {total} citations...")
    print("This will take a few minutes (rate limited to 1 req/sec)\n")

    for seq, row in enumerate(to_verify, 1):
        citation_text = row.get("citation_text", "").strip()
        parsed = _parsed_citation_from_row(row)

        # Skip rows with no case name (short cites)
        case_name = row.get("case_name", "").strip()
        if not case_name or case_name == "v." or case_name.startswith("None v. None"):
            print(f"[{seq}/{total}] SKIPPED: {citation_text} (short cite)")
            row["v_status"] = "SKIPPED"
            row["v_confidence"] = ""
            row["v_url"] = ""
            row["v_matched_name"] = ""
            row["v_git_hash"] = git_hash or ""
            if row.get("qc_status") == "rerun":
                row["qc_status"] = ""
                row["qc_notes"] = ""
            results_for_sidecar.append({
                "citation_text": citation_text,
                "classification": row.get("classification", ""),
                "pdf": row.get("pdf", ""),
                "status": "SKIPPED",
                "confidence": 0.0,
                "matched_case_name": None,
                "matched_url": None,
                "diagnostics": ["Short cite with no case name"],
            })
            print()
            continue

        print(f"[{seq}/{total}] Verifying: {citation_text}")

        try:
            result = verifier.verify(citation_text, parsed=parsed)
            print(f"  Status: {result.status.value}  "
                  f"Confidence: {result.confidence:.2f}")
            if result.matched_url:
                print(f"  Match: {result.matched_url}")

            row["v_status"] = result.status.value
            row["v_confidence"] = str(result.confidence)
            row["v_url"] = result.matched_url or ""
            row["v_matched_name"] = result.matched_case_name or ""
            row["v_git_hash"] = git_hash or ""

            # Clear QC fields on rerun
            if row.get("qc_status") == "rerun":
                row["qc_status"] = ""
                row["qc_notes"] = ""

            results_for_sidecar.append({
                "citation_text": citation_text,
                "classification": row.get("classification", ""),
                "pdf": row.get("pdf", ""),
                "status": result.status.value,
                "confidence": result.confidence,
                "matched_case_name": result.matched_case_name,
                "matched_url": result.matched_url,
                "diagnostics": result.diagnostics,
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            row["v_status"] = "NOT_FOUND"
            row["v_confidence"] = "0.0"
            row["v_url"] = ""
            row["v_matched_name"] = ""
            row["v_git_hash"] = git_hash or ""
            if row.get("qc_status") == "rerun":
                row["qc_status"] = ""
                row["qc_notes"] = ""
            results_for_sidecar.append({
                "citation_text": citation_text,
                "classification": row.get("classification", ""),
                "pdf": row.get("pdf", ""),
                "status": "ERROR",
                "confidence": 0.0,
                "matched_case_name": None,
                "matched_url": None,
                "diagnostics": [str(e)],
            })

        print()

    # Write CSV back (backup first)
    bak_path = csv_path.with_suffix(".csv.bak")
    shutil.copy2(csv_path, bak_path)
    print(f"Backup: {bak_path}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            # Ensure all new columns exist
            for col in NEW_COLUMNS:
                if col not in row:
                    row[col] = ""
            writer.writerow(row)

    print(f"Updated: {csv_path}")

    # Write JSON sidecar
    results_dir = Path(__file__).parent / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d")
    sidecar_path = results_dir / f"verification_{timestamp}_csv_seed{seed_label}.json"
    sidecar_data = {
        "_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_hash": git_hash,
            "seed": seed_label,
            "sample_size": len(to_verify),
            "source": str(csv_path),
            "stratification": strat_str,
        },
        "results": results_for_sidecar,
    }
    with open(sidecar_path, "w") as f:
        json.dump(sidecar_data, f, indent=2)

    # Summary
    by_status: dict[str, int] = {}
    for r in results_for_sidecar:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1

    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}")
    print(f"Total: {len(to_verify)}")
    for status, count in sorted(by_status.items()):
        print(f"  {status:20s}: {count}")
    print(f"\nJSON sidecar: {sidecar_path}")
    print(f"Git hash: {git_hash or 'unknown'}")

    # Highlight items needing QC
    needs_qc = [r for r in results_for_sidecar
                if r["status"] in ("NOT_FOUND", "POSSIBLE_MATCH")]
    if needs_qc:
        print(f"\n{'='*80}")
        print(f"NEEDS QC ({len(needs_qc)} items) - review in JSON sidecar:")
        print(f"{'='*80}")
        for r in needs_qc[:15]:
            print(f"\n  [{r['status']}] {r['citation_text']}")
            print(f"    Source: {r['pdf']}")
            if r.get("diagnostics"):
                print(f"    Why: {r['diagnostics'][0]}")
        if len(needs_qc) > 15:
            print(f"\n  ... and {len(needs_qc) - 15} more (see JSON sidecar)")


if __name__ == "__main__":
    main()
