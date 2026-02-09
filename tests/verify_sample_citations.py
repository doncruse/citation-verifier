"""Sample and verify citations from extracted hallucination opinions.

Takes a sample of citations and runs them through our verifier to see which
are real vs fake.

Usage:
    python tests/verify_sample_citations.py --sample-size 50
"""

import argparse
import json
import random
from pathlib import Path

from citation_verifier.verifier import CitationVerifier


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


def verify_citations_batch(citations: list[dict]) -> dict[str, list[dict]]:
    """Verify a batch of citations and organize by result status.

    Returns:
        Dict with keys: verified, possible_match, likely_real, not_found
    """
    results = {
        'VERIFIED': [],
        'LIKELY_REAL': [],
        'POSSIBLE_MATCH': [],
        'NOT_FOUND': []
    }

    # Initialize verifier
    verifier = CitationVerifier()

    total = len(citations)
    print(f"\nVerifying {total} citations...")
    print("This will take a few minutes (rate limited to avoid overwhelming the API)\n")

    for i, cite_data in enumerate(citations, 1):
        citation_text = cite_data['citation']
        source_pdf = cite_data.get('source_pdf', 'unknown')

        # Extract a simple citation string for verification
        # Format: "Case Name, Volume Reporter Page (Year)"
        case_name = cite_data['case_name'].strip()
        if not case_name or case_name == 'v.':
            case_name = f"{cite_data['volume']} {cite_data['reporter']} {cite_data['page']}"

        simple_citation = f"{case_name}, {cite_data['volume']} {cite_data['reporter']} {cite_data['page']}"
        if cite_data['year']:
            simple_citation += f" ({cite_data['year']})"

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
