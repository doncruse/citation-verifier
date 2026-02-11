# Cases to Investigate

## Extraction issues (parser / eyecite / PDF)

These affect the quality of citation data passed to the verifier.

### Parsing oddities
- "Odd v. Malone, 538 F.3d 202 (3d Cir. 2008)" — line break caused citation to not be recognized
- "Button v. Doherty, Case No. 24 Civ. 5026 (JPC) (KHP), 2025 WL 2776069 at *5 n. 7 (S.D.N.Y. Sept. 30, 2025)" — suspect parsing issue with case number
- "In re Suday II), No. 04-20-00510-CV, 2020 WL 7232130 (2020)" — stray `)` in case name from PDF extraction artifact

### Short cite handling
- "M.G., 566 P.3d at 146-147" — needs resolution back to the full citation earlier in the document. Does eyecite support this?

## Verifier issues

These are bugs or improvements needed in the verification pipeline.

### False negatives (verifier fails to find a real case)
- "Estate of Elkins v. Pelayo, Case No. 1:13-CV-1483 AWI SAB, 2020 WL 2571387, at *4 n.3 (E.D. Cal. May 21, 2020)" — failed to locate docket https://www.courtlistener.com/docket/5940372/elkins-v-california-highway-patrol/ (same case number, slightly different case name) and document https://www.courtlistener.com/docket/5940372/230/elkins-v-california-highway-patrol/
- "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, 2025 WL 459154, at *1 (W.D. Wash. Feb. 11, 2025)" — failed to locate docket https://www.courtlistener.com/docket/69346061/bossart-v-king-county/ and document https://www.courtlistener.com/docket/69346061/27/bossart-v-king-county/
- "Busha v. SC Dep't of Mental Health, No. 6:18-CV-02337-DCC, 2019 WL 651680 (D.S.C. Feb. 13, 2019)" — failed to locate docket and document https://www.courtlistener.com/docket/14553775/15/busha-v-sc-department-of-mental-health/

### Wrong PACER document selected
- "Button v. Breshears, Case No. 1:24-cv-03757-MKV, 2025 WL 2771663 (S.D.N.Y. Sept. 26, 2025)" — returned wrong document with wrong date, should have been https://www.courtlistener.com/docket/68536491/41/button-v-breshears/
- "Straw v. Avvo Inc., Case No. C20-0294JLR, 2020 WL 5066939 at *5 n. 4 (W.D. Wash. Aug. 27, 2020)" — returned wrong document with wrong date, should have been https://www.courtlistener.com/docket/16888269/44/straw-v-avvo-inc/
- "Mader v. Advanced Neuromodulation Sys., Inc., 2005 WL 1863181 (E.D. La. Aug. 3, 2005)" — RECAP matched wrong docket entirely (returned a 2025 order from an unrelated case)

## CourtListener data issues (unfixable on our end)

These are coverage gaps or data problems in CL itself. Citations will always be NOT_FOUND.

- "Jha v. Khan, 520 P.3d 470, 477 (Wash. Ct. App. 2022)" — CL doesn't have this case, available at https://www.courts.wa.gov/opinions/pdf/837681.pdf
- "Fowler v. Guerin, 515 P.3d 502, 506 (Wash. 2022)" — CL doesn't have this case, available at https://www.courts.wa.gov/opinions/index.cfm?fa=opinions.showOpinion&filename=1000693MAJ
- "M.G. v. Bainbridge Island School District #303, 566 P.3d 132, 147 (Wash. Ct. App. 2025)" — CL doesn't have
- "Himes v. Provident Life & Accident Insurance Co., No. 3:19-CV-00215, 2020 WL 9935829 (M.D. Tenn. Mar. 3, 2020)" — opinion not marked as free
- "Neravetla v. Virginia Mason Med. Ctr., No. C13-1501-JCC, 2014 WL 12787876, *3-*4 (W.D. Wash. May 23, 2014)" — opinion not marked as free https://www.courtlistener.com/docket/5262939/neravetla-v-virginia-mason-medical-center/
- "Booth v. Allstate Ins. Co., 198 Cal.App.3d 1357 (1988)" — real case, CL doesn't have it (CalApp coverage gap)
