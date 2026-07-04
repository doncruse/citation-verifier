"""Task 4c, round 2: targeted candidate list built from manual query
reconnaissance (bare 'motion to compel' surfaced almost entirely admiralty/misc
"In re" subpoena actions and attorney-filed motions -- see round-1 rejects).

Candidates below were found via queries whose RECAP descriptions explicitly
begin "Pro Se MOTION..." / "PRO SE MOTION..." naming an individual filer --
i.e. the docket-entry text itself asserts pro se status, which is then
confirmed by downloading and reading the actual document (attorney/bar-number
signature block => reject; no "pro se"/self-represented marker => reject).

Excludes: United States v. * (criminal cases -- want ordinary civil), In re /
admiralty/misc actions, and "All Pro 2, LLC v. Riding" (an IFP/removal notice,
not a procedural motion in the discovery/amend/extension sense).
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
from pull_baseline import sanction_hits, doc_slug, manifest_row

CELL = "pro_se__procedural_motion"
BASELINE_ROOT = os.path.join(_HERE, "baseline")
CELL_DIR = os.path.join(BASELINE_ROOT, CELL)

CANDIDATES = [
    # (docket_id, doc_num, case_name, court, source_desc)
    (69852808, 15, "McClanahan v. Trump", "mowd",
     "PRO SE MOTION to compel expedited service of process filed by Darrell Leon McClanahan, III."),
    (71978421, 7, "Flenoid v. Henry's Towing Service, LLC", "mowd",
     "PRO SE MOTION to Compel Recognition filed by Larry LexxLou Flenoid, II."),
    (71978421, 6, "Flenoid v. Henry's Towing Service, LLC", "mowd",
     "PRO SE MOTION to Compel Insurance and Indemnification Disclosures, MOTION for Leave to File Second Amended Complaint filed by Larry LexxLou Flenoid, II."),
    (67686939, 45, "McKee v. City of Columbia Missouri", "mowd",
     "PRO SE MOTION for leave to file Amended Complaint and Petition for Damages filed by Doressia T McKee."),
    (69796161, 21, "Frazier IV v. Jones", "iand",
     "PRO SE MOTION for Leave to File an Amended Complaint by Plaintiff Billy DeWayne Frazier, IV."),
    (68551918, 8, "Day v. DeVries", "mowd",
     "PRO SE MOTION for summary judgment filed by James C. Day."),  # likely merits_brief-adjacent; vet doctype too
    (67756069, 137, "Kyndryl, Inc. v. Cannady", "mowd",
     "PRO SE MOTION to Unseal Case and MOTION to Remove TRO filed by Vincent Cannady."),
    (70451268, 14, "Burgoon v. Martin", "mowd",
     "PRO SE MOTION for leave to file a response to defendant's motion to dismiss out of time filed by Melinda J Burgoon."),
    (68069953, 49, "Preston v. Virginia Community College System", "vawd",
     "Pro Se MOTION for Extension of Time to Obtain Counsel by Elmer T. Preston."),
    (69228719, 9, "The Service Companies, Inc. v. Barajas", "txed",
     "Pro Se MOTION for Extension of Time to File Answer re 1 Complaint by Norma L. Barajas."),
    (69375678, 29, "Robinson v. Jackson", "ncwd",
     "Pro Se MOTION for Extension of Time to Answer by Alysse Hyatt."),
    (69375678, 28, "Robinson v. Jackson", "ncwd",
     "Pro Se MOTION for Extension of Time to Answer by Wenter Donovan."),
    (69224132, 107, "Barry White Family Trust v. Cooley", "nysd",
     "PRO SE MOTION FROM DEFENDANT JOE COOLEY REQUESTING JUDICIAL NOTICE AND RULE-BASED RELIEF."),
]

_ATTORNEY_BLOCK = re.compile(
    r"attorneys?\s+for\s+(plaintiff|defendant)|counsel\s+for\s+(plaintiff|defendant)"
    r"|bar\s*(no\.?|number)\s*[:#]?\s*\d+",
    re.IGNORECASE,
)
_PRO_SE_MARKERS = re.compile(
    r"\bpro se\b|\bself[- ]represented\b|\bproceeding pro se\b|\bappearing pro se\b|\bPlaintiff,?\s*Pro Se\b",
    re.IGNORECASE,
)


def vet_pro_se_text(text: str) -> tuple[bool, str]:
    if not text:
        return False, "no text"
    atty = _ATTORNEY_BLOCK.search(text)
    if atty:
        # Could be a reference to opposing counsel; only reject if it looks
        # like the filer's own signature block (heuristic: within last 800
        # chars of the document, near a signature).
        tail = text[-1200:]
        if _ATTORNEY_BLOCK.search(tail):
            return False, f"attorney/counsel block near signature: {atty.group(0)!r}"
    if not _PRO_SE_MARKERS.search(text):
        return False, "no pro se marker found anywhere in text"
    return True, "pro se marker present; no attorney signature block at end"


async def main():
    token = ""
    envp = Path(".env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN") and "=" in line:
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    token = token or os.environ.get("COURTLISTENER_API_TOKEN", "")

    min_chars = 3000
    saved = []
    rejects = []
    os.makedirs(CELL_DIR, exist_ok=True)

    async with AsyncCourtListenerClient(token) as client:
        for docket_id, doc_num, case_name, court, src_desc in CANDIDATES:
            entries = await client.get_docket_entries(docket_id)
            hits = sanction_hits([e.get("description", "") for e in entries])
            if hits:
                rejects.append((case_name, docket_id, "sanction terms: " + ",".join(hits)))
                continue

            url = f"https://www.courtlistener.com/docket/{docket_id}/{doc_num}/"
            data = await client.get_opinion_text_with_metadata(url)
            text = (data or {}).get("text", "")
            if len(text) < min_chars:
                rejects.append((case_name, docket_id, f"text too short ({len(text)} chars)"))
                continue

            accept, reason = vet_pro_se_text(text)
            if not accept:
                rejects.append((case_name, docket_id, reason))
                continue

            slug = doc_slug(data.get("case_name", "") or case_name, data.get("docket_number", ""), docket_id)
            out_path = os.path.join(CELL_DIR, f"{slug}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
            row = manifest_row(
                slug=slug,
                court=court or data.get("court", ""),
                docket_id=docket_id,
                document_number=doc_num,
                filer_type="pro_se",
                doc_type="procedural_motion",
                recap_url=url,
                is_available=True,
                sanction_screen="clean",
                notes=f"{case_name[:60]}; src_desc={src_desc[:80]}; vet={reason}",
            )
            saved.append(row)
            print(f"  ACCEPT {slug[:50]:50s} court={row['court']:6s} doc#{doc_num} ({reason})")

    man = Path(CELL_DIR, f"manifest-{CELL}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{CELL}: saved {len(saved)}/{len(CANDIDATES)} candidates tried")
    print(f"rejected {len(rejects)}:")
    for cn, did, why in rejects:
        print(f"  reject docket={did} case={cn[:50]!r} why={why}")


if __name__ == "__main__":
    asyncio.run(main())
