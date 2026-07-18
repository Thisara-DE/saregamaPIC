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

export interface Health {
  status: string;
  version: string;
}
