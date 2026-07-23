-- Phase 3.5: preserve recognition attempts and human corrections.
-- recognition_runs.raw_stf_json is the model's immutable output. The existing
-- transcriptions row remains the current materialized view used by the app.

CREATE TABLE recognition_runs (
    id                    TEXT PRIMARY KEY,
    scan_id               TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preprocessing_version TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    model                 TEXT,
    suggested_title       TEXT,
    raw_stf_json          TEXT,
    warnings_json         TEXT NOT NULL DEFAULT '[]',
    input_tokens          INTEGER,
    output_tokens         INTEGER,
    latency_ms            INTEGER NOT NULL,
    outcome               TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
    error_code            TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_recognition_runs_scan_created
ON recognition_runs(scan_id, created_at);

CREATE INDEX idx_recognition_runs_user_created
ON recognition_runs(user_id, created_at);

CREATE TABLE transcription_revisions (
    id                      TEXT PRIMARY KEY,
    transcription_id        TEXT NOT NULL REFERENCES transcriptions(id) ON DELETE CASCADE,
    recognition_run_id      TEXT REFERENCES recognition_runs(id) ON DELETE SET NULL,
    stf_json                TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('draft', 'reviewed')),
    source                  TEXT NOT NULL CHECK (source IN ('recognition', 'manual')),
    correction_summary_json TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_transcription_revisions_transcription_created
ON transcription_revisions(transcription_id, created_at);

ALTER TABLE transcriptions ADD COLUMN recognition_run_id
    TEXT REFERENCES recognition_runs(id) ON DELETE SET NULL;

ALTER TABLE transcriptions ADD COLUMN current_revision_id
    TEXT REFERENCES transcription_revisions(id) ON DELETE SET NULL;

ALTER TABLE recognition_idempotency ADD COLUMN recognition_run_id
    TEXT REFERENCES recognition_runs(id) ON DELETE SET NULL;

-- Preserve the current snapshot for legacy/manual transcriptions. We cannot
-- truthfully reconstruct a historical model run, so these are manual revisions
-- with no recognition_run_id and are excluded from recognition baselines.
INSERT INTO transcription_revisions
    (id, transcription_id, stf_json, status, source)
SELECT lower(hex(randomblob(16))), id, stf_json, status, 'manual'
FROM transcriptions;

UPDATE transcriptions
SET current_revision_id = (
    SELECT tr.id
    FROM transcription_revisions tr
    WHERE tr.transcription_id = transcriptions.id
    ORDER BY tr.created_at DESC
    LIMIT 1
);
