"""Re-record the assessment-corpora cassettes under assess-v2 (Step 8, 9.3).

For each corpus: copy the frozen workdir to a run dir, run assess-v2 live
through AgentSDKExecutor (per-opinion packed jobs, all-Opus per the Step 8
decision log), then append the NEW assess-v2 verdicts to the frozen
cassette (jobs/assess_results.jsonl -- one file holds both versions;
RecordedExecutor keys on claim_id + prompt_version).

Resume-safe: each invocation copies the frozen corpus fresh, so v2 verdicts
already appended to the frozen cassette by a previous (partial) run are
inherited by the copy and run_assess skips them.

Usage:
    venv/Scripts/python.exe tools/record_assess_v2.py [--corpus NAME ...]
        [--model opus]
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

CORPORA = PROJECT_ROOT / "tests" / "data" / "assessment_corpora"
VERSION = "assess-v2"


def record_corpus(name: str, model: str) -> bool:
    from citation_verifier.executor import AgentSDKExecutor
    from citation_verifier.proposition_pipeline import run_assess

    frozen = CORPORA / name
    frozen_cassette = frozen / "jobs" / "assess_results.jsonl"
    run_wd = Path(tempfile.mkdtemp(prefix=f"v2rec_{name}_")) / name
    shutil.copytree(frozen, run_wd)

    print(f"=== {name}: recording {VERSION} (model={model}) ===",
          flush=True)
    ex = AgentSDKExecutor(model=model, cwd=str(run_wd))
    stats = run_assess(run_wd, executor=ex, prompt_version=VERSION)
    print(f"  {name}: eligible={stats.eligible} done={stats.done} "
          f"pending={stats.pending}", flush=True)
    for job_id, reason in ex.failures:
        print(f"  FAILURE {name}/{job_id}: {reason[:160]}", flush=True)

    # Append only NEW v2 lines to the frozen cassette (raw-line copy so
    # the cassette stays byte-faithful to what the executor wrote).
    have = set()
    for line in frozen_cassette.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            have.add((r["claim_id"], r.get("prompt_version", "")))
    appended = 0
    with frozen_cassette.open("a", encoding="utf-8") as out:
        for line in (run_wd / "jobs" / "assess_results.jsonl").read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["claim_id"], r.get("prompt_version", ""))
            if r.get("prompt_version") == VERSION and key not in have:
                out.write(line + "\n")
                have.add(key)
                appended += 1
    print(f"  {name}: appended {appended} {VERSION} verdicts to the "
          f"frozen cassette", flush=True)
    return stats.pending == 0 and not ex.failures


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Re-record corpora cassettes under assess-v2")
    ap.add_argument("--corpus", nargs="+",
                    default=["withers", "payne", "wainwright"])
    ap.add_argument("--model", default="opus")
    args = ap.parse_args()
    ok = True
    for name in args.corpus:
        ok = record_corpus(name, args.model) and ok
    print("RESULT:", "COMPLETE" if ok else
          "INCOMPLETE -- rerun this script to resume", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
