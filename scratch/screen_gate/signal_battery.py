"""Tier-0 deterministic screening signals for suspect briefs — gate-experiment v0.

Port of us-legal-research's suspect-brief signal battery onto citation-verifier's
own citation spine (eyecite.get_citations + parser.parsed_citation_from_eyecite +
text_cleaner.clean_case_name), replacing the source prototype's bespoke
CASE_CITE_RE / trim_party1 / clean_name regex stack. Signal semantics and output
schema are identical to the source; only the extraction machinery changed.

Document-internal signals only: no network, no LLM, no CourtListener calls. Each
signal returns a list of flag dicts; empty list = signal did not fire. Run over
the bad-brief corpus and matched controls; a signal graduates into a `screen`
verb under src/citation_verifier only if it separates the corpora.

Usage: python signal_battery.py <file.md> [more files...]
Emits one JSON object per file to stdout.

Source prototype: us-legal-research evals/corpora/suspect-briefs/signal_battery.py
Seed analysis:    us-legal-research docs/research-notes/2026-07-03-suspect-brief-deterministic-tells.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

from eyecite import get_citations
from eyecite.models import (
    FullCaseCitation,
    IdCitation,
    ShortCaseCitation,
    SupraCitation,
)

from citation_verifier.parser import parsed_citation_from_eyecite
from citation_verifier.text_cleaner import clean_case_name

# ---------------------------------------------------------------- normalization
#
# The source prototype's PDF-noise pre-pass is retained verbatim: it strips the
# pleading-paper line-number gutter and CM/ECF footers *per raw line* (before
# joining, so a footer never spans a page boundary), then collapses whitespace
# and tightens spaced hyphens ("2 - 719" -> "2-719"). eyecite ships a
# clean_text() helper, but it targets HTML/unicode artifacts, not this repo's
# line-gutter / footer noise, so the source pre-pass is the right tool and is
# kept unchanged. eyecite is run over the normalized text below.

LINE_NUMBER_RE = re.compile(r"^\s*\d{1,2}\s*$")  # pleading-paper gutter numbers
FOOTER_RE = re.compile(r"Case \d:\d\d-[a-z]{2}-\d{4,6}.{0,80}Page \d+ of \d+")


def normalize(raw: str) -> str:
    """Collapse PDF-extraction noise: drop bare line-number lines and CM/ECF
    footers (per line, before joining — a joined-text pass would span pages),
    collapse whitespace, tighten spaced hyphens ('2 - 719' -> '2-719')."""
    lines = [FOOTER_RE.sub(" ", ln) for ln in raw.splitlines()
             if not LINE_NUMBER_RE.match(ln)]
    text = " ".join(lines)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text


# --------------------------------------------- citation extraction (CV spine)

SIGNAL_WORDS_RE = re.compile(
    r"^(?:See(?:,?\s+e\.g\.,)?|In(?:\s+re)?|Cf\.|E\.g\.,?|Accord|Citing|Quoting|"
    r"Compare|But\s+see|Contra|Under|Per)\s+", re.IGNORECASE)

CIRCUIT_WORDS = {
    "First": "1st", "Second": "2d", "Third": "3d", "Fourth": "4th",
    "Fifth": "5th", "Sixth": "6th", "Seventh": "7th", "Eighth": "8th",
    "Ninth": "9th", "Tenth": "10th", "Eleventh": "11th",
    "D.C.": "D.C.", "Federal": "Fed.",
}
CIRCUIT_PAREN_RE = re.compile(r"\((1st|2d|3d|4th|5th|6th|7th|8th|9th|10th|11th|D\.C\.|Fed\.)\s*Cir\.")

_SKIP_TOKENS = {"in", "re", "the", "of", "ex", "parte", "see", "cf", "eg",
                "accord", "matter", "estate", "people", "state", "united"}


def _fallback_name_from_span(cite, text: str) -> str:
    """Thin fallback for a FullCaseCitation whose eyecite metadata yields no
    party names: recover a 'X v. Y' string from the text immediately preceding
    the citation span. Mirrors the source prototype's regex reach without
    reintroducing its full trim_party1 stack — clean_case_name does the peeling.
    Returns '' when no adversarial name is recoverable."""
    start = cite.span()[0]
    window = text[max(0, start - 120):start]
    m = re.search(r"([A-Z][\w.'’&()\- ]{1,60}?\s+v\.?\s+[A-Z][\w.'’&()\- ]{1,60}?)\s*,?\s*$",
                  window)
    if not m:
        return ""
    return clean_case_name(SIGNAL_WORDS_RE.sub("", m.group(1).strip()))


def _display_name(pc, cite, text: str) -> str:
    """Case name for a parsed citation: prefer the ParsedCitation plaintiff/
    defendant (built by parsed_citation_from_eyecite from eyecite metadata),
    run through text_cleaner.clean_case_name; fall back to a span-preceding
    prose scan when eyecite gave no party metadata."""
    name = clean_case_name(pc.case_name) if pc.case_name else ""
    if not name:
        name = _fallback_name_from_span(cite, text)
    return name


def _raw_name(cite) -> str:
    """Case name from eyecite's *raw* metadata, BEFORE parser._normalize_case_name
    expands abbreviations. s6's squash-anchor matching compares against the
    document's own surface text (which carries abbreviations like "Int'l",
    "Elec."), so it must anchor on the same un-expanded vocabulary — otherwise
    an anchor token expanded to "International"/"Electric" never substring-matches
    the abbreviated body. Returns '' when eyecite gave no adversarial parties."""
    meta = getattr(cite, "metadata", None)
    if meta is None:
        return ""
    p = (getattr(meta, "plaintiff", None) or "").strip()
    d = (getattr(meta, "defendant", None) or "").strip()
    if not (p and d):
        return ""
    return clean_case_name(f"{p} v. {d}")


def norm_case_name(name: str) -> str:
    """First distinctive token of each party, lowercased — drift-tolerant key."""
    parts = re.split(r"\s+v\.?\s+", name, maxsplit=1)
    if len(parts) != 2:
        return name.lower().strip()

    def first_token(p):
        toks = [t for t in re.findall(r"[A-Za-z']{2,}", p)
                if t.lower() not in _SKIP_TOKENS]
        return toks[0].lower() if toks else p.lower()
    return f"{first_token(parts[0])}|{first_token(parts[1])}"


def _cite_string(pc) -> str:
    """Reassemble the reporter/WL location from ParsedCitation fields. eyecite
    normalizes spacing ('34 Cal.4th 979' -> '34 Cal. 4th 979'), so the string
    is the normalized form, not the document's surface form."""
    vol = pc.volume or ""
    rep = pc.reporter or ""
    page = pc.page or ""
    return " ".join(f"{vol} {rep} {page}".split())


def _cite_kind(cite, pc) -> str:
    """Classify by eyecite type, not the source's 'at NNN' hack.

    * ShortCaseCitation / IdCitation / SupraCitation -> 'shortform'
      (short forms and back-references; excluded from drift).
    * FullCaseCitation to the WL reporter -> 'wl'.
    * FullCaseCitation to a print reporter -> 'reporter'.
    """
    if isinstance(cite, (ShortCaseCitation, IdCitation, SupraCitation)):
        return "shortform"
    if pc.is_westlaw or pc.reporter == "WL":
        return "wl"
    return "reporter"


def extract_cites(text: str):
    """Extract citations via eyecite, structured via parsed_citation_from_eyecite.

    Keeps eyecite span positions (`pos`) so TOA-region assignment (s6) and the
    prose-court window (s1) can locate each cite in the normalized text.
    """
    out = []
    for cite in get_citations(text):
        # Short forms are surfaced (needed to exclude them from drift), but
        # only case-shaped citations participate. Skip law/unknown citations.
        if isinstance(cite, (FullCaseCitation, ShortCaseCitation,
                             IdCitation, SupraCitation)):
            pass
        else:
            continue
        matched = cite.matched_text()
        pc = parsed_citation_from_eyecite(cite, matched) \
            if isinstance(cite, FullCaseCitation) else None
        kind = _cite_kind(cite, pc) if pc is not None else "shortform"
        name = _display_name(pc, cite, text) if pc is not None else ""
        raw_name = _raw_name(cite) if isinstance(cite, FullCaseCitation) else ""
        cite_str = _cite_string(pc) if pc is not None else matched
        out.append({
            "name": name,
            "raw_name": raw_name or name,
            "key": norm_case_name(name) if name else "",
            "cite": cite_str,
            "kind": kind,
            "pos": cite.span()[0],
        })
    return out


def _full_cites(text: str):
    """Citations that carry a usable case name (full, non-shortform)."""
    return [c for c in extract_cites(text)
            if c["kind"] != "shortform" and c["name"]]


# --------------------------------------------------------------------- signals


def s1_court_contradiction(text: str):
    """Prose names circuit X; a citation parenthetical within reach says circuit Y.

    Anchors on the PROSE circuit mention and scans forward for a court
    parenthetical — the parenthetical string is the cite-side court to compare.
    ParsedCitation.court (eyecite metadata, e.g. 'cafc' for the Fed. Cir. Intel
    cite) corroborates but is not the comparison surface here, because s1 must
    pair a cite against the prose court that immediately precedes it. The
    parenthetical window-scan is therefore the primary mechanism (source parity)."""
    flags = []
    for m in re.finditer(r"\b(" + "|".join(CIRCUIT_WORDS) + r")\s+Circuit\b", text):
        window = text[m.end(): m.end() + 350]
        p = CIRCUIT_PAREN_RE.search(window)
        if p and p.group(1) != CIRCUIT_WORDS[m.group(1)]:
            flags.append({
                "signal": "court_contradiction",
                "prose_court": f"{m.group(1)} Circuit",
                "cite_court": f"{p.group(1)} Cir.",
                "context": text[m.start(): m.end() + p.end() + 20][:300],
            })
    return flags


def s2_authority_drift(text: str):
    """Same case name carrying materially different citations in one document.

    Only FullCaseCitation instances participate (short forms — ShortCaseCitation
    / IdCitation / SupraCitation — are excluded upstream via _full_cites). Drift =
    two different full print-reporter cites for one name, or a name cited both to
    a print reporter and to WL (the multi-pass generation fingerprint)."""
    cites = _full_cites(text)
    by_key = defaultdict(list)
    for c in cites:
        if c["key"]:
            by_key[c["key"]].append(c)
    flags = []
    for key, group in by_key.items():
        reporters = {c["cite"] for c in group if c["kind"] == "reporter"}
        wls = {c["cite"] for c in group if c["kind"] == "wl"}
        distinct = reporters | wls
        if len(reporters) > 1 or (reporters and wls):
            flags.append({
                "signal": "authority_drift",
                "case_key": key,
                "cites": sorted(distinct),
                "names_seen": sorted({c["name"] for c in group})[:3],
            })
    return flags


STATUTE_GRAMMAR_RE = [
    (re.compile(r"\bCal\.?\s*U\.?C\.?C\.?\b"), "Cal. UCC — California codified the UCC as Cal. Com. Code"),
    (re.compile(r"\bN\.?Y\.?\s*U\.?C\.?C\.?\s*§\s*\d+-\d+\b"), "N.Y. UCC section form — check against N.Y. U.C.C. Law"),
]


def s3_statute_grammar(text: str):
    """Citation-independent: ported unchanged from the source prototype."""
    flags = []
    for rx, why in STATUTE_GRAMMAR_RE:
        for m in rx.finditer(text):
            flags.append({"signal": "statute_grammar", "match": m.group(0),
                          "why": why, "context": text[max(0, m.start() - 60): m.end() + 60]})
    return flags


MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
ARITH_RE = re.compile(
    r"\$([\d,]+)(?:\.\d+)?\s*(?:/|per\s+)month[^.$]{0,200}?"
    r"\$([\d,]+)(?:\.\d+)?[^.$]{0,80}?"
    r"from\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\s+to\s+(" + "|".join(MONTHS) + r")\s+(\d{4})",
    re.IGNORECASE,
)


def s4_arithmetic(text: str):
    """Rate x stated period vs stated total, ±1 month tolerance / ±5%.
    Citation-independent: ported unchanged from the source prototype."""
    flags = []
    for m in ARITH_RE.finditer(text):
        rate = int(m.group(1).replace(",", ""))
        total = int(m.group(2).replace(",", ""))
        months = ((int(m.group(6)) - int(m.group(4))) * 12
                  + MONTHS[m.group(5).capitalize()] - MONTHS[m.group(3).capitalize()] + 1)
        expected = rate * months
        if rate and months > 0 and abs(expected - total) > max(rate, 0.05 * expected):
            flags.append({"signal": "arithmetic", "rate_per_month": rate,
                          "stated_total": total, "stated_months": months,
                          "expected_total": expected,
                          "implied_months": round(total / rate, 1)})
    return flags


def s5_style_variance(text: str):
    """Mixed citation-style error profile: 'v' without period in case names;
    comma-in-court-parenthetical WL form.
    Citation-independent: ported unchanged from the source prototype."""
    flags = []
    no_period = re.findall(r"[A-Z][\w'’]+\s+v\s+[A-Z][\w'’]+", text)
    with_period = re.findall(r"[A-Z][\w'’]+\s+v\.\s+[A-Z][\w'’]+", text)
    if no_period and with_period:
        flags.append({"signal": "style_variance", "kind": "v_period_mixed",
                      "no_period_examples": no_period[:3],
                      "counts": {"v": len(no_period), "v.": len(with_period)}})
    for m in re.finditer(r"\(([A-Z][\w.]*?),\s+\d{4}\)", text):
        if m.group(1).rstrip(".") in ("Cal", "N.Y", "Tex", "Fla", "Ill", "Mass", "Wash"):
            flags.append({"signal": "style_variance", "kind": "comma_court_paren",
                          "match": m.group(0)})
    return flags


TOA_START_RE = re.compile(r"TABLE\s+OF\s+AUTHORITIES", re.IGNORECASE)
TOA_END_RE = re.compile(
    r"(MEMORANDUM\s+OF\s+POINTS|INTRODUCTION|PRELIMINARY\s+STATEMENT|"
    r"STATEMENT\s+OF|ARGUMENT|TO\s+ALL\s+PARTIES)", )


def _squash_text(s: str) -> str:
    """Letters-only lowercase — defeats PDF intra-word splits ('Cot ton',
    'C orp') and all punctuation/spacing when scanning for a case anchor."""
    return re.sub(r"[^a-z]", "", s.lower())


def _case_anchors(name: str):
    """Candidate squashed anchors for a case name, longest first. Each is a
    tail-suffix of party-1 + 'v' + party-2, so residual front-of-string
    over-capture that clean_case_name couldn't peel still yields a shorter
    anchor that substring-matches a clean occurrence elsewhere."""
    parts = re.split(r"\s+v\.?\s+", name, maxsplit=1)
    if len(parts) != 2:
        s = _squash_text(name)
        return [s] if s else []
    p2 = _squash_text(parts[1])
    toks = parts[0].split()
    out = []
    for i in range(len(toks)):
        p1 = _squash_text(" ".join(toks[i:]))
        if p1:
            out.append(p1 + "v" + p2)
    return out or [_squash_text(name)]


def _appears_in(name: str, squashed_hay: str) -> bool:
    """True if any case anchor for `name` occurs as a substring of the
    letters-only haystack. Anchors are >=6 chars to avoid spurious hits."""
    for a in _case_anchors(name):
        if len(a) >= 6 and a in squashed_hay:
            return True
    return False


def s6_toa_body_diff(text: str):
    """Authorities in the Table of Authorities but absent from the body, or
    vice versa. TOA/body split by the same header markers as the source."""
    m = TOA_START_RE.search(text)
    if not m:
        return []  # no TOA (memos often lack one) — signal not applicable
    end = TOA_END_RE.search(text, m.end())
    toa = text[m.end(): end.start()] if end else text[m.end(): m.end() + 8000]
    body = text[end.start():] if end else ""
    # s6 anchors on the *raw* (un-abbreviation-expanded) eyecite names so the
    # squash anchors share the document's own surface vocabulary. Display uses
    # the normalized name; membership uses raw_name.
    toa_cites = [c for c in _full_cites(toa) if c["raw_name"]]
    body_cites = [c for c in _full_cites(body) if c["raw_name"]]
    toa_sq = _squash_text(toa)
    body_sq = _squash_text(body)
    only_toa = sorted({c["name"] for c in toa_cites
                       if not _appears_in(c["raw_name"], body_sq)})
    only_body = sorted({c["name"] for c in body_cites
                        if not _appears_in(c["raw_name"], toa_sq)})
    if only_toa or only_body:
        return [{"signal": "toa_body_diff",
                 "in_toa_not_body": only_toa,
                 "in_body_not_toa": only_body,
                 "toa_count": len(toa_cites), "body_count": len(body_cites)}]
    return []


SIGNALS = [s1_court_contradiction, s2_authority_drift, s3_statute_grammar,
           s4_arithmetic, s5_style_variance, s6_toa_body_diff]


def screen(raw: str) -> dict:
    text = normalize(raw)
    result = {"n_cites_extracted": len(extract_cites(text)), "flags": []}
    for sig in SIGNALS:
        result["flags"].extend(sig(text))
    result["n_flags"] = len(result["flags"])
    result["signals_fired"] = sorted({f["signal"] for f in result["flags"]})
    return result


if __name__ == "__main__":
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8", errors="replace") as fh:
            r = screen(fh.read())
        r["file"] = path
        print(json.dumps(r, ensure_ascii=False))
