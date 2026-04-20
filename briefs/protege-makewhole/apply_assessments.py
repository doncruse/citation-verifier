"""Merge assessments_A.json and assessments_B.json into claims.csv."""
import csv
import json
from collections import Counter
from pathlib import Path

workdir = Path("briefs/protege-makewhole")

results = []
for p in [workdir / "assessments_A.json", workdir / "assessments_B.json"]:
    results.extend(json.loads(p.read_text()))

by_index = {r["row_index"]: r for r in results}

with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames)
    rows = list(reader)

for col in ["assessment", "badge_label", "brief_block", "opinion_block", "finding_analysis"]:
    if col not in fieldnames:
        fieldnames.append(col)

for i, row in enumerate(rows, start=1):
    r = by_index.get(i)
    if not r:
        print(f"WARNING: no assessment for row_index {i}")
        continue
    row["assessment"] = r["assessment"]
    row["badge_label"] = r.get("badge_label", "")
    row["brief_block"] = r.get("brief_block", "")
    row["opinion_block"] = r.get("opinion_block", "")
    row["finding_analysis"] = r.get("finding_analysis", "")

with open(workdir / "claims.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

counts = Counter(row["assessment"] for row in rows)
print(f"Merged {len(results)} assessments into {len(rows)} rows")
print("Assessment summary:", dict(counts))
