import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, deleteScan, getSong, getTranscription, scanImageUrl } from "../api/client";
import { StfLineText } from "../components/StfLineText";
import { pitchClassName, scalePitchClass, transposeLineOfKind } from "../stfTranspose";
import type { SongDetail, Transcription } from "../api/types";

type View = "original" | "digital";

// Non-breaking space — pads the two-name Key options so the columns line up in
// the monospace <select> (regular spaces collapse in option rendering).
const NBSP = " ";

/**
 * Full-screen viewer for one page. Toggles between the ORIGINAL photo (fidelity
 * rule — the verbatim scan) and the DIGITAL sargam render, with a scale selector
 * that transposes the digital view live. The stored STF is never rewritten; the
 * transposed view is derived at read time by rotating a copy through stfTranspose.
 */
export function PageViewer() {
  const { songId = "", pageNo = "" } = useParams();
  const navigate = useNavigate();
  const [song, setSong] = useState<SongDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<View>("original");
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  // Target tonic as a pitch class; null = the stored (original) scale — identity.
  const [targetPc, setTargetPc] = useState<number | null>(null);

  const page = Number(pageNo);
  const scans = useMemo(() => song?.scans ?? [], [song]);
  const scan = scans.find((s) => s.page_no === page);

  useEffect(() => {
    getSong(songId)
      .then(setSong)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [songId]);

  // Load the transcription for the current page (if any). Reset the view to the
  // photo and the scale back to original whenever the page changes.
  useEffect(() => {
    setView("original");
    setTargetPc(null);
    setTranscription(null);
    if (!scan) return;
    let cancelled = false;
    getTranscription(scan.id)
      .then((t) => {
        if (!cancelled) setTranscription(t);
      })
      .catch((e: unknown) => {
        // 404 = nothing transcribed yet; leave Digital disabled, surface others.
        if (!cancelled && !(e instanceof ApiError && e.status === 404)) {
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
    // Key on the scan id, not the `scan` object (re-derived via find() every
    // render — depending on it would refetch on every render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan?.id]);

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

  const stf = transcription?.stf;
  // The stored (original) scale, from the header's concert name. Null when the
  // header has no parseable scale — then transposition is unavailable.
  const sourcePc = stf ? scalePitchClass(stf.header.concert_scale) : null;
  const canTranspose = sourcePc !== null;
  const semitones =
    targetPc !== null && sourcePc !== null ? (((targetPc - sourcePc) % 12) + 12) % 12 : 0;

  // Header labels for the (possibly transposed) view: verbatim in the original
  // scale, derived (concert = target, alto = target + 9) once transposed.
  const shownConcert =
    semitones === 0 || sourcePc === null ? stf?.header.concert_scale : pitchClassName(targetPc!);
  const shownAlto =
    semitones === 0 || sourcePc === null
      ? stf?.header.alto_scale
      : pitchClassName(targetPc! + 9);

  return (
    <div className="viewer">
      <div className="viewer-bar">
        <button className="viewer-btn" onClick={() => navigate(`/songs/${songId}`)}>
          ✕
        </button>
        <span className="viewer-title">
          {song ? `${song.title} — ${page} / ${scans.length}` : "…"}
        </span>
        {transcription && (
          <div className="view-toggle" role="group" aria-label="View">
            <button
              className={view === "original" ? "on" : ""}
              aria-pressed={view === "original"}
              onClick={() => setView("original")}
            >
              Original
            </button>
            <button
              className={view === "digital" ? "on" : ""}
              aria-pressed={view === "digital"}
              onClick={() => setView("digital")}
            >
              Digital
            </button>
          </div>
        )}
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

      {view === "digital" && stf && (
        <div className="digital-controls">
          {canTranspose ? (
            <label>
              Key
              {/* One row per scale, keyed by its CONCERT pitch class, showing both
                  names (Concert left, Alto sax right). Concert D and Alto B are the
                  same scale, so they share the single "— Original" row. Sorted by
                  the concert scale (left column, ascending). */}
              <select
                value={targetPc ?? sourcePc!}
                onChange={(e) => {
                  const pc = Number(e.target.value);
                  setTargetPc(pc === sourcePc ? null : pc);
                }}
              >
                <optgroup label={`Concert${NBSP.repeat(4)}Alto`}>
                  {Array.from({ length: 12 }, (_, concertPc) => ({
                    concertPc,
                    altoPc: (concertPc + 9) % 12,
                  }))
                    .sort((a, b) => a.concertPc - b.concertPc)
                    .map(({ concertPc, altoPc }) => {
                      const original = concertPc === sourcePc;
                      // The Original row echoes the header's verbatim scale strings
                      // so it can never disagree with the "Concert …" line above;
                      // every other row is named from the flat-preferring table.
                      const concert =
                        original && stf.header.concert_scale
                          ? stf.header.concert_scale
                          : pitchClassName(concertPc);
                      const alto =
                        original && stf.header.alto_scale
                          ? stf.header.alto_scale
                          : pitchClassName(altoPc);
                      // nbsp padding + a monospace select align the two columns.
                      const label =
                        concert.padEnd(2, NBSP) +
                        NBSP.repeat(4) +
                        alto +
                        (original ? `${NBSP.repeat(3)}— Original` : "");
                      return (
                        <option key={concertPc} value={concertPc}>
                          {label}
                        </option>
                      );
                    })}
                </optgroup>
              </select>
              <span className="key-hint">Concert → Alto = up a major 6th (down a minor 3rd)</span>
            </label>
          ) : (
            <span className="muted">Header scale unknown — showing the original scale.</span>
          )}
          {semitones !== 0 && (
            <button className="viewer-btn reset-key" onClick={() => setTargetPc(null)}>
              Reset
            </button>
          )}
        </div>
      )}

      {error && <p className="error viewer-msg">{error}</p>}
      {song !== null && !scan && !error && (
        <p className="muted viewer-msg">Page {page} not found.</p>
      )}

      {scan && view === "original" && (
        <div className="viewer-stage">
          <img src={scanImageUrl(scan.id)} alt={`Page ${page} of ${song?.title ?? ""}`} />
        </div>
      )}

      {scan && view === "digital" && stf && (
        <div className="viewer-stage digital">
          <div className="viewer-digital">
            {(shownConcert || shownAlto || stf.header.beat) && (
              <div className="digital-header">
                {shownConcert && <span>Concert {shownConcert}</span>}
                {shownAlto && <span>Alto {shownAlto}</span>}
                {stf.header.beat && <span>{stf.header.beat}</span>}
                {semitones !== 0 && (
                  <span className="transposed-tag">transposed +{semitones}</span>
                )}
              </div>
            )}
            <ol className="digital-lines">
              {stf.lines.map((line) => (
                <li key={line.n} className={`digital-line kind-${line.kind}`}>
                  {NOTE_KINDS.has(line.kind) ? (
                    <StfLineText text={transposeLineOfKind(line.kind, line.text, semitones)} />
                  ) : (
                    <span className="digital-text">{line.text}</span>
                  )}
                </li>
              ))}
            </ol>
          </div>
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

// Note-bearing line kinds get the faithful arc/mark render; the rest are free
// text (mirrors backend _NOTE_KINDS + the editor's NOTE_KINDS).
const NOTE_KINDS = new Set(["sargam", "run"]);
