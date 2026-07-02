"""Resume the torn-down opus-v2 SDK control and score it.

One-off: fills the ~19 missing assess jobs in the existing run copy
(resume-keyed, so completed corpora no-op), scores each corpus the way
tools/ab_test_runner.py does (skip-mode RecordedExecutor so a transient
gap can't crash scoring), and writes a durable results snapshot to
scratch/ab_runs/ (the run copy under tests/data/results is gitignored).
"""
import json
from datetime import datetime
from pathlib import Path

from citation_verifier.proposition_pipeline import run_assess
from citation_verifier.executor import AgentSDKExecutor, RecordedExecutor
from citation_verifier.scoring import score_workdir

RUN = Path("tests/data/results/ab_runs/opus-v2_20260701-200903")
PV = "assess-v2"
CORPORA = ["withers", "payne", "wainwright"]

scores = {}
for name in CORPORA:
    wd = RUN / name
    ex = AgentSDKExecutor(model="opus", cwd=str(wd))
    stats = run_assess(wd, executor=ex, prompt_version=PV)
    fails = getattr(ex, "failures", [])
    if fails:
        print(f"  {name}: {len(fails)} job failures: {fails[:3]}", flush=True)
    if getattr(stats, "pending", 0):
        print(f"  {name}: {stats.pending} verdicts still pending", flush=True)
    scorer = RecordedExecutor(wd / "jobs" / "assess_results.jsonl",
                              missing="skip")
    s = score_workdir(wd, executor=scorer, prompt_version=PV)
    if scorer.misses:
        print(f"  {name}: {len(scorer.misses)} claims dropped from scoring "
              f"({scorer.misses[:3]})", flush=True)
    scores[name] = s
    print(f"=== {name} ===", flush=True)
    for attr in ("yellows_caught", "yellows_total", "reds_caught",
                 "reds_total", "greens_overflagged", "exact", "total"):
        if hasattr(s, attr):
            print(f"    {attr} = {getattr(s, attr)}", flush=True)

# Durable snapshot (mirror save_results' row format)
out_dir = Path("scratch/ab_runs")
out_dir.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d-%H%M%S")
out = out_dir / f"ab_opus-v2_{ts}.jsonl"
with out.open("w", encoding="utf-8") as f:
    for corpus, score in scores.items():
        for row in score.rows:
            f.write(json.dumps({"corpus": corpus, **row}) + "\n")
print(f"\nRESULTS SNAPSHOT: {out}", flush=True)
print("DONE", flush=True)
