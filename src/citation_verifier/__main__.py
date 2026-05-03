"""CLI interface for citation verification."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

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


def _result_to_json_dict(result: VerificationResult) -> dict:
    """JSON shape for a single-citation verification result.

    The first nine fields are the canonical schema shared with the
    verify-batch CSV: ``citation``, ``status``, ``matched_cluster_id``,
    ``matched_url``, ``matched_case_name``, ``matched_court_id``,
    ``matched_date_filed``, ``confidence``, ``diagnostics``.

    The tail (``candidates``, ``error``) is bonus debug data exposed
    only via ``--json``, not in the CSV. Useful for one-off debugging
    of POSSIBLE_MATCH and NOT_FOUND outcomes.
    """
    return {
        "citation": result.input_citation,
        "status": result.status.value,
        "matched_cluster_id": result.matched_cluster_id,
        "matched_url": result.matched_url,
        "matched_case_name": result.matched_case_name,
        "matched_court_id": result.matched_court,
        "matched_date_filed": result.matched_date,
        "confidence": result.confidence,
        "diagnostics": [
            {"category": d.category, "message": d.message}
            for d in (result.diagnostics or [])
        ],
        "candidates": [
            {
                "case_name": c.case_name,
                "url": c.url,
                "cluster_id": c.cluster_id,
                "date_filed": c.date_filed,
                "court_id": c.court_id,
                "score": c.score,
                "description": c.description,
                "mismatches": [
                    {"category": d.category, "message": d.message}
                    for d in (c.mismatches or [])
                ],
            }
            for c in (result.candidates or [])
        ],
        "error": result.error,
    }


def _print_result(result: VerificationResult, json_mode: bool) -> None:
    if json_mode:
        # One JSON object per line so multi-citation output is NDJSON.
        print(json.dumps(_result_to_json_dict(result), ensure_ascii=False))
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
        "--check-quotes", action="store_true",
        help="Run verbatim quote checker on claims.csv",
    )
    group.add_argument(
        "--metadata-check", action="store_true",
        help="Run metadata sanity check on merged claims",
    )
    group.add_argument(
        "--report", action="store_true",
        help="Generate HTML report from assessed claims",
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

    if args.metadata_check:
        from .brief_pipeline import metadata_check
        result = metadata_check(workdir)
        print(f"Metadata check: {result.total_claims} claims")
        print(f"  Name mismatches: {result.name_mismatches}")
        print(f"  NOT_FOUND: {result.not_found}")
        print(f"  No opinion: {result.no_opinion}")
        if result.flagged_claims:
            print(f"  Flagged for mandatory assessment ({len(result.flagged_claims)}):")
            for fc in result.flagged_claims:
                print(f"    - p.{fc['page']}: {fc['cited_case']} [{', '.join(fc['flags'])}]")
        if result.syllabus_items:
            print(f"  Syllabus check ({len(result.syllabus_items)}):")
            for si in result.syllabus_items:
                print(f'    - p.{si["page"]}: "{si["proposition"][:80]}" / Syllabus: "{si["syllabus"][:80]}"')
        return 0

    if args.report:
        from .brief_pipeline import generate_report
        import json as json_mod
        meta_path = workdir / "brief_metadata.json"
        meta = {}
        if meta_path.exists():
            meta = json_mod.loads(meta_path.read_text(encoding="utf-8"))
        report_path = generate_report(
            workdir,
            title=meta.get("title", ""),
            case_name=meta.get("case_name", ""),
            case_number=meta.get("case_number", ""),
            filed_date=meta.get("filed_date", ""),
            report_date=meta.get("report_date", ""),
        )
        print(f"Report generated: {report_path}")
        return 0

    if args.check_quotes:
        from .brief_pipeline import check_quotes
        stats = check_quotes(workdir)
        print(f"Quote check: {stats.total_claims} claims, {stats.checked} checked")
        print(f"  VERBATIM: {stats.verbatim}, CLOSE: {stats.close}, FABRICATED: {stats.fabricated}")
        print(f"  No quotes: {stats.no_quotes}, No opinion: {stats.no_opinion}")
        return 0

    if args.merge and not args.wave1 and not args.wave2 and not args.check_quotes:
        stats = merge_claims(workdir)
        print(f"Merge: {stats.matched} matched, {stats.unmatched} unmatched, "
              f"{stats.opinion_count} with opinions")
        for status, count in sorted(stats.statuses.items()):
            print(f"  {status}: {count}")
        if stats.unmatched_claims:
            print(f"  Unmatched claims ({len(stats.unmatched_claims)}):")
            for cite in stats.unmatched_claims:
                print(f"    - {cite}")
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
    if result.merge.unmatched_claims:
        print(f"  Unmatched claims ({len(result.merge.unmatched_claims)}):")
        for cite in result.merge.unmatched_claims:
            print(f"    - {cite}")
    return 0


_VERIFY_BATCH_OUTPUT_COLUMNS = [
    "citation",
    "status",
    "matched_cluster_id",
    "matched_url",
    "matched_case_name",
    "matched_court_id",
    "matched_date_filed",
    "confidence",
    "diagnostics_json",
]


def _result_to_row(result: VerificationResult) -> dict[str, str]:
    diagnostics = [
        {"category": d.category, "message": d.message}
        for d in (result.diagnostics or [])
    ]
    return {
        "citation": result.input_citation,
        "status": result.status.value,
        "matched_cluster_id": (
            str(result.matched_cluster_id)
            if result.matched_cluster_id is not None
            else ""
        ),
        "matched_url": result.matched_url or "",
        "matched_case_name": result.matched_case_name or "",
        "matched_court_id": result.matched_court or "",
        "matched_date_filed": result.matched_date or "",
        "confidence": f"{result.confidence}",
        "diagnostics_json": json.dumps(diagnostics, ensure_ascii=False),
    }


def verify_batch_main(argv: list[str] | None = None) -> int:
    """CLI for batch citation verification from a CSV.

    Reads citations from a CSV column and writes verification results
    to an output CSV with a stable column schema.
    """
    import csv as csv_mod
    from pathlib import Path

    from .models import ParsedCitation
    from .parser import parse_citation

    parser = argparse.ArgumentParser(
        prog="citation-verifier verify-batch",
        description="Verify a batch of citations from a CSV file.",
    )
    parser.add_argument("input", help="Input CSV file with a citation column")
    parser.add_argument(
        "--column",
        required=True,
        help="Name of the column in the input CSV containing citation strings",
    )
    parser.add_argument(
        "--name-column",
        default=None,
        help="Optional column name with the case name (used to enrich the parsed citation)",
    )
    parser.add_argument(
        "--court-column",
        default=None,
        help="Optional column name with the court ID (e.g. 'scotus', 'ca2')",
    )
    parser.add_argument(
        "--year-column",
        default=None,
        help="Optional column name with the citation year (integer)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output CSV path",
    )
    parser.add_argument(
        "--quick-only",
        action="store_true",
        help="Skip opinion-search/RECAP fallback (citation-lookup only)",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Error: input file does not exist: {in_path}", file=sys.stderr)
        return 1

    with in_path.open(encoding="utf-8", newline="") as f:
        reader = csv_mod.DictReader(f)
        if args.column not in (reader.fieldnames or []):
            print(
                f"Error: column '{args.column}' not found in {in_path}. "
                f"Available columns: {reader.fieldnames}",
                file=sys.stderr,
            )
            return 1
        rows = list(reader)

    citations: list[str] = [(row.get(args.column) or "").strip() for row in rows]

    use_metadata = bool(args.name_column or args.court_column or args.year_column)
    parsed_citations: list[ParsedCitation | None] | None = None
    if use_metadata:
        parsed_citations = []
        for cite, row in zip(citations, rows):
            base = parse_citation(cite) if cite else ParsedCitation(raw_text=cite)
            if args.name_column:
                name_val = (row.get(args.name_column) or "").strip()
                if name_val:
                    base.case_name = name_val
            if args.court_column:
                court_val = (row.get(args.court_column) or "").strip()
                if court_val:
                    base.court = court_val
            if args.year_column:
                year_val = (row.get(args.year_column) or "").strip()
                if year_val:
                    try:
                        base.year = int(year_val)
                    except ValueError:
                        pass
            parsed_citations.append(base)

    verifier = CitationVerifier()

    def _progress(done: int, total: int) -> None:
        print(f"  Verifying {done}/{total}...", file=sys.stderr, flush=True)

    kwargs: dict = {
        "progress_callback": _progress,
        "quick_only": args.quick_only,
    }
    if parsed_citations is not None:
        kwargs["parsed_citations"] = parsed_citations

    results = asyncio.run(verifier.verify_batch(citations, **kwargs))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=_VERIFY_BATCH_OUTPUT_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(_result_to_row(result))

    print(f"Wrote {len(results)} rows to {out_path}", file=sys.stderr)
    return 0


_AUDIT_MISSES_ADDED_COLUMNS = [
    "fallback_status",
    "fallback_path",
    "fallback_confidence",
    "fallback_url",
    "fallback_matched_name",
    "fallback_court_id",
    "fallback_date_filed",
]


def _classify_fallback_path(
    quick_result: VerificationResult | None,
    full_result: VerificationResult | None,
) -> str:
    """Attribute which production path resolved (or didn't resolve) a citation.

    - ``citation-lookup`` if the quick (citation-lookup-only) pass already
      returned a hit (VERIFIED or LIKELY_REAL). The chunking fix matters
      here: a citation that missed in an old run can recover in a fresh
      one without needing search fallback.
    - ``RECAP`` if the full pipeline returned a hit AND any diagnostic on
      the result has category ``recap`` (the verifier annotates RECAP-
      sourced candidates with this category).
    - ``opinion-search`` if the full pipeline returned a hit with no
      ``recap`` diagnostic — implying the opinion-search step resolved it.
    - ``no_match`` if the full pipeline still returned NOT_FOUND.
    """
    if quick_result is not None and quick_result.status in (
        VerificationStatus.VERIFIED,
        VerificationStatus.LIKELY_REAL,
        VerificationStatus.POSSIBLE_MATCH,
    ):
        return "citation-lookup"
    if full_result is None or full_result.status == VerificationStatus.NOT_FOUND:
        return "no_match"
    has_recap = any(
        (d.category or "").lower() == "recap" for d in (full_result.diagnostics or [])
    )
    return "RECAP" if has_recap else "opinion-search"


def audit_misses_main(argv: list[str] | None = None) -> int:
    """CLI for auditing CL misses against the full production fallback path.

    Two-pass design:
      1. ``verify_batch(quick_only=True)`` — citation-lookup with chunking.
         Catches anything that recovers from the bare lookup endpoint
         (e.g. fixed by recent chunking changes). Path attributed as
         ``citation-lookup``.
      2. ``verify_batch()`` (full) on the quick-misses — runs opinion-
         search and, for federal courts, RECAP. Diagnostics tell us
         which step matched.
    """
    import csv as csv_mod
    from pathlib import Path

    from .models import ParsedCitation
    from .parser import parse_citation

    parser = argparse.ArgumentParser(
        prog="citation-verifier audit-misses",
        description="Audit CL misses against the full fallback pipeline.",
    )
    parser.add_argument("input", help="Input CSV with one citation per row")
    parser.add_argument(
        "--column",
        required=True,
        help="Column with the citation string",
    )
    parser.add_argument(
        "--name-column",
        default=None,
        help="Optional column with the case name (improves search recall)",
    )
    parser.add_argument(
        "--court-column",
        default=None,
        help="Optional column with the court ID (e.g. 'ca9', 'dcd')",
    )
    parser.add_argument(
        "--year-column",
        default=None,
        help="Optional column with the citation year",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output CSV path (input columns passed through, fallback_* added)",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Error: input file does not exist: {in_path}", file=sys.stderr)
        return 1

    with in_path.open(encoding="utf-8", newline="") as f:
        reader = csv_mod.DictReader(f)
        in_fieldnames = list(reader.fieldnames or [])
        if args.column not in in_fieldnames:
            print(
                f"Error: column '{args.column}' not found. Available: {in_fieldnames}",
                file=sys.stderr,
            )
            return 1
        rows = list(reader)

    citations: list[str] = [(row.get(args.column) or "").strip() for row in rows]

    use_metadata = bool(args.name_column or args.court_column or args.year_column)
    parsed_citations: list[ParsedCitation | None] | None = None
    if use_metadata:
        parsed_citations = []
        for cite, row in zip(citations, rows):
            base = parse_citation(cite) if cite else ParsedCitation(raw_text=cite)
            if args.name_column:
                v = (row.get(args.name_column) or "").strip()
                if v:
                    base.case_name = v
            if args.court_column:
                v = (row.get(args.court_column) or "").strip()
                if v:
                    base.court = v
            if args.year_column:
                v = (row.get(args.year_column) or "").strip()
                if v:
                    try:
                        base.year = int(v)
                    except ValueError:
                        pass
            parsed_citations.append(base)

    verifier = CitationVerifier()

    def _progress(label: str):
        def _cb(done: int, total: int) -> None:
            print(f"  [{label}] {done}/{total}...", file=sys.stderr, flush=True)
        return _cb

    # Pass 1: quick (citation-lookup with chunking only)
    quick_kwargs: dict = {
        "progress_callback": _progress("quick"),
        "quick_only": True,
    }
    if parsed_citations is not None:
        quick_kwargs["parsed_citations"] = parsed_citations
    quick_results = asyncio.run(verifier.verify_batch(citations, **quick_kwargs))

    # Identify the indices that need the full pipeline.
    miss_indices: list[int] = [
        i for i, r in enumerate(quick_results)
        if r.status == VerificationStatus.NOT_FOUND
    ]

    full_results: dict[int, VerificationResult] = {}
    if miss_indices:
        miss_citations = [citations[i] for i in miss_indices]
        miss_parsed = (
            [parsed_citations[i] for i in miss_indices]
            if parsed_citations is not None else None
        )
        full_kwargs: dict = {"progress_callback": _progress("full")}
        if miss_parsed is not None:
            full_kwargs["parsed_citations"] = miss_parsed
        full_list = asyncio.run(verifier.verify_batch(miss_citations, **full_kwargs))
        for idx, res in zip(miss_indices, full_list):
            full_results[idx] = res

    # Build output rows: passthrough + fallback_* columns
    out_fieldnames = list(in_fieldnames) + [
        c for c in _AUDIT_MISSES_ADDED_COLUMNS if c not in in_fieldnames
    ]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=out_fieldnames)
        writer.writeheader()
        for idx, row in enumerate(rows):
            quick = quick_results[idx]
            full = full_results.get(idx)
            chosen = full if full is not None else quick
            path = _classify_fallback_path(quick, full)
            out_row = dict(row)
            out_row["fallback_status"] = chosen.status.value
            out_row["fallback_path"] = path
            out_row["fallback_confidence"] = f"{chosen.confidence}"
            out_row["fallback_url"] = chosen.matched_url or ""
            out_row["fallback_matched_name"] = chosen.matched_case_name or ""
            out_row["fallback_court_id"] = chosen.matched_court or ""
            out_row["fallback_date_filed"] = chosen.matched_date or ""
            writer.writerow(out_row)

    # Per-path summary to stderr
    counts: dict[str, int] = {}
    for idx in range(len(rows)):
        path = _classify_fallback_path(
            quick_results[idx], full_results.get(idx)
        )
        counts[path] = counts.get(path, 0) + 1
    print(
        f"Audit complete: {sum(counts.values())} rows. "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    # Dispatch subcommands if first arg matches
    if len(sys.argv) > 1 and sys.argv[1] == "verify-brief":
        sys.exit(verify_brief_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "verify-batch":
        sys.exit(verify_batch_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "audit-misses":
        sys.exit(audit_misses_main(sys.argv[2:]))
    sys.exit(main())
