"""Check which Indigo Book abbreviations are NOT in our parser.

The Indigo Book is the authoritative source for legal abbreviations:
https://law.resource.org/pub/us/code/blue/indigobook-2.0-beta.html#t11

This script helps identify gaps in our abbreviation normalization.
"""

# Indigo Book Table 11 - common abbreviations (subset for testing)
# Full table at: https://law.resource.org/pub/us/code/blue/indigobook-2.0-beta.html#t11
INDIGO_BOOK_SUBSET = {
    # Government entities
    "Cnty.": "County",
    "Cty.": "County",
    "Dept.": "Department",
    "Dep't": "Department",
    "Div.": "Division",
    "Bd.": "Board",
    "Comm.": "Commission",
    "Comm'n": "Commission",

    # Organizations
    "Corp.": "Corporation",
    "Co.": "Company",
    "Inc.": "Incorporated",
    "Ltd.": "Limited",
    "LLC": "Limited Liability Company",
    "L.L.C.": "Limited Liability Company",
    "Assn.": "Association",
    "Ass'n": "Association",

    # Positions
    "Admin.": "Administrator",
    "Adm'r": "Administrator",
    "Exec.": "Executive",
    "Dir.": "Director",
    "Sec'y": "Secretary",
    "Treas.": "Treasurer",

    # Legal terms
    "Atty.": "Attorney",
    "Dist.": "District",
    "Gen.": "General",
    "Off.": "Office",
    "Ofc.": "Office",
    "Serv.": "Service",
    "Servs.": "Services",

    # Education
    "Sch.": "School",
    "Dist.": "District",
    "Univ.": "University",
    "Coll.": "College",

    # Medical/Health
    "Hosp.": "Hospital",
    "Med.": "Medical",
    "Ctr.": "Center",

    # Geographic
    "N.": "North",
    "S.": "South",
    "E.": "East",
    "W.": "West",
    "St.": "Street",
    "Ave.": "Avenue",
    "Blvd.": "Boulevard",

    # Religious
    "Ch.": "Church",
    "Cath.": "Catholic",

    # Other common
    "Ins.": "Insurance",
    "Mfg.": "Manufacturing",
    "Nat'l": "National",
    "Natl.": "National",
    "Int'l": "International",
    "Intl.": "International",
    "Pub.": "Public",
    "Util.": "Utility",
    "Transp.": "Transportation",
}


def check_parser_coverage():
    """Check which abbreviations are in our parser."""
    from citation_verifier.parser import _normalize_case_name

    print("="*70)
    print("INDIGO BOOK ABBREVIATION COVERAGE")
    print("="*70)

    covered = []
    not_covered = []

    for abbrev, full_form in INDIGO_BOOK_SUBSET.items():
        # Test if our parser normalizes it
        test_input = f"Smith v. Test {abbrev}"
        normalized = _normalize_case_name(test_input)

        # Check if the full form appears in output
        if full_form in normalized and abbrev not in normalized:
            covered.append((abbrev, full_form))
        else:
            not_covered.append((abbrev, full_form))

    print(f"\nCOVERED ({len(covered)}/{len(INDIGO_BOOK_SUBSET)}):")
    for abbrev, full_form in sorted(covered):
        print(f"  {abbrev:15s} -> {full_form}")

    print(f"\nNOT COVERED ({len(not_covered)}/{len(INDIGO_BOOK_SUBSET)}):")
    for abbrev, full_form in sorted(not_covered):
        test_input = f"Smith v. Test {abbrev}"
        normalized = _normalize_case_name(test_input)
        print(f"  {abbrev:15s} -> {full_form:20s} (got: {normalized})")

    print("\n" + "="*70)
    print(f"Coverage: {len(covered)}/{len(INDIGO_BOOK_SUBSET)} ({len(covered)/len(INDIGO_BOOK_SUBSET)*100:.1f}%)")
    print("="*70)

    if not_covered:
        print("\nTO ADD TO PARSER:")
        print("Add these to _normalize_case_name() in parser.py:")
        print()
        for abbrev, full_form in sorted(not_covered):
            # Escape special regex chars
            escaped = abbrev.replace(".", r"\.").replace("'", r"'")
            print(f'    r"\\b{escaped}\\b": "{full_form}",')


if __name__ == "__main__":
    check_parser_coverage()
