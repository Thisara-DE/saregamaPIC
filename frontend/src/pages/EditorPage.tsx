import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getSong,
  getTranscription,
  recognizeScan,
  renameSong,
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
  // The title persisted on the server. Blur compares against this so a rename
  // fires only when the reader actually changed it, never on a bare tab-out.
  const [savedTitle, setSavedTitle] = useState("");
  const [titleBusy, setTitleBusy] = useState(false);
  const [scanId, setScanId] = useState<string | null>(null);
  const [stf, setStf] = useState<Stf>(EMPTY_STF);
  // The STF as last persisted (load / recognize / save all set this to the exact
  // object they put on screen). Every edit helper builds a NEW stf object, so a
  // plain reference check tells us there is unsaved work — the same trick the
  // "saved" confirmation below relies on.
  const [savedStf, setSavedStf] = useState<Stf>(EMPTY_STF);
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
  // A per-line "+" inserts a blank line; focus it once React has rendered the new
  // input. Line inputs render in order, so the index maps straight to position.
  const pendingFocusLine = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingFocusLine.current === null) return;
    const inputs = document.querySelectorAll<HTMLInputElement>(".stf-line-input");
    inputs[pendingFocusLine.current]?.focus();
    pendingFocusLine.current = null;
  });

  const apply = useCallback((t: Transcription) => {
    setStf(t.stf);
    setSavedStf(t.stf); // now on screen === persisted, so no unsaved work
    setStatus(t.status);
    setWarnings(t.warnings);
    setMetrics({ model: t.model, input_tokens: t.input_tokens, output_tokens: t.output_tokens });
    setHasTranscription(true);
  }, []);

  // Unsaved work = the STF on screen is a different object than the last
  // persisted one. (Title is excluded — it auto-saves on blur, which the ✕
  // button's own blur triggers on the way out.)
  const dirty = stf !== savedStf;

  // Block every in-app exit while there is unsaved work — the ✕ (a PUSH) and the
  // browser Back button (a POP) both land here, so one dialog covers both. A
  // hard navigation (tab close / refresh) can't be intercepted this way and is
  // caught by the beforeunload guard below instead.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );
  const leaving = blocker.state === "blocked";

  useEffect(() => {
    let cancelled = false;
    setBusy("load");
    (async () => {
      try {
        const song = await getSong(songId);
        if (cancelled) return;
        setTitle(song.title);
        setSavedTitle(song.title);
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
      setSavedTitle(refreshedSong.title);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setRecognitionRecovering(false);
    }
  }

  async function handleSave(next: TranscriptionStatus): Promise<boolean> {
    if (!scanId) return false;
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
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  // The ✕ just navigates; the blocker turns that into the dialog when there is
  // unsaved work, and lets it through cleanly when there isn't.
  function requestExit() {
    navigate(`/songs/${songId}`);
  }

  async function saveAndExit() {
    // Preserve the transcription's current status (draft stays draft, a
    // reviewed edit stays reviewed) rather than silently down-grading it.
    if (await handleSave(status)) blocker.proceed?.();
    else blocker.reset?.(); // save failed — cancel the exit so the error shows
  }

  function discardAndExit() {
    blocker.proceed?.();
  }

  // Native "Leave site?" prompt for hard navigations while work is unsaved. The
  // browser owns this dialog (no custom buttons possible), so it is only a
  // safety net; the in-app ✕ gets the richer save/discard choice.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // required by some browsers to trigger the prompt
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // The title is song-level, so it saves on its own the moment the field loses
  // focus — no need to press "Mark reviewed" (a page-level action) to keep a
  // name. A blank title is not a valid rename (the backend rejects it, and it
  // is the untitled state a reader is trying to leave), so we snap back to the
  // last saved value instead of firing a doomed request.
  async function handleTitleBlur() {
    const next = title.trim();
    if (next === savedTitle) {
      if (next !== title) setTitle(next); // tidy stray whitespace, no request
      return;
    }
    if (!next) {
      setTitle(savedTitle);
      return;
    }
    setTitleBusy(true);
    setError(null);
    try {
      const updated = await renameSong(songId, next);
      setTitle(updated.title);
      setSavedTitle(updated.title);
    } catch (e) {
      // Keep the typed value so the reader can fix and retry; savedTitle stays
      // put, so the next blur attempts the rename again.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTitleBusy(false);
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

  // Insert a blank line directly below line `i` (the per-line + button), then
  // focus it so the reader can type straight away — far less disruptive than the
  // bottom "Add line" when a line is missing in the middle of the sheet.
  function insertLineAfter(i: number) {
    setStf((s) => {
      const lines = [...s.lines];
      lines.splice(i + 1, 0, { n: 0, kind: "sargam", text: "" });
      return { ...s, lines: lines.map((l, j) => ({ ...l, n: j + 1 })) };
    });
    pendingFocusLine.current = i + 1;
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
        <button className="viewer-btn" aria-label="Close editor" onClick={requestExit}>
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

          <label className="editor-title-field">
            Song title
            <input
              value={title}
              maxLength={200}
              placeholder="Untitled — name it here or read it from the sheet"
              aria-label="Song title"
              disabled={busy === "load" || titleBusy}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => void handleTitleBlur()}
            />
          </label>

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
                    className="line-add"
                    aria-label={`Add line after line ${line.n}`}
                    title="Add a line below"
                    onClick={() => insertLineAfter(i)}
                  >
                    +
                  </button>
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

      {leaving && (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={() => !busy && blocker.reset?.()}
        >
          <div
            className="modal-card"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="leave-title"
            aria-describedby="leave-body"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape" && !busy) blocker.reset?.();
            }}
          >
            <h2 id="leave-title">Unsaved changes</h2>
            <p id="leave-body" className="muted">
              You have unsaved changes on this page. Save them before leaving, or discard them?
            </p>
            <div className="modal-actions">
              <button className="primary" disabled={busy !== null} onClick={() => void saveAndExit()}>
                {busy === "save" ? "Saving…" : "Save & exit"}
              </button>
              <button disabled={busy !== null} onClick={() => blocker.reset?.()}>
                Keep editing
              </button>
              <button className="danger-link" disabled={busy !== null} onClick={discardAndExit}>
                Discard changes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
