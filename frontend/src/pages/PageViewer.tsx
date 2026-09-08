import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  deleteScan,
  getSong,
  getTranscription,
  scanImageUrl,
  scanPreviewUrl,
} from "../api/client";
import { InstrumentPicker } from "../components/InstrumentPicker";
import { OfflineBanner } from "../components/OfflineBanner";
import { ProgressiveImage } from "../components/ProgressiveImage";
import { StfLineText } from "../components/StfLineText";
import { useFocusTrap } from "../focusTrap";
import {
  askedThisSession,
  instrumentHeader,
  keyColumnHeading,
  keyColumnValue,
  loadProfile,
  markAskedThisSession,
  profileHint,
  saveProfile,
  viewSemitones,
  type InstrumentProfile,
} from "../instrumentProfile";
import { readPref, writePref } from "../prefs";
import { NOTE_KINDS } from "../stfGrammar";
import { pitchClassName, scalePitchClass, transposeLineOfKind } from "../stfTranspose";
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
  // Which instrument is in the player's hands (Phase 3.6). Like the reading
  // preferences it persists and does NOT reset per page — you do not put the
  // flute down between pages — but unlike them it changes what the notes SAY:
  // the letters are fingerings, so they are re-derived for this instrument
  // while the song keeps its own concert key.
  const [profile, setProfile] = useState<InstrumentProfile>(loadProfile);
  const [asking, setAsking] = useState(false);
  const askDialog = useRef<HTMLDivElement>(null);
  useFocusTrap(askDialog, asking);

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
      // While a modal is open it owns the keyboard (finding F36). React attaches
      // its listeners at the root container, so the prompt's own Escape handler
      // does not stop the event reaching this native window listener: without
      // this guard one Escape would both close the prompt AND navigate out of
      // the viewer, and the arrow keys would page the sheet behind it.
      if (asking) return;
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
  }, [navigate, songId, page, scans, asking]);

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
  // header has no parseable scale — then there is no tonic to hold fixed, so
  // neither transposition nor re-fingering is defined and the stored letters are
  // shown exactly as they are.
  const sourcePc = stf ? scalePitchClass(stf.header.concert_scale) : null;
  const canTranspose = sourcePc !== null;
  // One rotation carries both halves of the view (see instrumentProfile.ts): the
  // chosen key AND the chosen instrument's fingering anchor, folded into the
  // nearest octave. The manual nudge then adds whole octaves on top.
  const baseSemitones = viewSemitones(profile, sourcePc, targetPc);
  // A different concert key is selected — i.e. the MUSIC changes, not just the
  // fingering. (Not the same as `baseSemitones !== 0`: an instrument whose
  // anchor happens to cancel the key change rotates by zero, and a flute at the
  // song's own key rotates without changing the key at all.)
  const keyChanged = targetPc !== null && targetPc !== sourcePc;
  // Whether the view is derived at all. While it is not, the stored text is
  // rendered byte-for-byte — the fidelity rule's identity case, which only the
  // Alto Sax profile at the song's own key reaches.
  const rotates = keyChanged || baseSemitones !== 0;
  const semitones = rotates ? baseSemitones + octaveShift * 12 : 0;

  // Header labels for the (possibly transposed) view. The concert key is
  // verbatim from the sheet until a new key is chosen; the right-hand label is
  // whatever the selected instrument makes of that key — the written key on the
  // sax, the tuning plus the tonic's fingering on a flute.
  const shownConcertPc = keyChanged ? targetPc : sourcePc;
  const shownConcert =
    !keyChanged || sourcePc === null ? stf?.header.concert_scale : pitchClassName(targetPc!);
  // Prefer the sheet's own verbatim alto string where it applies, so the printed
  // pair can never disagree with the paper over a spelling.
  const shownInstrument =
    profile.kind === "alto-sax" && !keyChanged && stf?.header.alto_scale
      ? `Alto ${stf.header.alto_scale}`
      : instrumentHeader(profile, shownConcertPc);

  function chooseProfile(next: InstrumentProfile) {
    setProfile(next);
    saveProfile(next); // the next session's default
    setOctaveShift(0); // fresh nearest-octave register for the new fingering
  }

  // "What are you playing?", once per playing session, the first time a digital
  // view is opened. Asking here rather than on app start means it only ever
  // interrupts someone who is about to read notation off the screen, and the
  // question is asked while the answer is visibly relevant.
  useEffect(() => {
    if (view !== "digital" || !stf || stf.lines.length === 0) return;
    if (askedThisSession()) return;
    markAskedThisSession();
    setAsking(true);
  }, [view, stf]);

  return (
    <div className={`viewer theme-${theme}`}>
      <OfflineBanner />
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
          {/* Instrument first: it decides what every letter to its right MEANS,
              so it reads as the premise of the key selector rather than a
              setting tucked away after it. */}
          <label>
            Instrument
            <InstrumentPicker value={profile} onChange={chooseProfile} />
          </label>
          {canTranspose ? (
            <label>
              Key
              {/* One row per scale, keyed by its CONCERT pitch class: the concert
                  name on the left, what the selected instrument makes of it on
                  the right (its written key on the sax, the tonic's fingering on
                  a flute). Both columns describe the same scale, so they share
                  the single "— Original" row. Sorted by concert pitch. */}
              <select
                // As with the instrument select: this label wraps both the
                // control and the hint line, so name the control explicitly.
                aria-label="Key"
                value={targetPc ?? sourcePc!}
                onChange={(e) => {
                  const pc = Number(e.target.value);
                  setTargetPc(pc === sourcePc ? null : pc);
                  setOctaveShift(0); // fresh nearest-octave default for the new key
                }}
              >
                <optgroup label={`Concert${NBSP.repeat(4)}${keyColumnHeading(profile)}`}>
                  {Array.from({ length: 12 }, (_, concertPc) => concertPc).map((concertPc) => {
                    const original = concertPc === sourcePc;
                    // The Original row echoes the header's verbatim scale strings
                    // so it can never disagree with the "Concert …" line above;
                    // every other row is named from the flat-preferring table.
                    // The right column only has a verbatim form on the sax — a
                    // flute's fingering is always derived.
                    const concert =
                      original && stf.header.concert_scale
                        ? stf.header.concert_scale
                        : pitchClassName(concertPc);
                    const instrument =
                      original && profile.kind === "alto-sax" && stf.header.alto_scale
                        ? stf.header.alto_scale
                        : keyColumnValue(profile, concertPc);
                    // nbsp padding + a monospace select align the two columns.
                    const label =
                      concert.padEnd(2, NBSP) +
                      NBSP.repeat(4) +
                      instrument +
                      (original ? `${NBSP.repeat(3)}— Original` : "");
                    return (
                      <option key={concertPc} value={concertPc}>
                        {label}
                      </option>
                    );
                  })}
                </optgroup>
              </select>
              <span className="key-hint">{profileHint(profile)}</span>
            </label>
          ) : (
            <span className="muted">
              Header scale unknown — no key to transpose from. Fingerings are still shown for the
              instrument above.
            </span>
          )}
          {rotates && (
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
          {(targetPc !== null || octaveShift !== 0) && (
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
            {(shownConcert || shownInstrument || stf.header.beat) && (
              <div className="digital-header">
                {shownConcert && <span>Concert {shownConcert}</span>}
                {shownInstrument && <span>{shownInstrument}</span>}
                {stf.header.beat && <span>{stf.header.beat}</span>}
                {/* Two independent facts, each shown on its own condition
                    (finding F37): the key was changed, and the register was
                    nudged. The nudge is available whenever the view is derived,
                    so tying its badge to `keyChanged` used to let a flute be
                    shifted two octaves with nothing on screen saying so. */}
                {(keyChanged || octaveShift !== 0) && (
                  <span className="transposed-tag">
                    {keyChanged && "transposed"}
                    {octaveShift !== 0 &&
                      `${keyChanged ? " · " : ""}${octaveShift > 0 ? "+" : "−"}${Math.abs(octaveShift)} 8va`}
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

      {asking && (
        <div className="modal-overlay" role="presentation" onClick={() => setAsking(false)}>
          <div
            ref={askDialog}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="instrument-title"
            aria-describedby="instrument-body"
            // tabIndex -1 lets useFocusTrap move focus onto the card itself on
            // open, so the Escape handler below actually receives keys.
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") setAsking(false);
            }}
          >
            <h2 id="instrument-title">What are you playing?</h2>
            {/* NOT `.muted`: inside `.viewer` that resolves to the viewer's
                --v-faint, which is tuned for the viewer's own backdrop, not for
                this card's app-palette --card (finding F38). */}
            <p id="instrument-body" className="modal-note">
              The letters are fingerings, so they are shown for this instrument. The song keeps its
              own key either way.
            </p>
            <label className="instrument-ask">
              Instrument
              <InstrumentPicker value={profile} onChange={chooseProfile} />
            </label>
            <div className="modal-actions">
              {/* One way out, and it is not a decision: the picker above has
                  already applied. Dismissing simply stops asking. */}
              <button className="primary" onClick={() => setAsking(false)}>
                Start playing
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
