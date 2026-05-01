# Case Law Retrieval Benchmark v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-model leaderboard (Sonnet 4.6 / Opus 4.7 / GPT-5) on 200 fresh-mined federal district parentheticals, scored on Real / Name-match / Supports axes by Opus 4.7.

**Architecture:** Five separately-runnable scripts in `tests/benchmark_v1/` mirroring Pilot A's pattern: build dataset → run each model → score → scorecard. Output to `benchmark_v1/` at repo root.

**Tech Stack:** Python 3.10+, eyecite, citation-verifier, `claude -p` CLI for Claude models, `openai` SDK for GPT-5.

**Spec:** [docs/plans/2026-04-30-benchmark-v1-design.md](2026-04-30-benchmark-v1-design.md)

---

## Task 0: Prerequisites — verify model cutoffs and add OpenAI

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env`

**Why:** Spec requires every model's training cutoff to be on or before 2025-12-31 for the 2026-01-01-to-04-30 sample window to be defensible. Also need OpenAI dep + key for GPT-5.

- [ ] **Step 1: Verify Claude model cutoffs**

Run from a hermetic dir (so project CLAUDE.md doesn't interfere):

```bash
mkdir -p /tmp/cutoff_check && cd /tmp/cutoff_check
claude -p "What is your training data cutoff date? Respond with ONLY the date in YYYY-MM-DD format, nothing else." --model sonnet --output-format json
claude -p "What is your training data cutoff date? Respond with ONLY the date in YYYY-MM-DD format, nothing else." --model opus --output-format json
```

Expected: both report a date <= 2025-12-31. If either is later, escalate to user before continuing.

- [ ] **Step 2: Verify GPT-5 cutoff via OpenAI docs**

WebFetch OpenAI's model docs for GPT-5 (search "GPT-5 training cutoff" or check https://platform.openai.com/docs/models). Document the cutoff in this plan's notes section. Expected: well before 2026-01-01.

- [ ] **Step 3: Install OpenAI SDK**

```bash
"venv/Scripts/python.exe" -m pip install "openai>=1.40"
```

- [ ] **Step 4: Add openai to pyproject.toml**

Edit `pyproject.toml`, add `"openai>=1.40"` to the `dependencies` list (next to existing `requests>=2.28`).

- [ ] **Step 5: Add OPENAI_API_KEY to .env**

Stop and ask the user to paste their OpenAI key into `.env`:
```
OPENAI_API_KEY=sk-...
```
Verify with:
```bash
"venv/Scripts/python.exe" -c "import os; from dotenv import load_dotenv; load_dotenv(); print('OK' if os.environ.get('OPENAI_API_KEY','').startswith('sk-') else 'MISSING')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add openai SDK for benchmark v1 GPT-5 calls"
```

(Don't commit `.env` — it's gitignored.)

---

## Task 1: Scaffold benchmark_v1 module and output dir

**Files:**
- Create: `tests/benchmark_v1/__init__.py`
- Create: `benchmark_v1/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Make directories**

```bash
mkdir -p tests/benchmark_v1 benchmark_v1
touch tests/benchmark_v1/__init__.py benchmark_v1/.gitkeep
```

- [ ] **Step 2: gitignore the OpenAI/Claude output caches but keep the deliverables**

Edit `.gitignore`, add:

```
# Benchmark v1 — opinion-text caches (regenerable)
benchmark_v1/_opinion_cache/

# Benchmark v1 — chatty run logs (regenerable; keep CSVs and markdown)
benchmark_v1/_*.txt
```

Note: outputs_*.csv, results.csv, dataset.csv, scorecards.md, README.md are **all** committed (per the user preference: "always commit working data").

- [ ] **Step 3: Commit**

```bash
git add tests/benchmark_v1/__init__.py benchmark_v1/.gitkeep .gitignore
git commit -m "scaffold: benchmark_v1 module + output dir"
```

---

## Task 2: Build the multi-district dataset

**Files:**
- Create: `tests/benchmark_v1/build_dataset.py`

**Why:** Pilot A's mining code is tied to D.D.C. Need a parameterized version that loops over 5 districts and applies the precedential-status fix.

- [ ] **Step 1: Write build_dataset.py**

Create `tests/benchmark_v1/build_dataset.py`:

```python
"""Mine 40 parentheticals each from 5 federal districts -> dataset.csv.

Reuses Pilot A's parenthetical-extraction logic. New: loops over court IDs,
applies the stat_Published=on&stat_Unknown=on filter, stratified-samples
40 per district.
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

import eyecite
from eyecite.models import FullCaseCitation
from eyecite.tokenizers import AhocorasickTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Reuse Pilot A's helpers verbatim where possible.
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "pilot_a"))
from build_fresh_dc_sample import (  # noqa: E402
    HOLDING_VERBS,
    MIN_WORDS,
    MAX_WORDS,
    _normalize_text,
    _is_explanatory_parenthetical,
    _word_count,
    extract_parentheticals,
)

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
OPINION_TEXT_CACHE = PROJECT_ROOT / "benchmark_v1" / "_opinion_cache"
RAW_POOL = PROJECT_ROOT / "benchmark_v1" / "_raw_pool.json"

# 5 districts, in priority order. NYSD has fallback if empty.
COURTS = ["dcd", "cand", "txsd", "ilnd", "nysd"]
COURTS_FALLBACK = ["mad", "paed"]  # used if a primary district has < 80 verified

DATE_FROM = "2026-01-01"
DATE_TO = "2026-04-30"
SAMPLE_PER_COURT = 40
OPINIONS_PER_COURT = 200  # oversample budget
SEED = 42


def fetch_opinion_list(client: CourtListenerClient, court_id: str) -> list[dict[str, Any]]:
    """Page through D.D.C.-style search but with stat_Unknown=on."""
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < OPINIONS_PER_COURT:
        r = client._request_with_retry(
            "GET",
            f"{client.BASE_URL}/search/",
            params={
                "type": "o",
                "court": court_id,
                "filed_after": DATE_FROM,
                "filed_before": DATE_TO,
                "stat_Published": "on",
                "stat_Unknown": "on",
                "order_by": "dateFiled desc",
                "page_size": 50,
                "page": page,
            },
        )
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        for hit in results:
            out.append({
                "cluster_id": hit.get("cluster_id"),
                "case_name": hit.get("caseName") or "",
                "date_filed": hit.get("dateFiled") or "",
                "court_id": court_id,
            })
            if len(out) >= OPINIONS_PER_COURT:
                break
        page += 1
        if not data.get("next"):
            break
    return out


def fetch_opinion_text(client: CourtListenerClient, cluster_id: int) -> str:
    """Cache-backed opinion text fetch. Reuses pilot_a opinion_cache when possible."""
    OPINION_TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OPINION_TEXT_CACHE / f"{cluster_id}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    # Fallback: try Pilot A's cache too
    pilot_cache = (PROJECT_ROOT / "scratch" / "pilot_a" / "_dcd_opinion_cache"
                   / f"{cluster_id}.txt")
    if pilot_cache.exists():
        text = pilot_cache.read_text(encoding="utf-8", errors="replace")
        cache.write_text(text, encoding="utf-8")
        return text
    cluster = client._request_with_retry(
        "GET", f"{client.BASE_URL}/clusters/{cluster_id}/"
    ).json()
    sub_ops = cluster.get("sub_opinions") or []
    if not sub_ops:
        return ""
    op = client._request_with_retry("GET", sub_ops[0]).json()
    text = op.get("plain_text") or ""
    cache.write_text(text, encoding="utf-8")
    return text


async def verify_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verifier = CitationVerifier()
    parsed = [parsed_citation_from_eyecite(item["fcc"]) for item in pool]
    citation_strs = [item["citation_text"] for item in pool]
    results = await verifier.verify_batch(citation_strs, parsed_citations=parsed,
                                          quick_only=True)
    keep: list[dict[str, Any]] = []
    for item, res in zip(pool, results):
        if res.status in (VerificationStatus.VERIFIED, VerificationStatus.LIKELY_REAL):
            item = {k: v for k, v in item.items() if k != "fcc"}
            item["v_status"] = res.status.value
            item["v_url"] = res.matched_url or ""
            item["v_matched_name"] = res.matched_case_name or ""
            keep.append(item)
    return keep


def mine_court(client: CourtListenerClient, court_id: str,
               tokenizer: AhocorasickTokenizer) -> list[dict[str, Any]]:
    print(f"\n=== {court_id} ===")
    opinions = fetch_opinion_list(client, court_id)
    print(f"  {court_id}: got {len(opinions)} opinions in date range", flush=True)
    if not opinions:
        return []
    pool: list[dict[str, Any]] = []
    for i, op in enumerate(opinions, 1):
        try:
            text = fetch_opinion_text(client, op["cluster_id"])
        except Exception as exc:
            print(f"  fetch fail cluster {op['cluster_id']}: {exc}", file=sys.stderr)
            continue
        if not text:
            continue
        for p in extract_parentheticals(text, tokenizer):
            p["citing_cluster_id"] = op["cluster_id"]
            p["citing_case"] = op["case_name"]
            p["citing_date"] = op["date_filed"]
            p["citing_court"] = court_id
            pool.append(p)
        if i % 25 == 0:
            print(f"  {court_id}: scanned {i}/{len(opinions)}, pool {len(pool)}",
                  flush=True)
    print(f"  {court_id}: raw pool {len(pool)}")
    verified = asyncio.run(verify_pool(pool))
    print(f"  {court_id}: verified {len(verified)}")
    return verified


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)

    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60
    tokenizer = AhocorasickTokenizer()

    courts_to_use = list(COURTS)
    all_rows: list[dict[str, Any]] = []
    raw_dump: dict[str, list[dict[str, Any]]] = {}

    for court_id in list(courts_to_use):
        verified = mine_court(client, court_id, tokenizer)
        raw_dump[court_id] = verified
        if len(verified) < 80:
            print(f"  WARN: {court_id} has only {len(verified)} verified rows; "
                  f"trying fallback", file=sys.stderr)
            # Try one fallback
            for fb in COURTS_FALLBACK:
                if fb in courts_to_use:
                    continue
                fb_verified = mine_court(client, fb, tokenizer)
                raw_dump[fb] = fb_verified
                if len(fb_verified) >= 80:
                    courts_to_use.append(fb)
                    courts_to_use.remove(court_id)
                    verified = fb_verified
                    court_id = fb
                    break

        if len(verified) < SAMPLE_PER_COURT:
            print(f"  WARN: {court_id} short — using all {len(verified)} rows",
                  file=sys.stderr)
            sample = verified
        else:
            sample = random.sample(verified, SAMPLE_PER_COURT)
        for i, item in enumerate(sample):
            all_rows.append({
                "id": f"{court_id}-{item['citing_cluster_id']}-{i}",
                "court": court_id,
                "proposition": item["parenthetical"],
                "gold_name": item["case_name"],
                "gold_cite": (
                    f"{item['case_name']}, {item['citation_text']} ({item['year']})"
                    if item["year"] else f"{item['case_name']}, {item['citation_text']}"
                ),
                "citing_cluster_id": item["citing_cluster_id"],
                "citing_year": (item.get("citing_date") or "")[:4],
                "cited_year": item.get("year") or "",
                "v_status": item.get("v_status", ""),
                "v_url": item.get("v_url", ""),
                "v_matched_name": item.get("v_matched_name", ""),
            })

    print(f"\nFinal dataset: {len(all_rows)} rows from {len(set(r['court'] for r in all_rows))} districts")
    RAW_POOL.write_text(json.dumps(raw_dump, indent=2, default=str), encoding="utf-8")

    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "court", "proposition", "gold_name", "gold_cite",
                        "citing_cluster_id", "citing_year", "cited_year",
                        "v_status", "v_url", "v_matched_name"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run on a single district as smoke test**

Add a `--limit` arg to limit OPINIONS_PER_COURT before running for real. Or simpler: edit `OPINIONS_PER_COURT = 30` temporarily, run, verify the script works end to end on DDC alone, then revert.

```bash
"venv/Scripts/python.exe" tests/benchmark_v1/build_dataset.py 2>&1 | tee benchmark_v1/_build_smoke.txt
```

Expected: produces `benchmark_v1/dataset.csv` with some rows (likely fewer than 200 since limit was reduced). No tracebacks.

- [ ] **Step 3: Restore OPINIONS_PER_COURT = 200 and run for real**

```bash
"venv/Scripts/python.exe" tests/benchmark_v1/build_dataset.py 2>&1 | tee benchmark_v1/_build_log.txt
```

Expected: ~30+ minutes runtime (5 districts × ~5 min each). Final output reports total rows and per-district counts.

- [ ] **Step 4: Verify dataset.csv**

```bash
"venv/Scripts/python.exe" -c "
import csv
rows = list(csv.DictReader(open('benchmark_v1/dataset.csv', encoding='utf-8')))
from collections import Counter
print(f'rows: {len(rows)}')
print(f'per-court: {Counter(r[\"court\"] for r in rows)}')
print(f'unique cluster: {len(set(r[\"citing_cluster_id\"] for r in rows))}')
"
```

Expected: 200 rows (or close — spec allows graceful degrade), 40 per court, mostly-unique cluster IDs.

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark_v1/build_dataset.py benchmark_v1/dataset.csv benchmark_v1/_raw_pool.json
git commit -m "benchmark v1: dataset — 200 fresh parens across 5 districts"
```

---

## Task 3: Model adapter with unit tests

**Files:**
- Create: `tests/benchmark_v1/model_adapter.py`
- Create: `tests/benchmark_v1/test_model_adapter.py`

**Why:** Need a unified `call_model(prompt, model_name) → dict` so `run_model.py` is symmetric across Sonnet/Opus/GPT-5.

- [ ] **Step 1: Write the failing tests**

Create `tests/benchmark_v1/test_model_adapter.py`:

```python
"""Unit tests for model_adapter (mocked subprocess + openai)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.benchmark_v1 import model_adapter as ma


def test_route_sonnet_uses_claude_cli():
    fake_proc = MagicMock(stdout=json.dumps({
        "result": "Smith v. Jones, 1 U.S. 1 (1900)",
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }), stderr="", returncode=0)
    with patch("tests.benchmark_v1.model_adapter.subprocess.run",
               return_value=fake_proc) as mock_run:
        result = ma.call_model("test prompt", "sonnet")
    assert mock_run.called
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "claude"
    assert "--model" in cmd and "sonnet" in cmd
    assert result["response"] == "Smith v. Jones, 1 U.S. 1 (1900)"
    assert result["cost_usd"] == 0.05
    assert result["input_tokens"] == 100


def test_route_opus_uses_claude_cli_with_opus():
    fake_proc = MagicMock(stdout=json.dumps({
        "result": "UNKNOWN", "total_cost_usd": 0.10, "usage": {}
    }), stderr="", returncode=0)
    with patch("tests.benchmark_v1.model_adapter.subprocess.run",
               return_value=fake_proc) as mock_run:
        ma.call_model("p", "opus")
    cmd = mock_run.call_args[0][0]
    assert "opus" in cmd


def test_route_gpt5_uses_openai():
    fake_completion = MagicMock()
    fake_completion.choices = [MagicMock(message=MagicMock(content="Doe v. Roe, 2 F.2d 3 (1950)"))]
    fake_completion.usage = MagicMock(prompt_tokens=80, completion_tokens=15)
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion
    with patch("tests.benchmark_v1.model_adapter._openai_client",
               return_value=fake_client):
        result = ma.call_model("p", "gpt-5")
    assert result["response"] == "Doe v. Roe, 2 F.2d 3 (1950)"
    assert result["input_tokens"] == 80
    assert result["output_tokens"] == 15


def test_unknown_model_raises():
    with pytest.raises(ValueError, match="unknown model"):
        ma.call_model("p", "bogus-model")


def test_claude_timeout_returns_none_response():
    import subprocess
    with patch("tests.benchmark_v1.model_adapter.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60)):
        result = ma.call_model("p", "sonnet", timeout_s=60)
    assert result["response"] == ""
    assert result["stderr"] == "TIMEOUT"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
"venv/Scripts/python.exe" -m pytest tests/benchmark_v1/test_model_adapter.py -v
```

Expected: ImportError or ModuleNotFoundError (model_adapter doesn't exist yet).

- [ ] **Step 3: Write the adapter**

Create `tests/benchmark_v1/model_adapter.py`:

```python
"""Unified call interface for Sonnet / Opus / GPT-5.

Claude models use `claude -p` subprocess (matches Pilot A); GPT-5 uses
the OpenAI Python SDK. Both return the same dict shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

# Bypass repo CLAUDE.md by running Claude CLI from a hermetic dir
# (Pilot A finding: project context bleeds in and the model refuses).
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="benchmark_v1_"))

PROMPT_TEMPLATE = """You are a legal research assistant. I will give you a legal proposition.
Name a US federal case that supports it.

Respond ONLY with the case name and citation, in this format:
<Case Name>, <Volume> <Reporter> <Page> (<Court> <Year>)

Do not include any explanation, parenthetical, or commentary. If you do
not know a supporting case, respond with "UNKNOWN".

Proposition: {proposition}"""


_OPENAI_CLIENT = None


def _openai_client():
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is None:
        from openai import OpenAI
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        _OPENAI_CLIENT = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _OPENAI_CLIENT


def _call_claude(prompt: str, model: str, timeout_s: int) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, cwd=str(_HERMETIC_DIR))
    except subprocess.TimeoutExpired:
        return {"response": "", "elapsed_s": timeout_s, "cost_usd": 0,
                "input_tokens": 0, "output_tokens": 0, "stderr": "TIMEOUT"}
    elapsed = time.time() - start
    try:
        payload = json.loads((proc.stdout or "").strip())
        response = (payload.get("result") or "").strip()
        cost = payload.get("total_cost_usd", 0)
        usage = payload.get("usage", {}) or {}
    except json.JSONDecodeError:
        response = (proc.stdout or "").strip()
        cost = 0
        usage = {}
    return {
        "response": response,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": cost,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "stderr": (proc.stderr or "")[:500] if proc.returncode != 0 else "",
    }


def _call_gpt5(prompt: str, timeout_s: int) -> dict:
    client = _openai_client()
    start = time.time()
    try:
        completion = client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=timeout_s,
        )
    except Exception as exc:
        return {"response": "", "elapsed_s": round(time.time() - start, 1),
                "cost_usd": 0, "input_tokens": 0, "output_tokens": 0,
                "stderr": f"OPENAI_ERROR: {exc}"[:500]}
    elapsed = time.time() - start
    response = (completion.choices[0].message.content or "").strip()
    usage = completion.usage
    return {
        "response": response,
        "elapsed_s": round(elapsed, 1),
        # OpenAI SDK doesn't return cost; computed by caller if needed.
        "cost_usd": 0,
        "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
        "stderr": "",
    }


def call_model(prompt: str, model_name: str, timeout_s: int = 60) -> dict:
    """Unified interface. Returns dict with response, elapsed_s, cost_usd,
    input_tokens, output_tokens, stderr."""
    if model_name in {"sonnet", "opus"}:
        return _call_claude(prompt, model_name, timeout_s)
    if model_name == "gpt-5":
        return _call_gpt5(prompt, timeout_s)
    raise ValueError(f"unknown model: {model_name!r}")
```

- [ ] **Step 4: Run tests, verify pass**

```bash
"venv/Scripts/python.exe" -m pytest tests/benchmark_v1/test_model_adapter.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Smoke-test the adapter against real APIs (one call each)**

```bash
"venv/Scripts/python.exe" -c "
from tests.benchmark_v1.model_adapter import call_model, PROMPT_TEMPLATE
prop = 'A grand jury subpoena requires a judicial finding of probable cause.'
for model in ['sonnet', 'opus', 'gpt-5']:
    print(f'=== {model} ===')
    r = call_model(PROMPT_TEMPLATE.format(proposition=prop), model)
    print(f'  response: {r[\"response\"][:120]}')
    print(f'  elapsed: {r[\"elapsed_s\"]}s | tokens in/out: {r[\"input_tokens\"]}/{r[\"output_tokens\"]}')
    if r['stderr']:
        print(f'  stderr: {r[\"stderr\"][:200]}')
"
```

Expected: each model returns a citation or "UNKNOWN" or refuses, within ~30s. No exceptions. (Note: this proposition is fake, so real responses may not exist — the point is just that the adapter routes correctly to each provider.)

- [ ] **Step 6: Commit**

```bash
git add tests/benchmark_v1/model_adapter.py tests/benchmark_v1/test_model_adapter.py
git commit -m "benchmark v1: model adapter (Claude CLI + OpenAI SDK)"
```

---

## Task 4: run_model.py — single-model runner

**Files:**
- Create: `tests/benchmark_v1/run_model.py`

- [ ] **Step 1: Write run_model.py**

```python
"""Run one model on the benchmark dataset -> outputs_{model}.csv.

Idempotent: if outputs_{model}.csv exists with N rows, resumes from row N+1.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.benchmark_v1.model_adapter import call_model, PROMPT_TEMPLATE  # noqa: E402

DATASET = PROJECT_ROOT / "benchmark_v1" / "dataset.csv"
TIMEOUT_S = 60


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=["sonnet", "opus", "gpt-5"])
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N rows (smoke test)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output CSV; defaults to benchmark_v1/outputs_{model}.csv")
    args = ap.parse_args()

    out = args.out or PROJECT_ROOT / "benchmark_v1" / f"outputs_{args.model.replace('-', '')}.csv"
    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]

    # Resume support
    existing_ids = set()
    if out.exists():
        existing_ids = {r["id"] for r in csv.DictReader(out.open(encoding="utf-8"))}
        print(f"Resuming: {len(existing_ids)} rows already done")

    fieldnames = [
        "id", "court", "proposition", "gold_name", "gold_cite",
        "model", "model_response", "elapsed_s", "cost_usd",
        "input_tokens", "output_tokens", "stderr",
    ]
    write_header = not out.exists()
    with out.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
        total_cost = 0.0
        for i, row in enumerate(rows, 1):
            if row["id"] in existing_ids:
                continue
            print(f"  [{i}/{len(rows)}] {args.model}/{row['id']}...",
                  end="", flush=True)
            prompt = PROMPT_TEMPLATE.format(proposition=row["proposition"])
            r = call_model(prompt, args.model, timeout_s=TIMEOUT_S)
            total_cost += r.get("cost_usd", 0) or 0
            preview = r["response"][:60].replace("\n", " ")
            print(f" {r['elapsed_s']}s | {preview}", flush=True)
            writer.writerow({
                "id": row["id"], "court": row["court"],
                "proposition": row["proposition"],
                "gold_name": row["gold_name"], "gold_cite": row["gold_cite"],
                "model": args.model,
                **r,
            })
            f.flush()
    print(f"\nWrote {out}; total notional cost ${total_cost:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test on 3 rows of one model**

```bash
"venv/Scripts/python.exe" tests/benchmark_v1/run_model.py --model sonnet --limit 3 --out benchmark_v1/_smoke_sonnet.csv
```

Expected: 3 rows, no tracebacks.

- [ ] **Step 3: Run all 3 models on full dataset**

These can run in parallel in three separate shells if you want. Each takes ~30 min for 200 rows.

Sequential is fine if quota matters:
```bash
"venv/Scripts/python.exe" tests/benchmark_v1/run_model.py --model sonnet 2>&1 | tee benchmark_v1/_run_sonnet_log.txt
"venv/Scripts/python.exe" tests/benchmark_v1/run_model.py --model opus   2>&1 | tee benchmark_v1/_run_opus_log.txt
"venv/Scripts/python.exe" tests/benchmark_v1/run_model.py --model gpt-5  2>&1 | tee benchmark_v1/_run_gpt5_log.txt
```

Expected: each produces `benchmark_v1/outputs_{sonnet,opus,gpt5}.csv` with 200 rows.

- [ ] **Step 4: Verify all three output files**

```bash
"venv/Scripts/python.exe" -c "
import csv
for m in ['sonnet', 'opus', 'gpt5']:
    rows = list(csv.DictReader(open(f'benchmark_v1/outputs_{m}.csv', encoding='utf-8')))
    unk = sum(1 for r in rows if r['model_response'].strip().upper().startswith('UNKNOWN'))
    print(f'{m}: {len(rows)} rows, {unk} UNKNOWN')
"
```

Expected: 200 rows each. UNKNOWN counts will vary per model.

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark_v1/run_model.py benchmark_v1/outputs_sonnet.csv benchmark_v1/outputs_opus.csv benchmark_v1/outputs_gpt5.csv
git commit -m "benchmark v1: model outputs — Sonnet 4.6 / Opus 4.7 / GPT-5"
```

---

## Task 5: score.py — three-axis scoring

**Files:**
- Create: `tests/benchmark_v1/score.py`

**Why:** Pilot A's score.py works on one CSV at a time. We need a version that joins three model outputs and produces one results.csv with (model, example) rows.

- [ ] **Step 1: Write score.py**

```python
"""Score outputs_*.csv on three axes -> results.csv.

Real (citation-verifier existence) + Name match (CaseNameMatcher) +
Supports (Opus 4.7 substance assessor on real cases). Joined across
all three models.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

import eyecite
from eyecite.models import FullCaseCitation
from eyecite.tokenizers import AhocorasickTokenizer

import importlib.util

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load Pilot A's score.py under a distinct module name to avoid colliding
# with this file (also called score.py).
_pilot_path = PROJECT_ROOT / "tests" / "pilot_a" / "score.py"
_spec = importlib.util.spec_from_file_location("pilot_a_score", _pilot_path)
_pilot_score = importlib.util.module_from_spec(_spec)
sys.modules["pilot_a_score"] = _pilot_score
_spec.loader.exec_module(_pilot_score)
extract_citation = _pilot_score.extract_citation
fetch_opinion_text = _pilot_score.fetch_opinion_text
call_assessor = _pilot_score.call_assessor
_names_score = _pilot_score._names_score

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

OUT = PROJECT_ROOT / "benchmark_v1" / "results.csv"

ASSESSOR_MODEL = "opus"  # spec calls for Opus 4.7
NAME_MATCH_THRESHOLD = 0.65


async def verify_extracted(rows: list[dict]) -> list[dict]:
    verifier = CitationVerifier()
    citation_strs, parsed, indices = [], [], []
    for i, row in enumerate(rows):
        ext = row.get("_extract") or {}
        if ext.get("citation_text") and ext.get("fcc"):
            indices.append(i)
            citation_strs.append(ext["citation_text"])
            parsed.append(parsed_citation_from_eyecite(ext["fcc"]))
    if not citation_strs:
        return rows
    results = await verifier.verify_batch(citation_strs, parsed_citations=parsed,
                                          quick_only=False)
    for idx, res in zip(indices, results):
        rows[idx]["_verify"] = res
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-substance", action="store_true",
                    help="skip Opus assessor (axes 1+2 only)")
    args = ap.parse_args()

    # Load all 3 model outputs
    bench = PROJECT_ROOT / "benchmark_v1"
    all_rows: list[dict] = []
    for m_file in ["outputs_sonnet.csv", "outputs_opus.csv", "outputs_gpt5.csv"]:
        p = bench / m_file
        if not p.exists():
            print(f"WARN: {p} not found, skipping", file=sys.stderr)
            continue
        for r in csv.DictReader(p.open(encoding="utf-8")):
            all_rows.append(r)
    print(f"Loaded {len(all_rows)} (model, example) cells")

    # Step A: extract citation from each model response
    for row in all_rows:
        row["_extract"] = extract_citation(row.get("model_response", ""))

    # Step B: batch-verify
    print("Verifying extracted citations...")
    all_rows = asyncio.run(verify_extracted(all_rows))

    # Resume support: load existing results, skip already-scored cells
    existing_keys: set[tuple[str, str]] = set()
    if OUT.exists():
        for r in csv.DictReader(OUT.open(encoding="utf-8")):
            existing_keys.add((r["model"], r["id"]))
        print(f"Resuming: {len(existing_keys)} cells already scored")

    fieldnames = [
        "id", "court", "model", "proposition", "gold_name", "gold_cite",
        "model_response", "extracted_case_name", "extracted_citation",
        "real", "real_status", "name_match", "matched_cl_name",
        "matched_cluster_id", "right_case",
        "supports", "support_rationale", "support_cost_usd",
    ]
    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60

    write_header = not OUT.exists()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()

        for i, row in enumerate(all_rows, 1):
            key = (row["model"], row["id"])
            if key in existing_keys:
                continue
            ext = row.get("_extract") or {}
            ver = row.get("_verify")

            real = False
            real_status = ""
            cl_name = ""
            cluster_id = ""
            if ver is not None:
                real_status = ver.status.value if ver.status else ""
                real = ver.status in (VerificationStatus.VERIFIED,
                                       VerificationStatus.LIKELY_REAL)
                cl_name = ver.matched_case_name or ""
                cluster_id = ver.matched_cluster_id or ""

            extracted_case = ext.get("case_name", "")
            ext_cite = (ext.get("citation_text") or "").strip()
            name_match = (real and _names_score(extracted_case, cl_name) >= NAME_MATCH_THRESHOLD)

            gold_cite = (row.get("gold_cite") or "").strip()
            gold_name = (row.get("gold_name") or "").strip()
            right_case = bool(ext_cite and ext_cite in gold_cite) and (
                _names_score(extracted_case, gold_name) >= 0.6
                if (extracted_case and gold_name) else False
            )

            support = None
            support_rationale = ""
            support_cost = 0.0
            if not args.skip_substance and real:
                opinion_text = fetch_opinion_text(client, cluster_id)
                if opinion_text:
                    case_label = f"{cl_name or extracted_case}, {ext_cite}"
                    print(f"  [{i}/{len(all_rows)}] {row['model']} | {case_label[:60]}")
                    a = call_assessor(row["proposition"], case_label, opinion_text,
                                       model=ASSESSOR_MODEL)
                    support = a["assessment"]
                    support_rationale = a["rationale"]
                    support_cost = a["cost_usd"]
                else:
                    support_rationale = "no opinion text"
            elif row.get("model_response", "").strip().upper().startswith("UNKNOWN"):
                support_rationale = "model returned UNKNOWN"

            writer.writerow({
                "id": row["id"], "court": row["court"], "model": row["model"],
                "proposition": row["proposition"],
                "gold_name": gold_name, "gold_cite": gold_cite,
                "model_response": row.get("model_response", ""),
                "extracted_case_name": extracted_case,
                "extracted_citation": ext_cite,
                "real": "Y" if real else "N",
                "real_status": real_status,
                "name_match": "Y" if name_match else "N",
                "matched_cl_name": cl_name,
                "matched_cluster_id": cluster_id,
                "right_case": "Y" if right_case else "N",
                "supports": support or "",
                "support_rationale": support_rationale,
                "support_cost_usd": support_cost,
            })
            f.flush()

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Patch Pilot A's call_assessor to accept a `model=` kwarg**

Verified: `tests/pilot_a/score.py:193` is `def call_assessor(proposition, case_name_citation, opinion_text)` — no model param. We need to add one defaulting to "sonnet" so v1 can pass "opus" without breaking pilot_a's existing behavior.

Edit `tests/pilot_a/score.py`:

```python
# Line 193 — change signature
def call_assessor(proposition: str, case_name_citation: str, opinion_text: str,
                  model: str = ASSESSOR_MODEL) -> dict:
```

```python
# Line 202 (inside cmd list) — change "--model", ASSESSOR_MODEL to use param
        "--model", model,
```

Verify with:
```bash
"venv/Scripts/python.exe" -m pytest tests/test_verifier.py -q 2>&1 | tail -3
```
Expected: existing tests still pass (pilot_a's score.py isn't covered by tests but the import shouldn't break anything that imports score.py).

Spot-check the new signature works:
```bash
"venv/Scripts/python.exe" -c "
from importlib.util import spec_from_file_location, module_from_spec
import inspect
spec = spec_from_file_location('pilot_score', 'tests/pilot_a/score.py')
m = module_from_spec(spec); spec.loader.exec_module(m)
print(inspect.signature(m.call_assessor))
"
```
Expected: `(proposition: str, case_name_citation: str, opinion_text: str, model: str = 'sonnet') -> dict`

- [ ] **Step 3: Smoke-test score.py on a small slice**

Temporarily edit `outputs_sonnet.csv` etc. to a 3-row copy, or pass a flag to limit. Easiest:

```bash
"venv/Scripts/python.exe" -c "
import csv, shutil
for m in ['sonnet','opus','gpt5']:
    src = f'benchmark_v1/outputs_{m}.csv'
    rows = list(csv.DictReader(open(src, encoding='utf-8')))[:3]
    with open(f'benchmark_v1/_smoke_outputs_{m}.csv','w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f, fieldnames=rows[0].keys(), quoting=csv.QUOTE_ALL); w.writeheader(); w.writerows(rows)
"
```

Then patch score.py temporarily (or hack with a `--limit` arg) and run on the smoke files. Verify output is sensible.

- [ ] **Step 4: Run score on full dataset**

```bash
"venv/Scripts/python.exe" tests/benchmark_v1/score.py 2>&1 | tee benchmark_v1/_score_log.txt
```

Expected: ~30+ minutes. Produces `benchmark_v1/results.csv` with 600 rows (200 × 3 models). Mid-run interruption is OK — script resumes.

- [ ] **Step 5: Verify results.csv**

```bash
"venv/Scripts/python.exe" -c "
import csv
from collections import Counter
rows = list(csv.DictReader(open('benchmark_v1/results.csv', encoding='utf-8')))
print(f'rows: {len(rows)}')
for m in ['sonnet','opus','gpt-5']:
    rs = [r for r in rows if r['model']==m]
    print(f'{m}: real={sum(1 for r in rs if r[\"real\"]==\"Y\")} '
          f'name={sum(1 for r in rs if r[\"name_match\"]==\"Y\")} '
          f'green={sum(1 for r in rs if r[\"supports\"]==\"Green\")} '
          f'unknown={sum(1 for r in rs if r[\"model_response\"].strip().upper().startswith(\"UNKNOWN\"))}')
"
```

Expected: 600 rows, 200 per model, varied real/name/green counts.

- [ ] **Step 6: Commit**

```bash
git add tests/benchmark_v1/score.py tests/pilot_a/score.py benchmark_v1/results.csv
git commit -m "benchmark v1: scored — 3 axes × 3 models × 200 examples"
```

---

## Task 6: scorecard.py — aggregates and bootstrap CIs

**Files:**
- Create: `tests/benchmark_v1/scorecard.py`
- Create: `tests/benchmark_v1/test_scorecard.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for scorecard bootstrap math."""
from __future__ import annotations

from tests.benchmark_v1 import scorecard as sc


def test_pct_returns_zero_for_empty():
    assert sc.green_rate([]) == 0.0


def test_pct_counts_green_only():
    rs = [{"supports": "Green"}, {"supports": "Yellow"}, {"supports": ""}, {"supports": "Green"}]
    assert sc.green_rate(rs) == 0.5


def test_hallucination_excludes_unknown():
    rs = [
        {"real": "Y", "name_match": "Y", "model_response": "Foo v. Bar"},
        {"real": "N", "name_match": "N", "model_response": "Made-up case"},
        {"real": "N", "name_match": "N", "model_response": "UNKNOWN"},  # excluded
    ]
    # 1 of 2 answered = 50%
    assert sc.hallucination_rate(rs) == 0.5


def test_bootstrap_diff_returns_ci_tuple():
    a = [{"supports": "Green"}] * 100
    b = [{"supports": "Red"}] * 100
    lo, hi = sc.bootstrap_diff(a, b, sc.green_rate, n=200, seed=42)
    # Diff should be ~ +1.0 with tight CI
    assert lo > 0.5 and hi < 1.5


def test_bootstrap_diff_zero_overlap_when_identical():
    a = [{"supports": "Green"}] * 50 + [{"supports": "Yellow"}] * 50
    b = [{"supports": "Green"}] * 50 + [{"supports": "Yellow"}] * 50
    lo, hi = sc.bootstrap_diff(a, b, sc.green_rate, n=500, seed=42)
    assert lo < 0 < hi  # CI straddles 0
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
"venv/Scripts/python.exe" -m pytest tests/benchmark_v1/test_scorecard.py -v
```

Expected: ImportError.

- [ ] **Step 3: Write scorecard.py**

```python
"""Aggregate results.csv into a per-model leaderboard with bootstrap CIs."""
from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "benchmark_v1" / "results.csv"
OUT = PROJECT_ROOT / "benchmark_v1" / "scorecards.md"

MODELS = ["sonnet", "opus", "gpt-5"]


def green_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("supports") == "Green") / len(rows)


def hallucination_rate(rows: list[dict]) -> float:
    """% of answered (non-UNKNOWN) responses that are not real or wrong-name."""
    answered = [r for r in rows if not r.get("model_response", "").strip().upper().startswith("UNKNOWN")]
    if not answered:
        return 0.0
    bad = sum(1 for r in answered if r.get("real") != "Y" or r.get("name_match") != "Y")
    return bad / len(answered)


def unknown_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("model_response", "").strip().upper().startswith("UNKNOWN")) / len(rows)


def right_case_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("right_case") == "Y") / len(rows)


def bootstrap_diff(rows_a: list[dict], rows_b: list[dict],
                   metric: Callable[[list[dict]], float],
                   n: int = 5000, seed: int = 42) -> tuple[float, float]:
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sa = [rng.choice(rows_a) for _ in range(len(rows_a))]
        sb = [rng.choice(rows_b) for _ in range(len(rows_b))]
        diffs.append(metric(sa) - metric(sb))
    diffs.sort()
    return (diffs[int(0.025 * n)], diffs[int(0.975 * n)])


def main() -> None:
    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
    by_model = {m: [r for r in rows if r["model"] == m] for m in MODELS}

    lines: list[str] = []
    lines.append("# Case Law Retrieval Benchmark v1 — Scorecard")
    lines.append("")
    lines.append(f"**N per model:** {min(len(rs) for rs in by_model.values())}  ")
    lines.append(f"**Models:** Sonnet 4.6, Opus 4.7, GPT-5  ")
    lines.append(f"**Eval mode:** closed-book, temperature 0  ")
    lines.append(f"**Substance assessor:** Opus 4.7")
    lines.append("")
    lines.append("## Per-model headlines")
    lines.append("")
    lines.append("| Model | % Green | Hallucination rate | UNKNOWN rate | Right-case rate |")
    lines.append("|---|---:|---:|---:|---:|")
    for m in MODELS:
        rs = by_model[m]
        lines.append(
            f"| {m} | {green_rate(rs):.1%} | {hallucination_rate(rs):.1%} "
            f"| {unknown_rate(rs):.1%} | {right_case_rate(rs):.1%} |"
        )
    lines.append("")
    lines.append("## Pairwise diffs (Green rate, 95% CI via 5000-sample bootstrap)")
    lines.append("")
    lines.append("| Pair | Green diff | 95% CI |")
    lines.append("|---|---:|---|")
    pairs = [("opus", "sonnet"), ("opus", "gpt-5"), ("sonnet", "gpt-5")]
    for a, b in pairs:
        diff = green_rate(by_model[a]) - green_rate(by_model[b])
        lo, hi = bootstrap_diff(by_model[a], by_model[b], green_rate)
        excl_zero = "**" if (lo > 0 or hi < 0) else ""
        lines.append(
            f"| {a} − {b} | {excl_zero}{diff*100:+.1f}pp{excl_zero} "
            f"| [{lo*100:+.1f}, {hi*100:+.1f}] |"
        )
    lines.append("")
    lines.append("Bold pairs have CI excluding zero (statistically distinguishable).")
    lines.append("")
    lines.append("## Per-district breakdown (Green rate)")
    lines.append("")
    courts = sorted({r["court"] for r in rows})
    header = "| Model | " + " | ".join(courts) + " |"
    lines.append(header)
    lines.append("|---|" + "|".join(["---:"] * len(courts)) + "|")
    for m in MODELS:
        cells = []
        for c in courts:
            sub = [r for r in by_model[m] if r["court"] == c]
            cells.append(f"{green_rate(sub):.1%}")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run unit tests, verify pass**

```bash
"venv/Scripts/python.exe" -m pytest tests/benchmark_v1/test_scorecard.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run scorecard on real results**

```bash
"venv/Scripts/python.exe" tests/benchmark_v1/scorecard.py
```

Expected: prints the markdown report. Writes `benchmark_v1/scorecards.md`. Inspect the output:
- Per-model headlines look reasonable (no NaN, no all-zero columns)
- At least one pairwise diff has CI excluding 0 (success criterion); if not, document in README

- [ ] **Step 6: Commit**

```bash
git add tests/benchmark_v1/scorecard.py tests/benchmark_v1/test_scorecard.py benchmark_v1/scorecards.md
git commit -m "benchmark v1: scorecard with bootstrap CIs"
```

---

## Task 7: README and final integration

**Files:**
- Create: `benchmark_v1/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Case Law Retrieval Benchmark v1

A 3-model leaderboard on 200 freshly-mined federal district-court parentheticals,
scored on Real / Name-match / Supports axes.

**Spec:** [../docs/plans/2026-04-30-benchmark-v1-design.md](../docs/plans/2026-04-30-benchmark-v1-design.md)

## What's here

| File | Description |
|---|---|
| `dataset.csv` | 200 examples (40 each from DDC, CAND, TXSD, ILND, NYSD/fallback) |
| `outputs_sonnet.csv` | Claude Sonnet 4.6 closed-book responses |
| `outputs_opus.csv` | Claude Opus 4.7 closed-book responses |
| `outputs_gpt5.csv` | OpenAI GPT-5 closed-book responses |
| `results.csv` | Per-(model, example) scoring on 3 axes |
| `scorecards.md` | Headline numbers + bootstrap CIs |

## How to reproduce

Requires:
- Python 3.10+, repo's `venv/` with `requests`, `eyecite`, `openai`, `python-dotenv`, etc.
- `COURTLISTENER_API_TOKEN` and `OPENAI_API_KEY` in `.env`
- Claude Code CLI with active subscription (for `claude -p`)

```bash
# Build dataset (~30 min)
venv/Scripts/python.exe tests/benchmark_v1/build_dataset.py

# Run each model (~30 min each, can run in parallel shells)
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model sonnet
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model opus
venv/Scripts/python.exe tests/benchmark_v1/run_model.py --model gpt-5

# Score (~30 min)
venv/Scripts/python.exe tests/benchmark_v1/score.py

# Generate scorecard (instant)
venv/Scripts/python.exe tests/benchmark_v1/scorecard.py
```

All scripts are idempotent — interrupted runs resume.

## Scope

In v1: closed-book only, federal districts only, 3 models, 3 axes.

Deferred to v1.1: forkable kit (SCHEMA / MINING_PLAYBOOK / etc.), web-search and
tool-augmented modes, currency and jurisdictional-appropriateness axes.

Deferred to v2: circuits + SCOTUS, state-law forks.

See spec for full design rationale and Pilot A predecessor work.
```

- [ ] **Step 2: Verify all success criteria from spec**

Walk through each item in the spec's "Success criteria" section:

```bash
"venv/Scripts/python.exe" -c "
import csv
ds = list(csv.DictReader(open('benchmark_v1/dataset.csv', encoding='utf-8')))
print(f'[1] dataset.csv rows: {len(ds)} (target 200, allowed <200)')

for m in ['sonnet','opus','gpt5']:
    rows = list(csv.DictReader(open(f'benchmark_v1/outputs_{m}.csv', encoding='utf-8')))
    print(f'[2] outputs_{m}.csv rows: {len(rows)} (must equal {len(ds)})')

results = list(csv.DictReader(open('benchmark_v1/results.csv', encoding='utf-8')))
print(f'[3] results.csv cells: {len(results)} (must equal 3 * {len(ds)} = {3*len(ds)})')

scorecard = open('benchmark_v1/scorecards.md', encoding='utf-8').read()
print(f'[4] scorecards.md present: {len(scorecard)} chars')
print(f'[5] CI-excludes-0 pair present: {\"**\" in scorecard}')
"
```

If [5] is False, edit the README to add a note: "current frontier models are statistically indistinguishable on this dataset at N=200."

- [ ] **Step 3: Commit and push**

```bash
git add benchmark_v1/README.md
git commit -m "benchmark v1: README — reproduction instructions and scope"
git push
```

---

## Notes section (for engineer reference)

- Pilot A's `tests/pilot_a/score.py` is reused directly — don't refactor in v1.
- Opinion-text cache in `scratch/pilot_a/_dcd_opinion_cache/` is checked first (saves re-fetching DDC opinions).
- All Claude calls run from a hermetic temp dir to avoid project CLAUDE.md leakage (Pilot A finding).
- CL search must include `stat_Published=on&stat_Unknown=on` to access PACER-flagged district opinions (Pilot A finding).
- `eyecite` parenthetical extraction breaks on multi-newline plain_text; `_normalize_text` collapses whitespace first (Pilot A finding).
- If GPT-5 cutoff is later than 2025-12-31, push DATE_FROM forward in build_dataset.py.

---

## Self-review notes

- All 5 success criteria mapped to verification steps in Task 7.
- Each script is independently runnable + idempotent (resume on rerun).
- Pilot A code reused via sys.path injection where it makes sense (keeps DRY); refactored only where the 3-model context required it (score.py joins).
- Unit tests on the two pieces with non-obvious logic: model adapter routing, bootstrap CI math.
- Integration verification (run + check) for I/O-heavy scripts (build, run_model, score, scorecard).
