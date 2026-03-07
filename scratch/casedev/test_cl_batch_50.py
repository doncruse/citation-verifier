"""Send the same 50 citations to CL citation-lookup as a batch and compare with case.dev."""

import csv
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

CL_TOKEN = os.environ["COURTLISTENER_API_TOKEN"]
CL_URL = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
CL_HEADERS = {
    "Authorization": f"Token {CL_TOKEN}",
    "Content-Type": "application/json",
}

DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(DIR, "..", "citations_for_review.csv")


def get_unverified_citations(n=50):
    """Same 50 citations we sent to case.dev."""
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    seen = set()
    batch = []
    for r in rows:
        cite = r["citation_text"]
        if r["v_status"] == "" and cite not in seen:
            seen.add(cite)
            batch.append(cite)
            if len(batch) >= n:
                break
    return batch


def main():
    citations = get_unverified_citations(50)
    citation_block = "\n".join(citations)
    print(f"Sending {len(citations)} citations ({len(citation_block)} chars) to CL citation-lookup...\n")

    t0 = time.time()
    resp = requests.post(
        CL_URL,
        headers=CL_HEADERS,
        json={"text": citation_block},
        timeout=60,
    )
    elapsed = time.time() - t0

    print(f"Status: {resp.status_code}")
    print(f"Time: {elapsed:.2f}s")

    # Log headers
    for key, value in resp.headers.items():
        if any(k in key.lower() for k in ["ratelimit", "retry", "x-"]):
            print(f"  Header: {key}: {value}")

    if resp.status_code != 200:
        print(f"Error: {resp.text[:500]}")
        return

    data = resp.json()

    # Save raw response
    outfile = os.path.join(DIR, "cl_batch_50_response.json")
    with open(outfile, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nRaw response saved to {outfile}")

    # Analyze structure
    print(f"\nResponse type: {type(data).__name__}")
    if isinstance(data, list):
        print(f"Top-level list length: {len(data)}")
        for i, item in enumerate(data[:5]):
            print(f"\n  [{i}] keys: {list(item.keys()) if isinstance(item, dict) else type(item).__name__}")
            if isinstance(item, dict):
                # Show the citation key and how many clusters
                cite_key = item.get("citation", item.get("normalized", "?"))
                clusters = item.get("clusters", [])
                print(f"       citation: {cite_key}")
                print(f"       clusters: {len(clusters)}")
                if clusters:
                    c = clusters[0]
                    print(f"       first cluster keys: {list(c.keys())}")
                    print(f"       case_name: {c.get('case_name', '?')}")
        if len(data) > 5:
            print(f"\n  ... and {len(data) - 5} more items")
    elif isinstance(data, dict):
        print(f"Top-level keys: {list(data.keys())}")
        for key in list(data.keys())[:5]:
            val = data[key]
            if isinstance(val, list):
                print(f"  {key}: list of {len(val)}")
            elif isinstance(val, dict):
                print(f"  {key}: dict with keys {list(val.keys())[:5]}")
            else:
                print(f"  {key}: {val}")

    # Compare counts
    print(f"\n--- Comparison with case.dev ---")
    casedev_file = os.path.join(DIR, "batch_verify_50_response.json")
    if os.path.exists(casedev_file):
        with open(casedev_file) as f:
            cd_data = json.load(f)
        cd_total = cd_data.get("summary", {}).get("total", "?")
        print(f"  case.dev found: {cd_total} citations")
        print(f"  case.dev time:  loaded from cache")

    if isinstance(data, list):
        cl_total = len(data)
        cl_with_clusters = sum(1 for item in data if isinstance(item, dict) and item.get("clusters"))
        cl_empty = cl_total - cl_with_clusters
        print(f"  CL found:       {cl_total} citation entries")
        print(f"  CL with match:  {cl_with_clusters}")
        print(f"  CL no match:    {cl_empty}")
    print(f"  CL time:        {elapsed:.2f}s")


if __name__ == "__main__":
    main()
