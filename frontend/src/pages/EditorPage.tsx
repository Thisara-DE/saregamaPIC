import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getSong,
  getTranscription,
  recognizeScan,
  saveTranscription,
  scanPreviewUrl,
} from "../api/client";
import { StfLineText } from "../components/StfLineText";
import { insertToken, toggleMark, type Mark } from "../stfEdit";
import type { Stf, StfLine, Transcription, TranscriptionStatus } from "../api/types";

const KINDS = ["sargam", "run", "section", "lyric", "roadmap", "annotation"] as const;
const NOTE_KINDS = new Set(["sargam", "run"]);

// Tap-to-toggle marks so the reviewer never has to remember the ASCII suffixes.
const MARK_BUTTONS: { label: string; title: string; mark: Mark }[] = [
  { label: "♭", title: "Flat — dash below (R G D N)", mark: "_" },
  { label: "♯", title: "Sharp — tick above (M only)", mark: "^" },
  { label: "●̇", title: "Octave up — dot above", mark: "'" },
  { label: "●̣", title: "Octave down — dot below", mark: "," },
];
const INSERT_BUTTONS: { label: string; title: string; token: string }[] = [
  { label: "−", title: "Hold the previous note one more beat", token: "-" },
  { label: "+", title: "One-beat rest", token: "+" },
  { label: "|", title: "Barline", token: "|" },
];

const EMPTY_STF: Stf = { header: { concert_scale: "", alto_scale: "", beat: "" }, lines: [] };

/**
 * Correction editor: original photo ↔ editable STF, side by side. "Recognize"
 * fills the STF from Claude vision; the reviewer fixes it and saves. The digital
 * copy must mirror the paper verbatim, so this edits the ORIGINAL-scale STF only
 * (transposition/Western views are derived later, never stored here).
 */
export function EditorPage() {
  const { songId = "", pageNo = "" } = useParams();
  const navigate = useNavigate();
  const page = Number(pageNo);

  const [title, setTitle] = useState("");
  const [scanId, setScanId] = useState<string | null>(null);
  const [stf, setStf] = useState<Stf>(EMPTY_STF);
  const [status, setStatus] = useState<TranscriptionStatus>("draft");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<Pick<
    Transcription,
    "model" | "input_tokens" | "output_tokens"
  > | null>(null);
  const [hasTranscription, setHasTranscription] = useState(false);
  const [busy, setBusy] = useState<"load" | "recognize" | "save" | null>("load");
  const [recognitionRecovering, setRecognitionRecovering] = useState(false);
  const [saved, setSaved] = useState<{ status: TranscriptionStatus; stf: Stf } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The line whose mark bar is showing, and a handle on its focused <input> so
  // a bar tap can read/restore the caret without the input losing focus.
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const activeInputRef = useRef<HTMLInputElement | null>(null);
  // A mark-bar edit sets a target caret; reassigning a controlled input's value
  // parks the caret at the end, so we restore it AFTER React commits — a layout
  // effect wins that race where requestAnimationFrame does not.
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingCaret.current !== null && activeInputRef.current) {
      const at = pendingCaret.current;
      activeInputRef.current.setSelectionRange(at, at);
      pendingCaret.current = null;
    }
  });

  const apply = useCallback((t: Transcription) => {
    setStf(t.stf);
    setStatus(t.status);
    setWarnings(t.warnings);
    setMetrics({ model: t.model, input_tokens: t.input_tokens, output_tokens: t.output_tokens });
    setHasTranscription(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy("load");
    (async () => {
      try {
        const song = await getSong(songId);
        if (cancelled) return;
        setTitle(song.title);
        const scan = song.scans.find((s) => s.page_no === page);
        if (!scan) {
          setError(`Page ${page} not found.`);
          return;
        }
        setScanId(scan.id);
        try {
          apply(await getTranscription(scan.id));
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) {
            setHasTranscription(false); // nothing recognized yet — offer the button
          } else {
            throw e;
          }
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setBusy(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [songId, page, apply]);

  async function handleRecognize() {
    if (!scanId) return;
    if (hasTranscription && !window.confirm("Re-run recognition? Current edits are replaced.")) {
      return;
    }
    setBusy("recognize");
    setRecognitionRecovering(false);
    setError(null);
    try {
      apply(await recognizeScan(scanId, () => setRecognitionRecovering(true)));
      const refreshedSong = await getSong(songId);
      setTitle(refreshedSong.title);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setRecognitionRecovering(false);
    }
  }

  async function handleSave(next: TranscriptionStatus) {
    if (!scanId) return;
    setBusy("save");
    setError(null);
    setSaved(null);
    try {
      const result = await saveTranscription(scanId, stf, next);
      apply(result);
      // Pin the confirmation to the exact STF that was saved. Every edit helper
      // builds a new object, so the banner clears itself the moment the reader
      // changes anything and it can never advertise a stale save.
      setSaved({ status: next, stf: result.stf });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function setHeader(field: keyof Stf["header"], value: string) {
    setStf((s) => ({ ...s, header: { ...s.header, [field]: value } }));
  }

  function setLine(i: number, patch: Partial<StfLine>) {
    setStf((s) => ({ ...s, lines: s.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  }

  function addLine() {
    setStf((s) => ({
      ...s,
      lines: [...s.lines, { n: s.lines.length + 1, kind: "sargam", text: "" }],
    }));
  }

  function deleteLine(i: number) {
    setStf((s) => ({
      ...s,
      lines: s.lines.filter((_, j) => j !== i).map((l, j) => ({ ...l, n: j + 1 })),
    }));
  }

  // Apply a mark-bar edit to line `i` at its live caret, then put the caret
  // back where the transform asks (the controlled input re-renders otherwise).
  function editLine(
    i: number,
    text: string,
    fn: (text: string, caret: number) => { text: string; caret: number },
  ) {
    const el = activeInputRef.current;
    const caret = el?.selectionStart ?? text.length;
    const next = fn(text, caret);
    pendingCaret.current = next.caret; // restored in the layout effect above
    setLine(i, { text: next.text });
  }

  return (
    <div className="editor">
      <div className="editor-bar">
        <button className="viewer-btn" onClick={() => navigate(`/songs/${songId}`)}>
          ✕
        </button>
        <span className="viewer-title">
          {`${title || "Untitled song"} — page ${page}`}
          {hasTranscription && <span className={`status-pill ${status}`}>{status}</span>}
        </span>
        <button
          className="primary"
          disabled={!scanId || busy !== null}
          onClick={() => void handleRecognize()}
        >
          {busy === "recognize" ? "Recognizing…" : hasTranscription ? "Re-recognize" : "Recognize"}
        </button>
      </div>

      {error && <p className="error editor-msg">{error}</p>}
      {busy === "recognize" && (
        <p className="muted editor-msg" role="status">
          {recognitionRecovering
            ? "The connection was interrupted. Checking for your completed digital draft…"
            : "Creating the digital draft… This can take about a minute."}
        </p>
      )}

      <div className="editor-split">
        <div className="editor-photo">
          {scanId && (
            <img
              src={scanPreviewUrl(scanId)}
              alt={`Page ${page} of ${title || "Untitled song"}`}
            />
          )}
        </div>

        <div className="editor-form">
          {busy === "load" && <p className="muted">Loading…</p>}

          {!hasTranscription && busy === null && (
            <p className="muted">
              No transcription yet. Press <strong>Recognize</strong> to draft one from the photo,
              or start typing below.
            </p>
          )}

          <fieldset className="stf-header">
            <legend>Header</legend>
            <label>
              Concert
              <input
                value={stf.header.concert_scale}
                placeholder="e.g. G"
                onChange={(e) => setHeader("concert_scale", e.target.value)}
              />
            </label>
            <label>
              Alto
              <input
                value={stf.header.alto_scale}
                placeholder="e.g. E"
                onChange={(e) => setHeader("alto_scale", e.target.value)}
              />
            </label>
            <label>
              Beat
              <input
                value={stf.header.beat}
                placeholder="e.g. 4/4"
                onChange={(e) => setHeader("beat", e.target.value)}
              />
            </label>
          </fieldset>

          <p className="stf-legend">
            Marks: <code>_</code> flat · <code>^</code> sharp (M) · <code>'</code> octave up ·{" "}
            <code>,</code> octave down · <code>-</code> hold · <code>+</code> rest · <code>|</code>{" "}
            bar · <code>( )</code> curve. Tap a note, then a button below — no need to type them.
          </p>

          {warnings.length > 0 && (
            <div className="stf-warnings" role="status">
              <strong>⚠ {warnings.length} to check</strong>
              <ul>
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <ol className="stf-lines">
            {stf.lines.map((line, i) => (
              <li key={i} className="stf-line">
                <div className="stf-line-controls">
                  <select
                    value={line.kind}
                    aria-label={`Line ${line.n} kind`}
                    onChange={(e) => setLine(i, { kind: e.target.value })}
                  >
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                  <input
                    className="stf-line-input"
                    value={line.text}
                    aria-label={`Line ${line.n} text`}
                    spellCheck={false}
                    onFocus={(e) => {
                      setActiveLine(i);
                      activeInputRef.current = e.currentTarget;
                    }}
                    onBlur={() => setActiveLine((cur) => (cur === i ? null : cur))}
                    onChange={(e) => setLine(i, { text: e.target.value })}
                  />
                  <button
                    className="danger-link"
                    aria-label={`Delete line ${line.n}`}
                    onClick={() => deleteLine(i)}
                  >
                    ✕
                  </button>
                </div>
                {activeLine === i && NOTE_KINDS.has(line.kind) && (
                  // preventDefault on mousedown keeps the input focused + its
                  // caret intact, so the tap edits the note the caret is on.
                  <div className="stf-mark-bar" onMouseDown={(e) => e.preventDefault()}>
                    {MARK_BUTTONS.map((b) => (
                      <button
                        key={b.mark}
                        title={b.title}
                        aria-label={b.title}
                        onClick={() => editLine(i, line.text, (t, c) => toggleMark(t, c, b.mark))}
                      >
                        {b.label}
                      </button>
                    ))}
                    <span className="stf-mark-sep" aria-hidden="true" />
                    {INSERT_BUTTONS.map((b) => (
                      <button
                        key={b.token}
                        title={b.title}
                        aria-label={b.title}
                        onClick={() => editLine(i, line.text, (t, c) => insertToken(t, c, b.token))}
                      >
                        {b.label}
                      </button>
                    ))}
                  </div>
                )}
                {NOTE_KINDS.has(line.kind) && line.text && (
                  <div className="stf-line-preview">
                    <StfLineText text={line.text} />
                  </div>
                )}
              </li>
            ))}
          </ol>

          <button className="add-line" onClick={addLine}>
            + Add line
          </button>

          <div className="editor-actions">
            <button disabled={busy !== null} onClick={() => void handleSave("draft")}>
              {busy === "save" ? "Saving…" : "Save draft"}
            </button>
            <button
              className="primary"
              disabled={busy !== null}
              onClick={() => void handleSave("reviewed")}
            >
              Mark reviewed
            </button>
          </div>

          {/* The editor shows one line at a time, so alignment across the whole
              sheet only becomes visible in the digital view. Offer it right here
              rather than making the reader walk back out through the song page. */}
          {saved && saved.stf === stf && (
            <div className="save-confirm" role="status">
              <span>{saved.status === "reviewed" ? "Marked reviewed." : "Draft saved."}</span>
              <button
                className="button-link"
                onClick={() => navigate(`/songs/${songId}/pages/${page}`)}
              >
                See the digital version →
              </button>
            </div>
          )}

          {metrics?.model && (
            <p className="muted metrics">
              Recognized with {metrics.model} · {metrics.input_tokens} in / {metrics.output_tokens}{" "}
              out tokens
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
