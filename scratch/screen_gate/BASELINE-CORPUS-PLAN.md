# Baseline Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stratified reference distribution of *normal* filings so the `screen` gate can score any document's surface-metric profile as deviation-from-its-stratum, then test whether the 11 known-bad docs deviate more than the baseline's own members.

**Architecture:** Build the deterministic measuring apparatus first, fully tested offline (Tasks 1–3): a shared `metrics.py` extractor, a `compute_baselines.py` aggregator, and a deviation-scoring extension to `run_gate.py`. Then collect the corpus via sonnet retrieval agents (Task 4), and run the gate verdict (Task 5).

**Tech Stack:** Python 3.10+, eyecite (AhocorasickTokenizer spine via `signal_battery`), `citation_verifier` package, pytest. CourtListener/RECAP for retrieval (courtlistener MCP or `AsyncCourtListenerClient`).

**Design of record:** `scratch/screen_gate/BASELINE-CORPUS-DESIGN.md`. Companion context: `PROJECT.md`, `GATE-RESULTS.md`.

## Global Constraints

- **Windows env:** the Python executable is `venv/Scripts/python.exe` (not `python`/`python3`). Run all commands from repo root `C:\Users\Rebecca Fordon\Projects\citation-verifier`. Tests: `venv/Scripts/python.exe -m pytest`.
- **Working directory for scripts:** the screen-gate scripts import `signal_battery` and run from `scratch/screen_gate/`. Tests for them live in `scratch/screen_gate/` and are invoked with that cwd.
- **Code is deterministic, zero-network, zero-LLM** (Tasks 1–3, 5). Every metric is a fact about the text — no model judgment.
- **Retrieval (Task 4) runs on sonnet agents**, never a reasoning model (PROJECT.md §7 tiering).
- **No minimum-citation floor** on baseline selection — the natural distribution, sparse filings included.
- **`filer_type` is assigned per document** (counsel-of-record vs. pro se signature), never assumed from the case caption.
- **Sanction screen is mandatory** per baseline doc: docket must be clean of sanction / show-cause / fabrication / hallucination history.
- **Commit style:** messages prefixed `screen-gate:`, ending with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer. Commit and push to branch `screen-signals-gate` after each task (the user syncs across machines).
- **Metric vector (canonical key order), produced by `compute_metrics` and used everywhere downstream:** `n_cites` (int), `words` (int), `cite_density` (float), `parenthetical_richness` (float), `string_cite_rate` (float), `gerund_paren_rate` (float), `has_toa` (bool), `proposition_repeat_rate` (float), `cite_prop_cv` (float).

---

### Task 1: Shared deterministic metric extractor (`metrics.py`)

Consolidate the metrics prototyped across `probe_texture.py` and `probe_repetition.py` into one importable extractor. This is the single source of truth for the feature vector; both the baseline aggregator and the gate consume it.

**Files:**
- Create: `scratch/screen_gate/metrics.py`
- Test: `scratch/screen_gate/test_metrics.py`

**Interfaces:**
- Consumes: `signal_battery.normalize(raw:str)->str`, `signal_battery.extract_cites(text:str)->list[dict]` (each dict has keys `cite:str`, `pos:int`), `signal_battery.TOA_START_RE` (compiled regex).
- Produces: `compute_metrics(raw:str)->dict` returning exactly the 9-key metric vector in the Global Constraints order.

- [ ] **Step 1: Write the failing tests**

Create `scratch/screen_gate/test_metrics.py`:

```python
from metrics import compute_metrics

METRIC_KEYS = ["n_cites", "words", "cite_density", "parenthetical_richness",
               "string_cite_rate", "gerund_paren_rate", "has_toa",
               "proposition_repeat_rate", "cite_prop_cv"]


def test_returns_full_vector():
    m = compute_metrics("Some text with no citations at all.")
    assert list(m.keys()) == METRIC_KEYS


def test_empty_text_is_safe():
    m = compute_metrics("")
    assert m["n_cites"] == 0
    assert m["cite_density"] == 0.0
    assert m["parenthetical_richness"] == 0.0
    assert m["proposition_repeat_rate"] == 0.0
    assert m["has_toa"] is False


def test_gerund_parenthetical_counts():
    # one citation, one gerund-led parenthetical
    txt = "The court agreed. Smith v. Jones, 500 U.S. 100 (2001) (holding that liability attaches)."
    m = compute_metrics(txt)
    assert m["n_cites"] >= 1
    assert m["gerund_paren_rate"] > 0.0


def test_proposition_repeat_detects_reshuffled_cites():
    # same proposition restated with a DIFFERENT citation -> a repeat pair
    txt = ("The statute bars retaliation against protected employees. "
           "Alpha v. Beta, 100 F.3d 200 (9th Cir. 1999). "
           "The statute bars retaliation against protected employees. "
           "Gamma v. Delta, 300 F.3d 400 (9th Cir. 2001).")
    m = compute_metrics(txt)
    assert m["proposition_repeat_rate"] > 0.0


def test_mph_fixture_pins_cite_count():
    # pins the current eyecite spine (matches GATE-RESULTS first run)
    raw = open("fixtures/support-community-mph--cand-63.md",
               encoding="utf-8", errors="replace").read()
    m = compute_metrics(raw)
    assert m["n_cites"] == 111
    assert m["cite_density"] > 0
    assert isinstance(m["has_toa"], bool)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metrics'`.

- [ ] **Step 3: Write `metrics.py`**

Create `scratch/screen_gate/metrics.py`:

```python
"""Shared deterministic surface-metric extractor for the screen baseline gate.

Consolidates the metrics prototyped in probe_texture.py + probe_repetition.py
into one importable function. Zero-network, no LLM: every metric is a fact about
the text. compute_metrics(raw) -> the canonical 9-key vector.
"""
from __future__ import annotations

import re

from signal_battery import normalize, extract_cites, TOA_START_RE

GERUNDS = ("holding", "finding", "noting", "concluding", "reasoning",
           "explaining", "stating", "affirming", "reversing", "rejecting",
           "recognizing", "acknowledging", "observing", "quoting", "citing",
           "granting", "denying", "ruling", "declining", "upholding", "applying")
GERUND_PAREN_RE = re.compile(r"\(\s*(?:" + "|".join(GERUNDS) + r")\b", re.IGNORECASE)
ANY_PAREN_RE = re.compile(
    r"\(\s*(?:[a-z]{3,}ing|per curiam|en banc|plurality|dissent|concurr|"
    r"emphasis|internal|quotation)", re.IGNORECASE)

STOP = set("""a an the of to in on at by for with from as and or but nor so yet
that this these those which who whom whose it its it's is are was were be been
being has have had do does did not no than then thus hence such same other any
all each both few more most some no only own very can will just about into over
under out up down off then once here there when where why how i we you he she
they them their our your his her would could should may might must shall see also
id supra infra cf accord e.g i.e viz ante post et al v vs case court held holding
finding plaintiff plaintiffs defendant defendants motion cite cited citing""".split())

SENT_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def _content_tokens(s: str) -> set:
    toks = {w.lower() for w in WORD_RE.findall(s)}
    return {t for t in toks if t not in STOP and len(t) >= 3}


def _sentences_with_spans(text: str):
    out, pos = [], 0
    for piece in SENT_SPLIT_RE.split(text):
        idx = text.find(piece, pos)
        if idx < 0:
            idx = pos
        out.append((idx, idx + len(piece), piece))
        pos = idx + len(piece)
    return out


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _propositions(text: str, cites):
    """Sentences carrying >=1 citation and >=4 content tokens."""
    out = []
    for s0, s1, stext in _sentences_with_spans(text):
        cs = {c["cite"] for c in cites if s0 <= c["pos"] < s1 and c["cite"]}
        if not cs:
            continue
        toks = _content_tokens(stext)
        if len(toks) < 4:
            continue
        out.append({"tokens": toks, "cites": cs})
    return out


def compute_metrics(raw: str) -> dict:
    text = normalize(raw)
    cites = extract_cites(text)
    n = len(cites)
    words = max(1, len(text.split()))
    gp = len(GERUND_PAREN_RE.findall(text))
    ap = len(ANY_PAREN_RE.findall(text))

    props = _propositions(text, cites)
    nprop = len(props)
    string_props = sum(1 for p in props if len(p["cites"]) >= 2)

    repeat_pairs = 0
    for i in range(nprop):
        for j in range(i + 1, nprop):
            if (_jaccard(props[i]["tokens"], props[j]["tokens"]) >= 0.6
                    and props[i]["cites"] != props[j]["cites"]):
                repeat_pairs += 1

    counts = [len(p["cites"]) for p in props]
    if counts:
        mu = sum(counts) / len(counts)
        var = sum((c - mu) ** 2 for c in counts) / len(counts)
        cv = (var ** 0.5) / mu if mu else 0.0
    else:
        cv = 0.0

    return {
        "n_cites": n,
        "words": words,
        "cite_density": round(1000 * n / words, 3),
        "parenthetical_richness": round(ap / n, 3) if n else 0.0,
        "string_cite_rate": round(string_props / nprop, 3) if nprop else 0.0,
        "gerund_paren_rate": round(gp / n, 3) if n else 0.0,
        "has_toa": bool(TOA_START_RE.search(text)),
        "proposition_repeat_rate": round(repeat_pairs / nprop, 3) if nprop else 0.0,
        "cite_prop_cv": round(cv, 3),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_metrics.py -v`
Expected: 5 passed. (If `test_mph_fixture_pins_cite_count` fails on the count, the eyecite spine drifted — update the pinned value and note it in `GATE-RESULTS.md`.)

- [ ] **Step 5: Commit**

```bash
git add scratch/screen_gate/metrics.py scratch/screen_gate/test_metrics.py
git commit -m "screen-gate: shared metrics.py extractor (consolidates probes)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin screen-signals-gate
```

---

### Task 2: Baseline aggregator (`compute_baselines.py`)

Walk the `baseline/` tree, compute the metric vector per document into `metrics.csv`, and reduce to per-cell **median + MAD** in `baselines.json`. Cell identity comes from the per-cell manifest rows.

**Files:**
- Create: `scratch/screen_gate/compute_baselines.py`
- Test: `scratch/screen_gate/test_compute_baselines.py`

**Interfaces:**
- Consumes: `metrics.compute_metrics`; the Global Constraints metric key list.
- Produces:
  - `mad(values:list[float])->float` — median absolute deviation.
  - `cell_baseline(rows:list[dict])->dict` — maps each metric name to `{"median":float,"mad":float,"n":int}`; `rows` are per-doc dicts each holding the 9 metric keys.
  - `CELLS:list[str]` — the six canonical cell names `"<filer>__<doctype>"` for `filer in {attorney,pro_se}` × `doctype in {merits_brief,pleading,procedural_motion}`.
  - CLI `python compute_baselines.py <baseline_root>` writing `metrics.csv` + `baselines.json`.

- [ ] **Step 1: Write the failing tests**

Create `scratch/screen_gate/test_compute_baselines.py`:

```python
from compute_baselines import mad, cell_baseline, CELLS


def test_cells_are_six_canonical():
    assert set(CELLS) == {
        "attorney__merits_brief", "attorney__pleading", "attorney__procedural_motion",
        "pro_se__merits_brief", "pro_se__pleading", "pro_se__procedural_motion",
    }


def test_mad_basic():
    # values 1,2,4,4,5 -> median 4 -> abs devs 3,2,0,0,1 -> median 1
    assert mad([1, 2, 4, 4, 5]) == 1.0


def test_mad_empty_is_zero():
    assert mad([]) == 0.0


def test_cell_baseline_shape_and_values():
    rows = [
        {"n_cites": 10, "cite_density": 5.0},
        {"n_cites": 20, "cite_density": 7.0},
        {"n_cites": 30, "cite_density": 9.0},
    ]
    b = cell_baseline(rows)
    assert b["n_cites"]["median"] == 20
    assert b["n_cites"]["n"] == 3
    assert b["cite_density"]["median"] == 7.0
    assert "mad" in b["n_cites"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_compute_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'compute_baselines'`.

- [ ] **Step 3: Write `compute_baselines.py`**

Create `scratch/screen_gate/compute_baselines.py`:

```python
"""Aggregate the baseline/ tree into per-doc metrics.csv and per-cell
median+MAD baselines.json. Cell = '<filer_type>__<doc_type>'.

Usage: python compute_baselines.py <baseline_root>
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys

from metrics import compute_metrics

FILERS = ["attorney", "pro_se"]
DOCTYPES = ["merits_brief", "pleading", "procedural_motion"]
CELLS = [f"{f}__{d}" for f in FILERS for d in DOCTYPES]

METRIC_KEYS = ["n_cites", "words", "cite_density", "parenthetical_richness",
               "string_cite_rate", "gerund_paren_rate", "has_toa",
               "proposition_repeat_rate", "cite_prop_cv"]
# has_toa is boolean -> excluded from median/MAD (reported as a rate separately)
NUMERIC_KEYS = [k for k in METRIC_KEYS if k != "has_toa"]


def mad(values):
    """Median absolute deviation."""
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    med = statistics.median(vals)
    return statistics.median([abs(v - med) for v in vals])


def cell_baseline(rows):
    """rows: per-doc metric dicts. -> {metric: {median, mad, n}} for numeric keys."""
    out = {}
    for k in NUMERIC_KEYS:
        vals = [float(r[k]) for r in rows if k in r]
        if not vals:
            continue
        out[k] = {"median": statistics.median(vals), "mad": mad(vals),
                  "n": len(vals)}
    return out


def load_manifest_rows(cell_dir):
    """Read every manifest-*.jsonl in a cell dir -> list of manifest dicts."""
    rows = []
    for fn in os.listdir(cell_dir):
        if fn.startswith("manifest-") and fn.endswith(".jsonl"):
            with open(os.path.join(cell_dir, fn), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
    return rows


def build(baseline_root):
    metric_rows, by_cell = [], {c: [] for c in CELLS}
    for cell in CELLS:
        cell_dir = os.path.join(baseline_root, cell)
        if not os.path.isdir(cell_dir):
            continue
        for man in load_manifest_rows(cell_dir):
            slug = man["slug"]
            txt_path = os.path.join(cell_dir, f"{slug}.txt")
            if not os.path.exists(txt_path):
                continue
            raw = open(txt_path, encoding="utf-8", errors="replace").read()
            m = compute_metrics(raw)
            row = {"slug": slug, "cell": cell,
                   "filer_type": man.get("filer_type", ""),
                   "doc_type": man.get("doc_type", ""), **m}
            metric_rows.append(row)
            by_cell[cell].append(m)

    baselines = {c: cell_baseline(rows) for c, rows in by_cell.items() if rows}

    with open(os.path.join(baseline_root, "metrics.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["slug", "cell", "filer_type",
                                           "doc_type"] + METRIC_KEYS)
        w.writeheader()
        w.writerows(metric_rows)
    with open(os.path.join(baseline_root, "baselines.json"), "w",
              encoding="utf-8") as fh:
        json.dump(baselines, fh, indent=2)
    return metric_rows, baselines


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    rows, bl = build(root)
    print(f"wrote metrics for {len(rows)} docs across {len(bl)} cells -> "
          f"{root}/metrics.csv, {root}/baselines.json")
    for cell in CELLS:
        n = sum(1 for r in rows if r["cell"] == cell)
        print(f"  {cell:28s}: {n}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_compute_baselines.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scratch/screen_gate/compute_baselines.py scratch/screen_gate/test_compute_baselines.py
git commit -m "screen-gate: baseline aggregator (metrics.csv + per-cell median/MAD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin screen-signals-gate
```

---

### Task 3: Deviation scoring + gate test (extend `run_gate.py`)

Add robust-z deviation scoring: score any doc against its cell baseline, flag metrics beyond a whisker, and report whether the 11 known-bad docs deviate more than the baseline's own members (leave-one-out null rate).

**Files:**
- Modify: `scratch/screen_gate/run_gate.py` (add functions + a `--deviation <baseline_root>` mode; leave the existing Tier-0 report intact)
- Test: `scratch/screen_gate/test_deviation.py`

**Interfaces:**
- Consumes: `metrics.compute_metrics`; `compute_baselines.NUMERIC_KEYS`; a `baselines.json` dict shaped `{cell:{metric:{median,mad,n}}}`.
- Produces:
  - `robust_z(x:float, median:float, mad:float)->float` — `(x-median)/(1.4826*mad)`, `0.0` when `mad==0`.
  - `deviation_flags(m:dict, cell_baseline:dict, z_thresh:float=3.5)->dict` — maps metric→signed z for metrics with `abs(z)>=z_thresh`.
  - `bad_doc_cells()->dict` — maps each of the 11 bad-doc slugs to its `"<filer>__<doctype>"` cell (hard-coded from PROJECT.md §4 + the manifests).

- [ ] **Step 1: Write the failing tests**

Create `scratch/screen_gate/test_deviation.py`:

```python
from run_gate import robust_z, deviation_flags, bad_doc_cells


def test_robust_z_zero_mad_is_zero():
    assert robust_z(100.0, 5.0, 0.0) == 0.0


def test_robust_z_scales_by_mad():
    # x=10, median=4, mad=1 -> (10-4)/(1.4826*1) ~= 4.047
    z = robust_z(10.0, 4.0, 1.0)
    assert 4.0 < z < 4.1


def test_deviation_flags_only_beyond_threshold():
    baseline = {
        "cite_density": {"median": 5.0, "mad": 1.0, "n": 12},
        "n_cites": {"median": 20.0, "mad": 4.0, "n": 12},
    }
    # cite_density wildly high, n_cites normal
    m = {"cite_density": 40.0, "n_cites": 21}
    flags = deviation_flags(m, baseline, z_thresh=3.5)
    assert "cite_density" in flags
    assert "n_cites" not in flags
    assert flags["cite_density"] > 0


def test_bad_doc_cells_covers_eleven():
    cells = bad_doc_cells()
    assert len(cells) == 11
    assert cells["stafford-taffet"] == "pro_se__merits_brief"
    assert cells["support-community-mph--cand-63"] == "attorney__merits_brief"
    assert set(cells.values()) <= {
        "attorney__merits_brief", "attorney__pleading", "attorney__procedural_motion",
        "pro_se__merits_brief", "pro_se__pleading", "pro_se__procedural_motion"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_deviation.py -v`
Expected: FAIL with `ImportError: cannot import name 'robust_z'`.

- [ ] **Step 3: Add the deviation code to `run_gate.py`**

Append to `scratch/screen_gate/run_gate.py` (keep existing content; add imports at top if missing):

```python
import json as _json
from metrics import compute_metrics
from compute_baselines import NUMERIC_KEYS

# Bad-doc -> cell map (PROJECT.md §4 strata + retrieval manifests).
# doc_type: merits_brief = MSJ/MTD memos, oppositions, replies, discovery
# *memoranda* that argue law; pleading = complaints; procedural_motion = bare
# procedural motions. Assignments below reflect each filing's actual role.
_BAD_DOC_CELLS = {
    "support-community-mph--cand-63": "attorney__merits_brief",
    "tantaros-fox-news":              "attorney__merits_brief",
    "tantaros-fox-news-surreply":     "attorney__merits_brief",
    "withers-aberdeen":               "attorney__merits_brief",
    "villalovos-vandepol":            "attorney__procedural_motion",
    "johnson-dunn":                   "attorney__procedural_motion",
    "braun-day":                      "attorney__procedural_motion",
    "reed-community-health":          "pro_se__merits_brief",
    "stafford-taffet":                "pro_se__merits_brief",
    "sherwood-botetourt":             "pro_se__pleading",
    "burnside-verdick":               "pro_se__pleading",
}


def bad_doc_cells():
    return dict(_BAD_DOC_CELLS)


def robust_z(x, median, mad):
    if mad == 0:
        return 0.0
    return (float(x) - float(median)) / (1.4826 * float(mad))


def deviation_flags(m, cell_baseline, z_thresh=3.5):
    flags = {}
    for k in NUMERIC_KEYS:
        if k in cell_baseline and k in m:
            z = robust_z(m[k], cell_baseline[k]["median"], cell_baseline[k]["mad"])
            if abs(z) >= z_thresh:
                flags[k] = round(z, 2)
    return flags


def run_deviation(baseline_root, z_thresh=3.5):
    """Score the 11 bad docs against their cell baselines and print the gate
    test: bad-doc deviation rate vs. the baseline's own leave-one-out tail rate."""
    with open(os.path.join(baseline_root, "baselines.json"), encoding="utf-8") as fh:
        baselines = _json.load(fh)

    print("=" * 78)
    print("DEVIATION GATE — bad docs vs. stratum baseline")
    print("=" * 78)
    cells = bad_doc_cells()
    for slug, cell in cells.items():
        path = os.path.join(CORPUS_ROOT, "bad", slug)
        txt = None
        for ext in (".txt", ".md"):
            if os.path.exists(path + ext):
                txt = open(path + ext, encoding="utf-8", errors="replace").read()
                break
        if txt is None:
            print(f"  {slug:32s} [MISSING TEXT]")
            continue
        cb = baselines.get(cell)
        if not cb:
            print(f"  {slug:32s} cell={cell} [NO BASELINE YET]")
            continue
        m = compute_metrics(txt)
        flags = deviation_flags(m, cb, z_thresh)
        fdesc = ", ".join(f"{k}={v:+.1f}" for k, v in flags.items()) or "(none)"
        print(f"  {slug:32s} {cell:24s} flags: {fdesc}")

    # baseline self-tail rate (leave-one-out) per cell, per metric
    print("\nBaseline own-tail rate (LOO) per cell/metric — the null to beat:")
    metrics_csv = os.path.join(baseline_root, "metrics.csv")
    import csv as _csv
    rows = list(_csv.DictReader(open(metrics_csv, encoding="utf-8"))) \
        if os.path.exists(metrics_csv) else []
    for cell in sorted({r["cell"] for r in rows}):
        crows = [r for r in rows if r["cell"] == cell]
        if len(crows) < 3:
            print(f"  {cell:24s} n={len(crows)} (too few for LOO)")
            continue
        tail = 0
        for i, r in enumerate(crows):
            others = crows[:i] + crows[i + 1:]
            cb = {k: {"median": __import__("statistics").median(
                        [float(o[k]) for o in others]),
                      "mad": __import__("compute_baselines").mad(
                        [float(o[k]) for o in others])}
                  for k in NUMERIC_KEYS}
            if deviation_flags({k: float(r[k]) for k in NUMERIC_KEYS}, cb, z_thresh):
                tail += 1
        print(f"  {cell:24s} n={len(crows)} own-tail={tail}/{len(crows)}")
```

Then extend the `__main__` block: add an `--deviation` argument that calls `run_deviation(args.deviation)` when provided (else the existing report).

```python
    ap.add_argument("--deviation", metavar="BASELINE_ROOT",
                    help="score bad docs against a baseline tree")
    # ... after parsing:
    if args.deviation:
        run_deviation(args.deviation)
        raise SystemExit(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest test_deviation.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full screen-gate test suite (no regressions)**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe -m pytest -v`
Expected: `test_signal_battery.py`, `test_metrics.py`, `test_compute_baselines.py`, `test_deviation.py` all pass.

- [ ] **Step 6: Commit**

```bash
git add scratch/screen_gate/run_gate.py scratch/screen_gate/test_deviation.py
git commit -m "screen-gate: robust-z deviation scoring + LOO gate test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin screen-signals-gate
```

---

### Task 4: Retrieval build — populate `baseline/` (sonnet agents)

Collect the reference corpus. This task is **data collection, not a TDD cycle**: its deliverable is the `baseline/` tree with clean manifest rows and saved text, and its acceptance is coverage per cell. Executed via **sonnet** subagents — one per cell (6 agents), dispatchable in parallel.

**Files:**
- Create: `scratch/screen_gate/baseline/<cell>/<slug>.txt` (extracted filing text, one per doc)
- Create: `scratch/screen_gate/baseline/<cell>/manifest-<cell>.jsonl` (one row per doc)

**Cell directories (create all six):**
`attorney__merits_brief`, `attorney__pleading`, `attorney__procedural_motion`, `pro_se__merits_brief`, `pro_se__pleading`, `pro_se__procedural_motion`.

**Per-document manifest row schema (exact keys):**
```json
{"slug": "smith-v-jones-msj", "court": "cand", "docket_id": 12345678,
 "document_number": 37, "filer_type": "attorney", "doc_type": "merits_brief",
 "recap_url": "https://www.courtlistener.com/docket/12345678/37/...",
 "is_available": true, "sanction_screen": "clean: 0 hits for sanction/show cause/fabricat/hallucin",
 "notes": "MSJ memo, counsel of record Jane Roe (Firm LLP); 31 case cites"}
```

**Per-cell agent protocol (give this verbatim to each retrieval subagent):**

1. Pick your assigned cell = `<filer_type>__<doc_type>`.
2. Search federal RECAP for docket entries whose description matches the doc-type:
   - `merits_brief` → "Memorandum in Support" / "Motion for Summary Judgment" / "Response in Opposition" / "Reply" tied to an MSJ or MTD.
   - `pleading` → "Complaint" / "Amended Complaint".
   - `procedural_motion` → "Motion to Compel" / "Motion to Remand" / "Discovery" / other non-dispositive motions.
   Use `search` type=`r`/`rd` (courtlistener MCP) or `AsyncCourtListenerClient`; request only the `is_available=true` documents.
3. For each candidate, determine `filer_type` **per document**: attorney = a counsel-of-record signature / attorney appearance; pro_se = a pro se signature block. Discard if it does not match your cell.
4. **Sanction screen the docket:** search the docket's entries/text for `sanction`, `show cause`, `fabricat`, `hallucin`, `fictitious`, `non-existent`. If any hit is a real sanction/OSC against the filer, **discard** the document. Record the screen result string in `sanction_screen`.
5. Fetch the document's extracted text (the canonical fallback chain — `read_document`, or `client.get_opinion_text`/RECAP `plain_text`; never a plain_text-only fetcher). Save to `baseline/<cell>/<slug>.txt`.
6. Append the manifest row. `slug` = short kebab case, unique within the cell.
7. **No minimum-citation floor** — keep sparse filings. Sample across different courts and dates; do not take N consecutive hits from one docket or firm.

**Acceptance criteria:**
- [ ] All six `baseline/<cell>/` directories exist.
- [ ] **Phase 1 target: ≥10 docs per cell.** If a cell (expected: the pro se cells) yields fewer clean docs, record the shortfall in a `baseline/SHORTFALLS.md` note rather than padding with near-misses.
- [ ] Every saved `.txt` has a matching manifest row; every manifest row's `filer_type`/`doc_type` matches its cell directory.
- [ ] Every manifest row has a non-empty `sanction_screen` string.
- [ ] `git add scratch/screen_gate/baseline && git commit -m "screen-gate: baseline corpus phase-1 pull" && git push` (commit the text + manifests — working data is synced per repo policy).

**Dispatch note:** launch the six retrieval agents with `subagent_type` sonnet (via `superpowers:dispatching-parallel-agents`); each owns exactly one cell so there is no shared-file contention.

---

### Task 5: Run the deviation gate + write the verdict

With the corpus in place, compute baselines and run the gate test.

**Files:**
- Create: `scratch/screen_gate/baseline/metrics.csv`, `scratch/screen_gate/baseline/baselines.json` (generated)
- Modify: `scratch/screen_gate/GATE-RESULTS.md` (append the deviation-gate verdict)

- [ ] **Step 1: Build the baselines**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe compute_baselines.py baseline`
Expected: prints per-cell doc counts; writes `baseline/metrics.csv` + `baseline/baselines.json`.

- [ ] **Step 2: Run the deviation gate**

Run: `cd scratch/screen_gate && ../../venv/Scripts/python.exe run_gate.py --deviation baseline`
Expected: per-bad-doc deviation flags + per-cell baseline own-tail (LOO) rate.

- [ ] **Step 3: Write the verdict**

Append a `## Deviation gate — first run` section to `GATE-RESULTS.md` recording, **per stratum/cell**: which metrics flag the bad docs, the bad-doc deviation rate vs. the baseline's own-tail (LOO) rate, and the per-cell n (flagging thin pro se cells honestly). State plainly which metrics separate (bad deviation rate clears the baseline own-tail rate within a cell) and which do not — the ship rule from `PROJECT.md` §6.3 applied against a real reference distribution. Note whether Phase 2 (expand to 20/cell) is warranted.

- [ ] **Step 4: Commit**

```bash
git add scratch/screen_gate/baseline/metrics.csv scratch/screen_gate/baseline/baselines.json scratch/screen_gate/GATE-RESULTS.md
git commit -m "screen-gate: deviation gate first run + verdict

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin screen-signals-gate
```

---

## Self-Review

**Spec coverage** (against `BASELINE-CORPUS-DESIGN.md`):
- §1 reference distribution / bad docs as test set → Task 3 (`bad_doc_cells`), Task 4, Task 5. ✔
- §2 filer×doctype 6 cells → Task 2 `CELLS`, Task 4 dirs. ✔
- §3 selection frame (is_available, per-doc filer, sanction screen, no cite floor) → Task 4 protocol + Global Constraints. ✔
- §4 phased 10→20/cell, pro se shortfall honesty → Task 4 acceptance + Task 5 Phase-2 note. ✔
- §5 metric schema (9 keys) → Task 1. ✔
- §6 median+MAD, robust-z, gate test → Tasks 2 & 3. ✔
- §7 artifacts/location → Tasks 2, 4, 5 paths. ✔
- §8 sonnet retrieval → Task 4 dispatch note. ✔
- §9 out of scope (no LLM/coherence/purchases) → honored; no task adds them. ✔

**Placeholder scan:** no TBD/TODO; every code step shows complete code; the one non-TDD task (4) is data collection with explicit acceptance criteria, not a hidden placeholder.

**Type consistency:** `compute_metrics->dict` (9 keys) consumed identically in Tasks 2/3; `NUMERIC_KEYS` excludes `has_toa` consistently; `cell = "<filer>__<doctype>"` naming identical in `CELLS`, `_BAD_DOC_CELLS`, and Task 4 dirs; `mad`/`cell_baseline`/`robust_z`/`deviation_flags` signatures match across tasks.
