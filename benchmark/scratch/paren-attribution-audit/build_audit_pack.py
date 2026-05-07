"""Build a review pack for the parenthetical-mis-attribution audit.

Motivation: the 2026-05-04 full-text Red audit found 3 of 5 Sonnet@FT
Reds were eyecite parenthetical mis-attribution bugs (parenthetical
attached to the wrong case in chained citations). That's a 60% bug rate
*on Reds*. The same misattribution likely affects Greens and Yellows,
but we don't have a baseline rate. v1.3's mining pipeline overhaul fixes
this; calibrating the v1 prevalence rate informs the v1↔v1.3 comparison.

Approach: random 30 non-Red gold pairs from v1's Sonnet@FT pass. For each,
locate the parenthetical in the citing opinion and extract a context
window. Heuristic flag: does the cited case's canonical_name appear in
the 300 chars preceding the parenthetical? If not, suspected mis-attrib.

Output:
  audit_pack.csv -- one row per sampled pair, ready for human review.
    Columns: idx, citing_cluster_id, cited_cluster_id, cited_name,
             cited_cite_string, parenthetical, ctx_before_300, ctx_after_300,
             heuristic_flag (Y/N/UNFOUND), heuristic_reason,
             user_classification (blank for human input),
             user_notes (blank for human input).
  summary.txt  -- heuristic flag-rate; instructions for the human review pass.
"""
from __future__ import annotations

import csv
import random
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from citation_verifier.gold_db import GoldDB  # noqa: E402

GOLD_DB = PROJECT_ROOT / "benchmark" / "gold_db" / "gold.db"
CITING_CACHE = PROJECT_ROOT / "benchmark" / "releases" / "v1" / "citing_opinion_cache"
OUT_CSV = Path(__file__).parent / "audit_pack.csv"
OUT_SUMMARY = Path(__file__).parent / "summary.txt"

SEED = 42
SAMPLE_N = 30
CTX_BEFORE = 500
CTX_AFTER = 300


# Map smart quotes / dashes / whitespace to canonical forms so a
# parenthetical normalized at mining time can be relocated in the
# original opinion text. Keep simple and conservative.
_QUOTE_FIX = str.maketrans({
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "–": "-", "—": "-",
    " ": " ",
})


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = s.translate(_QUOTE_FIX)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _find_paren_in_opinion(opinion: str, paren: str) -> int:
    """Return the start index of `paren` in `opinion`, or -1.

    Try (a) raw match, (b) normalized-both match, then (c) match on the
    first 60 chars of the parenthetical (parentheticals captured at
    mining time can have trailing junk that doesn't appear verbatim in
    the original).
    """
    if not opinion or not paren:
        return -1
    if paren in opinion:
        return opinion.index(paren)

    norm_op = _normalize(opinion)
    norm_paren = _normalize(paren)
    if norm_paren in norm_op:
        # Build an offset map from normalized index -> original index.
        # Cheaper alternative: just search for the first 60 chars in the
        # original; almost always uniquely locates the parenthetical.
        head = norm_paren[:60]
        norm_to_orig = _normalize_offset_map(opinion)
        idx = norm_op.find(head)
        if idx >= 0 and idx < len(norm_to_orig):
            return norm_to_orig[idx]

    head = _normalize(paren)[:60]
    if head:
        norm_op = _normalize(opinion)
        idx = norm_op.find(head)
        if idx >= 0:
            norm_to_orig = _normalize_offset_map(opinion)
            if idx < len(norm_to_orig):
                return norm_to_orig[idx]
    return -1


def _normalize_offset_map(opinion: str) -> list[int]:
    """For each char in `_normalize(opinion)`, return the corresponding
    index in the original `opinion`. Conservative: collapses whitespace
    runs to a single space and maps all the run's chars to the run's
    start in the original.
    """
    out: list[int] = []
    in_ws = False
    ws_start = 0
    for i, ch in enumerate(opinion):
        if ch in _QUOTE_FIX:
            ch = ch.translate(_QUOTE_FIX)
        if ch.isspace():
            if not in_ws:
                in_ws = True
                ws_start = i
                out.append(ws_start)
        else:
            in_ws = False
            out.append(i)
    return out


def _heuristic_check(ctx_before: str, cited_name: str) -> tuple[str, str]:
    """Does the cited case name appear in the preceding context?

    Returns (flag, reason) where flag in {'Y' meaning likely-correct,
    'N' meaning suspected-misattribution, 'UNFOUND' if context empty}.
    """
    if not ctx_before:
        return "UNFOUND", "no context (parenthetical not found in opinion)"

    cited_name_n = _normalize(cited_name).lower()
    ctx_n = _normalize(ctx_before).lower()

    # Try the full canonical name.
    if cited_name_n and cited_name_n in ctx_n:
        return "Y", "full canonical_name appears in preceding 500 chars"

    # Try just the case-name prefix up to "v." or "in re" — many CL
    # canonical names embed the full caption with extra punctuation
    # that won't survive eyecite's slicing into the citing opinion.
    parts = re.split(r"\sv\.\s", cited_name_n, maxsplit=1)
    plaintiff = parts[0].strip()
    defendant = (parts[1].split(",")[0].strip() if len(parts) > 1 else "")

    # Strip leading "in re ".
    plaintiff = re.sub(r"^in re\s+", "", plaintiff)

    if plaintiff and len(plaintiff) >= 4 and plaintiff in ctx_n:
        return "Y", f"plaintiff name {plaintiff!r} appears in preceding context"
    if defendant and len(defendant) >= 4 and defendant in ctx_n:
        return "Y", f"defendant name {defendant!r} appears in preceding context"

    # Common short-cite forms like "Id." or just "Foo," signal the
    # parenthetical is attached via continuation. Hard to ground-truth
    # heuristically; mark suspicious for human review.
    return "N", (
        f"neither full canonical_name nor plaintiff/defendant "
        f"({plaintiff!r}/{defendant!r}) appears in preceding 500 chars"
    )


def main() -> None:
    db = GoldDB(GOLD_DB)
    rows = db.conn.execute(
        """
        SELECT
            av.proposition_id,
            av.candidate_cluster_id AS cited_cluster_id,
            av.verdict,
            p.text AS parenthetical,
            cr.citing_cluster_id,
            cr.parenthetical AS citation_paren,
            c.canonical_name AS cited_name,
            c.cite_string   AS cited_cite_string,
            c.court_id      AS cited_court_id
        FROM assessor_verdicts av
        JOIN propositions p ON av.proposition_id = p.proposition_id
        LEFT JOIN citation_rows cr ON cr.proposition_id = av.proposition_id
        LEFT JOIN cases c ON c.cluster_id = av.candidate_cluster_id
        WHERE av.source = 'gold_pair'
          AND av.assessor_model = 'sonnet-4.6'
          AND av.assessor_prompt_version = 'v1-fulltext'
          AND av.verdict IN ('green', 'yellow')
        """
    ).fetchall()
    pairs = [dict(r) for r in rows]
    db.close()
    print(f"Loaded {len(pairs)} non-Red Sonnet@FT gold pairs from v1")

    # Sample
    random.seed(SEED)
    sample = random.sample(pairs, min(SAMPLE_N, len(pairs)))
    print(f"Sampled {len(sample)} (seed={SEED})")

    fieldnames = [
        "idx", "verdict",
        "citing_cluster_id", "cited_cluster_id",
        "cited_name", "cited_cite_string", "cited_court_id",
        "parenthetical",
        "ctx_before", "matched_paren", "ctx_after",
        "heuristic_flag", "heuristic_reason",
        "user_classification",  # bug | clean | ambiguous
        "user_notes",
    ]

    n_unfound = 0
    n_flagged = 0
    n_clean = 0
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for i, pair in enumerate(sample, 1):
            citing_id = pair["citing_cluster_id"]
            cache_path = CITING_CACHE / f"{citing_id}.txt"
            if not cache_path.exists():
                # Parenthetical can't be located without source text.
                n_unfound += 1
                w.writerow({
                    "idx": i,
                    "verdict": pair["verdict"],
                    "citing_cluster_id": citing_id,
                    "cited_cluster_id": pair["cited_cluster_id"],
                    "cited_name": pair["cited_name"],
                    "cited_cite_string": pair["cited_cite_string"],
                    "cited_court_id": pair["cited_court_id"],
                    "parenthetical": pair["parenthetical"],
                    "ctx_before": "",
                    "matched_paren": "",
                    "ctx_after": "",
                    "heuristic_flag": "UNFOUND",
                    "heuristic_reason": "citing opinion not in cache",
                    "user_classification": "",
                    "user_notes": "",
                })
                continue

            opinion = cache_path.read_text(encoding="utf-8", errors="replace")
            paren = pair["parenthetical"] or ""
            idx = _find_paren_in_opinion(opinion, paren)

            if idx < 0:
                n_unfound += 1
                ctx_before = ""
                matched = ""
                ctx_after = ""
                flag = "UNFOUND"
                reason = "parenthetical text not located in citing opinion"
            else:
                ctx_before = opinion[max(0, idx - CTX_BEFORE):idx]
                matched = opinion[idx:idx + len(paren)]
                ctx_after = opinion[idx + len(paren): idx + len(paren) + CTX_AFTER]
                flag, reason = _heuristic_check(ctx_before, pair["cited_name"] or "")

            if flag == "N":
                n_flagged += 1
            elif flag == "Y":
                n_clean += 1

            w.writerow({
                "idx": i,
                "verdict": pair["verdict"],
                "citing_cluster_id": citing_id,
                "cited_cluster_id": pair["cited_cluster_id"],
                "cited_name": pair["cited_name"],
                "cited_cite_string": pair["cited_cite_string"],
                "cited_court_id": pair["cited_court_id"],
                "parenthetical": paren,
                "ctx_before": ctx_before,
                "matched_paren": matched,
                "ctx_after": ctx_after,
                "heuristic_flag": flag,
                "heuristic_reason": reason,
                "user_classification": "",
                "user_notes": "",
            })

    summary = (
        f"Parenthetical-attribution audit pack -- {SAMPLE_N} random "
        f"non-Red Sonnet@FT gold pairs (seed={SEED})\n\n"
        f"Total pairs: {len(sample)}\n"
        f"Heuristic clean (cited name found in preceding 500c): {n_clean}\n"
        f"Heuristic flagged (cited name NOT in preceding 500c): {n_flagged}\n"
        f"Unfound (parenthetical not located in citing opinion):  {n_unfound}\n\n"
        f"Next step: open audit_pack.csv, read ctx_before / matched_paren / "
        f"ctx_after for each row, and fill in user_classification (bug | "
        f"clean | ambiguous) plus user_notes. Heuristic flags are a hint, "
        f"not ground truth -- the false-positive rate is unknown until the "
        f"manual pass classifies enough rows. Same review method as the "
        f"2026-05-04 5-Red audit.\n"
    )
    OUT_SUMMARY.write_text(summary, encoding="utf-8")
    print()
    print(summary)


if __name__ == "__main__":
    main()
