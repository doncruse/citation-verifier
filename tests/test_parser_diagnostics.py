"""Diagnostic tests to understand parser vs eyecite behavior.

These tests help identify:
1. What eyecite parses successfully
2. Where our regex fallbacks are needed
3. Potential contributions to eyecite upstream
"""

from eyecite import get_citations
from eyecite.models import FullCaseCitation

from citation_verifier.parser import parse_citation


def test_eyecite_vs_our_parser():
    """Compare eyecite's output with our full parser for various citations."""

    test_cases = [
        # Standard reporter - eyecite should handle
        "Obergefell v. Hodges, 576 U.S. 644 (2015)",

        # Abbreviations - does eyecite extract case names?
        "Bossart v. King Cnty., Case No. 2:24-cv-01776-JHC, 2025 WL 459154 (W.D. Wash. Feb. 11, 2025)",
        "Busha v. SC Dep't of Mental Health, No. 6:18-CV-02337-DCC, 2019 WL 651680 (D.S.C. Feb. 13, 2019)",

        # WestLaw citations - eyecite may not handle
        "Anderson v. Furst, No. 17-cv-12676, 2018 WL 4407750, at *2 (E.D. Mich. Sept. 17, 2018)",
        "Townsley v. Lifewise Assurance Co., Case No. C15-1228-JCC, 2016 WL 1393548, at *3 (W.D. Wash. April 8, 2016)",

        # California style - eyecite may not handle
        "Estrada v. Royalty Carpet Mills, Inc. (2022) 76 Cal.App.5th 685",

        # Reversed parentheticals
        "flycatcher v. affable, Case No. 24-cv-9429, 2026 WL 103589130 (Feb. 5, 2026 SDNY)",
    ]

    results = []
    for citation_text in test_cases:
        # What eyecite finds
        eyecite_results = get_citations(citation_text)
        eyecite_found_full = any(isinstance(c, FullCaseCitation) for c in eyecite_results)
        eyecite_reporter = None
        eyecite_volume = None
        eyecite_page = None

        for cite in eyecite_results:
            if isinstance(cite, FullCaseCitation):
                eyecite_volume = str(cite.groups.get("volume", ""))
                eyecite_reporter = str(cite.corrected_reporter() or "")  # type: ignore[no-untyped-call]
                eyecite_page = str(cite.groups.get("page", ""))
                break

        # What our parser finds
        our_parse = parse_citation(citation_text)

        results.append({
            "citation": citation_text,
            "eyecite_found_citation": eyecite_found_full,
            "eyecite_reporter": eyecite_reporter,
            "eyecite_volume": eyecite_volume,
            "eyecite_page": eyecite_page,
            "our_reporter": our_parse.reporter,
            "our_volume": our_parse.volume,
            "our_page": our_parse.page,
            "our_case_name": our_parse.case_name,
            "our_court": our_parse.court,
            "our_year": our_parse.year,
            "our_month": our_parse.month,
            "our_day": our_parse.day,
            "our_docket_number": our_parse.docket_number,
            "our_wl_number": our_parse.wl_number,
        })

    # Print comparison
    print("\n" + "="*80)
    print("EYECITE vs OUR PARSER COMPARISON")
    print("="*80)

    for r in results:
        print(f"\nCitation: {r['citation'][:70]}...")
        print(f"  eyecite found citation: {r['eyecite_found_citation']}")
        if r['eyecite_found_citation']:
            print(f"    ->{r['eyecite_volume']} {r['eyecite_reporter']} {r['eyecite_page']}")

        print(f"  Our parser found:")
        if r['our_reporter']:
            print(f"    ->Citation: {r['our_volume']} {r['our_reporter']} {r['our_page']}")
        if r['our_wl_number']:
            print(f"    ->WL: {r['our_year']} WL {r['our_wl_number']}")
        if r['our_case_name']:
            print(f"    ->Case name: {r['our_case_name']}")
        if r['our_court']:
            print(f"    ->Court: {r['our_court']}")
        if r['our_year']:
            date_str = str(r['our_year'])
            if r['our_month']:
                date_str += f"-{r['our_month']:02d}"
                if r['our_day']:
                    date_str += f"-{r['our_day']:02d}"
            print(f"    ->Date: {date_str}")
        if r['our_docket_number']:
            print(f"    ->Docket: {r['our_docket_number']}")

        # Highlight gaps
        if not r['eyecite_found_citation'] and (r['our_reporter'] or r['our_wl_number']):
            print(f"  [!]  GAP: eyecite missed but we found it with regex")

    print("\n" + "="*80)


def test_abbreviation_extraction():
    """Test whether eyecite extracts case names with abbreviations."""

    cases_with_abbrev = [
        ("Bossart v. King Cnty.", "Cnty."),
        ("Busha v. SC Dep't of Mental Health", "Dep't"),
        ("Smith v. Fire Dept.", "Dept."),
        ("Jones v. City Corp.", "Corp."),
        ("Doe v. County Bd. of Education", "Bd."),
    ]

    print("\n" + "="*80)
    print("ABBREVIATION HANDLING")
    print("="*80)

    for case_name_fragment, abbrev in cases_with_abbrev:
        # Build a full citation
        citation_text = f"{case_name_fragment}, 100 F.3d 200 (2d Cir. 2020)"

        # What eyecite extracts for case name (if anything)
        eyecite_results = get_citations(citation_text)
        eyecite_case_name = None
        for cite in eyecite_results:
            if isinstance(cite, FullCaseCitation) and hasattr(cite, 'metadata'):
                meta = cite.metadata
                if hasattr(meta, 'plaintiff') and hasattr(meta, 'defendant'):
                    eyecite_case_name = f"{meta.plaintiff} v. {meta.defendant}"
                break

        # What our parser extracts
        our_parse = parse_citation(citation_text)

        print(f"\nInput: {citation_text}")
        print(f"  eyecite case name: {eyecite_case_name or 'NOT EXTRACTED'}")
        print(f"  Our case name: {our_parse.case_name or 'NOT EXTRACTED'}")

        if our_parse.case_name and abbrev in our_parse.case_name:
            print(f"  [!]  Our parser kept abbreviation '{abbrev}' - normalization needed?")


def test_westlaw_citations():
    """Test eyecite's handling of WestLaw citations."""

    wl_citations = [
        "2018 WL 4407750",
        "2016 WL 1393548, at *3",
        "2025 WL 459154",
        "Anderson v. Furst, 2018 WL 4407750 (E.D. Mich. Sept. 17, 2018)",
    ]

    print("\n" + "="*80)
    print("WESTLAW CITATION HANDLING")
    print("="*80)

    for citation_text in wl_citations:
        eyecite_results = get_citations(citation_text)
        eyecite_found = len(eyecite_results) > 0

        our_parse = parse_citation(citation_text)

        print(f"\nInput: {citation_text}")
        print(f"  eyecite found: {eyecite_found}")
        if eyecite_found:
            print(f"    ->{[type(c).__name__ for c in eyecite_results]}")
        print(f"  Our parser found WL: {our_parse.wl_number or 'NO'}")

        if not eyecite_found and our_parse.wl_number:
            print(f"  [!]  GAP: eyecite missed WL citation that we found")
