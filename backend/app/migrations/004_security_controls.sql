-- Phase 3.4: persistent abuse controls and recognition idempotency.

CREATE TABLE security_limit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    occurred_at INTEGER NOT NULL
);

CREATE INDEX idx_security_limit_lookup
ON security_limit_events(action, subject, occurred_at);

CREATE TABLE recognition_idempotency (
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key  TEXT NOT NULL,
    scan_id          TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    status           TEXT NOT NULL CHECK (status IN ('started', 'completed')),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (user_id, idempotency_key)
);

CREATE INDEX idx_recognition_idempotency_scan
ON recognition_idempotency(scan_id);
