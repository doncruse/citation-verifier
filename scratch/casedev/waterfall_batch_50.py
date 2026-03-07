"""Run waterfall (name matching + CL fallback) on the 50 citations
already verified by case.dev in batch_verify_50_response.json."""

import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from citation_verifier import CitationVerifier
from citation_verifier.models import VerificationStatus
from citation_verifier.parser import parse_citation

DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(DIR, "..", "citations_for_review.csv")
RESPONSE_PATH = os.path.join(DIR, "batch_verify_50_response.json")


def load_citations_and_ground_truth(n=50):
    """Load the same 50 unverified citations we sent to case.dev."""
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    seen = set()
    batch = []
    for r in rows:
        cite = r["citation_text"]
        if r["v_status"] == "" and cite not in seen:
            seen.add(cite)
            batch.append(r)
            if len(batch) >= n:
                break
    return batch


def casedev_to_cluster(cd_case: dict) -> dict:
    """Convert case.dev case result to CL-style cluster dict."""
    return {
        "id": cd_case.get("id"),
        "case_name": cd_case.get("name", ""),
        "absolute_url": cd_case.get("url", ""),
        "date_filed": cd_case.get("dateDecided"),
    }


def match_casedev_to_citation(cd_citations, cite_text):
    """Find the case.dev result that corresponds to this citation text."""
    parsed = parse_citation(cite_text)

    # Build a key from our parsed citation
    if parsed.volume and parsed.reporter and parsed.page:
        our_key = f"{parsed.volume} {parsed.reporter} {parsed.page}"
    else:
        our_key = None

    for cd in cd_citations:
        cd_norm = cd.get("normalized", "")
        # Direct match on normalized string
        if our_key and (cd_norm == our_key or cd_norm.replace(". ", ".") == our_key.replace(". ", ".")):
            return cd
        # Try without periods
        if our_key and cd_norm.replace(".", "").replace("  ", " ") == our_key.replace(".", "").replace("  ", " "):
            return cd

    return None


def main():
    # Load case.dev response
    with open(RESPONSE_PATH) as f:
        casedev_data = json.load(f)
    cd_citations = casedev_data.get("citations", [])

    # Load our 50 citations
    rows = load_citations_and_ground_truth(50)
    print(f"Citations: {len(rows)}")
    print(f"case.dev results: {len(cd_citations)}")

    verifier = CitationVerifier()
    results = []
    resolved_by_casedev = 0
    name_mismatches = 0
    need_fallback = []

    for row in rows:
        cite_text = row["citation_text"]
        cd_match = match_casedev_to_citation(cd_citations, cite_text)

        if cd_match and cd_match["status"] == "verified" and "case" in cd_match:
            parsed = parse_citation(cite_text)
            cluster = casedev_to_cluster(cd_match["case"])
            vr = verifier._process_citation_lookup_hit(cite_text, parsed, cluster)
            source = "case.dev"
            if vr.status == VerificationStatus.VERIFIED:
                resolved_by_casedev += 1
            else:
                name_mismatches += 1
                source = "case.dev (name mismatch)"
            results.append({"row": row, "result": vr, "source": source, "cd": cd_match})

        elif cd_match and cd_match["status"] == "multiple_matches":
            parsed = parse_citation(cite_text)
            best_vr = None
            for candidate in cd_match.get("candidates", []):
                cluster = casedev_to_cluster(candidate)
                vr = verifier._process_citation_lookup_hit(cite_text, parsed, cluster)
                if vr.status == VerificationStatus.VERIFIED:
                    best_vr = vr
                    break
                if best_vr is None or vr.confidence > best_vr.confidence:
                    best_vr = vr
            if best_vr:
                source = "case.dev (multiple)"
                if best_vr.status == VerificationStatus.VERIFIED:
                    resolved_by_casedev += 1
                else:
                    name_mismatches += 1
                results.append({"row": row, "result": best_vr, "source": source, "cd": cd_match})
            else:
                need_fallback.append(row)

        else:
            need_fallback.append(row)

    print(f"\nResolved by case.dev: {resolved_by_casedev}")
    print(f"Name mismatches caught: {name_mismatches}")
    print(f"Need CL fallback: {len(need_fallback)}")

    # CL fallback
    if need_fallback:
        print(f"\n--- CL fallback for {len(need_fallback)} citations ---")
        t0 = time.time()
        for i, row in enumerate(need_fallback, 1):
            cite_text = row["citation_text"]
            print(f"  [{i}/{len(need_fallback)}] {cite_text[:70]}...")
            vr = verifier.verify(cite_text)
            results.append({"row": row, "result": vr, "source": "CL fallback", "cd": None})
        print(f"  Fallback time: {time.time() - t0:.1f}s")

    # Print results
    print(f"\n{'#':<4} {'Status':<18} {'Source':<25} {'Citation':<55} {'Matched name'}")
    print("-" * 155)

    for i, r in enumerate(results, 1):
        vr = r["result"]
        cite = r["row"]["citation_text"]
        cite_short = (cite[:53] + "..") if len(cite) > 55 else cite
        matched = vr.matched_case_name or ""
        if len(matched) > 50:
            matched = matched[:48] + ".."

        flag = ""
        if vr.status == VerificationStatus.POSSIBLE_MATCH:
            flag = " <-- MISMATCH"
        elif vr.status == VerificationStatus.NOT_FOUND:
            flag = " <-- NOT FOUND"

        print(f"{i:<4} {vr.status.value:<18} {r['source']:<25} {cite_short:<55} {matched}{flag}")

    # Summary
    from collections import Counter
    status_counts = Counter(r["result"].status.value for r in results)
    print(f"\n--- Summary ---")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")
    print(f"  Resolved by case.dev (no CL call): {resolved_by_casedev}")
    print(f"  Name mismatches caught: {name_mismatches}")
    print(f"  CL fallback needed: {len(need_fallback)}")

    # Save
    output = {
        "total": len(results),
        "resolved_by_casedev": resolved_by_casedev,
        "name_mismatches": name_mismatches,
        "fallback_needed": len(need_fallback),
        "status_counts": dict(status_counts),
        "details": [
            {
                "citation": r["row"]["citation_text"],
                "status": r["result"].status.value,
                "confidence": r["result"].confidence,
                "source": r["source"],
                "matched_name": r["result"].matched_case_name,
                "matched_url": r["result"].matched_url,
                "diagnostics": r["result"].diagnostics,
            }
            for r in results
        ],
    }
    outfile = os.path.join(DIR, "waterfall_batch_50.json")
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {outfile}")


if __name__ == "__main__":
    main()
