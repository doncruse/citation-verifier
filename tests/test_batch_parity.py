"""Batch vs. individual citation-lookup parity test.

Sends ~50 diverse citations through both the batch citation-lookup path
and individual citation-lookup calls, then verifies that the batch path
recognizes the same citations.  Uses the real CourtListener API.

Run with:
    python -m pytest tests/test_batch_parity.py -v -s

Requires COURTLISTENER_API_TOKEN in .env.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from citation_verifier.client import AsyncCourtListenerClient
from citation_verifier.verifier import CitationVerifier

# Skip entire module if no API token is available
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("COURTLISTENER_API_TOKEN", ""),
        reason="No COURTLISTENER_API_TOKEN set",
    ),
    pytest.mark.live_api,
]

# Curated corpus: proper Bluebook format, diverse reporters and courts.
# Every citation here has been individually verified as VERIFIED against CL.
CITATIONS = [
    # --- U.S. Reports (Supreme Court) ---
    "Obergefell v. Hodges, 576 U.S. 644 (2015)",
    "Walden v. Fiore, 571 U.S. 277 (2014)",
    "Erickson v. Pardus, 551 U.S. 89 (2007)",
    "Forrester v. White, 484 U.S. 219 (1988)",
    "Central Bank of Denver, N.A. v. First Interstate Bank of Denver, N.A., 511 U.S. 164 (1994)",
    "Chiaverini v. City of Napoleon, Ohio, 602 U.S. 556 (2024)",
    "Goodyear Dunlop Tires Operations, S.A. v. Brown, 564 U.S. 915 (2011)",
    "Rubber Co. v. Haeger, 581 U.S. 101 (2017)",

    # --- F.2d (older federal appeals) ---
    "Yagman v. Republic Ins., 987 F.2d 622 (9th Cir. 1993)",
    "United States v. Craner, 652 F.2d 23 (9th Cir. 1981)",
    "Napier v. Thirty or More Unidentified Fed. Agents, Emps. or Officers, 855 F.2d 1080 (3d Cir. 1988)",
    "Carpenter v. Bd. of Regents of Univ. of Wisconsin Sys., 728 F.2d 911 (7th Cir. 1984)",
    "Thomas v. Evans, 880 F.2d 1235 (11th Cir. 1989)",

    # --- F.3d ---
    "Hunt v. Aimco Props., L.P., 814 F.3d 1213 (11th Cir. 2016)",
    "United States v. Green, 873 F.3d 846 (11th Cir. 2017)",
    "Brown v. Whole Foods Mkt. Grp., Inc., 789 F.3d 146 (D.C. Cir. 2015)",
    "Conner v. Travis Cnty., 209 F.3d 794 (5th Cir. 2000)",
    "Bronk v. Ineichen, 54 F.3d 425 (7th Cir. 1995)",
    "Schwartz v. Millon Air, Inc., 341 F.3d 1220 (11th Cir. 2003)",
    "In re Purchasing Power, LLC, 851 F.3d 1219 (11th Cir. 2017)",
    "Browning v. Clinton, 292 F.3d 235 (D.C. Cir. 2002)",
    "Caldwell v. City & Cnty. of San Francisco, 889 F.3d 1105 (9th Cir. 2018)",
    "Pac. Harbor Cap., Inc. v. Carnival Air Lines, Inc., 210 F.3d 1112 (9th Cir. 2000)",

    # --- F.4th (newest federal appeals reporter) ---
    "Club Madonna Inc. v. City of Miami Beach, 42 F.4th 1231 (11th Cir. 2022)",
    "Watters v. Homeowners' Ass'n at Pres. at Bridgewater, 48 F.4th 779 (7th Cir. 2022)",

    # --- F. Supp. / F. Supp. 2d / F. Supp. 3d (district courts) ---
    "Higgins v. J.C. Penney, Inc., 630 F. Supp. 722 (E.D. Mo. 1986)",
    "Weiss v. 2100 Condo. Ass'n, Inc., 941 F. Supp. 2d 1337 (S.D. Fla. 2013)",
    "Allapattah Servs., Inc. v. Exxon Corp., 372 F. Supp. 2d 1344 (S.D. Fla. 2005)",
    "Presidential Bank, FSB v. 1733 27th Street SE LLC, 271 F. Supp. 3d 163 (D.D.C. 2017)",
    "Chambers v. NASA Fed. Credit Union, 222 F. Supp. 3d 1 (D.D.C. 2016)",
    "Whole Foods Mkt. Grp. v. Wical L.P., 288 F. Supp. 3d 176 (D.D.C. 2018)",

    # --- F. App'x (unpublished federal) ---
    "McDonald v. Cooper Tire & Rubber Co., 186 F. App'x 930 (11th Cir. 2006)",
    "Herndon v. Hous. Auth. of S. Bend, Indiana, 670 F. App'x 417 (7th Cir. 2016)",

    # --- F.R.D. ---
    "Celano v. Marriott Int'l, Inc., 242 F.R.D. 544 (N.D. Cal. 2007)",
    "Mir v. L-3 Commc'ns Integrated Sys., L.P., 319 F.R.D. 220 (N.D. Tex. 2016)",

    # --- B.R. (bankruptcy) ---
    "In re McFadden, 477 B.R. 686 (Bankr. N.D. Ohio 2012)",

    # --- State reporters: Maryland ---
    "Jefferson-El v. State, 330 Md. 99 (1993)",
    "Lloyd v. Niceta, 485 Md. 422 (2023)",
    "Milburn v. Milburn, 142 Md. App. 518 (2002)",
    "Davis v. Davis, 280 Md. 119 (1977)",

    # --- State reporters: California ---
    "D.I. Chadbourne, Inc. v. Superior Court, 60 Cal. 2d 723 (1964)",
    "In re Marriage of Smith, 195 Cal. App. 4th 1007 (2011)",
    "Lipton v. Superior Court, 48 Cal. App. 4th 1599 (1996)",

    # --- State reporters: Kansas ---
    "Garcia v. Ball, 303 Kan. 560 (2015)",
    "First Management v. Topeka Investment Group, 47 Kan. App. 2d 233 (2012)",

    # --- State reporters: N.E.2d / N.E.3d (Indiana, Illinois, Ohio) ---
    "Guardiola v. State, 375 N.E.2d 1105 (Ind. 1978)",
    "Durden v. State, 99 N.E.3d 645 (Ind. 2018)",
    "People v. Urdiales, 871 N.E.2d 669 (Ill. 2007)",

    # --- State reporters: P.3d ---
    "Landmark Nat'l Bank v. Kesler, 216 P.3d 158 (Kan. 2009)",

    # --- State reporters: S.W.2d / S.W.3d (Texas) ---
    "Busby v. Busby, 457 S.W.2d 551 (Tex. 1970)",
    "Ashfaq v. Ashfaq, 467 S.W.3d 539 (Tex. App. 2015)",

    # --- State reporters: A.3d (D.C., PA) ---
    "Krapf v. St. Luke's Hosp., 4 A.3d 642 (Pa. Super. Ct. 2010)",
]

# Total should be ~52
assert len(CITATIONS) == 52, f"Expected 52 citations, got {len(CITATIONS)}"


class TestBatchVsIndividualParity:
    """Verify that batch citation-lookup finds the same citations
    as individual lookups."""

    def test_batch_finds_all_individually_found_citations(self):
        """Every citation found by individual lookup should also be
        found by batch lookup."""

        async def run():
            async with AsyncCourtListenerClient() as client:
                # Individual lookups
                individual_hits: dict[int, str] = {}
                for i, cite in enumerate(CITATIONS):
                    try:
                        results = await client.citation_lookup(cite)
                        for entry in results:
                            clusters = entry.get("clusters", [])
                            if clusters:
                                individual_hits[i] = clusters[0].get(
                                    "case_name", ""
                                )
                                break
                    except Exception as e:
                        print(f"  Individual lookup failed for [{i}]: {e}")

                print(
                    f"\nIndividual hits: {len(individual_hits)}/{len(CITATIONS)}"
                )

                # Batch lookup
                verifier = CitationVerifier()
                batch_hits = await verifier._batch_citation_lookup(
                    client, CITATIONS
                )

                print(f"Batch hits: {len(batch_hits)}/{len(CITATIONS)}")

                # Compare
                individual_only = set(individual_hits) - set(batch_hits)
                batch_only = set(batch_hits) - set(individual_hits)

                if individual_only:
                    print("\nFound individually but NOT in batch:")
                    for i in sorted(individual_only):
                        print(f"  [{i}] {CITATIONS[i]}")
                        print(f"       individual: {individual_hits[i]}")

                if batch_only:
                    print("\nFound in batch but NOT individually:")
                    for i in sorted(batch_only):
                        print(
                            f"  [{i}] {CITATIONS[i]}"
                        )
                        print(
                            f"       batch: {batch_hits[i].get('case_name', '')}"
                        )

                # The key assertion: batch should find everything
                # individual finds
                assert not individual_only, (
                    f"Batch missed {len(individual_only)} citations that "
                    f"individual lookup found: "
                    + ", ".join(
                        f"[{i}] {CITATIONS[i][:50]}"
                        for i in sorted(individual_only)
                    )
                )

                # Informational: report overall hit rate
                not_found = [
                    i
                    for i in range(len(CITATIONS))
                    if i not in individual_hits and i not in batch_hits
                ]
                if not_found:
                    print(f"\nNeither path found ({len(not_found)}):")
                    for i in not_found:
                        print(f"  [{i}] {CITATIONS[i]}")

        asyncio.run(run())
