import csv, os

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_path = os.path.join(workdir, "claims.csv")
rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))

print("=== 7 UNASSESSED (empty assessment) rows ===")
for r in rows:
    if not r.get("assessment"):
        print("%s | %s | cl_status=%s | opinion_file=%s | track=%s | quote_floor=%s" % (
            r.get("claim_id"), r.get("cited_case","")[:45], r.get("cl_status"),
            os.path.basename(r.get("opinion_file","")), r.get("triage_track"), r.get("quote_floor")))
print()
print("=== 'Citation resolves to different case' + Davis-49: cited_case vs opinion_file vs cl_url ===")
ids = {"payne-02","payne-05","payne-27","payne-73","payne-74","payne-80","payne-49"}
for r in rows:
    if r.get("claim_id") in ids:
        print("%s | cited=%s" % (r.get("claim_id"), r.get("cited_case","")))
        print("        opinion_file=%s" % os.path.basename(r.get("opinion_file","")))
        print("        cl_url=%s" % r.get("cl_url",""))
        print("        cl_status=%s" % r.get("cl_status",""))
