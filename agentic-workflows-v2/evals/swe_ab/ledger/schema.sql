-- SQLite schema for the SWE-AB evaluation ledger.
--
-- Layout:
--   1. schema_meta                       (version marker)
--   2. reference tables                  (immutable definitions)
--   3. design tables                     (campaign / wave / plan structure)
--   4. observation tables                (append-only trial results)
--   5. append-only + invariant triggers
--   6. indexes
--
-- Timestamps are ISO-8601 UTC strings (TEXT); SQLite has no native
-- timestamp type. JSON-valued columns are TEXT holding canonical JSON.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. schema_meta
-- ---------------------------------------------------------------------

CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1');

-- ---------------------------------------------------------------------
-- 2. Reference tables (immutable definitions)
-- ---------------------------------------------------------------------

CREATE TABLE blob (
    digest TEXT PRIMARY KEY,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    retention TEXT NOT NULL CHECK (retention IN ('durable', 'prunable')),
    stored_at TEXT NOT NULL
);

CREATE TABLE model (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    wire_ref TEXT NOT NULL,
    family TEXT NOT NULL,
    params_b REAL,
    quantization TEXT,
    context_window INTEGER,
    serving_mode TEXT NOT NULL
        CHECK (serving_mode IN ('hosted', 'local_gpu', 'local_cpu')),
    weights_probe TEXT,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE price_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES model (model_id),
    observed_at TEXT NOT NULL,
    price_in REAL,
    price_out REAL,
    source TEXT NOT NULL
);

CREATE TABLE prompt (
    prompt_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    text_digest TEXT NOT NULL REFERENCES blob (digest)
);

CREATE TABLE workflow (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    yaml_digest TEXT NOT NULL,
    step_count INTEGER NOT NULL
);

CREATE TABLE workflow_prompt (
    workflow_id TEXT NOT NULL REFERENCES workflow (workflow_id),
    prompt_id TEXT NOT NULL REFERENCES prompt (prompt_id),
    PRIMARY KEY (workflow_id, prompt_id)
);

CREATE TABLE grader (
    grader_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN ('deterministic', 'judge', 'composite')),
    module_digest TEXT NOT NULL,
    rubric_id TEXT
);

CREATE TABLE judge_calibration (
    calibration_id TEXT PRIMARY KEY,
    grader_id TEXT NOT NULL REFERENCES grader (grader_id),
    judge_model_id TEXT NOT NULL REFERENCES model (model_id),
    tnr REAL NOT NULL,
    tpr REAL NOT NULL,
    wilson_lower REAL NOT NULL,
    n INTEGER NOT NULL,
    calibrated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE image (
    image_id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    tag TEXT,
    digest TEXT NOT NULL CHECK (digest LIKE 'sha256:%'),
    pulled_at TEXT NOT NULL
);

CREATE TABLE task_set (
    task_set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    revision TEXT NOT NULL,
    filter_expr TEXT,
    row_count INTEGER NOT NULL,
    licence TEXT,
    built_at TEXT NOT NULL
);

CREATE TABLE task (
    task_id TEXT PRIMARY KEY,
    task_set_id TEXT NOT NULL REFERENCES task_set (task_set_id),
    instance_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    target_file TEXT NOT NULL,
    image_id TEXT NOT NULL REFERENCES image (image_id),
    fail_to_pass TEXT NOT NULL,
    difficulty TEXT,
    contamination_risk TEXT,
    safe_after TEXT,
    problem_blob TEXT REFERENCES blob (digest),
    source_blob TEXT REFERENCES blob (digest),
    max_changed_lines INTEGER,
    UNIQUE (task_set_id, instance_id)
);

-- ---------------------------------------------------------------------
-- 3. Design tables
-- ---------------------------------------------------------------------

CREATE TABLE substrate (
    substrate_id TEXT PRIMARY KEY,
    task_set_id TEXT NOT NULL REFERENCES task_set (task_set_id),
    harness_version TEXT NOT NULL,
    runtime_digest TEXT NOT NULL,
    evalkit_version TEXT NOT NULL,
    grader_id TEXT NOT NULL REFERENCES grader (grader_id),
    image_digest_set TEXT NOT NULL
);

CREATE TABLE arm_config (
    arm_config_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES model (model_id),
    temperature REAL,
    top_p REAL,
    top_k INTEGER,
    max_tokens INTEGER,
    seed INTEGER,
    stop_sequences TEXT,
    context_window_used INTEGER,
    workflow_id TEXT NOT NULL REFERENCES workflow (workflow_id),
    retrieval_mode TEXT NOT NULL
        CHECK (retrieval_mode IN ('oracle', 'agentic_search')),
    tool_policy TEXT
);

CREATE TABLE campaign (
    campaign_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    question TEXT NOT NULL,
    primary_contrast TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'abandoned'))
);

CREATE TABLE arm (
    arm_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaign (campaign_id),
    arm_key TEXT NOT NULL,
    arm_config_id TEXT NOT NULL REFERENCES arm_config (arm_config_id),
    role TEXT NOT NULL
        CHECK (role IN ('control', 'treatment', 'exploratory')),
    UNIQUE (campaign_id, arm_key)
);

CREATE TABLE wave (
    wave_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaign (campaign_id),
    wave_no INTEGER NOT NULL,
    substrate_id TEXT NOT NULL REFERENCES substrate (substrate_id),
    stratification TEXT,
    planned_runs INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    UNIQUE (campaign_id, wave_no)
);

CREATE TABLE wave_task (
    wave_id TEXT NOT NULL REFERENCES wave (wave_id),
    task_id TEXT NOT NULL REFERENCES task (task_id),
    PRIMARY KEY (wave_id, task_id)
);

CREATE TABLE plan_cell (
    wave_id TEXT NOT NULL REFERENCES wave (wave_id),
    arm_id TEXT NOT NULL REFERENCES arm (arm_id),
    task_id TEXT NOT NULL REFERENCES task (task_id),
    run_idx INTEGER NOT NULL CHECK (run_idx >= 1),
    status TEXT NOT NULL
        CHECK (status IN ('planned', 'done', 'abandoned')),
    PRIMARY KEY (wave_id, arm_id, task_id, run_idx)
);

-- ---------------------------------------------------------------------
-- 4. Observation tables (append-only)
-- ---------------------------------------------------------------------

CREATE TABLE trial (
    wave_id TEXT NOT NULL,
    arm_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    run_idx INTEGER NOT NULL,
    trial_id TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL,
    substrate_id TEXT NOT NULL REFERENCES substrate (substrate_id),
    arm_config_id TEXT NOT NULL REFERENCES arm_config (arm_config_id),
    model_id TEXT NOT NULL REFERENCES model (model_id),
    models_answered TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    wall_seconds REAL,
    op_status TEXT NOT NULL CHECK (
        op_status IN
        ('ok', 'error', 'timeout', 'cancelled', 'unavailable', 'abstain')
    ),
    error_kind TEXT,
    error_blob TEXT REFERENCES blob (digest),
    tokens_in INTEGER,
    tokens_out INTEGER,
    trace_id TEXT NOT NULL,
    transcript_blob TEXT REFERENCES blob (digest),
    answer_blob TEXT REFERENCES blob (digest),
    supersedes TEXT REFERENCES trial (trial_id),
    PRIMARY KEY (wave_id, arm_id, task_id, run_idx),
    FOREIGN KEY (wave_id) REFERENCES wave (wave_id),
    FOREIGN KEY (arm_id) REFERENCES arm (arm_id),
    FOREIGN KEY (task_id) REFERENCES task (task_id),
    CHECK (tokens_in IS NULL OR tokens_in >= 0),
    CHECK (tokens_out IS NULL OR tokens_out >= 0),
    CHECK (wall_seconds IS NULL OR wall_seconds >= 0),
    CHECK (run_idx >= 1)
);

CREATE TABLE step_usage (
    trial_id TEXT NOT NULL REFERENCES trial (trial_id),
    step_idx INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    model_id TEXT REFERENCES model (model_id),
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms REAL,
    status TEXT,
    PRIMARY KEY (trial_id, step_idx)
);

CREATE TABLE spend (
    spend_id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL REFERENCES trial (trial_id),
    price_snapshot_id TEXT REFERENCES price_snapshot (snapshot_id),
    cost_usd REAL,
    gpu_seconds REAL,
    computed_at TEXT NOT NULL
);

CREATE TABLE grade (
    grade_id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL REFERENCES trial (trial_id),
    grader_id TEXT NOT NULL REFERENCES grader (grader_id),
    status TEXT NOT NULL
        CHECK (status IN ('pass', 'fail', 'abstain', 'unavailable', 'error')),
    outcome TEXT CHECK (outcome IN ('pass', 'fail')),
    score REAL,
    evidence_blob TEXT REFERENCES blob (digest),
    oracle_provenance TEXT,
    graded_at TEXT NOT NULL,
    supersedes TEXT REFERENCES grade (grade_id),
    CHECK ((outcome IS NULL) = (status NOT IN ('pass', 'fail'))),
    CHECK (outcome IS NULL OR outcome = status)
);

-- ---------------------------------------------------------------------
-- 5. Triggers
-- ---------------------------------------------------------------------

-- 5a. Append-only enforcement: trial, grade, spend, step_usage may only
-- ever be inserted into. Corrections happen by inserting a new row that
-- supersedes the old one, never by mutating or removing history.

CREATE TRIGGER trg_trial_no_update
BEFORE UPDATE ON trial
BEGIN
    SELECT RAISE(ABORT, 'trial is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_trial_no_delete
BEFORE DELETE ON trial
BEGIN
    SELECT RAISE(ABORT, 'trial is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_grade_no_update
BEFORE UPDATE ON grade
BEGIN
    SELECT RAISE(ABORT, 'grade is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_grade_no_delete
BEFORE DELETE ON grade
BEGIN
    SELECT RAISE(ABORT, 'grade is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_spend_no_update
BEFORE UPDATE ON spend
BEGIN
    SELECT RAISE(ABORT, 'spend is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_spend_no_delete
BEFORE DELETE ON spend
BEGIN
    SELECT RAISE(ABORT, 'spend is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_step_usage_no_update
BEFORE UPDATE ON step_usage
BEGIN
    SELECT RAISE(ABORT, 'step_usage is append-only; insert a superseding row instead');
END;

CREATE TRIGGER trg_step_usage_no_delete
BEFORE DELETE ON step_usage
BEGIN
    SELECT RAISE(ABORT, 'step_usage is append-only; insert a superseding row instead');
END;

-- 5b. Substrate match: a trial's substrate_id must match the substrate_id
-- recorded on the wave it belongs to. If wave_id does not reference an
-- existing wave, the subquery yields NULL and the WHEN condition is NULL
-- (not TRUE), so this trigger stays silent and the subsequent foreign-key
-- check on trial.wave_id is what rejects the insert.

CREATE TRIGGER trg_trial_substrate_match
BEFORE INSERT ON trial
WHEN NEW.substrate_id <> (
    SELECT substrate_id FROM wave WHERE wave_id = NEW.wave_id
)
BEGIN
    SELECT RAISE(ABORT, 'trial.substrate_id must match its wave');
END;

-- 5c. No grade on a failed trial: an operational failure (anything but
-- op_status='ok') means no verdict was ever rendered, so no grade row may
-- exist for it at all. As above, an unknown trial_id leaves the WHEN
-- condition NULL and is instead caught by the foreign-key constraint.

CREATE TRIGGER trg_grade_requires_ok_trial
BEFORE INSERT ON grade
WHEN (
    SELECT op_status FROM trial WHERE trial_id = NEW.trial_id
) <> 'ok'
BEGIN
    SELECT RAISE(ABORT, 'cannot grade a trial whose op_status is not ok');
END;

-- ---------------------------------------------------------------------
-- 6. Indexes
-- ---------------------------------------------------------------------

CREATE INDEX idx_trial_wave_arm ON trial (wave_id, arm_id);
CREATE INDEX idx_trial_task ON trial (task_id);
CREATE INDEX idx_grade_trial ON grade (trial_id);
CREATE INDEX idx_step_usage_trial ON step_usage (trial_id);
CREATE INDEX idx_spend_trial ON spend (trial_id);
CREATE INDEX idx_plan_cell_wave_status ON plan_cell (wave_id, status);
CREATE INDEX idx_task_task_set ON task (task_set_id);
