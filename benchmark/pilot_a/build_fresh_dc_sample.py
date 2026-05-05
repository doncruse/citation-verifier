"""Mine 50 fresh district-court parenthetical examples for Pilot A.

Source: D.D.C. opinions filed 2026-01-01 to 2026-04-25 (the only federal
district court with 2026 opinion ingest on CourtListener as of 2026-04-26;
documented as a pilot caveat).

Pipeline:
    1. Page through D.D.C. search results in date range, take ~200 opinions.
    2. For each, fetch plain_text from /opinions/{id}/.
    3. Run eyecite (Ahocorasick — Windows) over the text and pick
       FullCaseCitations whose parenthetical starts with a holding-style verb
       and is 15-80 words.
    4. Verify the cited case via the citation-verifier batch lookup.
    5. Random sample 50 from the verified pool (seed=42).

Output: benchmark/pilot_a/fresh_dc_sample.csv with the same column schema as
lepard_sample.csv, but `proposition` is the parenthetical and `gold_*` is
what eyecite extracted (case name + reporter citation).
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

import eyecite
from eyecite.models import FullCaseCitation
from eyecite.tokenizers import AhocorasickTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark" / "pilot_a" / "fresh_dc_sample.csv"
PARENS_RAW = PROJECT_ROOT / "benchmark" / "pilot_a" / "fresh_dc_parens_raw.json"

COURT_ID = "dcd"
DATE_FROM = "2026-01-01"
DATE_TO = "2026-04-25"

OPINION_BUDGET = 200       # opinions to scan
SAMPLE_SIZE = 50
SEED = 42

HOLDING_VERBS = (
    "holding", "held", "finding", "found", "concluding", "concluded",
    "noting", "noted", "explaining", "explained",
    "stating", "stated", "recognizing", "recognized",
    "affirming", "affirmed", "reasoning", "reasoned",
    "observing", "observed", "rejecting", "rejected",
    "ruling", "ruled", "emphasizing", "emphasized",
    "describing", "addressing", "discussing",
)
MIN_WORDS = 15
MAX_WORDS = 80


def _normalize_text(t: str) -> str:
    """Strip form-feeds + page-number-only lines + collapse whitespace.

    The eyecite parenthetical extractor breaks on text where every line is
    separated by `\\n\\n` (which is what CL's `plain_text` of D.D.C.
    opinions looks like). Collapsing whitespace fixes that.
    """
    t = re.sub(r"\f", " ", t)
    t = re.sub(r"\n\s*\d+\s*\n", "\n", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _is_explanatory_parenthetical(p: str) -> bool:
    """Accept both holding-verb parentheticals and substantive explanatory ones.

    Reject 'quoting X v. Y, ...' and 'citing X v. Y' since those wrap a
    further citation rather than carry their own proposition. Accept
    parentheticals beginning with a holding-style verb OR with substantive
    prose content.
    """
    if not p:
        return False
    s = p.strip()
    first = s.split()[0].lower().rstrip(",.;:")
    if first in {"quoting", "citing", "cited", "quoted", "internal",
                "alteration", "alterations", "emphasis", "footnote"}:
        return False
    if first in HOLDING_VERBS:
        return True
    # Otherwise, accept if the parenthetical reads like a substantive
    # proposition (>= 15 words means filter on length below already).
    return True


def _word_count(p: str) -> int:
    return len(p.strip().split())


def fetch_opinion_list(client: CourtListenerClient) -> list[dict[str, Any]]:
    """Return a list of {cluster_id, opinion_id, case_name, date_filed}."""
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < OPINION_BUDGET:
        r = client._request_with_retry(
            "GET",
            f"{client.BASE_URL}/search/",
            params={
                "type": "o",
                "court": COURT_ID,
                "filed_after": DATE_FROM,
                "filed_before": DATE_TO,
                "order_by": "dateFiled desc",
                "page_size": 50,
                "page": page,
            },
        )
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        for hit in results:
            out.append({
                "cluster_id": hit.get("cluster_id"),
                "case_name": hit.get("caseName") or "",
                "date_filed": hit.get("dateFiled") or "",
                "docket_number": hit.get("docketNumber") or "",
            })
            if len(out) >= OPINION_BUDGET:
                break
        page += 1
        if not data.get("next"):
            break
    return out


OPINION_TEXT_CACHE = PROJECT_ROOT / "benchmark" / "pilot_a" / "dcd_citing_opinion_cache"


def fetch_opinion_text(client: CourtListenerClient, cluster_id: int) -> str:
    """Return plain_text of the lead opinion for a cluster (with on-disk cache)."""
    OPINION_TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OPINION_TEXT_CACHE / f"{cluster_id}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    cluster = client._request_with_retry(
        "GET", f"{client.BASE_URL}/clusters/{cluster_id}/"
    ).json()
    sub_ops = cluster.get("sub_opinions") or []
    if not sub_ops:
        return ""
    op = client._request_with_retry("GET", sub_ops[0]).json()
    text = op.get("plain_text") or ""
    cache.write_text(text, encoding="utf-8")
    return text


def extract_parentheticals(text: str, tokenizer: AhocorasickTokenizer) -> list[dict[str, Any]]:
    """Return [{citation_text, full_citation_text, case_name, parenthetical, year, month, day, court, fcc}] tuples.

    `full_citation_text` is the source-text slice covering the entire citation
    (case name + reporter + court + date + parenthetical), so downstream
    consumers can re-parse if eyecite metadata extraction drops a field.
    """
    out: list[dict[str, Any]] = []
    if not text:
        return out
    text = _normalize_text(text)
    try:
        cites = eyecite.get_citations(text, tokenizer=tokenizer)
    except Exception as exc:
        print(f"  eyecite failed: {exc}", file=sys.stderr)
        return out
    for c in cites:
        if not isinstance(c, FullCaseCitation):
            continue
        meta = c.metadata
        paren = (meta.parenthetical or "").strip()
        if not _is_explanatory_parenthetical(paren):
            continue
        wc = _word_count(paren)
        if wc < MIN_WORDS or wc > MAX_WORDS:
            continue
        plaintiff = (meta.plaintiff or "").strip()
        defendant = (meta.defendant or "").strip()
        case_name = ""
        if plaintiff and defendant:
            case_name = f"{plaintiff} v. {defendant}"
        elif defendant:
            case_name = defendant
        if not case_name:
            continue
        try:
            fs_start, fs_end = c.full_span()
            full_citation_text = text[fs_start:fs_end]
        except Exception:
            full_citation_text = c.matched_text()
        out.append({
            "citation_text": c.matched_text(),
            "full_citation_text": full_citation_text,
            "case_name": case_name,
            "parenthetical": paren,
            "year": meta.year or "",
            "month": meta.month or "",
            "day": meta.day or "",
            "court": meta.court or "",
            "fcc": c,  # keep for downstream verification
        })
    return out


async def verify_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run citation-verifier batch on the pool. Keep only VERIFIED + LIKELY_REAL."""
    verifier = CitationVerifier()
    parsed = [parsed_citation_from_eyecite(item["fcc"]) for item in pool]
    citation_strs = [item["citation_text"] for item in pool]
    # quick_only=True skips opinion-search + RECAP fallback. The batch
    # citation-lookup endpoint resolves well-formed reporter cites in a
    # single call; for pilot sample-building we don't need the slower
    # fallback path.
    results = await verifier.verify_batch(citation_strs, parsed_citations=parsed,
                                          quick_only=True)
    keep: list[dict[str, Any]] = []
    for item, res in zip(pool, results):
        status = res.status
        if status in (VerificationStatus.VERIFIED, VerificationStatus.LIKELY_REAL):
            item = {k: v for k, v in item.items() if k != "fcc"}
            item["v_status"] = status.value
            item["v_confidence"] = res.confidence
            item["v_url"] = res.matched_url or ""
            item["v_matched_name"] = res.matched_case_name or ""
            keep.append(item)
    return keep


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)

    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60

    print(f"Step 1: fetching up to {OPINION_BUDGET} D.D.C. opinions "
          f"({DATE_FROM} to {DATE_TO})...", flush=True)
    opinions = fetch_opinion_list(client)
    print(f"  got {len(opinions)} opinion clusters")

    tokenizer = AhocorasickTokenizer()

    print("\nStep 2-3: downloading text and extracting parentheticals...", flush=True)
    pool: list[dict[str, Any]] = []
    seen = 0
    for op in opinions:
        seen += 1
        try:
            text = fetch_opinion_text(client, op["cluster_id"])
        except Exception as exc:
            print(f"  [{seen}/{len(opinions)}] fetch failed for "
                  f"cluster {op['cluster_id']}: {exc}", file=sys.stderr)
            continue
        if not text:
            continue
        parens = extract_parentheticals(text, tokenizer)
        for p in parens:
            p["citing_cluster_id"] = op["cluster_id"]
            p["citing_case"] = op["case_name"]
            p["citing_date"] = op["date_filed"]
        pool.extend(parens)
        if seen % 25 == 0:
            print(f"  scanned {seen}/{len(opinions)}, pool size {len(pool)}",
                  flush=True)
    print(f"  done. raw pool: {len(pool)} parentheticals from {seen} opinions")

    PARENS_RAW.write_text(
        json.dumps(
            [{k: v for k, v in p.items() if k != "fcc"} for p in pool],
            indent=2,
        ),
        encoding="utf-8",
    )

    if len(pool) < SAMPLE_SIZE:
        print(f"WARN: only {len(pool)} candidates -- might not reach {SAMPLE_SIZE} after verify",
              file=sys.stderr)

    print("\nStep 4: verifying cited cases against CourtListener...", flush=True)
    verified = asyncio.run(verify_pool(pool))
    print(f"  verified pool: {len(verified)} (kept VERIFIED + LIKELY_REAL)")

    if len(verified) < SAMPLE_SIZE:
        print(f"WARN: verified pool ({len(verified)}) smaller than target ({SAMPLE_SIZE})",
              file=sys.stderr)
        sample = verified
    else:
        sample = random.sample(verified, SAMPLE_SIZE)

    print(f"\nWriting {len(sample)} rows to {OUT}")
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "proposition", "gold_name", "gold_cite",
                        "citing_court", "citing_year", "cited_year",
                        "source_quote", "v_status", "v_confidence",
                        "v_url", "v_matched_name", "citing_cluster_id"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for i, item in enumerate(sample):
            writer.writerow({
                "id": f"freshdc-{item['citing_cluster_id']}-{i}",
                "proposition": item["parenthetical"],
                "gold_name": item["case_name"],
                "gold_cite": f"{item['case_name']}, {item['citation_text']} ({item['year']})"
                             if item['year'] else f"{item['case_name']}, {item['citation_text']}",
                "citing_court": "United States District Court for the District of Columbia",
                "citing_year": (item.get("citing_date") or "")[:4],
                "cited_year": item.get("year") or "",
                "source_quote": "",
                "v_status": item.get("v_status", ""),
                "v_confidence": item.get("v_confidence", ""),
                "v_url": item.get("v_url", ""),
                "v_matched_name": item.get("v_matched_name", ""),
                "citing_cluster_id": item.get("citing_cluster_id", ""),
            })

    print(f"\nSample row 0:")
    if sample:
        for k, v in sample[0].items():
            sval = str(v)
            if len(sval) > 200:
                sval = sval[:200] + "..."
            print(f"  {k}: {sval}")


if __name__ == "__main__":
    main()
