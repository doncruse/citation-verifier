"""Verify citations from law-firm EOS appeal brief and download opinion texts.

Uses verify_batch() for efficient bulk citation lookup (single API call),
with fallback to opinion search + RECAP only for misses.
"""

import asyncio
import csv
import re
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from citation_verifier import CitationVerifier
from citation_verifier.client import CourtListenerClient
from citation_verifier.models import VerificationStatus

BRIEF_DIR = PROJECT_ROOT / "briefs" / "law-firm-eos-appeal"
OPINIONS_DIR = BRIEF_DIR / "opinions"
RESULTS_CSV = BRIEF_DIR / "verification_results.csv"
CITATIONS_FILE = BRIEF_DIR / "citations_to_verify.txt"

OPINIONS_DIR.mkdir(exist_ok=True)


def load_citations() -> list[str]:
    """Load citations from citations_to_verify.txt."""
    return [
        line.strip()
        for line in CITATIONS_FILE.read_text().splitlines()
        if line.strip()
    ]


def sanitize_filename(name: str) -> str:
    """Convert a case name to a safe filename."""
    match = re.match(r"^(.+?),\s*\d+", name)
    case_name = match.group(1) if match else name
    case_name = case_name.replace("\u2019", "").replace("'", "")
    case_name = re.sub(r"[^\w\s\-]", "", case_name)
    case_name = re.sub(r"\s+", "_", case_name.strip())
    return case_name[:80] + ".txt"


def progress(completed: int, total: int) -> None:
    print(f"  [{completed}/{total}] verified", flush=True)


async def verify_all(citations: list[str]) -> list:
    """Batch-verify all citations."""
    verifier = CitationVerifier()
    print(f"Verifying {len(citations)} citations (batch mode)...\n", flush=True)
    results = await verifier.verify_batch(
        citations, progress_callback=progress
    )
    return results


def main():
    citations = load_citations()
    results = asyncio.run(verify_all(citations))

    # Build CSV rows and identify downloads
    rows = []
    verified_cases = []
    for citation, result in zip(citations, results):
        status = result.status.value
        url = result.matched_url or ""
        cluster_id = result.matched_cluster_id or ""
        confidence = result.confidence
        matched_name = result.matched_case_name or ""
        diagnostics = "; ".join(
            d.message for d in result.diagnostics
        ) if result.diagnostics else ""

        rows.append({
            "citation": citation,
            "status": status,
            "confidence": confidence,
            "cluster_id": cluster_id,
            "url": url,
            "matched_name": matched_name,
            "diagnostics": diagnostics,
        })

        if status in ("VERIFIED", "LIKELY_REAL") and url:
            filename = sanitize_filename(citation)
            verified_cases.append((citation, url, cluster_id, filename))

    # Write results CSV
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "citation", "status", "confidence", "cluster_id", "url",
            "matched_name", "diagnostics",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nResults saved to {RESULTS_CSV}", flush=True)

    # Summary
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print(f"\nSummary: {statuses}")
    print(f"Verified/Likely Real: {len(verified_cases)} cases to download\n",
          flush=True)

    # Download opinion texts
    client = CourtListenerClient()
    for i, (citation, url, cluster_id, filename) in enumerate(verified_cases, 1):
        filepath = OPINIONS_DIR / filename
        if filepath.exists():
            print(f"[{i:2d}/{len(verified_cases)}] SKIP (exists): {filename}",
                  flush=True)
            continue

        print(f"[{i:2d}/{len(verified_cases)}] Downloading: {filename}",
              flush=True)
        try:
            text = client.get_opinion_text(url)
            if text:
                filepath.write_text(text, encoding="utf-8")
                print(f"         -> Saved ({len(text):,} chars)", flush=True)
            else:
                print(f"         -> No text available", flush=True)
        except Exception as e:
            print(f"         -> Download error: {e}", flush=True)

    print(f"\nDone. Opinions saved to {OPINIONS_DIR}", flush=True)


if __name__ == "__main__":
    main()
