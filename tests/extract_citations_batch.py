"""Non-interactive batch extraction of citations from hallucination opinions.

Extracts all citations and classifies them by confidence level for manual review.
Includes automated QC checks and diff against previous runs.

Usage:
    python tests/extract_citations_batch.py
    python tests/extract_citations_batch.py --output custom_output.json
    python tests/extract_citations_batch.py --diff tests/data/citations_extracted_raw.json
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
from eyecite import clean_text, get_citations
from eyecite.models import FullCaseCitation

# Add parent directory to path to import from citation_verifier
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from citation_verifier.text_cleaner import clean_case_name

from extract_hallucination_citations import (
    HALLUCINATION_KEYWORDS,
    classify_citation,
    get_citation_context,
    has_hallucination_keywords,
    in_hallucination_section,
)


def _get_git_hash() -> str | None:
    """Get the current git short hash, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _strip_line_numbers(page_text: str) -> str:
    """Strip court document line numbers from extracted PDF text.

    Court documents have numbered lines (1-28+) in the left margin.
    pdfplumber extracts these inline, causing citation parsing errors
    (e.g., "153\\n14 Cal.App.3d" where 14 is a line number, not volume).

    Detection: if >=60% of lines start with a 1-2 digit number followed
    by a space, and numbers are roughly sequential, strip them.
    """
    lines = page_text.split("\n")
    if len(lines) < 5:
        return page_text

    # Count lines that start with a 1-2 digit number + space
    numbered_lines = []
    for i, line in enumerate(lines):
        match = re.match(r"^(\d{1,2})\s", line)
        if match:
            numbered_lines.append((i, int(match.group(1))))

    # Need at least 60% of lines to be numbered
    if len(numbered_lines) < len(lines) * 0.6:
        return page_text

    # Check for roughly sequential pattern (allow gaps for headers/footers)
    nums = [n for _, n in numbered_lines]
    if len(nums) >= 3:
        diffs = [nums[i + 1] - nums[i] for i in range(len(nums) - 1)]
        # Most consecutive differences should be 1 (sequential)
        sequential_count = sum(1 for d in diffs if d == 1)
        if sequential_count < len(diffs) * 0.5:
            return page_text

    # Strip leading line numbers and rejoin into flowing text.
    # Joining with spaces (not newlines) is critical: citations like
    # "153\n14 Cal.App.3d 467" become "153 Cal.App.3d 467" after stripping,
    # which eyecite can parse correctly.
    stripped = []
    for line in lines:
        stripped.append(re.sub(r"^(\d{1,2})\s", "", line))
    return " ".join(stripped)


# PACER/ECF header patterns:
#   "Case 1:25-cv-03398 Document #: 72 Filed: 01/16/26 Page 6 of 9 PageID #:653"
#   "FLSD Docket 02/04/2026 Page 5 of 12"
_PACER_HEADER_RE = re.compile(
    r'(?:'
    r'Case:?\s+[\d:]+[-\w]+\s+Document\s+[#\d:]+\s*\d*\s+Filed:?\s+\d+/\d+/\d+\s+'
    r'Page\s+\d+\s+of\s+\d+(?:\s+Page\s*ID\s*#?:?\s*\d+)?'
    r'|'
    r'[A-Z]{2,5}\s+Docket\s+\d+/\d+/\d+\s+Page\s+\d+\s+of\s+\d+'
    r')'
)

# Court seal garble: short lines of single spaced characters from circular watermarks.
# Matches lines like "t r i n", "Cf", "si", "cC", "Uo" — artifacts from
# "United States District Court" etc. rendered in a circle.
_GARBLE_LINE_RE = re.compile(r'^[a-zA-Z](?:\s[a-zA-Z]){0,8}$')


def _clean_pdf_text(text: str) -> str:
    """Clean PDF-extracted text before passing to eyecite.

    Applies targeted fixes for common PDF extraction artifacts while
    preserving paragraph boundaries (double newlines) that eyecite uses.
    """
    # 1. Normalize smart quotes and typographic characters
    text = text.replace('\u2019', "'")   # right single quote → apostrophe
    text = text.replace('\u2018', "'")   # left single quote → apostrophe
    text = text.replace('\u201c', '"')   # left double quote
    text = text.replace('\u201d', '"')   # right double quote
    text = text.replace('\u200b', '')    # zero-width space

    # 2. Strip PACER/ECF headers that span page breaks
    text = _PACER_HEADER_RE.sub(' ', text)

    # 3. Strip court seal garble lines (single-character-per-word short lines)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 20 and _GARBLE_LINE_RE.match(stripped):
            continue  # drop garble line
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)

    # 4. Normalize single newlines to spaces (PDF line breaks within a paragraph),
    #    but preserve double newlines (real paragraph boundaries).
    #    This is belt-and-suspenders with the forked eyecite's ParagraphToken fix.
    text = re.sub(r'\n(?!\n)', ' ', text)

    # 5. Use eyecite's built-in cleaners for underscores and inline whitespace
    text = clean_text(text, ['underscores', 'inline_whitespace'])

    return text


def _infer_westlaw_year(citation: FullCaseCitation) -> str | None:
    """For WestLaw citations (e.g., '2025 WL 1234567'), the year is the volume."""
    reporter = citation.groups.get('reporter', '')
    volume = citation.groups.get('volume', '')
    if reporter == 'WL' and volume and re.match(r'^\d{4}$', volume):
        return volume
    return None


def process_opinion_batch(pdf_path: Path) -> dict[str, Any]:
    """Process a single opinion PDF and return all classified citations."""
    print(f"\nProcessing: {pdf_path.name}")

    # Extract text from PDF
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text_parts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(_strip_line_numbers(text))
            full_text = "\n\n".join(text_parts)
    except Exception as e:
        print(f"  Error extracting text: {e}")
        return {
            'pdf_name': pdf_path.name,
            'error': str(e),
            'likely_fake': [],
            'likely_real': [],
            'uncertain': []
        }

    # Clean text before eyecite processes it
    full_text = _clean_pdf_text(full_text)

    # Extract all citations with eyecite
    citations = get_citations(full_text)
    full_citations = [c for c in citations if isinstance(c, FullCaseCitation)]

    print(f"  Found {len(full_citations)} full citations")

    # Classify each citation
    likely_fake = []
    likely_real = []
    uncertain = []

    for citation in full_citations:
        # Build reporter text for context searching
        volume = citation.groups.get('volume', '')
        reporter = citation.groups.get('reporter', '')
        page = citation.groups.get('page', '')
        reporter_text = f"{volume} {reporter} {page}".strip()

        # Classify using reporter text for context lookup
        classification = classify_citation(citation, reporter_text, full_text)

        # Build clean citation string from metadata
        plaintiff = getattr(citation.metadata, 'plaintiff', None) or ''
        defendant = getattr(citation.metadata, 'defendant', None) or ''

        # Handle "In re" cases (plaintiff is None, defendant exists)
        if not plaintiff and defendant:
            case_name = f"In re {defendant}"
        elif plaintiff and defendant:
            case_name = f"{plaintiff} v. {defendant}"
        else:
            case_name = ''

        # Clean contamination from case name
        case_name = clean_case_name(case_name) if case_name else ''

        # Build full citation string
        if case_name and reporter_text:
            clean_citation = f"{case_name}, {reporter_text}"
        elif reporter_text:
            clean_citation = reporter_text
        else:
            clean_citation = str(citation)  # Fallback to repr if all else fails

        year = getattr(citation.metadata, 'year', None)
        if not year:
            year = _infer_westlaw_year(citation)
        court = getattr(citation.metadata, 'court', None)

        if year and reporter_text:
            clean_citation += f" ({year})"

        citation_data = {
            'citation': clean_citation,
            'reporter_text': reporter_text,  # Store for later reference
            'case_name': case_name,
            'volume': volume,
            'reporter': reporter,
            'page': page,
            'year': year,
            'court': court,
            'plaintiff': plaintiff,
            'defendant': defendant,
            'classification': classification['classification'],
            'confidence': classification['confidence'],
            'reason': classification['reason'],
            'context': classification['context'][:300]  # Limit context length
        }

        if classification['classification'] == 'likely_fake':
            likely_fake.append(citation_data)
        elif classification['classification'] == 'likely_real':
            likely_real.append(citation_data)
        else:
            uncertain.append(citation_data)

    print(f"  Classified: {len(likely_fake)} likely fake, {len(likely_real)} likely real, {len(uncertain)} uncertain")

    return {
        'pdf_name': pdf_path.name,
        'likely_fake': likely_fake,
        'likely_real': likely_real,
        'uncertain': uncertain
    }


def _all_citations(results: list[dict]) -> list[dict]:
    """Flatten all citations from all opinions/classifications into a single list."""
    citations = []
    for r in results:
        for category in ('likely_fake', 'likely_real', 'uncertain'):
            for cite in r.get(category, []):
                cite_with_source = dict(cite)
                cite_with_source['source_pdf'] = r.get('pdf_name', 'unknown')
                citations.append(cite_with_source)
    return citations


def run_qc_checks(results: list[dict]) -> None:
    """Run automated quality checks on extracted citations and print a report."""
    all_cites = _all_citations(results)
    if not all_cites:
        print("No citations to QC.")
        return

    print(f"\n{'='*80}")
    print("EXTRACTION QC REPORT")
    print(f"{'='*80}")
    print(f"Total citations: {len(all_cites)}")

    issues_found = False

    # 1. Missing court but context has court parenthetical
    court_pattern = re.compile(r'\([A-Z][A-Za-z.]+\s+(?:Cir\.|Dist\.|App\.|Ct\.).*?\d{4}\)')
    missing_court = []
    for cite in all_cites:
        if cite.get('court') is None:
            context = cite.get('context', '')
            if court_pattern.search(context):
                missing_court.append(cite)
    if missing_court:
        issues_found = True
        print(f"\n[!] Missing court ({len(missing_court)} citations) - context has court parenthetical:")
        for cite in missing_court[:3]:
            print(f"    - {cite.get('citation', '')[:80]}")
            match = court_pattern.search(cite.get('context', ''))
            if match:
                print(f"      Context has: {match.group()}")

    # 2. Missing year but context has year in parentheses
    year_pattern = re.compile(r'\((?:[^)]*\s)?(\d{4})\)')
    missing_year = []
    for cite in all_cites:
        if cite.get('year') is None:
            context = cite.get('context', '')
            if year_pattern.search(context):
                missing_year.append(cite)
    if missing_year:
        issues_found = True
        print(f"\n[!] Missing year ({len(missing_year)} citations) - context has year:")
        for cite in missing_year[:3]:
            print(f"    - {cite.get('citation', '')[:80]}")
            match = year_pattern.search(cite.get('context', ''))
            if match:
                print(f"      Context has year: {match.group(1)}")

    # 3. Case name vs context mismatch (context has "X v. Y" but extracted differently)
    vs_pattern = re.compile(r'([A-Z][^\n,;]+?)\s+v\.\s+([^,\n;]+?),\s')
    name_mismatches = []
    for cite in all_cites:
        case_name = cite.get('case_name', '')
        context = cite.get('context', '')
        reporter_text = cite.get('reporter_text', '')
        if not case_name or not context or not reporter_text:
            continue
        # Find the case name that precedes this reporter text in context
        # Look for "X v. Y, <reporter_text>" pattern
        escaped_reporter = re.escape(reporter_text)
        ctx_match = re.search(
            r'([A-Z][^\n,;]+?)\s+v\.\s+([^,\n;]+?),\s*' + escaped_reporter,
            context
        )
        if ctx_match:
            ctx_name = f"{ctx_match.group(1).strip()} v. {ctx_match.group(2).strip()}"
            # Normalize for comparison
            norm_extracted = re.sub(r'\s+', ' ', case_name.lower().strip())
            norm_context = re.sub(r'\s+', ' ', ctx_name.lower().strip())
            # Flag if they differ meaningfully (not just whitespace/case)
            if norm_extracted != norm_context:
                # Check if one is a substring of the other (abbreviation differences are OK)
                if norm_extracted not in norm_context and norm_context not in norm_extracted:
                    name_mismatches.append({
                        'extracted': case_name,
                        'in_context': ctx_name,
                        'reporter_text': reporter_text,
                    })
    if name_mismatches:
        issues_found = True
        print(f"\n[!] Case name mismatch ({len(name_mismatches)} citations) - extracted name differs from context:")
        for m in name_mismatches[:3]:
            print(f"    - Extracted:  {m['extracted']}")
            print(f"      In context: {m['in_context']}")

    # 4. Duplicate reporter texts
    reporter_counts = Counter(cite.get('reporter_text', '') for cite in all_cites if cite.get('reporter_text'))
    duplicates = [(rt, count) for rt, count in reporter_counts.items() if count > 1]
    # Filter to duplicates with different case names (same citation appearing in multiple opinions is expected)
    real_dupes = []
    for rt, count in duplicates:
        names = set()
        for cite in all_cites:
            if cite.get('reporter_text') == rt:
                names.add(cite.get('case_name', ''))
        if len(names) > 1:
            real_dupes.append((rt, count, names))
    if real_dupes:
        issues_found = True
        print(f"\n[!] Duplicate reporter texts with different names ({len(real_dupes)}):")
        for rt, count, names in real_dupes[:3]:
            print(f"    - {rt} ({count}x): {', '.join(n[:50] for n in names)}")

    # 5. Missing plaintiff
    missing_plaintiff = []
    for cite in all_cites:
        plaintiff = cite.get('plaintiff', '')
        context = cite.get('context', '')
        if not plaintiff and ' v. ' in context:
            missing_plaintiff.append(cite)
    if missing_plaintiff:
        issues_found = True
        print(f"\n[!] Missing plaintiff ({len(missing_plaintiff)} citations) - context has 'v.':")
        for cite in missing_plaintiff[:3]:
            print(f"    - {cite.get('citation', '')[:80]}")

    # 6. Known fake cross-reference
    known_fakes_path = Path(__file__).parent / "data" / "known_fake_citations.json"
    if known_fakes_path.exists():
        with open(known_fakes_path) as f:
            known_fakes = json.load(f)

        extracted_reporters = {cite.get('reporter_text', '') for cite in all_cites}
        found_fakes = []
        missing_fakes = []
        for fake in known_fakes:
            # Extract reporter text from the known fake citation
            fake_citation = fake.get('citation', '')
            # Try to find a matching reporter text in our extracted data
            matched = False
            for cite in all_cites:
                if cite.get('reporter_text') and cite['reporter_text'] in fake_citation:
                    found_fakes.append((fake_citation, cite.get('citation', '')))
                    matched = True
                    break
            if not matched:
                missing_fakes.append(fake_citation)

        if found_fakes:
            print(f"\n[OK] Known fakes found in extraction ({len(found_fakes)}/{len(known_fakes)}):")
            for fake_cite, extracted_cite in found_fakes[:3]:
                print(f"    - {fake_cite[:80]}")
        if missing_fakes:
            issues_found = True
            print(f"\n[!] Known fakes NOT found in extraction ({len(missing_fakes)}):")
            for fake_cite in missing_fakes[:3]:
                print(f"    - {fake_cite[:80]}")

    if not issues_found:
        print("\n[OK] No QC issues detected.")

    print()


def run_diff(new_results: list[dict], old_path: Path) -> None:
    """Compare new extraction against a previous run and print changes."""
    with open(old_path) as f:
        old_results = json.load(f)

    # Handle metadata wrapper in old file
    if isinstance(old_results, dict) and '_metadata' in old_results:
        old_results = old_results.get('results', old_results.get('data', []))

    new_cites = _all_citations(new_results)
    old_cites = _all_citations(old_results)

    # Index by reporter_text for comparison
    new_by_reporter = {}
    for cite in new_cites:
        rt = cite.get('reporter_text', '')
        if rt:
            new_by_reporter.setdefault(rt, []).append(cite)
    old_by_reporter = {}
    for cite in old_cites:
        rt = cite.get('reporter_text', '')
        if rt:
            old_by_reporter.setdefault(rt, []).append(cite)

    new_reporters = set(new_by_reporter.keys())
    old_reporters = set(old_by_reporter.keys())

    gained = new_reporters - old_reporters
    lost = old_reporters - new_reporters
    common = new_reporters & old_reporters

    print(f"\n{'='*80}")
    print(f"DIFF vs {old_path.name}")
    print(f"{'='*80}")
    print(f"Previous: {len(old_cites)} citations ({len(old_reporters)} unique reporters)")
    print(f"Current:  {len(new_cites)} citations ({len(new_reporters)} unique reporters)")

    if gained:
        print(f"\n[+] Gained {len(gained)} citations:")
        for rt in sorted(gained)[:5]:
            cite = new_by_reporter[rt][0]
            print(f"    + {cite.get('case_name', '')} -- {rt}")
        if len(gained) > 5:
            print(f"    ... and {len(gained) - 5} more")

    if lost:
        print(f"\n[-] Lost {len(lost)} citations:")
        for rt in sorted(lost)[:5]:
            cite = old_by_reporter[rt][0]
            print(f"    - {cite.get('case_name', '')} -- {rt}")
        if len(lost) > 5:
            print(f"    ... and {len(lost) - 5} more")

    # Check for field changes in common citations
    court_gained = []
    court_lost = []
    year_gained = []
    year_lost = []
    name_changed = []

    for rt in common:
        new_cite = new_by_reporter[rt][0]
        old_cite = old_by_reporter[rt][0]

        # Court changes
        if new_cite.get('court') and not old_cite.get('court'):
            court_gained.append((rt, new_cite['court']))
        elif old_cite.get('court') and not new_cite.get('court'):
            court_lost.append((rt, old_cite['court']))

        # Year changes
        if new_cite.get('year') and not old_cite.get('year'):
            year_gained.append((rt, new_cite['year']))
        elif old_cite.get('year') and not new_cite.get('year'):
            year_lost.append((rt, old_cite['year']))

        # Name changes
        new_name = new_cite.get('case_name', '')
        old_name = old_cite.get('case_name', '')
        if new_name != old_name and (new_name or old_name):
            name_changed.append((rt, old_name, new_name))

    if court_gained:
        print(f"\n[+] Court newly captured ({len(court_gained)}):")
        for rt, court in court_gained[:3]:
            print(f"    {rt}: court={court}")

    if court_lost:
        print(f"\n[-] Court lost ({len(court_lost)}):")
        for rt, court in court_lost[:3]:
            print(f"    {rt}: was court={court}")

    if year_gained:
        print(f"\n[+] Year newly captured ({len(year_gained)}):")
        for rt, year in year_gained[:3]:
            print(f"    {rt}: year={year}")

    if year_lost:
        print(f"\n[-] Year lost ({len(year_lost)}):")
        for rt, year in year_lost[:3]:
            print(f"    {rt}: was year={year}")

    if name_changed:
        print(f"\n[~] Case name changed ({len(name_changed)}):")
        for rt, old_name, new_name in name_changed[:5]:
            print(f"    {rt}:")
            print(f"      old: {old_name[:60]}")
            print(f"      new: {new_name[:60]}")

    if not (gained or lost or court_gained or court_lost or year_gained or year_lost or name_changed):
        print("\nNo differences found.")

    print()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Extract and QC citations from hallucination opinion PDFs')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path (default: timestamped file in tests/data/)')
    parser.add_argument('--diff', type=str, default=None,
                        help='Compare against a previous extraction file')
    args = parser.parse_args()

    opinions_dir = Path(__file__).parent / "data" / "hallucination_opinions"
    output_dir = Path(__file__).parent / "data"

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d")
        output_path = output_dir / f"citations_extracted_{timestamp}.json"

    # Find all PDF files
    pdf_files = sorted(opinions_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {opinions_dir}")
        return

    print(f"Found {len(pdf_files)} opinion PDFs to process")

    # Process each opinion
    all_results = []

    for pdf_path in pdf_files:
        results = process_opinion_batch(pdf_path)
        all_results.append(results)

    # Build metadata
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_hash": _get_git_hash(),
        "script": "extract_citations_batch.py",
        "source_dir": str(opinions_dir),
        "pdf_count": len(pdf_files),
    }

    # Save results with metadata
    output_data = {
        "_metadata": metadata,
        "results": all_results,
    }
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    # Generate summary statistics
    total_fake = sum(len(r.get('likely_fake', [])) for r in all_results)
    total_real = sum(len(r.get('likely_real', [])) for r in all_results)
    total_uncertain = sum(len(r.get('uncertain', [])) for r in all_results)
    total_citations = total_fake + total_real + total_uncertain

    print(f"\n{'='*80}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*80}")
    print(f"Processed {len(pdf_files)} opinions")
    print(f"Extracted {total_citations} total citations:")
    print(f"  - {total_fake} likely fake (high/medium confidence)")
    print(f"  - {total_real} likely real (medium confidence)")
    print(f"  - {total_uncertain} uncertain (need manual review)")
    print(f"\nResults saved to: {output_path}")
    print(f"Git hash: {metadata['git_hash'] or 'unknown'}")

    # Run QC checks
    run_qc_checks(all_results)

    # Run diff if requested
    if args.diff:
        diff_path = Path(args.diff)
        if diff_path.exists():
            run_diff(all_results, diff_path)
        else:
            print(f"Diff file not found: {diff_path}")


if __name__ == "__main__":
    main()
