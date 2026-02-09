"""Non-interactive batch extraction of citations from hallucination opinions.

Extracts all citations and classifies them by confidence level for manual review.

Usage:
    python tests/extract_citations_batch.py
"""

import json
from pathlib import Path
from typing import Any

import pdfplumber
from eyecite import get_citations
from eyecite.models import FullCaseCitation

from extract_hallucination_citations import (
    HALLUCINATION_KEYWORDS,
    classify_citation,
    get_citation_context,
    has_hallucination_keywords,
    in_hallucination_section,
)


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
                    text_parts.append(text)
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
        citation_text = str(citation)
        classification = classify_citation(citation, citation_text, full_text)

        citation_data = {
            'citation': citation_text,
            'case_name': f"{getattr(citation.metadata, 'plaintiff', '')} v. {getattr(citation.metadata, 'defendant', '')}".strip(),
            'volume': citation.groups.get('volume', ''),
            'reporter': citation.groups.get('reporter', ''),
            'page': citation.groups.get('page', ''),
            'year': getattr(citation.metadata, 'year', None),
            'court': getattr(citation.metadata, 'court', None),
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
