# Baseline corpus — shortfalls & provenance notes (Task 4c, 2026-07-04)

Phase-1 target was 10 clean, representative, text-available filings per cell.
Final counts and every deviation from that, recorded honestly (a thin honest
cell beats a padded one — PROJECT.md §4).

| cell | count | notes |
|---|---|---|
| attorney__merits_brief | 9 | pilot pull of 10, then **snyder-v-the-state-of-nevada removed** — it was a pro se filing ("/s/ Raymond Max Snyder ... Pro Se") pulled via the unreliable case-level `firm` field. Remaining 9 content-clean. |
| attorney__pleading | 10 | content-verified attorney signatures; admiralty/misc rejected. |
| attorney__procedural_motion | 9 | agent stopped at 9 (looped into background-monitoring twice); 9 is a sufficient baseline, not topped to 10. |
| pro_se__pleading | 10 | content-verified pro se signatures (6 candidates rejected incl. one attorney block). |
| pro_se__merits_brief | 7 | **scarcity** — pro se litigants rarely file substantive merits briefs with available text. All 7 confirmed pro se on manual re-check (frymier/holt/lawson were false-"AMBIG" from certificate-of-service "counsel for [defendant]" language; they self-sign). |
| pro_se__procedural_motion | 3 | **acute scarcity** — only 3 clean pro se procedural motions found. `the-service-companies-inc-v-barajas` is an OCR'd handwritten filing (garbled tail, ~3.5k chars) — genuine pro se but low text quality; its metrics will be noisy. |

**Method caveats affecting interpretation:**
- **Filer type verified from document *content* (signature block), not RECAP's
  case-level `firm`/`attorney` fields** — those proved unreliable (list counsel
  who appeared after a pro se filing, or opposing counsel). The snyder removal is
  the one contamination that slipped through the pilot's field-based filter
  before this lesson was learned; the attorney pleading/procedural cells were
  re-scanned clean.
- **`available_only=on` sampling skew:** every doc is drawn from the
  `is_available=True` RECAP universe (filings someone purchased from PACER),
  which is NOT a random sample of all filings — it skews toward litigated /
  higher-stakes / researcher-interesting cases. The baseline therefore
  characterizes "normal among *available* filings," a documented limitation of
  the whole gate.
- **Manifests for the two interrupted pro se cells were reconstructed** from the
  saved .txt after the agents broke mid-write; `court`/`document_number` are
  blank in those rows (not used by the metrics or the deviation gate; docket_id
  recovered from the slug suffix).
