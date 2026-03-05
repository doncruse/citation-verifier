# TODO

## PDF Download Feature (in progress)

Added checkboxes + "Download PDFs" button to main page (`localhost:8000`). Backend resolves `matched_url` to downloadable PDF, bundles into zip.

### What works
- Frontend: checkboxes, select-all, download button with count, progress status
- RECAP documents: API -> `filepath_local` -> `storage.courtlistener.com` download (works)
- Opinion PDFs: resolves via cluster API -> sub_opinions -> opinion API -> `local_path` (pdf/) or `download_url`
- Skip feedback: UI shows "Downloaded N PDFs (M skipped -- no PDF available)" via X-Downloaded/X-Skipped headers

### Remaining issues
1. ~~**CloudFront WAF blocks server-side opinion PDF downloads.**~~ FIXED. Now resolves through API instead of appending `/pdf/`.
2. ~~**Opinion API resolution needs work.**~~ FIXED. Strategy: `local_path` starting with `pdf/` -> storage URL; else `download_url` (filtering .html/.htm/.xml). Many older opinions (Kitchen v. Herbert, MacPherson, Youngstown) have no PDF available — returns None gracefully.
3. ~~**Rate limiting for PDF resolution.**~~ FIXED. Both phases now use `asyncio.gather` with bounded concurrency: resolution goes through the client's existing rate limiter (0.5s interval + semaphore=5), downloads use a separate semaphore(5) for storage.courtlistener.com.
4. ~~**No user feedback when PDFs are skipped.**~~ FIXED. UI now shows downloaded vs skipped counts.

### Files modified
- `src/citation_verifier/client.py` — `get_pdf_url()`, `_first_recap_doc_url()` on `AsyncCourtListenerClient`
- `web/app.py` — `POST /api/download-pdfs` endpoint, `_sanitize_filename()`
- `web/static/index.html` — checkbox column, select-all, Download PDFs button + JS (now the Debug page at `/debug`)

## ~~Priority 0 — Tech debt~~ DONE

### ~~Deduplicate verify() and verify_async()~~ DONE
Extracted 7 shared helpers (`_process_citation_lookup_hit`, `_check_adjacent_page_cluster`, `_build_search_params`, `_build_fallback_result`, `_docket_date_ranges`, `_extract_docket_entry_docs`, `_has_recap_date_match`). Sync/async methods are now thin I/O wrappers calling shared logic. 1682 -> 1496 lines. Fixed 2 async parity test failures caused by the prior drift.

## Priority 1 — Bugs (wrong results)

### Citation mismatch detection ("Check Cite" status)
When the opinion search (step 2) finds a case by name but the reporter citation doesn't match (e.g., searched for `742 F. Supp. 2d 672` but CL has `759 F. Supp. 2d 822`), the result currently shows as VERIFIED/LIKELY_REAL. A wrong volume/page is a big deal — it means the citation in the brief is incorrect even though the case is real.

Proposed fix: after the opinion search finds a match, compare the matched case's citations against the searched citation. If the reporter citation doesn't match, flag it with a new status or a `citation_mismatch` field so the UI can show "Check Cite" instead of "Ready." This distinguishes three cases:
- **Ready**: case found, citation confirmed
- **Check Cite**: case found by name, but cited reporter/volume/page is wrong
- **Review Name**: something found, but case name doesn't match well

Example: `In re Chinese-Manufactured Drywall Products Liability Litigation, 742 F. Supp. 2d 672 (E.D. La. 2010)` — case exists at `759 F. Supp. 2d 822` but not at the cited location.

### INSUFFICIENT_DATA: skip verification entirely
When both court and date are missing, return a new `INSUFFICIENT_DATA` status immediately — no API calls. Court-only-missing is also borderline ("In re Wright" with just a year is too weak). WL citation "years" come from the volume number, not a court parenthetical — weaker evidence.
- Example: In re Marriage of Schultz, 2019 WL 5089859 (2015) — parser dropped court and case number, got year wrong (2015 vs actual). Matched wrong case in wrong court (0.59).

### State court RECAP leak (partially fixed)
`is_federal_court()` now gates RECAP API calls, but leaks remain:
- Oddi-Sampson v. State, 201 N.E.3d 749 (Ind. 2022) — court `ind`, matched Garner v. Biden (0.27), completely unrelated federal docket. `is_federal_court("ind")` returns False, so gate should work — needs investigation.
- Reinlasoder v. City of Billings, 455 P.3d 477 (Mont. 2020) — court `mont`, matched Wilson v. Mr. Bludsworth (0.27) via RECAP. Source: Thornton_v._Flathead_County_USA_23_January_2026.pdf.

### Cross-state opinion match (Graves)
Graves v. State, 773 N.E.2d 157 (Ind. 2002) — matched Graves v. State in a *different state* (0.70). Not a RECAP leak (matched via opinion search), but a cross-state match problem: state mismatch should disqualify results. https://www.courtlistener.com/opinion/1613021/graves-v-state/

### False positives: hallucinations scoring POSSIBLE_MATCH
Confirmed hallucinations that scored above NOT_FOUND threshold:
- Thompson v. Best (0.62) — matched Thompson v. Thompson in wrong court. Common surname inflates score.
- Lopez v. Bank of Am., N.A. (0.65) — docket and date mismatch should push below threshold. https://www.courtlistener.com/docket/5887170/85/lopez-v-bank-of-america-na/
- Benjamin v. Costco (0.53) — matched In re Monogioudis (completely wrong)
- In re Hudson (0.50) — matched In re: Hudson (different case, date off by centuries)
- Pointe Wholesale v. Vilardi (0.47), South Pointe Wholesale v. Vilardi (0.41), Reed v. ZipRecruiter (0.43), Mavy v. Comm'n of Soc. Security (0.42), Mungo v. State (0.51)
- Marion v. Hollis Cobb Assocs. (0.41) — wrong name, wrong date, should be well below threshold. https://www.courtlistener.com/docket/69958782/15/winer-v-mohammad/

Consider penalizing more when the distinctive party (defendant) doesn't match at all.

### Court ID mismatch: dccrimct vs dc
Weatherly v. Second Nw. Coop. Homes Ass'n scored only 53% partly because eyecite returned `dccrimct` but CL has `dc`. Either treat these as equivalent in court map, or fall back to prefix/substring match.
- Francis v. Rehman, 110 A.3d 615 (dccrimct 2015) — NOT_FOUND despite exact reporter match, same root cause. https://www.courtlistener.com/opinion/2782310/michael-francis-and-queue-llc-v-munir-rehman-and-hak-llc/

## Priority 2 — Improvements (better results)

### Plaintiff name truncation (eyecite upstream)
The dominant false negative pattern. eyecite stops too early on multi-word plaintiffs with abbreviations/punctuation:
- "Acceptance Indem. Ins. Co. v. Shepard" -> "Ins. Co. v. Shepard"
- "Auto. Fin. Corp. v. Liu" -> "Fin. Corp. v. Liu"
- "Jones v. Tenn. Dep't of Homeland Sec." -> "In re Tenn. Dep't of Homeland Sec." (plaintiff dropped, "In re" fallback)

Root cause likely in eyecite's `_scan_for_case_boundaries()`.

### Missing abbreviations in name_matcher
`LEGAL_ABBREVIATIONS` doesn't cover all Indigo Book terms. Known gaps:
- `Pro.` -> `Professional` (Smart v. Pro. Grp.)
- `Grp.` -> `Group` (Smart v. Pro. Grp.)
- Smart case: correct match found but scored only POSSIBLE_MATCH (0.60) because of these missing expansions.

### Composite opinion-likelihood + progressive date widening + page count
Full plan at `.claude/plans/woolly-nibbling-axolotl.md`. Three changes:
1. **Composite `_opinion_likelihood(desc, is_free, page_count)`** replaces separate `is_free` and `_doc_type_priority` tiebreakers. Prevents `is_free` on a memo endorsement from beating a real opinion (Cohen fix). Tier: opinion+free=3, opinion=2, order+free=2, order=1, free-only=1, none=0. Page count breaks ties within tier.
2. **Progressive date widening** in `_fetch_docs_for_docket`: exact date → month±1 → full year. Prevents year-range fallback from pulling docs 6 months away when we have month precision (HoosierVac fix).
3. **Page count as final tiebreaker** — `page_count` from docket-entries API. Longer docs more likely to be opinions (13-page opinion > 2-page memo endorsement).

### ~~`is_free_on_pacer` boost — manual testing~~ DONE
Tested via investigate rerun. Dukuray fixed (doc 40, exact date match). Cohen and HoosierVac need composite opinion-likelihood (above).

### Post comment on CL #6963
Draft ready at `scratch/drafts/cl-6963-is-free-on-pacer.md`. Post when ready.

### RECAP document selection (Patterns A, B, D)
**Pattern A** (non-substantive doc filtering): Lacey v. State Farm still chose "Order on Motion for Leave to File Document Under Seal" (POSSIBLE_MATCH 0.79). Fix: use `"leave to file" in desc` (contains) instead of `startswith`.

**Pattern B** (doc type priority — API issue): Mata v. Avianca and Davis v. Marion County still chose wrong docs. Correct docs (Opinion, R&R) likely not in `recap_documents` from search API. Investigate: docket-entries API followup query?

**Pattern D** (wrong doc, imprecise date matching):
- Wadsworth v. Walmart: chose "Memorandum in Opposition" (LIKELY_REAL 0.90)
- Dobson v. U.S. Bank: chose "Judgment" (POSSIBLE_MATCH 0.71)
- Moore v. Md. Hemp Coal.: NOT_FOUND 0.37, correct doc found but name mismatch ("Charm City Hemp v. Moore" vs "Moore v. Md. Hemp Coal.")
- Gauthier v. Goodyear: correct case (LIKELY_REAL 0.90) but wrong docket entry (doc 53 vs correct doc 48). https://www.courtlistener.com/docket/67624744/48/gauthier-v-goodyear-tire-rubber-co/
- HoosierVac: correct case (LIKELY_REAL 0.85) but wrong document. https://www.courtlistener.com/docket/68879596/129/mid-central-operating-engineers-health-and-welfare-fund-v-hoosiervac-llc/

### Semantic search fallback (CourtListener Citegeist)
CL supports `semantic=true` for `type=o`. Could help with abbreviation mismatches, name variations, multi-defendant cases. Best fit: new step between opinion search (Step 2) and RECAP search (Step 3), triggered only on failures. See: https://www.courtlistener.com/help/api/rest/search/#semantic-search

## Priority 3 — Parser edge cases

### Complex case number parsing (Button v. Doherty)
"Button v. Doherty, Case No. 24 Civ. 5026 (JPC) (KHP), 2025 WL 2776069 at *5 n. 7 (S.D.N.Y. Sept. 30, 2025)" — multiple parentheticals in case number may confuse court/year extraction.

### Short cite handling
eyecite may support short cites (e.g., "M.G., 566 P.3d at 146-147"). Would need to resolve back to the full citation earlier in the document.

### Docket number format variants
- Aikens v. Nw. Dodge: docket `03 C 7956` not parsed correctly, should expand to `03-cv-7956`. https://www.courtlistener.com/docket/5359695/108/aikens-v-northwestern-dodge/
- Fibertext Corp.: docket `20-20720-Civ` should parse as `20-cv-20720`. NOT_FOUND (0.32), matched wrong case.

## Investigate — needs manual research

### Johnson v. Dunn (slip opinion format)
Real case at https://www.courtlistener.com/docket/62980057/204/johnson-v-dunn/ but NOT_FOUND. Citation: `Johnson v. Dunn, -- F. Supp. 3d ----, 2025 WL 2086116 (N.D. Ala. July 23, 2025)`. The `-- F. Supp. 3d ----` slip-opinion format likely threw off citation lookup, and RECAP should have caught it.

### ~~Bidirectional abbreviation normalization (Priority 1)~~ PARTIALLY FIXED
Added missing abbreviations to both `name_matcher.py` (LEGAL_ABBREVIATIONS) and `parser.py` (`_normalize_case_name()`). The name_matcher now normalizes both the cited name AND the CL result name through the same expansion pipeline. New abbreviations: `comm'r` → commissioner, `info` → information, `sol`/`sols` → solution/solutions, `fin` → finance, `nw`/`sw` → northwest/southwest, `ass'n` → association, `coop` → cooperative. Also added `&` → `and` conversion in `_normalize()`.

Fixed abbreviation mismatches:
- ~~`Comm'r` vs `Commissioner` (Russomanno)~~ ✓
- ~~`&` vs `and` (King v. Police & Fire)~~ ✓
- ~~`Info. Sols.` vs `Information Solutions` (Dukuray)~~ ✓
- ~~`Fed.` vs `Federal` (King)~~ ✓ (was already handled)
- ~~`Gen. Ins. Co.` vs `General Insurance Company` (Lacey v. State Farm)~~ ✓ (was already handled)
- ~~`Nw.` vs `Northwest` + `Ass'n` vs `Assoc.` (Weatherly — scored 53%)~~ ✓
- ~~`Fin.` vs `Finance` + `Corp.` vs `Corporation` (Auto Fin. Corp. v. Liu — scored 59%)~~ ✓

Remaining (not abbreviation issues — different root causes):
- First names in CL but not in citation (Glass, Todd v. vs Glass v.) — name length mismatch, not abbreviation
- Truncated plaintiff: `Welfare Fund` vs `Mid Central Operating Engineers Health and Welfare Fund` (HoosierVac) — plaintiff truncation issue
- Reporter citation not confirmed when CL simply has no citations on file (Shahid v. Esaam) — CL data gap

### Cohen (common name)
United States v. Cohen, 724 F. Supp. 3d 251 (S.D.N.Y. 2024). Real case but NOT_FOUND. Common defendant name + CL search limitations. Semantic search may help.

### Hayes (common name)
U.S. v. Hayes, 763 F. Supp. 3d 1054 (E.D. Cal. 2025). Confirmed real, NOT_FOUND. Appears twice in seed 3193 batch (from two different PDFs).

### Rocha v. Fiedler, 2025 WL 1219007 (9th Cir. Apr. 28, 2025)
NOT_FOUND despite opinion existing in CL: https://www.courtlistener.com/opinion/10386186/rocha-v-fiedler/. Unclear why search missed it.

### Fibertext fuzzy search (possibly resolved)
"Fibertext" (cited) vs "Fibertex" (actual) — single character difference defeated CL fuzzy search. May have been resolved by CL improvements or our normalization fixes. Needs rerun to confirm. (Docket parsing issue tracked separately in Priority 3.)

## Eyecite Upstream

### PR for fork fixes
Holding until we've used the fork more. Current fixes on rlfordon/eyecite branch `fix-pdf-metadata-parsing`:
1. Apostrophe truncation in `_process_case_name()` -- negative lookbehind fix
2. ParagraphToken boundary in `match_on_tokens()` -- single newline = space
3. Apostrophe in regex character classes (SHORT_CITE_ANTECEDENT_REGEX, etc.)

## QC Review Findings

Items flagged during QC review (uncategorized — sort periodically).

**Dukuray v. Experian Info. Sols., No. 23 Civ. 9043, 2024 WL 3812259 (S.D.N.Y. July 26, 2024)**
Source: melissa_wilcox_v._matthew_a._gingrich.pdf. Verification: POSSIBLE_MATCH (0.5589). Matched: https://www.courtlistener.com/docket/67881565/43/dukuray-v-experian-information-solutions/. Notes: no slightly different date! https://www.courtlistener.com/docket/67881565/40/dukuray-v-experian-information-solutions/. Added automatically from QC review.

## FLP Contributions

See `scratch/flp_contributions.md` for detailed write-ups and drafted comments.

### RECAP-only federal court opinions (contribution #5)
Growing list of confirmed real cases found only in RECAP, not in the opinions DB. Now 16 unique cases (up from 9). CL's `recap_into_opinions` (#3790) converted 317K+ civil cases in Oct 2025, but gaps remain. See `flp_contributions.md` section 5.

## Known CL API Limitations

Tracked in `tests/data/cl_api_issues.json`. All have workarounds implemented.

1. **Search abbreviation matching** (HIGH) - "Cnty." doesn't match "County". Workaround: client-side normalization. FLP aware (#3089, #3367).
2. **Docket parameter unreliable** (HIGH) - RECAP `docket` param ignored. Workaround: use `q` with quoted string.
3. **Case name variations** (MEDIUM) - CL stores different defendant than cited. Workaround: docket search + fuzzy matching.
4. **Missing citations field** (MEDIUM) - Some cases have empty citations. Workaround: fall through to opinion/RECAP search.
5. **State court coverage gaps** (LOW) - Some state courts incomplete. No workaround.

## Testing

### Justia diagnostic script
One-off script to compare NOT_FOUND citations against Justia to distinguish: real hallucinations, CL data gaps, our search bugs. Diagnostic only.

### Expand fake citations corpus
`tests/data/known_fake_citations.json` has 8 entries. Categories planned: hallucinated_case_name, wrong_name_real_citation, wrong_court, future_date, invalid_reporter, out_of_range_page. See `tests/data/README.md`.

## verify-brief Skill

### Baseline test (RED phase)
Run the brief verification task WITHOUT the skill loaded to establish what Claude does naturally. Steps:
1. Rename `~/.claude/skills/verify-brief/SKILL.md` → `SKILL.md.bak`
2. Open fresh Claude Code session in this folder
3. Give it the Kettering brief: "verify the citations in this brief" (same input as first test)
4. Observe: Does it use `citation_verifier`? Read opinions? Assess claims? What structure does it use?
5. Rename skill back when done
6. Compare to skill-guided run — document what the skill improves

### Word doc support
Not tested yet. Options: python-docx dependency, or just have user paste text.

### Second test run
Re-run `/verify-brief` on Kettering brief with iteration 1 fixes. Document results in `briefs/kettering-v-collier/skill-test-2-feedback.md`.

### Valve v. Rothschild run retrospective (2026-03-04)
Full retrospective at `.claude/projects/-Users-fordon-4-Projects-citation-verifier/memory/verify-brief-retrospective.md`. Key takeaways:
- **AskUserQuestion broken** — remove from skill; auto-accept high-confidence, always generate HTML report.
- **Phase 2 needs async batch mode** — run all citation lookups (step 1) concurrently first, then steps 2-3 only for unresolved. Mirrors the web app approach. Could cut Phase 2 time significantly. Requires new `AsyncCitationVerifier` or batch method in the library.
- **Phase 1 CSV writing is slow** — Opus extraction is needed, but CSV writing from structured data could be Haiku.
- **Fortune Dynamic wrong text** — CL opinion page had Arthur v. Torres attached. Add sanity check: compare downloaded case name to expected.
- **Brief had 51% Red citations** — fabricated quotes, cases cited for opposite holdings, inapposite cases. Patterns consistent with AI-generated legal writing.

## Future Ideas

Moved to `scratch/ROADMAP.md` — covers client-side BYOK, WL/Lexis data contributions, semantic search, and more.
