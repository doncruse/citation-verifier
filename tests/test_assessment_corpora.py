"""Structural invariants for the frozen assessment corpora (design SS7).

Each corpus is a conforming workdir: claims.csv (with stable claim_id),
opinions/, ground_truth.csv, jobs/assess_results.jsonl. These tests are
offline and run against committed data only.
"""
import csv
from pathlib import Path

import pytest

from citation_verifier.executor import load_verdicts_jsonl

CORPORA = Path(__file__).parent / "data" / "assessment_corpora"
PROMPT_VERSION = "assess-v1"
CORPUS_NAMES = ["withers", "payne", "wainwright"]

# Claims in these states never get an agent verdict (deterministic lanes).
LOCATED = {"VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
           "VERIFIED_DOCKET_ONLY", "CITE_UNCONFIRMED"}


def load_claims(name):
    path = CORPORA / name / "claims.csv"
    return list(csv.DictReader(path.open(encoding="utf-8")))


def load_ground_truth(name):
    path = CORPORA / name / "ground_truth.csv"
    return list(csv.DictReader(path.open(encoding="utf-8")))


@pytest.mark.parametrize("name", CORPUS_NAMES)
class TestCorpusStructure:
    def test_files_exist(self, name):
        d = CORPORA / name
        assert (d / "claims.csv").is_file()
        assert (d / "ground_truth.csv").is_file()
        assert (d / "jobs" / "assess_results.jsonl").is_file()
        assert (d / "opinions").is_dir()

    def test_claim_ids_unique_and_prefixed(self, name):
        ids = [c["claim_id"] for c in load_claims(name)]
        assert len(ids) == len(set(ids))
        assert all(i.startswith(name + "-") for i in ids)

    def test_opinion_files_exist(self, name):
        d = CORPORA / name
        for c in load_claims(name):
            if c.get("opinion_file"):
                assert (d / c["opinion_file"]).is_file(), c["claim_id"]

    def test_ground_truth_covers_all_claims(self, name):
        gt_ids = {g["claim_id"] for g in load_ground_truth(name)}
        for c in load_claims(name):
            assert c["claim_id"] in gt_ids

    def test_cassette_covers_agent_assessable_claims(self, name):
        verdicts = load_verdicts_jsonl(
            CORPORA / name / "jobs" / "assess_results.jsonl")
        assert all(v.prompt_version == PROMPT_VERSION for v in verdicts)
        assert all(v.fields.get("assessment") in ("Green", "Yellow", "Red")
                   for v in verdicts)
        recorded = {v.claim_id for v in verdicts}
        for c in load_claims(name):
            needs_agent = (bool(c.get("opinion_file"))
                           and c.get("cl_status") != "WRONG_CASE")
            if needs_agent:
                assert c["claim_id"] in recorded, c["claim_id"]


class TestWithersSpecifics:
    def test_row_counts(self):
        assert len(load_claims("withers")) == 34
        assert len(load_ground_truth("withers")) == 54  # full exhibit

    def test_ground_truth_scale_and_labels(self):
        gt = load_ground_truth("withers")
        assert all(g["scale"] == "withers_exhibit" for g in gt)
        labels = {g["expected"] for g in gt}
        assert labels == {"green", "yellow", "red"}
