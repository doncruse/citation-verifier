# Handoff — cl-coverage-offshoot, 2026-05-15 EOD

Picking up after the unified_review eyeball pass that surfaced false positives
and false negatives in the audited rescues. Ends with: corrected coverage
number (91.4%), new extraction prompt schema (not yet smoke-tested),
verifier-side plumbing that consumes the new fields, and a clear list of
deliverables/decisions for the next session.

## Deliverables the user wants

1. **Memo** describing findings + process for this coverage-offshoot,
   shareable with CourtListener / FLP. Should include graphs.
2. **Clean CSV** — `unified_review.csv` has 31 columns and is hard to read.
   Want a simplified view with ~8-10 columns.
3. **Code fixes** committed to the repo so CL can re-run on larger corpora.

## What landed in this session

### Done (committed)

- **Phase 6 dedup of short-form citations** (`17_build_unified_review.py`).
  Detects `594 U.S. at 442`, `523 U.S.`, `B225051`, `Id./Jd. at P` style
  cites. When a fuller sibling exists in the same opinion, the short-form
  is marked `duplicate_of_fuller_sibling` (out of numerator and denominator).
  When no antecedent exists, marks `excluded_incomplete_citation` (out of
  denominator only — except when it luckily citation-lookup-resolved). 28
  rows reclassified. Overall coverage went from 82.8% → 91.4%.
- **Extraction prompt schema** extended (`extract_citations.py`). Now asks
  for `month`, `day`, and `docket_number` in addition to the existing fields.
  Designed to dramatically improve district court WL/LEXIS fallback — those
  citations frequently carry a docket number that's a near-unique
  identifier when the caption has changed (Rule 25(d), SSA anonymization,
  John/Jane Doe reveal).
- **`12_stratify.py`** threads the new fields from `real_extractions/*.json`
  → `final_200.csv` (uses `.get()` so older JSON without these keys still
  works — they just propagate as None).
- **`15_staged_fallback_rigorous.py`** `build_full_citation_str()` rewritten
  to emit Bluebook-style dates ("Jan. 8, 2014" instead of just "2014") and
  append "No. <docket>" suffix. The existing `parse_citation()` already
  recognizes these formats and populates `ParsedCitation.month`/`.day`/
  `.docket_number` — so the Stage B RECAP `docket_number` filter (line
  134-143) starts working automatically without verifier changes.

### Not done (pending)

See task list. Highlights:

- **Task #1 (audit false POSITIVES)**: Wilson/Wilmington/Rose Way/Thurman.
  Audit's `parties_present` test greenlights matches whose cited reporter
  cite is contradicted by the cluster's own `citations[]`. Fix: when
  `cite_test=='no'` AND cluster has populated `citations[]`, treat as
  LIKELY_FALSE. Implementation is a 5-line edit in
  `16_audit_rescues.py` around line 400. Independent of any data re-run.
- **Task #8 (audit false NEGATIVES)**: The 7 cases the user investigated.
  Splits 3 ways (see below).
- **Task #9 (smoke test the new prompt)**: gated on `claude -p` auth
  working. Currently the subprocess returns "Not logged in" even after
  CLI `/login`. User said this is an intermittent problem they've seen
  before.
- **Task #10 (memo)**, **Task #11 (clean CSV)**, **Task #12 (hand-correct vs
  re-extract decision)**: the user-facing deliverables.

## False-negative categorization (Task #8)

User's deep investigation of the 7 cases labeled `rescue_was_false_positive`
revealed three distinct patterns. Recording in detail because the audit fix
strategy is different for each.

### Category 1 — Right cluster, audit overruled (3 cases)

| Cited | Matched cluster | User-confirmed URL |
|---|---|---|
| Gilliard v. McWilliams, 2019 WL 3304707 | Gilliard v. Gruenberg | /opinion/4642011/ |
| Preston v. Smith, 2023 WL 5337430 | Preston v. Unidentified | /opinion/9729396/ |
| Viken Detection v. Doe, 2019 WL 5268725 | Viken Detection v. Bradshaw | /opinion/9731515/ |

Stage A returned the correct cluster. Audit overruled on
`parties_present` because cited surname (McWilliams/Smith/Doe) doesn't
appear in the new caption (Rule 25(d) substitution / Doe reveal).
`cite_test` was inconclusive because these clusters have empty
`citations[]` (CL ingestion lag for newer opinions).

**Fix path**: in `audit_one`, when court+date both pass and cluster
`citations[]` is empty (no negative signal), don't return LIKELY_FALSE on
parties alone — return AMBIGUOUS at minimum. Better: when extraction
captures `docket_number`, cross-check against the cluster's docket; if
docket matches, return VERIFIED_TRUE regardless of name divergence.

### Category 2 — Wrong cluster, real opinion exists (2 cases)

| Cited | Audit matched (wrong) | Real opinion |
|---|---|---|
| Michael B. v. Berryhill, 2019 WL 2269962 | Hansen v. Berryhill (9674062) | Buschman v. Berryhill (**9674181**) |
| John S. v. Bisignano, 2025 WL 1505405 | Hejna v. Bisignano (10663671) | Sims v. Bisignano (**10593230**) |

CL/PACER caption is the real surname; brief used SSA pseudonym.
Name-based search will never find these. Audit correctly identified
Stage A's wrong match, but verifier never tried Stage B (RECAP) because
Stage A returned non-NOT_FOUND.

**Fix path**: requires `docket_number` from new extraction prompt. With
docket numbers, Stage B's RECAP `docket_number` search (already
implemented at `15_staged_fallback_rigorous.py:134`) will land on the
correct PACER docket. Need to additionally let Stage B run when Stage A's
score is below some threshold even if not strictly NOT_FOUND.

### Category 3 — Truly docket-only in CL (2 cases)

| Cited | CL has | User URL |
|---|---|---|
| Doe v. Lawrence Gen. Hosp., 2025 WL 2808055 | docket only | /docket/69539673/ |
| Hunter v. CCSF, 2013 WL 6088409 | docket only | /docket/5929390/ |

CL has the docket via RECAP but no opinion cluster ingested. Audit's
LIKELY_FALSE on Stage A's wrong-cluster matches (Fitzgerald, Davis) was
correct. Stage B docket-number search would land on the right docket.

**Fix path**: same as Category 2.

## Plan for next session

Suggested order:

1. **Hand-correct the 7 false negatives** (1 hour, no auth needed).
   Manually edit `final_200.csv` to fill in `docket_number`, `month`, `day`
   for those 7 rows from the cited briefs/opinions. Re-run only
   `15_staged_fallback_rigorous.py` → `16_audit_rescues.py` →
   `17_build_unified_review.py`. This gives a stable corrected coverage
   number for the memo.

2. **Implement Task #1 audit fix** (15 min). Edit `16_audit_rescues.py:392-413`
   to add: `elif source == "cluster" and cite_test == "no" and matched_meta.get("citations"): verdict = "LIKELY_FALSE"`. Re-run audit + unified rollup.
   Eliminates Wilson/Wilmington/Rose Way/Thurman false positives.

3. **Build the simplified CSV view** (Task #11, 30 min). Either an
   additional writer in `17_build_unified_review.py` (`unified_review_concise.csv`)
   or a separate one-shot script. Columns: cited_tier, cited_case_name,
   citation_string, cited_year, FINAL_STATUS, FINAL_REASON, matched_name,
   matched_url. Maybe also cluster citations for rescued rows.

4. **Write the memo** (Task #10). Should cover:
   - What this offshoot did and why (the 2026-05-13 publication-plan
     redirected from one-off lookups to broader coverage measurement)
   - Methodology: 78 mined opinions → Haiku extraction → stratified 250-row
     sample → citation_lookup → rigorous staged fallback → audit
   - Findings:
     - 91.4% coverage overall after Phase 6 correction (was 82.8% raw)
     - Coverage gradient: SCOTUS 100% → Federal_District 85% → State_IAC 84%
     - Phase 6 found 28/250 rows were short-form duplicates/unmeasurables
       (mostly pin-cites the LLM emitted as separate rows from their
       antecedents)
     - 4 audit false POSITIVES caught by user's eyeball pass (Wilson,
       Wilmington, Rose Way, Thurman) — cluster's `citations[]` contradicted
       cited cite
     - 7 audit false NEGATIVES surfaced by user's investigation, split 3:2:2
       across categories above. All 5 in-opinion-DB cases trace to the same
       root cause: caption divergence between cited form and CL's record.
   - Graphs: corrected per-tier coverage bar chart; FINAL_STATUS pie or
     stacked bar; before/after Phase 6 overall.
   - Recommendations for CL / FLP: ingest docket numbers as a search field
     for opinion clusters; flag caption changes (Rule 25(d), anonymization
     reveal) more visibly.

5. **Decide on re-extraction** (Task #12). If the memo is internal, hand
   correction is fine. If we hand the corpus + code to CL for a larger
   re-run, the new prompt with `month`/`day`/`docket_number` is the canonical
   v2 version they should use. The smoke test (task #9) gates that
   decision — need to confirm Haiku populates the new fields reliably
   before claiming the prompt is production-ready.

## Files and their state

| File | Status |
|---|---|
| `extract_citations.py` | NEW prompt schema (month/day/docket_number). Not smoke-tested. Synthetic test sample updated. |
| `12_stratify.py` | Threads new fields. Safe with old JSON (fields default to None). |
| `15_staged_fallback_rigorous.py` | `build_full_citation_str` emits Bluebook date + "No. <docket>". |
| `17_build_unified_review.py` | Phase 6 logic. Outputs `unified_review.csv` with extra `duplicate_of_fuller_sibling`/`excluded_incomplete_citation` statuses and a corrected-coverage block in summary. |
| `unified_review.csv` | Reflects Phase 6 — 91.4% overall coverage. |
| `unified_review.xlsx` | Open Excel file; NOT committed yet (and Excel lock file `~$unified_review.xlsx` is local-only). Decide whether to commit the .xlsx separately for non-coder reviewers. |
| `16_audit_rescues.py` | UNCHANGED — Task #1 fix not applied yet. |
| `real_extractions/*.json` | UNCHANGED — pre-date the new prompt schema. |

## What `claude -p` auth issue looked like

In this session, `claude -p --output-format json --model haiku < some_input`
returned `{"result": "Not logged in · Please run /login"}` even after the
CLI itself was logged in. The CLI's auth state didn't propagate to the
subprocess. User said this is an intermittent issue. If it persists at home,
worth filing as a Claude Code issue — but for the work above, only Task #9
depends on it.
