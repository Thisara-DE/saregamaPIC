-- Phase 2: recognition cost metrics on transcriptions.
-- Populated when a draft comes from the Claude vision call; NULL for a
-- manually-typed transcription. Lets us measure "API cost per scan" (Phase 2
-- exit criterion) without a separate table.

ALTER TABLE transcriptions ADD COLUMN model         TEXT;
ALTER TABLE transcriptions ADD COLUMN input_tokens  INTEGER;
ALTER TABLE transcriptions ADD COLUMN output_tokens INTEGER;

-- One current transcription per scan (recognize/save upsert this row).
CREATE UNIQUE INDEX idx_transcriptions_scan_unique ON transcriptions(scan_id);
