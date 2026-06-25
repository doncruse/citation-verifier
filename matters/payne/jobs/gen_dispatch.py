import json, os

workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
jobs = json.load(open(os.path.join(workdir, "jobs", "assess.json"), encoding="utf-8"))
ddir = os.path.join(workdir, "jobs", "dispatch")
os.makedirs(ddir, exist_ok=True)
rdir = os.path.join(workdir, "jobs", "results")
os.makedirs(rdir, exist_ok=True)

for i, job in enumerate(jobs):
    pv = job["prompt_version"]
    cids = job["claim_ids"]
    out_path = os.path.join(rdir, "job_%02d.jsonl" % i)
    appendix = (
        "\n\n=== OUTPUT INSTRUCTIONS (follow exactly) ===\n"
        "This is a PACKED assess job covering these claim_ids: " + json.dumps(cids) + ".\n"
        "Your JSON response must contain a 'verdicts' array with one entry per claim_id above.\n"
        "After producing your JSON, write your results to THIS file (create it; it is yours alone, do not read or touch any other results file):\n"
        "  " + out_path + "\n"
        "Write ONE line PER entry of your verdicts array. Each line must be exactly this shape:\n"
        '  {"claim_id": "<that entry\'s claim_id>", "prompt_version": "' + pv + '", "model": "claude-opus-4-8", "fields": <that entry with its claim_id key removed>}\n'
        "Use ONLY the Read tool on files inside the workdir, plus writing your single results file above. "
        "No web search, no bash, no other tools. Do not rely on outside knowledge about any case.\n"
    )
    with open(os.path.join(ddir, "job_%02d.txt" % i), "w", encoding="utf-8") as f:
        f.write(job["prompt"] + appendix)

print("wrote", len(jobs), "dispatch files to", ddir)
print("claim counts per job:", [len(j["claim_ids"]) for j in jobs])
print("total claims:", sum(len(j["claim_ids"]) for j in jobs))
