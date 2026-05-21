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
| `recap_doc_not_opinion_typed` | 2 | **provisional (Phase 3 decides)** | Has text but isn't opinion-typed. Mark `phase3_classification_open: true`. Include both — Phase 3 needs them to settle the classification. |

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
