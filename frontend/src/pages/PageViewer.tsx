import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { deleteScan, getSong, scanImageUrl } from "../api/client";
import type { SongDetail } from "../api/types";

/**
 * Full-screen viewer for one page. Always shows the ORIGINAL photo
 * (fidelity rule — thumbnails are for grids only). Browser-native pinch
 * zoom stays available because the viewport allows scaling.
 */
export function PageViewer() {
  const { songId = "", pageNo = "" } = useParams();
  const navigate = useNavigate();
  const [song, setSong] = useState<SongDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const page = Number(pageNo);
  const scans = useMemo(() => song?.scans ?? [], [song]);
  const scan = scans.find((s) => s.page_no === page);

  useEffect(() => {
    getSong(songId)
      .then(setSong)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [songId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft" && page > 1) {
        navigate(`/songs/${songId}/pages/${page - 1}`, { replace: true });
      } else if (e.key === "ArrowRight" && scans.some((s) => s.page_no === page + 1)) {
        navigate(`/songs/${songId}/pages/${page + 1}`, { replace: true });
      } else if (e.key === "Escape") {
        navigate(`/songs/${songId}`);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, songId, page, scans]);

  async function handleDeletePage() {
    if (!scan) return;
    if (!window.confirm(`Delete page ${page}? The original photo is removed too.`)) return;
    try {
      await deleteScan(scan.id);
      navigate(`/songs/${songId}`); // remaining pages are renumbered server-side
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="viewer">
      <div className="viewer-bar">
        <button className="viewer-btn" onClick={() => navigate(`/songs/${songId}`)}>
          ✕
        </button>
        <span className="viewer-title">
          {song ? `${song.title} — ${page} / ${scans.length}` : "…"}
        </span>
        <button
          className="viewer-btn"
          aria-label="Transcribe page"
          title="Transcribe"
          onClick={() => navigate(`/songs/${songId}/pages/${page}/edit`)}
        >
          ✎
        </button>
        <button
          className="viewer-btn"
          aria-label="Delete page"
          onClick={() => void handleDeletePage()}
        >
          🗑
        </button>
      </div>

      {error && <p className="error viewer-msg">{error}</p>}
      {song !== null && !scan && !error && (
        <p className="muted viewer-msg">Page {page} not found.</p>
      )}
      {scan && (
        <div className="viewer-stage">
          <img src={scanImageUrl(scan.id)} alt={`Page ${page} of ${song?.title ?? ""}`} />
        </div>
      )}

      {page > 1 && (
        <button
          className="viewer-btn viewer-nav prev"
          aria-label="Previous page"
          onClick={() => navigate(`/songs/${songId}/pages/${page - 1}`, { replace: true })}
        >
          ‹
        </button>
      )}
      {scans.some((s) => s.page_no === page + 1) && (
        <button
          className="viewer-btn viewer-nav next"
          aria-label="Next page"
          onClick={() => navigate(`/songs/${songId}/pages/${page + 1}`, { replace: true })}
        >
          ›
        </button>
      )}
    </div>
  );
}
