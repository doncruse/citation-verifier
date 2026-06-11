"""First-measurement baseline: run the CURRENT verifier (live) over the Withers
v. City of Aberdeen corpus and score its EXISTENCE-layer predictions against the
exhibit's ground truth.

This measures only the verifier (does-the-case-exist / is-the-cite-right) layer,
not the proposition-assessment (green/yellow) layer — that needs the assessment
agents and is the redesign's job. For the existence layer the mapping is:

  exhibit exists=No  (red, hallucinated)  -> verifier should NOT return a clean
      VERIFIED. Ideal: NOT_FOUND / WRONG_CASE / CITE_UNCONFIRMED. A clean VERIFIED
      on a red is a FALSE POSITIVE (the worst outcome for a hallucination catcher).
  exhibit exists=Yes (green/yellow)       -> verifier should locate the case
      (any VERIFIED-family or CITE_UNCONFIRMED). A NOT_FOUND on a real case is a
      FALSE NEGATIVE.

Bonus signal: the exhibit's yellows include wrong-pincite / wrong-court / misquote
cases — exactly the CITE_UNCONFIRMED / quote-check surface. We report how many
yellows the verifier flags as CITE_UNCONFIRMED vs. plain VERIFIED.

Live API; single consumer. Run on the token machine, NOT concurrently with any
recorder. Output: tests/data/withers_baseline_results.csv
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from citation_verifier import CitationVerifier  # noqa: E402

_DATA = Path(__file__).parent / "data"
_CORPUS = _DATA / "withers_aberdeen_corpus.csv"
_OUT = _DATA / "withers_baseline_results.csv"

_FOUND = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP", "VERIFIED_DOCKET_ONLY"}


def main() -> None:
    rows = list(csv.DictReader(_CORPUS.open(encoding="utf-8")))
    v = CitationVerifier()
    results = []
    for i, r in enumerate(rows, 1):
        cite = r["citation"]
        try:
            res = v.verify(cite)
            status = res.status.value
            conf = res.headline_confidence
            warns = ";".join(w.category.value for w in res.warnings)
        except Exception as exc:  # noqa: BLE001
            status, conf, warns = f"ERROR:{type(exc).__name__}", None, ""
        results.append({**r, "v_status": status, "v_conf": conf, "v_warnings": warns})
        print(f"  {i:2d}/{len(rows)} [{r['label']:6s} exists={r['exists']:3s}] "
              f"{status:22s} :: {cite[:48]}", flush=True)

    with _OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    # ---- scoring ----
    print("\n" + "=" * 70)
    reds = [r for r in results if r["exists"] == "No"]
    reals = [r for r in results if r["exists"] == "Yes"]

    red_fp = [r for r in reds if r["v_status"] in _FOUND]  # clean-verified a fake
    print(f"REDS (hallucinated, n={len(reds)}):")
    for r in reds:
        flag = "  <-- FALSE POSITIVE" if r["v_status"] in _FOUND else ""
        print(f"    {r['v_status']:22s} {r['citation'][:50]}{flag}")
    print(f"  -> {len(red_fp)}/{len(reds)} clean-verified a hallucinated cite (want 0)")

    real_fn = [r for r in reals if r["v_status"] not in _FOUND
               and r["v_status"] != "CITE_UNCONFIRMED"]
    real_located = [r for r in reals if r["v_status"] in _FOUND
                    or r["v_status"] == "CITE_UNCONFIRMED"]
    print(f"\nREAL cases (green+yellow, n={len(reals)}):")
    print(f"  located (FOUND-family or CITE_UNCONFIRMED): {len(real_located)}/{len(reals)}")
    print(f"  NOT located (false negatives / gaps):       {len(real_fn)}/{len(reals)}")

    print("\nstatus x label cross-tab:")
    xt: dict[tuple[str, str], int] = Counter(
        (r["label"], r["v_status"]) for r in results)
    for (label, status), n in sorted(xt.items()):
        print(f"  {label:6s} | {status:22s} : {n}")

    # CITE_UNCONFIRMED signal on yellows (wrong-pincite/quote/court cases)
    yellows = [r for r in results if r["label"] == "yellow"]
    y_checkcite = [r for r in yellows if r["v_status"] == "CITE_UNCONFIRMED"]
    print(f"\nYellows flagged CITE_UNCONFIRMED: {len(y_checkcite)}/{len(yellows)} "
          f"(the cite-problem subset the verifier can catch)")
    print(f"\nWrote {_OUT}")


if __name__ == "__main__":
    main()
