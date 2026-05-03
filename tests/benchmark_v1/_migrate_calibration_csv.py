"""One-shot migration: add `model_under_test` column to calibration_results.csv.

The original calibrate_assessor.py keyed resume by (id, candidate_model),
which collapsed up to three v1 cells (one per model_under_test) into a
single resume key. The script then processed all such cells per id,
producing 1-3 rows per (id, candidate_model) pair — all real assessor
calls, but lacking the column needed to tell which model_under_test
each row corresponds to.

Recovery: rows in calibration_results.csv were written in the order
the script visited cells. The script visited cells in the order
load_candidate_cells() returned them, which preserves the order of
benchmark_v1/results.csv. So for each (id, candidate_model) pair,
the i-th calibration row corresponds to the i-th v1 cell with that
id (filtered to canonical + supports-populated cells).

Validation: this script asserts that the opus_verdict on each
calibration row matches the `supports` column of the v1 cell at the
inferred index. Any mismatch aborts.

After this migrates, re-run calibrate_assessor.py and the resume
logic will only fire the API for the 12 triples that the smoke run
skipped (the 3 first-cell smokes blocked their two siblings via
the broken resume key).
"""
from __future__ import annotations

import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "benchmark_v1"))
from scorecard import canonical_dataset_ids  # noqa: E402

BENCH = PROJECT_ROOT / "benchmark_v1"
CAL_CSV = BENCH / "calibration_results.csv"
BACKUP = BENCH / "calibration_results_original.csv"

NEW_FIELDS = [
    "id",
    "model_under_test",
    "candidate_model",
    "opus_verdict",
    "candidate_verdict",
    "candidate_rationale",
    "agree",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "elapsed_s",
    "error",
]


def main() -> int:
    if not CAL_CSV.exists():
        print(f"Nothing to migrate: {CAL_CSV} does not exist.")
        return 0

    cal_rows = list(csv.DictReader(CAL_CSV.open(encoding="utf-8")))
    if cal_rows and "model_under_test" in cal_rows[0]:
        print("Already migrated (model_under_test column present). No-op.")
        return 0

    # v1 cells in row order
    keep = canonical_dataset_ids()
    v1_rows = list(csv.DictReader((BENCH / "results.csv").open(encoding="utf-8")))
    v1_cells = [r for r in v1_rows if r.get("id") in keep and r.get("supports")]
    v1_by_id = defaultdict(list)
    for r in v1_cells:
        v1_by_id[r["id"]].append(r)

    # Group calibration rows by (id, candidate_model), preserving order
    cal_by_pair = defaultdict(list)
    for r in cal_rows:
        cal_by_pair[(r["id"], r["candidate_model"])].append(r)

    migrated: list[dict] = []
    for (cid, cmodel), pair_rows in cal_by_pair.items():
        v1_for_id = v1_by_id.get(cid, [])
        if len(pair_rows) > len(v1_for_id):
            print(
                f"ERROR: pair {(cid, cmodel)} has {len(pair_rows)} cal rows "
                f"but only {len(v1_for_id)} v1 cells. Aborting.",
                file=sys.stderr,
            )
            return 1
        for i, cal_row in enumerate(pair_rows):
            v1_cell = v1_for_id[i]
            # Validate: opus_verdict on cal row should equal v1's supports.
            if cal_row.get("opus_verdict", "") != v1_cell.get("supports", ""):
                print(
                    f"ERROR: opus_verdict mismatch on {(cid, cmodel)} row {i}: "
                    f"cal={cal_row.get('opus_verdict')!r} v1={v1_cell.get('supports')!r}. "
                    "Order-based recovery is unsafe; aborting.",
                    file=sys.stderr,
                )
                return 1
            new = dict(cal_row)
            new["model_under_test"] = v1_cell["model"]
            migrated.append(new)

    # Backup before overwrite (only if no backup yet)
    if not BACKUP.exists():
        shutil.copy(CAL_CSV, BACKUP)
        print(f"Backed up original to {BACKUP.name}")

    # Sort migrated rows: by candidate_model, then by id, then by model_under_test
    # (deterministic order makes diffs easier to read)
    migrated.sort(
        key=lambda r: (r["candidate_model"], r["id"], r["model_under_test"])
    )

    with CAL_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in migrated:
            writer.writerow({k: row.get(k, "") for k in NEW_FIELDS})

    print(f"Migrated {len(migrated)} rows. Wrote {CAL_CSV.name}.")
    print(
        f"Re-run calibrate_assessor.py to fill the "
        f"{257 * 2 - len(migrated)} missing triples."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
