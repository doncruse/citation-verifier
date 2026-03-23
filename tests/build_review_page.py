"""Build an HTML review page for A/B test ground truth cases.

Shows all test cases from Payne + Wainwright with columns for:
- Source brief, case ID, cited case, proposition
- Quote check results
- Machine assessment (if any)
- Human judgment column (editable)
- Notes column (editable)

The page has a "Copy JSON" button that exports the reviewed data
as JSON for pasting back into ab_test_cases.json.
"""
import csv
import json
from pathlib import Path


def esc(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_page():
    # Load Payne test cases (already curated)
    with open("tests/ab_test_cases.json") as f:
        payne_data = json.load(f)

    # Load Payne full claims for extra context
    with open("briefs/payne-proposed/claims.csv", encoding="utf-8") as f:
        payne_claims = list(csv.DictReader(f))

    # Load Wainwright claims
    with open("briefs/wainwright-v-state/claims.csv", encoding="utf-8") as f:
        wain_claims = list(csv.DictReader(f))

    rows_html = ""
    row_id = 0

    # --- Payne cases ---
    for tc in payne_data["cases"]:
        cid = tc["id"]
        claim = payne_claims[cid] if cid < len(payne_claims) else {}
        qc_raw = claim.get("quote_check", "")
        qc_display = ""
        if qc_raw:
            try:
                items = json.loads(qc_raw)
                parts = []
                for item in items:
                    parts.append('{}: "{}"'.format(
                        item.get("result", ""),
                        item.get("quote", "")[:60]))
                qc_display = "; ".join(parts)
            except (json.JSONDecodeError, TypeError):
                pass

        rows_html += """<tr data-row="{row_id}" data-source="payne" data-case-id="{cid}" data-opinion-file="{opinion_file}" data-quotes="{quotes}">
<td>{row_id}</td>
<td>Payne</td>
<td>{cid}</td>
<td class="cited-case">{cited}</td>
<td class="proposition">{prop}</td>
<td class="qc">{qcw}</td>
<td class="qc-detail">{qc_detail}</td>
<td class="machine-assess assess-{assess_lower}">{assess}</td>
<td><select class="human-judgment" data-row="{row_id}">
  <option value="">--</option>
  <option value="Green">Green</option>
  <option value="Yellow">Yellow</option>
  <option value="Red">Red</option>
</select></td>
<td><input type="text" class="human-notes" data-row="{row_id}" placeholder="notes..." style="width:100%"></td>
</tr>
""".format(
            row_id=row_id,
            cid=cid,
            cited=esc(tc.get("cited_case", "")),
            prop=esc(tc.get("proposition", "")),
            qcw=tc.get("quote_check_worst", ""),
            qc_detail=esc(qc_display),
            assess=tc.get("expected_assessment", ""),
            assess_lower=tc.get("expected_assessment", "").lower(),
            opinion_file=esc(claim.get("opinion_file", "")),
            quotes=esc(claim.get("quoted_text", "").replace('"', "")[:100]),
        )
        row_id += 1

    # --- Wainwright cases ---
    for i, claim in enumerate(wain_claims):
        qc_raw = claim.get("quote_check", "")
        qc_display = ""
        if qc_raw:
            try:
                items = json.loads(qc_raw)
                parts = []
                for item in items:
                    parts.append('{}: "{}"'.format(
                        item.get("result", ""),
                        item.get("quote", "")[:60]))
                qc_display = "; ".join(parts)
            except (json.JSONDecodeError, TypeError):
                pass

        assess = claim.get("assessment", "")

        rows_html += """<tr data-row="{row_id}" data-source="wainwright" data-case-id="{cid}" data-opinion-file="{opinion_file}" data-quotes="{quotes}">
<td>{row_id}</td>
<td>Wainwright</td>
<td>{cid}</td>
<td class="cited-case">{cited}</td>
<td class="proposition">{prop}</td>
<td class="qc">{qcw}</td>
<td class="qc-detail">{qc_detail}</td>
<td class="machine-assess assess-{assess_lower}">{assess}</td>
<td><select class="human-judgment" data-row="{row_id}">
  <option value="">--</option>
  <option value="Green">Green</option>
  <option value="Yellow">Yellow</option>
  <option value="Red">Red</option>
</select></td>
<td><input type="text" class="human-notes" data-row="{row_id}" placeholder="notes..." style="width:100%"></td>
</tr>
""".format(
            row_id=row_id,
            cid=i,
            cited=esc(claim.get("cited_case", "")),
            prop=esc(claim.get("proposition", "")),
            qcw=claim.get("quote_check_worst", ""),
            qc_detail=esc(qc_display),
            assess=assess,
            assess_lower=assess.lower() if assess else "",
            opinion_file=esc(claim.get("opinion_file", "")),
            quotes=esc(claim.get("quoted_text", "").replace('"', "")[:100]),
        )
        row_id += 1

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>A/B Test Ground Truth Review</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', sans-serif; font-size: 13px; background: #f5f5f5; overflow: hidden; height: 100vh; }
.container { display: flex; height: 100vh; }
.left-panel { flex: 1; overflow-y: auto; padding: 15px; min-width: 0; }
.right-panel { width: 45%; border-left: 2px solid #2c3e50; display: flex; flex-direction: column;
               background: #fff; }
.right-panel.collapsed { width: 0; min-width: 0; overflow: hidden; border: none; }
.panel-header { background: #2c3e50; color: white; padding: 10px; font-size: 0.85em; flex-shrink: 0; }
.panel-header .case-name { font-weight: bold; font-size: 1.1em; }
.panel-header .panel-prop { font-style: italic; margin-top: 5px; color: #bdc3c7; }
.panel-header .panel-quotes { margin-top: 5px; font-size: 0.9em; color: #f39c12; }
.panel-close { float: right; cursor: pointer; font-size: 1.2em; padding: 0 5px; }
.panel-close:hover { color: #e74c3c; }
.search-bar { display: flex; gap: 5px; margin-top: 8px; align-items: center; }
.search-bar input { flex: 1; padding: 5px 8px; border: none; border-radius: 3px; font-size: 12px; }
.search-bar button { padding: 4px 10px; background: #34495e; border: 1px solid #4a6fa5; font-size: 11px; }
.search-bar .search-count { color: #bdc3c7; font-size: 0.85em; min-width: 50px; }
.search-hl { background: #fff176; padding: 1px 0; }
.search-hl.current { background: #ff9800; color: white; }
#opinion-frame { flex: 1; border: none; width: 100%; }
h1 { font-size: 1.3em; margin-bottom: 5px; }
.meta { color: #666; margin-bottom: 15px; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th { background: #2c3e50; color: white; padding: 8px 6px; text-align: left; font-size: 0.75em;
     text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; z-index: 10; }
td { padding: 6px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }
tr:hover td { background: #f0f4f8; }
tr.selected td { background: #d6eaf8 !important; }
.cited-case { max-width: 180px; font-weight: 500; font-size: 0.9em; }
.proposition { max-width: 260px; font-style: italic; font-size: 0.9em; cursor: pointer; }
.proposition:hover { text-decoration: underline; color: #2c3e50; }
.qc { font-size: 0.8em; font-weight: bold; }
.qc-detail { font-size: 0.75em; color: #666; max-width: 180px; }
.assess-green { background: #d4edda; color: #155724; font-weight: bold; }
.assess-yellow { background: #fff3cd; color: #856404; font-weight: bold; }
.assess-red { background: #f8d7da; color: #721c24; font-weight: bold; }
select { padding: 4px; font-size: 12px; }
input[type="text"] { padding: 4px; font-size: 12px; border: 1px solid #ccc; border-radius: 3px; }
.toolbar { margin: 15px 0; display: flex; gap: 10px; align-items: center; }
button { padding: 8px 16px; background: #2c3e50; color: white; border: none; border-radius: 4px;
         cursor: pointer; font-size: 13px; }
button:hover { background: #34495e; }
#export-output { display: none; margin-top: 10px; width: 100%; height: 200px; font-family: monospace;
                 font-size: 11px; }
.count { margin-left: 20px; font-size: 0.9em; color: #666; }
</style>
</head>
<body>

<div class="container">
<div class="left-panel">

<h1>A/B Test Ground Truth Review</h1>
<div class="meta">
Click any proposition to view the cited opinion in the side panel.
Set your human judgment and add notes. Export when done.
<span class="count" id="progress">0 / TOTAL reviewed</span>
</div>

<div class="toolbar">
<button onclick="exportJSON()">Export JSON</button>
<button onclick="prefillFromMachine()">Pre-fill from Machine</button>
</div>
<textarea id="export-output" readonly></textarea>

<table>
<thead>
<tr>
<th>#</th>
<th>Source</th>
<th>Cited Case</th>
<th>Proposition (click to view opinion)</th>
<th>QC</th>
<th>Quote Detail</th>
<th>Machine</th>
<th>Human</th>
<th>Notes</th>
</tr>
</thead>
<tbody>
""" + rows_html + """
</tbody>
</table>

</div><!-- left-panel -->

<div class="right-panel collapsed" id="right-panel">
<div class="panel-header" id="panel-header">
  <span class="panel-close" onclick="closePanel()">&times;</span>
  <div class="case-name" id="panel-case"></div>
  <div class="panel-prop" id="panel-prop"></div>
  <div class="panel-quotes" id="panel-quotes"></div>
  <div class="search-bar">
    <input type="text" id="opinion-search" placeholder="Search opinion text..." onkeydown="if(event.key==='Enter')searchOpinion()">
    <button onclick="searchOpinion()">Find</button>
    <button onclick="searchNext()">Next</button>
    <button onclick="searchPrev()">Prev</button>
    <span class="search-count" id="search-count"></span>
  </div>
</div>
<div id="opinion-content" style="flex:1; overflow-y:auto; padding:15px; font-size:13px; line-height:1.6;"></div>
</div>

</div><!-- container -->

<script>
const TOTAL = """ + str(row_id) + """;

function updateProgress() {
    const selects = document.querySelectorAll('.human-judgment');
    let filled = 0;
    selects.forEach(s => { if (s.value) filled++; });
    document.getElementById('progress').textContent = filled + ' / ' + TOTAL + ' reviewed';
}

document.querySelectorAll('.human-judgment').forEach(s => {
    s.addEventListener('change', updateProgress);
});

// Click handler for propositions
document.querySelectorAll('tr[data-row]').forEach(tr => {
    const propCell = tr.querySelector('.proposition');
    if (propCell) {
        propCell.addEventListener('click', function() {
            // Highlight selected row
            document.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
            tr.classList.add('selected');

            const source = tr.dataset.source;
            const caseName = tr.querySelector('.cited-case').textContent;
            const prop = tr.querySelector('.proposition').textContent;
            const opinionFile = tr.dataset.opinionFile || '';
            const quotes = tr.dataset.quotes || '';

            // Update panel header
            document.getElementById('panel-case').textContent = caseName;
            document.getElementById('panel-prop').textContent = prop;
            if (quotes) {
                document.getElementById('panel-quotes').textContent = 'Search for: ' + quotes;
                document.getElementById('panel-quotes').style.display = 'block';
            } else {
                document.getElementById('panel-quotes').style.display = 'none';
            }

            // Load opinion in iframe
            const panel = document.getElementById('right-panel');
            panel.classList.remove('collapsed');

            // Clear previous search
            document.getElementById('opinion-search').value = '';
            document.getElementById('search-count').textContent = '';
            searchMatches = [];
            searchIndex = -1;

            if (opinionFile) {
                const basePath = source === 'payne' ? '../briefs/payne-proposed/' : '../briefs/wainwright-v-state/';
                loadOpinion(basePath + opinionFile);
            } else {
                document.getElementById('opinion-content').innerHTML = '<p style="color:#999;">No opinion file available.</p>';
            }
        });
    }
});

function closePanel() {
    document.getElementById('right-panel').classList.add('collapsed');
    document.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
}

function prefillFromMachine() {
    document.querySelectorAll('tr[data-row]').forEach(tr => {
        const machineCell = tr.querySelector('.machine-assess');
        const select = tr.querySelector('.human-judgment');
        if (machineCell && select && !select.value) {
            const val = machineCell.textContent.trim();
            if (['Green','Yellow','Red'].includes(val)) {
                select.value = val;
            }
        }
    });
    updateProgress();
}

function exportJSON() {
    const cases = [];
    document.querySelectorAll('tr[data-row]').forEach(tr => {
        const source = tr.dataset.source;
        const caseId = parseInt(tr.dataset.caseId);
        const cited = tr.querySelector('.cited-case').textContent;
        const prop = tr.querySelector('.proposition').textContent;
        const machine = tr.querySelector('.machine-assess').textContent.trim();
        const human = tr.querySelector('.human-judgment').value;
        const notes = tr.querySelector('.human-notes').value;
        const qc = tr.querySelector('.qc').textContent;
        const opinionFile = tr.dataset.opinionFile || '';

        if (human) {
            cases.push({
                source: source,
                id: caseId,
                opinion_file: opinionFile,
                cited_case: cited,
                proposition: prop,
                expected_assessment: human,
                machine_assessment: machine,
                quote_check_worst: qc,
                notes: notes
            });
        }
    });

    const output = JSON.stringify({cases: cases}, null, 2);
    const textarea = document.getElementById('export-output');
    textarea.style.display = 'block';
    textarea.value = output;
    textarea.select();
    navigator.clipboard.writeText(output).then(() => {
        alert('Copied ' + cases.length + ' reviewed cases to clipboard!');
    }).catch(() => {
        alert('JSON ready in textarea below. Select all and copy manually.');
    });
}

// --- Load opinion into div ---
function loadOpinion(url) {
    const container = document.getElementById('opinion-content');
    container.innerHTML = '<p style="color:#999;">Loading...</p>';
    fetch(url)
        .then(r => r.text())
        .then(html => {
            // For HTML files, extract body content; for txt, wrap in pre
            if (url.endsWith('.txt')) {
                container.innerHTML = '<pre style="white-space:pre-wrap;font-family:Georgia,serif;font-size:13px;">' + html.replace(/</g,'&lt;') + '</pre>';
            } else {
                // Strip <html>/<head>/<body> wrappers, keep inner content
                const match = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
                container.innerHTML = match ? match[1] : html;
            }
        })
        .catch(e => {
            container.innerHTML = '<p style="color:#c00;">Could not load opinion: ' + e.message + '</p>';
        });
}

// --- Opinion search ---
let searchMatches = [];
let searchIndex = -1;

function clearHighlights() {
    const container = document.getElementById('opinion-content');
    container.querySelectorAll('.search-hl').forEach(el => {
        const parent = el.parentNode;
        parent.replaceChild(document.createTextNode(el.textContent), el);
        parent.normalize();
    });
}

function searchOpinion() {
    const query = document.getElementById('opinion-search').value.trim();
    if (!query) return;

    clearHighlights();
    searchMatches = [];
    searchIndex = -1;

    const container = document.getElementById('opinion-content');
    if (!container.textContent.trim()) {
        document.getElementById('search-count').textContent = 'no doc';
        return;
    }

    // Walk text nodes and highlight matches
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    const lowerQuery = query.toLowerCase();
    const nodesToProcess = [];

    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.textContent.toLowerCase().includes(lowerQuery)) {
            nodesToProcess.push(node);
        }
    }

    nodesToProcess.forEach(node => {
        const text = node.textContent;
        const lowerText = text.toLowerCase();
        let idx = 0;
        const frag = document.createDocumentFragment();
        let pos;

        while ((pos = lowerText.indexOf(lowerQuery, idx)) !== -1) {
            if (pos > idx) {
                frag.appendChild(document.createTextNode(text.substring(idx, pos)));
            }
            const span = document.createElement('span');
            span.className = 'search-hl';
            span.textContent = text.substring(pos, pos + query.length);
            frag.appendChild(span);
            searchMatches.push(span);
            idx = pos + query.length;
        }

        if (idx < text.length) {
            frag.appendChild(document.createTextNode(text.substring(idx)));
        }

        node.parentNode.replaceChild(frag, node);
    });

    document.getElementById('search-count').textContent = searchMatches.length + ' found';

    if (searchMatches.length > 0) {
        searchIndex = 0;
        scrollToMatch();
    }
}

function scrollToMatch() {
    if (searchMatches.length === 0) return;
    // Remove current highlight from all
    searchMatches.forEach(m => m.classList.remove('current'));
    // Add to current
    const match = searchMatches[searchIndex];
    match.classList.add('current');
    match.scrollIntoView({ behavior: 'smooth', block: 'center' });
    document.getElementById('search-count').textContent =
        (searchIndex + 1) + ' / ' + searchMatches.length;
}

function searchNext() {
    if (searchMatches.length === 0) return;
    searchIndex = (searchIndex + 1) % searchMatches.length;
    scrollToMatch();
}

function searchPrev() {
    if (searchMatches.length === 0) return;
    searchIndex = (searchIndex - 1 + searchMatches.length) % searchMatches.length;
    scrollToMatch();
}
</script>
</body>
</html>
"""

    outpath = Path("tests/ab_test_review.html")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)
    print("Review page written to {}".format(outpath))
    print("  Payne cases: {}".format(len(payne_data["cases"])))
    print("  Wainwright cases: {}".format(len(wain_claims)))
    print("  Total: {}".format(row_id))


if __name__ == "__main__":
    build_page()
