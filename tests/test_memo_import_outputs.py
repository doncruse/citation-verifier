"""Additive output features for the memo-import integration (branch
memo-import/outputs). Three independent, downstream-read artifacts:

  1. Cache-dir override -- CITATION_VERIFIER_CACHE_DIR env var + --cache-dir
     CLI flag relocate .citation_cache.json and wire a persistent CL
     citation-lookup cache into the verify-propositions wave1/wave2 verifier.
     Default behavior unchanged (no cache dir set -> no pipeline caching).
  2. opinions/manifest.json -- per-opinion metadata written at download time.
  3. findings.json -- the report's per-claim data model, alongside report.html.

These files are read by downstream tools, so the tests pin stable keys.
"""
from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from citation_verifier.models import (
    FinalIds,
    ResolutionPathEntry,
    StageName,
    StageVerdict,
    Status,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _result(status, url="", case_name="", cluster_id=None):
    """Minimal v0.3 VerificationResult for these tests."""
    path = []
    if case_name:
        path.append(ResolutionPathEntry(
            stage=StageName.citation_lookup, query={},
            raw_response_summary={"case_name": case_name},
            verdict=StageVerdict.resolved, confidence=1.0,
            notes=None, elapsed_ms=0,
        ))
    return VerificationResult(
        citation_as_written=case_name or "test",
        parsed_citation=None,
        status=status,
        final_ids=FinalIds(
            cluster_id=cluster_id,
            opinion_id=None, docket_id=None, recap_document_id=None,
            absolute_url=url or None, text_source=None,
        ),
        resolution_path=path,
        warnings=[], gates_failed=[], timing={}, cache_hit=False,
    )


# ===========================================================================
# Feature 1: cache-dir override
# ===========================================================================

class TestCacheDirResolution:
    def test_default_is_none_when_unset(self, monkeypatch):
        from citation_verifier.cache import CACHE_DIR_ENV, resolve_cache_dir
        monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
        assert resolve_cache_dir() is None

    def test_env_var_resolves_to_path(self, monkeypatch, tmp_path):
        from citation_verifier.cache import CACHE_DIR_ENV, resolve_cache_dir
        monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path))
        assert resolve_cache_dir() == tmp_path

    def test_explicit_arg_overrides_env(self, monkeypatch, tmp_path):
        from citation_verifier.cache import CACHE_DIR_ENV, resolve_cache_dir
        monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "from_env"))
        got = resolve_cache_dir(str(tmp_path / "from_flag"))
        assert got == tmp_path / "from_flag"

    def test_citation_cache_path_default_unchanged(self):
        from citation_verifier.cache import (
            DEFAULT_CACHE_PATH, citation_cache_path,
        )
        # No cache dir -> the historical CWD-relative default, untouched.
        assert citation_cache_path(None) == DEFAULT_CACHE_PATH

    def test_citation_cache_path_under_dir(self, tmp_path):
        from citation_verifier.cache import citation_cache_path
        assert citation_cache_path(tmp_path) == tmp_path / ".citation_cache.json"

    def test_open_citation_cache_creates_dir_and_roundtrips(self, tmp_path):
        from citation_verifier.cache import open_citation_cache
        cache_dir = tmp_path / "nested" / "cachedir"
        cache = open_citation_cache(cache_dir)
        cache.put("Some Case, 1 U.S. 1", _result(Status.VERIFIED, "u", "Some Case"))
        # File landed under the requested dir, not CWD.
        assert (cache_dir / ".citation_cache.json").exists()
        # A fresh handle on the same dir reads it back.
        again = open_citation_cache(cache_dir)
        assert again.get("Some Case, 1 U.S. 1") is not None


class TestVerifyBatchCached:
    """The wave1/wave2 caching seam: serve verified hits from the cache,
    verify only misses, and persist only resolved (downloadable) results."""

    def _run(self, verifier, citations, cache, quick_only=True):
        from citation_verifier.proposition_pipeline import _verify_batch_cached
        return asyncio.run(_verify_batch_cached(
            verifier, citations, cache, quick_only=quick_only))

    def test_none_cache_passes_all_through(self):
        calls = []

        class V:
            async def verify_batch(self, cites, quick_only=False,
                                   progress_callback=None):
                calls.append(list(cites))
                return [_result(Status.NOT_FOUND) for _ in cites]

        out = self._run(V(), ["A", "B"], None)
        assert calls == [["A", "B"]]
        assert len(out) == 2

    def test_serves_cached_hits_and_verifies_only_misses(self, tmp_path):
        from citation_verifier.cache import open_citation_cache
        cache = open_citation_cache(tmp_path)
        cache.put("A", _result(Status.VERIFIED, "urlA", "Case A", cluster_id=1))

        calls = []

        class V:
            async def verify_batch(self, cites, quick_only=False,
                                   progress_callback=None):
                calls.append(list(cites))
                return [_result(Status.VERIFIED, "urlB", "Case B", cluster_id=2)
                        for _ in cites]

        out = self._run(V(), ["A", "B"], cache)
        # Only the uncached citation reached the verifier.
        assert calls == [["B"]]
        # Results returned in input order; A came from the cache.
        assert out[0].final_ids.absolute_url == "urlA"
        assert out[1].final_ids.absolute_url == "urlB"

    def test_stores_downloadable_but_not_misses(self, tmp_path):
        from citation_verifier.cache import open_citation_cache
        cache = open_citation_cache(tmp_path)

        class V:
            async def verify_batch(self, cites, quick_only=False,
                                   progress_callback=None):
                return [_result(Status.VERIFIED, "urlA", "Case A", cluster_id=1),
                        _result(Status.NOT_FOUND)]

        self._run(V(), ["A", "B"], cache)
        # Reopen to prove persistence to disk, not just in-memory state.
        fresh = open_citation_cache(tmp_path)
        assert fresh.get("A") is not None            # resolved -> cached
        assert fresh.get("B") is None                # miss -> not cached


class TestCacheDirWiring:
    def test_run_verify_builds_cache_under_dir(self, tmp_path):
        """run_verify(cache_dir=...) constructs a cache rooted at the dir and
        hands it to wave1/wave2."""
        from citation_verifier import proposition_pipeline as pp
        from citation_verifier.proposition_pipeline import (
            Wave1Result, Wave2Result,
        )
        wd = tmp_path / "wd"
        wd.mkdir()
        cache_dir = tmp_path / "cache"
        seen = {}

        async def fake_w1(workdir, citations, progress_callback=None,
                          cache=None):
            seen["cache"] = cache
            (workdir / "verification_results.csv").write_text(
                "citation,status\n", encoding="utf-8")
            return Wave1Result(results=[], miss_indices=[])

        async def fake_w2(workdir, citations, miss_indices,
                          progress_callback=None, cache=None):
            return Wave2Result(results=[])

        with patch.object(pp, "wave1_verify_and_download", fake_w1), \
                patch.object(pp, "wave2_fallback_and_download", fake_w2):
            asyncio.run(pp.run_verify(wd, citations=["X"], cache_dir=cache_dir))

        assert seen["cache"] is not None
        assert seen["cache"].path == cache_dir / ".citation_cache.json"

    def test_run_verify_no_cache_dir_means_no_cache(self, tmp_path):
        from citation_verifier import proposition_pipeline as pp
        from citation_verifier.proposition_pipeline import (
            Wave1Result, Wave2Result,
        )
        wd = tmp_path / "wd"
        wd.mkdir()
        seen = {}

        async def fake_w1(workdir, citations, progress_callback=None,
                          cache=None):
            seen["cache"] = cache
            (workdir / "verification_results.csv").write_text(
                "citation,status\n", encoding="utf-8")
            return Wave1Result(results=[], miss_indices=[])

        async def fake_w2(workdir, citations, miss_indices,
                          progress_callback=None, cache=None):
            return Wave2Result(results=[])

        with patch.object(pp, "wave1_verify_and_download", fake_w1), \
                patch.object(pp, "wave2_fallback_and_download", fake_w2):
            asyncio.run(pp.run_verify(wd, citations=["X"]))

        assert seen["cache"] is None

    def test_cli_verify_propositions_threads_cache_dir(self, tmp_path):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier import proposition_pipeline as pp
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / "claims.csv").write_text(
            "claim_id,cited_case\nx-01,\"A v. B, 1 U.S. 1\"\n", encoding="utf-8")
        captured = {}

        async def fake_run_verify(workdir, citations=None, force=False,
                                  progress_callback=None, cache_dir=None):
            captured["cache_dir"] = cache_dir
            return None

        with patch.object(pp, "run_verify", fake_run_verify):
            rc = verify_propositions_main(
                [str(wd), "verify", "--cache-dir", str(tmp_path / "cd")])
        assert rc == 0
        assert Path(captured["cache_dir"]) == tmp_path / "cd"

    def test_main_clear_cache_honors_cache_dir(self, tmp_path):
        from citation_verifier.__main__ import main
        from citation_verifier.cache import open_citation_cache
        cache = open_citation_cache(tmp_path)
        cache.put("A", _result(Status.VERIFIED, "u", "A"))
        target = tmp_path / ".citation_cache.json"
        assert target.exists()
        rc = main(["--cache-dir", str(tmp_path), "--clear-cache"])
        assert rc == 0
        # clear() removed the relocated file, proving --cache-dir was honored.
        assert not target.exists()


# ===========================================================================
# Feature 2: opinions/manifest.json
# ===========================================================================

def _meta(text, case_name, court="", date_filed="", fmt="text"):
    """Shape of client.get_opinion_text_with_metadata()."""
    return {"text": text, "case_name": case_name, "format": fmt,
            "citations": [], "court": court, "court_id": "",
            "date_filed": date_filed, "docket_number": ""}


def _run_wave1(tmp_path, citations, results, metas):
    from citation_verifier import proposition_pipeline as pp
    with patch.object(pp, "AsyncCourtListenerClient") as mock_client_cls, \
            patch.object(pp, "CitationVerifier") as mock_verifier_cls:
        mock_verifier_cls.return_value.verify_batch = AsyncMock(
            return_value=results)
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_opinion_text_with_metadata = AsyncMock(
            side_effect=metas)
        return asyncio.run(pp.wave1_verify_and_download(tmp_path, citations))


class TestOpinionManifest:
    def test_writes_manifest_keyed_by_stem_with_all_fields(self, tmp_path):
        from citation_verifier.proposition_pipeline import _sanitize_filename
        citations = ["Case A, 100 U.S. 1 (2000)", "Case B, 200 U.S. 2 (2001)"]
        results = [
            _result(Status.VERIFIED, "https://cl/opinion/11/a/", "Case A",
                    cluster_id=11),
            _result(Status.VERIFIED, "https://cl/opinion/22/b/", "Case B",
                    cluster_id=22),
        ]
        metas = [
            _meta("op A", "Case A", court="Supreme Court",
                  date_filed="2000-03-01"),
            _meta("op B", "Case B", court="Second Circuit",
                  date_filed="2001-06-15"),
        ]
        _run_wave1(tmp_path, citations, results, metas)

        manifest = json.loads(
            (tmp_path / "opinions" / "manifest.json").read_text(
                encoding="utf-8"))
        stem_a = _sanitize_filename("Case A")
        assert stem_a in manifest
        entry = manifest[stem_a]
        assert set(entry) == {
            "cluster_id", "case_name", "court", "date_filed", "citation",
            "absolute_url", "retrieved",
        }
        assert entry["cluster_id"] == 11
        assert entry["case_name"] == "Case A"
        assert entry["court"] == "Supreme Court"
        # date_filed is captured from the fetch, not re-derived.
        assert entry["date_filed"] == "2000-03-01"
        assert entry["citation"] == "Case A, 100 U.S. 1 (2000)"
        assert entry["absolute_url"] == "https://cl/opinion/11/a/"
        assert entry["retrieved"]  # non-empty ISO timestamp

    def test_manifest_only_lists_downloaded_opinions(self, tmp_path):
        from citation_verifier.proposition_pipeline import _sanitize_filename
        citations = ["Found, 1 U.S. 1 (2000)", "Missing, 2 U.S. 2 (2001)"]
        results = [
            _result(Status.VERIFIED, "https://cl/opinion/5/f/", "Found",
                    cluster_id=5),
            _result(Status.NOT_FOUND),
        ]
        metas = [_meta("op", "Found", date_filed="2000-01-01")]
        _run_wave1(tmp_path, citations, results, metas)

        manifest = json.loads(
            (tmp_path / "opinions" / "manifest.json").read_text(
                encoding="utf-8"))
        assert list(manifest) == [_sanitize_filename("Found")]

    def test_wave2_merges_into_existing_manifest(self, tmp_path):
        from citation_verifier import proposition_pipeline as pp
        from citation_verifier.proposition_pipeline import _sanitize_filename
        # Seed a manifest as if wave1 wrote one entry.
        opinions = tmp_path / "opinions"
        opinions.mkdir()
        (opinions / "manifest.json").write_text(
            json.dumps({_sanitize_filename("First"): {"cluster_id": 1}}),
            encoding="utf-8")

        citations = ["Second, 2 U.S. 2 (2001)"]
        results = [_result(Status.VERIFIED, "https://cl/opinion/9/s/",
                           "Second", cluster_id=9)]
        with patch.object(pp, "AsyncCourtListenerClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(
                return_value=False)
            mock_client.get_opinion_text_with_metadata = AsyncMock(
                return_value=_meta("op", "Second", date_filed="2001-01-01"))
            asyncio.run(pp.wave2_fallback_and_download(
                tmp_path, citations, [0]))

        manifest = json.loads(
            (opinions / "manifest.json").read_text(encoding="utf-8"))
        # Prior entry preserved AND the new one added (merge, not overwrite).
        assert _sanitize_filename("First") in manifest
        assert _sanitize_filename("Second") in manifest


# ===========================================================================
# Feature 3: findings.json
# ===========================================================================

_FINDINGS_COLUMNS = [
    "claim_id", "page", "proposition", "cited_case", "cl_url", "cl_status",
    "assessment", "opinion_file", "badge_label", "brief_block",
    "opinion_block", "finding_analysis", "quoted_text", "brief_sentence",
    "quote_check", "retrieved_case", "supporting_language",
]


def _findings_workdir(tmp_path, rows):
    wd = tmp_path / "wd"
    wd.mkdir()
    with (wd / "claims.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FINDINGS_COLUMNS)
        w.writeheader()
        for r in rows:
            base = {c: "" for c in _FINDINGS_COLUMNS}
            base.update(r)
            w.writerow(base)
    return wd


class TestFindingsJson:
    def _run(self, tmp_path, rows):
        from citation_verifier.proposition_pipeline import run_report
        wd = _findings_workdir(tmp_path, rows)
        run_report(wd)
        data = json.loads((wd / "findings.json").read_text(encoding="utf-8"))
        return wd, data

    def test_findings_json_emitted_alongside_report(self, tmp_path):
        wd, data = self._run(tmp_path, [
            {"claim_id": "c-01", "cited_case": "A v. B, 1 U.S. 1",
             "cl_status": "VERIFIED", "assessment": "Green",
             "opinion_file": "opinions/a.txt", "cl_url": "http://cl/1"},
        ])
        assert (wd / "report.html").exists()
        assert (wd / "findings.json").exists()
        assert [c["claim_id"] for c in data["claims"]] == ["c-01"]
        entry = data["claims"][0]
        assert set(entry) == {
            "claim_id", "lane", "severity", "badge_label",
            "brief_block", "opinion_block", "cl_url",
        }

    def test_green_claim_projection(self, tmp_path):
        _, data = self._run(tmp_path, [
            {"claim_id": "g", "cl_status": "VERIFIED", "assessment": "Green",
             "opinion_file": "opinions/a.txt", "cl_url": "http://cl/g",
             "brief_block": "BB", "opinion_block": "OB"},
        ])
        e = data["claims"][0]
        assert e["lane"] == "Green"
        assert e["severity"] == "green"
        assert e["badge_label"] == "Supported"
        assert e["brief_block"] == "BB"
        assert e["opinion_block"] == "OB"
        assert e["cl_url"] == "http://cl/g"

    def test_wrong_case_is_red_even_unassessed(self, tmp_path):
        _, data = self._run(tmp_path, [
            {"claim_id": "w", "cl_status": "WRONG_CASE", "assessment": ""},
        ])
        e = data["claims"][0]
        assert e["lane"] == "Red"
        assert e["severity"] == "red"

    def test_cite_unconfirmed_is_checkcite_orange(self, tmp_path):
        from citation_verifier.proposition_pipeline import (
            _STATUS_BADGE_FALLBACK,
        )
        _, data = self._run(tmp_path, [
            {"claim_id": "u", "cl_status": "CITE_UNCONFIRMED",
             "assessment": "Red", "opinion_file": "opinions/u.txt",
             "badge_label": "some agent badge"},
        ])
        e = data["claims"][0]
        assert e["lane"] == "CheckCite"
        assert e["severity"] == "orange"
        # Lane label wins over any agent badge for a Check Cite card.
        assert e["badge_label"] == _STATUS_BADGE_FALLBACK["CITE_UNCONFIRMED"]

    def test_gray_unlocatable_projection(self, tmp_path):
        _, data = self._run(tmp_path, [
            {"claim_id": "gr", "cl_status": "NOT_FOUND", "assessment": "",
             "opinion_file": ""},
        ])
        e = data["claims"][0]
        assert e["lane"] == "Gray"
        assert e["severity"] == "gray"

    def test_findings_json_matches_claims_order(self, tmp_path):
        _, data = self._run(tmp_path, [
            {"claim_id": "one", "cl_status": "VERIFIED", "assessment": "Red",
             "opinion_file": "opinions/a.txt"},
            {"claim_id": "two", "cl_status": "VERIFIED", "assessment": "Green",
             "opinion_file": "opinions/b.txt"},
            {"claim_id": "three", "cl_status": "NOT_FOUND"},
        ])
        assert [c["claim_id"] for c in data["claims"]] == \
            ["one", "two", "three"]
