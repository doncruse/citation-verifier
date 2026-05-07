"""Run the v1.3 pipeline pieces against the state-court sample.

For each item in sample.json, measures:
  - court_id resolution: did we get a CL match (cluster_id) AND does
    courts-db know about its court?
  - name match: v_status == VERIFIED (citation lookup name-matched) or
    LIKELY_REAL (fuzzy search resolved); POSSIBLE_MATCH and NOT_FOUND fail.
  - full-text coverage: is the cluster's plain-text opinion non-empty
    and substantive (>= 500 chars)?

For NOT_FOUND items, we re-run citation-verifier (without quick_only)
to give the fallback path a chance.

Output: results.json (per-item), report.md (aggregate metrics).
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from citation_verifier.client import CourtListenerClient
from citation_verifier.gold_db import lookup_court
from citation_verifier.models import VerificationStatus
from citation_verifier.parser import parse_citation
from citation_verifier.verifier import CitationVerifier

HERE = Path(__file__).parent
SAMPLE = HERE / "sample.json"
OUT = HERE / "results.json"

MIN_SUBSTANTIVE_CHARS = 500


def cluster_id_from_url(url: str) -> int | None:
    if not url:
        return None
    m = re.search(r"/opinion/(\d+)/", url)
    return int(m.group(1)) if m else None


def fetch_cluster_court(client: CourtListenerClient, cluster_id: int) -> tuple[str, str, str, str] | None:
    """Returns (court_id, case_name, date_filed, opinion_text)."""
    try:
        cluster_resp = client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{cluster_id}/",
        )
        cluster = cluster_resp.json()
    except Exception as exc:
        print(f"  cluster {cluster_id}: fetch error {exc}")
        return None

    case_name = cluster.get("case_name", "") or ""
    date_filed = cluster.get("date_filed", "") or ""

    docket_url = cluster.get("docket", "") or ""
    court_id = ""
    if docket_url:
        try:
            docket_resp = client._request_with_retry("GET", docket_url)
            docket = docket_resp.json()
            court_url = docket.get("court", "") or ""
            if court_url:
                court_id = court_url.rstrip("/").split("/")[-1]
        except Exception as exc:
            print(f"  cluster {cluster_id}: docket fetch error {exc}")

    text = ""
    for op_url in cluster.get("sub_opinions", []) or []:
        try:
            op_resp = client._request_with_retry("GET", op_url)
            op = op_resp.json()
            t = op.get("plain_text", "") or ""
            if t.strip():
                text = t
                break
        except Exception:
            continue

    return court_id, case_name, date_filed, text


async def reverify_misses(items: list[dict]) -> dict[int, dict]:
    """Re-run citation-verifier (full pipeline) on NOT_FOUND items.
    Returns {sample_index: result_dict} for items where status changed.
    """
    out: dict[int, dict] = {}
    todo: list[tuple[int, str]] = []
    for i, it in enumerate(items):
        if it.get("v_status") == "NOT_FOUND":
            cite = it.get("citation_text", "")
            if cite:
                todo.append((i, cite))
    if not todo:
        return out
    print(f"Re-verifying {len(todo)} NOT_FOUND items with full fallback...")
    verifier = CitationVerifier()
    cites = [c for _, c in todo]
    parsed = [parse_citation(c) for c in cites]
    results = await verifier.verify_batch(cites, parsed_citations=parsed, quick_only=False)
    for (idx, _), res in zip(todo, results):
        out[idx] = {
            "v_status": res.status.value if res.status else "",
            "v_url": res.matched_url or "",
            "v_matched_name": res.matched_case_name or "",
            "v_confidence": res.confidence,
        }
    return out


def main() -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    print(f"Loaded {len(sample)} sample items")

    # Step 1: re-verify NOT_FOUND items (give them the full fallback path)
    rerun = asyncio.run(reverify_misses(sample))
    for idx, upd in rerun.items():
        print(f"  rerun [{idx}] {sample[idx]['citation_text']}: "
              f"{sample[idx]['v_status']} -> {upd['v_status']}")
        sample[idx].update(upd)
        sample[idx]["reran_with_fallback"] = True

    # Step 2: for each item with a v_url, fetch cluster -> court_id, opinion text.
    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 30
    results = []
    for i, it in enumerate(sample):
        rec = dict(it)
        rec["sample_idx"] = i
        cluster_id = cluster_id_from_url(it.get("v_url", ""))
        rec["matched_cluster_id"] = cluster_id
        if cluster_id:
            print(f"[{i+1}/{len(sample)}] cluster {cluster_id} ({it['citation_text']})")
            fetched = fetch_cluster_court(client, cluster_id)
            if fetched:
                court_id, cl_name, date_filed, text = fetched
                rec["cl_court_id"] = court_id
                rec["cl_case_name"] = cl_name
                rec["cl_date_filed"] = date_filed
                rec["opinion_chars"] = len(text or "")
                sys, lvl = lookup_court(court_id)
                rec["courtsdb_system"] = sys
                rec["courtsdb_level"] = lvl
            else:
                rec["cl_court_id"] = ""
                rec["opinion_chars"] = 0
                rec["courtsdb_system"] = None
                rec["courtsdb_level"] = None
        else:
            print(f"[{i+1}/{len(sample)}] no v_url ({it['citation_text']}) "
                  f"status={it.get('v_status')}")
            rec["cl_court_id"] = ""
            rec["opinion_chars"] = 0
            rec["courtsdb_system"] = None
            rec["courtsdb_level"] = None
        results.append(rec)

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT}")

    # Quick aggregate
    n = len(results)
    name_match = sum(1 for r in results if r.get("v_status") in ("VERIFIED", "LIKELY_REAL"))
    courtsdb_resolvable = sum(1 for r in results if r.get("courtsdb_system"))
    full_text_ok = sum(1 for r in results if (r.get("opinion_chars") or 0) >= MIN_SUBSTANTIVE_CHARS)
    print(f"\nName-match (VERIFIED/LIKELY_REAL): {name_match}/{n} ({name_match/n:.0%})")
    print(f"Court resolvable in courts-db: {courtsdb_resolvable}/{n} ({courtsdb_resolvable/n:.0%})")
    print(f"Full-text >= {MIN_SUBSTANTIVE_CHARS} chars: {full_text_ok}/{n} ({full_text_ok/n:.0%})")


if __name__ == "__main__":
    main()
