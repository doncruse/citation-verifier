import csv, re, json
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\Rebecca Fordon\Projects\citation-verifier\.claude\worktrees\recursing-tharp-f76108\benchmark\scratch\cl-coverage-offshoot")
pool_path = BASE / "final_pool.csv"
rows = list(csv.DictReader(open(pool_path, encoding="utf-8")))
print("final_pool total:", len(rows))
print("by tier:", Counter(r["cited_tier"] for r in rows))

def looks_like_docket_only(cs):
    cs = cs.strip()
    if "WL" in cs or "LEXIS" in cs:
        return False
    # Reporter cite indicators
    if re.search(r"\b(?:U\.S\.|F\.\s*\d|F\.\s*Supp|S\.\s*Ct|L\.\s*Ed|Cal\.|N\.Y\.|A\.\s*\d|P\.\s*\d)", cs):
        return False
    return bool(re.match(r"^(?:No\.\s*|Case\s+No\.\s*)?\d+[:\-]?\d*-(?:cv|cr|mc|md|mj|po)-\d", cs))

docket_only = [r for r in rows if looks_like_docket_only(r["citation_string"])]
print("\ncitation_string that LOOKS docket-only (no reporter, no WL):", len(docket_only))
for r in docket_only[:20]:
    print(f"  {r['citation_string'][:50]!r} | {r['cited_case_name'][:35]} | hint={r['court_hint']!r} | tier={r['cited_tier']}")

# Check raw extractions for any cite whose citation_string looks docket-only
ext_dir = BASE / "real_extractions"
n_files = 0
n_cites = 0
n_docket_only = 0
samples = []
for f in sorted(ext_dir.glob("*.json")):
    n_files += 1
    data = json.loads(f.read_text(encoding="utf-8"))
    for c in data.get("citations_valid") or []:
        if not isinstance(c, dict):
            continue
        cs = (c.get("citation_string") or "").strip()
        if not cs:
            continue
        n_cites += 1
        if looks_like_docket_only(cs):
            n_docket_only += 1
            if len(samples) < 15:
                samples.append((cs, c.get("cited_case_name"), c.get("court_hint"), c.get("docket_number")))

print(f"\nraw extractions: {n_files} files, {n_cites} valid cites, {n_docket_only} look docket-only")
for s in samples:
    print(" ", s)

# And look for ECF references in citing opinions themselves to see whether the source material even contains them
opin_dir = BASE / "citing_opinions"
ecf_hits = 0
case_no_only_hits = 0
for f in sorted(opin_dir.glob("*.txt"))[:30]:
    txt = f.read_text(encoding="utf-8", errors="replace")
    # ECF references
    for m in re.finditer(r"ECF\s+No\.\s*\d+", txt):
        ecf_hits += 1
    # "Case No. <docket>" patterns appearing in body text (not just header)
    for m in re.finditer(r"Case\s+No\.\s*\d+[:\-]?\d*-(?:cv|cr|mc|md|mj|po)-\d+", txt):
        case_no_only_hits += 1
print(f"\nIn first 30 citing opinions: {ecf_hits} ECF references, {case_no_only_hits} 'Case No.' docket forms")
