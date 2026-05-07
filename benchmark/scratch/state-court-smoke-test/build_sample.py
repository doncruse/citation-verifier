"""Build a deduped state-court sample from v1's _raw_pool.json.

Mines federal-court source pleadings (the v1 raw pool — DCD/CAND/TXSD/ILND/MAD)
for citations to state COLR/COA cases, dedupes by (citation_text, parenthetical),
and writes the sample to sample.json.

State-tier filter:
  - Cited reporter is regional (A./P./N.E./N.W./S.W./S.E./So. + 2d/3d) OR
    state-specific COLR/IAC reporter, OR
  - Cited `court` field resolves to ('state', _) via gold_db.lookup_court(),
    excluding 'ljc' / 'gjc' (limited / general trial jurisdiction state courts).

Output: sample.json -- list of {tier_hint, citation_text, case_name,
parenthetical, year, court, citing_cluster_id, citing_court, v_status, v_url,
v_matched_name}.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from citation_verifier.gold_db import lookup_court

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_POOL = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "_raw_pool.json"
OUT = Path(__file__).parent / "sample.json"

SEED = 42
TARGET_N = 30

REGIONAL = re.compile(
    r"\b(?:A\.|P\.|N\.E\.|S\.E\.|S\.W\.|N\.W\.|So\.)\s?(?:2d|3d|4th)\b"
)
STATE_COLR = re.compile(
    r"\b(?:Cal\.|N\.Y\.|Ill\.|Mass\.|Tex\.|Pa\.|Ohio St\.|Mich\.|Wash\.|Fla\.|Ga\.|Va\.)"
    r"\s?(?:2d|3d|4th|5th|6th)\b"
)
STATE_IAC = re.compile(
    r"\b(?:Cal\. App\.|N\.Y\.S\.|A\.D\.|Ill\. App\.|Mass\. App\.|Tex\. App\."
    r"|Pa\. (?:Super|Commw)\.|Ohio App\.|Mich\. App\.|Wash\. App\.)"
    r"\s?(?:2d|3d|4th|5th|6th)\b"
)
FED_REPORTER = re.compile(
    r"\b(?:U\.S\.|S\.\s?Ct\.|F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.|L\.\s?Ed\.)"
)


def reporter_tier_hint(cite: str) -> str | None:
    s = cite or ""
    if FED_REPORTER.search(s):
        return None
    if STATE_IAC.search(s):
        return "state_iac"
    if STATE_COLR.search(s):
        return "state_colr"
    if REGIONAL.search(s):
        return "regional"
    return None


def court_tier_hint(court_id: str) -> str | None:
    """Return tier hint from courts-db lookup, excluding trial-level state."""
    if not court_id:
        return None
    sys, lvl = lookup_court(court_id)
    if sys != "state":
        return None
    if lvl in ("ljc", "gjc"):  # trial-level state, excluded per v1.3 design
        return None
    if lvl == "colr":
        return "state_colr"
    if lvl == "iac":
        return "state_iac"
    return "state_unknown_level"  # courts-db has it as state but no level


def is_state_tier(item: dict) -> tuple[str | None, str]:
    """Returns (tier_hint, source). Source = 'reporter' or 'court' or both."""
    rep_hint = reporter_tier_hint(item.get("citation_text", ""))
    court_hint = court_tier_hint(item.get("court", ""))
    if rep_hint and court_hint:
        return court_hint, "both"
    if court_hint:
        return court_hint, "court"
    if rep_hint:
        return rep_hint, "reporter"
    return None, ""


def main() -> None:
    data = json.loads(RAW_POOL.read_text(encoding="utf-8"))
    all_items = [it for items in data.values() for it in items]
    print(f"Total items in raw_pool: {len(all_items)}")

    candidates: list[dict] = []
    for it in all_items:
        tier, source = is_state_tier(it)
        if not tier:
            continue
        candidates.append({**it, "tier_hint": tier, "tier_source": source})
    print(f"State-tier candidates (raw): {len(candidates)}")

    # Dedup by (citation_text, parenthetical_first_60_chars) to handle
    # the intra-opinion duplication bug (full+short cites, etc).
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for it in candidates:
        key = (
            it.get("citation_text", ""),
            (it.get("parenthetical", "") or "")[:60],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    print(f"After dedup: {len(unique)}")

    # Tier breakdown
    from collections import Counter
    tier_counts = Counter(it["tier_hint"] for it in unique)
    print("Deduped by tier:")
    for t, n in tier_counts.most_common():
        print(f"  {t}: {n}")

    src_counts = Counter(it["tier_source"] for it in unique)
    print("By tier-detection source:")
    for s, n in src_counts.most_common():
        print(f"  {s}: {n}")

    status_counts = Counter(it.get("v_status", "") for it in unique)
    print("v_status (from v1 verifier run):")
    for s, n in status_counts.most_common():
        print(f"  {s}: {n}")

    # Sample TARGET_N (or all if smaller)
    random.seed(SEED)
    sample = unique if len(unique) <= TARGET_N else random.sample(unique, TARGET_N)
    print(f"Sample size: {len(sample)}")

    # Drop fields we don't need downstream
    keep_fields = (
        "tier_hint", "tier_source",
        "citation_text", "case_name", "parenthetical", "year", "court",
        "citing_cluster_id", "citing_court",
        "v_status", "v_url", "v_matched_name",
    )
    out = [{k: it.get(k) for k in keep_fields} for it in sample]
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
