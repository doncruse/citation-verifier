import csv, os, json

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = list(csv.DictReader(open(os.path.join(workdir, "claims.csv"), encoding="utf-8")))

def g(r, k): return (r.get(k) or "").strip()

print("### RESOLUTION ISSUES (not found / wrong case / resolves to different case) ###")
for r in rows:
    cl = g(r, "cl_status")
    badge = g(r, "badge_label")
    if cl in ("WRONG_CASE", "NOT_FOUND", "INSUFFICIENT_DATA") or badge == "Citation resolves to different case":
        print("\n%s | %s" % (r["claim_id"], g(r, "cited_case")))
        print("   cl_status=%s | badge=%s | support=%s | assess=%s" % (cl, badge, g(r,"support"), g(r,"assessment")))
        print("   opinion_file=%s | cl_url=%s" % (os.path.basename(g(r,"opinion_file")), g(r,"cl_url")))
        print("   page=%s | prop=%s" % (g(r,"page"), g(r,"proposition")[:120]))

print("\n\n### QUOTATION ERRORS (quote_check / quote_floor / quote badges) ###")
for r in rows:
    badge = g(r, "badge_label")
    qcw = g(r, "quote_check_worst")
    qf = g(r, "quote_floor")
    qt = g(r, "quoted_text")
    has_quote_badge = badge in ("Quote not found in opinion","Reworded -- not a verbatim quote","Paraphrase presented as direct quote")
    # any quote_check entry flagged FABRICATED or CLOSE
    flagged = ("FABRICATED" in qcw.upper()) or ("CLOSE" in qcw.upper()) or has_quote_badge or (qf != "")
    if flagged and qt not in ("", "[]"):
        print("\n%s | %s" % (r["claim_id"], g(r, "cited_case")))
        print("   badge=%s | quote_floor=%s" % (badge, qf))
        print("   quote_check_worst=%s" % qcw[:200])
        print("   opinion_file=%s | cl_status=%s" % (os.path.basename(g(r,"opinion_file")), g(r,"cl_status")))
        print("   quoted_text=%s" % qt[:250])
