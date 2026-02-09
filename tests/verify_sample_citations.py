"""Sample and verify citations from extracted hallucination opinions.

Takes a sample of citations and runs them through our verifier to see which
are real vs fake.

Usage:
    python tests/verify_sample_citations.py --sample-size 50
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

import pdfplumber

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from citation_verifier.verifier import CitationVerifier
from citation_verifier.text_cleaner import clean_case_name


def sample_citations(results: list[dict], sample_size: int = 50) -> list[dict]:
    """Sample citations strategically from extracted results.

    Takes citations from multiple opinions to get a diverse sample.
    """
    sampled = []

    # Calculate citations per opinion (roughly equal distribution)
    total_opinions = len(results)
    cites_per_opinion = max(1, sample_size // total_opinions)

    for result in results:
        pdf_name = result['pdf_name']
        uncertain = result.get('uncertain', [])

        if not uncertain:
            continue

        # Sample from this opinion
        n_to_sample = min(cites_per_opinion, len(uncertain))
        sampled_from_opinion = random.sample(uncertain, n_to_sample)

        # Add source info
        for cite in sampled_from_opinion:
            cite['source_pdf'] = pdf_name

        sampled.extend(sampled_from_opinion)

        if len(sampled) >= sample_size:
            break

    return sampled[:sample_size]


def extract_citation_from_pdf(pdf_path: Path, reporter_text: str, context_chars: int = 200) -> str | None:
    """Given a reporter citation string, find it in the PDF and extract
    the full citation including case name from surrounding text.

    Args:
        pdf_path: Path to the PDF file
        reporter_text: The reporter portion (e.g., "411 F.3d 1006")
        context_chars: Number of characters before match to grab

    Returns:
        The cleaned-up full citation string or None if not found
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        idx = full_text.find(reporter_text)
        if idx == -1:
            return None

        # Grab context before the reporter citation
        start = max(0, idx - context_chars)
        context = full_text[start:idx + len(reporter_text)]

        # Normalize whitespace
        context = re.sub(r'\s+', ' ', context).strip()

        # Look for "In re" pattern
        in_re_match = re.search(r'In re ([^,]+),\s*' + re.escape(reporter_text), context, re.IGNORECASE)
        if in_re_match:
            case_name = f"In re {in_re_match.group(1)}"
            case_name = clean_case_name(case_name)
            return f"{case_name}, {reporter_text}"

        # Look for standard "X v. Y" pattern
        vs_match = re.search(r'([A-Z][^\n,]+?)\s+v\.\s+([^,\n]+?),\s*' + re.escape(reporter_text), context, re.IGNORECASE)
        if vs_match:
            plaintiff = vs_match.group(1).strip()
            defendant = vs_match.group(2).strip()
            # Strip parenthetical aliases like "(Suday I)"
            defendant = re.sub(r'\s*\([^)]+\)\s*$', '', defendant).strip()
            case_name = f"{plaintiff} v. {defendant}"
            case_name = clean_case_name(case_name)
            return f"{case_name}, {reporter_text}"

        # Couldn't reconstruct, return just the reporter
        return reporter_text

    except Exception as e:
        return None


def verify_citations_batch(citations: list[dict]) -> dict[str, list[dict]]:
    """Verify a batch of citations and organize by result status.

    Returns:
        Dict with keys: verified, possible_match, likely_real, not_found, skipped
    """
    results = {
        'VERIFIED': [],
        'LIKELY_REAL': [],
        'POSSIBLE_MATCH': [],
        'NOT_FOUND': [],
        'SKIPPED': []
    }

    # Initialize verifier
    verifier = CitationVerifier()
    opinions_dir = Path(__file__).parent / "data" / "hallucination_opinions"

    total = len(citations)
    print(f"\nVerifying {total} citations...")
    print("This will take a few minutes (rate limited to avoid overwhelming the API)\n")

    for i, cite_data in enumerate(citations, 1):
        citation_text = cite_data['citation']
        source_pdf = cite_data.get('source_pdf', 'unknown')
        reporter_text = cite_data.get('reporter_text', '')

        # Check if we have a usable citation
        case_name = cite_data.get('case_name', '').strip()

        # Skip short cites (both parties None/empty)
        if not case_name or case_name == 'v.' or case_name.startswith('None v. None'):
            print(f"[{i}/{total}] SKIPPED: {citation_text} (short cite - no case name)")
            results['SKIPPED'].append({
                'citation': citation_text,
                'source_pdf': source_pdf,
                'reason': 'Short cite with no case name - cannot verify'
            })
            print()
            continue

        # Handle "None v." cases by going back to PDF
        if case_name.startswith('None v.') or 'None' in case_name:
            print(f"[{i}/{total}] Reconstructing from PDF: {source_pdf}")
            pdf_path = opinions_dir / source_pdf
            if pdf_path.exists() and reporter_text:
                reconstructed = extract_citation_from_pdf(pdf_path, reporter_text)
                if reconstructed and reconstructed != reporter_text:
                    simple_citation = reconstructed
                    print(f"  Reconstructed: {simple_citation}")
                else:
                    # Couldn't reconstruct, skip it
                    print(f"  Could not reconstruct case name, skipping")
                    results['SKIPPED'].append({
                        'citation': citation_text,
                        'source_pdf': source_pdf,
                        'reason': 'Could not reconstruct case name from PDF'
                    })
                    print()
                    continue
            else:
                print(f"  PDF not found or no reporter text, skipping")
                results['SKIPPED'].append({
                    'citation': citation_text,
                    'source_pdf': source_pdf,
                    'reason': 'PDF not found or no reporter text'
                })
                print()
                continue
        else:
            # Use the citation as-is (already cleaned by extract_citations_batch.py)
            simple_citation = citation_text

        print(f"[{i}/{total}] Verifying: {simple_citation}")

        try:
            result = verifier.verify(simple_citation)

            print(f"  Status: {result.status.value}")
            if result.matched_url:
                print(f"  Found: {result.matched_url}")

            # Organize by status
            cite_result = {
                'citation': simple_citation,
                'original': citation_text,
                'source_pdf': source_pdf,
                'status': result.status.value,
                'matched_url': result.matched_url,
                'matched_cluster_id': result.matched_cluster_id,
                'confidence': result.confidence,
                'diagnostics': result.diagnostics
            }

            results[result.status.value].append(cite_result)

        except Exception as e:
            print(f"  ERROR: {e}")
            results['NOT_FOUND'].append({
                'citation': simple_citation,
                'original': citation_text,
                'source_pdf': source_pdf,
                'status': 'ERROR',
                'error': str(e)
            })

        print()  # Blank line between citations

    return results


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Sample and verify citations')
    parser.add_argument('--sample-size', type=int, default=50,
                        help='Number of citations to sample (default: 50)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for reproducibility (default: 42)')
    args = parser.parse_args()

    # Set random seed for reproducibility
    random.seed(args.seed)

    # Load extracted citations
    data_dir = Path(__file__).parent / "data"
    extracted_file = data_dir / "citations_extracted_raw.json"

    if not extracted_file.exists():
        print(f"Error: {extracted_file} not found")
        print("Run extract_citations_batch.py first")
        return

    with open(extracted_file) as f:
        all_results = json.load(f)

    # Count total citations
    total_citations = sum(len(r.get('uncertain', [])) for r in all_results)
    print(f"Loaded {total_citations} citations from {len(all_results)} opinions")

    # Sample citations
    print(f"\nSampling {args.sample_size} citations...")
    sampled = sample_citations(all_results, args.sample_size)
    print(f"Sampled {len(sampled)} citations")

    # Verify the sample
    verification_results = verify_citations_batch(sampled)

    # Save results
    output_file = data_dir / f"verification_sample_{args.sample_size}.json"
    with open(output_file, 'w') as f:
        json.dump(verification_results, f, indent=2)

    # Print summary
    print(f"\n{'='*80}")
    print("VERIFICATION RESULTS")
    print(f"{'='*80}")
    print(f"Total verified: {len(sampled)}")
    print(f"\nBy status:")
    for status, items in verification_results.items():
        print(f"  {status:20s}: {len(items)}")

    print(f"\nResults saved to: {output_file}")

    # Show NOT_FOUND citations for manual review
    not_found = verification_results.get('NOT_FOUND', [])
    if not_found:
        print(f"\n{'='*80}")
        print(f"NOT FOUND CITATIONS ({len(not_found)}) - Candidates for fake citations:")
        print(f"{'='*80}")
        for item in not_found[:10]:  # Show first 10
            print(f"\n{item['citation']}")
            print(f"  Source: {item['source_pdf']}")
            if item.get('diagnostics'):
                print(f"  Why: {item['diagnostics'][0] if item['diagnostics'] else 'Unknown'}")

        if len(not_found) > 10:
            print(f"\n... and {len(not_found) - 10} more")


if __name__ == "__main__":
    main()
