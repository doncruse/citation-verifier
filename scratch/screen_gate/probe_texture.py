"""Throwaway diagnostic (NOT a gate signal): does statistical texture separate
bad from control at our current n, and how many docs would preamble/metadata
tells actually catch? Informs the Tier-0.5 vs. tell-signal decision.

Texture metrics per doc (all cheap, deterministic, no network):
  - gerund_paren_rate: gerund-led explanatory parentheticals per citation
    ("(holding that ...)", "(finding ...)"). AI-drafted string cites lean on
    these heavily and uniformly; the hypothesis is bad >> control.
  - paren_rate: any explanatory parenthetical per citation.
  - cite_density: citations per 1000 words.
Also: a preamble phrase scan over the raw text (chatbot_preamble recall probe).

Run: python probe_texture.py
"""
from __future__ import annotations
import os, re
from signal_battery import screen, normalize
from run_gate import CORPUS, CORPUS_ROOT

GERUNDS = ("holding", "finding", "noting", "concluding", "reasoning",
           "explaining", "stating", "affirming", "reversing", "rejecting",
           "recognizing", "acknowledging", "observing", "quoting", "citing",
           "granting", "denying", "ruling", "declining", "upholding", "applying")
GERUND_PAREN_RE = re.compile(r"\(\s*(?:" + "|".join(GERUNDS) + r")\b", re.IGNORECASE)
ANY_PAREN_RE = re.compile(r"\(\s*(?:[a-z]{3,}ing|per curiam|en banc|plurality|"
                          r"dissent|concurr|emphasis|internal|quotation)", re.IGNORECASE)

# chatbot_preamble candidate phrase bank (leaked AI-assistant framing)
PREAMBLE_PHRASES = [
    "here is a court-ready", "here is a", "you can insert", "you can paste",
    "i hope this helps", "let me know if", "as an ai", "i cannot provide",
    "certainly!", "here's a", "feel free to", "calibrated for", "i've drafted",
    "below is a", "note: this", "disclaimer:", "as a large language model",
]


def texture(raw: str):
    text = normalize(raw)
    n_cites = screen(raw)["n_cites_extracted"]
    words = max(1, len(text.split()))
    gp = len(GERUND_PAREN_RE.findall(text))
    ap = len(ANY_PAREN_RE.findall(text))
    low = raw.lower()
    hits = [p for p in PREAMBLE_PHRASES if p in low]
    return {
        "n_cites": n_cites,
        "words": words,
        "gerund_paren": gp,
        "gerund_per_cite": round(gp / n_cites, 3) if n_cites else 0.0,
        "any_paren_per_cite": round(ap / n_cites, 3) if n_cites else 0.0,
        "cite_density_k": round(1000 * n_cites / words, 2),
        "preamble_hits": hits,
    }


def main():
    rows = []
    for label, filer, rel in CORPUS:
        path = os.path.join(CORPUS_ROOT, rel)
        if not os.path.exists(path):
            continue
        raw = open(path, encoding="utf-8", errors="replace").read()
        t = texture(raw)
        rows.append((os.path.basename(rel).rsplit(".", 1)[0], label, filer, t))

    print(f"{'slug':30s} {'lab':4s} {'filer':8s} {'cites':>5s} {'g/cite':>6s} "
          f"{'ap/cite':>7s} {'dens':>5s}  preamble")
    for slug, label, filer, t in rows:
        pre = ",".join(t["preamble_hits"]) if t["preamble_hits"] else ""
        print(f"{slug:30s} {label:4s} {filer:8s} {t['n_cites']:>5d} "
              f"{t['gerund_per_cite']:>6.3f} {t['any_paren_per_cite']:>7.3f} "
              f"{t['cite_density_k']:>5.2f}  {pre}")

    # group means for the texture metrics
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0.0
    print("\nGroup means (g/cite, ap/cite, density):")
    for label in ("bad", "control"):
        for filer in ("attorney", "pro_se"):
            grp = [t for _, l, f, t in rows if l == label and f == filer and t["n_cites"] >= 5]
            if not grp:
                continue
            print(f"  {label:8s} {filer:9s} (n>=5cites, k={len(grp)}): "
                  f"g/cite={mean([t['gerund_per_cite'] for t in grp])}  "
                  f"ap/cite={mean([t['any_paren_per_cite'] for t in grp])}  "
                  f"dens={mean([t['cite_density_k'] for t in grp])}")

    n_pre = sum(1 for _, l, _, t in rows if l == "bad" and t["preamble_hits"])
    n_bad = sum(1 for _, l, _, _ in rows if l == "bad")
    print(f"\npreamble-phrase recall on bad: {n_pre}/{n_bad}")


if __name__ == "__main__":
    main()
