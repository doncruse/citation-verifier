"""Custom curation loop for the pro_se__pleading baseline cell (Task 4c).

pull_cell.py's require_firm=False alone isn't enough for pro se cells: RECAP
search firm/attorney fields describe the CASE, not necessarily the individual
filer, and bare complaint queries surface admiralty/"In re" outliers (see
task-4c-brief.md). This script:

1. Searches RECAP (available_only=on) across several pro-se-flavored queries.
2. Dedups by docket.
3. Rejects admiralty/MDL/misc captions ("In re", "In the Matter of",
   "Complaint of", "Petition of") -- want ordinary two-party "X v. Y" cases.
4. Picks the best-matching available document classifying as `pleading`.
5. Sanction-screens the docket (skip if any hit).
6. Downloads the actual document text and vets it for a pro se signature
   marker (regex over the last ~2000 chars, where signature blocks live),
   rejecting anything with an "Attorney for Plaintiff" / bar-number block.
7. Saves accepted docs + manifest rows.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from citation_verifier.client import AsyncCourtListenerClient
from pull_baseline import classify_doctype, sanction_hits, doc_slug, manifest_row

CELL = "pro_se__pleading"
BASELINE_ROOT = os.path.join(_HERE, "baseline")
CELL_DIR = os.path.join(BASELINE_ROOT, CELL)
TARGET = 10
MIN_CHARS = 3000
FILED_AFTER = "2023-01-01"

QUERIES = [
    "civil rights complaint pro se",
    "pro se complaint",
    "complaint pro se plaintiff",
    "civil rights complaint",
]

_EXCLUDE_CAPTION_RE = re.compile(
    r"^\s*(in re\b|in the matter of\b|complaint of\b|petition of\b)",
    re.IGNORECASE,
)

# Pro se markers: look for these near the end of the doc (signature block).
_PRO_SE_MARKERS = re.compile(
    r"\bpro\s*se\b|\bappearing\s+pro\s*se\b|\bself[-\s]represented\b|\bplaintiff,?\s*pro\s*se\b",
    re.IGNORECASE,
)
_ATTORNEY_MARKERS = re.compile(
    r"attorney[s]?\s+for\s+(plaintiff|defendant)|counsel\s+for\s+(plaintiff|defendant)"
    r"|bar\s*(no\.?|number|#)\s*[:#]?\s*\d|state\s+bar\s+no|esq\.?\b",
    re.IGNORECASE,
)


def load_token() -> str:
    env = Path(".env")
    if not env.exists():
        return os.environ.get("COURTLISTENER_API_TOKEN", "")
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("COURTLISTENER_API_TOKEN") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("COURTLISTENER_API_TOKEN", "")


async def _search_available(client, q, filed_after, page):
    params = {"type": "r", "available_only": "on", "q": q,
              "filed_after": filed_after, "page": str(page)}
    data = await client._request_with_retry(
        "GET", f"{client.BASE_URL}/search/", params=params)
    return data.get("results", [])


def vet_pro_se_text(text: str) -> tuple[bool, str]:
    """Check the tail of the document for pro se signature markers and
    reject if an attorney signature block is present. Returns (ok, reason)."""
    tail = text[-3000:]
    has_attorney = bool(_ATTORNEY_MARKERS.search(tail))
    has_pro_se = bool(_PRO_SE_MARKERS.search(tail)) or bool(_PRO_SE_MARKERS.search(text))
    if has_attorney:
        return False, "attorney signature block found in tail"
    if not has_pro_se:
        return False, "no pro se marker found"
    return True, "pro se marker confirmed, no attorney block"


async def main():
    async with AsyncCourtListenerClient(load_token()) as client:
        os.makedirs(CELL_DIR, exist_ok=True)
        saved = []
        seen_dockets = set()
        rejected_log = []

        for query in QUERIES:
            if len(saved) >= TARGET:
                break
            page = 1
            while len(saved) < TARGET and page <= 6:
                results = await _search_available(client, query, FILED_AFTER, page)
                page += 1
                if not results:
                    break
                for r in results:
                    if len(saved) >= TARGET:
                        break
                    did = r.get("docket_id")
                    if did in seen_dockets:
                        continue
                    case_name = r.get("caseName", "") or ""
                    if _EXCLUDE_CAPTION_RE.match(case_name):
                        seen_dockets.add(did)
                        rejected_log.append((case_name, "admiralty/misc caption"))
                        continue
                    if " v. " not in case_name and " v " not in case_name:
                        # Not an ordinary two-party case; skip (petitions, in-re, etc.)
                        seen_dockets.add(did)
                        rejected_log.append((case_name, "not two-party X v. Y"))
                        continue

                    cand = next(
                        (d for d in (r.get("recap_documents") or [])
                         if d.get("is_available")
                         and classify_doctype(d.get("description", "")) == "pleading"),
                        None,
                    )
                    if not cand:
                        continue

                    seen_dockets.add(did)

                    entries = await client.get_docket_entries(did)
                    hits = sanction_hits([e.get("description", "") for e in entries])
                    if hits:
                        rejected_log.append((case_name, f"sanction hits: {hits}"))
                        continue

                    # Fetch actual text to vet for pro se signature.
                    url = f"https://www.courtlistener.com/docket/{did}/{cand.get('document_number')}/"
                    data = await client.get_opinion_text_with_metadata(url)
                    if not data or not data.get("text"):
                        rejected_log.append((case_name, "no text"))
                        continue
                    text = data["text"]
                    if len(text) < MIN_CHARS:
                        rejected_log.append((case_name, f"too short ({len(text)} chars)"))
                        continue

                    ok, reason = vet_pro_se_text(text)
                    if not ok:
                        rejected_log.append((case_name, f"filer vet failed: {reason}"))
                        print(f"  REJECT {case_name[:60]:60s} -- {reason}")
                        continue

                    slug = doc_slug(data.get("case_name", "") or case_name,
                                     data.get("docket_number", ""), did)
                    out_path = os.path.join(CELL_DIR, f"{slug}.txt")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(text)

                    firm0 = (r.get("firm") or [""])[0]
                    row = manifest_row(
                        slug=slug,
                        court=r.get("court_id", "") or data.get("court", ""),
                        docket_id=did,
                        document_number=cand.get("document_number"),
                        filer_type="pro_se",
                        doc_type="pleading",
                        recap_url=url,
                        is_available=True,
                        sanction_screen="clean",
                        notes=(f"{case_name[:60]}; case-level firm={firm0}; "
                               f"pages={cand.get('page_count')}; vet={reason}"),
                    )
                    saved.append(row)
                    print(f"  ACCEPT {row['slug'][:44]:44s} court={row['court']:6s} "
                          f"doc#{row['document_number']}  ({reason})")

        man = Path(CELL_DIR, f"manifest-{CELL}.jsonl")
        with man.open("w", encoding="utf-8") as fh:
            for row in saved:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        print(f"\n{CELL}: saved {len(saved)}/{TARGET}")
        print(f"Rejected {len(rejected_log)} candidates.")
        return saved, rejected_log


if __name__ == "__main__":
    asyncio.run(main())
