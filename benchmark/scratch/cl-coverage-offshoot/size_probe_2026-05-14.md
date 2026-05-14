# Size probe — state COLR opinions in window (2026-01-01 to 2026-04-30)

Run during step-1 mining build to test whether the 25K-char cap can
reach the design's 2 accepted/state-court target. The cap is locked by
`REAL_RUN_DESIGN.md` (Option B — keep cap, disclose bias); this probe
quantifies the bias for California Supreme.

## cal (California Supreme)

12 clusters in window, all 12 too long for the 25K cap. Smallest is
~40K chars, well above the ~30K claude-p hang cliff (LIMITATIONS.md).

| cluster | chars | date | case |
|---|---|---|---|
| 10774947 | 98,435 | 2026-01-15 | City of Gilroy v. Superior Court |
| 10778229 | 193,687 | 2026-01-22 | L.A. Police Protective League v. City of L.A. |
| 10781362 | 42,546 | 2026-01-29 | Sellers v. Super. Ct. |
| 10782825 | 105,034 | 2026-02-02 | Fuentes v. Empire Nissan |
| 10800984 | 39,744 | 2026-02-26 | People v. Morgan |
| 10838236 | 79,614 | 2026-04-06 | People v. Deen |
| 10845535 | 386,707 | 2026-04-20 | People v. Bertsch and Hronis |
| 10847246 | 94,366 | 2026-04-23 | Shear Development Co. v. Cal. Coastal Com. |
| 10848555 | 54,474 | 2026-04-27 | In re Z.G. |
| 10851196 | 534,732 | 2026-04-30 | People v. Stayner |
| 10851197 | 74,033 | 2026-04-30 | People v. Lopez |
| 10851198 | 110,991 | 2026-04-30 | In re Kowalczyk |

Median: ~94K. Min: ~40K.

## Implication

The mining script will yield 0/2 citing opinions for `cal` under the
current 25K cap. The State_COLR cited tier still has yield budget from:
- federal districts (~0.1 state-COLR cite per federal opinion × 72 = ~7)
- other state COLRs (ny, tex, fla, ill — sizes unknown until probed)
- state IACs that cite their own state COLR (calctapp opinions often
  cite cal Supreme)

So overall State_COLR cited pool may still reach 50 even with cal=0.
But this is a known disclosed bias toward shorter-opinion citing
courts within the State_COLR cited tier.

## Options the user can pick

1. **Proceed as-is.** Cal contributes 0; rely on ny/tex/fla/ill state
   COLRs + cross-tier citation from federal + state IAC opinions to
   reach 50 cited State_COLR. Disclose in writeup.

2. **Probe ny/tex/fla/ill COLRs first.** If multiple state COLRs yield
   zero under 25K cap, the State_COLR cited tier is in danger.

3. **Bump cap to ~40K and risk individual claude-p hangs.** Smallest cal
   opinion is 40K — barely. With timeout=900s on extraction we'd waste
   minutes per hang. Counter-design.

4. **Add a chunking step** (LIMITATIONS option 3): split long opinions
   into 25K pieces, extract each, merge. Significant complexity for one
   pipeline step.

5. **Switch state COLRs** — replace cal with a state whose COLR writes
   shorter opinions (e.g. NJ, OH, MI, PA). Loses caseload-ranking
   rationale but recovers yield.
