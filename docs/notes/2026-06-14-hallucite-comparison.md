# Hallucite vs. Citation Verifier — technical comparison & design notes

**Date:** 2026-06-14 (revised 2026-06-15 after reading the full cloned source)
**Subject repo:** https://github.com/hallucite-org/hallucite (hallucite-org/hallucite)
**Status of that repo:** early-stage — v0.1.0, 2 commits, from Cornell. A focused,
well-written prototype. These are technical comparison notes for our own design work.

**Provenance of this note:** the descriptions below were read from the actual cloned
source (`hallucite/*.py`, `scripts/process.py`, `pyproject.toml`), not from the README
or a summarizer. Files read in full: `citation.py`, `citation_matcher.py`,
`citation_lookup.py`, `citation_repair.py`, `citation_extraction.py`, `process.py`.
Not read line-by-line: `db.py`/`db_base.py`, `address.py`, `abbrevs.py`,
`citation_cache.py`, `citation_covered.py`, `tesseract.py`, `pdf.py`, `utils.py`,
`types.py` (their behavior is inferred from call sites).

## What Hallucite does

A Python research project that detects **hallucinated citations in real-world legal
filings**, at scale. Pipeline (`scripts/process.py`): ingest PDF/text/STDIN → OCR if a
PDF has no sidecar `.txt` (Tesseract in the script; Marker-GPU for batch per README) →
extract citations → check each `cite.exists()` → print `N of M (X%) citations exist`
(their demo: Mata v. Avianca, 6/14). Single deterministic pass, **no LLM anywhere**.

### What "exists" actually means (read from `citation.py`) — important correction
Despite the "existence" framing, `Citation.exists()` is **resolution + name verification**,
not bare existence. `load()`:
1. Runs `CitationMatcher.match_case_name(case_name)` against the corpus.
2. **No candidate at the cite location** → invalid, reason `"<cite> not found"`.
3. Candidate found **and** (`parties_match` or fuzzy name-sim ≥ 70) → **exists**; any
   repaired plaintiff/defendant is written back.
4. Candidate found **but name too dissimilar** → invalid, reason
   `"Closest match is <name> (NN%) which is too dissimilar"`.

So it already does a lightweight version of our name-matching / `WRONG_CASE` idea (cite is
real but the caption disagrees). It does **not** do proposition support, RECAP/PACER, or
our richer identity diagnostics. Caveats baked in: it only checks the **first** parallel
cite and **ignores pincites** for existence ("could be a human error").

### Status taxonomy (`CitationStatus`)
`EXISTS / UNCOVERED / UNPUBLISHED / INVALID`. The interesting one is **UNCOVERED**
(`is_covered` via `citation_covered.py`): if the reporter/volume falls outside their
corpus coverage, the citation is *not* called invalid — it's "we can't speak to this."
`UNPUBLISHED` keys off `(Table)` / "unpublished" parentheticals. This is their
reporter-gap guardrail, directly analogous to our `CITE_UNCONFIRMED` reporter-gap policy.

### Data sources (`citation_lookup.py`) — the big architectural difference
No live API. A **local, merged corpus**, queried cache-first, keyed by
`(volume, reporter, page)`:
- **CourtListener**: a **bulk snapshot read from a parquet file into an in-memory cache**
  (`_lookup_from_cl_cache` + `citation_cache.py`). A live-Postgres path
  (`_lookup_from_cl_database`, the `search_citation`⋈`search_opinioncluster` SQL) exists
  but is **commented out / unused** — they moved to the parquet cache.
- **Leagle** scraped cases (`data/leagle/clean/cases.csv`; case name built `P v. D`).
- **SCOTUS** (`data/scotus/missing_scotus_cases.csv`) and **SCDB** Supreme Court Database
  (`data/scotus/missing_scdb_cases.csv`) — explicit gap-fillers for CL's SCOTUS holes.
- **OSCN** Oklahoma State Courts Network (`data/oscn/missing_citations.csv`; adds both
  short and full case-name rows).
- Local CSVs are loaded once and memoized into one merged dict.
- Scraping/persistence stack (per `pyproject.toml`): Scrapy, juriscraper, BeautifulSoup,
  selectolax; Django + SQLAlchemy + Postgres + Alembic.

### Extraction (`citation_extraction.py`)
- eyecite with **HyperscanTokenizer** (note: we must use Aho-Corasick on Windows; they
  assume Hyperscan is available).
- Keeps only `FullCaseCitation`; requires a `volume`; **sanity filters**: volume ≤ 2030,
  and drops noise reporters `T.C. Memo`, `O.S.` (Oklahoma Statutes false positives),
  `App.` (Ohio App. false positives).
- **Parallel-citation grouping** by `full_span()`, then `eyecite.resolve_citations` to
  fold short/supra/id back onto the full cite — one `Citation` per case.
- **Gibberish + address filtering**: `likely_gibberish` on the surrounding 50 chars and a
  non-alpha defendant (only when reporter ≤ 2 letters), plus `looks_like_address`
  (`address.py`) so street addresses aren't mistaken for reporter cites.

### Cite-string canonicalization (`citation.py: possible_cite_strings`)
Uses eyecite's `edition_guess` / `variation_editions` to expand an **ambiguous reporter**
into multiple candidate cite strings (their example: `W.2d` → `Wash. 2d` *and* `Wis. 2d`),
and `reporters_db` to flag neutral cites. Each candidate is looked up.

### Matching algorithm (`citation_matcher.py`)
Module docstring: "keep overall existence semantics unchanged ... without changing
validity decisions" — matching *selects the best candidate / party signal*; `exists()`
decides validity.
- **Tiered** (`CitationMatcher.match_case_name`): exact cite lookup → if none, a
  **citation-typo** match → if exact-cite parties are weak, citation-typo → fuzzy.
- **Citation-typo match** (`find_citation_typo_match`) has a *granular* cite-level
  taxonomy: `VOLUME_TYPO` (vol edit-dist 1), `PAGE_TYPO` (page edit-dist 1),
  `REPORTER_WRONG_SERIES` (F.2d↔F.3d, vol+page exact), `PINCITE` (the "page" is really a
  pincite — finds the largest first-page < cited page in that volume), and `TYPO_2`
  (total Damerau-Levenshtein across vol+reporter+page = 2). **Explicitly skips WL/LEXIS.**
  Gated on reasonable party agreement (exact/surname/prefix — no token-subset/fuzzy).
- **Party matching** is a typed, point-scored taxonomy (independent plaintiff/defendant):
  `EXACT (6) > TYPO_1 (5) > SURNAME (4) > SURNAME_TYPO (3) > PREFIX (2) = SHORT_CITE (2)
  > TOKEN_SUBSET (1)`. Sums P+D; falls back to combined-name fuzzy (rapidfuzz, threshold
  70). Normalization is **OCR-aware**: strips accents (NFD), maps `.`→space ("a space
  gets lost in OCR"), USA-variant special-casing, strips entity suffixes
  (Inc./LLC/Corp./Okla.) and litigation-role suffixes (Plaintiff/Appellant/…).
- **`_try_improving_match`**: when a party boundary looks wrong (eyecite mis-split), it
  walks the **preceding document text** token-by-token, extending *or* shrinking the
  first party until the similarity score improves — then writes the fix back into the
  citation span. A self-repair feedback loop we have no equivalent of.

### Repair (`citation_repair.py`) — eyecite party-extraction cleanup
`repair_party_extraction` applies three strategies:
1. **Oklahoma "Citationizer" detection** (`_is_likely_oklahoma_citationizer`): OK reporters
   (`OK`/`OK CR`/`OK CIV APP`/`P.`/`P.2d`/`P.3d`) + signals in ±100 chars — literal
   "Citationizer", `www.oscn.net/applications`, a `|`-delimited column containing
   "Cited"/"Discussed". These docs put the caption **after** the cite, so parties are
   garbage → **drop plaintiff/defendant entirely**.
2. **Asterisk recovery** (`_repair_party_asterisk`): if an odd number of `*` straddles the
   name, recover the real case name from the `*…*` span in the preceding ≤200 chars.
3. **Prefix stripping** (`_repair_party_prefix`): drop leading `Id.` / `and` / bare `In`
   (preserving `In re`).

## How it's similar to us
- Same mission: catch AI-hallucinated case citations.
- **Same extraction core: eyecite + reporters-db**, and both of us fight eyecite's
  party-extraction quirks (their `citation_repair.py` ≈ our parser fallbacks /
  `text_cleaner.py` / slip-op junk stripping / abbreviation normalization).
- Both verify the **case name**, not just that the cite resolves (their step 3/4 above is
  our name-match gate).
- Both have a **coverage-gap guardrail** so a reporter we/they don't hold isn't branded a
  hallucination (their `UNCOVERED` ≈ our `CITE_UNCONFIRMED` reporter-gap policy).
- Both do tiered fallback matching with fuzzy party comparison and surname/prefix/typo
  handling and a "short cite" notion.

## How it's different from us
| Axis | Hallucite | Citation Verifier (us) |
|------|-----------|------------------------|
| **Scope** | Resolve + name-verify ("real case, right caption?") | That **+ identity diagnostics** (`WRONG_CASE`) **+ proposition support** (LLM layer) |
| **LLMs** | None — fully deterministic | LLM-assisted proposition/assessment pipeline |
| **Data access** | Local bulk corpus, cache-first (CL parquet + Leagle + SCOTUS/SCDB + OSCN) | **Live CourtListener API** (citation-lookup + opinion search + **RECAP/PACER**) |
| **Ingestion** | **OCR-first** (Tesseract / Marker-GPU) for scanned filings | eyecite over extractable PDF/text; no OCR |
| **Cite-digit typos** | Granular typo taxonomy (vol/page/series/pincite, total dist ≤2), party-gated, WL/LEXIS-excluded | We mostly require exact reporter resolution in Step 1 |
| **Party self-repair** | Walks preceding text to fix eyecite mis-splits | Targeted regex cleanups only |
| **Court coverage** | Federal + targeted state gap-fills (Oklahoma/OSCN, SCDB) | 135 federal courts + regional-reporter→state inference; RECAP federal-only |
| **Maturity** | v0.1.0, 2 commits, prototype | Mature: ~250+ tests, web app, skills, versioned prompts, CHANGELOG |

We cover more of the verification problem (identity diagnostics + proposition support +
RECAP). Their **ingestion, corpus architecture, and matcher robustness** take a different
approach that's instructive for our own design.

## Techniques worth evaluating for our pipeline (ranked)

These are independently arrived-at approaches in their public code that bear on design
choices we face. (hallucite has no LICENSE file, i.e. all rights reserved — so this is
about *approaches and ideas*, not reusing their code.)

1. **Citation-digit typo tolerance (highest value).** `find_citation_typo_match` catches a
   *real* case cited with a transposed/OCR-garbled page or volume, or the wrong reporter
   series (F.2d↔F.3d), via Damerau-Levenshtein ≤ 2 — and it **gates on party agreement**,
   the guardrail that keeps "fuzzy on the digits" from blessing a hallucination. Today a
   real case with a one-digit page typo can fall through our exact citation-lookup to
   `NOT_FOUND`. Safer framing for us: surface as a **diagnostic / "did you mean 576 U.S.
   64**4**?"** or a `VERIFIED_PARTIAL`-style status, not a silent VERIFIED. Note their
   explicit **WL/LEXIS exclusion** — typo-matching opaque IDs is meaningless.

2. **Pincite-typo detection.** `_is_pincite_typo` recognizes when the cited "page" is
   actually a pincite into a case whose first page is lower. We have a star-pagination
   pincite *crosscheck*, but theirs runs at **match time** and can rescue a cite we'd miss.
   Compare against our crosscheck logic.

3. **Party-boundary self-repair (`_try_improving_match`).** Extends/shrinks the party
   against preceding text, scored by similarity, then rewrites the span. A more general
   answer to eyecite mis-splits than our regex cleanups — likely cuts name-mismatch false
   negatives. Conceptually the strongest idea in their matcher; higher effort to adopt.

4. **Cheap extraction-hygiene filters:** volume ≤ 2030 sanity bound, dropping noise
   reporters (`T.C. Memo`/`O.S.`/`App.`), gibberish detection on surrounding text, and
   **address detection** so street addresses aren't parsed as reporter cites. The same
   ideas would be low-risk precision wins for our parser.

5. **OCR-first ingestion (Marker) for scanned filings.** Our proposition-verifier intake
   assumes extractable PDF text; real filings are often image-only scans. A Tesseract/
   Marker front-end widens what `extract` accepts. Marker is GPU-heavy — keep it optional.

6. **Local CL bulk snapshot (parquet) as a batch accelerator/cache.** We're API-bound
   (1s rate limit, 15s timeout, 429s, RECAP gating). A parquet snapshot for cache-first
   lookups would speed `verify_batch`, cut API dependence, and enable offline runs; defer
   misses to the live API for best-of-both. Tradeoff: staleness + storage.

7. **Supplemental gap-fill corpora (Leagle / SCDB / OSCN).** We already model CL reporter
   gaps (the `CITE_UNCONFIRMED` "reporter-gap compensation"). They patch those gaps with
   other corpora so a CL miss becomes a *positive* confirmation. Worth evaluating
   Leagle/SCDB as a second existence source — and SCDB in particular for SCOTUS.

8. **Coverage-aware status (`UNCOVERED`).** An explicit "outside our coverage" state,
   distinct from "invalid," is a clean way to avoid false hallucination calls. Validates
   our `CITE_UNCONFIRMED` direction and suggests making the coverage boundary explicit.

9. **Typed, point-scored match taxonomy for explainability.** Their categorical labels
   (EXACT/TYPO_1/SURNAME/PREFIX/TOKEN_SUBSET/SHORT_CITE/…) are more auditable than our
   continuous score; emitting the *category* alongside the number would help the Debug page.

10. **Ambiguous-reporter expansion** (`W.2d` → `Wash. 2d`/`Wis. 2d`) via eyecite editions,
    looking up every candidate. Worth checking we don't silently drop ambiguous reporters.

11. Minor: `rapidfuzz` (Damerau-Levenshtein) over stdlib `difflib` — faster, and needed if
    we adopt the cite-digit typo idea.

## Capabilities specific to our project
Proposition support (the genuinely hard problem), richer identity diagnostics
(`WRONG_CASE` with "belongs to …"), RECAP/PACER docket verification, two-axis scoring +
Check Cite, a web app + QC workflow, and a deep deterministic test/replay harness. The
two projects emphasize different halves of the problem — they invest in ingestion + a
bulk corpus + a robust matcher; we invest in verification depth + the proposition layer.
