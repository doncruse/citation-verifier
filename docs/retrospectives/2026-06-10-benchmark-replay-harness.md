# Benchmark Replay Harness + the Muldrow Finding

**Date:** 2026-06-10
**Goal:** A bigger, faster, deterministic regression test — and validate that
the false-positive tightening (Levers 1–3, Step 4) didn't quietly start
rejecting *real* cases.

## What was built

A record/replay harness so interpretation-logic changes can be regression-
tested offline:

- **`tests/cassette_client.py`** — wraps `CourtListenerClient` at its public-
  method seam. `mode="record"` calls live and caches every return value;
  `mode="replay"` serves from cache and never touches the network. Keyed by
  (method, args, kwargs).
- **`tests/data/benchmark_real_citations.json`** — 204 real citations mined
  from the spun-off `case-law-proposition-benchmark` gold DB
  (`model_answers` where `cite_resolved_real=1`), deduped, with the
  benchmark's resolved `cluster_id` as expected truth.
- **`tests/record_benchmark_cassette.py`** — one-time (periodic) LIVE run that
  records the cassette + a baseline verdict per citation. `--from-cassette`
  recomputes the baseline by REPLAYING offline — use after a scoring change to
  refresh expected verdicts with zero API calls.
- **`tests/test_benchmark_regression.py`** — offline; replays the cassette
  through current logic and fails if any citation that resolved at record time
  now fails (new false negative). Runs in the normal suite.

**The payoff is concrete:** the full 204-case regression replays in **~2
seconds offline**, versus ~10 minutes of rate-limited live calls. Every change
this session was pure *interpretation* of the same API responses, so a cassette
is the right tool.

## The bigger test result

Recorded live: **202/204 resolved (99%)**. 179 of those matched the
benchmark's exact `cluster_id`; the other ~23 resolved to a *different* CL
cluster for the same case (CL parallel/duplicate clusters — we verified by
name, so not false positives). 1 transient `VERIFICATION_INCOMPLETE`. And **1
genuine false negative** — which turned out to be ours.

## The Muldrow finding (a real Lever 3 regression, caught and fixed)

**`Muldrow v. City of St. Louis, 144 S. Ct. 967 (U.S. 2024)`** came back
`NOT_FOUND`. Tracing it:

- The case is real — CL has it under the **parallel** cite `601 U.S. 346`.
- Our opinion search *found* it by name, but scored it **exactly 0.39** — the
  Lever 3 cap value.
- Root cause: Lever 3's no-corroboration cap had a **reporter-cite
  contradiction** arm. The cited `144 S. Ct. 967` isn't in CL's citation list
  (which has the U.S. parallel cite), so it was flagged a "contradiction" and
  capped — even though name and court matched. This is the exact
  parallel-citation false-negative risk flagged when Lever 3 landed.

**Fix:** drop the reporter/WL arm from the cap trigger; keep only party
mismatch and **docket-number** contradiction. A docket number has no benign
"parallel" form, so its contradiction is reliable; a reporter mismatch is too
often just a parallel citation. The cite arm was never load-bearing — Lopez and
Johnson (the Lever 3 FPs) are caught by the docket arm. TDD:
`test_parallel_reporter_citation_not_capped`.

**Validated:** Muldrow now resolves (**203/204**); the live fake corpus stays
**0/19**; removing a cap trigger can only un-cap (raise scores), so it cannot
create new false negatives. Full mocked suite 446 passed.

## Honest caveats

- **Coverage skew:** 204 cites → only 205 cached calls, i.e. ~every one
  resolved at the *first* stage (citation-lookup). So this corpus exercises
  citation-lookup heavily but barely touches the RECAP/opinion-search fallback
  scoring where Levers 1–3 + Step 4 actually live. It is the right guard for
  "do we still find real published cases," and the wrong one for "did our RECAP
  scoring regress" — the 19-case fake corpus and the WL-heavy 14-case real
  corpus cover that. The two are complementary, not redundant.
- **Label/cluster noise:** the benchmark's `cluster_id` and real/fake labels
  reflect CL's May-2026 state and the benchmark's own resolution; the ~23
  cluster-id differences are mostly that, not bugs.
- **Drift:** the cassette is a snapshot. Re-record periodically (live) to catch
  CourtListener data changes; `--from-cassette` only re-derives verdicts from
  the existing snapshot.

## Fallback corpus — closes the coverage gap (2026-06-10)

The benchmark corpus resolves almost entirely at citation-lookup, so it does
not exercise the fallback scoring our recent work changed. Rebecca's May-2026
FLP coverage study (`case-law-proposition-benchmark/scratch/cl-coverage-
offshoot/coverage_memo.docx` + `coverage_per_citation.csv`) already mapped
this: it ran `quick_only=True` (lookup only) over 250 real cited citations, so
every `lookup_status=NOT_FOUND` row is a real case that *bypasses* lookup and
drives the fallback.

`tests/build_fallback_corpus.py` reconstructs full citations from those 74
lookup misses (name + cite + court/year), keeping the 51 standalone ones
(dropping pinpoint/short forms like "189 AD3d at 90"). Recorded with the same
harness (`--corpus-name fallback`); the baseline now also stores the
`winning_stage`.

**Result: 32/51 resolve, and 100% of them via fallback stages — 23 via
opinion_search, 9 via recap_docket_search (0 via citation_lookup).** Status
mix: 23 VERIFIED, 7 VERIFIED_DOCKET_ONLY, 2 VERIFIED_VIA_RECAP — i.e. it
actually drives the RECAP/opinion-search code Levers 1-3 + Step 4 touch. The
remaining 18 NOT_FOUND are real CL coverage gaps the memo already catalogued
(WL/Lexis-only district orders, scraper misses) — not our bug; left unguarded.

`tests/test_fallback_regression.py` (offline, ~3s) guards three things: no new
fallback false negatives, **no silent resolution-path migration** (a cite that
resolved via opinion_search must keep doing so — catches a fallback-scoring
change that flips the winning stage even when the verdict label holds), and a
sanity check that the corpus still exercises fallback stages.

## Open / not done

- **Fake mining (Damien Charlotin's database, ~1,598 court-confirmed
  hallucination cases):** the right source for scaling the *false-positive*
  side (where our recent work focused). Blocked on access — the site and its
  CSV (`/hallucinations/hallucinations/download.csv`) return HTTP 403 to
  automated fetchers. Needs a human to download the CSV; even then it is
  case-level (ruling links + "nature of hallucination" prose), so extracting
  clean fabricated citation strings means processing the linked rulings (how
  the existing 8 court-confirmed fakes were built). A real sub-project.
