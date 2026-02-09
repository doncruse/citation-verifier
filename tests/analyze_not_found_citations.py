"""Analyze NOT_FOUND citations with context from source PDFs.

Extracts detailed context to identify patterns for improving classification.
"""

import json
from pathlib import Path

import pdfplumber


def find_citation_context(pdf_path: Path, citation_text: str, context_chars: int = 500) -> str:
    """Find and extract context around a citation in a PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n\n".join(
                page.extract_text() for page in pdf.pages if page.extract_text()
            )

            # Try to find the citation or key parts of it
            # Extract key identifiers from citation
            if " WL " in citation_text:
                # WestLaw citation - search for the WL number
                wl_num = citation_text.split(" WL ")[1].split()[0].replace(',', '')
                search_term = f"WL {wl_num}"
            elif ", " in citation_text and " F." in citation_text:
                # Federal reporter - search for volume + reporter
                parts = citation_text.split(",")[0]
                search_term = parts.strip()
            else:
                # Use the full citation
                search_term = citation_text[:50]

            idx = full_text.find(search_term)
            if idx == -1:
                return "Citation text not found in PDF"

            start = max(0, idx - context_chars)
            end = min(len(full_text), idx + len(search_term) + context_chars)

            context = full_text[start:end]

            # Add ellipsis if truncated
            if start > 0:
                context = "..." + context
            if end < len(full_text):
                context = context + "..."

            return context.replace('\n', ' ').strip()

    except Exception as e:
        return f"Error extracting context: {e}"


def main() -> None:
    """Main entry point."""
    data_dir = Path(__file__).parent / "data"
    opinions_dir = data_dir / "hallucination_opinions"

    # Load verification results
    results_file = data_dir / "verification_sample_50.json"
    with open(results_file) as f:
        results = json.load(f)

    not_found = results.get('NOT_FOUND', [])

    print(f"{'='*80}")
    print(f"ANALYZING {len(not_found)} NOT_FOUND CITATIONS")
    print(f"{'='*80}\n")

    for i, item in enumerate(not_found, 1):
        citation = item['citation']
        source_pdf = item['source_pdf']
        diagnostic = item['diagnostics'][0] if item.get('diagnostics') else 'No diagnostic'

        print(f"\n[{i}] {citation}")
        print(f"    Source: {source_pdf}")
        print(f"    Why NOT_FOUND: {diagnostic}")
        print(f"\n    Context from PDF:")
        print(f"    {'-'*76}")

        # Extract context
        pdf_path = opinions_dir / source_pdf
        if pdf_path.exists():
            context = find_citation_context(pdf_path, citation)
            # Wrap context for readability
            words = context.split()
            line = "    "
            for word in words:
                if len(line) + len(word) + 1 > 80:
                    print(line)
                    line = "    " + word
                else:
                    line += " " + word if line.strip() else word
            if line.strip():
                print(line)
        else:
            print(f"    PDF not found: {pdf_path}")

        print()


if __name__ == "__main__":
    main()
