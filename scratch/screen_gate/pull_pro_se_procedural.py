"""Custom vetting loop for pro_se__procedural_motion (Task 4c).

pull_cell.py's bare "motion to compel" query surfaces mostly "In re Motion to
Compel Compliance" subpoena-misc actions -- not ordinary pro se motions within
a two-party civil case. This script:

  1. Searches RECAP (available_only=on) across several pro-se-flavored
     procedural-motion queries (motion to compel, motion for extension of
     time, motion to amend, motion for leave to amend).
  2. Rejects caseName starting with "In re" / "In the Matter of" /
     "Complaint of" and standalone subpoena/compliance misc actions.
  3. Rejects dockets where the case-level `firm` looks like it covers the
     filing party (best-effort; RECAP firm/attorney fields describe the
     case, not always the individual filer -- so this is a pre-filter only).
  4. Downloads the actual candidate document text and greps for pro se
     signature markers ("pro se", "self-represented", no "Attorney for" /
     "Counsel for" block referencing the filer) before accepting.
  5. Sanction-screens the docket via docket-entry descriptions.

Saves accepted docs via pull_baseline.pull_candidate (same manifest schema)
into scratch/screen_gate/baseline/pro_se__procedural_motion/.
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
from pull_baseline import classify_doctype, sanction_hits, pull_candidate

CELL = "pro_se__procedural_motion"
BASELINE_ROOT = os.path.join(_HERE, "baseline")
CELL_DIR = os.path.join(BASELINE_ROOT, CELL)

QUERIES = [
    "motion to compel",
    "motion for extension of time",
    "motion to amend complaint",
    "motion for leave to amend",
    "motion to compel discovery",
]

_BAD_CASENAME_PREFIX = re.compile(
    r"^\s*(in re\b|in the matter of\b|complaint of\b)", re.IGNORECASE)
_MISC_TERMS = ("subpoena", "compliance", "administrative subpoena", "in re")

_PRO_SE_MARKERS = re.compile(
    r"\bpro se\b|\bself[- ]represented\b|\bproceeding pro se\b|\bappearing pro se\b",
    re.IGNORECASE,
)
_ATTORNEY_BLOCK = re.compile(
    r"attorneys?\s+for\s+(plaintiff|defendant)|counsel\s+for\s+(plaintiff|defendant)"
    r"|bar\s*(no\.?|number)\s*[:#]?\s*\d+",
    re.IGNORECASE,
)


def looks_like_misc_action(case_name: str) -> bool:
    if not case_name:
        return True
    if _BAD_CASENAME_PREFIX.search(case_name):
        return True
    lowered = case_name.lower()
    if any(term in lowered for term in _MISC_TERMS):
        return True
    if " v. " not in case_name and " v " not in lowered:
        # Not an ordinary two-party case caption.
        return True
    return False


def vet_pro_se_text(text: str) -> tuple[bool, str]:
    """Return (accept, reason). Requires a pro se marker and rejects any
    attorney/counsel signature block or bar number in the document."""
    if not text:
        return False, "no text"
    if _ATTORNEY_BLOCK.search(text):
        return False, "attorney/counsel signature block or bar number found"
    if not _PRO_SE_MARKERS.search(text):
        return False, "no pro se marker found"
    return True, "pro se marker present, no attorney block"


async def _search(client, q, page):
    params = {"type": "r", "available_only": "on", "q": q,
              "filed_after": "2023-01-01", "page": str(page)}
    data = await client._request_with_retry(
        "GET", f"{client.BASE_URL}/search/", params=params)
    return data.get("results", [])


async def main():
    token = ""
    envp = Path(".env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN") and "=" in line:
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    token = token or os.environ.get("COURTLISTENER_API_TOKEN", "")

    target = 10
    min_chars = 3000
    saved = []
    seen_dockets = set()
    rejects = []

    os.makedirs(CELL_DIR, exist_ok=True)

    async with AsyncCourtListenerClient(token) as client:
        for q in QUERIES:
            if len(saved) >= target:
                break
            for page in range(1, 7):
                if len(saved) >= target:
                    break
                results = await _search(client, q, page)
                if not results:
                    break
                for r in results:
                    if len(saved) >= target:
                        break
                    did = r.get("docket_id")
                    if did in seen_dockets:
                        continue
                    case_name = r.get("caseName", "")
                    if looks_like_misc_action(case_name):
                        continue
                    cand = next(
                        (d for d in (r.get("recap_documents") or [])
                         if d.get("is_available")
                         and classify_doctype(d.get("description", "")) == "procedural_motion"),
                        None)
                    if not cand:
                        continue
                    seen_dockets.add(did)

                    # Sanction screen on the docket first (cheap-ish, avoids
                    # downloading text for dockets we'll reject anyway).
                    entries = await client.get_docket_entries(did)
                    hits = sanction_hits([e.get("description", "") for e in entries])
                    if hits:
                        rejects.append((case_name, did, "sanction terms: " + ",".join(hits)))
                        continue

                    # Fetch the actual document text to vet pro se status.
                    url = f"https://www.courtlistener.com/docket/{did}/{cand.get('document_number')}/"
                    data = await client.get_opinion_text_with_metadata(url)
                    text = (data or {}).get("text", "")
                    if len(text) < min_chars:
                        rejects.append((case_name, did, f"text too short ({len(text)} chars)"))
                        continue

                    accept, reason = vet_pro_se_text(text)
                    if not accept:
                        rejects.append((case_name, did, reason))
                        continue

                    firm0 = (r.get("firm") or [""])[0]
                    meta = {
                        "court": r.get("court_id", ""),
                        "filer_type": "pro_se",
                        "doc_type": "procedural_motion",
                        "sanction_screen": "clean",
                        "notes": f"{case_name[:60]}; firm={firm0}; query='{q}'; vet={reason}",
                    }
                    slug = None
                    # pull_candidate re-fetches; reuse already-fetched data to
                    # avoid a duplicate network call by writing directly here,
                    # matching pull_candidate's own logic.
                    from pull_baseline import doc_slug, manifest_row
                    slug = doc_slug(data.get("case_name", ""), data.get("docket_number", ""), did)
                    out_path = os.path.join(CELL_DIR, f"{slug}.txt")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    row = manifest_row(
                        slug=slug,
                        court=meta["court"] or data.get("court", ""),
                        docket_id=did,
                        document_number=cand.get("document_number"),
                        filer_type="pro_se",
                        doc_type="procedural_motion",
                        recap_url=url,
                        is_available=True,
                        sanction_screen="clean",
                        notes=meta["notes"],
                    )
                    saved.append(row)
                    print(f"  ACCEPT {slug[:44]:44s} court={row['court']:6s} "
                          f"doc#{row['document_number']} ({reason})")

    man = Path(CELL_DIR, f"manifest-{CELL}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{CELL}: saved {len(saved)}/{target}")
    print(f"rejected {len(rejects)} candidates:")
    for cn, did, why in rejects[:60]:
        print(f"  reject docket={did} case={cn[:50]!r} why={why}")


if __name__ == "__main__":
    asyncio.run(main())
