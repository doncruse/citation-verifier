"""Shared deterministic surface-metric extractor for the screen baseline gate.

Consolidates the metrics prototyped in probe_texture.py + probe_repetition.py
into one importable function. Zero-network, no LLM: every metric is a fact about
the text. compute_metrics(raw) -> the canonical 9-key vector.
"""
from __future__ import annotations

import re

from signal_battery import normalize, extract_cites, TOA_START_RE

GERUNDS = ("holding", "finding", "noting", "concluding", "reasoning",
           "explaining", "stating", "affirming", "reversing", "rejecting",
           "recognizing", "acknowledging", "observing", "quoting", "citing",
           "granting", "denying", "ruling", "declining", "upholding", "applying")
GERUND_PAREN_RE = re.compile(r"\(\s*(?:" + "|".join(GERUNDS) + r")\b", re.IGNORECASE)
ANY_PAREN_RE = re.compile(
    r"\(\s*(?:[a-z]{3,}ing|per curiam|en banc|plurality|dissent|concurr|"
    r"emphasis|internal|quotation)", re.IGNORECASE)

STOP = set("""a an the of to in on at by for with from as and or but nor so yet
that this these those which who whom whose it its it's is are was were be been
being has have had do does did not no than then thus hence such same other any
all each both few more most some no only own very can will just about into over
under out up down off then once here there when where why how i we you he she
they them their our your his her would could should may might must shall see also
id supra infra cf accord e.g i.e viz ante post et al v vs case court held holding
finding plaintiff plaintiffs defendant defendants motion cite cited citing""".split())

SENT_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def _content_tokens(s: str) -> set:
    toks = {w.lower() for w in WORD_RE.findall(s)}
    return {t for t in toks if t not in STOP and len(t) >= 3}


def _sentences_with_spans(text: str):
    out, pos = [], 0
    for piece in SENT_SPLIT_RE.split(text):
        idx = text.find(piece, pos)
        if idx < 0:
            idx = pos
        out.append((idx, idx + len(piece), piece))
        pos = idx + len(piece)
    return out


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _propositions(text: str, cites):
    """Sentences carrying >=1 citation and >=4 content tokens."""
    out = []
    for s0, s1, stext in _sentences_with_spans(text):
        cs = {c["cite"] for c in cites if s0 <= c["pos"] < s1 and c["cite"]}
        if not cs:
            continue
        toks = _content_tokens(stext)
        if len(toks) < 4:
            continue
        out.append({"tokens": toks, "cites": cs})
    return out


def compute_metrics(raw: str) -> dict:
    text = normalize(raw)

    # Handle empty text edge case
    if not text or not text.strip():
        return {
            "n_cites": 0,
            "words": 0,
            "cite_density": 0.0,
            "parenthetical_richness": 0.0,
            "string_cite_rate": 0.0,
            "gerund_paren_rate": 0.0,
            "has_toa": False,
            "proposition_repeat_rate": 0.0,
            "cite_prop_cv": 0.0,
        }

    cites = extract_cites(text)
    n = len(cites)
    words = max(1, len(text.split()))
    gp = len(GERUND_PAREN_RE.findall(text))
    ap = len(ANY_PAREN_RE.findall(text))

    props = _propositions(text, cites)
    nprop = len(props)
    string_props = sum(1 for p in props if len(p["cites"]) >= 2)

    repeat_pairs = 0
    for i in range(nprop):
        for j in range(i + 1, nprop):
            if (_jaccard(props[i]["tokens"], props[j]["tokens"]) >= 0.6
                    and props[i]["cites"] != props[j]["cites"]):
                repeat_pairs += 1

    counts = [len(p["cites"]) for p in props]
    if counts:
        mu = sum(counts) / len(counts)
        var = sum((c - mu) ** 2 for c in counts) / len(counts)
        cv = (var ** 0.5) / mu if mu else 0.0
    else:
        cv = 0.0

    return {
        "n_cites": n,
        "words": words,
        "cite_density": round(1000 * n / words, 3),
        "parenthetical_richness": round(ap / n, 3) if n else 0.0,
        "string_cite_rate": round(string_props / nprop, 3) if nprop else 0.0,
        "gerund_paren_rate": round(gp / n, 3) if n else 0.0,
        "has_toa": bool(TOA_START_RE.search(text)),
        "proposition_repeat_rate": round(repeat_pairs / nprop, 3) if nprop else 0.0,
        "cite_prop_cv": round(cv, 3),
    }
