"""Second-measurement baseline: run the CURRENT assessment layer (verify-brief
Phase 2 path) over the Withers v. City of Aberdeen corpus and score its
Green/Yellow/Red predictions against the exhibit's human labels.

Companion to measure_withers_baseline.py (which measured the existence layer
and found 0/19 yellows catchable by the verifier). This script measures the
layer the redesign is actually about: given (citation, proposition, opinion
text), does the current assessment approach reproduce the exhibit author's
color call?

Fidelity choices:
- Front end is the REAL pipeline: brief_pipeline.wave1_verify_and_download +
  wave2_fallback_and_download + merge_claims + check_quotes. Real opinion
  downloads (incl. sibling-cluster swap), real deterministic quote checker.
- The assessment call is the ab_test_runner.py single-claim prompt — the
  prompt the A/B harness established as the measurable proxy for the SKILL's
  Phase 2c (same criteria text, same JSON contract), run via `claude -p`
  with --model opus (the SKILL's Phase 2c model).
- quoted_text is auto-extracted from the exhibit's transcribed proposition
  (double-quoted spans of >= 4 words). Single-quoted spans are skipped
  (apostrophe ambiguity); the agent still sees them inside the proposition.
- Deterministic mappings where the current pipeline never calls an agent:
    WRONG_CASE                          -> predicted Red  (resolves to different case)
    not located, no opinion text        -> predicted Gray (unable to verify)
    located but opinion download failed -> predicted Yellow (SKILL special case)

Sample: all 19 yellows + all 3 reds + 12 hand-picked greens (4 plain
VERIFIED, 3 hedged "arguable" greens, 2 VERIFIED_PARTIAL/name_unverified,
2 cite_not_on_record greens, 1 WL-coverage-gap NOT_FOUND green).

Live API (verification phase) + `claude -p` (assessment phase). Resumable:
assessment results are appended to a JSONL sidecar; rerunning skips done rows.

Usage:
    venv/Scripts/python.exe tests/measure_withers_assessment.py
        [--skip-verify]     reuse existing workdir (claims.csv + opinions/)
        [--score-only]      just rescore the existing JSONL
        [--max-workers N]   concurrent claude -p calls (default 3)
        [--model NAME]      default opus

Output:
    tests/data/withers_assessment_results.csv   (final scored table)
    tests/data/withers_assessment_runs.jsonl    (raw per-row agent output)
    tests/data/assessment_corpora/withers/      (frozen pipeline workdir)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
_DATA = Path(__file__).parent / "data"
_BASELINE = _DATA / "withers_baseline_results.csv"
_WORKDIR = _DATA / "assessment_corpora" / "withers"
_OUT_CSV = _DATA / "withers_assessment_results.csv"
_OUT_JSONL = _DATA / "withers_assessment_runs.jsonl"

# All yellows + all reds are auto-included. Greens are hand-picked:
_GREEN_SAMPLE = [
    "withers-01",  # plain VERIFIED green (Nix)
    "withers-07",  # plain VERIFIED green (Celotex)
    "withers-21",  # plain VERIFIED green, long multi-part proposition (Lacy)
    "withers-39",  # plain VERIFIED green (Matsushita)
    "withers-26",  # hedged green — author calls it "arguable" (Scott v. Carpanzano)
    "withers-36",  # hedged green (Missouri v. Jenkins n.10)
    "withers-46",  # hedged green (Franconia)
    "withers-11",  # VERIFIED_PARTIAL + name_unverified ("See, e.g., In re Carney")
    "withers-20",  # VERIFIED_PARTIAL + name_unverified ("See, e.g., In re United States")
    "withers-30",  # green w/ cite_not_on_record warning (Rice, WL cite)
    "withers-50",  # green w/ cite_not_on_record, conf 0.54 (Yilport)
    "withers-29",  # green NOT_FOUND — WL coverage gap (Hernandez) -> Gray path
]

_LOCATED = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
            "VERIFIED_DOCKET_ONLY", "CITE_UNCONFIRMED"}

# Double-quoted spans (straight or smart) of >= 4 words
_QUOTE_SPAN = re.compile(r'[“"]([^"“”]{10,}?)[”"]')


def extract_quotes(proposition: str) -> list[str]:
    out = []
    for m in _QUOTE_SPAN.finditer(proposition):
        span = m.group(1).strip()
        if len(span.split()) >= 4:
            out.append(span)
    return out


def load_sample() -> list[dict]:
    rows = list(csv.DictReader(_BASELINE.open(encoding="utf-8")))
    sample = [r for r in rows
              if r["label"] in ("yellow", "red") or r["row_id"] in _GREEN_SAMPLE]
    return sample


# ---------------------------------------------------------------------------
# Phase 1: pipeline front end (verify + download + merge + quote check)
# ---------------------------------------------------------------------------

def build_workdir(sample: list[dict]) -> None:
    from citation_verifier.brief_pipeline import (
        check_quotes, merge_claims, wave1_verify_and_download,
        wave2_fallback_and_download,
    )

    _WORKDIR.mkdir(parents=True, exist_ok=True)
    claims_path = _WORKDIR / "claims.csv"

    with claims_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "page", "proposition", "cited_case", "quoted_text", "brief_sentence",
        ])
        w.writeheader()
        for r in sample:
            w.writerow({
                "page": r["doc_number"],
                "proposition": r["proposition"],
                "cited_case": r["citation"],
                "quoted_text": json.dumps(extract_quotes(r["proposition"])),
                "brief_sentence": r["proposition"],
            })

    citations = list(dict.fromkeys(r["citation"] for r in sample))
    print(f"Verifying {len(citations)} unique citations (live API)...")

    async def _run() -> None:
        w1 = await wave1_verify_and_download(_WORKDIR, citations)
        print(f"  wave1: {len(citations) - len(w1.miss_indices)} hits, "
              f"{len(w1.miss_indices)} misses, downloads={w1.download_stats}")
        w2 = await wave2_fallback_and_download(_WORKDIR, citations, w1.miss_indices)
        print(f"  wave2: downloads={w2.download_stats}")

    asyncio.run(_run())


def _slug_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 2}


def link_and_check_quotes() -> None:
    """Merge + opinion-file linkage fixup + quote check.

    merge_claims links opinion files by cited-name/filename containment, which
    fails when CL's caption is longer than the cited name (e.g. 'Midwest
    Employers Cas. Co. v. Williams' vs the downloaded
    'MIDWEST_EMPLOYERS_CASUALTY_CO_Plaintiff-Appellant-Appellee_v_Jo_Ann_
    WILLIAMS...'). Root cause: matched_name is empty in
    verification_results.csv on the batch path (raw_response_summary lacks
    case_name) — a pipeline bug to log in the design doc. Workaround here:
    token-overlap match between the cl_url slug and the file stems.
    """
    from citation_verifier.brief_pipeline import check_quotes, merge_claims

    m = merge_claims(_WORKDIR)
    print(f"  merge: {m.matched} matched, {m.unmatched} unmatched, "
          f"{m.opinion_count} with opinion files; statuses={m.statuses}")
    if m.unmatched_claims:
        print(f"  UNMATCHED: {m.unmatched_claims}")

    claims_path = _WORKDIR / "claims.csv"
    claims = list(csv.DictReader(claims_path.open(encoding="utf-8")))
    stems = {f.name: _slug_tokens(f.stem)
             for f in (_WORKDIR / "opinions").iterdir() if f.is_file()}
    relinked = 0
    for claim in claims:
        if claim.get("opinion_file") or claim.get("cl_status") not in _LOCATED:
            continue
        url = claim.get("cl_url", "")
        slug = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
        if not slug:
            continue
        st = _slug_tokens(slug)
        best, best_score = "", 0.0
        for fname, ft in stems.items():
            if not st or not ft:
                continue
            score = len(st & ft) / len(st | ft)
            if score > best_score:
                best, best_score = fname, score
        if best and best_score >= 0.25:
            claim["opinion_file"] = f"opinions/{best}"
            relinked += 1
    with claims_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(claims[0].keys()))
        w.writeheader()
        w.writerows(claims)
    linked = sum(1 for c in claims if c.get("opinion_file"))
    print(f"  linkage fixup: +{relinked} relinked via cl_url slug; "
          f"{linked}/{len(claims)} rows now have opinion files")

    q = check_quotes(_WORKDIR)
    print(f"  quotes: {q.checked} checked, {q.verbatim} verbatim, {q.close} close, "
          f"{q.fabricated} fabricated, {q.no_quotes} no-quotes, {q.no_opinion} no-opinion")


# ---------------------------------------------------------------------------
# Phase 2: assessment via claude -p (ab_test_runner prompt, verbatim criteria)
# ---------------------------------------------------------------------------

def build_prompt(opinion_path: Path, cited_case: str, proposition: str,
                 qcw: str) -> str:
    return "\n".join([
        "You are assessing whether a case citation in a legal brief supports "
        "the proposition it is cited for.",
        "",
        "Read the opinion file at: {}".format(opinion_path),
        "",
        "Cited case: {}".format(cited_case),
        "Proposition: {}".format(proposition),
        "Quote check result: {}".format(qcw),
        "",
        "Assessment criteria:",
        "- Green: case directly and accurately supports the proposition",
        "- Yellow: partially relevant, support weaker than represented, "
        "or proposition overstates the holding",
        "- Red: does not support, misleading, case addresses a completely "
        "different topic, or quoted language is fabricated",
        "",
        "If the quote check is FABRICATED, downgrade to at least Yellow.",
        "",
        "Respond with ONLY a JSON object (no markdown, no explanation):",
        '{"assessment": "Green|Yellow|Red", "rationale": "one sentence"}',
    ])


def parse_response(response_text: str) -> tuple[str | None, str]:
    try:
        for line in response_text.split("\n"):
            line = line.strip()
            if line.startswith("{") and "assessment" in line:
                parsed = json.loads(line)
                return parsed.get("assessment"), parsed.get("rationale", "")
        parsed = json.loads(response_text)
        return parsed.get("assessment"), parsed.get("rationale", "")
    except (json.JSONDecodeError, TypeError):
        for color in ["Red", "Yellow", "Green"]:
            if color in response_text:
                return color, response_text[:200]
    return None, response_text[:200]


def run_assessment(row_id: str, claim: dict, model: str) -> dict:
    opinion_path = _WORKDIR / claim["opinion_file"]
    prompt = build_prompt(opinion_path, claim["cited_case"],
                          claim["proposition"],
                          claim.get("quote_check_worst", "NO_QUOTES"))
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--model", model, "--allowedTools", "Read,Glob,Grep"]
    # When run from inside a Claude Code session, ANTHROPIC_BASE_URL /
    # CLAUDE* env vars leak into the child and break CLI auth (401).
    # Strip them so the nested CLI uses the user's stored credentials.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("ANTHROPIC") or k.startswith("CLAUDE"))}
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=240, cwd=str(PROJECT_ROOT), env=env)
        elapsed = round(time.time() - start, 1)
        stdout = result.stdout.strip()
        response_text, cost = stdout, 0
        try:
            out = json.loads(stdout)
            response_text = out.get("result", stdout)
            cost = out.get("total_cost_usd", 0)
        except json.JSONDecodeError:
            pass
        assessment, rationale = parse_response(response_text)
        return {"row_id": row_id, "predicted": assessment,
                "rationale": rationale[:300], "elapsed_s": elapsed,
                "cost_usd": cost, "mode": "agent"}
    except subprocess.TimeoutExpired:
        return {"row_id": row_id, "predicted": None, "rationale": "TIMEOUT",
                "elapsed_s": 240, "cost_usd": 0, "mode": "agent"}
    except Exception as e:  # noqa: BLE001
        return {"row_id": row_id, "predicted": None,
                "rationale": f"ERROR: {str(e)[:150]}", "elapsed_s": 0,
                "cost_usd": 0, "mode": "agent"}


def assess_all(sample: list[dict], model: str, max_workers: int) -> dict[str, dict]:
    # claims.csv rows are in the same order as the sample
    claims = list(csv.DictReader((_WORKDIR / "claims.csv").open(encoding="utf-8")))
    assert len(claims) == len(sample), (
        f"claims.csv rows ({len(claims)}) != sample ({len(sample)})")

    done: dict[str, dict] = {}
    if _OUT_JSONL.exists():
        for line in _OUT_JSONL.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("predicted"):
                done[r["row_id"]] = r
    if done:
        print(f"Resuming: {len(done)} rows already assessed in {_OUT_JSONL.name}")

    lock = threading.Lock()
    jsonl = _OUT_JSONL.open("a", encoding="utf-8")

    def record(res: dict) -> None:
        with lock:
            jsonl.write(json.dumps(res) + "\n")
            jsonl.flush()
            done[res["row_id"]] = res

    agent_jobs: list[tuple[str, dict]] = []
    prep_only = max_workers == 0
    for r, claim in zip(sample, claims):
        rid = r["row_id"]
        if rid in done:
            continue
        status = claim.get("cl_status", "")
        has_opinion = bool(claim.get("opinion_file"))
        if status == "WRONG_CASE":
            record({"row_id": rid, "predicted": "Red",
                    "rationale": "deterministic: WRONG_CASE — citation resolves "
                                 "to a different case", "mode": "deterministic"})
        elif not has_opinion and status not in _LOCATED:
            record({"row_id": rid, "predicted": "Gray",
                    "rationale": f"deterministic: {status or 'unmatched'} and no "
                                 "opinion text — unable to verify",
                    "mode": "deterministic"})
        elif not has_opinion:
            record({"row_id": rid, "predicted": "Yellow",
                    "rationale": f"deterministic: {status} but opinion text not "
                                 "available for review (SKILL special case)",
                    "mode": "deterministic"})
        else:
            agent_jobs.append((rid, claim))

    print(f"Assessment: {len(agent_jobs)} agent calls (model={model}, "
          f"workers={max_workers}), {len(done)} deterministic/resumed")

    if prep_only:
        # --max-workers 0: don't call claude -p (e.g. CLI auth unavailable).
        # Emit the job list so an orchestrator (Claude Code Agent tool) can
        # run the same prompts and append results to the JSONL.
        jobs_out = _DATA / "withers_assessment_jobs.json"
        payload = []
        for rid, claim in agent_jobs:
            payload.append({
                "row_id": rid,
                "opinion_path": str(_WORKDIR / claim["opinion_file"]),
                "cited_case": claim["cited_case"],
                "proposition": claim["proposition"],
                "quote_check_worst": claim.get("quote_check_worst", "NO_QUOTES"),
                "prompt": build_prompt(
                    _WORKDIR / claim["opinion_file"], claim["cited_case"],
                    claim["proposition"],
                    claim.get("quote_check_worst", "NO_QUOTES")),
            })
        jobs_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Prep-only: wrote {len(payload)} jobs to {jobs_out}")
        jsonl.close()
        return done

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(run_assessment, rid, claim, model): rid
                   for rid, claim in agent_jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            record(res)
            print(f"  [{i}/{len(agent_jobs)}] {res['row_id']}: "
                  f"{res['predicted']} ({res.get('elapsed_s', '?')}s) "
                  f"{res['rationale'][:80]}", flush=True)

    jsonl.close()
    return done


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(sample: list[dict], done: dict[str, dict]) -> None:
    claims = list(csv.DictReader((_WORKDIR / "claims.csv").open(encoding="utf-8")))
    rows = []
    for r, claim in zip(sample, claims):
        res = done.get(r["row_id"], {})
        predicted = res.get("predicted") or "NONE"
        rows.append({
            "row_id": r["row_id"],
            "citation": r["citation"],
            "label": r["label"],
            "hedged": r["hedged"],
            "exists": r["exists"],
            "cl_status": claim.get("cl_status", ""),
            "opinion_file": claim.get("opinion_file", ""),
            "quote_check_worst": claim.get("quote_check_worst", ""),
            "predicted": predicted,
            "mode": res.get("mode", ""),
            "rationale": res.get("rationale", ""),
            "irregularity": r["irregularity"],
        })

    with _OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n" + "=" * 72)
    print("CONFUSION (exhibit label x predicted):")
    xt = Counter((r["label"], r["predicted"]) for r in rows)
    for (label, pred), n in sorted(xt.items()):
        print(f"  {label:6s} -> {pred:7s} : {n}")

    yellows = [r for r in rows if r["label"] == "yellow"]
    y_caught = [r for r in yellows if r["predicted"] in ("Yellow", "Red")]
    y_missed = [r for r in yellows if r["predicted"] == "Green"]
    print(f"\nYELLOWS (n={len(yellows)}): caught (Yellow/Red) = "
          f"{len(y_caught)}, missed (called Green) = {len(y_missed)}, "
          f"other = {len(yellows) - len(y_caught) - len(y_missed)}")
    for r in y_missed:
        print(f"  MISSED: {r['row_id']} qc={r['quote_check_worst']:10s} "
              f"{r['citation'][:55]}")

    greens = [r for r in rows if r["label"] == "green"]
    g_exact = [r for r in greens if r["predicted"] == "Green"]
    g_flagged = [r for r in greens if r["predicted"] in ("Yellow", "Red")]
    print(f"\nGREENS sampled (n={len(greens)}): exact = {len(g_exact)}, "
          f"over-flagged (Yellow/Red) = {len(g_flagged)}")
    for r in g_flagged:
        hh = " [hedged]" if r["hedged"] == "yes" else ""
        print(f"  OVER-FLAGGED{hh}: {r['row_id']} -> {r['predicted']} "
              f"{r['citation'][:50]}")

    reds = [r for r in rows if r["label"] == "red"]
    print(f"\nREDS (n={len(reds)}):")
    for r in reds:
        print(f"  {r['row_id']}: predicted={r['predicted']} ({r['mode']})")

    exact = sum(1 for r in rows if r["predicted"].lower() == r["label"])
    print(f"\nExact-match accuracy (Gray counts as miss): {exact}/{len(rows)} "
          f"({exact / len(rows):.0%})")
    agent_rows = [r for r in rows if r["mode"] == "agent"]
    agent_exact = sum(1 for r in agent_rows if r["predicted"].lower() == r["label"])
    print(f"Agent-assessed rows only: {agent_exact}/{len(agent_rows)} "
          f"({agent_exact / max(len(agent_rows), 1):.0%})")
    print(f"\nWrote {_OUT_CSV}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true",
                    help="reuse existing workdir (claims.csv + opinions/)")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--max-workers", type=int, default=3)
    ap.add_argument("--model", default="opus")
    args = ap.parse_args()

    sample = load_sample()
    print(f"Sample: {len(sample)} rows "
          f"({Counter(r['label'] for r in sample)})")

    if args.score_only:
        done = {}
        for line in _OUT_JSONL.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("predicted"):
                done[r["row_id"]] = r
        score(sample, done)
        return

    if not args.skip_verify:
        build_workdir(sample)
    link_and_check_quotes()
    done = assess_all(sample, args.model, args.max_workers)
    score(sample, done)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety
    main()
