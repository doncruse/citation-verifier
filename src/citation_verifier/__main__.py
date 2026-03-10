"""CLI interface for citation verification."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from .cache import VerificationCache
from .models import VerificationResult, VerificationStatus
from .verifier import CitationVerifier

# Status -> display style
_STATUS_LABELS = {
    VerificationStatus.VERIFIED: "[OK] VERIFIED",
    VerificationStatus.LIKELY_REAL: "[~] LIKELY REAL",
    VerificationStatus.POSSIBLE_MATCH: "[?] POSSIBLE MATCH",
    VerificationStatus.NOT_FOUND: "[X] NOT FOUND",
}


def _print_result(result: VerificationResult, json_mode: bool) -> None:
    if json_mode:
        d = asdict(result)
        d["status"] = result.status.value
        print(json.dumps(d, indent=2))
        return

    label = _STATUS_LABELS.get(result.status, result.status.value)
    print(f"\n  Citation: {result.input_citation}")
    print(f"  Status:   {label}")
    print(f"  Confidence: {result.confidence:.0%}")

    if result.matched_case_name:
        print(f"  Match:    {result.matched_case_name}")
    if result.matched_url:
        print(f"  URL:      {result.matched_url}")

    if result.diagnostics:
        print("  Issues:")
        for diagnostic in result.diagnostics:
            print(f"    - {diagnostic}")

    if result.candidates and result.status in (
        VerificationStatus.POSSIBLE_MATCH,
        VerificationStatus.NOT_FOUND,
    ):
        print("  Candidates:")
        for c in result.candidates[:3]:
            print(
                f"    - {c.case_name} ({c.date_filed}, {c.court_id}) "
                f"score={c.score:.2f}  {c.url}"
            )

    if result.error:
        print(f"  Error:    {result.error}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="citation-verifier",
        description="Verify legal citations against CourtListener.",
    )
    parser.add_argument(
        "citations",
        nargs="*",
        help="Citation strings to verify",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="File with one citation per line",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the results cache",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear the results cache and exit",
    )
    args = parser.parse_args(argv)

    if args.clear_cache:
        cache = VerificationCache()
        count = cache.clear()
        print(f"Cache cleared ({count} entries removed).")
        return 0

    citations: list[str] = list(args.citations)
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    citations.append(line)

    if not citations:
        parser.error("No citations provided. Pass them as arguments or use --file.")

    cache = None if args.no_cache else VerificationCache()
    verifier = CitationVerifier()

    # Check cache for hits, collect misses for batch verification
    results: list[VerificationResult | None] = [None] * len(citations)
    to_verify: list[tuple[int, str]] = []

    for i, cite_text in enumerate(citations):
        if cache:
            cached = cache.get(cite_text)
            if cached:
                results[i] = cached
                continue
        to_verify.append((i, cite_text))

    if cache and len(citations) > len(to_verify) and to_verify:
        print(
            f"  Cache: {len(citations) - len(to_verify)} cached, "
            f"{len(to_verify)} to verify",
            file=sys.stderr if args.json_mode else sys.stdout,
        )

    if to_verify:
        if len(to_verify) == 1:
            # Single citation -- use sync path (simpler, no event loop needed)
            idx, cite_text = to_verify[0]
            result = verifier.verify(cite_text)
            results[idx] = result
            if cache:
                cache.put(cite_text, result)
        else:
            # Multiple citations -- use async batch verification
            uncached_cites = [cite for _, cite in to_verify]

            def _progress(done: int, total: int) -> None:
                print(
                    f"  Verifying {done}/{total}...",
                    file=sys.stderr if args.json_mode else sys.stdout,
                    flush=True,
                )

            batch_results = asyncio.run(
                verifier.verify_batch(uncached_cites, progress_callback=_progress)
            )
            for (idx, cite_text), result in zip(to_verify, batch_results):
                results[idx] = result
                if cache:
                    cache.put(cite_text, result)

    # Print all results in original order
    any_not_found = False
    for result in results:
        assert result is not None
        _print_result(result, args.json_mode)
        if result.status == VerificationStatus.NOT_FOUND:
            any_not_found = True

    return 1 if any_not_found else 0


def verify_brief_main(argv: list[str] | None = None) -> int:
    """CLI for brief verification pipeline."""
    parser = argparse.ArgumentParser(
        prog="citation-verifier verify-brief",
        description="Verify citations in a legal brief working directory.",
    )
    parser.add_argument(
        "workdir",
        help="Brief working directory (contains claims.csv, citations_to_verify.txt)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--wave1", action="store_true",
        help="Run wave 1 only (batch citation lookup + download)",
    )
    group.add_argument(
        "--wave2", action="store_true",
        help="Run wave 2 only (fallback search for misses)",
    )
    group.add_argument(
        "--merge", action="store_true",
        help="Merge verification results into claims.csv",
    )
    group.add_argument(
        "--full", action="store_true", default=True,
        help="Run full pipeline: wave1 + wave2 + merge (default)",
    )
    args = parser.parse_args(argv)

    from pathlib import Path
    from .brief_pipeline import (
        wave1_verify_and_download,
        wave2_fallback_and_download,
        merge_claims,
        full_pipeline,
    )

    workdir = Path(args.workdir)
    if not workdir.exists():
        print(f"Error: workdir does not exist: {workdir}", file=sys.stderr)
        return 1

    def _progress(done: int, total: int) -> None:
        print(f"  Verifying {done}/{total}...", flush=True)

    # Load citations from citations_to_verify.txt
    def _load_citations() -> list[str]:
        cite_file = workdir / "citations_to_verify.txt"
        if not cite_file.exists():
            print(f"Error: {cite_file} not found", file=sys.stderr)
            sys.exit(1)
        citations = []
        with open(cite_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    citations.append(line)
        return citations

    if args.merge and not args.wave1 and not args.wave2:
        stats = merge_claims(workdir)
        print(f"Merge: {stats.matched} matched, {stats.unmatched} unmatched, "
              f"{stats.opinion_count} with opinions")
        for status, count in sorted(stats.statuses.items()):
            print(f"  {status}: {count}")
        return 0

    if args.wave1:
        citations = _load_citations()
        print(f"Wave 1: verifying {len(citations)} citations (quick lookup)...")
        result = asyncio.run(wave1_verify_and_download(workdir, citations, _progress))
        print(f"Wave 1 complete: {result.download_stats}")
        print(f"  Misses for wave 2: {len(result.miss_indices)}")
        return 0

    if args.wave2:
        citations = _load_citations()
        # Read wave1 results to find misses
        vr_path = workdir / "verification_results.csv"
        if not vr_path.exists():
            print("Error: run --wave1 first", file=sys.stderr)
            return 1
        import csv as csv_mod
        verified_cites = set()
        with open(vr_path, newline="", encoding="utf-8") as f:
            for row in csv_mod.DictReader(f):
                if row.get("status") in ("VERIFIED", "LIKELY_REAL", "POSSIBLE_MATCH"):
                    verified_cites.add(row.get("citation", ""))
        miss_indices = [
            i for i, c in enumerate(citations) if c not in verified_cites
        ]
        print(f"Wave 2: {len(miss_indices)} misses to resolve...")
        result = asyncio.run(wave2_fallback_and_download(
            workdir, citations, miss_indices, _progress,
        ))
        print(f"Wave 2 complete: {result.download_stats}")
        return 0

    # Default: full pipeline
    citations = _load_citations()
    print(f"Full pipeline: {len(citations)} citations...")
    result = asyncio.run(full_pipeline(workdir, citations, _progress))
    print(f"Wave 1: {result.wave1.download_stats}")
    print(f"  Misses: {len(result.wave1.miss_indices)}")
    print(f"Wave 2: {result.wave2.download_stats}")
    print(f"Merge: {result.merge.matched} matched, {result.merge.unmatched} unmatched")
    return 0


if __name__ == "__main__":
    # Dispatch to verify-brief subcommand if first arg matches
    if len(sys.argv) > 1 and sys.argv[1] == "verify-brief":
        sys.exit(verify_brief_main(sys.argv[2:]))
    sys.exit(main())
