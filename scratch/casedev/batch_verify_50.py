"""Send 50 unverified citations from citations_for_review.csv to case.dev verify()."""

import csv
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["CASEDEV_API_KEY"]
BASE_URL = "https://api.case.dev/legal/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(OUTPUT_DIR, "..", "citations_for_review.csv")


def get_unverified_citations(n=50):
    """Pull first n unique unverified citations from the CSV."""
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
    print(f"Sending {len(citations)} citations to case.dev verify()...\n")

    # Join as text block
    citation_block = "\n".join(citations)
    print(f"Text block: {len(citation_block)} chars (limit: 64,000)\n")

    resp = requests.post(
        f"{BASE_URL}/verify",
        headers=HEADERS,
        json={"text": citation_block},
    )

    print(f"Status: {resp.status_code}")

    # Log rate-limit headers
    print("\n--- Rate Limit Headers ---")
    rate_keys = ["ratelimit", "x-ratelimit", "x-rate-limit", "retry-after", "x-quota", "x-remaining"]
    found_any = False
    for key, value in resp.headers.items():
        if any(rk in key.lower() for rk in rate_keys):
            print(f"  {key}: {value}")
            found_any = True
    if not found_any:
        print("  (none found)")
        print("\n--- All Response Headers ---")
        for key, value in resp.headers.items():
            print(f"  {key}: {value}")

    if resp.status_code != 200:
        print(f"\nError: {resp.text}")
        return

    data = resp.json()

    # Save raw response
    outfile = os.path.join(OUTPUT_DIR, "batch_verify_50_response.json")
    with open(outfile, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nRaw response saved to {outfile}")

    # Summary
    summary = data.get("summary", {})
    print(f"\n--- Summary ---")
    print(f"  Total citations found: {summary.get('total', '?')}")
    print(f"  Verified:              {summary.get('verified', '?')}")
    print(f"  Not found:             {summary.get('notFound', '?')}")
    print(f"  Multiple matches:      {summary.get('multipleMatches', '?')}")

    # Per-citation results
    print(f"\n--- Results ---")
    for i, cite in enumerate(data.get("citations", []), 1):
        status = cite.get("status", "?")
        norm = cite.get("normalized", "?")
        case_name = ""
        if "case" in cite:
            case_name = cite["case"].get("name", "")
        elif "candidates" in cite:
            names = [c.get("name", "") for c in cite["candidates"][:2]]
            case_name = " / ".join(names)

        flag = ""
        if status == "not_found":
            flag = " <<<"
        elif status == "multiple_matches":
            flag = " [multiple]"

        print(f"  [{i:2d}] {status:<18} {norm:<30} {case_name}{flag}")


if __name__ == "__main__":
    main()
