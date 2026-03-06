"""Test case.dev verify() as first-pass in our verification pipeline.

Runs the waterfall: case.dev verify → name check → CL fallback pipeline.
Compares results against existing ground truth in claims.csv.
"""

import csv
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from citation_verifier import CitationVerifier
from citation_verifier.models import VerificationStatus
from citation_verifier.parser import parse_citation

load_dotenv()

CASEDEV_API_KEY = os.environ["CASEDEV_API_KEY"]
CASEDEV_URL = "https://api.case.dev/legal/v1/verify"
CASEDEV_HEADERS = {
    "Authorization": f"Bearer {CASEDEV_API_KEY}",
    "Content-Type": "application/json",
}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def casedev_verify(text: str) -> dict:
    """Call case.dev verify() with a text block."""
    resp = requests.post(CASEDEV_URL, headers=CASEDEV_HEADERS, json={"text": text})
    resp.raise_for_status()
    return resp.json()


def extract_reporter_key(citation_text: str) -> str | None:
    """Extract the reporter citation for matching case.dev results back."""
    import re
    parsed = parse_citation(citation_text)
    if parsed.volume and parsed.reporter and parsed.page:
        return f"{parsed.volume} {parsed.reporter} {parsed.page}"
    m = re.search(r"(\d{4})[- ]Ohio[- ](\d+)", citation_text)
    if m:
        return f"{m.group(1)} Ohio {m.group(2)}"
    m = re.search(r"(\d{4})\s+WL\s+(\d+)", citation_text)
    if m:
        return f"{m.group(1)} WL {m.group(2)}"
    return None


def casedev_to_cluster(cd_case: dict) -> dict:
    """Convert a case.dev case result to a CL-style cluster dict
    so we can feed it through verifier._process_citation_lookup_hit."""
    return {
        "id": cd_case.get("id"),
        "case_name": cd_case.get("name", ""),
        "absolute_url": cd_case.get("url", ""),
        "date_filed": cd_case.get("dateDecided"),
    }


def run_waterfall(brief_name: str, claims_csv: str):
    """Run the waterfall pipeline and compare against ground truth."""
    print(f"\n{'='*70}")
    print(f"WATERFALL TEST: {brief_name}")
    print(f"{'='*70}")

    # Load ground truth
    with open(claims_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    unique_cites = {}
    for row in rows:
        cite = row["cited_case"]
        if cite not in unique_cites:
            unique_cites[cite] = {
                "gt_status": row.get("cl_status", ""),
                "gt_url": row.get("cl_url", ""),
                "gt_name": row.get("retrieved_case", ""),
            }

    print(f"\nUnique citations: {len(unique_cites)}")

    # Step 0: case.dev verify (batch)
    citation_block = "\n".join(unique_cites.keys())
    print(f"\n--- Step 0: case.dev verify() ---")
    t0 = time.time()
    casedev_result = casedev_verify(citation_block)
    t_casedev = time.time() - t0
    print(f"  Time: {t_casedev:.2f}s")
    print(f"  Summary: {casedev_result.get('summary', {})}")

    # Index case.dev results by normalized citation
    casedev_map = {}
    for cd_cite in casedev_result.get("citations", []):
        casedev_map[cd_cite["normalized"]] = cd_cite

    # Use our verifier for both name checking and fallback
    verifier = CitationVerifier()
    results = {}
    resolved_by_casedev = 0
    casedev_possible_match = 0
    need_fallback = []

    for cite_text in unique_cites:
        key = extract_reporter_key(cite_text)

        # Try to find in case.dev results
        cd_match = None
        if key:
            key_norm = key.replace(".", ". ").replace("  ", " ").strip()
            cd_match = casedev_map.get(key_norm) or casedev_map.get(key)

        if cd_match and cd_match["status"] == "verified" and "case" in cd_match:
            # Feed through verifier's name-matching logic
            parsed = parse_citation(cite_text)
            cluster = casedev_to_cluster(cd_match["case"])
            vr = verifier._process_citation_lookup_hit(cite_text, parsed, cluster)
            results[cite_text] = {
                "source": "case.dev",
                "result": vr,
            }
            if vr.status == VerificationStatus.VERIFIED:
                resolved_by_casedev += 1
            else:
                casedev_possible_match += 1

        elif cd_match and cd_match["status"] == "multiple_matches":
            # Try each candidate through name matching, pick best
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
                results[cite_text] = {"source": "case.dev (multiple)", "result": best_vr}
                if best_vr.status == VerificationStatus.VERIFIED:
                    resolved_by_casedev += 1
                else:
                    casedev_possible_match += 1
            else:
                need_fallback.append(cite_text)

        else:
            # not_found or not matched
            need_fallback.append(cite_text)

    print(f"\n  Resolved by case.dev: {resolved_by_casedev}")
    print(f"  Possible matches (name mismatch): {casedev_possible_match}")
    print(f"  Need CL fallback: {len(need_fallback)}")

    # Fallback to our full pipeline
    t_fallback = 0
    if need_fallback:
        print(f"\n--- Steps 1-3: CL fallback for {len(need_fallback)} citations ---")
        t1 = time.time()
        for i, cite_text in enumerate(need_fallback, 1):
            print(f"  [{i}/{len(need_fallback)}] {cite_text[:60]}...")
            vr = verifier.verify(cite_text)
            results[cite_text] = {"source": "CL fallback", "result": vr}
        t_fallback = time.time() - t1
        print(f"  Fallback time: {t_fallback:.2f}s")

    # Compare against ground truth
    print(f"\n--- Comparison ---")
    print(f"{'Citation':<50} {'Ground Truth':<18} {'Waterfall':<18} {'Source':<22} {'Match?'}")
    print("-" * 115)

    status_matches = 0
    url_matches = 0
    for cite_text, gt in unique_cites.items():
        wf = results.get(cite_text, {})
        vr = wf.get("result")

        # Normalize ground truth status
        gt_raw = gt["gt_status"]
        if "VERIFIED" in gt_raw or "LIKELY_REAL" in gt_raw:
            gt_norm = "VERIFIED"
        elif "POSSIBLE_MATCH" in gt_raw:
            gt_norm = "POSSIBLE_MATCH"
        elif "NOT_FOUND" in gt_raw:
            gt_norm = "NOT_FOUND"
        else:
            gt_norm = gt_raw

        wf_status = vr.status.value if vr else "MISSING"
        wf_norm = "VERIFIED" if wf_status == "LIKELY_REAL" else wf_status

        same_status = gt_norm == wf_norm
        if same_status:
            status_matches += 1

        # URL comparison
        same_url = False
        if vr and vr.matched_url and gt["gt_url"]:
            same_url = vr.matched_url.rstrip("/") == gt["gt_url"].rstrip("/")
            if same_url:
                url_matches += 1

        cite_short = (cite_text[:48] + "..") if len(cite_text) > 50 else cite_text
        flag = "YES" if same_status else "NO <<<"
        print(f"{cite_short:<50} {gt_norm:<18} {wf_status:<18} {wf.get('source','?'):<22} {flag}")

    total = len(unique_cites)
    print(f"\n--- Summary ---")
    print(f"  Total unique citations:    {total}")
    print(f"  Status matches:            {status_matches}/{total} ({status_matches/total*100:.0f}%)")
    print(f"  URL matches:               {url_matches}/{total}")
    print(f"  Resolved by case.dev:      {resolved_by_casedev} ({resolved_by_casedev/total*100:.0f}%)")
    print(f"  Name mismatches caught:    {casedev_possible_match}")
    print(f"  CL fallback calls:         {len(need_fallback)}")
    print(f"  CL calls saved:            ~{resolved_by_casedev + casedev_possible_match}")
    print(f"  case.dev time:             {t_casedev:.2f}s")
    print(f"  CL fallback time:          {t_fallback:.2f}s")
    print(f"  Total time:                {t_casedev + t_fallback:.2f}s")

    # Save
    output = {
        "brief": brief_name,
        "total": total,
        "resolved_by_casedev": resolved_by_casedev,
        "casedev_possible_match": casedev_possible_match,
        "fallback_needed": len(need_fallback),
        "status_matches": status_matches,
        "url_matches": url_matches,
        "casedev_time_s": round(t_casedev, 2),
        "fallback_time_s": round(t_fallback, 2),
    }
    outfile = os.path.join(OUTPUT_DIR, f"waterfall_{brief_name.lower().replace(' ', '_')}.json")
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {outfile}")


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "..", "..")

    run_waterfall(
        "kettering",
        os.path.join(base, "briefs", "kettering-v-collier", "claims.csv"),
    )

    run_waterfall(
        "valve",
        os.path.join(base, "briefs", "Valve v Rothschild", "claims.csv"),
    )
