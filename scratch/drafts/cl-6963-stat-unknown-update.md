# Draft comment for CourtListener #6963

## Target
https://github.com/freelawproject/courtlistener/issues/6963

## Comment

### Correction: 9 of these 16 are actually in the opinions database

I discovered that my opinion searches were only returning Published results. The search API defaults to Published-only when no `stat_` parameters are provided, and the RECAP-ingested opinions are all classified as `precedential_status: Unknown`. After adding `stat_Unknown=on`, 9 of the 16 cases I reported are found in the opinions database.

Filed #7049 about the default behavior and missing documentation for `stat_` parameters.

**Remaining 7 cases — not found even with `stat_Unknown=on`:**

| Citation | Year | Court | RECAP Document |
|----------|------|-------|---------------|
| Fagundes v. Charter Builders, Inc., 2008 WL 268977 | 2008 | N.D. Cal. | [docket/5793562/104](https://www.courtlistener.com/docket/5793562/104/fagundes-v-charter-builders-inc/) |
| Mali v. British Airways, 2018 WL 3329858 | 2018 | S.D.N.Y. | [docket/7378483/44](https://www.courtlistener.com/docket/7378483/44/mali-v-british-airways/) |
| King v. Police & Fire Fed. Credit Union, No. 16-6414, 2019 WL 2226049 | 2019 | E.D. Pa. | [docket/7632576/31](https://www.courtlistener.com/docket/7632576/31/king-v-police-and-fire-federal-credit-union/) |
| Ruggierlo, Velardo, Burke, Reizen & Fox, P.C. v. Lancaster, 2023 WL 5846798 | 2023 | E.D. Mich. | [docket/64925451/25](https://www.courtlistener.com/docket/64925451/25/ruggierlo-velardo-burke-reizen-fox-pc-v-lancaster/) |
| Button v. Humphries, No. 24-cv-01730, 2025 WL 2994725 | 2025 | C.D. Cal. | [docket/69037800/148](https://www.courtlistener.com/docket/69037800/148/dusty-button-v-micah-humphries/) |
| Thomas v. Pangburn, 2024 WL 329947 | 2024 | S.D. Ga. | [docket/67565382/64](https://www.courtlistener.com/docket/67565382/64/thomas-v-pangburn/) |
| O'Brien v. Flick, No. 25-10143, 2025 WL 2731627 | 2025 | 11th Cir. | [docket/69638127/30](https://www.courtlistener.com/docket/69638127/30/emmet-obrien-v-paul-flick/) |

4 pre-sweep (2008–2023), 3 post-sweep (2024–2025).
