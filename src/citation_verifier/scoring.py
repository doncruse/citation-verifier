"""Two-axis scoring for the proposition pipeline (design SS6.9 / SS8).

Every claim carries three independent verdicts -- existence (verifier
status), support (supported|partial|unsupported|unverifiable), quote
(worst per-quote verdict). Report color is a documented pure function of
the three (derive_color). Scoring against external audits uses a
documented per-scale mapping (score_workdir): the Withers exhibit's
colors encode existence, ours encode support severity, so exhibit-yellow
matches our {Yellow, Red} and exhibit-red matches our existence lanes.

Offline by default: predictions replay a recorded cassette through
RecordedExecutor over a frozen corpus workdir
(tests/data/assessment_corpora/<name>/).

CLI:
    python -m citation_verifier.scoring <corpus-dir> [<corpus-dir> ...]
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

from .executor import Job, LLMExecutor, RecordedExecutor

GREEN = "Green"
YELLOW = "Yellow"
RED = "Red"
GRAY = "Gray"
CHECK_CITE = "CheckCite"

UNLOCATABLE = {"NOT_FOUND", "INSUFFICIENT_DATA", "VERIFICATION_INCOMPLETE"}
LOCATED = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
           "VERIFIED_DOCKET_ONLY", "CITE_UNCONFIRMED"}
_BAD_QUOTES = {"CLOSE", "FABRICATED"}

DEFAULT_PROMPT_VERSION = "assess-v1"

# Exhibit-scale mapping (SS6.9): the Withers exhibit's colors encode
# existence, ours encode support severity.
#   exhibit yellow ~= our {Yellow, Red} on a real case
#   exhibit red    ~= our {WRONG_CASE-Red, NOT_FOUND-Gray, CheckCite}
_EXHIBIT_YELLOW_CAUGHT = {YELLOW, RED}
_EXHIBIT_RED_CAUGHT = {RED, GRAY, CHECK_CITE}


def derive_color(existence: str, support: str | None = None,
                 quote_worst: str | None = None) -> str:
    """SS6.9: report color as a function of the three axes."""
    if existence in UNLOCATABLE:
        return GRAY
    if existence == "WRONG_CASE":
        return RED
    if existence == "CITE_UNCONFIRMED":
        return CHECK_CITE  # amber lane -- never Red
    # VERIFIED family: the support axis decides, quote floors apply.
    if support == "unsupported":
        return RED
    if support == "partial":
        return YELLOW
    if support == "supported":
        if quote_worst in _BAD_QUOTES:
            return YELLOW
        return GREEN
    return GRAY  # unverifiable / missing support axis


@dataclass
class ClaimPrediction:
    claim_id: str
    predicted: str
    mode: str  # "deterministic" | "agent"
    rationale: str = ""


def predict_workdir(workdir: str | Path, executor: LLMExecutor,
                    prompt_version: str = DEFAULT_PROMPT_VERSION,
                    ) -> list[ClaimPrediction]:
    """Predict a color per claim in a conforming workdir.

    Deterministic existence lanes are computed from claims.csv state
    (mirroring the 2026-06-11 measurement script); everything else gets
    the executor's verdict. With RecordedExecutor this is fully offline.
    """
    workdir = Path(workdir)
    claims = list(csv.DictReader(
        (workdir / "claims.csv").open(encoding="utf-8")))
    preds: list[ClaimPrediction] = []
    agent_claims: list[dict] = []
    for c in claims:
        status = c.get("cl_status", "")
        has_opinion = bool(c.get("opinion_file"))
        if status == "WRONG_CASE":
            preds.append(ClaimPrediction(
                c["claim_id"], RED, "deterministic",
                "WRONG_CASE -- citation resolves to a different case"))
        elif not has_opinion and status not in LOCATED:
            preds.append(ClaimPrediction(
                c["claim_id"], GRAY, "deterministic",
                f"{status or 'unmatched'} and no opinion text"))
        elif not has_opinion:
            preds.append(ClaimPrediction(
                c["claim_id"], YELLOW, "deterministic",
                f"{status} but opinion text not available"))
        else:
            agent_claims.append(c)
    if agent_claims:
        jobs = [Job(job_id=f"assess-{c['claim_id']}",
                    claim_ids=[c["claim_id"]],
                    prompt="",  # replay keys on (claim_id, prompt_version)
                    prompt_version=prompt_version,
                    files=[c["opinion_file"]])
                for c in agent_claims]
        for v in executor.run(jobs):
            preds.append(ClaimPrediction(
                v.claim_id, v.fields["assessment"], "agent",
                v.fields.get("rationale", "")))
    order = {c["claim_id"]: i for i, c in enumerate(claims)}
    preds.sort(key=lambda p: order[p.claim_id])
    return preds


@dataclass
class CorpusScore:
    rows: list[dict] = field(default_factory=list)
    # internal scale
    total: int = 0
    correct: int = 0
    # withers_exhibit scale
    yellows_total: int = 0
    yellows_caught: int = 0
    yellows_exact: int = 0
    greens_total: int = 0
    greens_exact: int = 0
    greens_overflagged: int = 0
    reds_total: int = 0
    reds_caught: int = 0


def score_workdir(workdir: str | Path,
                  executor: LLMExecutor | None = None,
                  prompt_version: str = DEFAULT_PROMPT_VERSION,
                  ) -> CorpusScore:
    """Score predictions against the workdir's ground_truth.csv.

    Ground-truth rows absent from claims.csv are skipped (e.g. the Withers
    exhibit has 54 rows; the frozen workdir holds the 34-row measurement
    sample). Default executor replays jobs/assess_results.jsonl.
    """
    workdir = Path(workdir)
    if executor is None:
        executor = RecordedExecutor(workdir / "jobs" / "assess_results.jsonl")
    preds = {p.claim_id: p for p in
             predict_workdir(workdir, executor, prompt_version)}
    gt = list(csv.DictReader(
        (workdir / "ground_truth.csv").open(encoding="utf-8")))

    score = CorpusScore()
    for g in gt:
        p = preds.get(g["claim_id"])
        if p is None:
            continue  # ground truth beyond the frozen workdir's sample
        row = {"claim_id": g["claim_id"], "scale": g["scale"],
               "expected": g["expected"], "predicted": p.predicted,
               "mode": p.mode}
        if g["scale"] == "internal":
            score.total += 1
            row["correct"] = p.predicted == g["expected"]
            score.correct += row["correct"]
        elif g["scale"] == "withers_exhibit":
            label = g["expected"]
            if label == "yellow":
                score.yellows_total += 1
                row["correct"] = p.predicted in _EXHIBIT_YELLOW_CAUGHT
                score.yellows_caught += row["correct"]
                score.yellows_exact += p.predicted == YELLOW
            elif label == "green":
                score.greens_total += 1
                row["correct"] = p.predicted == GREEN
                score.greens_exact += row["correct"]
                score.greens_overflagged += p.predicted in (YELLOW, RED)
            elif label == "red":
                score.reds_total += 1
                row["correct"] = p.predicted in _EXHIBIT_RED_CAUGHT
                score.reds_caught += row["correct"]
        else:
            raise ValueError(f"unknown ground-truth scale: {g['scale']!r}")
        score.rows.append(row)
    return score


def format_report(name: str, score: CorpusScore) -> str:
    """ASCII summary (Windows-console safe)."""
    lines = [f"=== {name} ==="]
    if score.total:
        lines.append(f"internal scale: {score.correct}/{score.total} exact "
                     f"({score.correct / score.total:.0%})")
    if score.yellows_total or score.greens_total or score.reds_total:
        lines.append(
            f"exhibit scale: yellows caught {score.yellows_caught}/"
            f"{score.yellows_total} ({score.yellows_exact} exact); "
            f"greens exact {score.greens_exact}/{score.greens_total} "
            f"({score.greens_overflagged} over-flagged); "
            f"reds caught {score.reds_caught}/{score.reds_total}")
    misses = [r for r in score.rows if not r.get("correct")]
    for r in misses:
        lines.append(f"  MISS {r['claim_id']}: expected {r['expected']}, "
                     f"predicted {r['predicted']} ({r['mode']})")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score a frozen assessment corpus offline "
                    "(replays jobs/assess_results.jsonl).")
    ap.add_argument("workdir", nargs="+",
                    help="corpus workdir(s), e.g. "
                         "tests/data/assessment_corpora/withers")
    ap.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    args = ap.parse_args()
    for wd in args.workdir:
        score = score_workdir(wd, prompt_version=args.prompt_version)
        print(format_report(Path(wd).name, score))


if __name__ == "__main__":
    main()
