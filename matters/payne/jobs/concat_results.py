import json, os, glob

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rdir = os.path.join(workdir, "jobs", "results")
out_path = os.path.join(workdir, "jobs", "assess_results.jsonl")

files = sorted(glob.glob(os.path.join(rdir, "job_*.jsonl")))
lines = []
seen_claims = set()
errors = []
for fp in files:
    with open(fp, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception as e:
                errors.append((os.path.basename(fp), "BAD JSON", str(e)))
                continue
            cid = obj.get("claim_id")
            if cid in seen_claims:
                errors.append((os.path.basename(fp), "DUP", cid))
                continue
            seen_claims.add(cid)
            lines.append(ln)

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("result files:", len(files))
print("total verdict lines written:", len(lines))
print("unique claim_ids:", len(seen_claims))
if errors:
    print("ERRORS:")
    for e in errors:
        print("  ", e)
else:
    print("no errors")
