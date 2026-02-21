# Resolved Issues & History

Archived from `TODO.md`. Items here are fixed or historical reference only.

## Resolved Issues

### Pettway v. American Savings — VERIFIED hallucination (FIXED)
Fixed in ff0a91d. Added `_NONDISTINCTIVE_SURNAMES` frozenset (23 common organization-starting words). Rerun confirmed: now returns NOT_FOUND ("Citation exists but belongs to a different case: American National Insurance v. Smith").

### Bidirectional abbreviation normalization (FIXED)
`name_matcher.py:calculate_similarity()` now normalizes BOTH the cited name and the CL result name via `_normalize()` before comparison. The 47-term Indigo Book expansion runs on both sides.

### Thomas v. Pangburn — parser issue causes low confidence (FIXED)
Fixed by `_DOCKET_JUNK` regex in `parser.py` which strips "Case No. ..." and docket number patterns from case names. "In re CV-46" misparse no longer occurs.

### RECAP Pattern A: O'Brien, Coronavirus (FIXED)
- O'Brien v. Flick (SD Fla): was "Transcript Order Form" -> now "Order Dismissing/Closing Case" (LIKELY_REAL 0.90)
- Coronavirus Reporter v. Apple: was "Proposed Order" -> now "Order on Administrative Motion" (LIKELY_REAL 0.90)

### RECAP Pattern C: Mali v. British Airways (FIXED)
Was docket-only -> now LIKELY_REAL 0.90 with document dated 2018-07-06.

### RECAP score too conservative (FIXED)
RECAP-only matches had a 0.6x docket-only discount, and WL citations almost never confirmed in CL. Real RECAP matches topped out around 60-75% even when name + court + date all matched. Fixed by boosting RECAP document matches when court and date align, and not penalizing WL citation mismatch when CL has no citations on file.

## Verification Run History

### Seed 814 reruns (2026-02-11)

13 rerun rows (Pettway surname fix + RECAP doc selection fixes):
- 7 LIKELY_REAL, 4 POSSIBLE_MATCH, 2 NOT_FOUND
- Pettway false VERIFIED -> now correctly NOT_FOUND
- RECAP Pattern A: 2/3 fixed (O'Brien, Coronavirus). Lacey still picks wrong doc (startswith miss).
- RECAP Pattern B: 0/2 fixed (Mata, Davis). Correct docs likely not in API search response.
- RECAP Pattern C: 1/1 fixed (Mali now has document match).
- RECAP Pattern D: 0/3 fixed (Wadsworth, Dobson, Moore). Date/name issues remain.

### Prior batches

- Seed 5270: 27 VERIFIED, 7 LIKELY_REAL, 9 POSSIBLE_MATCH, 7 NOT_FOUND
- Seed 3193: 24 VERIFIED, 5 LIKELY_REAL, 6 POSSIBLE_MATCH, 15 NOT_FOUND
- Seed 8487 (reruns): 0 VERIFIED, 1 LIKELY_REAL, 2 POSSIBLE_MATCH, 1 NOT_FOUND

Cumulative: 153/515 rows verified (49 seed 42 + 50 seed 3193 + 4 reruns + 50 seed 5270 + 13 reruns overlap)
