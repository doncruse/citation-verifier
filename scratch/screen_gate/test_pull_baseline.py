"""Unit tests for the pure functions in pull_baseline.py.

Per task-4a brief: only the pure, deterministic, zero-network, zero-LLM
functions are unit-tested here. `pull_candidate` (network) is validated
in Task 4b.
"""
from pull_baseline import (classify_doctype, sanction_hits, slugify, doc_slug,
                           manifest_row)


# --- classify_doctype ---

def test_classify_merits_over_pleading():
    assert classify_doctype("Response in Opposition to Motion to Dismiss the Complaint") == "merits_brief"


def test_classify_bare_complaint_is_pleading():
    assert classify_doctype("Amended Complaint") == "pleading"


def test_classify_procedural():
    assert classify_doctype("Motion to Compel Discovery Responses") == "procedural_motion"


def test_classify_unknown_is_none():
    assert classify_doctype("Notice of Appearance") is None


def test_classify_handles_empty():
    assert classify_doctype("") is None


# --- sanction_hits ---

def test_sanction_hits_finds_terms():
    hits = sanction_hits(["Order to Show Cause re Sanctions", "Motion for Summary Judgment"])
    assert "sanction" in hits and "show cause" in hits


def test_sanction_hits_clean():
    assert sanction_hits(["Complaint", "Answer", "Motion to Compel"]) == []


def test_sanction_hits_dedup():
    assert sanction_hits(["sanction", "SANCTION again"]) == ["sanction"]


# --- slugify ---

def test_slugify_basic():
    assert slugify("Smith v. Jones Corporation, LLC") == "smith-v-jones-corporation-llc"


def test_slugify_caps_length():
    assert slugify("a b c d e f g h i") == "a-b-c-d-e-f"


def test_slugify_falls_back_to_docket():
    assert slugify("", "1:24-cv-00123") == "1-24-cv-00123"


def test_slugify_final_fallback():
    assert slugify("", "") == "doc"


# --- doc_slug (per-cell uniqueness via docket_id suffix) ---

def test_doc_slug_suffixes_docket_id():
    assert doc_slug("Smith v. Jones", "1:24-cv-1", 555) == "smith-v-jones-555"


def test_doc_slug_disambiguates_same_case_name():
    # two different dockets, identical case name -> distinct slugs
    a = doc_slug("Citizens for Responsibility and Ethics in Washington", "", 111)
    b = doc_slug("Citizens for Responsibility and Ethics in Washington", "", 222)
    assert a != b and a.endswith("-111") and b.endswith("-222")


# --- manifest_row ---

def test_manifest_row_shape():
    r = manifest_row(slug="x", court="cand", docket_id=1, document_number=2,
                     filer_type="attorney", doc_type="merits_brief",
                     recap_url="u", is_available=True, sanction_screen="clean")
    assert set(r) == {"slug", "court", "docket_id", "document_number", "filer_type",
                      "doc_type", "recap_url", "is_available", "sanction_screen", "notes"}
    assert r["notes"] == ""
