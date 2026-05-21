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

- verified-via-recap-mehar-holdings | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_opinion_not_ingested[mehar-holdings] | recap_doc_opinion_not_ingested | Opinion-typed RECAPDoc with plain_text (docket 5474769, doc 18720567)
- verified-via-recap-doe-lawrence | VERIFIED_VIA_RECAP | benchmark/recap_diagnosis.csv#recap_doc_opinion_not_ingested[doe-lawrence] | recap_doc_opinion_not_ingested | Memorandum & Order RECAPDoc with text (docket 69539673, doc 454203499)
- named-exemplar-menges | VERIFIED_VIA_RECAP | design_v2_doc#section_4 | named_exemplar | Substituted with Darensburg v. MTC (2009 WL 2392094) per §4 escape hatch — original Menges cite has no usable RECAPDoc at the cited 2000-05-31 date
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
