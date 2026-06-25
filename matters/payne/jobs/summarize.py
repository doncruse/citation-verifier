import csv, os, json
from collections import Counter

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_path = os.path.join(workdir, "claims.csv")

rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
print("total claim rows:", len(rows))
print("columns:", list(rows[0].keys()))
print()

assess = Counter(r.get("assessment", "") for r in rows)
support = Counter(r.get("support", "") for r in rows)
print("assessment counts:", dict(assess))
print("support counts:", dict(support))
print()

# group by badge
badge = Counter(r.get("badge_label", "") for r in rows)
print("badge_label counts:")
for k, v in badge.most_common():
    print("  %2d  %s" % (v, k))
print()

def short(r):
    return "%s | %s | assess=%s support=%s badge=%s" % (
        r.get("claim_id"), r.get("cited_case", "")[:55],
        r.get("assessment"), r.get("support"), r.get("badge_label"))

print("=== RED (assessment Red) ===")
for r in rows:
    if r.get("assessment") == "Red":
        print(short(r))
print()
print("=== YELLOW (assessment Yellow) ===")
for r in rows:
    if r.get("assessment") == "Yellow":
        print(short(r))
print()
print("=== GRAY / unable (assessment Gray or support unverifiable) ===")
for r in rows:
    if r.get("assessment") == "Gray" or r.get("support") == "unverifiable":
        print(short(r))
