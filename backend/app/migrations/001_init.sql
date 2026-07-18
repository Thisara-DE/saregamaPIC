-- Schema v1 — mirrors the data model in the technical design doc.
-- transcriptions.stf_json holds canonical STF (ALWAYS the original scale;
-- transposed/Western views are derived at read time, never stored).

CREATE TABLE songs (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE scans (
    id           TEXT PRIMARY KEY,
    song_id      TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    page_no      INTEGER NOT NULL,
    image_path   TEXT NOT NULL,  -- relative to DATA_DIR, e.g. images/<song>/<scan>.jpg
    content_type TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_scans_song ON scans(song_id, page_no);

CREATE TABLE transcriptions (
    id         TEXT PRIMARY KEY,
    scan_id    TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    stf_json   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('draft', 'reviewed')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_transcriptions_scan ON transcriptions(scan_id);
