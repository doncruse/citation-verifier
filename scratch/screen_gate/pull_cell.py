"""Parameterized baseline-cell puller — the reproducible driver behind Task 4c.

Promoted from the validated Task 4b pilot. Given a cell + a RECAP search query,
it: searches `available_only=on` (most RECAP docs have no text — this is
required), dedups by docket, keeps docs whose description classifies to the
target doc_type, sanction-screens each docket, and saves text + a manifest row
via pull_baseline.pull_candidate.

Filer type: attorney cells pass require_firm=True (docket has counsel of record).
Pro se cells pass require_firm=False and are the harder case — the agent driving
this must still vet each candidate for a pro se signature (RECAP search fields
describe the case, not always the individual filer). See PROJECT.md §5 #2.

CLI:
  python pull_cell.py <cell> "<query>" <filer_type> <doc_type> \
      [--target 10] [--min-chars 4000] [--filed-after 2023-01-01] \
      [--no-require-firm] [--max-pages 8]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Make `from pull_baseline import ...` resolve regardless of cwd, so agents can
# run this from the repo root while it still finds its sibling module.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from citation_verifier.client import AsyncCourtListenerClient
from pull_baseline import classify_doctype, sanction_hits, pull_candidate

# baseline/ lives next to this script; script-relative so cwd doesn't matter.
BASELINE_ROOT = os.path.join(_HERE, "baseline")


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


async def pull_cell(client, *, cell, query, filer_type, doc_type,
                    filed_after="2023-01-01", target=10, min_chars=4000,
                    require_firm=True, max_pages=8, baseline_root=BASELINE_ROOT):
    """Pull up to `target` clean docs for one cell. Returns manifest rows and
    writes <slug>.txt + manifest-<cell>.jsonl under baseline_root/<cell>/."""
    cell_dir = os.path.join(baseline_root, cell)
    os.makedirs(cell_dir, exist_ok=True)
    saved, seen = [], set()
    page = 1
    while len(saved) < target and page <= max_pages:
        results = await _search_available(client, query, filed_after, page)
        page += 1
        if not results:
            break
        for r in results:
            if len(saved) >= target:
                break
            did = r.get("docket_id")
            if did in seen:
                continue
            if require_firm and not r.get("firm"):
                continue
            cand = next((d for d in (r.get("recap_documents") or [])
                         if d.get("is_available")
                         and classify_doctype(d.get("description", "")) == doc_type), None)
            if not cand:
                continue
            entries = await client.get_docket_entries(did)
            hits = sanction_hits([e.get("description", "") for e in entries])
            if hits:
                continue  # not a clean docket
            seen.add(did)
            firm0 = (r.get("firm") or [""])[0]
            meta = {"court": r.get("court_id", ""), "filer_type": filer_type,
                    "doc_type": doc_type, "sanction_screen": "clean",
                    "notes": f"{r.get('caseName', '')[:60]}; firm={firm0}; "
                             f"pages={cand.get('page_count')}"}
            row = await pull_candidate(client, did, cand.get("document_number"),
                                       cell_dir, meta, min_chars=min_chars)
            if row:
                saved.append(row)
                print(f"  saved {row['slug'][:44]:44s} court={row['court']:6s} "
                      f"doc#{row['document_number']}")
    man = Path(cell_dir, f"manifest-{cell}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{cell}: saved {len(saved)}/{target}")
    return saved


async def _main(a):
    async with AsyncCourtListenerClient(load_token()) as client:
        await pull_cell(client, cell=a.cell, query=a.query,
                        filer_type=a.filer_type, doc_type=a.doc_type,
                        filed_after=a.filed_after, target=a.target,
                        min_chars=a.min_chars, require_firm=not a.no_require_firm,
                        max_pages=a.max_pages)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cell")
    ap.add_argument("query")
    ap.add_argument("filer_type", choices=["attorney", "pro_se"])
    ap.add_argument("doc_type", choices=["merits_brief", "pleading", "procedural_motion"])
    ap.add_argument("--target", type=int, default=10)
    ap.add_argument("--min-chars", type=int, default=4000, dest="min_chars")
    ap.add_argument("--filed-after", default="2023-01-01", dest="filed_after")
    ap.add_argument("--no-require-firm", action="store_true")
    ap.add_argument("--max-pages", type=int, default=8, dest="max_pages")
    asyncio.run(_main(ap.parse_args()))
