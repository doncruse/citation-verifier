"""Tier-0.5 probe #2 (throwaway diagnostic): the REAL hypotheses, measuring the
AI-generation fingerprint rather than professionalism.

Two signals, both document-internal / deterministic / zero-network:

  A. proposition_repeat — the same proposition restated with DIFFERENT
     citations. The padding fingerprint: a model asked to lengthen a brief
     re-states one legal point several times, each backed by a different
     (often fabricated) string cite. Human briefs make a point once with a
     string cite; they rarely repeat the SAME sentence with DIFFERENT authority.
     Boilerplate legal standards repeat with the SAME cite (Iqbal/Twombly), so
     the "different cite-set" requirement is what makes this discriminating.

  B. cite_prop_uniformity — how uniform is citations-per-proposition. The
     hypothesis: AI cite usage is regular (~1 cite per point, every point);
     human briefs are lumpy (some points get a 5-cite string, many get none).
     Reported as coefficient of variation of cites-per-proposition — LOWER CV =
     more uniform = more AI-suspicious under the hypothesis.

Unlike probe_texture's parenthetical/density proxies (which measured
professionalism and anti-separated), these target within-document structure that
should be independent of brief quality. If THESE don't separate either, Tier 0.5
can be retired with confidence.

Run: python probe_repetition.py
"""
from __future__ import annotations
import os, re
from collections import defaultdict
from signal_battery import normalize, extract_cites
from run_gate import CORPUS, CORPUS_ROOT

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
    """Yield (start, end, sentence_text) over the normalized text."""
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


def analyze(raw: str):
    text = normalize(raw)
    cites = extract_cites(text)
    sents = _sentences_with_spans(text)

    # assign each cite to the sentence whose span contains it
    props = []  # {tokens, cites(set of cite-strings), raw}
    for s0, s1, stext in sents:
        cs = {c["cite"] for c in cites if s0 <= c["pos"] < s1 and c["cite"]}
        if not cs:
            continue
        toks = _content_tokens(stext)
        if len(toks) < 4:      # too short to judge similarity
            continue
        props.append({"tokens": toks, "cites": cs, "raw": stext})

    n = len(props)
    # A. repetition: pairs of high-content-similarity props with different cites
    repeat_pairs = 0
    strict_pairs = 0
    # union-find-ish cluster of mutually-similar props (>=0.6)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard(props[i]["tokens"], props[j]["tokens"])
            if sim >= 0.6 and props[i]["cites"] != props[j]["cites"]:
                repeat_pairs += 1
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
                if sim >= 0.8:
                    strict_pairs += 1
    # largest cluster of similar-but-reshuffled propositions
    csize = defaultdict(int)
    for i in range(n):
        csize[find(i)] += 1
    max_cluster = max(csize.values()) if csize else 0

    # B. uniformity: CV of cites-per-proposition
    counts = [len(p["cites"]) for p in props]
    if counts:
        mu = sum(counts) / len(counts)
        var = sum((c - mu) ** 2 for c in counts) / len(counts)
        cv = round((var ** 0.5) / mu, 3) if mu else 0.0
    else:
        cv = 0.0

    return {
        "n_prop": n,
        "repeat_pairs": repeat_pairs,
        "strict_pairs": strict_pairs,
        "repeat_rate": round(repeat_pairs / n, 3) if n else 0.0,
        "max_cluster": max_cluster,
        "cite_prop_cv": cv,
    }


def main():
    rows = []
    for label, filer, rel in CORPUS:
        path = os.path.join(CORPUS_ROOT, rel)
        if not os.path.exists(path):
            continue
        raw = open(path, encoding="utf-8", errors="replace").read()
        rows.append((os.path.basename(rel).rsplit(".", 1)[0], label, filer,
                     analyze(raw)))

    print(f"{'slug':30s} {'lab':4s} {'filer':8s} {'nprop':>5s} {'rptP':>4s} "
          f"{'strP':>4s} {'rate':>5s} {'clst':>4s} {'cv':>5s}")
    for slug, label, filer, a in rows:
        print(f"{slug:30s} {label:4s} {filer:8s} {a['n_prop']:>5d} "
              f"{a['repeat_pairs']:>4d} {a['strict_pairs']:>4d} "
              f"{a['repeat_rate']:>5.3f} {a['max_cluster']:>4d} "
              f"{a['cite_prop_cv']:>5.3f}")

    def mean(vals):
        return round(sum(vals) / len(vals), 3) if vals else 0.0
    print("\nGroup means (repeat_pairs, repeat_rate, max_cluster, cv); n_prop>=5:")
    for label in ("bad", "control"):
        for filer in ("attorney", "pro_se"):
            grp = [a for _, l, f, a in rows if l == label and f == filer
                   and a["n_prop"] >= 5]
            if not grp:
                continue
            print(f"  {label:8s} {filer:9s} (k={len(grp)}): "
                  f"rptP={mean([a['repeat_pairs'] for a in grp])}  "
                  f"rate={mean([a['repeat_rate'] for a in grp])}  "
                  f"clst={mean([a['max_cluster'] for a in grp])}  "
                  f"cv={mean([a['cite_prop_cv'] for a in grp])}")


if __name__ == "__main__":
    main()
