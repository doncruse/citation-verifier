"""One-off: dump v0.3 verdicts for the fake-citation corpus next to v0.2 priors.

Tier 1 Step 1 measurement. Writes a clean table to stdout and a JSON
sidecar to scratch/fp_triage_result.json.
"""
import json
from pathlib import Path

from citation_verifier import CitationVerifier
from citation_verifier.models import Status

DATA = Path("tests/data/known_fake_citations.json")
corpus = json.loads(DATA.read_text(encoding="utf-8"))

VERIFIED_FAMILY = {
    Status.VERIFIED, Status.VERIFIED_PARTIAL,
    Status.VERIFIED_VIA_RECAP, Status.VERIFIED_DOCKET_ONLY,
}

v = CitationVerifier()
rows = []
for e in corpus:
    cite = e["citation"]
    r = v.verify(cite)
    prior = e.get("prior_result", {})
    fp = r.status in VERIFIED_FAMILY
    rows.append({
        "citation": cite,
        "category": e["category"],
        "v03_status": r.status.value,
        "v03_conf": r.headline_confidence,
        "v03_url": r.final_ids.absolute_url,
        "v03_is_fp": fp,
        "prior_engine": prior.get("engine"),
        "prior_status": prior.get("status"),
        "prior_conf": prior.get("confidence"),
        "warnings": [w.category.value for w in r.warnings],
    })
    flag = "FP " if fp else "ok "
    print(f"{flag} {r.status.value:22} conf={str(r.headline_confidence):6} "
          f"| prior {str(prior.get('status','-')):14} {prior.get('confidence','-')} "
          f"| {cite[:55]}")
    if fp:
        print(f"      -> matched {r.final_ids.absolute_url}")

Path("scratch/fp_triage_result.json").write_text(
    json.dumps(rows, indent=2), encoding="utf-8")

n_fp = sum(1 for r in rows if r["v03_is_fp"])
print(f"\n{n_fp}/{len(rows)} still false-positive (VERIFIED-family) under v0.3")
