"""Build report.html for payne-proposed in Kettering format."""
import csv
import json
from datetime import datetime

with open("briefs/payne-proposed/claims.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

green = [r for r in rows if r["assessment"] == "Green"]
yellow = [r for r in rows if r["assessment"] == "Yellow"]
red = [r for r in rows if r["assessment"] == "Red"]


def esc(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def make_retrieved(r):
    status = r.get("cl_status", "")
    url = r.get("cl_url", "")
    retrieved_case = r.get("retrieved_case", "")

    if status == "VERIFIED":
        if url:
            label = retrieved_case if retrieved_case else "Verified"
            return '<a href="{}">{}</a> &mdash; Verified'.format(url, esc(label))
        return "Verified"
    elif status == "POSSIBLE_MATCH":
        if url:
            label = retrieved_case if retrieved_case else "Check Name"
            return '<a href="{}">{}</a> &mdash; Check Name'.format(url, esc(label))
        return "Possible Match"
    elif status == "LIKELY_REAL":
        if url:
            label = retrieved_case if retrieved_case else "Likely Real"
            return '<a href="{}">{}</a> &mdash; Likely Real'.format(url, esc(label))
        return "Likely Real"
    else:
        return "Not Found"


def make_supporting(r):
    parts = []
    assessment = r.get("assessment", "")
    supporting = r.get("supporting_language", "")
    qc_raw = r.get("quote_check", "")

    # Parse quote check results
    qc_items = []
    if qc_raw:
        try:
            qc_items = json.loads(qc_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    # Show quote comparisons if any
    for item in qc_items:
        quote = item.get("quote", "")
        result = item.get("result", "")
        sim = item.get("similarity", 0)

        if result == "VERBATIM":
            cls = "passage-supports"
            label = "VERBATIM"
        elif result == "CLOSE":
            cls = "passage-partial"
            label = "CLOSE ({:.0%})".format(sim)
        elif result == "FABRICATED":
            cls = "passage-contradicts"
            label = "FABRICATED ({:.0%})".format(sim)
        else:
            cls = "passage-different"
            label = result

        parts.append(
            '<div class="quote-compare">'
            '<div class="quote-label">Brief quotes:</div>'
            '<div class="passage {}">&ldquo;{}&rdquo;</div>'
            '<div class="quote-result {}"> {}</div>'
            '</div>'.format(cls, esc(quote), cls, label)
        )

    # Assessment rationale
    if assessment == "Red":
        cls = "passage-contradicts"
    elif assessment == "Yellow":
        cls = "passage-partial"
    else:
        cls = "passage-supports"

    parts.append('<div class="passage {}">{}</div>'.format(cls, esc(supporting)))
    return "\n".join(parts)


def assessment_cell(r):
    assessment = r.get("assessment", "")
    qcw = r.get("quote_check_worst", "")
    cls = "assess-{}".format(assessment.lower())
    sl = r.get("supporting_language", "")

    if assessment == "Red":
        if "Wrong case" in sl or "typo" in sl.lower():
            label = "Red &mdash; Wrong case at citation"
        elif "FABRICATED" in sl:
            label = "Red &mdash; Fabricated quote / wrong case"
        elif "Does not discuss" in sl or "Never" in sl or "is a " in sl:
            label = "Red &mdash; Case does not address cited topic"
        else:
            label = "Red &mdash; Does not support proposition"
    elif assessment == "Yellow":
        if "Wrong case name" in sl:
            label = "Yellow &mdash; Wrong case name, partially related"
        elif "FABRICATED" in sl:
            label = "Yellow &mdash; Fabricated quote, substance partially supported"
        elif "overstate" in sl.lower() or "embellish" in sl.lower():
            label = "Yellow &mdash; Proposition overstates holding"
        else:
            label = "Yellow &mdash; Partially relevant"
    else:
        if qcw == "VERBATIM":
            label = "Green &mdash; Verbatim"
        else:
            label = "Green"

    return '<td class="{}">{}</td>'.format(cls, label)


def render_table(claims, show_supporting=True):
    if show_supporting:
        html = '<table><thead><tr><th>Pg</th><th>Proposition</th><th>Cited Case</th><th>Retrieved</th><th>Supporting Language</th><th>Assessment</th></tr></thead><tbody>\n'
    else:
        html = '<table><thead><tr><th>Pg</th><th>Proposition</th><th>Cited Case</th><th>Assessment</th></tr></thead><tbody>\n'

    for r in claims:
        html += "<tr>\n"
        html += '<td class="page-num">{}</td>\n'.format(r.get("page", ""))
        html += '<td class="proposition">{}</td>\n'.format(esc(r.get("proposition", "")))
        html += '<td class="cited-case">{}</td>\n'.format(esc(r.get("cited_case", "")))
        if show_supporting:
            html += '<td class="retrieved">{}</td>\n'.format(make_retrieved(r))
            html += '<td class="supporting">{}</td>\n'.format(make_supporting(r))
        html += assessment_cell(r) + "\n"
        html += "</tr>\n"

    html += "</tbody></table>\n"
    return html


now = datetime.now()
date_str = now.strftime("%B %d, %Y")

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Citation Verification Report - State v. Payne (Proposed Order)</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Georgia', serif; color: #1a1a1a; max-width: 1200px; margin: 0 auto; padding: 20px; background: #fafafa; }
  h1 { font-size: 1.4em; margin-bottom: 5px; }
  h2 { font-size: 1.15em; margin: 25px 0 10px; border-bottom: 2px solid #333; padding-bottom: 5px; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 20px; }
  .summary { display: flex; gap: 15px; margin: 15px 0 25px; }
  .stat { padding: 12px 20px; border-radius: 6px; font-weight: bold; font-size: 1.1em; }
  .stat-green { background: #d4edda; color: #155724; }
  .stat-yellow { background: #fff3cd; color: #856404; }
  .stat-red { background: #f8d7da; color: #721c24; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0 25px; font-size: 0.85em; }
  th { background: #2c3e50; color: white; padding: 10px 8px; text-align: left; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; }
  td { padding: 10px 8px; border-bottom: 1px solid #ddd; vertical-align: top; }
  tr:hover td { background: #f0f4f8; }
  .assess-green { background: #d4edda; color: #155724; font-weight: bold; border-left: 4px solid #28a745; }
  .assess-yellow { background: #fff3cd; color: #856404; font-weight: bold; border-left: 4px solid #ffc107; }
  .assess-red { background: #f8d7da; color: #721c24; font-weight: bold; border-left: 4px solid #dc3545; }
  .proposition { max-width: 280px; font-style: italic; }
  .cited-case { max-width: 200px; font-weight: 500; }
  .retrieved { max-width: 200px; font-size: 0.85em; }
  .supporting { max-width: 300px; font-size: 0.85em; line-height: 1.4; }
  .passage { background: #f8f9fa; border-left: 3px solid #6c757d; padding: 6px 10px; margin: 4px 0; font-size: 0.9em; }
  .passage-supports { border-left-color: #28a745; }
  .passage-contradicts { border-left-color: #dc3545; }
  .passage-different { border-left-color: #6c757d; }
  .passage-partial { border-left-color: #ffc107; }
  .quote-compare { margin-bottom: 8px; }
  .quote-label { font-size: 0.8em; color: #666; font-weight: bold; margin-bottom: 2px; }
  .quote-result { font-size: 0.75em; font-weight: bold; padding: 2px 6px; display: inline-block; margin-top: 2px; border-radius: 3px; }
  .quote-result.passage-supports { background: #d4edda; color: #155724; }
  .quote-result.passage-contradicts { background: #f8d7da; color: #721c24; }
  .quote-result.passage-partial { background: #fff3cd; color: #856404; }
  a { color: #4a6fa5; }
  .page-num { font-weight: bold; text-align: center; min-width: 40px; }
  .footer { margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; color: #999; font-size: 0.8em; }
</style>
</head>
<body>

<h1>Citation Verification Report</h1>
<div class="meta">
  <strong>Brief:</strong> Proposed Order Denying Defendant's Motion for New Trial as Amended<br>
  <strong>Case:</strong> State of Georgia v. Hannah Renee Payne, Case No. 2019CR01737-14 (Superior Court of Clayton County)<br>
  <strong>Analyzed:</strong> """ + date_str + """ &nbsp;|&nbsp; <strong>Total claims:</strong> """ + str(len(rows)) + """ proposition-case pairs (53 unique citations)
</div>

<div class="summary">
  <div class="stat stat-green">""" + str(len(green)) + """ Green</div>
  <div class="stat stat-yellow">""" + str(len(yellow)) + """ Yellow</div>
  <div class="stat stat-red">""" + str(len(red)) + """ Red</div>
</div>

<h2>Red Assessments &mdash; Citations with Issues (""" + str(len(red)) + """)</h2>
"""

html += render_table(red, show_supporting=True)

html += "<h2>Yellow Assessments &mdash; Partially Supporting (" + str(len(yellow)) + ")</h2>\n"
html += render_table(yellow, show_supporting=True)

html += "<h2>Green Assessments &mdash; Properly Supported (" + str(len(green)) + ")</h2>\n"
html += render_table(green, show_supporting=False)

html += """
<div class="footer">
  Generated by verify-brief skill &nbsp;|&nbsp; Citation verification via <a href="https://www.courtlistener.com/">CourtListener</a> API &nbsp;|&nbsp; """ + date_str + """
</div>

</body>
</html>
"""

with open("briefs/payne-proposed/report.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Report written: {} red, {} yellow, {} green".format(len(red), len(yellow), len(green)))
