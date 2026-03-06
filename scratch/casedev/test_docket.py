"""Test case.dev docket() endpoint as potential RECAP replacement.

Compares results against our existing RECAP pipeline for cases that
fell through to Step 3 in the Valve v. Rothschild verification.
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["CASEDEV_API_KEY"]
BASE_URL = "https://api.case.dev/legal/v1/docket"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Cases that went through RECAP in our pipeline
TEST_CASES = [
    {
        "name": "PacTool v. Kett Tool",
        "cited": "PacTool Int'l v. Kett Tool Co., No. C06-5367BHS, 2009 WL 10705131 (W.D. Wash. Sept. 15, 2009)",
        "court": "wawd",
        "docket_number": "C06-5367BHS",
        "our_result_url": "https://www.courtlistener.com/docket/4410019/95/pactool-international-ltd-v-dewalt-industrial-tool-co/",
        "our_result_name": "Pactool International Ltd v. Dewalt Industrial Tool Co",
    },
    {
        "name": "Amazon v. Personal Web Tech",
        "cited": "Amazon.com, Inc. v. Personal Web Technologies, LLC, No. C14-01375 BLW, 2020 WL 3515051 (W.D. Wash. June 29, 2020)",
        "court": "wawd",
        "docket_number": "C14-01375",
        "our_result_url": "https://www.courtlistener.com/docket/17136064/21/amazoncom-inc-v-robojap-technologies-llc/",
        "our_result_name": "Amazon.com, Inc. v. Robojap Technologies LLC",
    },
    {
        "name": "Diamondback v. Repeat Precision",
        "cited": "Diamondback Industries, Inc. v. Repeat Precision, LLC, No. 6:19-cv-00034-ADA (W.D. Tex. June 27, 2019)",
        "court": "txwd",
        "docket_number": "6:19-cv-00034",
        "our_result_url": "https://www.courtlistener.com/docket/14534075/68/diamondback-industries-inc-v-repeat-precision-llc/",
        "our_result_name": "Diamondback Industries, Inc. v. Repeat Precision, LLC",
    },
]


def test_docket_search(case):
    """Test docket search mode."""
    print(f"\n--- Search: {case['name']} ---")
    print(f"  Query: {case['cited'].split(',')[0]}")
    print(f"  Court: {case['court']}")

    resp = requests.post(
        BASE_URL,
        headers=HEADERS,
        json={
            "type": "search",
            "query": case["cited"].split(",")[0],  # case name only
            "court": case["court"],
        },
    )
    print(f"  Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Error: {resp.text[:200]}")
        return None

    data = resp.json()
    print(f"  Found: {data.get('found', 0)} dockets")

    dockets = data.get("dockets", [])
    for i, d in enumerate(dockets[:3]):
        print(f"    [{i+1}] {d.get('caseName', '?')}")
        print(f"        Docket: {d.get('docketNumber', '?')}")
        print(f"        Court:  {d.get('court', '?')}")
        print(f"        Filed:  {d.get('dateFiled', '?')}")
        print(f"        URL:    {d.get('url', '?')}")
        print(f"        ID:     {d.get('id', '?')}")

    return data


def test_docket_lookup(docket_id, case_name):
    """Test docket lookup mode with entries."""
    print(f"\n  --- Lookup docket {docket_id} with entries ---")

    resp = requests.post(
        BASE_URL,
        headers=HEADERS,
        json={
            "type": "lookup",
            "docketId": str(docket_id),
            "includeEntries": True,
        },
    )
    print(f"  Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Error: {resp.text[:200]}")
        return None

    data = resp.json()
    docket = data.get("docket", {})
    entries = docket.get("entries", [])
    print(f"  Case: {docket.get('caseName', '?')}")
    print(f"  Entries: {len(entries)}")

    # Show entries that look like opinions/orders (first 5)
    opinion_keywords = ["opinion", "order", "memorandum", "ruling", "decision", "judgment"]
    relevant = []
    for e in entries:
        desc = (e.get("description") or "").lower()
        if any(kw in desc for kw in opinion_keywords):
            relevant.append(e)

    print(f"  Opinion-like entries: {len(relevant)}")
    for e in relevant[:5]:
        docs = e.get("documents", [])
        doc_info = f" ({len(docs)} docs)" if docs else " (no docs)"
        print(f"    [{e.get('entryNumber', '?')}] {e.get('date', '?')}: {e.get('description', '?')[:80]}{doc_info}")
        for d in docs[:2]:
            print(f"         doc#{d.get('documentNumber', '?')}: {d.get('description', '?')[:60]} (pages: {d.get('pageCount', '?')}, avail: {d.get('isAvailable', '?')})")

    return data


def main():
    all_results = {}

    for case in TEST_CASES:
        print(f"\n{'='*70}")
        print(f"TEST: {case['name']}")
        print(f"Our pipeline found: {case['our_result_name']}")
        print(f"Our URL: {case['our_result_url']}")
        print(f"{'='*70}")

        t0 = time.time()

        # Search by case name
        search_result = test_docket_search(case)

        # If we found dockets, look up the first one with entries
        if search_result and search_result.get("dockets"):
            first_docket = search_result["dockets"][0]
            docket_id = first_docket.get("id")
            if docket_id:
                lookup_result = test_docket_lookup(docket_id, case["name"])

        elapsed = time.time() - t0
        print(f"\n  Total time: {elapsed:.2f}s")

        all_results[case["name"]] = {
            "search": search_result,
            "time_s": round(elapsed, 2),
        }

    # Save raw results
    outfile = os.path.join(OUTPUT_DIR, "docket_response.json")
    with open(outfile, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {outfile}")


if __name__ == "__main__":
    main()
