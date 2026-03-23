"""
A/B test runner for verify-brief assessment phase.

Runs test cases through Claude Code headless mode with different configs,
comparing assessment accuracy, speed, and token usage.

Usage:
    # Run a single config:
    python tests/ab_test_runner.py --config opus-baseline

    # Run two configs for comparison:
    python tests/ab_test_runner.py --config opus-baseline sonnet-baseline

    # Dry run (show prompts without executing):
    python tests/ab_test_runner.py --config opus-baseline --dry-run

    # Use a specific test cases file:
    python tests/ab_test_runner.py --config opus-baseline --cases tests/ab_test_cases.json

    # Compare existing results:
    python tests/ab_test_runner.py --compare results/ab_opus-baseline.jsonl results/ab_sonnet-baseline.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BRIEFS_DIR = PROJECT_ROOT / "briefs"
RESULTS_DIR = PROJECT_ROOT / "tests" / "data" / "results"
CASES_FILE = PROJECT_ROOT / "tests" / "ab_test_cases.json"
CONFIGS_FILE = PROJECT_ROOT / "tests" / "ab_test_configs.json"


def load_cases(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    brief = data.get("brief", "")
    return brief, data["cases"]


def load_configs(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["configs"]


SOURCE_DIRS = {
    "payne": "briefs/payne-proposed",
    "wainwright": "briefs/wainwright-v-state",
}


def build_prompt(case, config, brief_dir):
    """Build the assessment prompt for a single test case."""
    source = case.get("source", "")
    if source in SOURCE_DIRS:
        opinion_path = PROJECT_ROOT / SOURCE_DIRS[source] / case["opinion_file"]
    else:
        opinion_path = brief_dir / case["opinion_file"]
    proposition = case["proposition"]
    cited_case = case["cited_case"]
    qcw = case.get("quote_check_worst", "NO_QUOTES")

    prompt_parts = [
        "You are assessing whether a case citation in a legal brief supports "
        "the proposition it is cited for.",
        "",
        "Read the opinion file at: {}".format(opinion_path),
        "",
        "Cited case: {}".format(cited_case),
        "Proposition: {}".format(proposition),
        "Quote check result: {}".format(qcw),
    ]

    if config.get("include_hints") and case.get("hint"):
        prompt_parts.extend([
            "",
            "Hint from preliminary review: {}".format(case["hint"]),
        ])

    prompt_parts.extend([
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

    return "\n".join(prompt_parts)


def run_case(case, config, brief_dir, dry_run=False):
    """Run a single test case through claude -p."""
    prompt = build_prompt(case, config, brief_dir)
    model = config.get("model", "sonnet")

    if dry_run:
        print("  [DRY RUN] Case {} | model={}".format(case["id"], model))
        print("  Prompt length: {} chars".format(len(prompt)))
        return {
            "case_id": case["id"],
            "dry_run": True,
            "prompt_length": len(prompt),
        }

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--allowedTools", "Read,Glob,Grep",
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.time() - start

        # Parse claude -p JSON output: {"type":"result","result":"...","usage":...}
        stdout = result.stdout.strip()
        response_text = ""
        cost_usd = 0
        input_tokens = 0
        output_tokens = 0
        try:
            claude_output = json.loads(stdout)
            response_text = claude_output.get("result", stdout)
            cost_usd = claude_output.get("total_cost_usd", 0)
            usage = claude_output.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
        except json.JSONDecodeError:
            response_text = stdout

        # Extract the assessment JSON from the response text
        assessment = None
        rationale = ""
        try:
            # Look for JSON object with "assessment" key
            for line in response_text.split("\n"):
                line = line.strip()
                if line.startswith("{") and "assessment" in line:
                    parsed = json.loads(line)
                    assessment = parsed.get("assessment")
                    rationale = parsed.get("rationale", "")
                    break
            if not assessment:
                parsed = json.loads(response_text)
                assessment = parsed.get("assessment")
                rationale = parsed.get("rationale", "")
        except (json.JSONDecodeError, TypeError):
            # Fallback: look for Green/Yellow/Red in text
            for color in ["Red", "Yellow", "Green"]:
                if color in response_text:
                    assessment = color
                    rationale = response_text[:200]
                    break

        return {
            "case_id": case["id"],
            "cited_case": case["cited_case"],
            "proposition": case["proposition"][:80],
            "expected": case["expected_assessment"],
            "actual": assessment,
            "correct": assessment == case["expected_assessment"],
            "rationale": rationale[:200],
            "elapsed_s": round(elapsed, 1),
            "model": model,
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    except subprocess.TimeoutExpired:
        return {
            "case_id": case["id"],
            "expected": case["expected_assessment"],
            "actual": None,
            "correct": False,
            "rationale": "TIMEOUT",
            "elapsed_s": 120,
            "model": model,
        }
    except Exception as e:
        return {
            "case_id": case["id"],
            "expected": case["expected_assessment"],
            "actual": None,
            "correct": False,
            "rationale": "ERROR: {}".format(str(e)[:100]),
            "elapsed_s": 0,
            "model": model,
        }


def run_config(config_name, config, cases, brief_dir, dry_run=False):
    """Run all test cases for a single config."""
    print("\n=== Config: {} ===".format(config_name))
    print("  {}".format(config.get("description", "")))
    print("  Model: {} | Hints: {} | {} cases".format(
        config.get("model", "sonnet"),
        config.get("include_hints", False),
        len(cases),
    ))

    results = []
    for i, case in enumerate(cases):
        print("  [{}/{}] Case {} ({})...".format(
            i + 1, len(cases), case["id"], case["cited_case"][:30]
        ), end="", flush=True)

        result = run_case(case, config, brief_dir, dry_run)
        results.append(result)

        if not dry_run:
            mark = "OK" if result.get("correct") else "MISS"
            print(" {} (expected={}, got={}, {:.1f}s)".format(
                mark,
                result.get("expected"),
                result.get("actual"),
                result.get("elapsed_s", 0),
            ))
        else:
            print(" (dry run)")

    return results


def save_results(config_name, results):
    """Save results to a JSONL file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outfile = RESULTS_DIR / "ab_{}_{}.jsonl".format(config_name, timestamp)
    with open(outfile, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print("\n  Results saved to {}".format(outfile))
    return outfile


def print_summary(config_name, results):
    """Print accuracy summary for a single config run."""
    total = len(results)
    correct = sum(1 for r in results if r.get("correct"))
    by_expected = {}
    for r in results:
        exp = r.get("expected", "?")
        if exp not in by_expected:
            by_expected[exp] = {"total": 0, "correct": 0}
        by_expected[exp]["total"] += 1
        if r.get("correct"):
            by_expected[exp]["correct"] += 1

    avg_time = sum(r.get("elapsed_s", 0) for r in results) / max(total, 1)
    total_cost = sum(r.get("cost_usd", 0) for r in results)
    total_in = sum(r.get("input_tokens", 0) for r in results)
    total_out = sum(r.get("output_tokens", 0) for r in results)

    print("\n  --- {} Summary ---".format(config_name))
    print("  Overall: {}/{} correct ({:.0%})".format(correct, total,
                                                      correct / max(total, 1)))
    for exp in ["Green", "Yellow", "Red"]:
        if exp in by_expected:
            b = by_expected[exp]
            print("    {}: {}/{} ({:.0%})".format(
                exp, b["correct"], b["total"],
                b["correct"] / max(b["total"], 1)))
    print("  Avg time per case: {:.1f}s".format(avg_time))
    print("  Total time: {:.0f}s".format(
        sum(r.get("elapsed_s", 0) for r in results)))
    print("  Tokens: {:,} in / {:,} out".format(total_in, total_out))
    print("  Cost: ${:.4f}".format(total_cost))


def compare_results(file_a, file_b):
    """Compare two result files side by side."""
    def load_results(path):
        results = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                results[r["case_id"]] = r
        return results

    a = load_results(file_a)
    b = load_results(file_b)
    name_a = Path(file_a).stem
    name_b = Path(file_b).stem

    all_ids = sorted(set(a.keys()) | set(b.keys()))

    print("\n=== Comparison: {} vs {} ===\n".format(name_a, name_b))
    print("{:<6} {:<10} {:<10} {:<10} {}".format(
        "Case", "Expected", name_a[:10], name_b[:10], "Cited Case"))
    print("-" * 80)

    correct_a = correct_b = 0
    disagreements = []
    for cid in all_ids:
        ra = a.get(cid, {})
        rb = b.get(cid, {})
        exp = ra.get("expected") or rb.get("expected", "?")
        aa = ra.get("actual", "-")
        ab = rb.get("actual", "-")

        if ra.get("correct"):
            correct_a += 1
        if rb.get("correct"):
            correct_b += 1

        marker = ""
        if aa != ab:
            marker = " <-- DIFFERENT"
            disagreements.append(cid)

        cited = ra.get("cited_case") or rb.get("cited_case", "")
        print("{:<6} {:<10} {:<10} {:<10} {}{}".format(
            cid, exp, aa or "-", ab or "-", cited[:35], marker))

    total = len(all_ids)
    time_a = sum(r.get("elapsed_s", 0) for r in a.values())
    time_b = sum(r.get("elapsed_s", 0) for r in b.values())

    print("\n--- Summary ---")
    print("{:<20} {:<15} {}".format("", name_a[:15], name_b[:15]))
    print("{:<20} {:<15} {}".format(
        "Accuracy",
        "{}/{} ({:.0%})".format(correct_a, total, correct_a / max(total, 1)),
        "{}/{} ({:.0%})".format(correct_b, total, correct_b / max(total, 1)),
    ))
    print("{:<20} {:<15} {}".format(
        "Total time",
        "{:.0f}s".format(time_a),
        "{:.0f}s".format(time_b),
    ))
    print("{:<20} {:<15} {}".format(
        "Avg time/case",
        "{:.1f}s".format(time_a / max(total, 1)),
        "{:.1f}s".format(time_b / max(total, 1)),
    ))
    print("\nDisagreements: {} of {} cases".format(len(disagreements), total))

    if disagreements:
        print("\nDisagreement details:")
        for cid in disagreements:
            ra = a.get(cid, {})
            rb = b.get(cid, {})
            print("  Case {}: {} says {}, {} says {}".format(
                cid, name_a, ra.get("actual"), name_b, rb.get("actual")))
            print("    Expected: {}".format(ra.get("expected")))
            print("    {}: {}".format(name_a, ra.get("rationale", "")[:100]))
            print("    {}: {}".format(name_b, rb.get("rationale", "")[:100]))


def main():
    parser = argparse.ArgumentParser(
        description="A/B test runner for verify-brief assessment phase")
    parser.add_argument("--config", nargs="+",
                        help="Config name(s) to run")
    parser.add_argument("--cases", default=str(CASES_FILE),
                        help="Test cases JSON file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show prompts without executing")
    parser.add_argument("--compare", nargs=2, metavar="FILE",
                        help="Compare two existing result files")

    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare[0], args.compare[1])
        return

    if not args.config:
        parser.error("Specify --config or --compare")

    configs = load_configs(CONFIGS_FILE)
    brief_name, cases = load_cases(args.cases)
    brief_dir = BRIEFS_DIR / brief_name

    print("Brief: {}".format(brief_name))
    print("Test cases: {}".format(len(cases)))
    print("Brief dir: {}".format(brief_dir))

    result_files = []
    for config_name in args.config:
        if config_name not in configs:
            print("Unknown config: {}. Available: {}".format(
                config_name, list(configs.keys())))
            sys.exit(1)

        config = configs[config_name]
        results = run_config(
            config_name, config, cases, brief_dir, args.dry_run)

        if not args.dry_run:
            outfile = save_results(config_name, results)
            result_files.append(outfile)
            print_summary(config_name, results)

    # Auto-compare if two configs were run
    if len(result_files) == 2:
        compare_results(str(result_files[0]), str(result_files[1]))


if __name__ == "__main__":
    main()
