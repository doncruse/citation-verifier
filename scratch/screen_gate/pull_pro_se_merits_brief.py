"""Custom vetting loop for pro_se__merits_brief (Task 4c).

pull_cell.py's bare query ("response in opposition to motion to dismiss")
surfaces almost entirely "In re" subpoena-compliance / discovery-dispute misc
actions (confirmed in a live run: 11/11 results were In re/misc). This script:

1. Searches RECAP with --no-require-firm across several query variants aimed
   at self-represented plaintiffs opposing dispositive motions.
2. Excludes non-representative captions (In re / In the Matter of / Complaint
   of / standalone subpoena or compliance misc actions).
3. Classifies candidate documents to merits_brief via classify_doctype.
4. Sanction-screens the docket.
5. Downloads the actual document text and vets it for a pro se signature
   marker, rejecting anything with an "Attorney for" / counsel signature
   block (RECAP's firm/attorney fields describe the case, not the filer).
6. Saves accepted docs + appends manifest rows, with notes recording the
   pro se marker found.
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

CELL = "pro_se__merits_brief"
CELL_DIR = os.path.join(_HERE, "baseline", CELL)
FILED_AFTER = "2023-01-01"
MIN_CHARS = 3500
TARGET = 10

QUERIES = [
    "response in opposition to motion to dismiss",
    "opposition to motion for summary judgment",
    "plaintiff's response in opposition to defendants' motion to dismiss",
    "pro se plaintiff opposition motion to dismiss",
    "memorandum in opposition to motion to dismiss pro se",
    "response to motion for summary judgment pro se plaintiff",
    "plaintiff pro se response in opposition",
    "pro se opposition to defendants motion for summary judgment",
    "response in opposition to defendants motion to dismiss civil rights",
]

_EXCLUDE_CAPTION_RE = re.compile(
    r"^\s*(in re\b|in the matter of\b|complaint of\b)", re.IGNORECASE
)
_EXCLUDE_MISC_TERMS = ["subpoena", "compliance", "motion to quash", "motion to compel compliance"]

# Document-title markers that indicate this is a COURT-authored document
# (report and recommendation, order, clerk's notice) rather than a party's
# own brief -- reject these even if "pro se" appears (it often does, in
# court-generated "Notice to Pro Se Litigant" form notices).
_COURT_DOC_TITLE_RE = re.compile(
    r"(report\s+and\s+recommendation|^\s*order\b|memorandum\s+opinion\s+and\s+order|"
    r"notice\s+to\s+pro\s+se\s+litigant|magistrate\s+judge.{0,20}recommend)",
    re.IGNORECASE,
)

# Pro se signature / filer markers to look for in the actual document text.
_PRO_SE_MARKERS = [
    re.compile(r"pro\s+se", re.IGNORECASE),
    re.compile(r"appearing\s+pro\s+se", re.IGNORECASE),
    re.compile(r"self[-\s]represented", re.IGNORECASE),
    re.compile(r"plaintiff,?\s+pro\s+se", re.IGNORECASE),
]
_COUNSEL_SIGNATURE_RE = re.compile(
    r"(attorney[s]?\s+for\s+(plaintiff|defendant)|counsel\s+for\s+(plaintiff|defendant)|"
    r"bar\s+no\.?\s*\d+|state\s+bar\s+number|pro\s+hac\s+vice|law\s+(firm|offices?|group|llc|llp|pc)\b)",
    re.IGNORECASE,
)


def excluded_caption(case_name: str) -> bool:
    if not case_name:
        return True
    if _EXCLUDE_CAPTION_RE.search(case_name):
        return True
    lowered = case_name.lower()
    if any(term in lowered for term in _EXCLUDE_MISC_TERMS):
        return True
    return False


def vet_pro_se_text(text: str) -> tuple[bool, str]:
    """Return (is_pro_se, reason).

    Rejects outright if the document's title (first ~1200 chars, where the
    caption + title block live) marks it as a COURT-authored document
    (Report & Recommendation, Order, clerk's "Notice to Pro Se Litigant") --
    those are never the filer's own brief, even though they often contain
    the phrase "pro se" as boilerplate.

    Otherwise requires a pro se marker in the signature-block tail (where a
    self-represented filer signs "Pro Se Plaintiff" / "appearing pro se")
    AND rejects if a counsel/attorney signature block (bar number, "Attorney
    for", "pro hac vice", law-firm name) is found in that same tail -- that
    indicates the document was actually filed by counsel (either for this
    party, or the "pro se" phrase belongs to boilerplate/other-party text
    elsewhere in the document, not this filer's signature)."""
    if not text:
        return False, "empty text"

    head = text[:1200]
    if _COURT_DOC_TITLE_RE.search(head):
        return False, "court-authored document (R&R/Order/clerk notice), not a party brief"

    tail = text[-3000:]
    has_pro_se_tail = any(p.search(tail) for p in _PRO_SE_MARKERS)
    has_counsel_tail = _COUNSEL_SIGNATURE_RE.search(tail)

    if has_counsel_tail:
        return False, "counsel/attorney signature block found in signature area"
    if has_pro_se_tail:
        return True, "pro se marker in signature-block area"
    return False, "no pro se marker in signature-block area"


async def search_available(client, q, page):
    params = {"type": "r", "available_only": "on", "q": q,
              "filed_after": FILED_AFTER, "page": str(page)}
    data = await client._request_with_retry(
        "GET", f"{client.BASE_URL}/search/", params=params)
    return data.get("results", [])


# Docket ids manually confirmed BAD in first-pass human review (court-authored
# docs or attorney-filed docs that false-positived on a "pro se" substring
# elsewhere in the text) -- never re-accept these even if re-surfaced.
_MANUAL_REJECT_DOCKETS = {
    70683669,  # Bailey v. East Greenville Summary Court -- Report & Recommendation
    70593746,  # Benkirane v. Magellan Healthcare -- clerk "Notice to Pro Se Litigant"
    68029706,  # Chacon v. State Board for Community College -- court Order
    68061565,  # City of Warren General Employees' System -- attorney class action
    69953933,  # Rodney Grubbs adversary proceeding -- attorney-signed (Mulvey Law LLC)
    67641172,  # Waterman v. Harred -- clerk notice + defense counsel signature
}


def load_existing_manifest():
    man = Path(CELL_DIR, f"manifest-{CELL}.jsonl")
    rows = []
    if man.exists():
        for line in man.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def main():
    from pull_cell import load_token
    os.makedirs(CELL_DIR, exist_ok=True)
    saved = load_existing_manifest()
    seen_dockets = set(_MANUAL_REJECT_DOCKETS) | {row["docket_id"] for row in saved}
    rejected_log = []
    print(f"Starting from {len(saved)} already-accepted docs: "
          f"{[r['slug'] for r in saved]}")

    async with AsyncCourtListenerClient(load_token()) as client:
        for query in QUERIES:
            if len(saved) >= TARGET:
                break
            page = 1
            while len(saved) < TARGET and page <= 6:
                try:
                    results = await search_available(client, query, page)
                except Exception as e:
                    print(f"  [search error] {query!r} page {page}: {e}")
                    break
                page += 1
                if not results:
                    break
                for r in results:
                    if len(saved) >= TARGET:
                        break
                    did = r.get("docket_id")
                    if did in seen_dockets:
                        continue
                    case_name = r.get("caseName", "")
                    if excluded_caption(case_name):
                        continue
                    cand = next(
                        (d for d in (r.get("recap_documents") or [])
                         if d.get("is_available")
                         and classify_doctype(d.get("description", "")) == "merits_brief"),
                        None,
                    )
                    if not cand:
                        continue
                    seen_dockets.add(did)
                    try:
                        entries = await client.get_docket_entries(did)
                    except Exception as e:
                        print(f"  [docket-entries error] {did}: {e}")
                        continue
                    hits = sanction_hits([e.get("description", "") for e in entries])
                    if hits:
                        rejected_log.append((case_name, "sanction hit: " + ",".join(hits)))
                        continue

                    url = f"https://www.courtlistener.com/docket/{did}/{cand.get('document_number')}/"
                    try:
                        data = await client.get_opinion_text_with_metadata(url)
                    except Exception as e:
                        print(f"  [fetch error] {did}: {e}")
                        continue
                    if not data or not data.get("text"):
                        continue
                    text = data["text"]
                    if len(text) < MIN_CHARS:
                        rejected_log.append((case_name, f"too short ({len(text)} chars)"))
                        continue

                    is_pro_se, reason = vet_pro_se_text(text)
                    if not is_pro_se:
                        rejected_log.append((case_name, f"filer vet failed: {reason}"))
                        print(f"  REJECT {case_name[:60]:60s} - {reason}")
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
                        doc_type="merits_brief",
                        recap_url=url,
                        is_available=True,
                        sanction_screen="clean",
                        notes=f"{case_name[:60]}; firm={firm0}; pages={cand.get('page_count')}; "
                              f"pro_se_vet={reason}",
                    )
                    saved.append(row)
                    print(f"  ACCEPT {slug[:44]:44s} court={row['court']:6s} "
                          f"doc#{row['document_number']} ({reason})")

    man = Path(CELL_DIR, f"manifest-{CELL}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{CELL}: saved {len(saved)}/{TARGET}")
    print(f"Rejected {len(rejected_log)} candidates:")
    for name, reason in rejected_log:
        print(f"  - {name[:60]:60s} : {reason}")


if __name__ == "__main__":
    asyncio.run(main())
