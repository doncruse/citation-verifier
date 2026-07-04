"""Task 4c final save step: write the 3 additional vetted candidates
(Preston, Barajas, Robinson/Hyatt) alongside the already-saved McClanahan doc.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from citation_verifier.client import AsyncCourtListenerClient
from pull_baseline import doc_slug, manifest_row

CELL_DIR = os.path.join(_HERE, "baseline", "pro_se__procedural_motion")

CANDIDATES = [
    (68069953, 49, "Preston v. Virginia Community College System", "vawd",
     "Pro Se MOTION for Extension of Time to Obtain Counsel by Elmer T. Preston."),
    (69228719, 9, "The Service Companies, Inc. v. Barajas", "txed",
     "Pro Se MOTION for Extension of Time to File Answer by Norma L. Barajas."),
    (69375678, 29, "Robinson v. Jackson", "ncwd",
     "Pro Se MOTION for Extension of Time to Answer by Alysse Hyatt."),
]


async def main():
    token = ""
    envp = Path(".env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN") and "=" in line:
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    token = token or os.environ.get("COURTLISTENER_API_TOKEN", "")

    rows = []
    async with AsyncCourtListenerClient(token) as client:
        for docket_id, doc_num, case_name, court, src_desc in CANDIDATES:
            url = f"https://www.courtlistener.com/docket/{docket_id}/{doc_num}/"
            data = await client.get_opinion_text_with_metadata(url)
            text = (data or {}).get("text", "")
            slug = doc_slug(data.get("case_name", "") or case_name, data.get("docket_number", ""), docket_id)
            out_path = os.path.join(CELL_DIR, f"{slug}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
            row = manifest_row(
                slug=slug, court=court or data.get("court", ""), docket_id=docket_id,
                document_number=doc_num, filer_type="pro_se", doc_type="procedural_motion",
                recap_url=url, is_available=True, sanction_screen="clean",
                notes=f"{case_name[:60]}; src_desc={src_desc[:90]}; vet=self-signed pro se, no attorney block, clean docket",
            )
            rows.append(row)
            print(f"saved {slug} {len(text)} chars")

    out_json = os.path.join(CELL_DIR, "_round2_rows.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
