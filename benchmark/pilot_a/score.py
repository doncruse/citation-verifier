"""Score Pilot A model outputs on three axes.

For each row in model_outputs.csv:
    Axis 1 (Real)        -- citation-verifier existence check on the citation
                            extracted from the model's response.
    Axis 2 (Name match)  -- citation-verifier name matcher between the model's
                            named case and CourtListener's resolved name.
    Axis 3 (Supports)    -- single Claude call: given the proposition + the
                            model's named case + the downloaded opinion text,
                            score Green / Yellow / Red.

Writes benchmark/pilot_a/results.csv. We use Sonnet for the substance assessor
to bound pilot cost; the parent benchmark spec calls for Opus, but the
contamination signal we're chasing should be robust to assessor choice.

This is intentionally simpler than /verify-brief Phase 2 (no triage, no
grep, no Haiku safety net) per the Pilot A plan.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Bypass repo CLAUDE.md so the assessor isn't biased by project context.
_HERMETIC_DIR = Path(tempfile.mkdtemp(prefix="pilot_a_score_"))

import eyecite
from eyecite.models import FullCaseCitation
from eyecite.tokenizers import AhocorasickTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

from citation_verifier.client import CourtListenerClient  # noqa: E402
from citation_verifier.models import VerificationStatus  # noqa: E402
from citation_verifier.name_matcher import CaseNameMatcher  # noqa: E402
from citation_verifier.parser import parsed_citation_from_eyecite  # noqa: E402
from citation_verifier.verifier import CitationVerifier  # noqa: E402

MODEL_OUTPUTS = PROJECT_ROOT / "benchmark" / "pilot_a" / "model_outputs.csv"
RESULTS = PROJECT_ROOT / "benchmark" / "pilot_a" / "results.csv"
OPINIONS_CACHE = PROJECT_ROOT / "benchmark" / "pilot_a" / "cited_opinion_cache"

ASSESSOR_MODEL = "sonnet"
ASSESSOR_TIMEOUT = 90
MAX_OPINION_CHARS = 20_000

ASSESSMENT_PROMPT = """You are a legal-research auditor. You will be given:
  1. A legal proposition (the claim being made).
  2. A case name + citation that someone offered in support.
  3. An excerpt from the cited case's opinion text.

Your job: decide whether the cited case substantively supports the proposition.

Score:
  - Green: case directly and accurately supports the proposition.
  - Yellow: partially relevant; support is weaker than represented, or the
    proposition slightly overstates what the case held.
  - Red: case does not support the proposition; case addresses a completely
    different topic; or no on-point passage exists in the excerpt.

Respond with ONLY a single-line JSON object. No prose, no markdown.
Format: {{"assessment": "Green|Yellow|Red", "rationale": "one short sentence"}}

PROPOSITION:
{proposition}

CITED CASE:
{case_name_citation}

OPINION TEXT (excerpt, may be truncated):
{opinion_text}
"""


def extract_citation(model_response: str) -> dict[str, Any]:
    """Pull the first FullCaseCitation from the model's response.

    Returns a dict with raw_text, case_name, citation_text, year, fcc -- or
    {} if nothing extractable.
    """
    if not model_response:
        return {}
    if model_response.strip().upper().startswith("UNKNOWN"):
        return {"unknown": True}

    tokenizer = AhocorasickTokenizer()
    try:
        cites = eyecite.get_citations(model_response, tokenizer=tokenizer)
    except Exception:
        cites = []
    fc = next((c for c in cites if isinstance(c, FullCaseCitation)), None)
    if fc is None:
        return {"raw_text": model_response[:200]}

    meta = fc.metadata
    plaintiff = (meta.plaintiff or "").strip()
    defendant = (meta.defendant or "").strip()
    case_name = ""
    if plaintiff and defendant:
        case_name = f"{plaintiff} v. {defendant}"
    elif defendant:
        case_name = defendant

    return {
        "raw_text": model_response[:200],
        "case_name": case_name,
        "citation_text": fc.matched_text(),
        "year": meta.year or "",
        "court": meta.court or "",
        "fcc": fc,
    }


async def verify_extracted(rows_with_extract: list[dict]) -> list[dict]:
    """Batch-verify all rows that have an extracted citation."""
    verifier = CitationVerifier()
    citation_strs = []
    parsed = []
    indices = []
    for i, row in enumerate(rows_with_extract):
        ext = row.get("_extract") or {}
        if ext.get("citation_text") and ext.get("fcc"):
            indices.append(i)
            citation_strs.append(ext["citation_text"])
            parsed.append(parsed_citation_from_eyecite(ext["fcc"]))
    if not citation_strs:
        return rows_with_extract

    results = await verifier.verify_batch(
        citation_strs, parsed_citations=parsed, quick_only=False
    )
    for idx, res in zip(indices, results):
        rows_with_extract[idx]["_verify"] = res
    return rows_with_extract


def fetch_opinion_text(client: CourtListenerClient, cluster_id: int | None) -> str:
    """Pull plain text for a cluster, with a tiny on-disk cache."""
    if not cluster_id:
        return ""
    OPINIONS_CACHE.mkdir(parents=True, exist_ok=True)
    cache = OPINIONS_CACHE / f"{cluster_id}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")[:MAX_OPINION_CHARS]
    try:
        cluster = client._request_with_retry(
            "GET", f"{client.BASE_URL}/clusters/{cluster_id}/"
        ).json()
    except Exception as exc:
        print(f"  cluster fetch failed for {cluster_id}: {exc}", file=sys.stderr)
        return ""
    sub_ops = cluster.get("sub_opinions") or []
    if not sub_ops:
        return ""
    # Try each sub_opinion until we find one with text. Fall back through
    # plain_text -> html -> html_with_citations -> xml_harvard.
    text = ""
    for sub in sub_ops:
        try:
            op = client._request_with_retry("GET", sub).json()
        except Exception as exc:
            print(f"  opinion fetch failed for {cluster_id}: {exc}", file=sys.stderr)
            continue
        text = op.get("plain_text") or ""
        if text:
            break
        for field in ("html", "html_columbia", "html_with_citations",
                      "html_lawbox", "xml_harvard"):
            raw = op.get(field) or ""
            if raw:
                stripped = re.sub(r"<[^>]+>", " ", raw)
                stripped = re.sub(r"&[a-z#0-9]+;", " ", stripped)
                stripped = re.sub(r"\s+", " ", stripped).strip()
                if stripped:
                    text = stripped
                    break
        if text:
            break
    cache.write_text(text, encoding="utf-8")
    return text[:MAX_OPINION_CHARS]


def call_assessor(proposition: str, case_name_citation: str, opinion_text: str,
                  model: str = ASSESSOR_MODEL) -> dict:
    prompt = ASSESSMENT_PROMPT.format(
        proposition=proposition,
        case_name_citation=case_name_citation,
        opinion_text=opinion_text or "(opinion text unavailable)",
    )
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", model,
    ]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=ASSESSOR_TIMEOUT, cwd=str(_HERMETIC_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"assessment": None, "rationale": "TIMEOUT", "elapsed_s": ASSESSOR_TIMEOUT, "cost_usd": 0}
    elapsed = time.time() - start
    try:
        payload = json.loads(proc.stdout.strip())
        response = (payload.get("result") or "").strip()
        cost = payload.get("total_cost_usd", 0)
    except json.JSONDecodeError:
        response = proc.stdout.strip()
        cost = 0

    assessment = None
    rationale = ""
    try:
        match = re.search(r"\{[^{}]*assessment[^{}]*\}", response)
        if match:
            j = json.loads(match.group(0))
            assessment = j.get("assessment")
            rationale = j.get("rationale", "")
    except json.JSONDecodeError:
        pass
    if not assessment:
        for color in ("Red", "Yellow", "Green"):
            if color in response:
                assessment = color
                rationale = response[:200]
                break

    return {
        "assessment": assessment,
        "rationale": rationale,
        "elapsed_s": round(elapsed, 1),
        "cost_usd": cost,
    }


_NAME_MATCHER = CaseNameMatcher()


def _names_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return _NAME_MATCHER.calculate_similarity(a, b)


def name_matches_check(model_name: str, cl_name: str) -> bool:
    return _names_score(model_name, cl_name) >= 0.65


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, default=MODEL_OUTPUTS)
    ap.add_argument("--out", type=Path, default=RESULTS)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-substance", action="store_true",
                    help="skip the assessor call (only score axes 1+2)")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.inp.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]
    print(f"Scoring {len(rows)} rows from {args.inp}")

    # Step A: extract citation from each model response
    for row in rows:
        row["_extract"] = extract_citation(row.get("model_response", ""))

    # Step B: batch-verify each extracted citation
    print("Step A/B: extracting + verifying citations...")
    rows = asyncio.run(verify_extracted(rows))

    # Step C: per-row substance assessment
    client = CourtListenerClient()
    client.REQUEST_TIMEOUT = 60

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id", "source", "proposition", "gold_name", "gold_cite",
        "model_response", "extracted_case_name", "extracted_citation",
        "extracted_year",
        "real", "real_status", "name_match", "matched_cl_name", "matched_cluster_id",
        "right_case",
        "supports", "support_rationale", "support_cost_usd",
        "model_cost_usd",
    ]
    total_assessor_cost = 0.0
    n_ok_extract = 0
    n_real = 0
    n_name = 0
    n_unknown = 0

    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for i, row in enumerate(rows, 1):
            ext = row.get("_extract") or {}
            ver = row.get("_verify")

            unknown = bool(ext.get("unknown"))
            if unknown:
                n_unknown += 1
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
                if real:
                    n_real += 1

            extracted_case = ext.get("case_name", "")
            name_match = name_matches_check(extracted_case, cl_name) if real else False
            if name_match:
                n_name += 1
            if ext.get("citation_text"):
                n_ok_extract += 1

            # Did the model cite the gold case? (strict diagnostic)
            gold_cite = (row.get("gold_cite") or "").strip()
            gold_name = (row.get("gold_name") or "").strip()
            ext_cite = (ext.get("citation_text") or "").strip()
            ext_case = (ext.get("case_name") or "").strip()
            right_case = bool(
                ext_cite and ext_cite in gold_cite
            ) and (
                _names_score(ext_case, gold_name) >= 0.6
                if (ext_case and gold_name) else False
            )

            # Step C: substance assessment (only if we actually have a real case)
            support = None
            support_rationale = ""
            support_cost = 0.0
            if not args.skip_substance and real:
                opinion_text = fetch_opinion_text(client, cluster_id)
                if opinion_text:
                    case_label = f"{cl_name or extracted_case}, {ext_cite}"
                    print(f"  [{i}/{len(rows)}] assessing: {case_label[:60]}")
                    a = call_assessor(row["proposition"], case_label, opinion_text)
                    support = a["assessment"]
                    support_rationale = a["rationale"]
                    support_cost = a["cost_usd"]
                    total_assessor_cost += support_cost or 0
                else:
                    support_rationale = "no opinion text"
            elif unknown:
                support_rationale = "model returned UNKNOWN"

            writer.writerow({
                "id": row["id"],
                "source": row["source"],
                "proposition": row["proposition"],
                "gold_name": gold_name,
                "gold_cite": gold_cite,
                "model_response": row.get("model_response", ""),
                "extracted_case_name": extracted_case,
                "extracted_citation": ext_cite,
                "extracted_year": ext.get("year", ""),
                "real": "Y" if real else "N",
                "real_status": real_status,
                "name_match": "Y" if name_match else "N",
                "matched_cl_name": cl_name,
                "matched_cluster_id": cluster_id,
                "right_case": "Y" if right_case else "N",
                "supports": support or "",
                "support_rationale": support_rationale,
                "support_cost_usd": support_cost,
                "model_cost_usd": row.get("cost_usd", 0),
            })
            f.flush()

    print(f"\nWrote {args.out}")
    print(f"Extracts: {n_ok_extract}/{len(rows)} ; UNKNOWN: {n_unknown}")
    print(f"Real (axis 1): {n_real}/{len(rows)}")
    print(f"Name match (axis 2): {n_name}/{len(rows)}")
    print(f"Assessor cost: ${total_assessor_cost:.2f}")


if __name__ == "__main__":
    main()
