-- ============ Entities ============

CREATE TABLE cases (
    cluster_id          INTEGER PRIMARY KEY,         -- CourtListener cluster ID
    canonical_name      TEXT NOT NULL,
    court_id            TEXT,                        -- CL court abbrev (e.g. 'scotus', 'ca9', 'almd')
    year                INTEGER,
    system              TEXT,                        -- courts-db: federal|state|tribal|extraterritorial|special
    level               TEXT,                        -- courts-db: colr|iac|gjc|ljc|trial
    cite_string         TEXT,                        -- canonical reporter citation
    first_seen_run_id   TEXT,
    first_seen_at       TEXT NOT NULL                -- ISO 8601
);
CREATE INDEX idx_cases_court        ON cases(court_id);
CREATE INDEX idx_cases_system_level ON cases(system, level);

CREATE TABLE propositions (
    proposition_id      TEXT PRIMARY KEY,            -- sha256(normalized_text)
    text                TEXT NOT NULL,               -- raw text as mined
    normalized_text     TEXT NOT NULL,               -- whitespace-collapsed, lowercased
    holding_verb        TEXT,                        -- 'holding' | 'finding' | ...
    first_seen_run_id   TEXT,
    first_seen_at       TEXT NOT NULL
);

CREATE TABLE datasets (
    name                  TEXT PRIMARY KEY,          -- 'v1', 'v2', ...
    mining_window_start   DATE,
    mining_window_end     DATE,
    mined_courts          TEXT,                      -- JSON array of court IDs
    n_rows                INTEGER,
    frozen_at             TEXT,                      -- ISO 8601 when sealed
    git_commit            TEXT,                      -- citation-verifier commit at freeze
    notes                 TEXT
);

-- ============ Edges ============

-- A row from a real opinion: citing case cites cited case for a proposition.
CREATE TABLE citation_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_cluster_id   INTEGER NOT NULL REFERENCES cases(cluster_id),
    cited_cluster_id    INTEGER NOT NULL REFERENCES cases(cluster_id),
    proposition_id      TEXT    NOT NULL REFERENCES propositions(proposition_id),
    parenthetical       TEXT    NOT NULL,
    dataset_name        TEXT             REFERENCES datasets(name),
    mined_at            TEXT    NOT NULL,
    UNIQUE (citing_cluster_id, cited_cluster_id, proposition_id)
);
CREATE INDEX idx_citation_rows_proposition ON citation_rows(proposition_id);
CREATE INDEX idx_citation_rows_dataset     ON citation_rows(dataset_name);

-- Verdict: does this case support this proposition?
-- Polymorphic across gold-pair self-scores, model-answer scores, and probes.
CREATE TABLE assessor_verdicts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    proposition_id           TEXT    NOT NULL REFERENCES propositions(proposition_id),
    candidate_cluster_id     INTEGER NOT NULL REFERENCES cases(cluster_id),
    verdict                  TEXT    NOT NULL,
    assessor_model           TEXT    NOT NULL,
    assessor_prompt_version  TEXT    NOT NULL,
    opinion_window_chars     INTEGER,
    confidence               REAL,
    reasoning_excerpt        TEXT,
    source                   TEXT    NOT NULL,
    run_id                   TEXT,
    assessed_at              TEXT    NOT NULL,
    UNIQUE (proposition_id, candidate_cluster_id, assessor_model, assessor_prompt_version, opinion_window_chars)
);
CREATE INDEX idx_verdicts_prop_case ON assessor_verdicts(proposition_id, candidate_cluster_id);

-- A model's answer to a proposition during a specific run.
CREATE TABLE model_answers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    proposition_id        TEXT    NOT NULL REFERENCES propositions(proposition_id),
    answer_cluster_id     INTEGER          REFERENCES cases(cluster_id),
    model_name            TEXT    NOT NULL,
    raw_response          TEXT    NOT NULL,
    parse_status          TEXT    NOT NULL,
    answered_cite_string  TEXT,
    cite_resolved_real    BOOLEAN,
    name_match_score      REAL,
    run_id                TEXT    NOT NULL,
    answered_at           TEXT    NOT NULL
);
CREATE INDEX idx_answers_prop ON model_answers(proposition_id);
CREATE INDEX idx_answers_run  ON model_answers(run_id);

-- ============ Run metadata ============

CREATE TABLE runs (
    run_id      TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    git_commit  TEXT,
    notes       TEXT
);
