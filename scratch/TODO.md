# TODO

## Parser / Extraction

### Plaintiff name truncation (Priority 1)
The dominant false negative pattern. eyecite's case name boundary scanner stops too early on multi-word plaintiffs with abbreviations/punctuation. Examples from seed 256 verification run:
- "Acceptance Indem. Ins. Co. v. Shepard" -> extracted as "Ins. Co. v. Shepard"
- "Auto. Fin. Corp. v. Liu" -> extracted as "Fin. Corp. v. Liu"
- "Ferro Corp. v. Cook" -> extracted as "Corp. v. Cook"
- "Jones v. Tenn. Dep't of Homeland Sec." -> extracted as "In re Tenn. Dep't of Homeland Sec." (plaintiff dropped, "In re" fallback triggered)
- "Ramirez v. Humala" -> extracted as "In re Ramirez" (same pattern)

Root cause likely in eyecite's `_scan_for_case_boundaries()` or our regex fallbacks. The "In re" misclassification is especially problematic -- when eyecite fails to capture the plaintiff, our "In re" fallback fires and creates a completely wrong case structure.

### Short cite handling
eyecite may support short cites (e.g., "M.G., 566 P.3d at 146-147"). Would need to resolve back to the full citation earlier in the document.

### INSUFFICIENT_DATA status
Consider adding a dedicated `INSUFFICIENT_DATA` status to `VerificationStatus` when both court and date are missing, instead of returning NOT_FOUND. Court-only-missing is also problematic -- "In re Wright" with just a year is too weak. Options:
- New enum value returned when court is missing
- Or cap score / block match return when court is missing
- Note: WL citation "years" come from the volume number, not a court parenthetical -- weaker evidence

## Verification Improvements

### Semantic search fallback (CourtListener Citegeist)
CL supports semantic search via `semantic=true` (GET) or POST with embeddings. Only for `type=o`. Could help with:
- Abbreviation mismatches without client-side normalization
- Name variations where keyword search fails ("Estate of Elkins v. Pelayo" vs "Elkins v. California Highway Patrol")
- Multi-defendant cases where CL stores a different caption
- Best fit: new step between opinion search (Step 2) and RECAP search (Step 3), triggered only on failures
- See: https://www.courtlistener.com/help/api/rest/search/#semantic-search

### CL fuzzy search limitations
- "Fibertext" (cited) vs "Fibertex" (actual) -- single character difference defeats CL fuzzy search
- Docket number also differs (20-20720-Civ vs 1:20-cv-20718)
- Semantic search might help

## Eyecite Upstream

### PR for fork fixes
Holding until we've used the fork more. Need to verify fixes stable across more verification runs. Current fixes on rlfordon/eyecite branch `fix-pdf-metadata-parsing`:
1. Apostrophe truncation in `_process_case_name()` -- negative lookbehind fix
2. ParagraphToken boundary in `match_on_tokens()` -- single newline = space
3. Apostrophe in regex character classes (SHORT_CITE_ANTECEDENT_REGEX, etc.)

## FLP Contributions

See `scratch/flp_contributions.md` for detailed write-ups and drafted comments.

## Testing

### Justia diagnostic script
One-off script to compare NOT_FOUND citations against Justia to distinguish:
1. Real hallucinations (neither CL nor Justia finds it)
2. CL data gaps (Justia finds, CL doesn't -- report to FLP)
3. Our search bugs (CL has it, we're not finding it -- fix query)
NOT for production -- diagnostic only.

### Expand fake citations corpus
`tests/data/known_fake_citations.json` has 8 entries. Categories planned: hallucinated_case_name, wrong_name_real_citation, wrong_court, future_date, invalid_reporter, out_of_range_page. See `tests/data/README.md` for schema.

## Known CL API Limitations

Tracked in `tests/data/cl_api_issues.json`. All have workarounds implemented.

1. **Search abbreviation matching** (HIGH) - "Cnty." doesn't match "County". Workaround: client-side normalization. FLP aware (#3089, #3367).
2. **Docket parameter unreliable** (HIGH) - RECAP `docket` param ignored. Workaround: use `q` with quoted string.
3. **Case name variations** (MEDIUM) - CL stores different defendant than cited. Workaround: docket search + fuzzy matching.
4. **Missing citations field** (MEDIUM) - Some cases have empty citations. Workaround: fall through to opinion/RECAP search.
5. **State court coverage gaps** (LOW) - Some state courts incomplete. No workaround.

## Last Verification Results (seed 256, 2026-02-09)

36 sampled, 50 requested:
- 22 VERIFIED (61%), 3 LIKELY_REAL (8%), 5 POSSIBLE_MATCH (14%), 5 NOT_FOUND (14%), 1 SKIPPED (3%)
- 30/35 non-skipped found (86%)
- 4 of 5 NOT_FOUND are confirmed hallucinations
- Remaining NOT_FOUND: Versant (real but abbreviated name + no court, too little data)
- POSSIBLE_MATCH: 2 real (truncated plaintiffs), 1 party variation, 1 hallucination, 1 indeterminate
