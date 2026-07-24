import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteSong, getSong, scanThumbnailUrl, uploadScan } from "../api/client";
import type { SongDetail } from "../api/types";

/**
 * Song detail: capture/upload sheet photos and browse the stored pages.
 *
 * Camera strategy (Phase 0): <input type="file" capture="environment">
 * opens the native camera on phones and works over plain HTTP too — far
 * fewer failure modes than getUserMedia. A live-preview capture UI can
 * replace it later without touching the upload path.
 */
export function SongPage() {
  const { songId = "" } = useParams();
  const navigate = useNavigate();
  const [song, setSong] = useState<SongDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    getSong(songId)
      .then(setSong)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [songId]);

  useEffect(refresh, [refresh]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadScan(songId, file);
      }
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (cameraInput.current) cameraInput.current.value = "";
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleDeleteSong() {
    if (!song) return;
    const pages = song.scans.length;
    const displayTitle = song.title || "Untitled song";
    const warning =
      pages === 0
        ? `Delete "${displayTitle}"?`
        : `Delete "${displayTitle}" and its ${pages} ${pages === 1 ? "page" : "pages"}? ` +
          "The original photos are removed too.";
    if (!window.confirm(warning)) return;
    try {
      await deleteSong(songId);
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section>
      <div className="page-toolbar">
        <Link className="back" to="/">
          ← Songs
        </Link>
        <button className="danger-link" onClick={() => void handleDeleteSong()}>
          Delete song
        </button>
      </div>
      <h2>{song ? song.title || "Untitled song" : "…"}</h2>

      <div className="capture-actions">
        {/* capture="environment" → rear camera straight away on mobile */}
        <input
          ref={cameraInput}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(e) => void handleFiles(e.target.files)}
        />
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => void handleFiles(e.target.files)}
        />
        <button
          className="primary"
          disabled={uploading}
          onClick={() => cameraInput.current?.click()}
        >
          📷 Photograph sheet
        </button>
        <button disabled={uploading} onClick={() => fileInput.current?.click()}>
          Upload image…
        </button>
      </div>

      {uploading && <p className="muted">Uploading…</p>}
      {error && <p className="error">{error}</p>}

      <ul className="scan-grid">
        {song?.scans.map((scan) => (
          <li key={scan.id}>
            <Link to={`/songs/${songId}/pages/${scan.page_no}`}>
              <img src={scanThumbnailUrl(scan.id)} alt={`Page ${scan.page_no}`} loading="lazy" />
              <span className="scan-caption">
                <span className="muted">Page {scan.page_no}</span>
                {scan.status === "draft" ? (
                  <span className="status-pill draft">Draft</span>
                ) : scan.status === "new" ? (
                  <span className="status-pill new">New</span>
                ) : null}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {song !== null && song.scans.length === 0 && !uploading && (
        <p className="muted">No pages yet. Photograph the hand-written sheet to add one.</p>
      )}
    </section>
  );
}
