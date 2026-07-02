"""Root-cause probe: catch a REAL sonnet-v1 parse failure with full raw
text. Runs the whole withers corpus fresh through a debug executor that
dumps complete raw text + block types for any job whose result fails
_parse_json_object. Loops fresh copies until >=1 failure is caught (the
failure is intermittent, ~7% of jobs) or max attempts hit.
"""
import shutil
from pathlib import Path

from citation_verifier.executor import MessagesAPIExecutor, _parse_json_object
from citation_verifier.proposition_pipeline import run_assess

FROZEN = Path("tests/data/assessment_corpora/withers")
OUT = Path("scratch/parse_failure_raw.txt")
MAX_ATTEMPTS = 4

if OUT.exists():
    OUT.unlink()
caught = 0


class DebugExecutor(MessagesAPIExecutor):
    def _verdicts_from_message(self, job, message, elapsed_s):
        global caught
        text = "".join(
            getattr(b, "text", "") for b in (message.content or [])
            if getattr(b, "type", "") == "text")
        if _parse_json_object(text) is None:
            caught += 1
            block_types = [getattr(b, "type", "?")
                           for b in (message.content or [])]
            with OUT.open("a", encoding="utf-8") as f:
                f.write(f"\n===== FAILED job {job.job_id} =====\n")
                f.write(f"stop_reason={getattr(message,'stop_reason','')}\n")
                f.write(f"block types: {block_types}\n")
                f.write(f"raw len={len(text)}\n")
                f.write("---- RAW TEXT ----\n")
                f.write(text + "\n")
                f.write("---- repr ----\n")
                f.write(repr(text) + "\n")
        return super()._verdicts_from_message(job, message, elapsed_s)


for attempt in range(1, MAX_ATTEMPTS + 1):
    wd = Path(f"scratch/_debug_withers_{attempt}")
    if wd.exists():
        shutil.rmtree(wd)
    shutil.copytree(FROZEN, wd)
    (wd / "jobs" / "assess_results.jsonl").unlink(missing_ok=True)
    ex = DebugExecutor(model="claude-sonnet-5", cwd=str(wd))
    run_assess(wd, executor=ex, prompt_version="assess-v1")
    print(f"attempt {attempt}: {len(ex.failures)} failures, "
          f"{caught} total captured")
    shutil.rmtree(wd, ignore_errors=True)
    if caught:
        break

print(f"raw dump -> {OUT} (captured {caught})")
