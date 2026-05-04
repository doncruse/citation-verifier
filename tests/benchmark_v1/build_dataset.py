"""Mine 40 parentheticals each from 5 federal districts -> dataset.csv.

Reuses Pilot A's parenthetical-extraction logic. New: loops over court IDs,
applies the stat_Published=on&stat_Unknown=on filter, stratified-samples
40 per district.
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

# Reuse Pilot A's helpers verbatim where possible.
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "pilot_a"))
from build_fresh_dc_sample import (  # noqa: E402
    HOLDING_VERBS,
    MIN_WORDS,
    MAX_WORDS,
    _normalize_text,
    _is_explanatory_parenthetical,
    _word_count,
    extract_parentheticals,
)

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.gold_db import GoldDB  # noqa: E402
from citation_verifier.models import VerificationResult, VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
OPINION_TEXT_CACHE = PROJECT_ROOT / "benchmark_v1" / "_opinion_cache"
RAW_POOL = PROJECT_ROOT / "benchmark_v1" / "_raw_pool.json"
GOLD_DB_PATH = PROJECT_ROOT / "gold_db" / "gold.db"

# 5 districts, in priority order. NYSD has fallback if empty.
COURTS = ["dcd", "cand", "txsd", "ilnd", "nysd"]
COURTS_FALLBACK = ["mad", "paed"]  # used if a primary district has < 80 verified

DATE_FROM = "2026-01-01"
DATE_TO = "2026-04-30"
SAMPLE_PER_COURT = 40
OPINIONS_PER_COURT = 200  # oversample budget
SEED = 42


def fetch_opinion_list(client: CourtListenerClient, court_id: str) -> list[dict[str, Any]]:
    """Page through D.D.C.-style search but with stat_Unknown=on."""
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < OPINIONS_PER_COURT:
        r = client._request_with_retry(
            "GET",
            f"{client.BASE_URL}/search/",
            params={
                "type": "o",
                "court": court_id,
                "filed_after": DATE_FROM,
                "filed_before": DATE_TO,
                "stat_Published": "on",
                "stat_Unknown": "on",
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
                "court_id": court_id,
            })
            if len(out) >= OPINIONS_PER_COURT:
                break
        page += 1
        if not data.get("next"):
            break
    return out


def fetch_opinion_text(client: CourtListenerClient, cluster_id: int) -> str:
    """Cache-backed opinion text fetch. Reuses pilot_a opinion_cache when possible."""
    OPINION_TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OPINION_TEXT_CACHE / f"{cluster_id}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    # Fallback: try Pilot A's cache too
    pilot_cache = (PROJECT_ROOT / "scratch" / "pilot_a" / "_dcd_opinion_cache"
                   / f"{cluster_id}.txt")
    if pilot_cache.exists():
        text = pilot_cache.read_text(encoding="utf-8", errors="replace")
        cache.write_text(text, encoding="utf-8")
        return text
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


VERIFY_CHUNK = 100  # Pilot A learning: large verify_batch hangs; chunk it.


async def verify_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify pool in chunks. Returns ALL items annotated with v_status.

    Both resolved (VERIFIED / LIKELY_REAL) and unresolved (NOT_FOUND etc.)
    are kept and annotated; the caller filters for sampling. Saving the
    full annotated pool lets us audit CL-coverage bias later (e.g. spot-
    check unresolved items to estimate the "real but missed" rate).
    """
    verifier = CitationVerifier()
    annotated: list[dict[str, Any]] = []
    total_chunks = (len(pool) + VERIFY_CHUNK - 1) // VERIFY_CHUNK
    db = GoldDB(GOLD_DB_PATH)
    try:
        for ci in range(total_chunks):
            chunk = pool[ci * VERIFY_CHUNK : (ci + 1) * VERIFY_CHUNK]
            parsed = [parsed_citation_from_eyecite(item["fcc"]) for item in chunk]
            citation_strs = [item["citation_text"] for item in chunk]
            print(f"    verify chunk {ci + 1}/{total_chunks} ({len(chunk)} cites)...",
                  flush=True)
            # --- Build-side gold-DB cache ---
            # On a cache hit (cite_string already in cases table) we skip the CL
            # call entirely and synthesise a VerificationResult from stored data.
            # This only matters for future dataset builds (v2+); v1 is sealed.
            cached_results: dict[int, VerificationResult] = {}
            to_verify_indices: list[int] = []
            to_verify_cites: list[str] = []
            to_verify_parsed: list = []
            for j, (cite, pc) in enumerate(zip(citation_strs, parsed)):
                row = db.conn.execute(
                    "SELECT cluster_id, canonical_name FROM cases"
                    " WHERE cite_string = ? LIMIT 1",
                    (cite,),
                ).fetchone()
                if row is not None:
                    cached_results[j] = VerificationResult(
                        input_citation=cite,
                        status=VerificationStatus.VERIFIED,
                        confidence=1.0,
                        matched_case_name=row["canonical_name"],
                        matched_url=(
                            f"https://www.courtlistener.com/opinion/{row['cluster_id']}/"
                        ),
                        matched_cluster_id=row["cluster_id"],
                    )
                else:
                    to_verify_indices.append(j)
                    to_verify_cites.append(cite)
                    to_verify_parsed.append(pc)

            n_cached = len(cached_results)
            if n_cached:
                print(f"      build-side cache: {n_cached} hits / {len(chunk)} in chunk",
                      flush=True)

            if to_verify_cites:
                cl_results = await verifier.verify_batch(
                    to_verify_cites, parsed_citations=to_verify_parsed, quick_only=True,
                )
            else:
                cl_results = []

            results: list[VerificationResult] = [None] * len(chunk)  # type: ignore[list-item]
            for idx, r in zip(to_verify_indices, cl_results):
                results[idx] = r
            for idx, r in cached_results.items():
                results[idx] = r
            for item, res in zip(chunk, results):
                item = {k: v for k, v in item.items() if k != "fcc"}
                item["v_status"] = res.status.value if res.status else ""
                item["v_url"] = res.matched_url or ""
                item["v_matched_name"] = res.matched_case_name or ""
                annotated.append(item)
    finally:
        db.close()
    return annotated


def _is_resolved(item: dict[str, Any]) -> bool:
    return item.get("v_status") in (
        VerificationStatus.VERIFIED.value,
        VerificationStatus.LIKELY_REAL.value,
    )


def mine_court(client: CourtListenerClient, court_id: str,
               tokenizer: AhocorasickTokenizer) -> list[dict[str, Any]]:
    print(f"\n=== {court_id} ===")
    opinions = fetch_opinion_list(client, court_id)
    print(f"  {court_id}: got {len(opinions)} opinions in date range", flush=True)
    if not opinions:
        return []
    pool: list[dict[str, Any]] = []
    for i, op in enumerate(opinions, 1):
        try:
            text = fetch_opinion_text(client, op["cluster_id"])
        except Exception as exc:
            print(f"  fetch fail cluster {op['cluster_id']}: {exc}", file=sys.stderr)
            continue
        if not text:
            continue
        for p in extract_parentheticals(text, tokenizer):
            p["citing_cluster_id"] = op["cluster_id"]
            p["citing_case"] = op["case_name"]
            p["citing_date"] = op["date_filed"]
            p["citing_court"] = court_id
            pool.append(p)
        if i % 25 == 0:
            print(f"  {court_id}: scanned {i}/{len(opinions)}, pool {len(pool)}",
                  flush=True)
    print(f"  {court_id}: raw pool {len(pool)}")
    annotated = asyncio.run(verify_pool(pool))
    n_resolved = sum(1 for it in annotated if _is_resolved(it))
    print(f"  {court_id}: annotated {len(annotated)} | resolved {n_resolved} "
          f"| unresolved {len(annotated) - n_resolved}")
    return annotated


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)

    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60
    tokenizer = AhocorasickTokenizer()

    courts_to_use = list(COURTS)
    all_rows: list[dict[str, Any]] = []
    # raw_dump now holds the FULL annotated pool per court (resolved + unresolved).
    # Sampling pulls only resolved items, but unresolved are persisted to
    # _raw_pool.json so we can audit CL-coverage bias later.
    raw_dump: dict[str, list[dict[str, Any]]] = {}

    for court_id in list(courts_to_use):
        annotated = mine_court(client, court_id, tokenizer)
        raw_dump[court_id] = annotated
        verified = [it for it in annotated if _is_resolved(it)]
        if len(verified) < 80:
            print(f"  WARN: {court_id} has only {len(verified)} verified rows; "
                  f"trying fallback", file=sys.stderr)
            # Try one fallback
            for fb in COURTS_FALLBACK:
                if fb in courts_to_use:
                    continue
                fb_annotated = mine_court(client, fb, tokenizer)
                raw_dump[fb] = fb_annotated
                fb_verified = [it for it in fb_annotated if _is_resolved(it)]
                if len(fb_verified) >= 80:
                    courts_to_use.append(fb)
                    courts_to_use.remove(court_id)
                    verified = fb_verified
                    court_id = fb
                    break

        if len(verified) < SAMPLE_PER_COURT:
            print(f"  WARN: {court_id} short — using all {len(verified)} rows",
                  file=sys.stderr)
            sample = verified
        else:
            sample = random.sample(verified, SAMPLE_PER_COURT)
        for i, item in enumerate(sample):
            all_rows.append({
                "id": f"{court_id}-{item['citing_cluster_id']}-{i}",
                "court": court_id,
                "proposition": item["parenthetical"],
                "gold_name": item["case_name"],
                "gold_cite": (
                    f"{item['case_name']}, {item['citation_text']} ({item['year']})"
                    if item["year"] else f"{item['case_name']}, {item['citation_text']}"
                ),
                "citing_cluster_id": item["citing_cluster_id"],
                "citing_year": (item.get("citing_date") or "")[:4],
                "cited_year": item.get("year") or "",
                "v_status": item.get("v_status", ""),
                "v_url": item.get("v_url", ""),
                "v_matched_name": item.get("v_matched_name", ""),
            })

    print(f"\nFinal dataset: {len(all_rows)} rows from {len(set(r['court'] for r in all_rows))} districts")
    RAW_POOL.write_text(json.dumps(raw_dump, indent=2, default=str), encoding="utf-8")

    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "court", "proposition", "gold_name", "gold_cite",
                        "citing_cluster_id", "citing_year", "cited_year",
                        "v_status", "v_url", "v_matched_name"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
