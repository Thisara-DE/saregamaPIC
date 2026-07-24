// Mirrors backend/app/schemas.py — keep the two in sync by hand (the API is
// small; add a generated client only if it grows past a handful of routes).

export interface Song {
  id: string;
  title: string;
  notes: string;
  created_at: string;
  scan_count: number;
  // First page's scan id (null when the song has no pages yet) — the
  // gallery uses it to show a cover thumbnail without fetching details.
  cover_scan_id: string | null;
  // First page that has a transcription (null when nothing is transcribed yet).
  // Lets the gallery link straight to the digital view, and disable that link,
  // without fetching every page's transcription.
  digital_page_no: number | null;
}

export interface Scan {
  id: string;
  song_id: string;
  page_no: number;
  content_type: string;
  uploaded_at: string;
}

export interface SongDetail extends Song {
  scans: Scan[];
}

export interface SongImport {
  song: Song;
  scan: Scan;
}

export interface Health {
  status: string;
  version: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

// --- Transcriptions (STF) — mirror backend/app/schemas.py by hand ---

export interface StfHeader {
  concert_scale: string;
  alto_scale: string;
  beat: string;
}

// kind: section | sargam | run | lyric | roadmap | annotation
export interface StfLine {
  n: number;
  kind: string;
  text: string;
}

export interface Stf {
  header: StfHeader;
  lines: StfLine[];
}

export type TranscriptionStatus = "draft" | "reviewed";

export interface Transcription {
  id: string;
  scan_id: string;
  status: TranscriptionStatus;
  stf: Stf;
  warnings: string[];
  // Recognition cost metrics (null for a manually-typed transcription).
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  updated_at: string;
}
