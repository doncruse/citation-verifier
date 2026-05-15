"""
Step 1 of the real run: mine candidate citing opinions from CourtListener.

Per `REAL_RUN_DESIGN.md`:
- Federal: 12 per district × 6 districts (dcd/cand/txsd/ilnd/nysd/mad) = 72
- State:    2 per court × 10 courts (cal/calctapp/ny/nyappdiv/tex/texapp/
                                    fla/flaapp/ill/illappct)            = 20
- Date window: 2026-01-01 to 2026-04-30 (same as v1).
- Opinion text cap: 25,000 chars (LIMITATIONS.md — claude -p hangs above
  ~30-40K). Capping at 25K keeps headroom and matches the pilot.
- Buffer: try up to 25 candidates per court before giving up; design
  expects ~50% to fit under the cap.

For each source court we paginate the CL `/clusters/` endpoint
(date-filtered), shuffle the resulting cluster IDs with a fixed seed for
reproducibility, then iterate. For each cluster we fetch opinion text via
the canonical fallback chain (`get_opinion_text_with_metadata` —
plain_text → html_with_citations → html → html_lawbox → ...). State
opinions in CL frequently have empty plain_text but populate
`html_lawbox` / `xml_harvard`; the canonical helper handles that. We
accept the cluster if the resolved text is ≤ 25K chars.

Outputs (under benchmark/scratch/cl-coverage-offshoot/):
- citing_opinions/<cluster_id>.txt  one file per accepted opinion (plain
                                    text, post-fallback-chain extraction)
- citing_opinions/_manifest.csv     metadata per accepted cluster

Re-runnable: skips clusters whose .txt already exists; manifest rebuilds
from disk at the end of each run.

Run from the project root with the venv activated:
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/10_mine_citing_opinions.py

Smoke-test mode (one court, target=1):
    venv/Scripts/python.exe benchmark/scratch/cl-coverage-offshoot/10_mine_citing_opinions.py --smoke
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(find_dotenv(usecwd=False), override=True)
sys.path.insert(0, str(ROOT / "src"))

from citation_verifier.client import CourtListenerClient  # noqa: E402

HERE = Path(__file__).parent
OUT_DIR = HERE / "citing_opinions"
MANIFEST_CSV = OUT_DIR / "_manifest.csv"

DATE_FROM = "2026-01-01"
DATE_TO = "2026-04-30"

# 25,000-char cap on opinion text. Above ~30K, claude -p hangs (see
# LIMITATIONS.md). 25K leaves headroom. The cap is biased toward shorter
# opinions and will be disclosed in the writeup; stratification across
# cited tiers mitigates per-tier denominator bias.
OPINION_CHAR_CAP = 25_000

# Per-court candidate buffer. Iterate at most this many random clusters
# per court before giving up — design expects ~50% to fit under the cap.
PER_COURT_CANDIDATE_BUFFER = 25

# Random seed for the per-court shuffle of cluster IDs. Fixed for
# reproducibility; rerunning the script picks the same opinions absent
# CL data changes.
SEED = 42

# Paginate at most this many cluster pages per court. CL's default page
# size is 20; some courts (esp. state IACs) emit hundreds of opinions per
# 4-month window. Cap at 5000 clusters per court to bound wall time.
MAX_PAGES_PER_COURT = 250  # 250 × 20 = 5000 cluster cap
PAGE_SIZE = 20  # CL clusters endpoint default


@dataclass
class CourtSpec:
    court_id: str
    target_count: int
    level: str  # "federal_trial", "state_colr", or "state_iac"


COURTS: list[CourtSpec] = [
    # Federal districts (same 6 as v1) — 12 each → originally 72.
    # `nysd` set to 0: known CL ingestion bug (per user, 2026-05-14) —
    # CL returns 0 SDNY clusters for 2026 even though 2025 has hundreds.
    # Keeping the slot here for v1-comparability accounting; gap is
    # disclosed rather than filled with a substitute district.
    CourtSpec("dcd", 12, "federal_trial"),
    CourtSpec("cand", 12, "federal_trial"),
    CourtSpec("txsd", 12, "federal_trial"),
    CourtSpec("ilnd", 12, "federal_trial"),
    CourtSpec("nysd", 0, "federal_trial"),
    CourtSpec("mad", 12, "federal_trial"),
    # State COLRs + IACs for 5 largest states by caseload — 2 each.
    # `cal` set to 0: probe (size_probe_2026-05-14.md) found all 12
    # Cal Supreme opinions in window are >= 40K chars, none fit under
    # the 25K claude-p cap.
    # `texapp` set to 0: CL has the court_id registered but zero
    # opinions ingested in 2025 or 2026 — TX state appellate isn't in
    # CL's bulk. Documented gap.
    CourtSpec("cal", 0, "state_colr"),
    CourtSpec("calctapp", 2, "state_iac"),
    CourtSpec("ny", 2, "state_colr"),
    CourtSpec("nyappdiv", 2, "state_iac"),
    CourtSpec("tex", 2, "state_colr"),
    CourtSpec("texapp", 0, "state_iac"),
    CourtSpec("fla", 2, "state_colr"),
    # FL appellate: original design said `flaapp` but that ID does not
    # exist on CL. CL's `fladistctapp` ("District Court of Appeal of
    # Florida") is the umbrella ID and has data.
    CourtSpec("fladistctapp", 2, "state_iac"),
    CourtSpec("ill", 2, "state_colr"),
    CourtSpec("illappct", 2, "state_iac"),
]


@dataclass
class ManifestRow:
    cluster_id: int
    court_id: str
    level: str
    case_name: str
    date_filed: str
    char_count: int
    source_url: str


@dataclass
class CourtStats:
    court_id: str
    target: int
    accepted: int = 0
    skipped_existing: int = 0
    rejected_too_long: int = 0
    rejected_no_text: int = 0
    rejected_error: int = 0
    candidates_tried: int = 0
    clusters_listed: int = 0
    notes: list[str] = field(default_factory=list)


def _month_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Split [date_from, date_to] into roughly monthly half-open chunks.

    CL's clusters endpoint with `docket__court=<state>` is slow on wide
    date windows (60-150s/page for calctapp on 4 months) but fast on
    narrow windows (<1s on 2 weeks). Monthly chunking keeps every query
    snappy without dramatically inflating request count.
    """
    from datetime import date, timedelta
    y1, m1, d1 = (int(x) for x in date_from.split("-"))
    y2, m2, d2 = (int(x) for x in date_to.split("-"))
    start = date(y1, m1, d1)
    end = date(y2, m2, d2)
    chunks: list[tuple[str, str]] = []
    cur = start
    while cur <= end:
        # Last day of cur's month
        if cur.month == 12:
            next_first = date(cur.year + 1, 1, 1)
        else:
            next_first = date(cur.year, cur.month + 1, 1)
        chunk_end = min(next_first - timedelta(days=1), end)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return chunks


def fetch_clusters_for_court(
    client: CourtListenerClient,
    court_id: str,
    date_from: str,
    date_to: str,
    *,
    max_pages: int = MAX_PAGES_PER_COURT,
) -> list[dict[str, Any]]:
    """Paginate /clusters/ for a court+date window. Returns list of cluster JSONs.

    Uses the public `_request_with_retry` path so rate limit and 429
    handling are honored. Pagination follows the `next` cursor URL.
    Chunks the date range monthly to avoid per-page server timeouts on
    slow state-court queries.
    """
    # CL's clusters endpoint uses Django ORM lookups: filter by the
    # docket's court via `docket__court`. The bare `court` param 400s.
    # Adding `order_by=date_filed` turns the response from "scan and
    # lazy-count" into a fast indexed query — critical for large state
    # courts where the unsorted query times out at 15s.
    chunks = _month_chunks(date_from, date_to)
    clusters: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    pages = 0
    # Per-request timeout (s). Monthly chunks should mostly stay under
    # 10s, but cold-cache state queries can spike to ~30s. Give headroom.
    list_timeout = 90
    for chunk_from, chunk_to in chunks:
        if pages >= max_pages:
            break
        params: dict[str, Any] = {
            "docket__court": court_id,
            "date_filed__gte": chunk_from,
            "date_filed__lte": chunk_to,
            "order_by": "date_filed",
            "page_size": PAGE_SIZE,
        }
        url: str | None = f"{client.BASE_URL}/clusters/"
        while url and pages < max_pages:
            resp = client._request_with_retry(
                "GET", url, params=params, timeout=list_timeout,
            )
            data = resp.json()
            results = data.get("results", []) or []
            for r in results:
                rid = r.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    clusters.append(r)
            url = data.get("next")
            pages += 1
            # Only pass params on the first request of each chunk;
            # subsequent next-cursor URLs carry them already.
            params = {}
    return clusters


def try_accept_cluster(
    client: CourtListenerClient,
    cluster: dict[str, Any],
    *,
    court_id_fallback: str,
    level: str,
    char_cap: int,
) -> tuple[str | None, ManifestRow | None, str]:
    """Try to accept one cluster — fetch opinion text via canonical chain.

    Returns (opinion_text, manifest_row, reason). `opinion_text` is None
    if the cluster is rejected; `reason` is a short tag for stats.
    """
    cluster_id = cluster.get("id")
    if not cluster_id:
        return None, None, "no_id"

    absolute_url = cluster.get("absolute_url") or ""
    if not absolute_url:
        return None, None, "no_url"
    if not absolute_url.startswith("http"):
        absolute_url = f"https://www.courtlistener.com{absolute_url}"

    try:
        meta = client.get_opinion_text_with_metadata(absolute_url)
    except Exception as e:
        return None, None, f"error:{type(e).__name__}"

    if not meta:
        return None, None, "no_text"
    text = (meta.get("text") or "").strip()
    if not text:
        return None, None, "no_text"

    if len(text) > char_cap:
        return None, None, "too_long"

    # CL clusters don't expose court_id as a top-level field — it's on
    # the linked docket. Use the spec's court_id (which is exactly what
    # we filtered on) so the manifest stays useful.
    row = ManifestRow(
        cluster_id=int(cluster_id),
        court_id=cluster.get("court_id") or court_id_fallback,
        level=level,
        case_name=meta.get("case_name") or cluster.get("case_name") or "",
        date_filed=meta.get("date_filed") or cluster.get("date_filed") or "",
        char_count=len(text),
        source_url=absolute_url,
    )
    return text, row, "ok"


def mine_court(
    client: CourtListenerClient,
    spec: CourtSpec,
    *,
    rng: random.Random,
    out_dir: Path,
    char_cap: int,
    buffer: int,
) -> tuple[list[ManifestRow], CourtStats]:
    """Mine one source court — return (accepted manifest rows, stats)."""
    stats = CourtStats(court_id=spec.court_id, target=spec.target_count)
    accepted: list[ManifestRow] = []

    print(f"\n=== {spec.court_id} ({spec.level}, target={spec.target_count}) ===")
    if spec.target_count <= 0:
        print("  target=0; skipping (deliberately excluded — see CourtSpec comment)")
        stats.notes.append("excluded:target=0")
        return accepted, stats
    print("  fetching cluster list...", end="", flush=True)
    t0 = time.time()
    try:
        clusters = fetch_clusters_for_court(client, spec.court_id, DATE_FROM, DATE_TO)
    except Exception as e:
        stats.notes.append(f"list_error:{type(e).__name__}:{e}")
        print(f" FAILED: {e}")
        return accepted, stats
    stats.clusters_listed = len(clusters)
    print(f" {len(clusters):,} clusters in window  ({time.time()-t0:.1f}s)")

    if not clusters:
        stats.notes.append("no_clusters_in_window")
        return accepted, stats

    # Shuffle with seeded RNG for reproducibility. Stable across reruns
    # absent CL data changes.
    rng.shuffle(clusters)

    for cluster in clusters:
        if stats.accepted >= spec.target_count:
            break
        if stats.candidates_tried >= buffer:
            stats.notes.append(
                f"buffer_exhausted: tried {buffer}, accepted {stats.accepted}/{spec.target_count}"
            )
            break

        cluster_id = cluster.get("id")
        out_file = out_dir / f"{cluster_id}.txt"
        if out_file.exists():
            # Already mined in a prior run — count toward target without
            # re-fetching, but don't count against the candidate buffer
            # since it cost nothing.
            print(f"  [{stats.accepted+1}/{spec.target_count}] {cluster_id} (already on disk, reusing)")
            stats.skipped_existing += 1
            stats.accepted += 1
            # Reconstruct a manifest row from disk + cluster metadata
            try:
                char_count = len(out_file.read_text(encoding="utf-8"))
            except Exception:
                char_count = 0
            absolute_url = cluster.get("absolute_url") or ""
            if absolute_url and not absolute_url.startswith("http"):
                absolute_url = f"https://www.courtlistener.com{absolute_url}"
            accepted.append(ManifestRow(
                cluster_id=int(cluster_id),
                court_id=spec.court_id,
                level=spec.level,
                case_name=cluster.get("case_name") or "",
                date_filed=cluster.get("date_filed") or "",
                char_count=char_count,
                source_url=absolute_url,
            ))
            continue

        stats.candidates_tried += 1
        text, row, reason = try_accept_cluster(
            client, cluster,
            court_id_fallback=spec.court_id,
            level=spec.level,
            char_cap=char_cap,
        )
        if reason == "ok" and text and row:
            out_file.write_text(text, encoding="utf-8")
            accepted.append(row)
            stats.accepted += 1
            print(
                f"  [{stats.accepted}/{spec.target_count}] {row.cluster_id}  "
                f"{row.char_count:>6,} chars  {(row.case_name or '')[:60]}"
            )
        elif reason == "too_long":
            stats.rejected_too_long += 1
        elif reason == "no_text" or reason == "no_url":
            stats.rejected_no_text += 1
        else:
            stats.rejected_error += 1
            stats.notes.append(f"cluster {cluster_id}: {reason}")

    if stats.accepted < spec.target_count:
        stats.notes.append(
            f"undershoot: {stats.accepted}/{spec.target_count} after {stats.candidates_tried} candidates"
        )

    print(
        f"  -> accepted {stats.accepted}/{spec.target_count}; "
        f"tried {stats.candidates_tried}; "
        f"rej(long/notext/err)={stats.rejected_too_long}/{stats.rejected_no_text}/{stats.rejected_error}; "
        f"reused={stats.skipped_existing}"
    )
    return accepted, stats


def _load_existing_manifest(path: Path) -> dict[int, ManifestRow]:
    """Load existing manifest CSV (if any) into a cluster_id -> row map."""
    if not path.exists():
        return {}
    out: dict[int, ManifestRow] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                cid = int(r["cluster_id"])
            except (KeyError, TypeError, ValueError):
                continue
            out[cid] = ManifestRow(
                cluster_id=cid,
                court_id=r.get("court_id", ""),
                level=r.get("level", ""),
                case_name=r.get("case_name", ""),
                date_filed=r.get("date_filed", ""),
                char_count=int(r.get("char_count") or 0),
                source_url=r.get("source_url", ""),
            )
    return out


def write_manifest(rows: list[ManifestRow], path: Path) -> None:
    """Write manifest, merging with any existing rows on disk.

    Partial reruns (--only-courts) should add to the manifest, not
    clobber rows from earlier whole-cohort runs. Cluster_id is the key.
    """
    existing = _load_existing_manifest(path)
    merged: dict[int, ManifestRow] = dict(existing)
    for r in rows:
        merged[r.cluster_id] = r  # this run's row wins on conflict
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "cluster_id", "court_id", "level", "case_name",
            "date_filed", "char_count", "source_url",
        ])
        for cid in sorted(merged.keys(),
                          key=lambda c: (merged[c].court_id, c)):
            r = merged[cid]
            w.writerow([
                r.cluster_id, r.court_id, r.level, r.case_name,
                r.date_filed, r.char_count, r.source_url,
            ])


def main() -> int:
    ap = argparse.ArgumentParser(description="Mine citing opinions from CL for the real run")
    ap.add_argument("--smoke", action="store_true",
                    help="Smoke test: one federal court, target=1.")
    ap.add_argument("--seed", type=int, default=SEED,
                    help=f"RNG seed for per-court shuffle (default {SEED})")
    ap.add_argument("--buffer", type=int, default=PER_COURT_CANDIDATE_BUFFER,
                    help=f"Candidates tried per court before giving up (default {PER_COURT_CANDIDATE_BUFFER})")
    ap.add_argument("--char-cap", type=int, default=OPINION_CHAR_CAP,
                    help=f"Max opinion text chars (default {OPINION_CHAR_CAP:,})")
    ap.add_argument("--only-courts", type=str, default="",
                    help="Comma-separated court_ids to mine (default: all). Useful for resuming a single court.")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        courts = [CourtSpec("dcd", 1, "federal_trial")]
    elif args.only_courts:
        wanted = {c.strip() for c in args.only_courts.split(",") if c.strip()}
        courts = [c for c in COURTS if c.court_id in wanted]
        if not courts:
            print(f"ERROR: no matching courts in --only-courts={args.only_courts}")
            return 2
    else:
        courts = COURTS

    target_total = sum(c.target_count for c in courts)
    print(f"Mining {len(courts)} courts; target total = {target_total} accepted opinions")
    print(f"Window: {DATE_FROM} to {DATE_TO}")
    print(f"Cap:    {args.char_cap:,} chars per opinion")
    print(f"Buffer: {args.buffer} candidates per court")
    print(f"Seed:   {args.seed}")
    print(f"Out:    {OUT_DIR}")

    client = CourtListenerClient()
    if not client.api_token:
        print("\nWARNING: no COURTLISTENER_API_TOKEN found; running unauthenticated will be slow/throttled.")

    rng = random.Random(args.seed)
    all_rows: list[ManifestRow] = []
    all_stats: list[CourtStats] = []
    run_t0 = time.time()
    for spec in courts:
        rows, stats = mine_court(
            client, spec,
            rng=rng,
            out_dir=OUT_DIR,
            char_cap=args.char_cap,
            buffer=args.buffer,
        )
        all_rows.extend(rows)
        all_stats.append(stats)
        write_manifest(all_rows, MANIFEST_CSV)  # checkpoint every court

    elapsed = time.time() - run_t0
    print("\n=== SUMMARY ===")
    print(f"  wall time: {elapsed/60:.1f} min")
    print(f"  manifest:  {MANIFEST_CSV}")
    print()
    print(f"  {'court':<10} {'lvl':<14} {'accepted':>10}  {'tried':>6}  {'too_long':>8}  {'no_text':>8}  {'err':>5}  {'reused':>7}")
    for s in all_stats:
        spec = next((c for c in courts if c.court_id == s.court_id), None)
        lvl = spec.level if spec else ""
        print(
            f"  {s.court_id:<10} {lvl:<14} "
            f"{s.accepted:>4} / {s.target:<3}  {s.candidates_tried:>6}  "
            f"{s.rejected_too_long:>8}  {s.rejected_no_text:>8}  "
            f"{s.rejected_error:>5}  {s.skipped_existing:>7}"
        )
    total_accepted = sum(s.accepted for s in all_stats)
    total_target = sum(s.target for s in all_stats)
    print(f"\n  TOTAL: {total_accepted} / {total_target} accepted")

    undershoots = [s for s in all_stats if s.accepted < s.target]
    if undershoots:
        print("\n  Undershoots (target not met):")
        for s in undershoots:
            print(f"    {s.court_id}: {s.accepted}/{s.target}  notes={s.notes}")

    return 0 if total_accepted >= int(0.9 * total_target) else 1


if __name__ == "__main__":
    sys.exit(main())
