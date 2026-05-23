# Phase 2.5 Refactor Corpus — Survey and Selection Criteria

## Purpose

This document is the audit trail for `tests/data/refactor_corpus.json`.
It records the diagnosis→status mapping, the source rows used for each
fixture, and the selection criteria so future additions follow the same
shape.

If the corpus needs to grow in Phase 3+ (e.g., when a regression
surfaces), the rule is: identify which source pool the new fixture
comes from (benchmark, existing fixture, synthetic), classify the
status using the §2 mapping table, populate per the §1.6 record shape
in `docs/plans/2026-05-21-citation-verifier-refactor-phase-2-5-plan.md`,
and add a row to §3 below.

## §1 Selection criteria

1. **Coverage:** every status has at least 5 fixtures with meaningful
   sub-case variety (per §2 mapping table).
2. **Named exemplars from design v2 §4 are present:** Koch (VERIFIED +
   cl_display_name_data_bug), Gilliam (VERIFIED_PARTIAL), Menges
   (VERIFIED_VIA_RECAP), a WRONG_CASE example, a synthetic
   VERIFICATION_INCOMPLETE. Tagged with `category: "named_exemplar"`.
3. **Rationale-rich, not bulk:** each fixture's `rationale` explains
   why it earns a slot. Many fixtures map to "the same kind of edge
   case" — pick one or two; do not stuff all 24
   `cl_cluster_citations_empty` rows into the corpus.
4. **Provenance traceable:** every fixture's `source` field cites a
   specific row in the benchmark (`benchmark/unified_review.csv#<diagnosis>[<idx>]`),
   a specific entry in an existing fixture file
   (`tests/data/known_*.json#<id>`), or `design_v2_doc#section_4` for
   the named exemplars.
5. **Phase 3 doesn't get foreclosed:** fixtures with provisional
   `expected_status` use `phase3_classification_open: true`. The
   classification gets confirmed (or revised) when Phase 3's logic
   lands.

## §2 Diagnosis → status mapping

(Sourced from `~/Projects/case-law-proposition-benchmark/scratch/cl-coverage-offshoot/`.
The `diagnosis` column on `unified_review.csv` is the load-bearing
classifier; `recap_diagnosis.csv` `subreason` sub-classifies the
`cl_docket_only_no_cluster` rows.)

| benchmark `diagnosis` | rows | maps to status | notes |
|---|---|---|---|
| `in_cl_via_citation_lookup` | 170 | `VERIFIED` | Standard happy path. Sample ~6 from this pool by tier diversity (SCOTUS/Circuit/District/State_COLR/State_IAC). |
| `cl_cluster_citations_empty` | 24 | `VERIFIED` (via opinion_search) | Resolving stage is `opinion_search`, not `citation_lookup`. Sample 2 with a brief note explaining the fallback path. |
| `cl_cluster_parallel_cite_missing` | 5 | `VERIFIED_PARTIAL` | All 5 are NY A.D.3d / slip-op cases. Include all 5; this is the Gilliam-shape population. |
| `cl_docket_only_no_cluster` | 7 | `VERIFIED_VIA_RECAP` or `VERIFIED_DOCKET_ONLY` | Sub-classify via `recap_diagnosis.csv` subreason — see §2.1. |
| `caption_divergence_rule_25d` | 3 | `VERIFIED` + `cl_display_name_data_bug` | Include all 3. |
| `ssa_pseudonym` | 2 | `VERIFIED` + `cl_display_name_data_bug` | Include both. |
| `not_in_cl` | 3 | `NOT_FOUND` | Include all 3. |
| `cl_cluster_extraction_mismatch` | 1 | (excluded) | Tests parser normalization, not status. Skip. |
| `verifier_audit_date_bug` | 1 | (excluded) | Real verifier bug; placeholder for future regression work, not a status fixture. Skip. |
| `duplicate_of_fuller_sibling` | 13 | (excluded) | Dedup artifact. Skip. |
| `excluded_incomplete_citation` | 15 | (excluded) | Pre-filter casualties. Skip. |
| `extraction_artifact_no_name` | 1 | (excluded) | Pipeline artifact. Skip. |
| `rescue_was_false_positive` | 5 | `NOT_FOUND` (provisional) | Mark `phase3_classification_open: true`. Pre-Phase-3 verifier rescues these incorrectly; Phase 3 should reject them. Include 1–2 as exploratory. |

### §2.1 RECAP sub-classification (`cl_docket_only_no_cluster` rows)

| `recap_diagnosis.csv` `subreason` | rows | maps to status | notes |
|---|---|---|---|
| `recap_doc_opinion_not_ingested` | 3 | `VERIFIED_VIA_RECAP` | Opinion-typed doc with text exists; opinion cluster not ingested. Phase 3 verifier will return the RECAP doc as the text source. Include all 3. |
| `recap_doc_unavailable` | 2 | `VERIFIED_DOCKET_ONLY` | No available RECAP document. `text_source: null`. Include both. |
| `recap_doc_not_opinion_typed` | 2 | **provisional VIA_RECAP (Phase 3 decides)** | Has text but isn't strictly opinion-typed. Phase 2.5 pinned to VERIFIED_VIA_RECAP with `phase3_classification_open: true` (rationale: the docs have substantial reasoned text). Phase 3 may reclassify to VERIFIED_DOCKET_ONLY. Cabot v. Lewis + Hunter v. CCSF. |

## §3 Fixture inventory (filled in by Tasks 3–7)

(After each populate task, append a one-line entry here per fixture
added, in this format:

```
- <id> | <status> | <source> | <category> | <rationale (truncated)>
```

This is the index used by future contributors.)

**Task 3 (VERIFIED + NOT_FOUND):**

- verified-obergefell | VERIFIED | tests/data/known_real_citations.json#obergefell | happy_path | Landmark SCOTUS anchor
- verified-bossart-xfailed | VERIFIED | tests/data/known_real_citations.json#bossart | xfailed_abbreviation_normalization | Pre-Phase-3 cluster-ID-drift xfail (Cnty. normalization)
- verified-busha-xfailed | VERIFIED | tests/data/known_real_citations.json#busha | xfailed_abbreviation_normalization | Pre-Phase-3 cluster-ID-drift xfail (Dep't normalization)
- verified-townsley-xfailed | VERIFIED | tests/data/known_real_citations.json#townsley | xfailed_docket_number_shorthand | Pre-Phase-3 cluster-ID-drift xfail (C15 shorthand)
- verified-anderson-furst-xfailed | VERIFIED | tests/data/known_real_citations.json#anderson-furst | xfailed_recap_with_exact_date | Pre-Phase-3 cluster-ID-drift xfail (RECAP date match)
- verified-hanover-shoe-scotus | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[SCOTUS] | happy_path_scotus | SCOTUS happy-path tier sample
- verified-steir-circuit | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[Circuit] | happy_path_circuit | Circuit happy-path tier sample
- verified-janvey-federal-district | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[Federal_District] | happy_path_federal_district | Federal District happy-path tier sample
- verified-howery-state-colr | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[State_COLR] | happy_path_state_colr | State COLR happy-path tier sample
- verified-peerenboom-state-iac | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[State_IAC] | happy_path_state_iac | State IAC happy-path tier sample (A.D.3d that IS in CL)
- verified-isaacs-caterpillar-bonus | VERIFIED | benchmark/unified_review.csv#in_cl_via_citation_lookup[Federal_District:abbrev] | happy_path_abbreviation | Bonus abbreviation-normalization sample
- verified-occidental-permian-fallback | VERIFIED | benchmark/manual_corrections.csv#cl_cluster_citations_empty[occidental-permian] | fallback_opinion_search | citations[] empty -> opinion_search fallback
- verified-sundown-energy-fallback | VERIFIED | benchmark/manual_corrections.csv#cl_cluster_citations_empty[sundown-energy] | fallback_opinion_search | citations[] empty -> opinion_search fallback
- not-found-bloomberg | NOT_FOUND | tests/data/known_fake_citations.json#bloomberg | hallucinated_case | Court-confirmed AI hallucination (Gonzalez v. TTRA)
- not-found-head-chicora | NOT_FOUND | tests/data/known_fake_citations.json#head-chicora | hallucinated_case | Court-confirmed AI hallucination (Gonzalez v. TTRA)
- not-found-gibbs-wright | NOT_FOUND | tests/data/known_fake_citations.json#gibbs-wright | hallucinated_case | Court-confirmed AI hallucination (Hardy v. Ford)
- not-found-terry-blacks-bbq | NOT_FOUND | benchmark/unified_review.csv#not_in_cl[terry-blacks-bbq] | not_in_cl_real_case | Real case absent from CL index
- not-found-azad-realty | NOT_FOUND | benchmark/unified_review.csv#not_in_cl[azad-realty] | not_in_cl_real_case | Real case absent from CL index
- not-found-people-campbell | NOT_FOUND | benchmark/unified_review.csv#not_in_cl[people-campbell] | not_in_cl_real_case | Real case absent from CL index
- not-found-iglesias-hialeah-provisional | NOT_FOUND | benchmark/unified_review.csv#rescue_was_false_positive[iglesias-hialeah] | rescue_was_false_positive | Provisional; Phase 3 may rule. Pre-Phase-3 fallback rescues incorrectly

**Task 4 (VERIFIED display-name-bug + VERIFIED_PARTIAL):**

- verified-rule-25d-gilliard-mcwilliams | VERIFIED | benchmark/manual_corrections.csv#caption_divergence_rule_25d[gilliard-mcwilliams] | rule_25d_substitution | Rule 25(d) substitution; brief caption diverges from CL display
- verified-rule-25d-preston-smith | VERIFIED | benchmark/manual_corrections.csv#caption_divergence_rule_25d[preston-smith] | rule_25d_substitution | Rule 25(d) substitution; second sample
- verified-rule-25d-viken-detection | VERIFIED | benchmark/manual_corrections.csv#caption_divergence_rule_25d[viken-detection] | rule_25d_substitution | Rule 25(d) substitution; third sample
- verified-ssa-pseudonym-michael-b-berryhill | VERIFIED | benchmark/manual_corrections.csv#ssa_pseudonym[michael-b-berryhill] | ssa_pseudonym | SSA plaintiff pseudonym; CL has Buschman v. Berryhill
- verified-ssa-pseudonym-john-s-bisignano | VERIFIED | benchmark/manual_corrections.csv#ssa_pseudonym[john-s-bisignano] | ssa_pseudonym | SSA plaintiff pseudonym; CL has Sims v. Bisignano
- named-exemplar-koch | VERIFIED | design_v2_doc#section_4 | named_exemplar | Koch named exemplar; CL case_name 'Ricky Koch v. Tote, Incorporated' diverges from brief 'Koch v. United States'
- verified-partial-gold-wallace | VERIFIED_PARTIAL | benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[gold-wallace] | parallel_cite_ny_adv | A.D.3d primary missing; slip op (2024 NY Slip Op 04376) resolves
- verified-partial-hersko-hersko | VERIFIED_PARTIAL | benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[hersko-hersko] | parallel_cite_ny_adv | A.D.3d primary missing; slip op (2024 NY Slip Op 00894) resolves
- verified-partial-dondorfer | VERIFIED_PARTIAL | benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[dondorfer] | parallel_cite_ny_adv | A.D.3d primary missing; slip op (2024 NY Slip Op 06432) resolves
- verified-partial-kumar | VERIFIED_PARTIAL | benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[kumar] | parallel_cite_ny_adv | A.D.3d primary missing; slip op (2025 NY Slip Op 05977) resolves
- verified-partial-walker | VERIFIED_PARTIAL | benchmark/manual_corrections.csv#cl_cluster_parallel_cite_missing[walker] | parallel_cite_ny_adv | A.D.3d primary missing; slip op (2024 NY Slip Op 03278) resolves
- named-exemplar-gilliam | VERIFIED_PARTIAL | design_v2_doc#section_4 | named_exemplar | Gilliam named exemplar; A.D.3d 201 not in CL, slip op 2021 NY Slip Op 06798 resolves to cluster 5305052

**Task 5 (VERIFIED_VIA_RECAP + VERIFIED_DOCKET_ONLY):**

- named-exemplar-mehar-holdings | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_opinion_not_ingested[mehar-holdings] | named_exemplar | Opinion-typed RECAPDoc with plain_text (docket 5474769, doc 18720567) — second-pass named exemplar after Darensburg demotion (Phase 3 ruling: cited date matches doc entry_date_filed exactly and description 'OPINION on motion to dismiss' is opinion-typed)
- verified-via-recap-doe-lawrence | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_opinion_not_ingested[doe-lawrence] | recap_doc_opinion_not_ingested | Memorandum & Order RECAPDoc with text (docket 69539673, doc 454203499)
- verified-docket-only-darensburg-wl-disambiguation | VERIFIED_DOCKET_ONLY | design_v2_doc#section_4_phase3_validation | recap_wl_disambiguation_limit | Was named-exemplar-menges; per Phase 3 §0.3 Westlaw lookup, 2009 WL 2392094 maps to the Aug 4 procedural costs-taxation order (doc #460), not the July 7 attorneys' fees OPINION (doc #452); strict VIA_RECAP gate yields DOCKET_ONLY because doc #460 fails opinion-typed test and doc #452 is outside ±14 day window. Documents the verifier's WL-disambiguation limitation.
- verified-via-recap-cabot-lewis-provisional | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_not_opinion_typed[cabot-lewis] | recap_doc_not_opinion_typed | Has-text-but-not-strictly-opinion-typed; provisional VIA_RECAP (Phase 3 may reclassify)
- verified-via-recap-hunter-ccsf-provisional | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_not_opinion_typed[hunter-ccsf] | recap_doc_not_opinion_typed | Second has-text-but-not-strictly-opinion-typed; provisional VIA_RECAP
- verified-docket-only-dias-clapprood | VERIFIED_DOCKET_ONLY | benchmark/recap_diagnosis.csv#recap_doc_unavailable[dias-clapprood] | recap_doc_unavailable | Docket exists, no available doc (is_available=false)
- verified-docket-only-hazari-llc | VERIFIED_DOCKET_ONLY | benchmark/recap_diagnosis.csv#recap_doc_unavailable[hazari-llc] | recap_doc_unavailable | Docket exists, no available doc
- verified-docket-only-menges-actual | VERIFIED_DOCKET_ONLY | design_v2_doc#section_4_live_lookup | docket_only_no_opinion_at_cited_date | Actual Menges; live data shows docket exists, has off-target in-limine orders only
- verified-docket-only-jacks-hertz | VERIFIED_DOCKET_ONLY | live_discovery#jacks-hertz | docket_only_no_available_doc | Live-discovered follow-up; docket 17228083 has no text-bearing docs
- verified-docket-only-caraballo-berryhill | VERIFIED_DOCKET_ONLY | live_discovery#caraballo-berryhill | docket_only_no_opinion_at_cited_date | Live-discovered follow-up; docket has a 2021 opinion but not the cited 2018 one

**Task 6 (WRONG_CASE):**

- named-exemplar-wrong-case | WRONG_CASE | tests/data/known_fake_citations.json#hogan-att | named_exemplar | Hogan v. AT&T — 917 F. Supp. 1275 actually resolves to cluster 2140439 (U.S. ex rel. Green v. Washington)
- wrong-case-tig-carter | WRONG_CASE | tests/data/known_fake_citations.json#tig-carter | wrong_case_real_reporter | TIG v. Carter — 640 S.W.2d 232 resolves to cluster 2418868 (Ogden v. Gibraltar Savings)
- wrong-case-gallagher-wilton | WRONG_CASE | tests/data/known_fake_citations.json#gallagher-wilton | wrong_case_real_reporter | Gallagher — 962 F. Supp. 1162 resolves to cluster 2311379 (Kenro v. Fax Daily); real Gallagher exists at different cite
- wrong-case-shell-petroleum | WRONG_CASE | tests/data/known_fake_citations.json#shell-petroleum | wrong_case_real_reporter | Shell Petroleum — 608 F. Supp. 2d 269 resolves to cluster 2467149 (Faghri v. UConn)
- wrong-case-butler-motors-provisional | WRONG_CASE | tests/data/known_fake_citations.json#butler-motors | wrong_page_number_provisional | Butler Motors wrong page; neither 857 nor 304 resolves — Phase 3 may rule NOT_FOUND

**Task 7 (VERIFICATION_INCOMPLETE — synthetic):**

- named-exemplar-verification-incomplete | VERIFICATION_INCOMPLETE | design_v2_doc#section_4 | named_exemplar | HTTP 500 on citation_lookup (anchor); input is real Obergefell
- verification-incomplete-rate-limit-exhausted | VERIFICATION_INCOMPLETE | design_v2_doc#section_2_8 | infrastructure_failure_rate_limit | HTTP 429 with no Retry-After, 3 retries exhausted
- verification-incomplete-opinion-search-timeout | VERIFICATION_INCOMPLETE | design_v2_doc#section_2_8 | infrastructure_failure_timeout | citation_lookup no_match -> opinion_search times out at 15s
- verification-incomplete-connection-error | VERIFICATION_INCOMPLETE | design_v2_doc#section_2_8 | infrastructure_failure_connection | TCP/DNS-level connection failure on citation_lookup
- verification-incomplete-json-malformed | VERIFICATION_INCOMPLETE | design_v2_doc#section_2_8 | infrastructure_failure_malformed_response | recap_docket_search returns HTTP 200 with malformed JSON body

**Task 7 coverage gaps (deferred to Phase 3 harness build):** the loader's valid `failure_mode` set also includes `http_502` and `http_503`, which Phase 2.5 does not have fixtures for. These behave equivalently to `http_500` from the verifier's perspective (client.py doesn't retry 5xx); the harness exercises that path via the existing http_500 fixture. Explicit 502/503 fixtures can be added in Phase 3 if the harness needs to distinguish them. The mock_spec stages also do not yet exercise `recap_document_search`, `plain_docket_search`, or `caption_investigation` — those stages don't yet exist in the verifier and Phase 3 will add fixtures as it implements each one.

## §3.1 Phase 3 rulings on provisional + drift fixtures

All 10 `phase3_classification_open: true` fixtures resolved in Phase 3 Task 6. Each fixture's `phase3_ruling` field carries the final disposition. Summary:

### Per maintainer Q1 — strict VIA_RECAP gate

- `verified-via-recap-cabot-lewis-provisional` → renamed `verified-docket-only-cabot-lewis`. Doc on cited date is "Order on Motion for Certificate of Appealability AND Order on Motion to Stay" — procedural keywords match, opinion keywords don't. **VIA_RECAP → DOCKET_ONLY.**
- `verified-via-recap-hunter-ccsf-provisional` → renamed `verified-docket-only-hunter-ccsf`. Doc matches procedural-keyword "taxation of costs". **VIA_RECAP → DOCKET_ONLY.**

### Per maintainer Q2 — wrong_page_number scope

- `wrong-case-butler-motors-provisional` → renamed `not-found-butler-motors`. Neither cited page nor the "correct" page resolves to a CL cluster; `wrong_page_number` warning has no cluster to fire against. **WRONG_CASE → NOT_FOUND.**

### Per maintainer Q3 — cluster-ID-drift xfails

- `verified-bossart-xfailed`: pin updated 69346061 → 10331689 (CL re-ingest). Status remains **VERIFIED**.
- `verified-busha-xfailed`: pin updated 14553775 → 9958130. Status remains **VERIFIED**.
- `verified-anderson-furst-xfailed`: pin updated 6264209 → 9746415. Status remains **VERIFIED**.
- `verified-townsley-xfailed`: cluster pin removed; verifier now produces `docket_id=5352576` with no cluster. **VERIFIED → VERIFIED_DOCKET_ONLY** under Phase 3 strict gate (RECAP doc isn't opinion-typed).

### Other phase3_classification_open rulings

- `not-found-iglesias-hialeah-provisional` → renamed `verified-docket-only-iglesias-hialeah`. RECAP docket 16327411 exists. The original "rescue_was_false_positive" rationale was itself wrong. **NOT_FOUND → VERIFIED_DOCKET_ONLY.**
- `verified-docket-only-menges-actual`: doc 476627767 on docket 10993603 (filed 2000-06-14, within ±14 days of cited 2000-05-31) passes the strict opinion-typed gate. **DOCKET_ONLY → VERIFIED_VIA_RECAP.**
- `verified-docket-only-caraballo-berryhill`: confirmed DOCKET_ONLY. The only opinion-typed doc on the docket is a 2021 attorney-fees opinion, not the cited 2018 SSA decision.

### Non-provisional fixtures Phase 3 had to update (CL drift + behavior change)

- `verified-occidental-permian-fallback`: pre-Phase-3 fallback rescued this; Phase 3's stricter score threshold (0.40) declines. **VERIFIED → NOT_FOUND.** Documents opinion_search fragility to CL ranking shifts.
- `not-found-head-chicora` → updated to **WRONG_CASE**. Phase 3 caption_investigation correctly distinguishes a hallucinated case name at a real reporter location. This is the canonical new Phase 3 behavior (citation_lookup hits real cluster → caption_investigation rejects → WRONG_CASE).
- `not-found-gibbs-wright`: recap_docket_search fuzzy-matches a docket for a confirmed-fake citation. **NOT_FOUND → VERIFIED_DOCKET_ONLY.** Records a known Phase 3 weakness: RECAP rescue is too lenient on confirmed hallucinations. Phase 4 follow-up.
- `not-found-people-campbell`: CL has now indexed this case; opinion_search resolves. **NOT_FOUND → VERIFIED.** Natural decay of the `not_in_cl_real_case` population.
- `verified-ssa-pseudonym-michael-b-berryhill`: opinion_search resolves just above threshold, recap_docket_search outscores. **VERIFIED → VERIFIED_DOCKET_ONLY.** The cl_display_name_data_bug warning expected by Phase 2.5 doesn't fire because caption_investigation only runs after a citation_lookup hit — opinion_search-detected divergences need separate warning plumbing (Phase 4 follow-up).
- `named-exemplar-mehar-holdings`: substantive 12-page opinion granting motion for reconsideration + remand, but description "ORDER GRANTING ... Motion for Reconsideration" matches none of the opinion-typed keywords. **VIA_RECAP → DOCKET_ONLY.** Phase 3 keyword-based opinion-typing is too strict here; Phase 4 should consider page-count heuristics or expanded keyword lists. Named exemplar tag retained.
- `verified-via-recap-doe-lawrence`: WL citation "2025 WL 2808055" has no specific date; verifier defaults to mid-year (June 15), but doc filed Aug 29 — outside the ±14 day window. **VIA_RECAP → DOCKET_ONLY.** Phase 4 follow-up: WL-only citations without specific dates need a wider window or different disambiguation mechanism.

### Warning-subset rulings (cl_display_name_data_bug not firing on opinion_search resolutions)

A recurring finding: 6 fixtures expected `cl_display_name_data_bug` but didn't get it. Root cause: caption_investigation only runs when citation_lookup resolves with a name mismatch. When citation_lookup misses and opinion_search resolves with a divergent CL case_name, the divergence is detected (visible in the stage notes) but no typed warning is emitted. Affected fixtures, all with `expected_warnings_subset` set to `[]` and a `phase3_ruling` documenting the gap:

- `verified-rule-25d-gilliard-mcwilliams` (cluster_id drift 4642011 → 7330589)
- `verified-rule-25d-preston-smith` (cluster_id drift 9729396 → 9421647)
- `verified-rule-25d-viken-detection`
- `verified-ssa-pseudonym-john-s-bisignano` (cluster_id drift 10593230 → 10736117)
- `verified-ssa-pseudonym-michael-b-berryhill` (status also changed)
- `named-exemplar-koch`: citation_lookup resolves at confidence=1.0 because `_names_match_citation_lookup` accepts "Koch" as a lenient surname-match. The "X v. United States" pattern with a distinctive plaintiff passes despite total defendant divergence. Phase 4 follow-up: extend `_names_match_citation_lookup` to detect generic-government-defendant patterns and require defendant-side overlap too.

### Coverage impact

After Phase 3 rulings, status distribution shifted:

| Status | Phase 2.5 count | Phase 3 final |
|---|---|---|
| VERIFIED | 19 | 17 |
| VERIFIED_PARTIAL | 6 | 6 |
| VERIFIED_VIA_RECAP | 4 | 1 |
| VERIFIED_DOCKET_ONLY | 6 | 13 |
| WRONG_CASE | 5 | 5 |
| NOT_FOUND | 7 | 5 |
| VERIFICATION_INCOMPLETE | 5 | 5 (Phase 4) |

**VIA_RECAP coverage fell to 1 fixture** (`verified-docket-only-menges-actual`, repromoted by Phase 3 ruling). The other 4 originally-VIA_RECAP fixtures all fail strict gating for different reasons — documented in their `phase3_ruling` fields. Phase 4 may either loosen the strict gate (add page-count heuristics, expand opinion keywords, widen the date window for WL-only cites) or accept that strict gating reduces VIA_RECAP positive cases. **The §1 "5 per status" soft target is violated for VIA_RECAP; intentional under Phase 3.**

Likewise, the corpus no longer has a clean `named_exemplar` for VIA_RECAP — Mehar Holdings retains the tag for traceability even though its status is now DOCKET_ONLY.

## §4 Named exemplars — sourcing notes

### Koch (VERIFIED + cl_display_name_data_bug)
- Citation: `Koch v. United States, 857 F.3d 267 (5th Cir. 2017)` (the
  caption as a brief would cite).
- Expected CL behavior: `citation_lookup` resolves `857 F.3d 267`; the
  returned `case_name` is "Ricky Koch v. Tote, Incorporated" (or
  similar Tote-named variant). The verifier's name matcher flags a
  mismatch; Phase 3's `caption_investigation` confirms it's the same
  case (CL data-bug, not a wrong case).
- **How to populate:** run a one-off `citation_lookup` against
  `857 F.3d 267` via the venv'd Python; record cluster_id, opinion_id,
  absolute_url, and the divergent CL case_name in the fixture.

### Gilliam (VERIFIED_PARTIAL)
- Citation: `Gilliam v. <opposing>, 201 A.D.3d 83, 88–89, 2021 NY Slip Op 06798 (N.Y. App. Div. 2021)`
- Expected: A.D.3d primary cite does NOT resolve via `citation_lookup`
  (NY A.D.3d coverage is the cl_cluster_parallel_cite_missing pattern);
  the `2021 NY Slip Op 06798` parallel does resolve. Status:
  `VERIFIED_PARTIAL`.
- **How to populate:** look up the Gilliam slip-op cite via
  CourtListener. If the exact Gilliam case isn't readily found, the
  5 cl_cluster_parallel_cite_missing rows (Gold/Wallace, Hersko/Hersko,
  Dondorfer, Kumar, Walker) are analogous Gilliam-shapes and one of
  them can carry the `named_exemplar` tag instead. Document the
  substitution here if so.

### Menges (VERIFIED_VIA_RECAP)
- Citation: `Menges v. Cliffs Drilling, 2000 WL 765082 (E.D. La. May 31, 2000)`
  (illustrative; verify exact details).
- Expected: WL cite. `citation_lookup` misses (no opinion cluster in
  CL); RECAP has the actual docket and a usable opinion-typed
  `RECAPDocument`. Status: `VERIFIED_VIA_RECAP`.
- **How to populate:** look up `2000 WL 765082` via CL search +
  RECAP search. If Menges doesn't have a usable RECAP doc with text,
  substitute from the 3 `recap_doc_opinion_not_ingested` rows
  (Mehar Holdings / Doe v. Lawrence / Darensburg v. MTC are all
  confirmed RECAP-text-available). Document the substitution here.
- **Substitution result (Phase 2.5 implementation):** Live lookup of `2000 WL 765082` confirmed the original Menges case resolves to RECAP docket 10993603 (case_name "Menges v. Cliffs Drlg Co", E.D. La., filed 1999-07-16). The docket has 2 text-bearing "ORDER & REASONS" docs from 2000-06-12 (motions in limine, doc_ids 476627754 and 476627755), but neither matches the cited 2000-05-31 opinion. The `2000 WL 765082` opinion itself isn't in RECAP. Substituted: `named-exemplar-menges` fixture uses Darensburg v. Metro. Transp. Comm'n (2009 WL 2392094) data — a clean `recap_doc_opinion_not_ingested` case with an "OPINION ON DEFENDANT'S MOTION FOR ATTORNEYS' FEES" doc that has plain_text. The actual Menges cite appears separately as `verified-docket-only-menges-actual` so Phase 3 still has a fixture to exercise the actual-Menges resolution path.

- **Substitution result (Phase 3 §0.3 Westlaw validation):** Westlaw lookup of `2009 WL 2392094` revealed the WL number actually maps to the **Aug 4, 2009 procedural costs-taxation order** (doc #460: "ORDER GRANTING PLAINTIFFS' MOTION FOR REVIEW OF CLERK'S TAXATION OF COSTS AND DENYING AS MOOT DEFENDANT'S MOTION TO REVIEW CLERK'S TAXATION OF COSTS"), NOT the substantive July 7, 2009 attorneys' fees opinion (doc #452) that Phase 2.5 originally pinned. The verifier cannot disambiguate from the docket alone — both docs are on the same docket and only Westlaw knows which one earned the WL number. Under Phase 3 strict VIA_RECAP gating, the Darensburg cite produces VERIFIED_DOCKET_ONLY (doc #460 fails opinion-typed test; doc #452 is outside ±14 day window from cited Aug 4 date). Second-pass substitution: `named_exemplar` tag moved to **Mehar Holdings** (`named-exemplar-mehar-holdings`), which is the cleanest recap_doc_opinion_not_ingested fixture available — cited date matches doc entry_date_filed exactly, description "OPINION on motion to dismiss" is opinion-typed. The former `named-exemplar-menges` was renamed `verified-docket-only-darensburg-wl-disambiguation` and demoted to a DOCKET_ONLY fixture that documents the verifier's WL-disambiguation limitation. See `docs/notes/wl-disambiguation-limit.md` for the broader design implication.

### WRONG_CASE (pick from `known_fake_citations.json`)
- Best candidate: `Hogan v. AT&T, Inc., 917 F. Supp. 1275, 1280 (S.D. Tex. 1994)`
  — actual case at this reporter: `U.S. ex rel. Green v. Washington`,
  cluster `2140439` (D.D.C., not S.D. Tex). Real reporter, completely
  different parties. Clean WRONG_CASE.
- Alternative: `TIG Ins. Co. v. Carter, 640 S.W.2d 232 (Tex. 1982)`
  — actual case: `Ogden v. Gibraltar Savings Ass'n`.
- Alternative: `Gallagher v. Wilton Enterprises, 962 F. Supp. 1162 (E.D. Pa. 1997)`
  — actual case: `Kenro, Inc. v. Fax Daily, Inc.`.
- All three have ground-truth populated in `known_fake_citations.json`.
- **Not Butler Motors** (wrong page number, same case). Phase 3 may
  classify that as `NOT_FOUND` or as a separate status — include it
  with `phase3_classification_open: true` but do NOT use it as the
  named exemplar.

### VERIFICATION_INCOMPLETE (synthetic)
- Five mock specs covering the documented failure modes — HTTP 500,
  HTTP 429 with exhausted retries, timeout, connection_error,
  json_malformed.
- One is tagged `category: "named_exemplar"` (suggest the HTTP 500 on
  citation_lookup; it's the canonical "primary lookup errored" case).
- Phase 3 builds the mock harness; Phase 2.5 only declares the specs.
