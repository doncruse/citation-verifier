# Proposition-Verifier Step 3: Quote-Check Extensions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land design §6.4: quoted-span extraction at ≥2 words (was ≥4), a `quote_floor` column (FABRICATED → at most Yellow; CLOSE inside quotation marks → at most Yellow), floor-aware offline scoring, and the empirically-measured Withers improvement (design projects 12/19 → ~15/19 yellows caught).

**Architecture:** Three layers. (1) `extract_quoted_spans()` in `proposition_pipeline.py` — the span extractor, lowered to ≥2 words (the Am. Auto "judicial admissions" class). (2) `check_quotes()` extended: re-derives `quoted_text` from the proposition when the input has none, and writes `quote_floor` (deterministic; the agent can lower a color but `apply-assessments` — Step 4 — will never let it pass the floor). (3) `scoring.predict_workdir()` applies the floor to replayed verdicts, modeling what apply-assessments will do. The frozen Withers corpus is then *regenerated through the new deterministic phase* (claims.csv quote columns only — cassette verdicts and claim identity untouched), and the regression baselines update to the measured numbers in the same commit, with the before/after documented.

**Tech Stack:** stdlib + pytest, all offline.

**Source facts:**
- Old extractor (`measure_withers_assessment.py:92`): `_QUOTE_SPAN = re.compile(r'[“"]([^"“”]{10,}?)[”"]')` + `len(span.split()) >= 4`. Single-quoted spans deliberately skipped (apostrophe ambiguity) — keep that.
- `check_quotes` (proposition_pipeline.py): NO_QUOTES when `quoted_text` empty; thresholds >0.85 VERBATIM / ≥0.6 CLOSE / else FABRICATED.
- Frozen Withers misses the floors would catch (Step 1 baseline): Anderson -38 (qc=CLOSE, agent said Green), Am. Auto -09/-12 (2-word quote invisible to the ≥4 extractor).
- §8 green guardrail: over-flags ≤2/12 sampled.

---

### Task 1: `extract_quoted_spans()` (≥2 words)

**Files:** Modify `src/citation_verifier/proposition_pipeline.py`; test `tests/test_proposition_pipeline.py`.

- [ ] **1.1 Failing tests:**

```python
class TestExtractQuotedSpans:
    def test_two_word_span_extracted(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = ('The court treated stipulations as "judicial admissions" '
                'binding on the parties.')
        assert extract_quoted_spans(text) == ["judicial admissions"]

    def test_smart_quotes(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = "Held that “good cause shown” is required."
        assert extract_quoted_spans(text) == ["good cause shown"]

    def test_single_word_skipped(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        assert extract_quoted_spans('The "factors" test applies.') == []

    def test_single_quoted_spans_skipped(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        assert extract_quoted_spans("It's 'two words' here.") == []

    def test_multiple_spans_in_order(self):
        from citation_verifier.proposition_pipeline import (
            extract_quoted_spans)
        text = ('"first span here" and then "second span" follows')
        assert extract_quoted_spans(text) == ["first span here",
                                              "second span"]
```

- [ ] **1.2 Implement** (port the measurement regex, drop the `{10,}` length floor to accommodate short 2-word terms, keep double-quote-only):

```python
# Double-quoted spans (straight or smart). Single-quoted spans are skipped
# (apostrophe ambiguity); >= 2 words per design SS6.4 -- the 2-word quoted
# term "judicial admissions" is exactly what the Am. Auto misses hinged on.
_QUOTE_SPAN = re.compile(r'[“"]([^"“”]{3,}?)[”"]')


def extract_quoted_spans(text: str, min_words: int = 2) -> list[str]:
    """Extract double-quoted spans of >= min_words words from text."""
    out = []
    for m in _QUOTE_SPAN.finditer(text or ""):
        span = m.group(1).strip()
        if len(span.split()) >= min_words:
            out.append(span)
    return out
```

- [ ] **1.3 Run; commit** — `feat: extract_quoted_spans at >=2 words (SS6.4)`

### Task 2: `check_quotes` — re-derivation + `quote_floor`

**Files:** same.

Behavior:
- When a claim's `quoted_text` parses to a non-empty list → use it as-is (extraction-front-end data is authoritative).
- When empty → `extract_quoted_spans(proposition)` ∪ `extract_quoted_spans(brief_sentence)` (order-preserving dedup); write the derived list back into `quoted_text` so downstream phases and the report see it.
- New column `quote_floor`: `"Yellow"` when worst is CLOSE or FABRICATED, else `""`. (CLOSE inside quotation marks *is* every CLOSE we produce — quotes only enter via quotation marks.)
- Stats gain `derived_quotes` counter.

- [ ] **2.1 Failing tests:**

```python
class TestCheckQuotesExtensions:
    def _wd(self, tmp_path, proposition, opinion_text, quoted_text="[]"):
        wd = tmp_path / "wd"
        (wd / "opinions").mkdir(parents=True)
        (wd / "opinions" / "A.html").write_text(opinion_text,
                                                encoding="utf-8")
        with (wd / "claims.csv").open("w", newline="",
                                      encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "claim_id", "proposition", "cited_case", "quoted_text",
                "opinion_file", "cl_status"])
            w.writeheader()
            w.writerow({"claim_id": "t-01", "proposition": proposition,
                        "cited_case": "A v. B", "quoted_text": quoted_text,
                        "opinion_file": "opinions/A.html",
                        "cl_status": "VERIFIED"})
        return wd

    def test_derives_quotes_from_proposition(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'Stipulations are "judicial admissions" here.',
                      "nothing relevant in this opinion text at all")
        stats = check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert json.loads(claims[0]["quoted_text"]) == [
            "judicial admissions"]
        assert claims[0]["quote_check_worst"] == "FABRICATED"
        assert claims[0]["quote_floor"] == "Yellow"
        assert stats.derived_quotes == 1

    def test_verbatim_quote_no_floor(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'The court said "exact words match" plainly.',
                      "Indeed the court said exact words match in text.")
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["quote_check_worst"] == "VERBATIM"
        assert claims[0]["quote_floor"] == ""

    def test_existing_quoted_text_not_overwritten(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path,
                      'Also has "another quote" inside.',
                      "supplied span appears right here in the opinion",
                      quoted_text=json.dumps(["supplied span appears"]))
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert json.loads(claims[0]["quoted_text"]) == [
            "supplied span appears"]

    def test_no_quotes_anywhere_still_no_quotes(self, tmp_path):
        from citation_verifier.proposition_pipeline import check_quotes
        wd = self._wd(tmp_path, "No quotation marks at all.", "text")
        check_quotes(wd)
        claims = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        assert claims[0]["quote_check_worst"] == "NO_QUOTES"
        assert claims[0]["quote_floor"] == ""
```

- [ ] **2.2 Implement** inside `check_quotes`: after parsing `quotes`, if empty, derive (`proposition` then `brief_sentence`), set `claim["quoted_text"] = json_mod.dumps(quotes)` and bump `stats.derived_quotes`. After the worst computation: `claim["quote_floor"] = "Yellow" if worst in ("CLOSE", "FABRICATED") else ""`. Add `quote_floor` to the fieldnames block alongside quote_check columns; add `derived_quotes: int = 0` to `QuoteCheckStats`. NO_OPINION rows get `quote_floor = ""`.

- [ ] **2.3 Run** new tests + `test_brief_pipeline.py::TestCheckQuotes` (legacy fixtures' propositions that contain no double-quoted spans stay NO_QUOTES; if a legacy fixture proposition *does* contain quoted spans, the new derivation is the designed behavior — update that test's expectation and say so in the commit).

- [ ] **2.4 Commit** — `feat: check_quotes derives >=2-word spans + quote_floor column (SS6.4)`

### Task 3: Floor-aware scoring

**Files:** `src/citation_verifier/scoring.py`; `tests/test_scoring.py`.

- [ ] **3.1 Failing test:** in the synthetic workdir, give t-01 `quote_floor=Yellow` while its cassette verdict says Green → prediction Yellow, and a new `floored` flag on the prediction:

```python
class TestQuoteFloor:
    def test_floor_raises_replayed_green_to_yellow(self, tmp_path):
        wd = make_workdir(tmp_path)
        # add quote_floor column: t-01 floored
        rows = list(csv.DictReader(
            (wd / "claims.csv").open(encoding="utf-8")))
        for r in rows:
            r["quote_floor"] = "Yellow" if r["claim_id"] == "t-01" else ""
        with (wd / "claims.csv").open("w", newline="",
                                      encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        # cassette says Green for t-01
        (wd / "jobs" / "assess_results.jsonl").unlink()
        append_verdict_jsonl(
            wd / "jobs" / "assess_results.jsonl",
            Verdict(claim_id="t-01",
                    fields={"assessment": "Green", "rationale": "r"},
                    model="opus", prompt_version="assess-v1"))
        ex = RecordedExecutor(wd / "jobs" / "assess_results.jsonl")
        preds = {p.claim_id: p for p in predict_workdir(wd, ex, "assess-v1")}
        assert preds["t-01"].predicted == "Yellow"
        assert preds["t-01"].floored is True

    def test_floor_never_lowers(self, tmp_path):
        # agent Red + floor Yellow stays Red
        ...  # same setup, cassette Red; assert predicted == "Red"
```

- [ ] **3.2 Implement** in `predict_workdir`: add `floored: bool = False` to `ClaimPrediction`; in the agent branch, look up the claim's `quote_floor`; with `_RANK = {GREEN: 0, YELLOW: 1, RED: 2}`, if floor and `_RANK[color] < _RANK[floor]` → use floor, `floored=True`. Deterministic lanes unaffected. (This models apply-assessments §6.4: agent may lower, never below floor... precisely: floor sets the *minimum severity*.)

- [ ] **3.3 Run; commit** — `feat: quote_floor enforcement in offline scoring (models apply-assessments)`

### Task 4: Regenerate the Withers corpus quote columns + measure

- [ ] **4.1** Add a builder step in `tests/build_assessment_corpora.py::build_withers`: after the claim_id stamping block, **re-derive quotes with the new rules** — for each claims.csv row, set `quoted_text = extract_quoted_spans(proposition)` (the corpus's quoted_text was auto-extracted at ≥4 words from the same propositions, so re-derivation from source is the honest regeneration, replacing not augmenting), then run `check_quotes(corpus_dir)` to rewrite quote_check/quote_check_worst/quote_floor. Print before/after worst-counts.
- [ ] **4.2** Run the builder; inspect the diff (`git diff --stat tests/data/assessment_corpora/withers/claims.csv` + the printed counts). Expect: Am. Auto rows (-09, -12) gain the "judicial admissions" quote; Anderson (-38) keeps CLOSE; floors appear.
- [ ] **4.3** Run the regression suite — `test_assessment_regression.py` will now FAIL (that is the point). Score the corpus, record the new numbers:
  `venv/Scripts/python.exe -m citation_verifier.scoring tests/data/assessment_corpora/withers`
  Design projection: yellows caught ≈ 15/19. Check the green guardrail: over-flags must stay ≤ 2 + only-floor-induced ones that are defensible; if greens over-flag beyond ≤2/12 + Gray, STOP and reassess (the CLOSE floor may need the report-side "Check quote" framing rather than a Yellow).
- [ ] **4.4** Update `tests/test_assessment_regression.py` with the measured numbers, docstring documenting before (12/19) → after, and which rows moved and why (floor vs extraction). Update the corpora README baselines table likewise.
- [ ] **4.5** Full offline suite; commit corpus + tests + README together — `data: Withers corpus through SS6.4 quote rules; baselines 12/19 -> <measured>`

### Task 5: Docs + push

- [ ] CLAUDE.md proposition_pipeline row: add `extract_quoted_spans`/`quote_floor`; scoring row: floor enforcement. Execution notes here. Push.

## Execution notes (2026-06-11, all tasks complete)

- **Measured result: 14/19 yellows caught (8 exact), greens 9/12 exact /
  2 over-flagged, reds 3/3** — vs the design's ~15/19 projection.
- The unbanded CLOSE floor (floor every CLOSE) hit the plan's stop
  condition: it over-flagged withers-21 (a true green whose hand-
  transcribed quotes scored CLOSE@0.79/0.80) → greens 3/12 over-flagged,
  breaching the §8 ≤2/12 guardrail. Reassessed per plan: the floor is now
  **banded** — FABRICATED always floors; CLOSE floors only when
  similarity < 0.75. The real catches sat at 0.64 (Am. Auto -09) and
  0.73 (Anderson -38); the near-verbatim band [0.75, 0.85) is dominated
  by transcription noise / bracket alterations and keeps its CLOSE
  verdict in the report without forcing Yellow. Calibration recorded in
  `proposition_pipeline._quote_floor`; revisit against the Fletcher
  corpus when it gets frozen (§7 candidate list).
- Am. Auto **-12 is not mechanically catchable**: its proposition
  paraphrases without quotation marks, so span extraction has nothing to
  extract. The design's "~3 mechanically catchable" was actually 2.
  Remaining misses (-05, -12, -32, -44, -49) are the judgment-call band —
  levers are §6.3 scoping, §6.5 crosscheck, and prompt work (Steps 4-6).
- The floor logic was extracted to a pure `_quote_floor(results)` helper
  so the band is unit-tested directly instead of through the fuzzy
  matcher.

## Self-review notes
- §6.4 bullet 1 (≥2-word extraction + per-quote verdicts): Tasks 1-2. Bullet 2 (floors, enforced at apply-assessments): the column lands in Task 2; enforcement is modeled in scoring (Task 3) and will be re-used by the real `apply-assessments` verb in Step 4. Bullet 3 (matcher normalization limits): explicitly out of scope (stays on TODO).
- The corpus regeneration is design-sanctioned (§6.4 "Withers projection") and changes only deterministic-phase columns; cassette keys (claim_id + prompt_version) untouched, so no re-record.
