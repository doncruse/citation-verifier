"""Extract and classify citations from judicial opinions about AI hallucinations.

This script processes PDF opinions that discuss fabricated citations, using eyecite
to extract all citations and pattern matching to classify them as likely fake or real.

Requirements:
    pip install pdfplumber eyecite

Usage:
    python tests/extract_hallucination_citations.py
"""

import json
import re
from pathlib import Path
from typing import Any

import pdfplumber
from eyecite import get_citations
from eyecite.models import FullCaseCitation


# Patterns that suggest a citation is fabricated
HALLUCINATION_KEYWORDS = [
    "nonexistent",
    "does not exist",
    "no such case",
    "fabricated",
    "false citation",
    "misleading citation",
    "AI-generated",
    "hallucination",
    "does not appear to be",
    "leads to an unrelated",
    "not authored by",
]

# Section headers that indicate discussion of fake citations
HALLUCINATION_HEADERS = [
    "false or misleading case citation",
    "fabricated citation",
    "nonexistent case",
    "ai hallucination",
]


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file using pdfplumber."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text_parts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n\n".join(text_parts)
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return ""


def get_citation_context(citation_text: str, full_text: str, context_chars: int = 200) -> str:
    """Extract surrounding text for a citation."""
    idx = full_text.find(citation_text)
    if idx == -1:
        return ""

    start = max(0, idx - context_chars)
    end = min(len(full_text), idx + len(citation_text) + context_chars)

    context = full_text[start:end]

    # Clean up context
    context = re.sub(r'\s+', ' ', context)  # Normalize whitespace

    # Add ellipsis if truncated
    if start > 0:
        context = "..." + context
    if end < len(full_text):
        context = context + "..."

    return context.strip()


def has_hallucination_keywords(context: str) -> tuple[bool, str | None]:
    """Check if context contains hallucination keywords.

    Returns:
        (found, keyword) tuple
    """
    context_lower = context.lower()
    for keyword in HALLUCINATION_KEYWORDS:
        if keyword in context_lower:
            return True, keyword
    return False, None


def in_hallucination_section(citation_text: str, full_text: str) -> bool:
    """Check if citation appears in a section about hallucinations."""
    # Find the citation's position
    idx = full_text.find(citation_text)
    if idx == -1:
        return False

    # Look backwards for the most recent section header (within 5000 chars)
    text_before = full_text[max(0, idx - 5000):idx].lower()

    for header in HALLUCINATION_HEADERS:
        if header in text_before:
            return True

    return False


def classify_citation(
    citation: FullCaseCitation,
    citation_text: str,
    full_text: str
) -> dict[str, Any]:
    """Classify a citation as likely fake, likely real, or uncertain.

    Returns:
        Dict with 'classification' and 'confidence' and 'reason'
    """
    context = get_citation_context(citation_text, full_text)

    # Check for hallucination keywords in context
    has_keywords, keyword = has_hallucination_keywords(context)
    in_hallucination_sec = in_hallucination_section(citation_text, full_text)

    if has_keywords or in_hallucination_sec:
        return {
            'classification': 'likely_fake',
            'confidence': 'high' if has_keywords else 'medium',
            'reason': f"Keyword '{keyword}'" if has_keywords else "In hallucination section",
            'context': context
        }

    # Heuristic: citations in parentheticals following "see" are usually real
    if re.search(r'\bsee\b.*?' + re.escape(citation_text), context, re.IGNORECASE):
        return {
            'classification': 'likely_real',
            'confidence': 'medium',
            'reason': 'Used in standard legal citation format',
            'context': context
        }

    # Default: uncertain
    return {
        'classification': 'uncertain',
        'confidence': 'low',
        'reason': 'No clear indicators',
        'context': context
    }


def format_citation_for_display(citation: FullCaseCitation) -> str:
    """Format a citation for display."""
    return str(citation)


def review_citations_interactive(
    citations_data: list[dict[str, Any]],
    pdf_name: str
) -> dict[str, list[dict[str, Any]]]:
    """Interactive review of classified citations.

    Returns:
        Dict with 'fake' and 'real' lists
    """
    results: dict[str, list[dict[str, Any]]] = {
        'fake': [],
        'real': []
    }

    print(f"\n{'='*80}")
    print(f"Reviewing citations from: {pdf_name}")
    print(f"{'='*80}\n")

    # Group by classification
    likely_fake = [c for c in citations_data if c['classification'] == 'likely_fake']
    likely_real = [c for c in citations_data if c['classification'] == 'likely_real']
    uncertain = [c for c in citations_data if c['classification'] == 'uncertain']

    print(f"Found {len(citations_data)} total citations:")
    print(f"  - {len(likely_fake)} likely fake")
    print(f"  - {len(likely_real)} likely real")
    print(f"  - {len(uncertain)} uncertain")
    print()

    # Review likely fake citations
    if likely_fake:
        print(f"\n--- LIKELY FAKE CITATIONS ({len(likely_fake)}) ---\n")
        for i, cit_data in enumerate(likely_fake, 1):
            print(f"[{i}] {cit_data['citation_text']}")
            print(f"    Reason: {cit_data['reason']}")
            print(f"    Context: {cit_data['context'][:200]}...")
            print()

            response = input("    Is this FAKE? [y/n/s=skip]: ").strip().lower()
            if response == 'y':
                results['fake'].append({
                    'citation': cit_data['citation_text'],
                    'category': 'hallucinated_case_name',
                    'source_opinion': pdf_name,
                    'notes': f"Court identified as fake. {cit_data['reason']}",
                    'expected_status': 'NOT_FOUND'
                })
            elif response == 'n':
                results['real'].append({
                    'citation': cit_data['citation_text'],
                    'category': 'standard_reporter',
                    'source_opinion': pdf_name,
                    'notes': f"From hallucination opinion but actually real",
                    'expected_cluster_id': None
                })
            # Skip if 's' or anything else

    # Review uncertain citations (show a few)
    if uncertain:
        print(f"\n--- UNCERTAIN CITATIONS (showing first 5 of {len(uncertain)}) ---\n")
        for i, cit_data in enumerate(uncertain[:5], 1):
            print(f"[{i}] {cit_data['citation_text']}")
            print(f"    Context: {cit_data['context'][:200]}...")
            print()

            response = input("    Classify: [f=fake/r=real/s=skip]: ").strip().lower()
            if response == 'f':
                results['fake'].append({
                    'citation': cit_data['citation_text'],
                    'category': 'hallucinated_case_name',
                    'source_opinion': pdf_name,
                    'notes': 'Manually identified as fake',
                    'expected_status': 'NOT_FOUND'
                })
            elif response == 'r':
                results['real'].append({
                    'citation': cit_data['citation_text'],
                    'category': 'standard_reporter',
                    'source_opinion': pdf_name,
                    'notes': 'From hallucination opinion, used by court',
                    'expected_cluster_id': None
                })

    return results


def process_opinion(pdf_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Process a single opinion PDF and extract classified citations."""
    print(f"\nProcessing: {pdf_path.name}")

    # Extract text from PDF
    # TODO: Implement actual PDF extraction using Read tool or pdfplumber
    full_text = extract_text_from_pdf(pdf_path)

    if not full_text:
        print(f"  Warning: Could not extract text from {pdf_path.name}")
        return {'fake': [], 'real': []}

    # Extract all citations with eyecite
    citations = get_citations(full_text)
    full_citations = [c for c in citations if isinstance(c, FullCaseCitation)]

    print(f"  Found {len(full_citations)} full citations")

    # Classify each citation
    citations_data = []
    for citation in full_citations:
        citation_text = str(citation)
        classification = classify_citation(citation, citation_text, full_text)

        citations_data.append({
            'citation': citation,
            'citation_text': citation_text,
            **classification
        })

    # Interactive review
    results = review_citations_interactive(citations_data, pdf_path.name)

    return results


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
    all_fake: list[dict[str, Any]] = []
    all_real: list[dict[str, Any]] = []

    for pdf_path in pdf_files:
        results = process_opinion(pdf_path)
        all_fake.extend(results['fake'])
        all_real.extend(results['real'])

    # Save results
    fake_output = output_dir / "known_fake_citations.json"
    real_output = output_dir / "known_real_citations.json"

    # Load existing real citations if file exists
    existing_real = []
    if real_output.exists():
        with open(real_output) as f:
            existing_real = json.load(f)

    # Merge and deduplicate real citations
    all_real = existing_real + all_real

    # Save fake citations
    with open(fake_output, 'w') as f:
        json.dump(all_fake, f, indent=2)
    print(f"\nSaved {len(all_fake)} fake citations to {fake_output}")

    # Save real citations
    with open(real_output, 'w') as f:
        json.dump(all_real, f, indent=2)
    print(f"Saved {len(all_real)} real citations to {real_output}")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Processed {len(pdf_files)} opinions")
    print(f"Extracted {len(all_fake)} fake citations")
    print(f"Extracted {len(all_real)} real citations (including existing)")
    print()


if __name__ == "__main__":
    main()
