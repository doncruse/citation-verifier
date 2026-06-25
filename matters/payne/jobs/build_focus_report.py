# -*- coding: utf-8 -*-
import csv, os, json, html

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = {r["claim_id"]: r for r in csv.DictReader(open(os.path.join(workdir, "claims.csv"), encoding="utf-8"))}

RUN_DATE = "2026-06-24"
OUT = os.path.join(workdir, "report_focus_2026-06-24_not-found-and-quotes.html")

def g(cid, k): return (rows[cid].get(k) or "").strip()
def esc(s): return html.escape(s or "")
def slug_name(url):
    if not url: return ""
    parts = [p for p in url.strip("/").split("/") if p]
    return parts[-1].replace("-", " ").title() if parts else ""
def quotes(cid):
    raw = g(cid, "quoted_text")
    try:
        arr = json.loads(raw) if raw else []
    except Exception:
        arr = []
    return [q for q in arr if q]

# ---- categorization ----
UNCONFIRMED = ["payne-03","payne-08","payne-09","payne-20","payne-55","payne-02","payne-23","payne-21"]
ARTIFACT_RES = ["payne-73","payne-74","payne-80","payne-05","payne-27"]
QUOTE_FAB = ["payne-11","payne-13","payne-14","payne-57","payne-58"]
QUOTE_REWORD = ["payne-34"]

# notes for unconfirmed (resolved-case info / context)
UNCONF_NOTE = {
    "payne-03": "CourtListener finds a different case at <b>288 Ga. 768</b>: <i>%s</i>. The cited name/volume/page do not line up — verify by hand." % esc(slug_name(g("payne-03","cl_url"))),
    "payne-08": "CourtListener finds a different case at <b>283 Ga. 155</b>: <i>%s</i>. Verify the citation by hand." % esc(slug_name(g("payne-08","cl_url"))),
    "payne-09": "CourtListener finds a different case at <b>269 Ga. App. 242</b>: <i>%s</i>. Verify the citation by hand." % esc(slug_name(g("payne-09","cl_url"))),
    "payne-20": "CourtListener finds a different case at <b>268 Ga. App. 362</b>: <i>%s</i>. Verify the citation by hand." % esc(slug_name(g("payne-20","cl_url"))),
    "payne-55": "CourtListener finds a different case at <b>279 Ga. 50</b>: <i>%s</i>. This is almost certainly a typo — the order cites <b>Patel v. State, 279 Ga. <u>750</u></b> elsewhere. Confirm the intended pincite." % esc(slug_name(g("payne-55","cl_url"))),
    "payne-02": "Not found at the cited reporter (NOT_FOUND). <i>Reynolds</i> is cited throughout for Georgia's adoption of <i>Strickland</i>; likely a verifier miss rather than a bad cite, but confirm <b>306 Ga. 630</b> by hand.",
    "payne-23": "Short-form repeat of the <i>Reynolds</i> cite above (p.24). Same NOT_FOUND result — confirm <b>306 Ga. 630</b> by hand.",
    "payne-21": "Cited with <b>no reporter citation</b> (year only), so it could not be looked up. Supply the full cite — <i>United States v. Valenzuela-Bernal</i>, 458 U.S. 858 (1982) — and re-check.",
}
ARTIFACT_NOTE = {
    "payne-73": "<i>Taylor v. State</i> <b>was verified at CourtListener</b> (correctly cited, quoting the new-trial-discretion standard). The Red is a tool artifact: no distinct <code>Taylor</code> opinion file was saved, so the claim was compared against <code>Black_v_State.html</code>. <b>Disregard — not a brief defect.</b>",
    "payne-74": "<i>Jackson v. Virginia</i>, 443 U.S. 307 — the federal sufficiency-of-the-evidence standard — <b>was verified at CourtListener</b> and is correctly cited. The Red is a tool artifact: it was compared against <code>Johnson_v_Jackson.html</code> (a different Georgia case). <b>Disregard.</b>",
    "payne-80": "Second correct citation to <i>Jackson v. Virginia</i>, 443 U.S. 307 (p.35), <b>verified at CourtListener</b>. Same linkage artifact as above. <b>Disregard.</b>",
    "payne-05": "<i>Davis v. State</i>, 285 Ga. 343 (2009) <b>was verified at CourtListener</b>. Marked unverifiable only because its opinion file collided with the unrelated 1998 <i>Davis v. State</i>, 269 Ga. 276 (same <code>Davis_v_State.html</code> filename). Confirm the 2009 opinion supports the point; the citation itself resolves.",
    "payne-27": "Repeat of the 2009 <i>Davis</i> cite (p.25). Same filename-collision artifact. The citation resolves at CourtListener.",
}

CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#23201c;--muted:#6b6358;--line:#e7e2d9;
--red:#b42318;--redbg:#fef3f2;--amber:#b54708;--amberbg:#fffaeb;--gray:#475467;--graybg:#f2f4f7;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:860px;margin:0 auto;padding:40px 24px 80px;}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin:0 0 6px}
.meta{color:var(--muted);font-size:13px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:10px 0;margin:18px 0 28px}
.meta b{color:var(--ink)}
h2{font-size:19px;margin:38px 0 4px;letter-spacing:-.01em}
.lead{color:var(--muted);font-size:14px;margin:0 0 16px}
.count{display:inline-block;background:var(--graybg);color:var(--gray);border-radius:20px;padding:1px 10px;font-size:13px;font-weight:600;margin-left:8px;vertical-align:middle}
.card{background:var(--card);border:1px solid var(--line);border-left-width:5px;border-radius:10px;padding:16px 18px;margin:12px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.card.red{border-left-color:var(--red)}
.card.amber{border-left-color:var(--amber)}
.card.gray{border-left-color:var(--gray)}
.case{font-weight:700;font-size:16px;margin:0 0 2px}
.pg{color:var(--muted);font-size:12.5px;font-weight:500}
.badge{display:inline-block;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:2px 8px;border-radius:5px;margin:6px 0 8px}
.badge.red{background:var(--redbg);color:var(--red)}
.badge.amber{background:var(--amberbg);color:var(--amber)}
.badge.gray{background:var(--graybg);color:var(--gray)}
.row{margin:8px 0}
.lbl{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:2px}
.prop{font-size:14.5px}
.quote{background:var(--redbg);border-left:3px solid var(--red);padding:8px 12px;border-radius:0 6px 6px 0;font-size:14px;color:#7a271a;font-style:italic}
.quote.amber{background:var(--amberbg);border-left-color:var(--amber);color:#7a4a0a}
.sent{background:#f7f5f1;border-radius:6px;padding:8px 12px;font-size:13.5px;color:#433f38}
.note{font-size:14px}
.note.gray{color:var(--gray)}
code{background:#f2f0ec;padding:1px 5px;border-radius:4px;font-size:12.5px}
.tip{background:#f0f7ff;border:1px solid #d6e8ff;border-radius:8px;padding:12px 16px;font-size:13.5px;color:#1c3d5a;margin:16px 0 0}
footer{margin-top:46px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}
"""

def card(cid, klass, badge_txt, badge_cls, note_html, show_quote=False, quote_cls="amber"):
    h = ['<div class="card %s">' % klass]
    h.append('<div class="case">%s <span class="pg">&nbsp;· p.%s</span></div>' % (esc(g(cid,"cited_case")), esc(g(cid,"page"))))
    h.append('<span class="badge %s">%s</span>' % (badge_cls, esc(badge_txt)))
    h.append('<div class="row"><div class="lbl">Cited for</div><div class="prop">%s</div></div>' % esc(g(cid,"proposition")))
    if show_quote:
        for q in quotes(cid):
            h.append('<div class="row"><div class="lbl">Quoted in the order (not found / altered in the opinion)</div><div class="quote %s">“%s”</div></div>' % (quote_cls, esc(q)))
    fa = g(cid,"finding_analysis")
    if fa:
        h.append('<div class="row"><div class="lbl">Assessment</div><div class="note">%s</div></div>' % esc(fa))
    if note_html:
        h.append('<div class="row"><div class="lbl">What to do</div><div class="note %s">%s</div></div>' % ("gray" if klass=="gray" else "", note_html))
    h.append('</div>')
    return "\n".join(h)

parts = []
parts.append('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payne — Not-found / Quotation issues</title><style>%s</style></head><body><div class="wrap">' % CSS)
parts.append('<h1>Not-Found / Mismatched Citations &amp; Quotation Errors</h1>')
parts.append('<p class="sub"><i>State of Georgia v. Hannah Renee Payne</i>, No. 2019CR01737-14 &mdash; Order Denying Motion for New Trial (proposed)</p>')
parts.append('<div class="meta">Filtered view &mdash; run <b>%s</b> &middot; assess-v2 / Opus &middot; code <b>efd173d</b><br>Shows only citation-resolution problems and quotation errors. Full results: <code>report.html</code> &middot; supporting data: <code>claims.csv</code>.</div>' % RUN_DATE)

# Section 1
parts.append('<h2>1 &nbsp;Citations that could not be confirmed<span class="count">%d</span></h2>' % len(UNCONFIRMED))
parts.append('<p class="lead">CourtListener could not match the cited case at the cited reporter location. These were <b>not machine-assessed</b> and need a manual check &mdash; some may be additional hallucinated or garbled citations.</p>')
for cid in UNCONFIRMED:
    cl = g(cid,"cl_status")
    if cl == "WRONG_CASE":
        parts.append(card(cid, "red", "Wrong case at this citation", "red", UNCONF_NOTE.get(cid,"")))
    else:
        parts.append(card(cid, "amber", cl.replace("_"," ").title() if cl else "Unconfirmed", "amber", UNCONF_NOTE.get(cid,"")))

# Section 2
parts.append('<h2>2 &nbsp;Quotation errors<span class="count">%d</span></h2>' % (len(QUOTE_FAB)+len(QUOTE_REWORD)))
parts.append('<p class="lead">Language placed inside quotation marks in the order that does not appear in the cited opinion, or that has been materially reworded. (Minor apostrophe/ellipsis differences in otherwise-accurate quotes are excluded.)</p>')
for cid in QUOTE_FAB:
    parts.append(card(cid, "red", "Fabricated quote — not in the opinion", "red", "Remove or correct the quotation; the cited opinion does not contain this language.", show_quote=True, quote_cls=""))
for cid in QUOTE_REWORD:
    parts.append(card(cid, "amber", "Reworded — not a verbatim quote", "amber", "Substance is supported, but the quoted words differ from the opinion. Re-quote verbatim or convert to a paraphrase without quotation marks.", show_quote=True, quote_cls="amber"))
parts.append('<div class="tip"><b>Note:</b> <i>Taylor v. State</i> (payne-73) also carries a &ldquo;fabricated quote&rdquo; flag in the raw data, but it was checked against the wrong opinion and is excluded here. The identical sentence is verified as accurate where the order quotes it via <i>Hargrave v. State</i>. Not a real quotation error.</div>')

parts.append('<footer>Generated from the /proposition-verifier pipeline output for this matter. This is a filtered companion to the full report; it omits the verified, overstated, and topic-mismatch findings. See <code>FINDINGS_2026-06-24.md</code> for the complete write-up.</footer>')
parts.append('</div></body></html>')

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(parts))
print("wrote", OUT)
print("section1 unconfirmed:", len(UNCONFIRMED), "| section2 artifacts:", len(ARTIFACT_RES), "| section3 quotes:", len(QUOTE_FAB)+len(QUOTE_REWORD))
