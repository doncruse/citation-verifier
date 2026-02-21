# Draft comment for CourtListener #6963

## Target
https://github.com/freelawproject/courtlistener/issues/6963

## Comment

### Diagnostic: `is_free_on_pacer` field on all 16 documents

I checked the `is_free_on_pacer` field on each RECAP document via the API (`/api/rest/v4/recap-documents/`) to see whether these opinions were flagged by PACER's Written Opinion Report. If they weren't flagged as free, that could explain why `recap_into_opinions` skipped them.

**Result: 13 of 16 have `is_free_on_pacer=True`.** The pipeline should have seen these documents.

| Case | Year | `is_free_on_pacer` | `is_available` | Pages |
|------|------|--------------------|----------------|-------|
| **Pre-sweep** | | | | |
| Fagundes v. Charter Builders | 2008 | True | True | 12 |
| Mali v. British Airways | 2018 | True | True | 28 |
| King v. Police & Fire FCU | 2019 | True | True | 1 |
| Ruggierlo v. Lancaster | 2023 | True | True | 9 |
| **Sweep-edge** | | | | |
| Dukuray v. Experian | 2024 | True | True | 9 |
| **Post-sweep** | | | | |
| Tercero v. Sacramento Logistics | 2025 | True | True | 24 |
| Oneto v. Watson | 2025 | True | True | 7 |
| Russomanno v. Comm'r of Soc. Sec. | 2025 | True | True | 5 |
| Glass v. Foley & Lardner | 2025 | True | True | 7 |
| Thomas v. Pangburn | 2024 | True | True | 1 |
| Lahti v. Consensys | 2025 | True | True | 17 |
| Coronavirus Reporter v. Apple | 2025 | True | True | 14 |
| Davis v. Marion County | 2025 | True | True | 10 |
| Button v. Humphries | 2025 | None | False | — |
| Welfare Fund v. HoosierVac | 2025 | None | True | 2 |
| O'Brien v. Flick | 2025 | None | False | 2 |

**3 cases have `is_free_on_pacer=None`:** Button, HoosierVac, and O'Brien were never flagged by PACER as free written opinions. For these three, the pipeline not ingesting them is expected — it never saw them.

**The 13 `True` cases are the real puzzle** — especially the 4 pre-sweep cases (all `True`). PACER flagged them, the documents are available with extracted text, yet they didn't make it into the opinions DB. Could the pipeline's citation-extraction step be the bottleneck? If these documents lack case law citations in their text, that would be a pipeline filter rather than a pipeline bug. Happy to spot-check the document text for citations if that would help narrow it down.
