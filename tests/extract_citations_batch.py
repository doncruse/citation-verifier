"""Non-interactive batch extraction of citations from hallucination opinions.

Extracts all citations and classifies them by confidence level for manual review.

Usage:
    python tests/extract_citations_batch.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber
from eyecite import get_citations
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
            'court': getattr(citation.metadata, 'court', None),
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


def main() -> None:
    """Main entry point."""
    opinions_dir = Path(__file__).parent / "data" / "hallucination_opinions"
    output_dir = Path(__file__).parent / "data"

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

    # Save raw results for review
    raw_output = output_dir / "citations_extracted_raw.json"
    with open(raw_output, 'w') as f:
        json.dump(all_results, f, indent=2)

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
    print(f"\nRaw results saved to: {raw_output}")
    print("\nNext step: Review citations_extracted_raw.json and classify manually")


if __name__ == "__main__":
    main()
