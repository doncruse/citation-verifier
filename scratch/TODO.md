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

### Complex case number parsing (Button v. Doherty)
"Button v. Doherty, Case No. 24 Civ. 5026 (JPC) (KHP), 2025 WL 2776069 at *5 n. 7 (S.D.N.Y. Sept. 30, 2025)" — suspect parsing issue with `Case No. 24 Civ. 5026 (JPC) (KHP)` format. The multiple parentheticals in the case number may confuse court/year extraction. Needs investigation.

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

### Bidirectional abbreviation normalization (Priority 1)
Currently we normalize cited names → expanded form (Cnty. → County) to match CL. But CL also stores expanded forms that don't match our abbreviated citations. Confirmed correct matches scoring low due to abbreviation mismatches (from seed 42, 3193, and 5270 runs):
- `Comm'r` vs `Commissioner` (Russomanno)
- `&` vs `and` (King v. Police & Fire)
- `Info. Sols.` vs `Information Solutions` (Dukuray)
- `Fed.` vs `Federal` (King)
- First names in CL but not in citation (Glass, Todd v. vs Glass v.)
- `Gen. Ins. Co.` vs `General Insurance Company` (Lacey v. State Farm)
- Truncated plaintiff: `Welfare Fund` vs `Mid Central Operating Engineers Health and Welfare Fund` (HoosierVac)
- Reporter citation not confirmed when CL simply has no citations on file (Shahid v. Esaam)
- `Nw.` vs `Northwest` + `Ass'n` vs `Assoc.` (Weatherly — scored 53% for correct match)
- `Fin.` vs `Finance` + `Corp.` vs `Corporation` (Auto Fin. Corp. v. Liu — scored 59%)

Fix: normalize both the cited name AND the CL result name before comparison. Either expand both or strip both to a canonical form. The name_matcher should handle this.

### RECAP document selection improvements (Priority 2)
The verifier frequently picks the wrong RECAP document from a docket. 10 confirmed cases across 3 patterns:

**Pattern A: Non-substantive doc chosen over substantive (fix `_is_substantive_doc()` / `_doc_type_priority()`)**
- Lacey v. State Farm: chose "Leave to File Document Under Seal" (doc 117) over "Order" (doc 119), same day. Correct: https://www.courtlistener.com/docket/68872463/119/
- O'Brien v. Flick (SD Fla): chose "Transcript Order Form" (doc 28) — not the actual order. Case behind paywall, can't identify correct doc.
- Coronavirus Reporter v. Apple: chose "Proposed Order" (doc 89/1) over "Order" (doc 102). Correct: https://www.courtlistener.com/docket/69434738/102/

Fix: add negative keywords ("leave to file", "transcript order form", "proposed order", "proposed") that disqualify docs. A "proposed order" is not an order.

**Pattern B: Lower-priority substantive doc over higher-priority**
- Davis v. Marion County: chose "Order" (doc 70) over "Report & Recommendation" (doc 71). In magistrate cases the R&R is the opinion-equivalent. Correct: https://www.courtlistener.com/docket/69325037/71/
- Mata v. Avianca: chose "Clerk's Judgment" (doc 59) over "Opinion" (doc 54). Correct: https://www.courtlistener.com/docket/63107798/54/

Fix: add "report" and "recommendation" to `_doc_type_priority()` at priority 2 (same as opinion/memorandum). Add "clerk's judgment" at priority 0 (below order).

**Pattern C: Docket-level match when document match exists**
- Mali v. British Airways: returned docket URL instead of document #44 (the actual opinion, dated 2018-07-06 — exact date match). Correct: https://www.courtlistener.com/docket/7378483/44/

Investigate why `_pick_best_recap_doc()` didn't find doc #44. May be a search result issue (doc not in `recap_documents` response).

**Pattern D: Wrong document due to imprecise date matching**
- Wadsworth v. Walmart: wrong doc selected, no exact date available to disambiguate
- Dobson v. U.S. Bank: wrong doc, not exact same date
- Moore v. Md. Hemp Coal.: wrong doc (parties also reversed — "Charm City Hemp v. Moore")

### RECAP score too conservative for confirmed matches
RECAP-only matches get a 0.6x docket-only discount, and WL citations almost never confirmed in CL (CL doesn't store them). This double penalty means real RECAP matches top out around 60-75% even when name + court + date all match. Consider:
- Boosting RECAP document matches (not docket-only) when court and date align
- Not penalizing WL citation mismatch when CL simply has no citations on file (empty vs contradictory)

### Investigate: Johnson v. Dunn false negative
Real case at https://www.courtlistener.com/docket/62980057/204/johnson-v-dunn/ but verifier returned NOT_FOUND. Citation: `Johnson v. Dunn, -- F. Supp. 3d ----, 2025 WL 2086116 (N.D. Ala. July 23, 2025)`. The `-- F. Supp. 3d ----` slip-opinion format (no page number) likely threw off citation lookup, and RECAP search should have caught it but didn't. Investigate why.

### Investigate: United States v. Cohen false negative
Real case but verifier can't find it. Citation: `United States v. Cohen, 724 F. Supp. 3d 251 (S.D.N.Y. 2024)`. Common defendant name + CL search limitations. Semantic search may help.

### Investigate: U.S. v. Hayes false negative
Real case (confirmed by user QC) but verifier returns NOT_FOUND. Citation: `U.S. v. Hayes, 763 F. Supp. 3d 1054 (E.D. Cal. 2025)`. Appears in multiple PDFs. Probably common defendant name + CL coverage/search limitations. Appears twice in seed 3193 batch (from two different PDFs), both NOT_FOUND.

### Investigate: In re Suday, 2025 WL 3193777
Returned NOT_FOUND (0.29 confidence, matched Chinese Drywall litigation). May be a data issue (case not in CL) or a search issue. Needs manual investigation to determine whether case exists in CL at all.

### CRITICAL: Pettway v. American Savings — VERIFIED hallucination (Priority 1)
Citation: `Pettway v. American Savings & Loan Association, 197 F. Supp. 489 (N.D. Ala. 1961)`. Citation lookup found 197 F. Supp. 489, which belongs to "American National Insurance v. Smith". Verifier returned VERIFIED at 100% confidence despite completely different case names. User QC confirmed this is a hallucination.

Root cause: `_names_match_citation_lookup()` extracts defendant surname "American" from "American Savings & Loan Association", checks if "american" appears in "American National Insurance v. Smith" → YES. But these are completely different parties — "American" is a common word, not a distinctive surname.

Fix options:
- Skip single common words as surnames (American, National, United, General, etc.)
- Require surname match of 2+ words when the first word is common
- Or require higher similarity threshold for single-word surnames that are dictionary words
- This is the most critical false positive found so far — a VERIFIED hallucination undermines trust

### False positives: hallucinations getting POSSIBLE_MATCH
Seven confirmed hallucinations scored as POSSIBLE_MATCH across seed 42/3193/5270 runs:
- Pointe Wholesale v. Vilardi (0.47) → matched Thompson v. Martuscello (completely wrong case)
- South Pointe Wholesale v. Vilardi (0.41) → matched US v. Kenner (completely wrong case)
- Reed v. ZipRecruiter (0.43) → matched Adzhikosyan v. AT&T Corp (completely wrong case)
- Thompson v. Best (0.62) → matched Thompson v. Thompson in wrong court (ohioctapp vs indctapp)
- In re Hudson (0.50) → matched In re: Hudson (different case, date off by centuries — 1812 vs modern)
- Mavy v. Comm'n of Soc. Security (0.42) → matched Nina Alley v. County of Pima (completely wrong)
- Mungo v. State (0.51) → matched Freeman v. State (completely wrong name, citation doesn't match)
- Benjamin v. Costco (0.53, seed 3193) → matched In re Monogioudis (completely wrong)

The Thompson v. Best case is the most concerning POSSIBLE_MATCH — 0.62 confidence for a hallucination. The common surname "Thompson" in both cited and matched case names inflates the score. Consider whether name_matcher should penalize more when the distinctive party (defendant) doesn't match at all.

Note: Mavy and South Pointe Wholesale both scored ~0.42 for completely wrong cases. These should score well below 0.40 (our NOT_FOUND threshold). The 0.6x RECAP docket discount isn't enough when the name is a total mismatch.

### Court ID mismatch: dccrimct vs dc (Weatherly)
Weatherly v. Second Nw. Coop. Homes Ass'n scored only 53% partly because eyecite returned court `dccrimct` but CL has `dc`. These refer to the same court (D.C. Superior Court). Either our court map should treat these as equivalent, or we should fall back to a prefix/substring match when the exact court ID doesn't match.

### Thomas v. Pangburn: parser issue causes low confidence
Thomas v. Pangburn, 2024 WL 329947 (S.D. Ga. Jan. 29, 2024) — RECAP found the exact case with matching name and date, but scored only 43%. The name mismatch diagnostic shows the parser extracted the case name as "In re CV-46" instead of "Thomas v. Pangburn". This is a parser/extraction issue where docket number junk ("CV-46") got misidentified as a case name. The verifier correctly found the right case but the broken parse prevented a good score.

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

### RECAP-only federal court opinions (contribution #5)
Growing list of confirmed real cases found only in RECAP, not in the opinions DB. Now 16 unique cases (up from 9). CL's `recap_into_opinions` (#3790) converted 317K+ civil cases in Oct 2025, but gaps remain — civil cases from 2008–2025 still missing, plus criminal cases not yet processed. See `flp_contributions.md` §5.

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

## Future Ideas

### Contribute WL/Lexis citation strings for confirmed cases to FLP
When our tool confirms a citation is real (VERIFIED or LIKELY_REAL), we know the WestLaw or Lexis citation string (e.g. "2018 WL 01581301") corresponds to a real opinion. CL often doesn't have these proprietary citations on file — the `citation` field is empty or only has reporter cites. We could collect these confirmed WL/Lexis citation strings and contribute them to FLP as metadata, not the documents themselves. Something like "we've confirmed that cluster X / docket Y corresponds to 2018 WL 01581301."

This would turn the verification pipeline into a data flywheel: every confirmed citation enriches CL's citation metadata, which in turn improves citation lookup for everyone.

Would need to figure out:
- Whether FLP wants this kind of contributed citation metadata
- What format to submit (bulk CSV? API? issue with list?)
- Whether there's a "possible citation" or "unverified citation" field they could use
- How to batch these up (per-case is too noisy, periodic bulk submissions better)
- Whether WL/Lexis citation strings themselves have any IP concerns (probably not — they're just identifiers)

## Last Verification Results (seed 5270, 2026-02-11)

50 sampled (20 likely_fake, 20 likely_real, 10 uncertain):
- 27 VERIFIED (54%), 7 LIKELY_REAL (14%), 9 POSSIBLE_MATCH (18%), 7 NOT_FOUND (14%)
- QC: 2 new abbreviation examples (Weatherly, Auto Fin. Corp.), 5 RECAP document selection bugs (Mali, Coronavirus, O'Brien SD Fla, Wadsworth, Dobson), 1 VERIFIED hallucination (Pettway — critical bug), 2 new false positive POSSIBLE_MATCHes (Mavy, South Pointe), 1 parser issue (Thomas v. Pangburn), 1 FLP data gap (O'Brien 11th Cir)

Prior batch (seed 3193): 24 VERIFIED, 5 LIKELY_REAL, 6 POSSIBLE_MATCH, 15 NOT_FOUND
Prior batch (seed 8487, reruns): 0 VERIFIED, 1 LIKELY_REAL, 2 POSSIBLE_MATCH, 1 NOT_FOUND

Cumulative: 153/515 rows verified (49 seed 42 + 50 seed 3193 + 4 reruns + 50 seed 5270)
