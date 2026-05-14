"""
Probe: char-length distribution of state COLR opinions in the design's
2026-01-01..2026-04-30 window.

Built after `cal` Supreme yielded 0/12 under the 25K cap. Question: is
the 25K-cap-vs-state-COLR-length issue cal-specific, or do ny/tex/fla/ill
behave the same way?

Lists every cluster in window for the four remaining state COLRs and
fetches its opinion-text length via the canonical fallback chain.
Outputs both a printed table and a CSV for the writeup.

Run from project root with venv activated:
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/probe_state_colr_sizes.py
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)
sys.path.insert(0, str(ROOT / "src"))

from citation_verifier.client import CourtListenerClient  # noqa: E402

HERE = Path(__file__).parent
OUT_CSV = HERE / "state_colr_size_probe.csv"

COURTS = ["ny", "tex", "fla", "ill"]
DATE_FROM = "2026-01-01"
DATE_TO = "2026-04-30"
CHAR_CAP = 25_000


def month_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    y1, m1, d1 = (int(x) for x in date_from.split("-"))
    y2, m2, d2 = (int(x) for x in date_to.split("-"))
    start = date(y1, m1, d1)
    end = date(y2, m2, d2)
    chunks: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        chunk_end = min(nxt - timedelta(days=1), end)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return chunks


def list_clusters(client: CourtListenerClient, court_id: str) -> list[dict]:
    seen: set[int] = set()
    out: list[dict] = []
    for f, t in month_chunks(DATE_FROM, DATE_TO):
        params: dict = {
            "docket__court": court_id,
            "date_filed__gte": f,
            "date_filed__lte": t,
            "order_by": "date_filed",
            "page_size": 20,
        }
        url = f"{client.BASE_URL}/clusters/"
        while url:
            resp = client._request_with_retry("GET", url, params=params, timeout=90)
            d = resp.json()
            for cl in d.get("results") or []:
                if cl.get("id") and cl["id"] not in seen:
                    seen.add(cl["id"])
                    out.append(cl)
            url = d.get("next")
            params = {}
    return out


def main() -> int:
    client = CourtListenerClient()
    rows: list[dict] = []
    summary: list[tuple[str, int, int, int]] = []  # court, n, fit_under_cap, min_chars

    for court in COURTS:
        print(f"\n=== {court} ===")
        t0 = time.time()
        clusters = list_clusters(client, court)
        print(f"  listed {len(clusters)} clusters in {time.time()-t0:.1f}s")

        sizes = []
        fits = 0
        for cl in clusters:
            abs_url = cl.get("absolute_url") or ""
            if abs_url and not abs_url.startswith("http"):
                abs_url = f"https://www.courtlistener.com{abs_url}"
            try:
                meta = client.get_opinion_text_with_metadata(abs_url)
                text = (meta.get("text") if meta else "") or ""
                chars = len(text)
            except Exception as e:
                chars = -1
                print(f"  ERROR on {cl['id']}: {type(e).__name__}: {str(e)[:80]}")
            sizes.append(chars)
            if 0 < chars <= CHAR_CAP:
                fits += 1
            rows.append({
                "court": court,
                "cluster_id": cl["id"],
                "date_filed": cl.get("date_filed", ""),
                "case_name": cl.get("case_name", ""),
                "char_count": chars,
                "fits_25k_cap": "yes" if 0 < chars <= CHAR_CAP else "no",
            })
            tag = "[OK]" if 0 < chars <= CHAR_CAP else "    "
            print(f"  {tag} {cl['id']:>10}  {chars:>7,}  {cl.get('date_filed')}  {cl.get('case_name','')[:55]}")

        valid_sizes = [s for s in sizes if s > 0]
        min_chars = min(valid_sizes) if valid_sizes else 0
        summary.append((court, len(clusters), fits, min_chars))

    # Write CSV
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["court", "cluster_id", "date_filed",
                                          "case_name", "char_count", "fits_25k_cap"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {OUT_CSV}")

    # Summary
    print("\n=== SUMMARY ===")
    print(f"  {'court':<10} {'n':>6}  {'fits<=25K':>10}  {'min_chars':>10}")
    for court, n, fits, min_c in summary:
        print(f"  {court:<10} {n:>6}  {fits:>10}  {min_c:>10,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
