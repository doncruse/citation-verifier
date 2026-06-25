import csv, os
from collections import Counter

def profile(path, label):
    if not os.path.exists(path):
        print(label, "(missing)"); return
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    # v2 batch = claims grouped per opinion_file (only assessable rows w/ a linked opinion)
    per = Counter()
    for r in rows:
        of = (r.get("opinion_file") or "").strip()
        # count only rows that would be assessed (have an opinion to pack against)
        if of:
            per[os.path.basename(of)] += 1
    sizes = sorted(per.values(), reverse=True)
    n_jobs = len(sizes)
    n_claims = sum(sizes)
    dist = Counter(sizes)
    big = sum(1 for s in sizes if s >= 4)
    small = sum(1 for s in sizes if s <= 2)
    print("%-12s opinions/jobs=%-3d claims=%-3d  avg=%.2f  max=%d  | size<=2: %d jobs  size>=4: %d jobs" % (
        label, n_jobs, n_claims, (n_claims/n_jobs if n_jobs else 0), (max(sizes) if sizes else 0), small, big))
    print("              size histogram (claims/job -> #jobs): " + ", ".join("%d->%d" % (k, dist[k]) for k in sorted(dist)))

base = "tests/data/assessment_corpora"
for c in ["withers","wainwright","payne"]:
    profile(os.path.join(base, c, "claims.csv"), c+" (corpus)")
print()
profile("matters/payne/claims.csv", "payne (THIS run)")
