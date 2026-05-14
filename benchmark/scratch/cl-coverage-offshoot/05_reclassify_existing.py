"""
Bring the 2 already-extracted opinions (Whole Foods, Wojcicki) into the
same three-bucket schema 04_rerun_timeouts.py writes:

- citations_appears_in_source
- citations_near_miss_after_normalize
- citations_not_in_source
- citations_all

So all 5 pilot extractions can be analyzed together.

The original 03_pilot_extraction.py wrote citations_valid + citations_hallucinated
based on strict substring matching. This script re-buckets without re-extracting
(no API calls).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
EXTRACTIONS_DIR = HERE / "pilot_extractions"
OPINIONS_DIR = HERE / "pilot_opinions"

_SMART_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
})


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_SMART_QUOTE_MAP)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def classify(citation: str, opinion_text: str) -> str:
    cite = (citation or "").strip()
    if not cite:
        return "empty"
    if cite in opinion_text:
        return "appears_in_source"
    if normalize(cite) in normalize(opinion_text):
        return "near_miss_after_normalize"
    return "not_in_source"


def main():
    for f in sorted(EXTRACTIONS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        # Skip files already in the new schema
        if "citations_all" in data:
            continue
        # Need the original opinion text
        op_file = OPINIONS_DIR / f"{data['cluster_id']}.txt"
        if not op_file.exists():
            print(f"  {f.name}: opinion file missing, skipping")
            continue
        op_text = op_file.read_text(encoding="utf-8")
        # The old schema had citations_valid + citations_hallucinated;
        # union them and re-classify all
        old_valid = data.get("citations_valid") or []
        old_halluc = data.get("citations_hallucinated") or []
        all_cites = list(old_valid) + list(old_halluc)

        buckets = {"appears_in_source": [], "near_miss_after_normalize": [], "not_in_source": []}
        for c in all_cites:
            if not isinstance(c, dict):
                continue
            cls = classify(c.get("citation_string", ""), op_text)
            if cls in buckets:
                c["_classification"] = cls
                buckets[cls].append(c)

        # Write in the new shape — keep old keys around for traceability, but
        # the new keys take precedence
        new_data = {
            **data,
            "citations_appears_in_source": buckets["appears_in_source"],
            "citations_near_miss_after_normalize": buckets["near_miss_after_normalize"],
            "citations_not_in_source": buckets["not_in_source"],
            "citations_all": all_cites,
            "_reclassified_from": "valid+hallucinated -> appears/near_miss/not_in_source",
        }
        # Drop the old keys to avoid confusion
        new_data.pop("citations_valid", None)
        new_data.pop("citations_hallucinated", None)

        f.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {f.name}: reclassified — appears={len(buckets['appears_in_source'])}  near_miss={len(buckets['near_miss_after_normalize'])}  not_in_source={len(buckets['not_in_source'])}")


if __name__ == "__main__":
    main()
