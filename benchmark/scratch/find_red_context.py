"""Find each Sonnet@FT Red parenthetical in its citing opinion, dump
context to a file. Output is markdown for easy reading."""
from pathlib import Path
import re

CACHES = [
    Path("benchmark/pilot_a/cited_opinion_cache"),
    Path("benchmark/releases/v1/citing_opinion_cache"),
]

# (citing_cluster, cited_cluster, cited_name, citing_court, search_phrases)
# search_phrases: ordered list of distinctive substrings to try locating
RED_PAIRS = [
    {
        "row_id": 5,
        "citing_cluster": 10848714,
        "cited_cluster": 222130,
        "cited_name": "United States v. Moore",
        "citing_court": "dcd",
        "search_phrases": [
            "intrinsic to the charged crime",
            "wholly unregulated by Rule 404",
            "United States v. Moore",
        ],
    },
    {
        "row_id": 8,
        "citing_cluster": 10848672,
        "cited_cluster": 118510,
        "cited_name": "Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co.",
        "citing_court": "dcd",
        "search_phrases": [
            "demand for unreasonable precision",
            "verbal precision",
            "Festo Corp",
        ],
    },
    {
        "row_id": 14,
        "citing_cluster": 10851116,
        "cited_cluster": 112510,
        "cited_name": "Irwin v. Department of Veterans Affairs",
        "citing_court": "dcd",
        "search_phrases": [
            "Irwin v. Department of Veterans Affairs",
            "Irwin v. Dep",
            "DCHRA was recently amended",
        ],
    },
    {
        "row_id": 70,
        "citing_cluster": 10851548,
        "cited_cluster": 112262,
        "cited_name": "Maleng v. Cook",
        "citing_court": "txsd",
        "search_phrases": [
            "Maleng v. Cook",
            "usually “custody” signifies",
            "incarceration or supervised release",
        ],
    },
    {
        "row_id": 82,
        "citing_cluster": 10849944,
        "cited_cluster": 2996534,
        "cited_name": "Omosegbon",
        "citing_court": "ilnd",
        "search_phrases": [
            "Omosegbon",
            "sovereign immunity barred due process",
            "academic freedom",
        ],
    },
]


def load_opinion(cluster_id: int) -> str:
    for d in CACHES:
        p = d / f"{cluster_id}.txt"
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    return ""


def find_context(text: str, phrases: list[str], chars_before: int = 400,
                 chars_after: int = 600) -> tuple[int, str] | None:
    for phrase in phrases:
        idx = text.find(phrase)
        if idx == -1:
            # Try case-insensitive
            lower_idx = text.lower().find(phrase.lower())
            if lower_idx != -1:
                idx = lower_idx
        if idx != -1:
            start = max(0, idx - chars_before)
            end = min(len(text), idx + len(phrase) + chars_after)
            snippet = text[start:end]
            return (idx, snippet, phrase)
    return None


lines = []
for r in RED_PAIRS:
    lines.append(f"## row_id={r['row_id']} | {r['cited_name']} ({r['citing_court']})\n")
    lines.append(f"**Cited opinion ({r['cited_cluster']}):** "
                 f"https://www.courtlistener.com/opinion/{r['cited_cluster']}/\n")
    lines.append(f"**Citing opinion ({r['citing_cluster']}):** "
                 f"https://www.courtlistener.com/opinion/{r['citing_cluster']}/\n")

    op = load_opinion(r["citing_cluster"])
    if not op:
        lines.append(f"\n*Citing opinion text not in cache.*\n")
        continue

    found = find_context(op, r["search_phrases"])
    if not found:
        lines.append(f"\n*Could not locate parenthetical in citing opinion (tried "
                     f"{len(r['search_phrases'])} phrases).*\n")
        continue

    idx, snippet, phrase = found
    lines.append(f"\n**Parenthetical found at offset {idx:,} (matched: `{phrase}`)**\n")
    lines.append("```\n" + snippet.strip() + "\n```\n")

out_path = Path("scratch/red_context.md")
out_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {out_path}")
print(f"  {len(RED_PAIRS)} reds processed")
