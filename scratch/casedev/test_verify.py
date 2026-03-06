"""Test case.dev verify() and citations() endpoints against Kettering v. Collier citations."""

import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["CASEDEV_API_KEY"]
BASE_URL = "https://api.case.dev/legal/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# All unique citations from Kettering v. Collier claims.csv
CITATIONS = [
    "Simpson v. Voiture Nationale La Societe des Quarante Hommes et Huit Chevaux, 2021-Ohio-2131, ¶¶ 13-15 (2d Dist.)",
    "First Fed. Bank of Ohio v. Angelini, 2012-Ohio-2136, ¶ 6 (3d Dist.)",
    "Heskett v. Van Horn Title Agency, Inc., 2006-Ohio-6900, ¶ 26 (10th Dist.)",
    "Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009)",
    "Bell Atl. Corp. v. Twombly, 550 U.S. 544, 570 (2007)",
    "Hecht v. Levin, 66 Ohio St. 3d 458, 460-61, 613 N.E.2d 585 (1993)",
    "Surace v. Willer, 25 Ohio St. 3d 229, 232-33, 495 N.E.2d 939 (1986)",
    "State v. Carter, 72 Ohio App.3d 553 (2d Dist. 1991)",
    "State v. Milam, 2022-Ohio-3965 (10th Dist.)",
    "Kenty v. Transamerica Premium Ins. Co., 72 Ohio St.3d 415, 419 (1995)",
    "United States v. Pendergraft, 297 F.3d 1198, 1205 (11th Cir. 2002)",
    "United States v. Jackson, 180 F.3d 55, 70 (2d Cir. 1999)",
    "Flatley v. Mauro, 39 Cal.4th 299, 331 (2006)",
    "Kulch v. Structural Fibers, Inc., 78 Ohio St.3d 134, 150 (1997)",
    "Office Depot, Inc. v. Impact Off. Prods., LLC, 821 F. Supp. 2d 912, 919-23 (N.D. Ohio 2011)",
    "In re Protech Indus., 51 F.4th 714, 720-22 (6th Cir. 2022)",
    "Stolle Mach. Co. v. RAM Precision Indus., 605 F. App'x 473, 484 (6th Cir. 2015)",
    "Van Buren v. United States, 593 U.S. 374, 380-86 (2021)",
    "Royal Truck & Trailer Sales & Serv., Inc. v. Kraft, 974 F.3d 756, 758-61 (6th Cir. 2020)",
    "Wilson v. Collins, 517 F.3d 421, 429 (6th Cir. 2008)",
]

# Build a block of text with all citations (simulating a brief)
citation_block = "\n".join(CITATIONS)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def test_verify():
    """Test verify() with full citation block."""
    print("=" * 60)
    print("TEST: verify() with all 20 Kettering citations as text block")
    print("=" * 60)

    resp = requests.post(
        f"{BASE_URL}/verify",
        headers=HEADERS,
        json={"text": citation_block},
    )
    print(f"\nStatus: {resp.status_code}")

    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return

    data = resp.json()

    # Save raw response
    with open(os.path.join(OUTPUT_DIR, "verify_response.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"Raw response saved to scratch/casedev/verify_response.json")

    # Summary
    if "summary" in data:
        print(f"\nSummary: {json.dumps(data['summary'], indent=2)}")

    if "citations" in data:
        print(f"\nCitations found: {len(data['citations'])}")
        for i, cite in enumerate(data["citations"], 1):
            print(f"\n  [{i}] {json.dumps(cite, indent=4)}")


def test_citations():
    """Test citations() Bluebook parser."""
    print("\n" + "=" * 60)
    print("TEST: citations() Bluebook parser")
    print("=" * 60)

    resp = requests.post(
        f"{BASE_URL}/citations",
        headers=HEADERS,
        json={"text": citation_block},
    )
    print(f"\nStatus: {resp.status_code}")

    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return

    data = resp.json()

    with open(os.path.join(OUTPUT_DIR, "citations_response.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"Raw response saved to scratch/casedev/citations_response.json")

    if isinstance(data, list):
        print(f"\nParsed {len(data)} citations:")
        for i, cite in enumerate(data, 1):
            print(f"\n  [{i}] {json.dumps(cite, indent=4)}")
    else:
        print(f"\nResponse: {json.dumps(data, indent=2)}")


if __name__ == "__main__":
    test_verify()
    test_citations()
