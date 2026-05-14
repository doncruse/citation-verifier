"""
Step 07: tier-classify each extracted citation, dedup, apply K=5 per-opinion
cap, and stratified-sample to N per tier.

Tier classification is reporter-pattern-based (no API calls). Four target tiers:
- SCOTUS    (federal, colr) — U.S., S. Ct., L. Ed.
- Circuit   (federal, iac)  — F.2d, F.3d, F.4th, F. App'x
- State_COLR — state-specific COLR reporters + regional reporters (default)
- State_IAC  — state intermediate appellate reporters (Cal. App., A.D., etc.)

Plus diagnostics: Federal_District (F. Supp.) and Other (everything else) so
nothing is silently dropped. Final stratified sample only draws from the four
target tiers.

Ambiguity caveat: regional reporters (A.3d, P.3d, N.E.3d, etc.) carry both
state COLR and state IAC opinions. We default them to State_COLR. The
authoritative tier comes from courts-db via the CL lookup that happens in
step 06. Post-hoc, we can flag rows where pattern-tier != lookup-tier — this
is a known limitation of pre-lookup stratification.

Cap semantics: for each (citing_cluster, cited_tier), keep at most K=5
citations. Dedup at (citing_cluster, citation_string, parenthetical) first
to remove pure intra-opinion duplicates, then apply cap.

Inputs : pilot_extractions/*.json
Outputs:
- stratified_pool.csv      : full deduped pool with tier + cap applied
- stratified_sample.csv    : 50-per-tier sample (or all, if smaller pool)
- stratify_summary.md      : narrative + distribution stats
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
EXTRACTIONS_DIR = HERE / "pilot_extractions"
SAMPLE_PER_TIER = 50  # final target per tier; pilot will likely undersample
K_PER_OPINION_PER_TIER = 5  # cap to prevent one opinion dominating a tier
SEED = 20260513

TARGET_TIERS = ("SCOTUS", "Circuit", "State_COLR", "State_IAC")


# ---- tier classification ----------------------------------------------------

# State IAC reporters — most specific first. Match before COLR patterns.
_STATE_IAC_PATTERNS = [
    r"\bCal\.\s*(?:Rptr\.|App\.)\s*(?:2d|3d|4th|5th|6th)?",  # Cal. App. 5th, Cal. Rptr.
    r"\bCal\.\s*App\.\b",
    r"\bA\.D\.\s*(?:2d|3d|4th)?",                              # NY appellate division
    r"\bN\.Y\.S\.\s*(?:2d|3d)?",                              # NY Supplement
    r"\bIll\.\s*App\.\s*(?:2d|3d)?",
    r"\bMass\.\s*App\.\s*Ct\.",
    r"\bTex\.\s*App\.",
    r"\bOhio\s*App\.\s*(?:2d|3d)?",
    r"\bMich\.\s*App\.",
    r"\bN\.J\.\s*Super\.",
    r"\bPa\.\s*Super\.",
    r"\bWash\.\s*App\.",
    r"\bMo\.\s*App\.",
    r"\bMd\.\s*App\.",
    r"\bN\.C\.\s*App\.",
    r"\bGa\.\s*App\.",
    r"\bConn\.\s*App\.",
    r"\bTenn\.\s*(?:Crim\.\s*)?App\.",
    r"\bAla\.\s*Crim\.\s*App\.",
    r"\bAla\.\s*Civ\.\s*App\.",
    r"\bKy\.\s*App\.",
    r"\bMinn\.\s*App\.",
    r"\bOhio\s*App\.",
    r"\bColo\.\s*App\.",
    r"\bAriz\.\s*App\.",
    r"\bN\.M\.\s*Ct\.\s*App\.",
    r"\bN\.M\.\s*App\.",
    r"\bWis\.\s*App\.",
    r"\bFla\.\s*App\.",
    r"\bFla\.\s*Dist\.\s*Ct\.\s*App\.",
]
_STATE_IAC_RE = re.compile("|".join(_STATE_IAC_PATTERNS))

# State COLR — state-specific high-court reporters.
# Note: trailing `\b` doesn't work after `\.` (period-then-space is non-word
# to non-word, no boundary). Rely on negative lookahead instead.
_STATE_COLR_PATTERNS = [
    r"\bCal\.\s*(?:2d|3d|4th|5th)\b",
    r"\bCal\.(?!\s*(?:App|Rptr))",                            # bare Cal. = old CA Supreme
    r"\bN\.Y\.\s*(?:2d|3d)(?!\s*S)",                          # N.Y.3d
    r"\bN\.Y\.(?=\s+\d)",                                      # bare N.Y. followed by digit
    r"\bMass\.(?!\s*App)",
    r"\bPa\.(?!\s*Super)",
    r"\bMd\.(?!\s*App)",
    r"\bVa\.(?!\s*App)",
    r"\bOhio\s*St\.\s*(?:2d|3d)?",
    r"\bMich\.(?!\s*App)",
    r"\bIll\.\s*(?:2d|3d)?(?!\s*App)",
    r"\bTex\.(?!\s*App)",
    r"\bWash\.\s*(?:2d)?(?!\s*App)",
    r"\bWis\.\s*(?:2d|3d)?(?!\s*App)",
    r"\bOr\.(?!\s*App)",
    r"\bN\.C\.(?!\s*App)",
    r"\bN\.J\.(?!\s*Super)",
    r"\bConn\.(?!\s*App)",
    r"\bGa\.(?!\s*App)",
    r"\bIowa\b",
    r"\bColo\.(?!\s*App)",
    r"\bAriz\.(?!\s*App)",
    r"\bMinn\.(?!\s*App)",
    r"\bMo\.(?!\s*App)",
    r"\bKy\.(?!\s*App)",
    r"\bAla\.(?!\s*(?:Crim|Civ)\s*App)",
    r"\bN\.M\.(?!\s*(?:Ct|App))",
    r"\bFla\.(?!\s*App|\s*Dist)",
]
_STATE_COLR_RE = re.compile("|".join(_STATE_COLR_PATTERNS))

# Regional reporters — ambiguous (mostly COLR, sometimes IAC). Default to COLR.
_REGIONAL_RE = re.compile(r"\b(?:A|P|N\.E|N\.W|S\.E|S\.W|So)\.\s*(?:2d|3d)?\b")

# Federal
_SCOTUS_RE = re.compile(r"\bU\.?\s?S\.?\b|S\.\s*Ct\.|L\.\s*Ed\.")
_CIRCUIT_RE = re.compile(r"\bF\.?\s?(?:2d|3d|4th)\b|F\.\s*App'x\b")
_FED_DISTRICT_RE = re.compile(r"\bF\.\s*Supp\.\s*(?:2d|3d)?\b")


def tier_from_cite(cite: str) -> str:
    """Coarse tier inference from the citation string.

    Returns one of: SCOTUS, Circuit, State_COLR, State_IAC, Federal_District, Other.
    """
    c = cite or ""

    # Order matters: most specific first
    if _SCOTUS_RE.search(c):
        return "SCOTUS"
    if _CIRCUIT_RE.search(c):
        return "Circuit"
    if _FED_DISTRICT_RE.search(c):
        return "Federal_District"
    if _STATE_IAC_RE.search(c):
        return "State_IAC"
    if _STATE_COLR_RE.search(c):
        return "State_COLR"
    if _REGIONAL_RE.search(c):
        return "State_COLR"  # default for ambiguous regional reporters
    return "Other"


# ---- main ------------------------------------------------------------------

def main():
    rng = random.Random(SEED)

    # 1. Load all extracted citations into a flat list
    flat = []
    for f in sorted(EXTRACTIONS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        all_cites = data.get("citations_all") or (
            (data.get("citations_appears_in_source") or [])
            + (data.get("citations_near_miss_after_normalize") or [])
            + (data.get("citations_not_in_source") or [])
        )
        for c in all_cites:
            if not isinstance(c, dict):
                continue
            cite_str = (c.get("citation_string") or "").strip()
            if not cite_str:
                continue
            tier = tier_from_cite(cite_str)
            flat.append({
                "citing_tier": data.get("tier_label", ""),
                "citing_cluster": data.get("cluster_id", ""),
                "citing_case": (data.get("case_name") or "")[:50],
                "citation_string": cite_str,
                "cited_case_name": (c.get("cited_case_name") or "").strip(),
                "year": c.get("year"),
                "court_hint": c.get("court_hint"),
                "parenthetical": c.get("parenthetical"),
                "sentence_context": (c.get("sentence_context") or "")[:300],
                "cited_tier": tier,
                "appears_in_source_class": c.get("_classification"),
            })

    if not flat:
        print("no citations found in pilot_extractions/ — re-run extractions first")
        return

    print(f"loaded {len(flat)} extracted citations from {len(set(r['citing_cluster'] for r in flat))} citing opinions")

    # 2. Dedup at (citing_cluster, citation_string, parenthetical)
    seen = set()
    deduped = []
    for r in flat:
        key = (r["citing_cluster"], r["citation_string"], r.get("parenthetical") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    print(f"after intra-opinion dedup: {len(deduped)} (removed {len(flat)-len(deduped)} duplicates)")

    # 3. Apply K cap per (citing_cluster, cited_tier)
    by_op_tier = defaultdict(list)
    for r in deduped:
        by_op_tier[(r["citing_cluster"], r["cited_tier"])].append(r)
    capped = []
    capped_dropped = 0
    for k, rows in by_op_tier.items():
        if len(rows) <= K_PER_OPINION_PER_TIER:
            capped.extend(rows)
        else:
            rng.shuffle(rows)
            capped.extend(rows[:K_PER_OPINION_PER_TIER])
            capped_dropped += len(rows) - K_PER_OPINION_PER_TIER
    print(f"after K={K_PER_OPINION_PER_TIER} cap: {len(capped)} (dropped {capped_dropped} over-cap rows)")

    # Save the capped pool
    with open(HERE / "stratified_pool.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(capped[0].keys()))
        w.writeheader()
        w.writerows(capped)
    print(f"wrote stratified_pool.csv ({len(capped)} rows)")

    # 4. Distribution
    by_tier = Counter(r["cited_tier"] for r in capped)
    print("\nNatural distribution after dedup + cap:")
    for t in ("SCOTUS", "Circuit", "State_COLR", "State_IAC", "Federal_District", "Other"):
        n = by_tier.get(t, 0)
        target = SAMPLE_PER_TIER if t in TARGET_TIERS else "-"
        status = ""
        if t in TARGET_TIERS:
            status = " ✓ enough" if n >= SAMPLE_PER_TIER else f" need {SAMPLE_PER_TIER-n} more"
        print(f"  {t:<18} {n:>4}   target={target}{status}")

    # 5. Stratified sample 50 per target tier (or all if pool < 50)
    by_target = defaultdict(list)
    for r in capped:
        if r["cited_tier"] in TARGET_TIERS:
            by_target[r["cited_tier"]].append(r)
    sample = []
    for tier in TARGET_TIERS:
        rows = by_target.get(tier, [])
        if len(rows) > SAMPLE_PER_TIER:
            rng.shuffle(rows)
            sample.extend(rows[:SAMPLE_PER_TIER])
        else:
            sample.extend(rows)
    print(f"\nstratified sample: {len(sample)} rows (target {SAMPLE_PER_TIER*len(TARGET_TIERS)})")

    # Save
    if sample:
        with open(HERE / "stratified_sample.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(sample[0].keys()))
            w.writeheader()
            w.writerows(sample)
        print(f"wrote stratified_sample.csv ({len(sample)} rows)")

    # 6. Narrative
    lines = ["# Stratification summary", ""]
    lines.append(f"- Total citations extracted: {len(flat)}")
    lines.append(f"- After intra-opinion dedup: {len(deduped)}")
    lines.append(f"- After K={K_PER_OPINION_PER_TIER} cap per (citing_opinion, cited_tier): {len(capped)}")
    lines.append("")
    lines.append("## Pool distribution by cited tier")
    lines.append("")
    lines.append("| tier | n in pool | target | sample |")
    lines.append("|---|---|---|---|")
    for t in ("SCOTUS", "Circuit", "State_COLR", "State_IAC", "Federal_District", "Other"):
        n = by_tier.get(t, 0)
        if t in TARGET_TIERS:
            sample_n = min(n, SAMPLE_PER_TIER)
            tgt = SAMPLE_PER_TIER
        else:
            sample_n = "(not sampled)"
            tgt = "—"
        lines.append(f"| {t} | {n} | {tgt} | {sample_n} |")
    lines.append("")
    lines.append("## Volume needed to hit 50/50/50/50")
    lines.append("")
    n_citing = len(set(r["citing_cluster"] for r in capped))
    lines.append(f"Current pool from {n_citing} citing opinions. Per-citing-opinion yield:")
    for t in TARGET_TIERS:
        n = by_tier.get(t, 0)
        if n_citing == 0:
            continue
        per_op = n / n_citing
        needed = SAMPLE_PER_TIER / per_op if per_op > 0 else float("inf")
        lines.append(f"- {t}: {n}/{n_citing} = {per_op:.2f} per opinion → need {needed:.0f} citing opinions for {SAMPLE_PER_TIER}")
    lines.append("")
    lines.append("Caveats:")
    lines.append("- Regional reporters (A.3d, P.3d, N.E.3d, etc.) default to State_COLR — actual COLR/IAC split won't be known until CL lookup.")
    lines.append("- Mixed citing-opinion source (federal + state) gives different yields per tier than federal-only. State citing opinions will dominate State_COLR + State_IAC yield.")
    lines.append("")
    (HERE / "stratify_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote stratify_summary.md")


if __name__ == "__main__":
    main()
