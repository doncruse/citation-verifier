"""Custom vetting loop for the attorney__procedural_motion baseline cell.

pull_cell.py with a bare "motion to compel" query is biased: 6/10 hits are
standalone "In re Motion to Compel Compliance with Subpoena" miscellaneous
actions (doc #1 IS the motion; no underlying two-party case). This script
adds a caption-based exclusion filter on top of the same pull_cell/pull_baseline
machinery, and rotates across several query variants (compel production,
compel discovery responses, motion to strike, motion for extension of time)
to get court/topic spread instead of one query's ranking order.

Run from repo root:
    venv/Scripts/python.exe scratch/screen_gate/pull_attorney_procedural_motion.py
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
from pull_cell import _search_available, load_token

CELL = "attorney__procedural_motion"
FILER_TYPE = "attorney"
DOC_TYPE = "procedural_motion"
BASELINE_ROOT = os.path.join(_HERE, "baseline")
TARGET = 10
MIN_CHARS = 3500
FILED_AFTER = "2023-01-01"

QUERIES = [
    "motion to compel discovery responses",
    "motion to compel production of documents",
    "motion to strike affirmative defenses",
    "motion for extension of time to respond",
    "motion to compel interrogatory responses",
    "motion to compel answers to interrogatories",
    "motion for protective order discovery",
]

# Dockets whose classified doc slipped the description filter but is NOT a
# discovery/procedural motion on inspection (Task 4c content vet):
#  - 67303601: doc 64-1 is a [Proposed] Second Amended Complaint (pleading)
#  - 68056627: doc 1 is a Petition of Removal (jurisdictional pleading)
_REJECT_DOCKETS = {67303601, 68056627}

# Content-level doc_type guard: the FIRST title line of the document must
# read as a motion, not a complaint/petition/notice/answer. The docket-entry
# description classifier can misfire when a motion for leave carries a
# proposed pleading as its lead attachment, or when a removal petition's
# entry text mentions "discovery".
_CONTENT_PLEADING_TITLES = (
    "complaint", "petition of removal", "petition for removal",
    "notice of removal", "amended complaint", "supplemental complaint",
    "answer and", "answer to complaint", "counterclaim",
)


def content_is_motion(text: str) -> bool:
    """Return True only if the document's own caption/title reads as a
    motion (not a complaint/petition/notice). Scans the first ~1500 chars
    for a 'MOTION' title and rejects lead pleading titles."""
    head = (text or "")[:1800].lower()
    for bad in _CONTENT_PLEADING_TITLES:
        # a lead pleading title near the top, before any 'motion' word
        idx = head.find(bad)
        m_idx = head.find("motion")
        if idx != -1 and (m_idx == -1 or idx < m_idx):
            return False
    return "motion" in head

# Caption patterns that mark a standalone misc action / admiralty / MDL
# rather than an ordinary two-party district-court civil case. Note: RECAP
# search caseName is sometimes truncated/derived from the motion title
# itself (not the docket's true "In re ..." caption), so we also match
# "compel <name> to comply with subpoena" style captions that never
# literally start with "in re" in the search result (Task 4c finding:
# motion-to-compel-livingston-allen-to-71363248 slipped through the
# prefix-only filter this way -- it's an ancillary Rule 45 miscellaneous
# proceeding, not an in-case discovery motion).
_EXCLUDE_PREFIXES = ("in re", "in the matter of", "complaint of", "motion to compel")
_EXCLUDE_SUBSTRINGS = ("compliance with subpoena", "compliance with a subpoena",
                       "to quash subpoena", "to quash a subpoena", "subpoena to",
                       "comply with rule 45", "comply with subpoena",
                       "comply with a subpoena")


def is_excluded_caption(case_name: str) -> bool:
    name = (case_name or "").strip().lower()
    if not name:
        return True
    for prefix in _EXCLUDE_PREFIXES:
        if name.startswith(prefix):
            return True
    for sub in _EXCLUDE_SUBSTRINGS:
        if sub in name:
            return True
    # Not a "X v. Y" two-party case at all (e.g. filed as a bare motion
    # title with no "v." in the caption) -- ordinary civil cases always
    # have "v." (or "vs.") in the caption.
    if " v. " not in name and " vs. " not in name and " v " not in name:
        return True
    return False


# Filer-field false positives: RECAP sometimes puts the pro se party's own
# name in the `firm` field. Reject those so pro se filings don't leak into
# the attorney cell.
_FIRM_LOOKS_LIKE_PARTY_NAME = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")


def _load_existing(cell_dir):
    """Resume support: reload manifest rows already on disk from a prior
    (possibly network-interrupted) run so reruns top up instead of
    duplicating work or losing progress."""
    man_path = Path(cell_dir, f"manifest-{CELL}.jsonl")
    rows = []
    if man_path.exists():
        with man_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


async def run():
    cell_dir = os.path.join(BASELINE_ROOT, CELL)
    os.makedirs(cell_dir, exist_ok=True)
    saved = _load_existing(cell_dir)
    seen_dockets = {row["docket_id"] for row in saved}
    seen_courts: dict = {}
    for row in saved:
        seen_courts[row["court"]] = seen_courts.get(row["court"], 0) + 1
    rejected_log = []
    if saved:
        print(f"resuming with {len(saved)} already-saved rows: "
              f"{[r['slug'] for r in saved]}")

    async with AsyncCourtListenerClient(load_token()) as client:
        for query in QUERIES:
            if len(saved) >= TARGET:
                break
            page = 1
            while len(saved) < TARGET and page <= 6:
                results = None
                for attempt in range(4):
                    try:
                        results = await _search_available(client, query, FILED_AFTER, page)
                        break
                    except Exception:
                        if attempt < 3:
                            await asyncio.sleep(2 * (attempt + 1))
                if results is None:
                    break
                page += 1
                if not results:
                    break
                for r in results:
                    if len(saved) >= TARGET:
                        break
                    did = r.get("docket_id")
                    if did in seen_dockets or did in _REJECT_DOCKETS:
                        continue
                    case_name = r.get("caseName", "")

                    if is_excluded_caption(case_name):
                        rejected_log.append((case_name, "excluded caption pattern"))
                        continue

                    if not r.get("firm"):
                        rejected_log.append((case_name, "no firm (not attorney-filed)"))
                        continue

                    court = r.get("court_id", "")
                    # soft court diversity cap: no more than 2 per court
                    if seen_courts.get(court, 0) >= 2:
                        rejected_log.append((case_name, f"court cap reached ({court})"))
                        continue

                    cand = next((d for d in (r.get("recap_documents") or [])
                                 if d.get("is_available")
                                 and classify_doctype(d.get("description", "")) == DOC_TYPE),
                                None)
                    if not cand:
                        continue

                    # CL's docket-entries endpoint is flaky (502/timeout seen
                    # repeatedly). Retry a few times before giving up on this
                    # candidate so one transient failure doesn't end the run.
                    entries = None
                    for attempt in range(4):
                        try:
                            entries = await client.get_docket_entries(did)
                            break
                        except Exception as exc:
                            if attempt == 3:
                                rejected_log.append((case_name, f"docket-entries fetch failed: {exc}"))
                            else:
                                await asyncio.sleep(2 * (attempt + 1))
                    if entries is None:
                        continue
                    hits = sanction_hits([e.get("description", "") for e in entries])
                    if hits:
                        rejected_log.append((case_name, f"sanction screen hit: {hits}"))
                        continue

                    firm0 = (r.get("firm") or [""])[0]
                    meta = {"court": court, "filer_type": FILER_TYPE,
                            "doc_type": DOC_TYPE, "sanction_screen": "clean",
                            "notes": f"{case_name[:60]}; firm={firm0}; "
                                     f"pages={cand.get('page_count')}; query={query!r}"}
                    row = None
                    fetch_failed = False
                    for attempt in range(4):
                        try:
                            row = await pull_candidate(client, did, cand.get("document_number"),
                                                       cell_dir, meta, min_chars=MIN_CHARS)
                            break
                        except Exception as exc:
                            if attempt == 3:
                                fetch_failed = True
                                rejected_log.append((case_name, f"doc fetch failed: {exc}"))
                            else:
                                await asyncio.sleep(2 * (attempt + 1))
                    if fetch_failed:
                        continue
                    if not row:
                        rejected_log.append((case_name, "no usable text / below min_chars"))
                        continue

                    # Post-fetch vet: confirm counsel signed the filing (reject
                    # if it reads pro se despite a firm-looking search field --
                    # Task 4c found RECAP's `firm` sometimes holds the pro se
                    # party's own name, e.g. Ramos v. Midland Credit Mgmt).
                    txt_path = os.path.join(cell_dir, f"{row['slug']}.txt")
                    with open(txt_path, encoding="utf-8") as fh:
                        saved_text = fh.read()
                    lowered_text = saved_text.lower()
                    has_counsel_marker = any(
                        marker in lowered_text for marker in
                        ("attorney for", "attorneys for", "counsel for", "esq.", "esq,")
                    )
                    looks_pro_se = "pro se" in lowered_text[:3000] or not has_counsel_marker
                    if looks_pro_se:
                        os.remove(txt_path)
                        rejected_log.append((case_name, "post-fetch vet: reads pro se, no counsel marker"))
                        continue

                    # Content-level doc_type guard: reject docs whose own lead
                    # title is a pleading (proposed amended complaint attached
                    # to a motion-for-leave, notice/petition of removal, etc.)
                    # even though the docket-entry description classified as a
                    # procedural motion (Task 4c content vet).
                    if not content_is_motion(saved_text):
                        os.remove(txt_path)
                        rejected_log.append((case_name, "post-fetch vet: lead title is a pleading, not a motion"))
                        continue

                    seen_dockets.add(did)
                    saved.append(row)
                    seen_courts[court] = seen_courts.get(court, 0) + 1
                    print(f"  saved {row['slug'][:50]:50s} court={row['court']:6s} "
                          f"doc#{row['document_number']}  ({case_name[:50]})")
                    # Write manifest incrementally so a mid-run network
                    # failure (observed twice already) doesn't lose progress.
                    man = Path(cell_dir, f"manifest-{CELL}.jsonl")
                    with man.open("w", encoding="utf-8") as fh:
                        for srow in saved:
                            fh.write(json.dumps(srow, ensure_ascii=False) + "\n")

    man = Path(cell_dir, f"manifest-{CELL}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{CELL}: saved {len(saved)}/{TARGET}")
    print(f"rejected {len(rejected_log)} candidates along the way")
    for name, reason in rejected_log[:40]:
        print(f"  REJECTED: {reason:45s} {name[:60]}")
    return saved


if __name__ == "__main__":
    asyncio.run(run())
