# Proposition-Verifier Step 6: crosscheck + triage Verbs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land design §10 step 6: the deterministic `crosscheck` verb (§6.5: TOA-vs-body diff, court check, pincite check — flags, never verdicts) and the `triage` verb (§6.7: `triage_track` full|fast per claim + Haiku prescreen wired through the executor, default OFF), plus the prerequisite matched-court persistence from verify and the missing `check-quotes` CLI verb.

**Architecture:** The matched court rides for free on the opinion download — `get_opinion_text_with_metadata` already fetches the docket→court chain for every downloaded opinion and discards it; we add `court_id` to its return dicts, stash `matched_court`/`matched_court_id` into the resolving stage's `raw_response_summary` in `_download_opinion` (the same pattern as the sibling-swap `case_name` stash), surface them via accessors on `VerificationResult` mirroring `matched_case_name` (the §11-bug-1 lesson: never read stage keys directly), and persist them as two new `verification_results.csv` columns. `crosscheck` then compares cited vs matched court IDs via `lookup_court_id`, diffs the extract verb's TOA/body citation lists, and best-effort-checks pincites against star pagination and footnote existence in the downloaded opinion text — writing a `crosscheck_flags` JSON column. `triage` derives `triage_track` deterministically from quote-check + crosscheck + status columns (the SKILL Phase 2a rules minus the two LLM judgments), and when `prescreen=True` emits per-claim Haiku summary-hint jobs through the same executor protocol (new `prescreen-v1` template, results into `prescreen_hint`).

**Tech stack:** stdlib only (csv, json, re); existing `parse_citation`/`lookup_court_id`/`_normalize_for_match`; executor protocol from Step 4/5. Tests: pytest, offline, synthetic workdirs + tmp copies of the frozen Withers corpus.

**Source facts (verified this session):**
- Citation-lookup clusters carry **no court field** (verified against `benchmark_cassette.json.gz`: keys are case_name/docket/docket_id/..., no court) — the download-time stash is the only no-new-API-call source. NOT_FOUND/WRONG_CASE rows get no court, which is fine: the court check only applies to verified matches.
- `client.py` metadata returns already compute `court_id` internally (e.g. sync cluster path line ~519: `court_id = court_url.rstrip("/").split("/")[-1]`) before fetching `full_name`; they return `"court": court_name` only. Four return-dict families: sync/async × (docket path, cluster path), plus PDF-fallback dicts with `"court": ""`.
- `_download_opinion` (proposition_pipeline.py ~386) fetches `data = await client.get_opinion_text_with_metadata(...)` and already mutates `result.resolution_path[-1].raw_response_summary["case_name"]` on sibling swap — the stash precedent.
- `VerificationResult.matched_case_name` (models.py ~300) walks `resolution_path` in reverse over `_MATCHED_NAME_KEYS`; the new accessors mirror it.
- `_VR_FIELDS` (proposition_pipeline.py ~205) = citation, status, confidence, cl_url, matched_name, diagnostics_cat, diagnostics_msg, syllabus. Tests pinning this header: `test_proposition_pipeline.py:130-133` and `:298-302` (update both); `test_brief_pipeline.py` writes legacy-format CSVs as *inputs* only (DictReader tolerates missing columns — no changes there).
- `check_quotes` exists with floors (Step 3) but the `verify-propositions` CLI has no `check-quotes` verb — gap closed here (it sits between merge and crosscheck in §3, and triage reads its columns).
- SKILL Phase 2a triage rules — full track: quote_check_worst FABRICATED/CLOSE, metadata flags, syllabus topic mismatch (LLM — out of deterministic scope), has quoted_text, lead authority (LLM — out of scope). Fast track: NO_QUOTES/VERBATIM + no flags.
- Prescreen prior data (§6.7): 76% exact, ~15× cheaper; ship wired, **default OFF** until the A/B re-run. The assess-v1 template is byte-pinned and cannot consume `prescreen_hint` — hints are recorded for assess-v2 (noted in Subsequent steps).
- Opinion text loading: `check_quotes` strips HTML inline (`re.sub(r"<[^>]+>", " ", raw)` + entity/whitespace collapse). crosscheck gets its own small helper with the same strip; `check_quotes` is left untouched (floor-calibrated path).
- `ParsedCitation.court` is the cited court (abbrev or CL id); `lookup_court_id` accepts both and returns CL id or None (federal map only — state cites return None and the court check skips, best-effort per design).

**Scope notes:**
- Pincite/footnote checks produce *flags only* and never touch colors (§6.5: "feeds triage and the report, never the color function directly").
- `assess` does not yet consume `triage_track` (fast-track Haiku confirmation is assess-v2 work — Subsequent steps).
- No live calls anywhere in this step.

---

### Task 1: Matched-court persistence (client → download stash → accessors → CSV)

**Files:**
- Modify: `src/citation_verifier/client.py` (metadata return dicts, sync + async)
- Modify: `src/citation_verifier/models.py` (accessors after `matched_case_name`)
- Modify: `src/citation_verifier/proposition_pipeline.py` (`_download_opinion` stash; `_VR_FIELDS` + writer)
- Test: `tests/test_proposition_pipeline.py` (accessors + CSV columns), existing header-pinning tests at :130-133 and :298-302 updated

- [x] **1.1 Write the failing tests** — append to `tests/test_proposition_pipeline.py`:

```python
class TestMatchedCourtAccessors:
    def test_matched_court_from_download_stash(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Doe v. Memphis",
                             "matched_court": "United States Court of "
                                              "Appeals for the Sixth Circuit",
                             "matched_court_id": "ca6"})])
        assert r.matched_court.endswith("Sixth Circuit")
        assert r.matched_court_id == "ca6"

    def test_later_stage_supersedes(self):
        r = _result([
            _entry(StageName.citation_lookup, {"matched_court_id": "ca5"}),
            _entry(StageName.opinion_search, {"matched_court_id": "ca6"}),
        ])
        assert r.matched_court_id == "ca6"

    def test_empty_when_no_stage_recorded_court(self):
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "X v. Y"})])
        assert r.matched_court == ""
        assert r.matched_court_id == ""
```

And extend the existing `_write_verification_csv` column test (the test at ~:125-145 asserting the header list): add `"matched_court", "matched_court_id"` to the expected fieldnames and, in the row-content assertion block at ~:298-302, the same. Also add one new test:

```python
class TestVerificationCsvCourtColumns:
    def test_matched_court_columns_written(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        r = _result([_entry(StageName.citation_lookup,
                            {"matched_case_name": "Doe v. Memphis",
                             "matched_court": "Sixth Circuit",
                             "matched_court_id": "ca6"})])
        pp._write_verification_csv(tmp_path, ["Doe v. Memphis, 1 F.3d 1"],
                                   [r])
        with open(tmp_path / "verification_results.csv", newline="",
                  encoding="utf-8") as f:
            (row,) = list(csv.DictReader(f))
        assert row["matched_court"] == "Sixth Circuit"
        assert row["matched_court_id"] == "ca6"
```

- [x] **1.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k "MatchedCourt or CourtColumns"`
Expected: FAIL — `VerificationResult` has no attribute `matched_court`

- [x] **1.3 Implement models.py accessors** — insert after `matched_case_name` (before the `_MATCHED_NAME_KEYS` constant):

```python
    @property
    def matched_court(self) -> str:
        """Matched court full name, stashed at opinion-download time
        (proposition_pipeline._download_opinion) -- mirrors
        matched_case_name: the accessor is the only sanctioned read
        surface for stage-summary keys (design SS11 bug 1 lesson)."""
        for entry in reversed(self.resolution_path):
            value = entry.raw_response_summary.get("matched_court")
            if value:
                return value
        return ""

    @property
    def matched_court_id(self) -> str:
        """Matched CL court id (e.g. 'ca6'), stashed at download time.
        Empty for results that never reached download (NOT_FOUND,
        WRONG_CASE) -- the crosscheck court check skips those."""
        for entry in reversed(self.resolution_path):
            value = entry.raw_response_summary.get("matched_court_id")
            if value:
                return value
        return ""
```

- [x] **1.4 Implement client.py court_id** — in BOTH sync and async clients, every metadata return dict that has a `"court"` key gains a `"court_id"` key. Pattern for the docket path and cluster path (the court id is already computed; hoist it):

```python
            court_name = ""
            court_id = ""
            ...
                    court_url = docket.get("court", "")
                    if court_url:
                        court_id = court_url.rstrip("/").split("/")[-1]
                        court_data = self._request_with_retry(
                            "GET", f"{self.BASE_URL}/courts/{court_id}/",
                        )
                        court_name = court_data.json().get("full_name", "")
            ...
            return {
                ...
                "court": court_name,
                "court_id": court_id,
                ...
            }
```

Find every site with `Grep '"court":' src/citation_verifier/client.py -n` (6 sites as of this writing: sync docket ~425, sync PDF-fallback ~485, sync cluster ~531, async docket ~882, async PDF-fallback ~942, async cluster). PDF-fallback dicts get `"court_id": ""`. The async client reads JSON via awaited dicts (`court_data.get(...)` not `.json()`) — keep each site's existing idiom, only hoist/emit `court_id`.

- [x] **1.5 Implement the download stash** — in `proposition_pipeline._download_opinion`, after the sibling-swap block (so the swapped sibling's court wins) and before the `fmt = data.get(...)` line:

```python
        # Stash the matched court (design SS6.5 court check). The metadata
        # fetch already walked cluster->docket->court; persisting it here
        # is the only no-extra-API-call source (citation-lookup clusters
        # carry no court field). Same stash pattern as the sibling-swap
        # case_name above; surfaced via VerificationResult.matched_court.
        if result.resolution_path:
            _summ = result.resolution_path[-1].raw_response_summary
            if data.get("court"):
                _summ["matched_court"] = data["court"]
            if data.get("court_id"):
                _summ["matched_court_id"] = data["court_id"]
```

- [x] **1.6 Implement the CSV columns** — `_VR_FIELDS` becomes:

```python
_VR_FIELDS = [
    "citation", "status", "confidence", "cl_url",
    "matched_name", "matched_court", "matched_court_id",
    "diagnostics_cat", "diagnostics_msg",
    "syllabus",
]
```

and the `writer.writerow({...})` dict gains:

```python
                "matched_court": result.matched_court,
                "matched_court_id": result.matched_court_id,
```

Update the two header-pinning tests in `test_proposition_pipeline.py` (:130-133, :298-302) to the new column list.

- [x] **1.7 Run the suites**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py tests/test_brief_pipeline.py tests/test_verifier.py tests/test_client_html.py -q`
Expected: all PASS (merge reads vr CSVs by DictReader — extra columns are additive; legacy corpora CSVs without the columns still load because consumers use `.get`)

- [x] **1.8 Commit**

```bash
git add src/citation_verifier/client.py src/citation_verifier/models.py src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: persist matched court from verify -- client court_id, download stash, accessors, vr CSV columns (SS6.5 prereq)"
```

### Task 2: `run_check_quotes` wrapper + `check-quotes` CLI verb (gap closure)

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (thin wrapper near the other `run_*` verbs)
- Modify: `src/citation_verifier/__main__.py` (verb choices + dispatch)
- Test: `tests/test_proposition_pipeline.py`

- [x] **2.1 Write the failing tests:**

```python
class TestRunCheckQuotes:
    def test_wrapper_stamps_run_json(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _copy_withers(tmp_path)
        stats = pp.run_check_quotes(wd)
        assert stats.total_claims > 0
        run = json.loads((wd / "run.json").read_text(encoding="utf-8"))
        assert "check-quotes" in run["verbs"]

    def test_cli_check_quotes_verb(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import QuoteCheckStats
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_check_quotes",
            lambda wd: QuoteCheckStats(total_claims=3, verbatim=2))
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "check-quotes"])
        assert rc == 0
        assert "[OK] check-quotes" in capsys.readouterr().out
```

(`_copy_withers` already exists in the test module. `QuoteCheckStats` is the existing dataclass — check its field names with `Grep 'class QuoteCheckStats' -A 8`; adjust the fake's kwargs to two real fields if `verbatim` isn't one.)

- [x] **2.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunCheckQuotes`
Expected: FAIL — `run_check_quotes` undefined

- [x] **2.3 Implement the wrapper** (place after `run_merge`):

```python
def run_check_quotes(workdir: Path) -> QuoteCheckStats:
    """Verb 3 (design SS3): deterministic quote verdicts + SS6.4 floors.
    Thin wrapper over check_quotes adding the run.json stamp."""
    workdir = Path(workdir)
    stats = check_quotes(workdir)
    _update_run_json(workdir, "check-quotes",
                     total=stats.total_claims)
    return stats
```

- [x] **2.4 Implement the CLI verb** — in `verify_propositions_main`: add `"check-quotes"` to choices (after `"merge"`); in `_dispatch_proposition_verbs`, after the merge block:

```python
    if args.verb in ("check-quotes", "full"):
        qstats = pp.run_check_quotes(workdir)
        print(f"[OK] check-quotes: {qstats.total_claims} claims checked")
```

- [x] **2.5 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunCheckQuotes`
Expected: PASS

- [x] **2.6 Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py src/citation_verifier/__main__.py tests/test_proposition_pipeline.py
git commit -m "feat: check-quotes verb in the propositions CLI (SS3 verb 3 gap)"
```

### Task 3: `crosscheck` verb (§6.5)

**Files:**
- Modify: `src/citation_verifier/proposition_pipeline.py` (verb + helpers after `run_check_quotes`)
- Test: `tests/test_proposition_pipeline.py`

- [x] **3.1 Write the failing tests:**

```python
def _crosscheck_workdir(tmp_path):
    """Synthetic workdir: 2 claims, vr CSV with matched court, one
    opinion file with star pagination + footnotes, TOA/body lists with
    one volume discrepancy (the Bryant class)."""
    wd = tmp_path / "xc"
    wd.mkdir()
    (wd / "opinions").mkdir()
    (wd / "opinions" / "tompkins.txt").write_text(
        "*770 Start of opinion. The court held things. *775 More text "
        "here including footnote n.3 discussion. *787 The evidence must "
        "be relevant to a consequential fact. *790 End.",
        encoding="utf-8")
    with open(wd / "claims.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "claim_id", "page", "proposition", "cited_for", "cited_case",
            "quoted_text", "brief_sentence", "cl_status", "cl_url",
            "opinion_file"])
        w.writeheader()
        w.writerow({
            "claim_id": "xc-01", "page": "3",
            "proposition": "Settlement evidence is irrelevant.",
            "cited_case": "Tompkins v. Cyr, 202 F.3d 770, 787 "
                          "(5th Cir. 2000)",
            "quoted_text": "[]", "cl_status": "VERIFIED",
            "opinion_file": "opinions/tompkins.txt"})
        w.writerow({
            "claim_id": "xc-02", "page": "5",
            "proposition": "Out-of-range pinpoint and bad footnote.",
            "cited_case": "Tompkins v. Cyr, 202 F.3d 770, 999 "
                          "(6th Cir. 2000) n.42",
            "quoted_text": "[]", "cl_status": "VERIFIED",
            "opinion_file": "opinions/tompkins.txt"})
    with open(wd / "verification_results.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "citation", "status", "confidence", "cl_url", "matched_name",
            "matched_court", "matched_court_id", "diagnostics_cat",
            "diagnostics_msg", "syllabus"])
        w.writeheader()
        for cite in ("Tompkins v. Cyr, 202 F.3d 770, 787 (5th Cir. 2000)",
                     "Tompkins v. Cyr, 202 F.3d 770, 999 (6th Cir. 2000) "
                     "n.42"):
            w.writerow({"citation": cite, "status": "VERIFIED",
                        "confidence": "1.00",
                        "matched_name": "Tompkins v. Cyr",
                        "matched_court": "Fifth Circuit",
                        "matched_court_id": "ca5"})
    (wd / "citations_toa.txt").write_text(
        "Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)\n"
        "Bryant v. Jones, 597 F.3d 1320 (11th Cir. 2010)\n",
        encoding="utf-8")
    (wd / "citations_body.txt").write_text(
        "Tompkins v. Cyr, 202 F.3d 770 (5th Cir. 2000)\n"
        "Bryant v. Jones, 97 F.3d 1320 (11th Cir. 2010)\n",
        encoding="utf-8")
    return wd


class TestRunCrosscheck:
    def test_clean_claim_gets_empty_flags(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _crosscheck_workdir(tmp_path)
        stats = pp.run_crosscheck(wd)
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        assert rows["xc-01"]["crosscheck_flags"] == ""
        assert stats.total == 2

    def test_court_mismatch_flagged(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _crosscheck_workdir(tmp_path)
        pp.run_crosscheck(wd)
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        flags = json.loads(rows["xc-02"]["crosscheck_flags"])
        assert flags["court_mismatch"]["cited_id"] == "ca6"
        assert flags["court_mismatch"]["matched_id"] == "ca5"

    def test_pincite_out_of_star_range_flagged(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _crosscheck_workdir(tmp_path)
        pp.run_crosscheck(wd)
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        flags = json.loads(rows["xc-02"]["crosscheck_flags"])
        assert flags["pincite_flag"]["pinpoint"] == "999"
        assert flags["pincite_flag"]["star_range"] == [770, 790]

    def test_footnote_missing_flagged_and_present_not(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = _crosscheck_workdir(tmp_path)
        pp.run_crosscheck(wd)
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        flags2 = json.loads(rows["xc-02"]["crosscheck_flags"])
        assert flags2["pincite_flag"]["footnote_missing"] == "42"
        # xc-01 has no footnote pincite -> no flag at all
        assert rows["xc-01"]["crosscheck_flags"] == ""

    def test_toa_body_mismatch_flagged_on_matching_claims(self, tmp_path):
        """Bryant 597-vs-97 class: the mismatch is recorded on claims
        citing Bryant; Tompkins (consistent) claims stay clean."""
        import citation_verifier.proposition_pipeline as pp
        wd = _crosscheck_workdir(tmp_path)
        # add a Bryant claim
        with open(wd / "claims.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            fields = rows[0].keys()
        bryant = dict.fromkeys(fields, "")
        bryant.update({"claim_id": "xc-03",
                       "proposition": "Something about Bryant.",
                       "cited_case": "Bryant v. Jones, 597 F.3d 1320 "
                                     "(11th Cir. 2010)",
                       "quoted_text": "[]", "cl_status": "VERIFIED"})
        rows.append(bryant)
        with open(wd / "claims.csv", "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            w.writerows(rows)
        stats = pp.run_crosscheck(wd)
        out = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        flags = json.loads(out["xc-03"]["crosscheck_flags"])
        variants = flags["toa_mismatch"]["variants"]
        assert any("597 F.3d" in v for v in variants)
        assert any("97 F.3d" in v for v in variants)
        assert "toa_mismatch" not in (
            json.loads(out["xc-01"]["crosscheck_flags"])
            if out["xc-01"]["crosscheck_flags"] else {})
        assert stats.toa_mismatches >= 1

    def test_tolerates_missing_inputs(self, tmp_path):
        """Prepared-pairs workdir: no TOA/body lists, legacy vr CSV
        without matched_court columns -> runs clean, flags empty."""
        import citation_verifier.proposition_pipeline as pp
        wd = tmp_path / "bare"
        wd.mkdir()
        with open(wd / "claims.csv", "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "claim_id", "proposition", "cited_case", "quoted_text"])
            w.writeheader()
            w.writerow({"claim_id": "b-01", "proposition": "P.",
                        "cited_case": "A v. B, 1 F.3d 1 (1st Cir. 1990)",
                        "quoted_text": "[]"})
        stats = pp.run_crosscheck(wd)
        assert stats.total == 1
        rows = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert rows[0]["crosscheck_flags"] == ""

    def test_runs_on_withers_corpus_copy(self, tmp_path):
        """Corpus tolerance: the frozen Withers workdir (no TOA lists,
        pre-court vr CSV) crosschecks without error and every claim
        gets a crosscheck_flags cell (possibly empty)."""
        import citation_verifier.proposition_pipeline as pp
        wd = _copy_withers(tmp_path)
        stats = pp.run_crosscheck(wd)
        rows = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert stats.total == len(rows)
        assert all("crosscheck_flags" in r for r in rows)
```

- [x] **3.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunCrosscheck`
Expected: FAIL — `run_crosscheck` undefined

- [x] **3.3 Implement** (after `run_check_quotes`; needs `from .court_map import lookup_court_id` and `from .parser import parse_citation` — import inside the verb like the executor imports, to keep module import light):

```python
_BASE_CITE_RE = re.compile(
    r"^(?P<name>.+?),\s*(?P<vol>\d+)\s+"
    r"(?P<rep>[A-Z][A-Za-z0-9. ']*?)\s+(?P<page>\d+)")
_CITE_YEAR_RE = re.compile(r"\((?:[^()]*?\s)?(\d{4})\)")
_PIN_AFTER_BASE_RE = re.compile(r"^\s*,\s*(\d+)")
_FOOTNOTE_PIN_RE = re.compile(r"\bn\.\s*(\d+)", re.IGNORECASE)
_STAR_PAGE_RE = re.compile(r"\*\s?(\d{1,5})\b")


def _parse_base_cite(text: str) -> dict[str, str] | None:
    """Volume/reporter/page/year + normalized case name from a citation
    string. Regex-level parse (the SS6.5 diff needs components, not a
    full ParsedCitation)."""
    m = _BASE_CITE_RE.match(text.strip())
    if not m:
        return None
    year = _CITE_YEAR_RE.search(text)
    return {
        "name_norm": re.sub(r"[^a-z0-9]", "", m.group("name").lower()),
        "volume": m.group("vol"),
        "reporter": re.sub(r"[\s.]", "", m.group("rep")).lower(),
        "page": m.group("page"),
        "year": year.group(1) if year else "",
        "_end": str(m.end()),
    }


def _toa_body_variants(workdir: Path) -> dict[str, list[str]]:
    """name_norm -> distinct citation variants across the TOA/body lists
    (only names with >1 variant -- the Bryant 597-vs-97 class)."""
    seen: dict[str, dict[tuple, str]] = {}
    for fname in ("citations_toa.txt", "citations_body.txt"):
        p = workdir / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            c = _parse_base_cite(line)
            if not c:
                continue
            key = (c["volume"], c["reporter"], c["page"])
            seen.setdefault(c["name_norm"], {}).setdefault(key, line)
    return {name: list(variants.values())
            for name, variants in seen.items() if len(variants) > 1}


def _read_clean_opinion(workdir: Path, opinion_file: str) -> str:
    """Opinion text with HTML stripped (same strip as check_quotes)."""
    try:
        raw = (workdir / opinion_file).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"&\w+;", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _pincite_flag(cited_case: str, opinion_text: str) -> dict | None:
    """Best-effort SS6.5 pincite check: star-pagination range + footnote
    existence. Returns a details dict or None. Flags only -- never
    feeds the color function."""
    base = _parse_base_cite(cited_case)
    if not base or not opinion_text:
        return None
    flag: dict[str, Any] = {}
    rest = cited_case.strip()[int(base["_end"]):]
    pin_m = _PIN_AFTER_BASE_RE.match(rest)
    if pin_m:
        pin = int(pin_m.group(1))
        stars = [int(s) for s in _STAR_PAGE_RE.findall(opinion_text)]
        # >=3 markers = real star pagination, not stray asterisks
        if len(stars) >= 3:
            lo, hi = min(stars), max(stars)
            if not (lo <= pin <= hi):
                flag["pinpoint"] = str(pin)
                flag["star_range"] = [lo, hi]
    fn_m = _FOOTNOTE_PIN_RE.search(cited_case)
    if fn_m:
        fn = fn_m.group(1)
        if not re.search(
                rf"(?:n\.\s*{fn}\b|footnote\s+{fn}\b|\[fn?{fn}\])",
                opinion_text, re.IGNORECASE):
            flag["footnote_missing"] = fn
    return flag or None


@dataclass
class CrosscheckStats:
    """Statistics from run_crosscheck."""
    total: int = 0
    toa_mismatches: int = 0
    court_mismatches: int = 0
    pincite_flags: int = 0


def run_crosscheck(workdir: Path) -> CrosscheckStats:
    """Verb 4 (design SS3 / SS6.5): deterministic TOA-vs-body diff,
    court check, and best-effort pincite check. Writes the
    crosscheck_flags JSON column ('' when clean). Flags only: never
    touches assessment colors. Idempotent -- recomputes on rerun."""
    from .court_map import lookup_court_id
    from .parser import parse_citation

    workdir = Path(workdir)
    with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    variants = _toa_body_variants(workdir)

    # citation -> vr row (for matched_court_id), same join key as merge
    vr_lookup: dict[str, dict] = {}
    vr_path = workdir / "verification_results.csv"
    if vr_path.exists():
        with open(vr_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = _normalize_for_match(row.get("citation", ""))
                if key:
                    vr_lookup[key] = row

    stats = CrosscheckStats()
    opinion_cache: dict[str, str] = {}
    for claim in claims:
        stats.total += 1
        cited = claim.get("cited_case", "") or ""
        flags: dict[str, Any] = {}

        # 1. TOA vs body (SS6.5 bullet 1)
        base = _parse_base_cite(cited)
        if base and base["name_norm"] in variants:
            flags["toa_mismatch"] = {
                "variants": variants[base["name_norm"]]}

        # 2. Court check (SS6.5 bullet 2): cited vs matched CL court id.
        # Skips when either side is unknown (state courts, legacy vr
        # CSVs without matched_court_id, unparseable cites) -- best
        # effort by design.
        vr_row = vr_lookup.get(_normalize_for_match(cited), {})
        matched_id = (vr_row.get("matched_court_id") or "").strip()
        if matched_id:
            try:
                parsed = parse_citation(cited)
            except Exception:
                parsed = None
            cited_court = getattr(parsed, "court", None)
            cited_id = lookup_court_id(cited_court) if cited_court else None
            if cited_id and cited_id != matched_id:
                stats.court_mismatches += 1
                flags["court_mismatch"] = {
                    "cited": cited_court,
                    "cited_id": cited_id,
                    "matched_id": matched_id,
                    "matched": vr_row.get("matched_court", ""),
                }

        # 3. Pincite check (SS6.5 bullet 3, best-effort flags)
        opinion_file = claim.get("opinion_file", "") or ""
        if opinion_file:
            if opinion_file not in opinion_cache:
                opinion_cache[opinion_file] = _read_clean_opinion(
                    workdir, opinion_file)
            pin = _pincite_flag(cited, opinion_cache[opinion_file])
            if pin:
                stats.pincite_flags += 1
                flags["pincite_flag"] = pin

        if "toa_mismatch" in flags:
            stats.toa_mismatches += 1
        claim["crosscheck_flags"] = (
            json_mod.dumps(flags, ensure_ascii=False) if flags else "")

    fields = list(claims[0].keys()) if claims else ["crosscheck_flags"]
    if "crosscheck_flags" not in fields:
        fields.append("crosscheck_flags")
    for c in claims:
        c.setdefault("crosscheck_flags", "")
    with open(workdir / "claims.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(claims)

    _update_run_json(workdir, "crosscheck", total=stats.total,
                     toa=stats.toa_mismatches,
                     court=stats.court_mismatches,
                     pincite=stats.pincite_flags)
    return stats
```

Note on `test_footnote_missing_flagged_and_present_not`: xc-02's pinpoint flag and footnote flag share the one `pincite_flag` dict (pinpoint 999 out of range AND n.42 missing). xc-01 cites no footnote and pin 787 is inside [770, 790] — clean.

- [x] **3.4 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunCrosscheck`
Expected: PASS. If `parse_citation("Tompkins v. Cyr, 202 F.3d 770, 999 (6th Cir. 2000) n.42")` doesn't yield court "6th Cir." (check by running it directly), adjust the synthetic cite format in the fixture to one the parser handles (e.g. drop the trailing ` n.42` into the pin: `"...770, 999 n.42 (6th Cir. 2000)"`) — record the working form in Execution notes.

- [x] **3.5 Commit**

```bash
git add src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: crosscheck verb -- TOA/body diff, court check, pincite flags (SS6.5)"
```

### Task 4: `triage` verb + prescreen-v1 template (§6.7)

**Files:**
- Create: `src/citation_verifier/prompts/prescreen_v1.md`
- Modify: `src/citation_verifier/proposition_pipeline.py` (verb after `run_crosscheck`; `PRESCREEN_PROMPT_VERSION` near the other version constants)
- Test: `tests/test_proposition_pipeline.py`

- [x] **4.1 Write the failing tests:**

```python
def _triage_claims(wd, rows):
    fields = ["claim_id", "proposition", "cited_case", "quoted_text",
              "cl_status", "opinion_file", "quote_check_worst",
              "quote_floor", "crosscheck_flags"]
    with open(wd / "claims.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            base = dict.fromkeys(fields, "")
            base.update(r)
            w.writerow(base)


class TestRunTriage:
    def _wd(self, tmp_path):
        wd = tmp_path / "tr"
        wd.mkdir()
        (wd / "opinions").mkdir()
        (wd / "opinions" / "a.txt").write_text("short opinion",
                                               encoding="utf-8")
        return wd

    def test_tracks_assigned_deterministically(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = self._wd(tmp_path)
        _triage_claims(wd, [
            # clean verified, no quotes -> fast
            {"claim_id": "t-01", "cl_status": "VERIFIED",
             "opinion_file": "opinions/a.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES"},
            # CLOSE quote -> full
            {"claim_id": "t-02", "cl_status": "VERIFIED",
             "opinion_file": "opinions/a.txt", "quoted_text": "[]",
             "quote_check_worst": "CLOSE"},
            # has quoted text -> full
            {"claim_id": "t-03", "cl_status": "VERIFIED",
             "opinion_file": "opinions/a.txt",
             "quoted_text": '["some quote"]',
             "quote_check_worst": "VERBATIM"},
            # crosscheck flag -> full
            {"claim_id": "t-04", "cl_status": "VERIFIED",
             "opinion_file": "opinions/a.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES",
             "crosscheck_flags": '{"court_mismatch": {}}'},
            # CITE_UNCONFIRMED (not clean-verified) -> full
            {"claim_id": "t-05", "cl_status": "CITE_UNCONFIRMED",
             "opinion_file": "opinions/a.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES"},
            # not assessable (no opinion) -> "" (deterministic lane)
            {"claim_id": "t-06", "cl_status": "NOT_FOUND",
             "quoted_text": "[]"},
        ])
        stats = pp.run_triage(wd)
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        assert rows["t-01"]["triage_track"] == "fast"
        assert rows["t-02"]["triage_track"] == "full"
        assert rows["t-03"]["triage_track"] == "full"
        assert rows["t-04"]["triage_track"] == "full"
        assert rows["t-05"]["triage_track"] == "full"
        assert rows["t-06"]["triage_track"] == ""
        assert (stats.full, stats.fast, stats.skipped) == (4, 1, 1)

    def test_prescreen_off_by_default_no_jobs(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        wd = self._wd(tmp_path)
        big = "word " * 6000  # >= 20K chars
        (wd / "opinions" / "big.txt").write_text(big, encoding="utf-8")
        _triage_claims(wd, [
            {"claim_id": "t-01", "cl_status": "VERIFIED",
             "opinion_file": "opinions/big.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES"},
        ])
        stats = pp.run_triage(wd)
        assert stats.prescreen_pending == 0
        assert not (wd / "jobs" / "prescreen.json").exists()

    def test_prescreen_jobs_mode_emits_and_ingests(self, tmp_path):
        import citation_verifier.proposition_pipeline as pp
        from citation_verifier.executor import (
            Verdict, append_verdict_jsonl)
        wd = self._wd(tmp_path)
        big = "word " * 6000
        (wd / "opinions" / "big.txt").write_text(big, encoding="utf-8")
        _triage_claims(wd, [
            {"claim_id": "t-01", "cl_status": "VERIFIED",
             "opinion_file": "opinions/big.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES"},
            {"claim_id": "t-02", "cl_status": "VERIFIED",
             "opinion_file": "opinions/a.txt", "quoted_text": "[]",
             "quote_check_worst": "NO_QUOTES"},  # small -> no prescreen
        ])
        stats = pp.run_triage(wd, prescreen=True)
        assert stats.prescreen_pending == 1
        jobs = json.loads((wd / "jobs" / "prescreen.json")
                          .read_text(encoding="utf-8"))
        assert len(jobs) == 1
        assert jobs[0]["claim_ids"] == ["t-01"]
        assert jobs[0]["prompt_version"] == "prescreen-v1"
        # agent appends a hint verdict; rerun ingests it
        append_verdict_jsonl(
            wd / "jobs" / "prescreen_results.jsonl",
            Verdict(claim_id="t-01",
                    fields={"hint": "Case is about X, not Y."},
                    model="haiku", prompt_version="prescreen-v1"))
        stats2 = pp.run_triage(wd, prescreen=True)
        assert stats2.prescreen_pending == 0
        assert stats2.prescreen_done == 1
        rows = {r["claim_id"]: r for r in csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8"))}
        assert rows["t-01"]["prescreen_hint"] == "Case is about X, not Y."
        assert rows["t-02"]["prescreen_hint"] == ""

    def test_prescreen_template_renders(self):
        import citation_verifier.proposition_pipeline as pp
        prompt = pp.render_prescreen_prompt(
            "prescreen-v1", "opinions/big.txt", "The proposition.")
        assert "opinions/big.txt" in prompt
        assert "The proposition." in prompt
        assert "do NOT assess" in prompt

    def test_triage_on_withers_corpus_copy(self, tmp_path):
        """Corpus tolerance + sanity: every assessable claim gets a
        track; deterministic-lane rows get ''."""
        import citation_verifier.proposition_pipeline as pp
        wd = _copy_withers(tmp_path)
        stats = pp.run_triage(wd)
        rows = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        tracked = [r for r in rows if r["triage_track"]]
        assert len(tracked) == stats.full + stats.fast
        assert stats.skipped == len(rows) - len(tracked)
        assert stats.full >= 1  # withers has CLOSE/FABRICATED rows
```

- [x] **4.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k RunTriage`
Expected: FAIL — `run_triage` undefined

- [x] **4.3 Create the template** `src/citation_verifier/prompts/prescreen_v1.md` (sourced from the SKILL's Haiku full-read prompt, single-claim summary-hint form; new template, no cassettes):

```markdown
<!-- prompt_version: prescreen-v1 -->
<!-- Haiku summary-hint prescreen (design SS6.7, roadmap Tier 2 #7).
     One job per claim on a long opinion (>= 20K chars). The hint is
     stored in claims.csv prescreen_hint and passed to the assessment
     template from assess-v2 on (assess-v1 is byte-pinned and takes no
     hint). Any edit to this file is a NEW prompt version. Placeholders:
     {opinion_path}, {proposition}. -->
You are pre-screening a long legal opinion before a detailed assessment by a stronger model.

Read the ENTIRE opinion file at: {opinion_path}

A legal brief cites this case for the following proposition:
{proposition}

Your job is to produce a short factual hint for the assessing model:
1. What this case is actually about -- its core dispute and holding (1-2 sentences).
2. Whether the opinion discusses the proposition's topic AT ALL, even under different terminology: if yes, name the section or quote a short identifying phrase; if no, say what the opinion covers instead.

Be precise and only summarize -- do NOT assess whether the proposition is supported.

Use ONLY the Read tool on the opinion file. Do not use web search or any other tool.

Respond with ONLY a JSON object (no markdown fences):
{"hint": "2-4 sentence summary-hint"}
```

- [x] **4.4 Implement** — version constant next to `EXTRACT_PROMPT_VERSION`:

```python
PRESCREEN_PROMPT_VERSION = "prescreen-v1"
```

renderer next to `render_extract_prompt`:

```python
def render_prescreen_prompt(version: str, opinion_path: str,
                            proposition: str) -> str:
    """Render the Haiku prescreen prompt (design SS6.7)."""
    body = load_prompt_template(version)
    return body.replace("{opinion_path}", opinion_path).replace(
        "{proposition}", proposition)
```

verb after `run_crosscheck`:

```python
# SS6.7: opinions at/above this cleaned-text size get a Haiku
# summary-hint prescreen (when enabled). Prior data: 76% exact hints,
# ~15x cheaper; default OFF until the per-phase A/B re-run decides.
PRESCREEN_MIN_CHARS = 20_000

_PRESCREEN_SCHEMA = {"hint": "2-4 sentence summary-hint"}

_CLEAN_VERIFIED_STATUSES = {
    "VERIFIED", "VERIFIED_PARTIAL", "VERIFIED_VIA_RECAP",
    "VERIFIED_DOCKET_ONLY",
}


def _triage_track_for(claim: dict) -> str:
    """Deterministic SS6.7 track. '' = deterministic lane (not agent-
    assessable). The SKILL's two LLM-judgment criteria (syllabus topic
    mismatch, lead authority) are out of deterministic scope -- the
    full-track net below is correspondingly conservative."""
    if not _assessable(claim):
        return ""
    if claim.get("quote_check_worst") in ("FABRICATED", "CLOSE"):
        return "full"
    if (claim.get("quote_floor") or "").strip():
        return "full"
    quoted = (claim.get("quoted_text") or "").strip()
    if quoted and quoted != "[]":
        return "full"
    if (claim.get("crosscheck_flags") or "").strip():
        return "full"
    if claim.get("cl_status") not in _CLEAN_VERIFIED_STATUSES:
        return "full"
    return "fast"


@dataclass
class TriageStats:
    """Statistics from run_triage."""
    full: int = 0
    fast: int = 0
    skipped: int = 0
    prescreen_done: int = 0
    prescreen_pending: int = 0


def run_triage(workdir: Path, prescreen: bool = False,
               executor: Any = None,
               prompt_version: str = PRESCREEN_PROMPT_VERSION,
               ) -> TriageStats:
    """Verb 5 (design SS3 / SS6.7): assessment depth per claim.

    Writes triage_track ('full' | 'fast' | '' for the deterministic
    lane) and, when prescreen=True, runs Haiku summary-hint jobs for
    claims on long opinions (>= PRESCREEN_MIN_CHARS) through the
    executor protocol (jobs/prescreen.json + jobs/
    prescreen_results.jsonl, resume key = claim_id + prompt_version),
    ingesting hints into prescreen_hint. Prescreen defaults OFF
    (SS6.7: decide the default by re-running the A/B harness).
    Idempotent -- tracks recompute on rerun; hints are resume-keyed.
    """
    from .executor import AgentToolExecutor, Job, append_verdict_jsonl, \
        load_verdicts_jsonl

    workdir = Path(workdir)
    with open(workdir / "claims.csv", newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    stats = TriageStats()
    for c in claims:
        track = _triage_track_for(c)
        c["triage_track"] = track
        if track == "full":
            stats.full += 1
        elif track == "fast":
            stats.fast += 1
        else:
            stats.skipped += 1
        c.setdefault("prescreen_hint", "")

    if prescreen:
        results_path = workdir / "jobs" / "prescreen_results.jsonl"
        hints: dict[str, str] = {}
        if results_path.exists():
            for v in load_verdicts_jsonl(results_path):
                if v.prompt_version == prompt_version:
                    hints[v.claim_id] = str(
                        v.fields.get("hint", "")).strip()
        opinion_cache: dict[str, str] = {}
        todo: list[dict] = []
        for c in claims:
            if not c.get("triage_track"):
                continue
            if c["claim_id"] in hints:
                c["prescreen_hint"] = hints[c["claim_id"]]
                stats.prescreen_done += 1
                continue
            opinion_file = c.get("opinion_file", "") or ""
            if opinion_file not in opinion_cache:
                opinion_cache[opinion_file] = _read_clean_opinion(
                    workdir, opinion_file)
            if len(opinion_cache[opinion_file]) >= PRESCREEN_MIN_CHARS:
                todo.append(c)
        if todo:
            jobs = [Job(
                job_id=f"prescreen-{c['claim_id']}",
                claim_ids=[c["claim_id"]],
                prompt=render_prescreen_prompt(
                    prompt_version,
                    str(workdir / c["opinion_file"]),
                    c.get("cited_for") or c["proposition"]),
                prompt_version=prompt_version,
                files=[c["opinion_file"]],
                schema=_PRESCREEN_SCHEMA,
            ) for c in todo]
            if executor is None:
                executor = AgentToolExecutor(
                    workdir / "jobs" / "prescreen.json")
            done_now: dict[str, str] = {}
            for v in executor.run(jobs):
                append_verdict_jsonl(results_path, v)
                done_now[v.claim_id] = str(
                    v.fields.get("hint", "")).strip()
            for c in todo:
                if c["claim_id"] in done_now:
                    c["prescreen_hint"] = done_now[c["claim_id"]]
                    stats.prescreen_done += 1
                else:
                    stats.prescreen_pending += 1

    fields = list(claims[0].keys()) if claims else []
    for col in ("triage_track", "prescreen_hint"):
        if col not in fields:
            fields.append(col)
    for c in claims:
        for col in fields:
            c.setdefault(col, "")
    with open(workdir / "claims.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(claims)

    _update_run_json(workdir, "triage", full=stats.full, fast=stats.fast,
                     skipped=stats.skipped,
                     prescreen_done=stats.prescreen_done,
                     prescreen_pending=stats.prescreen_pending)
    return stats
```

- [x] **4.5 Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k "RunTriage or prescreen"`
Expected: PASS

- [x] **4.6 Commit**

```bash
git add src/citation_verifier/prompts/prescreen_v1.md src/citation_verifier/proposition_pipeline.py tests/test_proposition_pipeline.py
git commit -m "feat: triage verb -- deterministic tracks + Haiku prescreen wired, default OFF (SS6.7)"
```

### Task 5: CLI — `crosscheck`/`triage` verbs, `--prescreen`, full-chain order

**Files:**
- Modify: `src/citation_verifier/__main__.py`
- Test: `tests/test_proposition_pipeline.py` (`TestCli`)

- [x] **5.1 Write the failing tests** — append to `TestCli`:

```python
    def test_crosscheck_verb_dispatch(self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import CrosscheckStats
        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_crosscheck",
            lambda wd: CrosscheckStats(total=3, court_mismatches=1))
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "crosscheck"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[OK] crosscheck" in out
        assert "1 court" in out

    def test_triage_verb_dispatch_with_prescreen_flag(
            self, tmp_path, monkeypatch, capsys):
        from citation_verifier.__main__ import verify_propositions_main
        from citation_verifier.proposition_pipeline import TriageStats
        captured = {}

        def fake_triage(wd, prescreen=False, executor=None,
                        prompt_version="prescreen-v1"):
            captured["prescreen"] = prescreen
            captured["executor"] = executor
            return TriageStats(full=2, fast=1, skipped=1)

        monkeypatch.setattr(
            "citation_verifier.proposition_pipeline.run_triage",
            fake_triage)
        wd = tmp_path / "wd"
        wd.mkdir()
        rc = verify_propositions_main([str(wd), "triage"])
        assert rc == 0
        assert captured["prescreen"] is False
        assert "[OK] triage" in capsys.readouterr().out
        verify_propositions_main([str(wd), "triage", "--prescreen"])
        assert captured["prescreen"] is True

    def test_full_chain_runs_new_verbs_in_order(
            self, tmp_path, monkeypatch):
        """full = verify -> merge -> check-quotes -> crosscheck ->
        triage -> assess (-> apply)."""
        from citation_verifier.__main__ import verify_propositions_main
        import citation_verifier.proposition_pipeline as pp
        order = []
        monkeypatch.setattr(pp, "run_merge",
                            lambda wd: order.append("merge") or
                            pp.MergeStats())
        monkeypatch.setattr(pp, "run_check_quotes",
                            lambda wd: order.append("check-quotes") or
                            pp.QuoteCheckStats())
        monkeypatch.setattr(pp, "run_crosscheck",
                            lambda wd: order.append("crosscheck") or
                            pp.CrosscheckStats())
        monkeypatch.setattr(
            pp, "run_triage",
            lambda wd, prescreen=False, executor=None,
            prompt_version="prescreen-v1": order.append("triage") or
            pp.TriageStats())
        monkeypatch.setattr(
            pp, "run_assess",
            lambda wd, executor=None, prompt_version="assess-v1":
            order.append("assess") or pp.AssessStats(pending=1))
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / "verification_results.csv").write_text(
            "citation,status\n", encoding="utf-8")  # verify no-ops
        rc = verify_propositions_main([str(wd), "full"])
        assert rc == 0
        assert order == ["merge", "check-quotes", "crosscheck",
                         "triage", "assess"]
```

- [x] **5.2 Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py -v -k "crosscheck_verb or triage_verb or full_chain_runs"`
Expected: FAIL — `crosscheck` not in CLI choices

- [x] **5.3 Implement** — verb `choices` becomes:

```python
        choices=["extract", "verify", "merge", "check-quotes",
                 "crosscheck", "triage", "assess", "apply-assessments",
                 "full"],
```

add the flag:

```python
    parser.add_argument(
        "--prescreen", action="store_true",
        help="Triage: run Haiku summary-hint prescreen jobs for long "
             "opinions (default off pending the A/B re-run)",
    )
```

and in `_dispatch_proposition_verbs`, after the check-quotes block (Task 2) insert:

```python
    if args.verb in ("crosscheck", "full"):
        xstats = pp.run_crosscheck(workdir)
        print(f"[OK] crosscheck: {xstats.total} claims, "
              f"{xstats.toa_mismatches} TOA, "
              f"{xstats.court_mismatches} court, "
              f"{xstats.pincite_flags} pincite flags")

    if args.verb in ("triage", "full"):
        tstats = pp.run_triage(workdir, prescreen=args.prescreen,
                               executor=_make_executor())
        print(f"[OK] triage: {tstats.full} full, {tstats.fast} fast, "
              f"{tstats.skipped} deterministic")
        if tstats.prescreen_pending:
            print(f"  PENDING: {tstats.prescreen_pending} prescreen "
                  f"jobs -> jobs/prescreen.json (dispatch agents, "
                  f"append to jobs/prescreen_results.jsonl, rerun)")
```

(The assess block already follows; full-chain order comes out as verify → merge → check-quotes → crosscheck → triage → assess → apply.) Note `--prompt-version` stays assess-only; `run_triage` keeps its own default (`prescreen-v1`) — do not thread `args.prompt_version` into triage.

- [x] **5.4 Run the CLI block + neighboring suites**

Run: `venv/Scripts/python.exe -m pytest tests/test_proposition_pipeline.py tests/test_executor.py tests/test_brief_pipeline.py -q`
Expected: all PASS

- [x] **5.5 Commit**

```bash
git add src/citation_verifier/__main__.py tests/test_proposition_pipeline.py
git commit -m "feat: crosscheck + triage CLI verbs, --prescreen flag, full-chain order (SS3)"
```

### Task 6: Docs, regression sweep, push

- [x] **6.1** Full offline suite:

Run: `venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_false_negatives.py --ignore=tests/test_cl_api_issues.py`
Expected: >= 724 passed + this step's new tests, 0 failures; `test_assessment_regression.py` and `test_assessment_corpora.py` unchanged (frozen corpora are only read via tmp copies).

- [x] **6.2** CLAUDE.md updates: `proposition_pipeline.py` row (run_check_quotes/run_crosscheck/run_triage verbs, crosscheck_flags/triage_track/prescreen_hint columns, prescreen-v1 template, CLI verb list + `--prescreen`), `models.py`/Common Pitfalls (matched_court/matched_court_id accessors beside matched_case_name; vr CSV schema), `client.py` row (court_id in metadata dicts).

- [x] **6.3** Fill in this plan's Execution notes (incl. the parse_citation court-format finding from Task 3.4 and the Withers triage counts from Task 4's corpus test).

- [x] **6.4 Commit + push**

```bash
git add CLAUDE.md docs/plans/2026-06-11-prop-pipeline-step6-crosscheck-triage-plan.md
git commit -m "docs: Step 6 execution notes + CLAUDE.md (crosscheck, triage, matched court)"
git push origin pipeline-redesign
```

---

## Subsequent steps (§10 map)

7. **Report lanes (§6.9), SKILL stub, A/B harness re-point.** The report should
   render `crosscheck_flags` as card-level flags ("renders as a flag on the
   card even when support is otherwise fine", §6.5) and the §6.9 lanes.
8. **Acceptance runs (§8); retro.** Also owed to assess-v2 (re-record event):
   multi-opinion packing (§6.8), external-tool prohibition in the assess
   template, `{prescreen_hint}` placeholder consumption, and `assess`
   honoring `triage_track` (fast-track Haiku confirmation instead of full
   Opus). The prescreen default (ON vs OFF) is decided by the per-phase A/B
   re-run over the 62 cases + Withers.

## Execution notes (2026-06-12, all tasks complete)

- **Deviation (Task 1.1):** the two "header-pinning" test sites the plan
  flagged (`test_proposition_pipeline.py` ~:130 and ~:300) turned out to
  be *input fixtures* for merge (read via DictReader, tolerant of the
  old header), not output assertions — left unchanged; they now double
  as legacy-format tolerance coverage. The output header is asserted by
  the new `TestVerificationCsvCourtColumns`.
- **Pre-flight (Task 3.4) finding:** `parse_citation` returns CL court
  ids directly for circuit cites (`'(6th Cir. 2000)'` → court `'ca6'`),
  and the trailing-`n.42` form parses fine — the plan's original
  fixture format worked unmodified.
- Crosscheck tests passed on the first implementation run (7/7).
- **Withers corpus numbers** (tmp copy, post-Step-3 columns):
  triage = 10 full / 19 fast / 5 deterministic-lane;
  crosscheck = 34 claims, 0 TOA (no extract lists in that corpus),
  0 court (legacy vr CSV has no matched_court_id), 1 pincite flag.
  The pincite flag is a *finding to review when Step 8 acceptance runs*:
  one Withers cite's pinpoint falls outside the opinion text's
  star-pagination range (flag-only; no color impact by design).
- Verb choices for crosscheck/triage landed early (in Task 2's choices
  edit) — dispatch blocks and `--prescreen` landed in Task 5 as planned;
  TDD still caught the missing dispatch (3 CLI tests failed before 5.3).
- Suite: **745 passed offline** (724 + 21 new), 0 regressions;
  `test_assessment_regression.py` / `test_assessment_corpora.py`
  unchanged.

## Self-review notes

- §6.5 bullet 1 (TOA vs body) → Task 3 `_toa_body_variants` + per-claim flag; "both variants go to verify" already holds (`citations_from_workdir` unions both lists since Step 5).
- §6.5 bullet 2 (court check) → Task 1 persistence + Task 3 comparison; zero LLM involvement; skips when either side unknown (state courts/legacy CSVs) — best-effort per design.
- §6.5 bullet 3 (pincite) → Task 3 `_pincite_flag`: star-pagination range + footnote existence; flags only, never the color function.
- §6.7 → Task 4: track rules = SKILL Phase 2a minus the two LLM judgments (documented in the docstring); prescreen wired through the executor protocol, default OFF, per-claim jobs (executor semantics give every claim_id in a job the same fields — per-claim is the clean fit), 20K threshold from the SKILL/design.
- §4 schema → crosscheck_flags / triage_track / prescreen_hint columns exactly as the design's state table names them.
- Type consistency: `CrosscheckStats(total, toa_mismatches, court_mismatches, pincite_flags)` and `TriageStats(full, fast, skipped, prescreen_done, prescreen_pending)` used identically in Tasks 3-5; `run_triage(wd, prescreen, executor, prompt_version)` matches the CLI fake in 5.1.
- Frozen corpora untouched (tests copy to tmp); legacy workdirs tolerated (missing TOA lists, pre-court vr CSVs → no flags, no crashes).
