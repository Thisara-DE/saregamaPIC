import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  deleteScan,
  getSong,
  getTranscription,
  scanImageUrl,
  scanPreviewUrl,
} from "../api/client";
import { ProgressiveImage } from "../components/ProgressiveImage";
import { StfLineText } from "../components/StfLineText";
import { readPref, writePref } from "../prefs";
import { NOTE_KINDS } from "../stfGrammar";
import {
  pitchClassName,
  scalePitchClass,
  transposeLineOfKind,
  transposeSemitones,
} from "../stfTranspose";
import type { SongDetail, Transcription } from "../api/types";

type View = "original" | "digital";

// Non-breaking space — pads the two-name Key options so the columns line up in
// the monospace <select> (regular spaces collapse in option rendering).
const NBSP = " ";

// Reading preferences (text size, theme) survive page changes and app restarts —
// see the notes on each below, and prefs.ts for why every access is guarded.

// Digital-view text size. This is the read-while-playing view at music-stand
// distance, so the chosen size is a per-user constant (not per-page). Discrete
// multipliers keep the stepping predictable and the % labels clean; 1 (= 100%)
// is always a member.
const DIGITAL_SCALES: readonly number[] = [0.8, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const MIN_DIGITAL_SCALE = DIGITAL_SCALES[0] ?? 1;
const MAX_DIGITAL_SCALE = DIGITAL_SCALES[DIGITAL_SCALES.length - 1] ?? 1;
const SCALE_KEY = "saregamapic.digitalScale";

function loadDigitalScale(): number {
  const stored = Number(readPref(SCALE_KEY));
  return DIGITAL_SCALES.includes(stored) ? stored : 1;
}

// Viewer theme. Night (light-on-black) is the default — that is how the viewer
// has always looked and it suits the photo. Day is the paper-like inverse for
// reading the digital render in a bright room or daylight, where light-on-black
// glares. Like the text size it is a per-user reading constant, not per-page.
type Theme = "night" | "day";
const THEME_KEY = "saregamapic.viewerTheme";

function loadTheme(): Theme {
  return readPref(THEME_KEY) === "day" ? "day" : "night";
}

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
  // Manual whole-octave nudge on the transposed view (× 12 semitones). The
  // Key selector auto-picks the nearest octave; this shifts the whole line
  // up/down from there for register preference. Reset whenever the key changes.
  const [octaveShift, setOctaveShift] = useState(0);
  // Digital text size multiplier (persisted; see DIGITAL_SCALES) and viewer
  // theme (persisted; see Theme). Unlike the key and octave, neither is reset
  // per page — they are reading preferences, not per-sheet performance choices.
  const [digitalScale, setDigitalScale] = useState(loadDigitalScale);
  const [theme, setTheme] = useState<Theme>(loadTheme);

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
    setOctaveShift(0);
    setTranscription(null);
    if (!scan) return;
    let cancelled = false;
    getTranscription(scan.id)
      .then((t) => {
        if (cancelled) return;
        setTranscription(t);
        // Open on the digital version when there is one to show — that is what
        // the page is usually opened for. An empty transcription would be a
        // blank screen, so fall back to the photo. The toggle only renders once
        // this resolves, so this can never overwrite a user's choice.
        if (t.stf.lines.length > 0) setView("digital");
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

  // Step the digital text size one notch and persist it. Bounds are enforced by
  // clamping the index into DIGITAL_SCALES; the buttons also disable at the ends.
  // Both handlers persist outside the state updater — updaters must stay pure
  // (React double-invokes them in StrictMode).
  function stepDigitalScale(dir: 1 | -1) {
    const i = DIGITAL_SCALES.indexOf(digitalScale);
    const clamped = Math.min(DIGITAL_SCALES.length - 1, Math.max(0, i + dir));
    const next = DIGITAL_SCALES[clamped] ?? digitalScale;
    setDigitalScale(next);
    writePref(SCALE_KEY, String(next));
  }

  function toggleTheme() {
    const next: Theme = theme === "day" ? "night" : "day";
    setTheme(next);
    writePref(THEME_KEY, next);
  }

  const stf = transcription?.stf;
  // The stored (original) scale, from the header's concert name. Null when the
  // header has no parseable scale — then transposition is unavailable.
  const sourcePc = stf ? scalePitchClass(stf.header.concert_scale) : null;
  const canTranspose = sourcePc !== null;
  // Base key change picks the nearest octave (signed, [-5,+6]); the manual nudge
  // adds whole octaves. keyChanged = a different tonic is selected (octave nudge
  // alone doesn't count as a transposition — the scale is unchanged).
  const baseSemitones =
    targetPc !== null && sourcePc !== null ? transposeSemitones(sourcePc, targetPc) : 0;
  const keyChanged = baseSemitones !== 0;
  const semitones = baseSemitones + (keyChanged ? octaveShift * 12 : 0);

  // Header labels for the (possibly transposed) view: verbatim in the original
  // scale, derived (concert = target, alto = target + 9) once the key changes.
  const shownConcert =
    !keyChanged || sourcePc === null ? stf?.header.concert_scale : pitchClassName(targetPc!);
  const shownAlto =
    !keyChanged || sourcePc === null ? stf?.header.alto_scale : pitchClassName(targetPc! + 9);

  return (
    <div className={`viewer theme-${theme}`}>
      <div className="viewer-bar">
        <button className="viewer-btn" onClick={() => navigate(`/songs/${songId}`)}>
          ✕
        </button>
        <span className="viewer-title">
          {song ? `${song.title || "Untitled song"} — ${page} / ${scans.length}` : "…"}
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
        {/* Theme toggle. One button, constant meaning: "day theme" —
            aria-pressed carries the state, so the icon does not have to flip.
            It sits in the bar rather than with the other reading preference
            (text size) because the theme repaints the whole viewer, including
            pages that have no transcription and so render no controls row. */}
        <button
          className={`viewer-btn theme-btn${theme === "day" ? " on" : ""}`}
          onClick={toggleTheme}
          aria-pressed={theme === "day"}
          aria-label="Day theme"
          title="Day theme — dark notes on paper, for bright rooms"
        >
          ☀
        </button>
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
                  setOctaveShift(0); // fresh nearest-octave default for the new key
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
          {keyChanged && (
            <span className="octave-nudge" role="group" aria-label="Octave">
              <button
                className="viewer-btn oct-btn"
                onClick={() => setOctaveShift((s) => Math.min(2, s + 1))}
                disabled={octaveShift >= 2}
                title="Shift the whole line up one octave"
              >
                8va▲
              </button>
              <button
                className="viewer-btn oct-btn"
                onClick={() => setOctaveShift((s) => Math.max(-2, s - 1))}
                disabled={octaveShift <= -2}
                title="Shift the whole line down one octave"
              >
                8va▼
              </button>
            </span>
          )}
          {keyChanged && (
            <button
              className="viewer-btn reset-key"
              onClick={() => {
                setTargetPc(null);
                setOctaveShift(0);
              }}
            >
              Reset
            </button>
          )}
          {/* Text size — pushed to the right so it stays put as the key/octave
              controls appear and disappear. Reading size at music-stand
              distance. The theme toggle, the other reading preference, lives in
              the bar instead; see the comment there. */}
          <span className="text-size" role="group" aria-label="Text size">
            <button
              className="viewer-btn size-btn"
              onClick={() => stepDigitalScale(-1)}
              disabled={digitalScale <= MIN_DIGITAL_SCALE}
              aria-label="Smaller text"
              title="Smaller text"
            >
              A−
            </button>
            <span className="size-value" aria-live="polite">
              {Math.round(digitalScale * 100)}%
            </span>
            <button
              className="viewer-btn size-btn"
              onClick={() => stepDigitalScale(1)}
              disabled={digitalScale >= MAX_DIGITAL_SCALE}
              aria-label="Larger text"
              title="Larger text"
            >
              A+
            </button>
          </span>
        </div>
      )}

      {error && <p className="error viewer-msg">{error}</p>}
      {song !== null && !scan && !error && (
        <p className="muted viewer-msg">Page {page} not found.</p>
      )}

      {scan && view === "original" && (
        <div className="viewer-stage">
          {/* Paint the 1600px preview first, then swap in the full-res original
              when it loads (#15) — the stored 4000×3000 scan is a multi-second
              blank over cellular. */}
          <ProgressiveImage
            key={scan.id}
            preview={scanPreviewUrl(scan.id)}
            full={scanImageUrl(scan.id)}
            alt={`Page ${page} of ${song?.title || "Untitled song"}`}
          />
        </div>
      )}

      {scan && view === "digital" && stf && (
        <div className="viewer-stage digital">
          <div
            className="viewer-digital"
            style={{ "--digital-scale": digitalScale } as CSSProperties}
          >
            {(shownConcert || shownAlto || stf.header.beat) && (
              <div className="digital-header">
                {shownConcert && <span>Concert {shownConcert}</span>}
                {shownAlto && <span>Alto {shownAlto}</span>}
                {stf.header.beat && <span>{stf.header.beat}</span>}
                {keyChanged && (
                  <span className="transposed-tag">
                    transposed
                    {octaveShift !== 0 &&
                      ` · ${octaveShift > 0 ? "+" : "−"}${Math.abs(octaveShift)} 8va`}
                  </span>
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
