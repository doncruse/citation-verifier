# -*- coding: utf-8 -*-
"""Build a print-optimized HTML (one section per page) for the focused Payne report."""
import csv, os, json, html

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = {r["claim_id"]: r for r in csv.DictReader(open(os.path.join(workdir, "claims.csv"), encoding="utf-8"))}

RUN_DATE = "2026-06-24"
OUT_HTML = os.path.join(workdir, "jobs", "focus_print.html")

def g(cid, k): return (rows[cid].get(k) or "").strip()
def esc(s): return html.escape(s or "")
def trunc(s, n): return s if len(s) <= n else s[:n-1].rstrip() + "…"
def slug_name(url):
    if not url: return ""
    parts = [p for p in url.strip("/").split("/") if p]
    return parts[-1].replace("-", " ").title() if parts else ""
def quotes(cid):
    raw = g(cid, "quoted_text")
    try: arr = json.loads(raw) if raw else []
    except Exception: arr = []
    return [q for q in arr if q]

# ---- categorization (artifacts intentionally excluded) ----
UNCONFIRMED = ["payne-03","payne-08","payne-09","payne-20","payne-55","payne-02","payne-23","payne-21"]
QUOTE_FAB   = ["payne-11","payne-13","payne-14","payne-57","payne-58"]
QUOTE_REWORD= ["payne-34"]

UNCONF_NOTE = {
 "payne-03": "CourtListener finds <i>%s</i> at 288 Ga. 768 &mdash; the cited name/page don't match. Verify by hand." % esc(slug_name(g("payne-03","cl_url"))),
 "payne-08": "CourtListener finds <i>%s</i> at 283 Ga. 155. Verify the citation by hand." % esc(slug_name(g("payne-08","cl_url"))),
 "payne-09": "CourtListener finds <i>%s</i> at 269 Ga. App. 242. Verify the citation by hand." % esc(slug_name(g("payne-09","cl_url"))),
 "payne-20": "CourtListener finds <i>%s</i> at 268 Ga. App. 362. Verify the citation by hand." % esc(slug_name(g("payne-20","cl_url"))),
 "payne-55": "CL finds <i>%s</i> here; almost certainly a typo for <b>Patel v. State, 279 Ga. 750</b> (cited elsewhere). Confirm the pincite." % esc(slug_name(g("payne-55","cl_url"))),
 "payne-02": "Not found at 306 Ga. 630. Cited throughout for Georgia's adoption of <i>Strickland</i> &mdash; likely a verifier miss; confirm the pincite by hand.",
 "payne-23": "Short-form repeat of the <i>Reynolds</i> cite (p.24); same NOT_FOUND result. Confirm 306 Ga. 630.",
 "payne-21": "Cited with <b>no reporter</b> (year only), so it could not be looked up. Supply the full cite &mdash; 458 U.S. 858 (1982).",
}
UNCONF_BADGE = {"WRONG_CASE": ("Wrong case at cite", "red"),
                "NOT_FOUND": ("Not found", "amber"),
                "INSUFFICIENT_DATA": ("No reporter cite", "amber")}

CSS = """
@page{size:Letter;margin:0.5in;}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
html,body{margin:0;padding:0;}
body{font:12px/1.42 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#23201c;}
h1{font-size:18px;margin:0 0 2px;letter-spacing:-.01em;}
.cap{font-size:11px;color:#6b6358;margin:0;}
.meta{font-size:10px;color:#6b6358;border-top:1px solid #e7e2d9;border-bottom:1px solid #e7e2d9;padding:5px 0;margin:9px 0 13px;}
.meta b{color:#23201c;}
h2{font-size:15px;margin:0 0 2px;letter-spacing:-.01em;}
.cnt{display:inline-block;background:#f2f4f7;color:#475467;border-radius:18px;padding:0 8px;font-size:11px;font-weight:700;margin-left:6px;vertical-align:middle;}
.lead{font-size:10.5px;color:#6b6358;margin:0 0 9px;}
.page2{break-before:page;}
.p2cap{font-size:10px;color:#8a8377;margin:0 0 10px;}
.card{border:1px solid #e7e2d9;border-left-width:4px;border-radius:7px;padding:8px 11px;margin:7px 0;page-break-inside:avoid;}
.card.red{border-left-color:#b42318;}
.card.amber{border-left-color:#b54708;}
.chead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;}
.case{font-weight:700;font-size:13px;}
.pg{color:#8a8377;font-size:10px;font-weight:500;}
.badge{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:2px 7px;border-radius:4px;white-space:nowrap;}
.badge.red{background:#fef3f2;color:#b42318;}
.badge.amber{background:#fffaeb;color:#b54708;}
.note{font-size:11px;margin-top:4px;}
.for{font-size:10px;color:#8a8377;margin-top:3px;}
.quote{font-size:11px;font-style:italic;background:#fef3f2;border-left:3px solid #b42318;padding:5px 9px;border-radius:0 5px 5px 0;margin-top:5px;color:#7a271a;}
.quote.amber{background:#fffaeb;border-left-color:#b54708;color:#7a4a0a;}
.tip{background:#f0f7ff;border:1px solid #d6e8ff;border-radius:7px;padding:8px 11px;font-size:10px;color:#1c3d5a;margin-top:11px;}
footer{margin-top:14px;color:#8a8377;font-size:9.5px;}
"""

P = []
P.append('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Payne focus</title><style>%s</style></head><body>' % CSS)

# ---------- PAGE 1 ----------
P.append('<section class="page1">')
P.append('<h1>Not-Found / Mismatched Citations &amp; Quotation Errors</h1>')
P.append('<p class="cap"><i>State v. Hannah Renee Payne</i>, No. 2019CR01737-14 &mdash; Order Denying Motion for New Trial (proposed)</p>')
P.append('<div class="meta">Filtered view &mdash; run <b>%s</b> &middot; assess-v2 / Opus &middot; code <b>efd173d</b>. Companion to the full <code>report.html</code>; shows only citation-resolution problems (this page) and quotation errors (next page).</div>' % RUN_DATE)
P.append('<h2>1&nbsp;&nbsp;Citations that could not be confirmed<span class="cnt">%d</span></h2>' % len(UNCONFIRMED))
P.append('<p class="lead">CourtListener could not match the cited case at the cited reporter location. Not machine-assessed &mdash; each needs a manual check; some may be additional hallucinated or garbled citations.</p>')
for cid in UNCONFIRMED:
    cl = g(cid, "cl_status")
    btxt, bcls = UNCONF_BADGE.get(cl, ("Unconfirmed", "amber"))
    P.append('<div class="card %s">' % bcls)
    P.append('<div class="chead"><span class="case">%s <span class="pg">&middot; p.%s</span></span><span class="badge %s">%s</span></div>' % (esc(g(cid,"cited_case")), esc(g(cid,"page")), bcls, esc(btxt)))
    P.append('<div class="note">%s</div>' % UNCONF_NOTE.get(cid, ""))
    P.append('<div class="for">Cited for: %s</div>' % esc(trunc(g(cid,"proposition"), 95)))
    P.append('</div>')
P.append('</section>')

# ---------- PAGE 2 ----------
P.append('<section class="page2">')
P.append('<h2>2&nbsp;&nbsp;Quotation errors<span class="cnt">%d</span></h2>' % (len(QUOTE_FAB)+len(QUOTE_REWORD)))
P.append('<p class="lead">Language placed in quotation marks in the order that does not appear in the cited opinion, or is materially reworded. (Minor apostrophe/ellipsis differences in accurate quotes are excluded.)</p>')
for cid in QUOTE_FAB:
    P.append('<div class="card red">')
    P.append('<div class="chead"><span class="case">%s <span class="pg">&middot; p.%s</span></span><span class="badge red">Fabricated quote</span></div>' % (esc(g(cid,"cited_case")), esc(g(cid,"page"))))
    for q in quotes(cid):
        P.append('<div class="quote">&ldquo;%s&rdquo;</div>' % esc(q))
    P.append('<div class="note">Does not appear in the cited opinion &mdash; remove or correct.</div>')
    P.append('</div>')
for cid in QUOTE_REWORD:
    P.append('<div class="card amber">')
    P.append('<div class="chead"><span class="case">%s <span class="pg">&middot; p.%s</span></span><span class="badge amber">Reworded quote</span></div>' % (esc(g(cid,"cited_case")), esc(g(cid,"page"))))
    for q in quotes(cid):
        P.append('<div class="quote amber">&ldquo;%s&rdquo;</div>' % esc(q))
    P.append('<div class="note">Substance is supported, but the quoted words differ from the opinion &mdash; re-quote verbatim or drop the quotation marks.</div>')
    P.append('</div>')
P.append('<div class="tip"><b>Note:</b> <i>Taylor v. State</i> also carries a &ldquo;fabricated quote&rdquo; flag in the raw data, but it was checked against the wrong opinion and is excluded here; the same sentence is verified as accurate where the order quotes it via <i>Hargrave v. State</i>.</div>')
P.append('<footer>Generated from /proposition-verifier output. Full detail: report.html &middot; FINDINGS_2026-06-24.md.</footer>')
P.append('</section>')

P.append('</body></html>')

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write("\n".join(P))
print("wrote", OUT_HTML)
print("section1:", len(UNCONFIRMED), "cards | section2:", len(QUOTE_FAB)+len(QUOTE_REWORD), "cards")
