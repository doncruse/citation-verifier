# Haiku Prescreen + Verbatim Quote Checker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Haiku-based opinion summarization and deterministic verbatim quote checking to the verify-brief pipeline.

**Architecture:** Two independent additions. (1) `check_quotes()` in `brief_pipeline.py` — deterministic string matching that reads `quoted_text` from claims.csv and checks each quote against the opinion file. (2) SKILL.md updates — new Haiku summary phase using Explore agents, updated Phase 1c prompt for `quoted_text` extraction, updated assessment prompt that receives both summaries and quote-check results.

**Tech Stack:** Python 3.10+, difflib.SequenceMatcher, csv, json. No new dependencies.

---

### Task 1: Update merge_claims to pass through new columns

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py:353-357` (output_fields list)
- Modify: `src/citation_verifier/brief_pipeline.py:390-401` (merged row construction)
- Test: `tests/test_brief_pipeline.py`

**Step 1: Write the failing test**

Add to `tests/test_brief_pipeline.py`:

```python
class TestMergePassthroughColumns:
    def test_merge_preserves_quoted_text(self, tmp_path):
        """merge_claims passes through quoted_text and quote_check columns."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            'page,proposition,cited_case,quoted_text\n'
            '21,"Courts defer.","Egan, 484 U.S. 518 (1988)","[""defer to executive""]"\n'
            '30,"Free speech.","Garcetti, 547 U.S. 410 (2006)","[]"\n'
        )
        vr = tmp_path / "verification_results.csv"
        vr.write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,https://cl/1/,Egan,,\n'
            '"Garcetti, 547 U.S. 410 (2006)",VERIFIED,1.0,https://cl/2/,Garcetti,,\n'
        )
        (tmp_path / "opinions").mkdir()

        merge_claims(tmp_path)

        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quoted_text"] == '["defer to executive"]'
        assert merged[1]["quoted_text"] == "[]"

    def test_merge_preserves_quote_check(self, tmp_path):
        """merge_claims passes through quote_check and quote_check_worst."""
        claims = tmp_path / "claims.csv"
        claims.write_text(
            'page,proposition,cited_case,quoted_text,quote_check,quote_check_worst\n'
            '21,"Courts defer.","Egan, 484 U.S. 518 (1988)","[""defer""]",'
            '"[{""quote"": ""defer"", ""result"": ""VERBATIM"", ""similarity"": 0.95}]",VERBATIM\n'
        )
        vr = tmp_path / "verification_results.csv"
        vr.write_text(
            "citation,status,confidence,cl_url,matched_name,diagnostics_cat,diagnostics_msg\n"
            '"Egan, 484 U.S. 518 (1988)",VERIFIED,1.0,https://cl/1/,Egan,,\n'
        )
        (tmp_path / "opinions").mkdir()

        merge_claims(tmp_path)

        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quote_check_worst"] == "VERBATIM"
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestMergePassthroughColumns -v`
Expected: FAIL — `quoted_text` not in output fields

**Step 3: Write minimal implementation**

In `brief_pipeline.py`, update `merge_claims()`:

1. Change `output_fields` (line 353) to dynamically include any extra columns from claims.csv:

```python
    # Core output fields (always present)
    _CORE_FIELDS = [
        "page", "proposition", "cited_case",
        "retrieved_case", "supporting_language", "assessment",
        "cl_url", "cl_status", "diagnostics", "opinion_file",
    ]

    # Passthrough fields — preserved from input claims.csv if present
    _PASSTHROUGH_FIELDS = ["quoted_text", "quote_check", "quote_check_worst"]
```

2. In `merge_claims()`, detect which passthrough columns exist in input claims:

```python
    # Detect extra columns present in input
    output_fields = list(_CORE_FIELDS)
    if claims:
        for col in _PASSTHROUGH_FIELDS:
            if col in claims[0]:
                output_fields.append(col)
```

3. In the merged row construction, copy passthrough columns:

```python
        row = {
            "page": claim.get("page", ""),
            # ... existing fields ...
            "opinion_file": opinion_file,
        }
        # Copy passthrough columns
        for col in _PASSTHROUGH_FIELDS:
            if col in claim:
                row[col] = claim[col]
        merged_rows.append(row)
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py -v`
Expected: All tests PASS (new + existing)

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: merge_claims passes through quoted_text and quote_check columns"
```

---

### Task 2: Quote normalization helpers

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py` (add at end of helpers section, ~line 102)
- Test: `tests/test_brief_pipeline.py`

**Step 1: Write the failing tests**

```python
from citation_verifier.brief_pipeline import _normalize_quote_text


class TestNormalizeQuoteText:
    def test_smart_quotes_to_straight(self):
        assert _normalize_quote_text("\u201cno desire\u201d") == '"no desire"'

    def test_collapses_whitespace(self):
        assert _normalize_quote_text("no   desire\n to") == "no desire to"

    def test_strips_bracketed_alterations(self):
        assert _normalize_quote_text("the [Defendant] must show") == "the must show"

    def test_strips_ellipses(self):
        # Three dots
        assert _normalize_quote_text("first ... last") == "first last"
        # Unicode ellipsis
        assert _normalize_quote_text("first \u2026 last") == "first last"

    def test_combined(self):
        text = "\u201c[T]he court\u2019s [inherent] authority \u2026 extends\u201d"
        result = _normalize_quote_text(text)
        assert result == '"he court\'s authority extends"'
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestNormalizeQuoteText -v`
Expected: FAIL — ImportError

**Step 3: Write minimal implementation**

Add to `brief_pipeline.py` after `_normalize_for_match` (~line 73):

```python
import unicodedata

def _normalize_quote_text(text: str) -> str:
    """Normalize quoted text for fuzzy matching.

    Strips bracketed alterations, ellipses, smart quotes, and excess whitespace.
    """
    # Smart quotes to straight
    s = text.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    # Strip bracketed alterations: [T]he -> he, [inherent] -> ""
    s = re.sub(r"\[([A-Z])\]", lambda m: m.group(1).lower(), s)  # [T] -> t
    s = re.sub(r"\[[^\]]*\]", "", s)  # [word] -> ""
    # Strip ellipses
    s = s.replace("\u2026", " ")  # unicode ellipsis
    s = re.sub(r"\.{3,}", " ", s)  # three+ dots
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestNormalizeQuoteText -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add _normalize_quote_text helper for verbatim quote matching"
```

---

### Task 3: Core check_quotes function

**Files:**
- Modify: `src/citation_verifier/brief_pipeline.py` (new function after merge_claims)
- Test: `tests/test_brief_pipeline.py`

**Step 1: Write the failing tests**

```python
import json
from citation_verifier.brief_pipeline import check_quotes, QuoteCheckStats


class TestCheckQuotes:
    def _setup_workdir(self, tmp_path, claims_text, opinion_text):
        """Helper: write claims.csv and an opinion file."""
        (tmp_path / "claims.csv").write_text(claims_text)
        opinions = tmp_path / "opinions"
        opinions.mkdir(exist_ok=True)
        if opinion_text is not None:
            (opinions / "Test_Case.txt").write_text(opinion_text)
        return tmp_path

    def test_verbatim_match(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""the court held that sanctions require bad faith""]",opinions/Test_Case.txt\n',
            "In this opinion, the court held that sanctions require bad faith under the statute.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        checks = json.loads(merged[0]["quote_check"])
        assert len(checks) == 1
        assert checks[0]["result"] == "VERBATIM"
        assert checks[0]["similarity"] > 0.85
        assert merged[0]["quote_check_worst"] == "VERBATIM"

    def test_fabricated_quote(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""completely invented language not in the opinion""]",opinions/Test_Case.txt\n',
            "This opinion discusses sanctions under Rule 11 and the standard of review.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        checks = json.loads(merged[0]["quote_check"])
        assert checks[0]["result"] == "FABRICATED"
        assert checks[0]["similarity"] < 0.6
        assert merged[0]["quote_check_worst"] == "FABRICATED"

    def test_no_quotes(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[]",opinions/Test_Case.txt\n',
            "Some opinion text.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quote_check"] == "[]"
        assert merged[0]["quote_check_worst"] == "NO_QUOTES"

    def test_no_opinion_file(self, tmp_path):
        """Claims with no opinion file get empty quote_check."""
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)","[""some quote""]",""\n',
            None,
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        assert merged[0]["quote_check"] == "[]"
        assert merged[0]["quote_check_worst"] == "NO_OPINION"

    def test_multiple_quotes_worst_wins(self, tmp_path):
        """quote_check_worst reflects the worst result across all quotes."""
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)",'
            '"[""sanctions require bad faith"", ""totally fake quote here""]",'
            'opinions/Test_Case.txt\n',
            "The court stated that sanctions require bad faith under the rule.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        checks = json.loads(merged[0]["quote_check"])
        assert len(checks) == 2
        # Worst should be FABRICATED even though one is VERBATIM
        assert merged[0]["quote_check_worst"] == "FABRICATED"

    def test_close_match(self, tmp_path):
        """Near-match with minor word changes classified as CLOSE."""
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"Prop","Test, 100 U.S. 1 (2000)",'
            '"[""the court concluded that sanctions clearly require showing of bad faith""]",'
            'opinions/Test_Case.txt\n',
            "The court stated that sanctions require a showing of bad faith under the applicable standard.",
        )
        stats = check_quotes(workdir)
        merged = list(csv.DictReader((tmp_path / "claims.csv").open()))
        checks = json.loads(merged[0]["quote_check"])
        assert checks[0]["result"] in ("CLOSE", "VERBATIM")  # threshold-dependent

    def test_stats_returned(self, tmp_path):
        workdir = self._setup_workdir(
            tmp_path,
            'page,proposition,cited_case,quoted_text,opinion_file\n'
            '1,"P1","Test, 100 U.S. 1 (2000)","[""sanctions require bad faith""]",opinions/Test_Case.txt\n'
            '2,"P2","Test, 100 U.S. 1 (2000)","[]",opinions/Test_Case.txt\n',
            "The court held that sanctions require bad faith.",
        )
        stats = check_quotes(workdir)
        assert stats.total_claims == 2
        assert stats.checked == 1
        assert stats.no_quotes == 1
```

**Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestCheckQuotes -v`
Expected: FAIL — ImportError

**Step 3: Write minimal implementation**

Add `QuoteCheckStats` dataclass and `check_quotes()` function to `brief_pipeline.py`:

```python
import difflib
import json as json_mod

@dataclass
class QuoteCheckStats:
    """Statistics from check_quotes."""
    total_claims: int = 0
    checked: int = 0
    no_quotes: int = 0
    no_opinion: int = 0
    verbatim: int = 0
    close: int = 0
    fabricated: int = 0


def _best_match_ratio(needle: str, haystack: str) -> float:
    """Find the best SequenceMatcher ratio for needle in a sliding window of haystack."""
    if not needle or not haystack:
        return 0.0
    # For short quotes, SequenceMatcher on the full text works well.
    # For long haystacks, use find_longest_match heuristics.
    needle_norm = _normalize_quote_text(needle).lower()
    haystack_norm = _normalize_quote_text(haystack).lower()

    if not needle_norm:
        return 0.0

    # If exact substring, it's verbatim
    if needle_norm in haystack_norm:
        return 1.0

    # Sliding window: compare against chunks of haystack roughly needle-sized
    best = 0.0
    window = len(needle_norm)
    # Use SequenceMatcher with autojunk=False for short strings
    for start in range(0, max(1, len(haystack_norm) - window + 1), max(1, window // 4)):
        chunk = haystack_norm[start:start + window + window // 2]
        ratio = difflib.SequenceMatcher(None, needle_norm, chunk, autojunk=False).ratio()
        if ratio > best:
            best = ratio
            if best > 0.95:
                break  # good enough
    return best


def check_quotes(workdir: Path) -> QuoteCheckStats:
    """Check quoted text in claims against opinion files.

    Reads claims.csv, checks each quoted_text entry against the opinion,
    writes quote_check and quote_check_worst columns back to claims.csv.
    """
    workdir = Path(workdir)
    claims_path = workdir / "claims.csv"
    stats = QuoteCheckStats()

    with open(claims_path, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    # Cache opinion text by file path
    opinion_cache: dict[str, str] = {}

    for claim in claims:
        stats.total_claims += 1
        quoted_raw = claim.get("quoted_text", "[]")
        opinion_file = claim.get("opinion_file", "")

        try:
            quotes = json_mod.loads(quoted_raw) if quoted_raw else []
        except (json_mod.JSONDecodeError, TypeError):
            quotes = []

        if not quotes:
            claim["quote_check"] = "[]"
            claim["quote_check_worst"] = "NO_QUOTES"
            stats.no_quotes += 1
            continue

        if not opinion_file:
            claim["quote_check"] = "[]"
            claim["quote_check_worst"] = "NO_OPINION"
            stats.no_opinion += 1
            continue

        # Load opinion text
        opinion_path = workdir / opinion_file
        if opinion_file not in opinion_cache:
            try:
                opinion_cache[opinion_file] = opinion_path.read_text(encoding="utf-8")
            except (FileNotFoundError, UnicodeDecodeError):
                claim["quote_check"] = "[]"
                claim["quote_check_worst"] = "NO_OPINION"
                stats.no_opinion += 1
                continue
        opinion_text = opinion_cache[opinion_file]

        # Check each quote
        results = []
        worst = "VERBATIM"  # best possible, will be downgraded
        _WORST_ORDER = {"VERBATIM": 0, "CLOSE": 1, "FABRICATED": 2}

        for quote in quotes:
            ratio = _best_match_ratio(quote, opinion_text)
            if ratio > 0.85:
                result = "VERBATIM"
                stats.verbatim += 1
            elif ratio >= 0.6:
                result = "CLOSE"
                stats.close += 1
            else:
                result = "FABRICATED"
                stats.fabricated += 1

            results.append({
                "quote": quote,
                "result": result,
                "similarity": round(ratio, 2),
            })

            if _WORST_ORDER.get(result, 0) > _WORST_ORDER.get(worst, 0):
                worst = result

        claim["quote_check"] = json_mod.dumps(results)
        claim["quote_check_worst"] = worst
        stats.checked += 1

    # Write updated claims.csv — preserve all columns
    if claims:
        all_fields = list(claims[0].keys())
        # Ensure new columns are present
        for col in ("quote_check", "quote_check_worst"):
            if col not in all_fields:
                all_fields.append(col)

        with open(claims_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields)
            writer.writeheader()
            writer.writerows(claims)

    return stats
```

**Step 4: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py::TestCheckQuotes -v`
Expected: PASS

Then run all tests:

Run: `venv/Scripts/python.exe -m pytest tests/test_brief_pipeline.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/citation_verifier/brief_pipeline.py tests/test_brief_pipeline.py
git commit -m "feat: add check_quotes() for verbatim quote verification"
```

---

### Task 4: CLI --check-quotes flag

**Files:**
- Modify: `src/citation_verifier/__main__.py:182-198` (add to mutually exclusive group)
- Modify: `src/citation_verifier/__main__.py:231-241` (add handler)

**Step 1: Write minimal implementation**

In `__main__.py`, add to the mutually exclusive group (after `--merge`):

```python
    group.add_argument(
        "--check-quotes", action="store_true",
        help="Run verbatim quote checker on claims.csv",
    )
```

Add handler before the `if args.wave1:` block:

```python
    if args.check_quotes:
        from .brief_pipeline import check_quotes
        stats = check_quotes(workdir)
        print(f"Quote check: {stats.total_claims} claims, {stats.checked} checked")
        print(f"  VERBATIM: {stats.verbatim}, CLOSE: {stats.close}, FABRICATED: {stats.fabricated}")
        print(f"  No quotes: {stats.no_quotes}, No opinion: {stats.no_opinion}")
        return 0
```

**Step 2: Smoke test**

Run: `venv/Scripts/python.exe -m citation_verifier verify-brief --help`
Expected: `--check-quotes` appears in help output

**Step 3: Commit**

```bash
git add src/citation_verifier/__main__.py
git commit -m "feat: add --check-quotes CLI flag to verify-brief"
```

---

### Task 5: Update SKILL.md — Phase 1c quoted_text extraction

**Files:**
- Modify: `.claude/skills/verify-brief/SKILL.md:60-68` (Phase 1c agent instructions)

**Step 1: Update Phase 1c instructions**

Add `quoted_text` to the columns and add extraction instruction. Replace Phase 1c agent instructions:

```markdown
**Agent 1 (Opus) — Extract propositions:**
- Read the brief
- Reference the citation list from `citations_to_verify.txt`
- Extract every proposition-case pair into `claims.csv` with columns: `page,proposition,cited_case,quoted_text`
- CRITICAL: The `cited_case` column MUST start with the exact full citation text from `citations_to_verify.txt` (including case name, reporter, and year). Append pinpoint pages after the start page (e.g., "Camp v. Pitts, 411 U.S. 138, 142 (1973)"). Do NOT abbreviate, omit the reporter, or use short-form case names.
- `quoted_text`: JSON array of any text that appears inside quotation marks in the brief's sentence for this claim. Extract the exact quoted words. If the claim has no quoted text, use `[]`. Example: `["no desire to deter", "but-for causation"]`
- Same case cited for different propositions = separate rows
- Same proposition supported by multiple cases = separate rows
- Exclude non-case sources
```

**Step 2: Verify no syntax issues**

Read the updated SKILL.md to confirm formatting.

**Step 3: Commit**

```bash
git add .claude/skills/verify-brief/SKILL.md
git commit -m "feat: Phase 1c extracts quoted_text column"
```

---

### Task 6: Update SKILL.md — Haiku summary phase + quote-check integration

**Files:**
- Modify: `.claude/skills/verify-brief/SKILL.md` (add Phase 1d, update Phase 2)

**Step 1: Add Phase 1d (Quote Check + Haiku Summaries)**

Insert new phase between the merge step (end of Phase 1c) and Phase 2. Add after the merge instructions:

```markdown
### Phase 1d: Quote Check + Haiku Summaries

Two steps, run sequentially.

**Step 1 — Verbatim Quote Check (deterministic):**

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief <workdir> --check-quotes
```

This checks every quoted string in `quoted_text` against the opinion file and writes `quote_check` and `quote_check_worst` columns to `claims.csv`. Report the stats.

**Step 2 — Haiku Opinion Summaries:**

Group claims by `opinion_file`. For each unique opinion file:

1. Check file size: `Read` the opinion and count characters
2. If < 20,000 characters → **skip** (Opus reads directly in Phase 2)
3. If >= 20,000 characters → launch an **Explore** agent (Haiku) with this prompt:

> Read the ENTIRE opinion file at `{opinion_path}` very thoroughly. This is a legal opinion.
>
> For each proposition below, search the full opinion text and report your findings.
>
> Propositions to check:
> {numbered list of propositions from claims citing this opinion}
>
> **Output format — follow exactly:**
>
> TOPICS FOUND:
> For each proposition where you found relevant content, write:
> - Proposition N: [quote or close paraphrase from the opinion with page/section reference]
>
> TOPICS NOT FOUND:
> For each proposition where the opinion does NOT address the topic at all, write:
> - Proposition N: NOT FOUND. The opinion does not discuss [topic]. [One sentence on what the opinion actually covers instead.]
>
> Be precise. If a topic is only tangentially mentioned, put it under TOPICS FOUND with a note that the support is indirect. Only put items under TOPICS NOT FOUND when the opinion genuinely does not address that subject.

4. Save the summary to `opinions/{case_name}_summary.txt`

Report: "Summarized X opinions (Y skipped, under 20K chars)."
```

**Step 2: Update Phase 2 assessment instructions**

Replace the Phase 2 subagent instructions to use summaries and include quote-check:

```markdown
### Phase 2: Assess Cases (Opus Subagents)

Group claims by opinion file. For each opinion, launch an Opus subagent.

**Subagent input:**
- Opinion source: If `opinions/{case}_summary.txt` exists → read the **summary**. Otherwise → read the **full opinion** using the Read tool.
- List of claims: `[{row_index, proposition, cited_case, quote_check_worst, quote_check}]`
- Assessment criteria (below)

**Subagent instructions:**
> Read the opinion (or summary). For each claim, assess whether the case supports the proposition.
>
> If reading a full opinion (not a summary): read the entire text. For opinions > 80K characters, read in chunks using offset/limit (2000 lines per chunk). Read ALL chunks.
>
> **Quote check results are provided for each claim.** Factor these into your assessment:
> - `FABRICATED` quote: the brief puts words in quotation marks that do not appear in the opinion. This is a serious issue — downgrade to at least Yellow, Red if the substance is also wrong.
> - `CLOSE` quote: near-match with minor word changes. Note the discrepancy but don't automatically downgrade.
> - `VERBATIM` or `NO_QUOTES`: no issue with quoted text.
>
> Write your response as a JSON array:
> ```json
> [{"row_index": 7, "assessment": "Green", "supporting_language": "(1) Supports: \"exact quote...\""}]
> ```

**Assessment criteria:**
- **Green** — case directly and accurately supports the proposition as stated, AND any quoted text is verbatim or no quotes used
- **Yellow** — partially relevant, support weaker than represented, pinpoint off, proposition overstates holding, OR quoted text is close but not verbatim
- **Red** — does not support, misleading, quoted language fabricated, or fundamentally misrepresents the holding
```

**Step 3: Update resume table**

Update the resume table to account for new phases:

```markdown
| State | Resume at |
|-------|-----------|
| No `claims.csv` | Phase 1a |
| Has `cited_case` but no `cl_status` | Phase 1b (wave1) |
| Has `cl_status` but no `quote_check_worst` | Phase 1d (quote check + summaries) |
| Has `quote_check_worst` but no `assessment` | Phase 2 |
| Has `assessment` | Phase 4 (report) |
```

**Step 4: Commit**

```bash
git add .claude/skills/verify-brief/SKILL.md
git commit -m "feat: add Haiku summary phase and quote-check integration to verify-brief"
```

---

### Task 7: Integration test with Fletcher data

**Files:**
- No code changes — validation only

**Step 1: Dry-run quote checker on Fletcher**

Check that the Fletcher working directory has the right structure:

```bash
ls briefs/fletcher-v-experian/
```

If `claims.csv` exists with `opinion_file` populated, run:

```bash
venv/Scripts/python.exe -m citation_verifier verify-brief briefs/fletcher-v-experian --check-quotes
```

**Step 2: Verify known false negatives**

Check the output for the 4 known false-negative cases:
- Fox rows 26/29/35 — fabricated "but-for" quotes should be FABRICATED
- Thomas row 53 — fabricated quote should be FABRICATED

Check the 10 Green rows to ensure real quotes aren't false-flagged.

**Step 3: Tune thresholds if needed**

If real quotes are being flagged as CLOSE or FABRICATED, adjust the thresholds in `_best_match_ratio` or `check_quotes`. The 0.85/0.6 thresholds are starting points.

**Step 4: Commit any threshold adjustments**

```bash
git add src/citation_verifier/brief_pipeline.py
git commit -m "fix: tune quote-check similarity thresholds based on Fletcher data"
```

---

## Task Dependencies

```
Task 1 (merge passthrough) ──┐
Task 2 (normalize helpers) ───┼── Task 3 (check_quotes) ── Task 4 (CLI) ── Task 7 (integration)
                              │
Task 5 (SKILL Phase 1c) ─────┘
Task 6 (SKILL Phase 1d + Phase 2) ── after Task 5
```

Tasks 1, 2, and 5 are independent and can be done in parallel.
Task 3 depends on 1 and 2.
Task 4 depends on 3.
Task 6 depends on 5.
Task 7 depends on 4 and 6.
