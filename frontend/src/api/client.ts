// Thin typed fetch wrapper. All paths are same-origin /api/* — the Vite dev
// server proxies them to FastAPI, so no CORS and no base-URL configuration.

import { invalidateCached } from "../offline";
import type {
  AdminUser,
  AuthUser,
  Health,
  LineBands,
  Scan,
  Song,
  SongDetail,
  SongImport,
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

// --- Access management (admin only, finding #18) ---

export function listUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>("/api/auth/users");
}

export function inviteUser(email: string): Promise<AdminUser> {
  return request<AdminUser>("/api/auth/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export function listSongs(): Promise<Song[]> {
  return request<Song[]>("/api/songs");
}

export function getSong(id: string): Promise<SongDetail> {
  return request<SongDetail>(`/api/songs/${id}`);
}

// Writes that change cached read data evict the affected GET entries after they
// succeed (finding F21). With no network timeout on the read-data cache a stale
// entry is only served when genuinely offline, but a mutation made just before
// going offline would otherwise still read back the pre-change copy.

export async function createSong(title: string, notes = ""): Promise<Song> {
  const song = await request<Song>("/api/songs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, notes }),
  });
  await invalidateCached(["/api/songs"]);
  return song;
}

export async function importSong(file: File, title = ""): Promise<SongImport> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  const imported = await request<SongImport>("/api/songs/import", {
    method: "POST",
    body: form,
  });
  await invalidateCached(["/api/songs"]);
  return imported;
}

export async function uploadScan(songId: string, file: File): Promise<Scan> {
  const form = new FormData();
  form.append("file", file);
  const scan = await request<Scan>(`/api/songs/${songId}/scans`, {
    method: "POST",
    body: form,
  });
  await invalidateCached([`/api/songs/${songId}`, "/api/songs"]);
  return scan;
}

export async function renameSong(id: string, title: string): Promise<Song> {
  const song = await request<Song>(`/api/songs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await invalidateCached([`/api/songs/${id}`, "/api/songs"]);
  return song;
}

export async function deleteSong(id: string): Promise<void> {
  await request<void>(`/api/songs/${id}`, { method: "DELETE" });
  await invalidateCached([`/api/songs/${id}`, "/api/songs"]);
}

export async function deleteScan(id: string): Promise<void> {
  await request<void>(`/api/scans/${id}`, { method: "DELETE" });
  // The scan's own transcription entry is now dead; the parent song detail also
  // changes, but its id isn't known here, so evict the list it appears on.
  await invalidateCached([`/api/scans/${id}/transcription`, "/api/songs"]);
}

// --- Transcriptions (STF) ---

export function getTranscription(scanId: string): Promise<Transcription> {
  return request<Transcription>(`/api/scans/${scanId}/transcription`);
}

const RECOGNITION_RECOVERY_POLL_MS = 2_000;
// Budget for the recovery poll ALONE, measured from the interruption. It is not
// a budget for the whole call: recognition itself regularly runs past this, and
// timing from the start of the call meant a slow recognition — precisely the
// case recovery exists for — reached its first retry with the budget spent.
const RECOGNITION_RECOVERY_TIMEOUT_MS = 240_000;
const RECOGNITION_IN_PROGRESS = "Recognition with this Idempotency-Key is in progress";
// Giving up on the poll does not mean the work failed: the server is still
// writing the draft. Say that, rather than surfacing the internal 409 text.
const RECOGNITION_STILL_RUNNING =
  "Recognition is taking longer than usual, but it is still running. " +
  "Reopen this page shortly and the draft should be waiting.";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * Recognition can outlive an infrastructure request timeout. Replaying the
 * same idempotency key is safe: the backend returns the completed draft
 * without calling the model again, or reports that the original call is still
 * running. Keep polling that action instead of showing a false network failure.
 */
export async function recognizeScan(
  scanId: string,
  onRecovering?: () => void,
): Promise<Transcription> {
  const idempotencyKey = crypto.randomUUID();
  const path = `/api/scans/${scanId}/recognize`;
  let recoveringSince = 0;
  let recovering = false;

  while (true) {
    try {
      return await request<Transcription>(path, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
      });
    } catch (error) {
      const stillRunning =
        error instanceof ApiError &&
        error.status === 409 &&
        error.message === RECOGNITION_IN_PROGRESS;
      const networkFailure = error instanceof TypeError;

      // A real failure (503, a 404, a key reused for another scan) surfaces as-is.
      if (!networkFailure && !stillRunning) {
        throw error;
      }
      const retryImmediately = networkFailure && !recovering;
      if (!recovering) {
        recovering = true;
        recoveringSince = Date.now();
        onRecovering?.();
      } else if (Date.now() - recoveringSince >= RECOGNITION_RECOVERY_TIMEOUT_MS) {
        throw new Error(RECOGNITION_STILL_RUNNING);
      }
      // A network failure may occur just as the backend commits, so retry it
      // immediately once. In-progress responses then settle into a quiet poll.
      if (!retryImmediately) {
        await delay(RECOGNITION_RECOVERY_POLL_MS);
      }
    }
  }
}

export async function saveTranscription(
  scanId: string,
  stf: Stf,
  status: TranscriptionStatus,
): Promise<Transcription> {
  const saved = await request<Transcription>(`/api/scans/${scanId}/transcription`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stf, status }),
  });
  // Evict the now-superseded cached transcription (and the songs list, whose
  // status pill this may flip) so an offline reopen can't read back the
  // pre-save STF (finding F21). Best-effort, after the write succeeds.
  await invalidateCached([`/api/scans/${scanId}/transcription`, "/api/songs"]);
  return saved;
}

// Detected ink-row bands for the editor's per-line photo auto-scroll (#11).
export function getLineBands(scanId: string): Promise<LineBands> {
  return request<LineBands>(`/api/scans/${scanId}/line-bands`);
}

export function scanImageUrl(scanId: string): string {
  return `/api/scans/${scanId}/image`;
}

export function scanThumbnailUrl(scanId: string): string {
  return `/api/scans/${scanId}/thumbnail`;
}

// Downscaled 1600px copy of the scan. Used by the editor's photo pane (legible
// marks without the full-res original's sluggishness) and, since #15, by the
// viewer's first paint (it then swaps in scanImageUrl). detect_line_bands also
// runs on this image server-side, so its size is load-bearing for auto-scroll.
export function scanPreviewUrl(scanId: string): string {
  return `/api/scans/${scanId}/preview`;
}
