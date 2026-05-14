# Step 2 — Re-verify summary

- Input: `v1_scotus_circuit.csv` (158 rows; 26 SCOTUS + 132 Circuit)
- Verifier wall time: 548.3s

## Status distribution: v1 verifier vs current verifier

| status | v1 | current | delta |
|---|---|---|---|
| LIKELY_REAL | 0 | 58 | +58 |
| NOT_FOUND | 10 | 37 | +27 |
| POSSIBLE_MATCH | 1 | 63 | +62 |
| VERIFIED | 147 | 0 | -147 |

## Per-tier current-verifier results

| tier | total | VERIFIED | NOT_FOUND | POSSIBLE_MATCH | miss_rate |
|---|---|---|---|---|---|
| SCOTUS | 26 | 0 | 7 | 4 | 42.3% |
| Circuit | 132 | 0 | 30 | 59 | 67.4% |

## Per-row status change (v1 → current)

| v1 → current | n |
|---|---|
| VERIFIED → POSSIBLE_MATCH | 57 |
| VERIFIED → LIKELY_REAL | 55 |
| VERIFIED → NOT_FOUND | 35 |
| NOT_FOUND → POSSIBLE_MATCH | 5 |
| NOT_FOUND → LIKELY_REAL | 3 |
| NOT_FOUND → NOT_FOUND | 2 |
| POSSIBLE_MATCH → POSSIBLE_MATCH | 1 |

## Recovered (0 rows: v1 NOT_FOUND/POSSIBLE_MATCH → current VERIFIED)


## Regressed (92 rows: v1 VERIFIED → current NOT_FOUND/POSSIBLE_MATCH)

- `947 F.3d 240` — Wojcicki v. SCANA/SCE&G (2020) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `712 F.3d 1` — SEC v. Am. Int’l Grp. (2013) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "SEC v. Am. International Grp." vs found "Fre
- `888 F.3d 197` — D’Onofrio v. Vacation Publ’ns, Inc. (2018) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "D'Onofrio v. Vacation Publ'ns, Inc." vs foun
- `952 F.2d 457` — S. Cal. v. Barr (1991) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "S. California. v. Barr" vs found "Aclu Found
- `789 F.3d 146` — Brown v. Whole Foods Mkt. Grp., Inc. (2015) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Brown v. Whole Foods Mkt. Grp., Inc." vs fou
- `498 U.S. 89` — Irwin v. Dep’t of Veterans Affs. (2010) — current: POSSIBLE_MATCH  diag: Name mismatch: cited "Irwin v. Department of Veterans Affs." vs found "Holland v. Florida"; Citation mismatch: cited 498
- `722 F.3d 345` — Payne v. D.C. Gov’t (2013) — current: POSSIBLE_MATCH  diag: Found in RECAP (not in opinions database). Document dated 2023-02-03: Appendix in Support filed by Stacy Eley Payne re 3
- `720 F.2d 29` — Comm. v. Webster (1983) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 1983 vs filed 1982-11-18; Citation mismatch: cit
- `454 F.3d 290` — Chaplaincy  Full Gospel Churches v. England (2006) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Chaplaincy  Full Gospel Churches v. England" 
- `771 F.3d 713` — “Stansell I”) (2014) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `722 F.3d 677` — Relief & Dev. (2013) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `994 F.2d 874` — Int’l Dev. (1993) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `755 F.3d 448` — United States v. Volpendesto (2014) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `19 F.3d 663` — United States v. Pogue (1994) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `705 F.3d 603` — Bogie v. Rosenberg (2013) — current: POSSIBLE_MATCH  diag: Found in RECAP (not in opinions database). Document dated 2012-03-20:   JUDGMENT      entered in favor of Defendants Bre
- `367 F.3d 958` — Kaempe v. Myers (2004) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `649 F.3d 688` — United States v. Safavian (2011) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `854 F.3d 721` — Kincaid v. District of Columbia (2017) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Kincaid v. District of Columbia" vs found "P
- `776 F.3d 865` — Williams v. Johnson (2015) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `526 F. App’x 29` — United States v. Williams (2013) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2013 vs filed 2014-10-30; Reporter citation 526 
- `962 F.3d 568` — United States v. Han (2020) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `748 F.3d 1159` — Trebro Mfg., Inc. v. Firefly Equip., LLC (2013) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Trebro Manufacturing., Inc. v. Firefly Equip.
- `456 U.S. 694` — Guinee (1982) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `490 F.3d 1340` — Entegris, Inc. v. Pall Corp. (2007) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `843 F.2d 631` — Castro (1988) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `535 U.S. 722` — Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co. (2014) — current: POSSIBLE_MATCH  diag: Name mismatch: cited "Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co." vs found "Nautilus, Inc. v. Biosig Instrument
- `751 F.3d 1307` — Packard (2014) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `274 F.3d 1354` — Bose Corp. v. JBL, Inc. (2001) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `28 F. 4th 240` — Broadcom Corp. v. Int’l Trade Comm’n (2022) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Broadcom Corp. v. International Trade Commis
- `896 F.3d 1033` — USA), Inc. v. 5 Turchin (2018) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `555 U.S. 7` — Winter v. National Resources Defense 7 Council, Inc. (2008) — current: POSSIBLE_MATCH  diag: Name mismatch: cited "Winter v. National Resources Defense 7 Council, Inc." vs found "Winter v. Natural Resources Defens
- `821 F.2d 714` — Corp. v. EPA (1987) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Corp. v. EPA" ~ found "Kennecott Corp. v. Env
- `679 F.3d 1121` — Pacific Pictures 10 Corp. (2012) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `704 F.3d 568` — Pouncil v. Tilton (2012) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `471 F. App’x 620` — City of Los Angeles (2012) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `522 F.3d 1049` — Supply v. EOFF Elec., Inc. (2008) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Supply v. EOFF Electric., Inc." vs found "Pl
- `430 F.3d 985` — Mpoyo v. Litton 6 Electro-Optical Sys. (2005) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Mpoyo v. Litton 6 Electro-Optical System." v
- `296 F.3d 787` — Nw. Airlines, Inc. v. Camacho (2002) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `374 F.3d 797` — Schwarzenegger v. Fred 25 Martin Motor Co. (2004) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Schwarzenegger v. Fred 25 Martin Motor Co." ~
- `130 F.3d 400` — Planned Parenthood v. Neely (1997) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `814 F.2d 1011` — United States v. Shipco Gen., Inc. (1987) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "United States v. Shipco General., Inc." vs f
- `328 U.S. 680` — Anderson v. Mt. Clemens Pottery Co. (1985) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `66 S.Ct. 1187` — Anderson v. Mt. Clemens Pottery Co. (1985) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `765 F.2d 1317` — Beliz v. W.H. McLeod & Sons Packing Co. (1985) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Beliz v. W.H. McLeod & Sons Packing Co." vs 
- `490 U.S. 488` — Maleng v. Cook (2013) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `837 F.2d 1362` — Mays v. Bowen (1988) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `813 F.2d 55` — Lovelace v. Bowen (1987) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `705 F.2d 123` — Dellolio v. Heckler (1983) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `583 U.S. 281` — Jennings v. Rodriquez (2018) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `592 F.3d 759` — Reger Dev., LLC v. Nat’l City Bank (2010) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Reger Dev., LLC v. National City Bank" vs fo
- `910 F.3d 293` — NewSpin Sports, LLC v. Arrow Elecs., Inc. (2018) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "NewSpin Sports, LLC v. Arrow Elecs., Inc." v
- `853 F.3d 876` — Assurance Co., R.R.G. v. First Am. Title Ins. Co. (2017) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Assurance Co., R.R.G. v. First Am. Title Ins
- `153 F.3d 516` — Bennett v. Schmidt (1998) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `667 F.3d 877` — Keeton v. Morningstar, Inc. (2012) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `636 F.3d 312` — Loudermilk v. Best Pallet Co. (2011) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Loudermilk v. Best Pallet Co." ~ found "Loude
- `827 F.3d 656` — Simpson v. Franciscan All., Inc. (2016) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Simpson v. Franciscan All., Inc." ~ found "Si
- `95 F.4th 493` — Gerlach v. Rokita (2024) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `937 F.3d 1016` — Lockett v. Bonson (2019) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `352 F.3d 328` — Ciarpaglini v. Saini (2003) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `590 F. App’x 629` — Blankenship v. Birch (2014) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `940 F.3d 954` — Walker v. Wexford Health Sources, Inc. (2019) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Walker v. Wexford Health Sources, Inc." ~ fou
- `882 F.3d 674` — Avina v. Bohlen (2018) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `510 U.S. 471` — F.D.I.C. v. Meyer (1994) — current: POSSIBLE_MATCH  diag: Name mismatch: cited "F.D.I.C. v. Meyer" vs found "Federal Deposit Insurance v. Meyer", but we identified a possible mat
- `599 F.3d 720` — Ctr. v. BP Prods. North America, Inc. (2012) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Center. v. BP Products. North America, Inc."
- `49 F.3d 1243` — Tolefree v. Cudahy (1995) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `44 F.4th 676` — Helmstetter (2022) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `78 F.4th 976` — Baysal v. Midvale Indem. Co. (2023) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Baysal v. Midvale Indem. Co." vs found "Kowa
- `822 F.2d 1518` — Campbell v. Bowen (1987) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `322 F.3d 912` — Golembiewski v. Barnhart (2003) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `602 U.S. 367` — Hippocratic Med. (2024) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `407 F.3d 1` — Co. v. U.S. Env’t Prot. Agency (2005) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Co. v. U.S. Env't Prot. Agency" vs found "Fl
- `637 F.3d 18` — Huffington v. T.C. Grp., LLC (2011) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Huffington v. T.C. Grp., LLC" vs found "Prov
- `669 F.3d 50` — Schatz v. Republican State Leadership Comm. (2012) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Schatz v. Republican State Leadership Commis
- `308 F.3d 25` — Singh v. Blue Cross/Blue Shield of Massachusetts, Inc. (2002) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `19 F.2d 500` — Doidge v. Cunard S.S. Co. (1927) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Doidge v. Cunard S.S. Co." ~ found "Doidge v.
- `364 F.3d 355` — In Bank of New England Corp.) (2004) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `962 F.3d 60` — Tomasella v. Nestlé USA, Inc. (2020) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2020 vs filed 2019-01-30; Citation mismatch: cit
- `708 F.3d 324` — Latson v. Plaza Home Mortg., Inc. (2013) — current: NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2013-08-05: Judge Rya W. Zobel: Memorandum of Decision entered
- `86 F.4th 76` — Wiener v. MIB Grp., Inc. (2023) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Wiener v. MIB Grp., Inc." vs found "Foss v. 
- `86 F.4th 76` — Wiener v. MIB Grp., Inc. (2023) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Wiener v. MIB Grp., Inc." vs found "Foss v. 
- `241 F.3d 1267` — Benefield v. McDowall (2001) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `874 F.3d 767` — P.R. Tel. Co. v. San Juan Cable LLC (2017) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2017 vs filed 2018-04-23; Citation mismatch: cit
- `367 F.3d 61` — Acción v. Hernandez (2004) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2004 vs filed 2003-02-27; Citation mismatch: cit
- `55 F.3d 1` — Grant v. News Grp. Bos., Inc. (1995) — current: NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2025-01-17: Response to Motion; Low confidence: court not avai
- `401 U.S. 321` — Zenith Radio Corp. v. Hazeltine Rsch. (1971) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `642 F.3d 240` — Fuller (2011) — current: NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- `971 F.2d 811` — Bos. Car Co. v. Acura Auto. Div., Am. Honda Motor Co. (1992) — current: NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2024-10-04: NOTICE of Removal to Plaintiffs by AMERICAN HONDA 
- `514 F.2d 362` — Cicchetti v. Lucy (1975) — current: NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2020-07-06: Complaint; Low confidence: court not available in 
- `804 F.3d 1193` — Certified Pub. Accts. v. I.R.S. (2015) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Certified Public. Accts. v. I.R.S." vs found
- `800 F.2d 970` — Li Hing  Hong Kong, Inc. v. Levin (1986) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Li Hing  Hong Kong, Inc. v. Levin" vs found 
- `985 F.3d 357` — Gonzalez v. Cuccinelli (2021) — current: POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- `698 F.2d 48` — Hahn v. Vt. L. Sch. (1983) — current: NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Hahn v. Vt. L. School." vs found "Petrey v. 

## Still missing after re-verify (100 rows)

These are the rows that look like real candidate CL gaps for SCOTUS/Circuit — but each one still needs manual audit before being counted as a true miss (could be eyecite mis-extraction, format quirk, etc.).

- [Circuit] `947 F.3d 240` — Wojcicki v. SCANA/SCE&G (2020) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `712 F.3d 1` — SEC v. Am. Int’l Grp. (2013) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "SEC v. Am. International Grp." vs found "Fre
- [Circuit] `888 F.3d 197` — D’Onofrio v. Vacation Publ’ns, Inc. (2018) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "D'Onofrio v. Vacation Publ'ns, Inc." vs foun
- [Circuit] `952 F.2d 457` — S. Cal. v. Barr (1991) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "S. California. v. Barr" vs found "Aclu Found
- [Circuit] `789 F.3d 146` — Brown v. Whole Foods Mkt. Grp., Inc. (2015) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Brown v. Whole Foods Mkt. Grp., Inc." vs fou
- [SCOTUS] `498 U.S. 89` — Irwin v. Dep’t of Veterans Affs. (2010) — POSSIBLE_MATCH  diag: Name mismatch: cited "Irwin v. Department of Veterans Affs." vs found "Holland v. Florida"; Citation mismatch: cited 498
- [Circuit] `722 F.3d 345` — Payne v. D.C. Gov’t (2013) — POSSIBLE_MATCH  diag: Found in RECAP (not in opinions database). Document dated 2023-02-03: Appendix in Support filed by Stacy Eley Payne re 3
- [Circuit] `720 F.2d 29` — Comm. v. Webster (1983) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 1983 vs filed 1982-11-18; Citation mismatch: cit
- [Circuit] `454 F.3d 290` — Chaplaincy  Full Gospel Churches v. England (2006) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Chaplaincy  Full Gospel Churches v. England" 
- [Circuit] `2026 WL 1073317` — Int’l Mar. Org. No. 9189952, No. 24- 5218 (2026) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `771 F.3d 713` — “Stansell I”) (2014) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `722 F.3d 677` — Relief & Dev. (2013) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `152 F.4th 339` — Havlish v. Taliban (2025) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Reporter citation 152 F.4th 339 could not be confirmed (CourtListe
- [Circuit] `994 F.2d 874` — Int’l Dev. (1993) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `755 F.3d 448` — United States v. Volpendesto (2014) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `19 F.3d 663` — United States v. Pogue (1994) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `705 F.3d 603` — Bogie v. Rosenberg (2013) — POSSIBLE_MATCH  diag: Found in RECAP (not in opinions database). Document dated 2012-03-20:   JUDGMENT      entered in favor of Defendants Bre
- [Circuit] `367 F.3d 958` — Kaempe v. Myers (2004) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `649 F.3d 688` — United States v. Safavian (2011) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `854 F.3d 721` — Kincaid v. District of Columbia (2017) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Kincaid v. District of Columbia" vs found "P
- [Circuit] `776 F.3d 865` — Williams v. Johnson (2015) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `2026 WL 913399` — United States v. Wilburn, --- F.4th --- (2026) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Reporter citation 2026 WL 913399 could not be confirmed (CourtList
- [Circuit] `526 F. App’x 29` — United States v. Williams (2013) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2013 vs filed 2014-10-30; Reporter citation 526 
- [Circuit] `962 F.3d 568` — United States v. Han (2020) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `763 F.3d 443` — United States v. Fields (2014) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2014 vs filed 2015-09-03; Citation mismatch: cit
- [Circuit] `748 F.3d 1159` — Trebro Mfg., Inc. v. Firefly Equip., LLC (2013) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Trebro Manufacturing., Inc. v. Firefly Equip.
- [SCOTUS] `456 U.S. 694` — Guinee (1982) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `153 F.4th 1` — Global Health Council v. Trump (2025) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Global Health Council v. Trump" ~ found "Glob
- [Circuit] `490 F.3d 1340` — Entegris, Inc. v. Pall Corp. (2007) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `843 F.2d 631` — Castro (1988) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [SCOTUS] `535 U.S. 722` — Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co. (2014) — POSSIBLE_MATCH  diag: Name mismatch: cited "Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co." vs found "Nautilus, Inc. v. Biosig Instrument
- [Circuit] `751 F.3d 1307` — Packard (2014) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `274 F.3d 1354` — Bose Corp. v. JBL, Inc. (2001) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `28 F. 4th 240` — Broadcom Corp. v. Int’l Trade Comm’n (2022) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Broadcom Corp. v. International Trade Commis
- [Circuit] `896 F.3d 1033` — USA), Inc. v. 5 Turchin (2018) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [SCOTUS] `555 U.S. 7` — Winter v. National Resources Defense 7 Council, Inc. (2008) — POSSIBLE_MATCH  diag: Name mismatch: cited "Winter v. National Resources Defense 7 Council, Inc." vs found "Winter v. Natural Resources Defens
- [Circuit] `821 F.2d 714` — Corp. v. EPA (1987) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Corp. v. EPA" ~ found "Kennecott Corp. v. Env
- [Circuit] `679 F.3d 1121` — Pacific Pictures 10 Corp. (2012) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `704 F.3d 568` — Pouncil v. Tilton (2012) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `471 F. App’x 620` — City of Los Angeles (2012) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `522 F.3d 1049` — Supply v. EOFF Elec., Inc. (2008) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Supply v. EOFF Electric., Inc." vs found "Pl
- [Circuit] `430 F.3d 985` — Mpoyo v. Litton 6 Electro-Optical Sys. (2005) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Mpoyo v. Litton 6 Electro-Optical System." v
- [Circuit] `296 F.3d 787` — Nw. Airlines, Inc. v. Camacho (2002) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `374 F.3d 797` — Schwarzenegger v. Fred 25 Martin Motor Co. (2004) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Schwarzenegger v. Fred 25 Martin Motor Co." ~
- [Circuit] `130 F.3d 400` — Planned Parenthood v. Neely (1997) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `814 F.2d 1011` — United States v. Shipco Gen., Inc. (1987) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "United States v. Shipco General., Inc." vs f
- [SCOTUS] `328 U.S. 680` — Anderson v. Mt. Clemens Pottery Co. (1985) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [SCOTUS] `66 S.Ct. 1187` — Anderson v. Mt. Clemens Pottery Co. (1985) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `765 F.2d 1317` — Beliz v. W.H. McLeod & Sons Packing Co. (1985) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Beliz v. W.H. McLeod & Sons Packing Co." vs 
- [SCOTUS] `490 U.S. 488` — Maleng v. Cook (2013) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `837 F.2d 1362` — Mays v. Bowen (1988) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `813 F.2d 55` — Lovelace v. Bowen (1987) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `705 F.2d 123` — Dellolio v. Heckler (1983) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [SCOTUS] `583 U.S. 281` — Jennings v. Rodriquez (2018) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `592 F.3d 759` — Reger Dev., LLC v. Nat’l City Bank (2010) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Reger Dev., LLC v. National City Bank" vs fo
- [Circuit] `910 F.3d 293` — NewSpin Sports, LLC v. Arrow Elecs., Inc. (2018) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "NewSpin Sports, LLC v. Arrow Elecs., Inc." v
- [Circuit] `853 F.3d 876` — Assurance Co., R.R.G. v. First Am. Title Ins. Co. (2017) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Assurance Co., R.R.G. v. First Am. Title Ins
- [Circuit] `153 F.3d 516` — Bennett v. Schmidt (1998) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `667 F.3d 877` — Keeton v. Morningstar, Inc. (2012) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `636 F.3d 312` — Loudermilk v. Best Pallet Co. (2011) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Loudermilk v. Best Pallet Co." ~ found "Loude
- [Circuit] `827 F.3d 656` — Simpson v. Franciscan All., Inc. (2016) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Simpson v. Franciscan All., Inc." ~ found "Si
- [Circuit] `95 F.4th 493` — Gerlach v. Rokita (2024) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `937 F.3d 1016` — Lockett v. Bonson (2019) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `38 F.4th 545` — Brown v. Osmundson (2022) — POSSIBLE_MATCH  diag: Found in RECAP (not in opinions database). Document dated 2026-03-16: Order on Motion to Request Counsel AND Prisoner Me
- [Circuit] `352 F.3d 328` — Ciarpaglini v. Saini (2003) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `590 F. App’x 629` — Blankenship v. Birch (2014) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `940 F.3d 954` — Walker v. Wexford Health Sources, Inc. (2019) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Walker v. Wexford Health Sources, Inc." ~ fou
- [Circuit] `882 F.3d 674` — Avina v. Bohlen (2018) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [SCOTUS] `510 U.S. 471` — F.D.I.C. v. Meyer (1994) — POSSIBLE_MATCH  diag: Name mismatch: cited "F.D.I.C. v. Meyer" vs found "Federal Deposit Insurance v. Meyer", but we identified a possible mat
- [Circuit] `751 F. App’x 928` — Slabon v. Berryhill (2019) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Reporter citation 751 F. App'x 928 could not be confirmed (CourtLi
- [Circuit] `599 F.3d 720` — Ctr. v. BP Prods. North America, Inc. (2012) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Center. v. BP Products. North America, Inc."
- [Circuit] `49 F.3d 1243` — Tolefree v. Cudahy (1995) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `44 F.4th 676` — Helmstetter (2022) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `78 F.4th 976` — Baysal v. Midvale Indem. Co. (2023) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Baysal v. Midvale Indem. Co." vs found "Kowa
- [Circuit] `822 F.2d 1518` — Campbell v. Bowen (1987) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `322 F.3d 912` — Golembiewski v. Barnhart (2003) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [SCOTUS] `602 U.S. 367` — Hippocratic Med. (2024) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `407 F.3d 1` — Co. v. U.S. Env’t Prot. Agency (2005) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Co. v. U.S. Env't Prot. Agency" vs found "Fl
- [Circuit] `637 F.3d 18` — Huffington v. T.C. Grp., LLC (2011) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Huffington v. T.C. Grp., LLC" vs found "Prov
- [Circuit] `669 F.3d 50` — Schatz v. Republican State Leadership Comm. (2012) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Schatz v. Republican State Leadership Commis
- [Circuit] `308 F.3d 25` — Singh v. Blue Cross/Blue Shield of Massachusetts, Inc. (2002) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `19 F.2d 500` — Doidge v. Cunard S.S. Co. (1927) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name differs: cited "Doidge v. Cunard S.S. Co." ~ found "Doidge v.
- [Circuit] `364 F.3d 355` — In Bank of New England Corp.) (2004) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `962 F.3d 60` — Tomasella v. Nestlé USA, Inc. (2020) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2020 vs filed 2019-01-30; Citation mismatch: cit
- [Circuit] `708 F.3d 324` — Latson v. Plaza Home Mortg., Inc. (2013) — NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2013-08-05: Judge Rya W. Zobel: Memorandum of Decision entered
- [Circuit] `86 F.4th 76` — Wiener v. MIB Grp., Inc. (2023) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Wiener v. MIB Grp., Inc." vs found "Foss v. 
- [Circuit] `86 F.4th 76` — Wiener v. MIB Grp., Inc. (2023) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Wiener v. MIB Grp., Inc." vs found "Foss v. 
- [Circuit] `241 F.3d 1267` — Benefield v. McDowall (2001) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `874 F.3d 767` — P.R. Tel. Co. v. San Juan Cable LLC (2017) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2017 vs filed 2018-04-23; Citation mismatch: cit
- [Circuit] `367 F.3d 61` — Acción v. Hernandez (2004) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Date close: cited 2004 vs filed 2003-02-27; Citation mismatch: cit
- [Circuit] `55 F.3d 1` — Grant v. News Grp. Bos., Inc. (1995) — NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2025-01-17: Response to Motion; Low confidence: court not avai
- [Circuit] `2005 WL 5493113` — No. 05-1057 (2005) — NOT_FOUND  diag: We found a possible docket match in RECAP, but no specific document could be verified; Low confidence: court not availab
- [SCOTUS] `401 U.S. 321` — Zenith Radio Corp. v. Hazeltine Rsch. (1971) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `642 F.3d 240` — Fuller (2011) — NOT_FOUND  diag: No matching cases found in CourtListener opinions or RECAP
- [Circuit] `971 F.2d 811` — Bos. Car Co. v. Acura Auto. Div., Am. Honda Motor Co. (1992) — NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2024-10-04: NOTICE of Removal to Plaintiffs by AMERICAN HONDA 
- [Circuit] `514 F.2d 362` — Cicchetti v. Lucy (1975) — NOT_FOUND  diag: Found in RECAP (not in opinions database). Document dated 2020-07-06: Complaint; Low confidence: court not available in 
- [Circuit] `804 F.3d 1193` — Certified Pub. Accts. v. I.R.S. (2015) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Certified Public. Accts. v. I.R.S." vs found
- [Circuit] `800 F.2d 970` — Li Hing  Hong Kong, Inc. v. Levin (1986) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text; Name mismatch: cited "Li Hing  Hong Kong, Inc. v. Levin" vs found 
- [Circuit] `985 F.3d 357` — Gonzalez v. Cuccinelli (2021) — POSSIBLE_MATCH  diag: Low confidence: court not available in citation text, but we identified a possible match.
- [Circuit] `698 F.2d 48` — Hahn v. Vt. L. Sch. (1983) — NOT_FOUND  diag: Low confidence: court not available in citation text; Name mismatch: cited "Hahn v. Vt. L. School." vs found "Petrey v. 
