// Thin typed fetch wrapper. All paths are same-origin /api/* — the Vite dev
// server proxies them to FastAPI, so no CORS and no base-URL configuration.

import type {
  AuthUser,
  Health,
  Scan,
  Song,
  SongDetail,
  Stf,
  Transcription,
  TranscriptionStatus,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function getCurrentUser(): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me");
}

export function logout(): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST" });
}

export function listSongs(): Promise<Song[]> {
  return request<Song[]>("/api/songs");
}

export function getSong(id: string): Promise<SongDetail> {
  return request<SongDetail>(`/api/songs/${id}`);
}

export function createSong(title: string, notes = ""): Promise<Song> {
  return request<Song>("/api/songs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, notes }),
  });
}

export function uploadScan(songId: string, file: File): Promise<Scan> {
  const form = new FormData();
  form.append("file", file);
  return request<Scan>(`/api/songs/${songId}/scans`, {
    method: "POST",
    body: form,
  });
}

export function deleteSong(id: string): Promise<void> {
  return request<void>(`/api/songs/${id}`, { method: "DELETE" });
}

export function deleteScan(id: string): Promise<void> {
  return request<void>(`/api/scans/${id}`, { method: "DELETE" });
}

// --- Transcriptions (STF) ---

export function getTranscription(scanId: string): Promise<Transcription> {
  return request<Transcription>(`/api/scans/${scanId}/transcription`);
}

export function recognizeScan(scanId: string): Promise<Transcription> {
  return request<Transcription>(`/api/scans/${scanId}/recognize`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export function saveTranscription(
  scanId: string,
  stf: Stf,
  status: TranscriptionStatus,
): Promise<Transcription> {
  return request<Transcription>(`/api/scans/${scanId}/transcription`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stf, status }),
  });
}

export function scanImageUrl(scanId: string): string {
  return `/api/scans/${scanId}/image`;
}

export function scanThumbnailUrl(scanId: string): string {
  return `/api/scans/${scanId}/thumbnail`;
}

// Downscaled copy for the correction editor — legible marks without the
// full-res original's sluggishness. The viewer still uses scanImageUrl.
export function scanPreviewUrl(scanId: string): string {
  return `/api/scans/${scanId}/preview`;
}
