import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  getSong,
  getTranscription,
  recognizeScan,
  saveTranscription,
  scanImageUrl,
} from "../api/client";
import { StfLineText } from "../components/StfLineText";
import type { Stf, StfLine, Transcription, TranscriptionStatus } from "../api/types";

const KINDS = ["sargam", "run", "section", "lyric", "roadmap", "annotation"] as const;
const NOTE_KINDS = new Set(["sargam", "run"]);

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
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    try {
      apply(await recognizeScan(scanId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function handleSave(next: TranscriptionStatus) {
    if (!scanId) return;
    setBusy("save");
    setError(null);
    try {
      apply(await saveTranscription(scanId, stf, next));
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

  return (
    <div className="editor">
      <div className="editor-bar">
        <button className="viewer-btn" onClick={() => navigate(`/songs/${songId}`)}>
          ✕
        </button>
        <span className="viewer-title">
          {title ? `${title} — page ${page}` : "…"}
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

      <div className="editor-split">
        <div className="editor-photo">
          {scanId && <img src={scanImageUrl(scanId)} alt={`Page ${page} of ${title}`} />}
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
