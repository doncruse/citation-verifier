# scratch/

Working directory for the iterative citation verification workflow. Not part of the tool itself.

## Files

| File | Purpose |
|------|---------|
| `citations_for_review.csv` | Master state file -- 515 citations tracked through extraction, verification, and human QC |
| `citations_for_review.csv.bak` | Auto-backup from the last `verify_from_csv.py` run |
| `TODO.md` | Bug/feature tracking with prioritized items |
| `flp_contributions.md` | Drafted contributions to Free Law Project (with submission checklists) |
| `check_indigo_book_coverage.py` | One-off script testing abbreviation coverage against CL search |
| `hallucination_opinions/` | Source PDFs of court opinions discussing AI-hallucinated citations (gitignored, synced separately) |

## Verification workflow

Each iteration: run a batch, QC the results, fix issues, repeat.

```bash
# 1. Run verification on next batch (async, ~50 citations)
python tests/verify_from_csv.py --sample-size 50

# 2. QC review
#    Open the JSON sidecar (tests/data/results/verification_*.json)
#    Review NOT_FOUND and POSSIBLE_MATCH items
#    Update qc_status and qc_notes in the CSV

# 3. After code fixes, re-verify affected rows
#    Set qc_status=rerun on rows to re-check, then:
python tests/verify_from_csv.py --rerun-only
```

### CLI options

```
python tests/verify_from_csv.py [options]
  --csv PATH          (default: scratch/citations_for_review.csv)
  --sample-size N     (default: 50)
  --seed N            (default: random)
  --all               verify all pending, no sampling
  --rerun-only        only rows where qc_status=rerun
  --dry-run           show what would be verified, don't call API
```

## CSV columns

The CSV has 25 columns. The first 18 come from the extraction pipeline (pdf, citation_text, context, classification, case_name, plaintiff, defendant, volume, reporter, page, court, year, month, day, docket_number, is_westlaw, wl_number, review_reason). The last 7 are added by the verification workflow:

| Column | Values | Purpose |
|--------|--------|---------|
| `v_status` | `VERIFIED`, `LIKELY_REAL`, `POSSIBLE_MATCH`, `NOT_FOUND`, `SKIPPED`, (empty) | Verifier result. Empty = not yet run. |
| `v_confidence` | 0.0-1.0, (empty) | Confidence score |
| `v_url` | URL or empty | CourtListener match URL for QC |
| `v_matched_name` | case name or empty | What CL matched (for comparison) |
| `v_git_hash` | short hash or empty | Code version that produced this result |
| `qc_status` | `approved`, `rerun`, `duplicate`, `ignore`, `investigate`, `data`, (empty) | Human QC decision |
| `qc_notes` | free text | Human notes |

## QC status vocabulary

- **approved** -- verified result is correct, no action needed
- **rerun** -- needs re-verification after code fix (cleared automatically on next run)
- **duplicate** -- duplicate citation in the CSV, skip in future runs
- **ignore** -- not worth verifying (e.g. short cite, junk extraction)
- **investigate** -- QC issue that may require a code fix; add details to `TODO.md`
- **data** -- CL data gap; add details to `flp_contributions.md` section 6

## Post-run QC checklist

After each `verify_from_csv.py` run:

1. Review NOT_FOUND and POSSIBLE_MATCH items from the JSON sidecar
2. Set `qc_status` on reviewed rows in the CSV
3. Add any new `investigate` items to `TODO.md`
4. Add any new `data` items to `flp_contributions.md` section 6
