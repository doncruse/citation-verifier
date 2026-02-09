"""CLI interface for citation verification."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .models import VerificationResult, VerificationStatus
from .verifier import CitationVerifier

# Status → display style
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
    args = parser.parse_args(argv)

    citations: list[str] = list(args.citations)
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    citations.append(line)

    if not citations:
        parser.error("No citations provided. Pass them as arguments or use --file.")

    verifier = CitationVerifier()
    any_not_found = False

    for cite_text in citations:
        result = verifier.verify(cite_text)
        _print_result(result, args.json_mode)
        if result.status == VerificationStatus.NOT_FOUND:
            any_not_found = True

    return 1 if any_not_found else 0


if __name__ == "__main__":
    sys.exit(main())
