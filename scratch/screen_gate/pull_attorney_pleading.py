"""Custom curation loop for the attorney__pleading baseline cell (Task 4c).

pull_cell.py alone is insufficient here: a bare "complaint" query surfaces
admiralty limitation-of-liability petitions ("In re / In the Matter of the
Complaint of <vessel>"), which are NOT ordinary district-court civil
complaints. This loop adds:
  - caseName exclusion for "in re", "in the matter of", "complaint of"
    (admiralty/MDL/misc actions), checked case-insensitively.
  - multiple query variants (civil-rights, employment, contract, tort,
    generic "complaint for damages") to get topic + court spread.
  - a per-court cap so no single court dominates the 10-doc sample.
  - firm requirement (attorney cell => counsel of record via `firm` field).

Reuses pull_baseline.classify_doctype / sanction_hits / pull_candidate for the
same doctype-classification, sanction-screen, and save/manifest logic as
pull_cell.py -- only the search/vet loop is custom.
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
from pull_baseline import classify_doctype, sanction_hits, pull_candidate

BASELINE_ROOT = os.path.join(_HERE, "baseline")
CELL = "attorney__pleading"
FILER_TYPE = "attorney"
DOC_TYPE = "pleading"
TARGET = 10
MIN_CHARS = 4000
FILED_AFTER = "2023-01-01"
MAX_PER_COURT = 2  # spread cap

QUERIES = [
    "employment discrimination complaint",
    "breach of contract complaint",
    "complaint for personal injury",
    "complaint for negligence",
    "wrongful termination complaint",
    "products liability complaint",
    "complaint for damages",
    "trademark infringement complaint",
]

_EXCLUDE_PREFIXES = ("in re", "in the matter of", "complaint of")
_EXCLUDE_SUBSTRINGS = ("complaint of the", "petition for exoneration",
                       "limitation of liability", "motion to compel compliance")

# RECAP's `firm` field for pro se prisoner filings is often populated with the
# facility name (not counsel) -- e.g. "Harris County Jail", "G-64213,
# California Substance Abuse Treatment Facility (5248)". A `(PC)` case-name
# prefix (CourtListener's own "prisoner civil rights" tag) is a strong pro se
# signal that survives even when `firm` looks non-empty.
_FACILITY_FIRM_HINTS = ("jail", "correctional", "prison", "detention",
                        "state prison", "facility")


def is_ordinary_civil_case(case_name: str) -> bool:
    """Reject admiralty limitation petitions / MDL / misc actions.

    Ordinary district-court civil complaints are two-party "X v. Y" captions.
    Admiralty limitation-of-liability petitions and miscellaneous actions are
    styled "In re <vessel>" / "In the Matter of the Complaint of <owner>" /
    "Complaint of <owner>" and must be excluded even though they satisfy the
    RECAP doctype classifier (their filing is literally called "Complaint").
    """
    if not case_name:
        return False
    lowered = case_name.strip().lower()
    if lowered.startswith("(pc)"):
        return False  # CourtListener's own prisoner-civil-rights tag
    for prefix in _EXCLUDE_PREFIXES:
        if lowered.startswith(prefix):
            return False
    for sub in _EXCLUDE_SUBSTRINGS:
        if sub in lowered:
            return False
    # Prefer an actual "v." / "vs." two-party caption.
    if " v. " not in lowered and " v " not in lowered and " vs. " not in lowered:
        return False
    return True


def plaintiff_has_real_counsel(result: dict) -> bool:
    """Cheap pre-filter on docket-level RECAP fields (NOT sufficient alone --
    see `document_shows_attorney_filer` for the authoritative content check).

    RECAP search results' `firm`/`attorney` describe the whole case, not
    necessarily the filing party -- and for pro se suits, `firm` is
    frequently populated with the facility name, or with the plaintiff's own
    name, rather than left empty. Two independent guards:
      1. Reject if any `firm` entry looks like a facility/institution rather
         than a law firm (jail/prison/correctional/detention keywords).
      2. Reject if the plaintiff's own name appears in the `attorney` list
         (a strong pro se signature -- CourtListener lists self-represented
         parties as their own "attorney").
    This catches the cheap/obvious cases fast, before spending a network call
    on `pull_candidate`. It is NOT sufficient: Task 4c found cases where a
    plaintiff filed pro se and *later* retained counsel who then appears in
    the case-level `firm`/`attorney` fields, even though the complaint itself
    has no attorney signature. Every candidate that passes this must still
    pass `document_shows_attorney_filer` on the actual saved text.
    """
    firms = [f for f in (result.get("firm") or []) if f]
    if not firms:
        return False
    for f in firms:
        fl = f.lower()
        if any(hint in fl for hint in _FACILITY_FIRM_HINTS):
            return False
    parties = result.get("party") or []
    attorneys = set(a.lower() for a in (result.get("attorney") or []))
    if parties:
        plaintiff = parties[0]
        if plaintiff and plaintiff.lower() in attorneys:
            return False  # plaintiff listed as their own attorney => pro se
    return True


# --- content-based filer vetting (authoritative) --------------------------
# Task 4c finding: docket-level `firm`/`attorney` RECAP fields describe the
# whole case and can list counsel who appeared AFTER the complaint was filed
# pro se. The only reliable signal is the complaint document's own signature
# block. We check the tail of the document (signature blocks are always at
# the end of the pleading, before any attached exhibits) for law-firm
# letterhead markers and the absence of pro se self-filing language.

_PRO_SE_MARKERS = (
    "pro se", "self-represented", "in propria persona", "pro-se",
    "declaration under penalty of perjury",  # standard pro se complaint forms
)

_ATTORNEY_SIGNATURE_MARKERS = (
    "attorney for plaintiff", "attorneys for plaintiff",
    "counsel for plaintiff",
)


def document_shows_attorney_filer(text: str) -> tuple[bool, str]:
    """Authoritative check: does the saved complaint text show a genuine
    attorney filer? Returns (ok, reason).

    Looks at the whole text for pro se markers (declaration-under-penalty
    forms, "pro se" self-identification) and requires an explicit "Attorney
    for Plaintiff" / "Counsel for Plaintiff" signature marker. Order matters:
    an explicit pro se self-identification in the caption ("and Pro Se,
    hereby files") overrides a later "Attorney for Plaintiff" appearing only
    in a certificate-of-service block naming opposing/other counsel.
    """
    lowered = text.lower()
    for marker in _PRO_SE_MARKERS:
        if marker in lowered:
            return False, f"pro se marker present: {marker!r}"
    if not any(marker in lowered for marker in _ATTORNEY_SIGNATURE_MARKERS):
        return False, "no 'Attorney for Plaintiff' / 'Counsel for Plaintiff' signature found"
    return True, "attorney signature block confirmed"


def load_token() -> str:
    env = Path(".env")
    if not env.exists():
        return os.environ.get("COURTLISTENER_API_TOKEN", "")
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("COURTLISTENER_API_TOKEN") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("COURTLISTENER_API_TOKEN", "")


FILED_BEFORE = "2025-12-31"


async def _search_available(client, q, filed_after, page, filed_before=FILED_BEFORE):
    params = {"type": "r", "available_only": "on", "q": q,
              "filed_after": filed_after, "filed_before": filed_before,
              "page": str(page)}
    data = await client._request_with_retry(
        "GET", f"{client.BASE_URL}/search/", params=params)
    return data.get("results", [])


async def pull_attorney_pleading(client, *, target=TARGET, min_chars=MIN_CHARS,
                                  filed_after=FILED_AFTER, max_pages_per_query=6,
                                  baseline_root=BASELINE_ROOT, preload_manifest=None):
    cell_dir = os.path.join(baseline_root, CELL)
    os.makedirs(cell_dir, exist_ok=True)
    saved, seen_dockets = [], set()
    court_counts: dict[str, int] = {}
    rejected_log = []

    # Preload rows already saved and vetted-good from a prior partial run so
    # we only need to fill the remaining slots (avoids re-fetching/re-vetting
    # docs already confirmed clean).
    if preload_manifest and os.path.exists(preload_manifest):
        with open(preload_manifest, encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                saved.append(row)
                seen_dockets.add(row["docket_id"])
                court_counts[row["court"]] = court_counts.get(row["court"], 0) + 1
        print(f"Preloaded {len(saved)} rows from {preload_manifest}")

    for query in QUERIES:
        if len(saved) >= target:
            break
        page = 1
        while len(saved) < target and page <= max_pages_per_query:
            results = await _search_available(client, query, filed_after, page)
            page += 1
            if not results:
                break
            for r in results:
                if len(saved) >= target:
                    break
                did = r.get("docket_id")
                if did in seen_dockets:
                    continue
                case_name = r.get("caseName", "")
                if not is_ordinary_civil_case(case_name):
                    rejected_log.append(f"REJECT (admiralty/misc caption): {case_name!r}")
                    continue
                court = r.get("court_id", "")
                if court_counts.get(court, 0) >= MAX_PER_COURT:
                    continue
                if not plaintiff_has_real_counsel(r):
                    rejected_log.append(
                        f"REJECT (no genuine plaintiff counsel): {case_name!r} "
                        f"firm={r.get('firm')!r} attorney={r.get('attorney')!r}")
                    continue
                cand = next((d for d in (r.get("recap_documents") or [])
                             if d.get("is_available")
                             and classify_doctype(d.get("description", "")) == DOC_TYPE),
                            None)
                if not cand:
                    continue
                entries = await client.get_docket_entries(did)
                hits = sanction_hits([e.get("description", "") for e in entries])
                if hits:
                    rejected_log.append(f"REJECT (sanction screen {hits}): {case_name!r}")
                    continue
                seen_dockets.add(did)
                firm0 = (r.get("firm") or [""])[0]
                meta = {"court": court, "filer_type": FILER_TYPE,
                        "doc_type": DOC_TYPE, "sanction_screen": "clean",
                        "notes": f"{case_name[:60]}; firm={firm0}; "
                                 f"pages={cand.get('page_count')}; query={query!r}"}
                row = await pull_candidate(client, did, cand.get("document_number"),
                                           cell_dir, meta, min_chars=min_chars)
                if not row:
                    continue
                # Authoritative content check -- see document_shows_attorney_filer
                # docstring: docket-level firm/attorney fields are not enough.
                saved_path = os.path.join(cell_dir, f"{row['slug']}.txt")
                with open(saved_path, encoding="utf-8") as fh:
                    saved_text = fh.read()
                ok, reason = document_shows_attorney_filer(saved_text)
                if not ok:
                    os.remove(saved_path)
                    rejected_log.append(f"REJECT (content check failed: {reason}): {case_name!r}")
                    continue
                court_counts[court] = court_counts.get(court, 0) + 1
                saved.append(row)
                print(f"  saved {row['slug'][:44]:44s} court={row['court']:6s} "
                      f"doc#{row['document_number']} query={query!r} ({reason})")

    man = Path(cell_dir, f"manifest-{CELL}.jsonl")
    with man.open("w", encoding="utf-8") as fh:
        for row in saved:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{CELL}: saved {len(saved)}/{target}")
    print(f"Rejected (sample of {min(len(rejected_log), 15)}):")
    for line in rejected_log[:15]:
        print(f"  {line}")
    return saved


async def _main():
    preload = os.path.join(BASELINE_ROOT, CELL, "manifest-preload.jsonl")
    async with AsyncCourtListenerClient(load_token()) as client:
        await pull_attorney_pleading(client, preload_manifest=preload)


if __name__ == "__main__":
    asyncio.run(_main())
