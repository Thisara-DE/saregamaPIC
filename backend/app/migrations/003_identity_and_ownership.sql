-- Phase 3.4: provider-neutral identities, opaque server sessions, and
-- explicit ownership. Existing single-user data belongs to the initial owner;
-- startup configuration replaces the placeholder email before auth is enabled.

CREATE TABLE users (
    id           TEXT PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL CHECK (status IN ('invited', 'active', 'disabled')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO users (id, email, display_name, status)
VALUES ('00000000000000000000000000000001', 'initial-owner@invalid.local',
        'Initial owner', 'invited');

CREATE TABLE identities (
    provider   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (provider, subject)
);

CREATE INDEX idx_identities_user ON identities(user_id);

CREATE TABLE sessions (
    id_hash    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_sessions_user ON sessions(user_id, expires_at);

-- SQLite cannot ADD a non-null REFERENCES column to a populated table.
-- Rebuild songs so the ownership constraint is real from the first migration.
PRAGMA foreign_keys = OFF;

CREATE TABLE songs_with_owner (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    owner_id   TEXT NOT NULL REFERENCES users(id)
);

INSERT INTO songs_with_owner (id, title, notes, created_at, owner_id)
SELECT id, title, notes, created_at, '00000000000000000000000000000001'
FROM songs;

DROP TABLE songs;
ALTER TABLE songs_with_owner RENAME TO songs;

PRAGMA foreign_keys = ON;

CREATE INDEX idx_songs_owner_created ON songs(owner_id, created_at DESC);
