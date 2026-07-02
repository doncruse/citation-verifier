# `claims.csv` schema (version 1)

`claims.csv` is the master state file of a proposition-verification workdir
(`matters/<name>/claims.csv`). It is produced and progressively enriched by the
idempotent verbs in
[`src/citation_verifier/proposition_pipeline.py`](../src/citation_verifier/proposition_pipeline.py).
Each verb reads the file, adds or fills its columns, and writes it back; no verb
removes a column, so a fully-processed row is a superset of an extracted row.

This document is the **external contract** for that file. It is consumed
downstream by the `memo-import` skill in `us-legal-research` (see the
"Upstream asks" section of that project's
`docs/superpowers/specs/2026-07-02-memo-import-design.md`). It describes the
columns **as the code writes them today** — it does not propose changes.

## Versioning

The version of this contract is the module constant
`proposition_pipeline.CLAIMS_SCHEMA_VERSION` (currently `1`). Every verb stamps
it into the workdir's `run.json` as the top-level `schema_version` key via
`_update_run_json`, so a consumer can read `run.json` and detect a mismatch
before parsing `claims.csv`:

```json
{
  "schema_version": 1,
  "git_hash": "7e4df32",
  "verbs": { "merge": { "at": "2026-07-02T…", "matched": 12, "linked": 9 } }
}
```

Bump `CLAIMS_SCHEMA_VERSION` (and this doc) when a column is renamed, removed,
or its meaning / allowed values change. Adding a new column is
backward-compatible for dict-keyed consumers and does **not** require a bump,
but noting it here is expected.

## File format

- UTF-8, standard CSV with a header row (`csv.DictReader` / `csv.DictWriter`).
- **Every value is a string.** The "Type" column below describes the *semantic*
  type; JSON-typed columns hold a JSON document serialized into the cell (parse
  with `json.loads`). An empty cell (`""`) is the universal "absent / not yet
  computed" value.
- Column **order** is not part of the contract — always key by column name.
  (Order in practice follows production order: extract columns first, then each
  verb appends its new columns.)
- **Row identity** is `claim_id`. **Citation join key** (to
  `verification_results.csv`) is `cited_case`, pinpoint-stripped and normalized.

## Columns by producing verb

### `extract` — initial rows (prompt `extract-v1`)

Writes the seven base columns. (Prepared-pairs workdirs may supply `claims.csv`
directly, in which case `extract` no-ops and these columns come from the input.)

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `claim_id` | string | `<workdir-name>-NN`, zero-padded (e.g. `my-brief-00`) | Stable row identity; also the resume/join key for LLM verdicts in `jobs/*_results.jsonl`. |
| `page` | string | free text; may be empty | Page / location reference in the source document. |
| `proposition` | string | free text; **required, non-empty** | The proposition the case is cited for. |
| `cited_for` | string | free text; may be empty | The "judge this" instruction (design §6.3) — what the case is offered to establish. |
| `cited_case` | string | `<case name>, <reporter cite> (<year>)`; **required, non-empty** | The citation as written. Join key to `verification_results.csv`. |
| `quoted_text` | JSON array of string | e.g. `["judicial admissions"]`; default `"[]"` | Double-quoted spans from the brief. **May be rewritten by `check-quotes`** when empty (derived ≥2-word spans from `proposition` / `brief_sentence`). |
| `brief_sentence` | string | free text; may be empty | The surrounding brief sentence + parenthetical. |

### `merge` — verification join + opinion linkage

Overlays verification results from `verification_results.csv` and links each
claim to its downloaded opinion file. Carries every pre-existing column through
unchanged. Introduces:

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `retrieved_case` | string | CL matched case name; `""` if unmatched | From the vr `matched_name`. |
| `cl_url` | string | CourtListener URL; `""` if unmatched | Matched opinion / cluster URL. |
| `cl_status` | string | a `Status` enum value, or `""` | One of: `VERIFIED`, `VERIFIED_PARTIAL`, `VERIFIED_VIA_RECAP`, `VERIFIED_DOCKET_ONLY`, `WRONG_CASE`, `CITE_UNCONFIRMED`, `NOT_FOUND`, `VERIFICATION_INCOMPLETE`, `INSUFFICIENT_DATA`. `""` = the citation matched no vr row. Drives report lanes. |
| `diagnostics` | string | free text; `""` if none | Joined verifier warning messages + stage notes (vr `diagnostics_msg`). |
| `opinion_file` | string | workdir-relative path, e.g. `opinions/Smith_v_Jones.txt`; `""` if none | Slug-token-linked opinion text file. Empty → the claim cannot be assessed (Gray "unable to verify" lane). |
| `syllabus` | string | free text; `""` if none | Syllabus / nature-of-suit text (vr `syllabus`). |
| `supporting_language` | string | free text; `""` | Optional supporting-language field (created empty; may be filled by legacy flows). Report uses it for the Green card and Gray-card explanation. |
| `assessment` | string | created empty here | The final color column. **Value is set by `apply-assessments`** (see below); `merge` only guarantees the column exists. |

### `check-quotes` — deterministic quote verdicts

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `quote_check` | JSON array of object | each object: `{"quote": str, "result": str, "similarity": float, "matched_passage"?: str}`; `"[]"` when no quotes / no opinion | `result` ∈ `VERBATIM` \| `CLOSE` \| `FABRICATED`; `similarity` in `[0.0, 1.0]`; `matched_passage` present only when a passage was located. |
| `quote_check_worst` | string | `VERBATIM` \| `CLOSE` \| `FABRICATED` \| `NO_QUOTES` \| `NO_OPINION` | Worst per-quote result, or a sentinel when nothing could be checked. |
| `quote_floor` | string | `""` \| `Yellow` | Design §6.4 floor: any `FABRICATED` quote, or a `CLOSE` quote with similarity < 0.75, forces `Yellow` (`apply-assessments` enforces it — an agent may lower a color but never raise it past the floor). |

(May also rewrite `quoted_text`, as noted under `extract`.)

### `crosscheck` — deterministic flags (never colors)

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `crosscheck_flags` | JSON object | keys: `toa_mismatch`, `court_mismatch`, `pincite_flag` (any subset); `""` when clean | Design §6.5 flags. `toa_mismatch: {variants: [str]}`; `court_mismatch: {cited, cited_id, matched_id, matched}`; `pincite_flag: {pinpoint?, star_range?: [lo, hi], footnote_missing?}`. Flags surface as report chips but **never move a claim's lane or color**. |

### `triage` — assessment depth

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `triage_track` | string | `full` \| `fast` \| `""` | Design §6.7 depth. `""` = deterministic lane (not agent-assessable — no opinion, or resolved to the wrong case). |

### `assess` — no `claims.csv` columns

The `assess` verb **reads** `claims.csv` but writes LLM verdicts to
`jobs/assess_results.jsonl`, not to `claims.csv`. Its output reaches
`claims.csv` only through `apply-assessments`.

### `apply-assessments` — fold verdicts back in

Fills `assessment` and writes the agent-authored narrative columns for
assessable claims. For assess-v2 verdicts the color is derived by
`scoring.derive_color(cl_status, support, quote_axis)`; for assess-v1 it is the
agent's own color. In both cases the §6.4 quote floor is enforced.

| Column | Type | Allowed values / format | Notes |
|--------|------|-------------------------|-------|
| `assessment` | string | `Green` \| `Yellow` \| `Red` \| `""` | Final, floor-enforced color. `""` for claims that were never assessed (report lanes still route these deterministically off `cl_status` / `opinion_file`). |
| `support` | string | `supported` \| `partial` \| `unsupported` \| `unverifiable` \| `""` | Support axis. assess-v2 fills it; assess-v1 leaves it `""` (unless the agent supplied one). |
| `assessed_by` | string | `<model>/<prompt_version>`, e.g. `claude-opus-4-8/assess-v2`; `""` if unassessed | Verdict provenance. |
| `finding_analysis` | string | free text; `""` | Agent's prose analysis (assess-v2) or rationale (assess-v1). |
| `badge_label` | string | free text; `""` | Report badge, e.g. `Supported`, `Not supported by cited case`, `Case on unrelated subject`. The report may override it for the Check Cite lane. |
| `brief_block` | string | free text; `""` | Orange-box quote from the brief. Defaults to `brief_sentence` when the verdict omits it. |
| `opinion_block` | string | free text; `""` | Green-box opinion passage. Intentionally empty for pure topic-mismatch / wrong-case reds. |

### `report` — reads only

`report` renders `claims.csv` → `report.html` and writes **no** columns. It
reads the columns above plus the tolerated legacy columns below.

## Tolerated legacy columns

These are **read as fallbacks** but are not written by any current verb. They
appear only in older workdirs. Consumers may ignore them.

| Column | Type | Notes |
|--------|------|-------|
| `prescreen_hint` | string | Former Haiku prescreen hint. The prescreen path was removed (cost-audit F4, 2026-07-02); the column is carried through if present but nothing populates it. |
| `opinion_text` | string | Legacy two-field analysis schema; read by `report` as a `finding_analysis` fallback. |
| `explanation` | string | Legacy two-field analysis schema; read by `report` as a `finding_analysis` fallback. |

## Related files in the workdir

`claims.csv` is the contract surface, but the pipeline also writes siblings a
consumer may care about:

- `run.json` — reproducibility stamp; carries `schema_version` and per-verb records.
- `verification_results.csv` — raw verifier output that `merge` joins in (its own column set; not covered here).
- `citations_toa.txt` / `citations_body.txt` — extract's citation lists (one per line).
- `opinions/` — downloaded opinion text referenced by `opinion_file`.
- `report.html` — the human-facing deliverable.
