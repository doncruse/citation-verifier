"""Build a candidate fake-citation corpus from Damien Charlotin's database.

Source: scratch/Charlotin-hallucination_cases.csv — 1,598 court rulings that
addressed AI-hallucinated material (manually downloaded; the site 403s
automated fetchers). The CSV is case-level, but the `Hallucination Items`
field very often quotes the fabricated citation strings verbatim inside
"Fabricated: Case Law" findings, so a large slice is minable without
processing the linked rulings.

Pipeline (offline — no API calls):
1. Keep USA rows (CourtListener only covers US courts).
2. Split `Hallucination Items` into (category, description) items; keep
   "Fabricated: Case Law".
3. Extract full case citations from each description with eyecite, taking
   the *verbatim* text span (so docket numbers, pin cites, and the original
   parenthetical survive for the verifier to parse).
4. Flag citations that appear AFTER a contrast marker ("unrelated",
   "actually", "the correct citation is", ...) — those are typically the
   REAL case the court found instead of the fake, and must not enter a
   fake corpus.
5. Dedup (within the corpus and against known_fake_citations.json) and
   write tests/data/charlotin_candidate_fakes.json.

The output is *candidates*: court-confirmed fabrications per Charlotin's
data, but unverified by us. Promotion into known_fake_citations.json happens
only after a live verification/adjudication pass.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from eyecite import get_citations
from eyecite.models import FullCaseCitation
from eyecite.tokenizers import AhocorasickTokenizer

_SRC = Path(__file__).parent.parent / "scratch" / "Charlotin-hallucination_cases.csv"
_KNOWN_FAKES = Path(__file__).parent / "data" / "known_fake_citations.json"
# Named to match record_benchmark_cassette.py's --corpus-name convention:
# `python tests/record_benchmark_cassette.py --corpus-name charlotin` (live)
# records the cassette + baseline verdicts for the whole candidate set.
_OUT = Path(__file__).parent / "data" / "charlotin_corpus.json"

_TOKENIZER = AhocorasickTokenizer()

# Phrases that introduce the REAL case a court found in place of the fake
# ("...identified only an unrelated Jackson v. Lew..."). Any citation whose
# span starts after one of these is flagged, not kept.
_CONTRAST_MARKERS = re.compile(
    r"unrelated|actual(?:ly)?\b|instead|correct citation|correct cite"
    r"|real (?:case|decision|opinion)|appears? to (?:be|refer|match)"
    r"|likely intended"
    r"|similar(?:ly)? (?:titled|named)|identified only|in fact"
    r"|corresponds to|belongs to|refers to a different"
    r"|corrected (?:by|to|as)|different case|existing case"
    # 2026-06-11 triage additions (charlotin retro "Corpus hygiene"): the
    # finder verbs that poisoned 15 bucket-A entries. Bare "court found" is
    # deliberately NOT a marker — ambiguous between "court found the
    # citation to FAKE" and "court found REAL instead"; those items are
    # handled by _ADJUDICATED instead.
    r"|closest (?:possible )?match|intended (?:citation was|to cite)"
    r"|citation maps to|citation points to|traced to|falls within"
    r"|search retrieved|may relate to|nearby real citation|the only real",
    re.IGNORECASE,
)

# Per-entry adjudication from the 2026-06-11 live run
# (scratch/charlotin_bucketA_adjudication.csv), keyed by _core_cite_key.
# ("drop", reason): poisoned extraction with no safe marker, or a Charlotin
# mislabel (real, correctly-cited case). ("relabel:<label>", reason): real
# case with a fabricated *detail* — kept as a future detection target, not
# a NOT_FOUND assertion.
_ADJUDICATED: dict[str, tuple[str, str]] = {
    # Poisoned extractions whose item text defeats the markers:
    "463|fsupp2d|928": ("drop", "A2: court found Lampe instead; 'court found' too ambiguous to mark"),
    "479|fsupp3d|1039": ("drop", "C: court located Curtis v. Oliver instead of fake Wallace cite"),
    # Charlotin mislabels — real, correctly-cited cases:
    "233|orapp|339": ("drop", "A4: Tubra v. Cooke is real at 233 Or App 339"),
    "112|dpr|573": ("drop", "A5: Colon v. Romero Barcelo real; fabricated QUOTE, not case"),
    "731|f3d|1196": ("drop", "A8: Kidd v. Mando real 11th Cir. case"),
    "712|nw2d|828": ("drop", "A13: State ex rel. Stenehjem v. FreeEats.com real"),
    "2012|nd|135": ("drop", "A14: State v. Clark, 2012 ND 135 real"),
    "2012|nd|176": ("drop", "A15: State v. $44,140.00, 2012 ND 176 real"),
    "498|so2d|463": ("drop", "A24: Perez v. Zazo real Fla. 3d DCA case"),
    "282|f3d|147": ("drop", "A39: Chambers v. Time Warner real; quote fabricated"),
    "277|f3d|535": ("drop", "A44: Hensley v. Alcon real; brief typo 'Henlsey'"),
    "201|ill2d|476": ("drop", "A46: In re D.F., 201 Ill. 2d 476 real"),
    # B/C sweep (2026-06-10 session): poisoned/mislabeled entries whose
    # finder verbs are too generic to be markers ("returns", "There is a"):
    "2019WL1036077": ("drop", "B: real Jones v. Jones the Doe v. Roe docket number 'returns'"),
    "639|sw3d|651": ("drop", "B: 'There is a Nandigam...' = real case; fake was typo'd 2022 WLE 1512346"),
    "2017|nyslipop|50417": ("drop", "C: party's offered REPLACEMENT for the fakes, not a court-confirmed fake"),
    "174|dpr|650": ("drop", "C: fabricated QUOTE, not case (same ruling/pattern as A5 Colon)"),
    # Post-fix replay finding: CL resolves 144 Cal.App.4th 925 to cluster
    # "Manfer v. Manfer" = In re Marriage of Manfer — real case, name
    # matches. Charlotin's court complained of inconsistent citations, not
    # nonexistence (A43 was misclassified as Bug 1 in the adjudication CSV).
    "144|calapp4th|925": ("drop", "A43: In re Marriage of Manfer real (CL cluster Manfer v. Manfer)"),
    # Real cases with a fabricated detail — future detection targets:
    "98|f4th|1359": (
        "relabel:charlotin_real_case_wrong_pincite",
        "A12: Holden real; fabricated pinpoint 1371 > opinion end 1369",
    ),
    "225|f3d|1234": (
        "relabel:charlotin_real_case_wrong_court",
        "A33: Bolin v. Story real but 11th Cir., cited as 6th Cir.",
    ),
}


def adjudication_for(citation: str) -> tuple[str, str] | None:
    """(action, reason) for a manually adjudicated citation, else None.

    action is "drop" or "relabel:<new label>".
    """
    key = _core_cite_key(citation)
    return _ADJUDICATED.get(key) if key else None

# A fabricated-citation item description usually introduces the fake with a
# citing verb; used only for stats, not filtering.
_FABRICATED_CATEGORY = "Fabricated: Case Law"


@dataclass
class Candidate:
    citation: str
    flags: list[str] = field(default_factory=list)
    span_start: int = 0


def split_items(raw: str) -> list[tuple[str, str]]:
    """Split a `Hallucination Items` field into (category, description).

    Items are separated by '||'; within an item the FIRST '|' separates the
    category label from the description (descriptions may contain '|').
    """
    items = []
    for chunk in raw.split("||"):
        chunk = chunk.strip()
        if not chunk:
            continue
        category, _, description = chunk.partition("|")
        items.append((category.strip(), description.strip()))
    return items


def _verbatim_citation(text: str, cite: FullCaseCitation) -> str:
    """The citation as written, from the case name through the parenthetical."""
    start, end = cite.full_span()
    # eyecite drops the plaintiff when a quote character abuts it
    # ("cited 'Thornbury v. ..."), leaving the span at "v.". Recover the
    # name by extending back to the opening quote.
    if not (cite.metadata.plaintiff or "").strip():
        m = re.search(r"['\"‘“]([A-Z][^'\"‘“]{0,60}?)\s*$", text[:start])
        if m:
            start = m.start(1)
    # eyecite also stops the name span at "States" in "United States v. X"
    # when unusual punctuation (em-dash, quote) precedes it.
    if text[start:].startswith("States v.") and text[:start].endswith("United "):
        start -= len("United ")
    snippet = text[start:end]
    # full_span() can stop inside the (court date) parenthetical; extend to
    # the balancing close paren.
    if snippet.count("(") > snippet.count(")"):
        close = text.find(")", end)
        if close != -1:
            snippet = text[start : close + 1]
    return snippet.strip().strip("'\"").rstrip(",;.")


def extract_candidates(item_text: str) -> list[Candidate]:
    """Extract full case citations from one item description.

    Citations appearing after a contrast marker are flagged 'real_contrast'
    (the court naming the real case the fake collided with).
    """
    if not item_text.strip():
        return []
    marker = _CONTRAST_MARKERS.search(item_text)
    marker_pos = marker.start() if marker else None
    out: list[Candidate] = []
    for cite in get_citations(item_text, tokenizer=_TOKENIZER):
        if not isinstance(cite, FullCaseCitation):
            continue
        start = cite.full_span()[0]
        flags = []
        if marker_pos is not None and start > marker_pos:
            flags.append("real_contrast")
        citation = _verbatim_citation(item_text, cite)
        if citation.startswith("v.") or citation[:1].isdigit():
            # Case name lost (or never present) — not usable as a
            # standalone fake-citation input without manual repair.
            flags.append("incomplete_name")
        if _CONTRAST_MARKERS.search(citation):
            # eyecite's name backscan swallowed surrounding prose (seen
            # with NY square-bracket cites) — the string mixes the fake
            # and the court's correction; unusable without repair.
            flags.append("spans_prose")
        out.append(Candidate(citation=citation, flags=flags, span_start=start))
    return out


def _core_cite_key(citation: str) -> str | None:
    """Normalized volume+reporter+page (or WL) key for dedup."""
    m = re.search(r"\b(\d{4})\s+WL\s+(\d+)", citation)
    if m:
        return f"{m.group(1)}WL{m.group(2)}"
    m = re.search(r"\b(\d{1,4})\s+([A-Z][A-Za-z0-9.\' ]{0,25}?)\s+(\d{1,5})\b", citation)
    if m:
        reporter = re.sub(r"[^a-z0-9]", "", m.group(2).lower())
        return f"{m.group(1)}|{reporter}|{m.group(3)}"
    return None


def build() -> tuple[list[dict], dict]:
    rows = list(csv.DictReader(open(_SRC, encoding="utf-8-sig")))
    usa = [r for r in rows if r["State(s)"] == "USA"]

    known = json.load(open(_KNOWN_FAKES, encoding="utf-8"))
    known_keys = {_core_cite_key(e["citation"]) for e in known}
    known_keys.discard(None)

    corpus: list[dict] = []
    seen: set[str] = set()
    stats = {
        "usa_rows": len(usa),
        "fabricated_items": 0,
        "items_with_cites": 0,
        "extracted": 0,
        "flagged_real_contrast": 0,
        "flagged_incomplete_name": 0,
        "flagged_spans_prose": 0,
        "dup_within": 0,
        "dup_known_fakes": 0,
        "adjudicated_drop": 0,
        "adjudicated_relabel": 0,
    }
    for row in usa:
        for category, description in split_items(row["Hallucination Items"]):
            if category != _FABRICATED_CATEGORY:
                continue
            stats["fabricated_items"] += 1
            cands = extract_candidates(description)
            if cands:
                stats["items_with_cites"] += 1
            for cand in cands:
                stats["extracted"] += 1
                if cand.flags:
                    if "real_contrast" in cand.flags:
                        stats["flagged_real_contrast"] += 1
                    if "incomplete_name" in cand.flags:
                        stats["flagged_incomplete_name"] += 1
                    if "spans_prose" in cand.flags:
                        stats["flagged_spans_prose"] += 1
                    continue
                key = _core_cite_key(cand.citation)
                if key is None:
                    continue
                adj = _ADJUDICATED.get(key)
                if adj is not None and adj[0] == "drop":
                    stats["adjudicated_drop"] += 1
                    continue
                if key in seen:
                    stats["dup_within"] += 1
                    continue
                if key in known_keys:
                    stats["dup_known_fakes"] += 1
                    continue
                seen.add(key)
                label = "charlotin_court_confirmed_fake"
                if adj is not None:
                    label = adj[0].split(":", 1)[1]
                    stats["adjudicated_relabel"] += 1
                corpus.append(
                    {
                        "citation": cand.citation,
                        "label": label,
                        "charlotin_case": row["Case Name"],
                        "charlotin_court": row["Court"],
                        "charlotin_date": row["Date"],
                        "source_pdf": row["Source"],
                        "item_text": description,
                    }
                )
    stats["corpus_size"] = len(corpus)
    return corpus, stats


def main() -> None:
    corpus, stats = build()
    _OUT.write_text(json.dumps(corpus, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(corpus)} candidates -> {_OUT}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
