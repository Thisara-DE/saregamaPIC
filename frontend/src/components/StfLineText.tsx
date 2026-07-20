import { Fragment, type ReactNode } from "react";

/**
 * Render a sargam/run line the way it looks on paper: flat = underline,
 * sharp (M only) = overline, octave dots above/below the letter. The
 * accidental and octave marks are given a distinct accent colour because
 * dot-below (octave) vs dash-below (flat) is the #1 recognition confusion —
 * making them visually loud helps the reviewer catch mis-reads (fidelity rule).
 *
 * Storage is ASCII (R_ flat, M^ sharp, S' upper dot, S, lower dot); this only
 * changes how it *displays*, never the stored text.
 */

const NOTE_RE = /[SRGMPDN][_^',]*/g;

interface NoteToken {
  letter: string;
  flat: boolean;
  sharp: boolean;
  above: number; // upper-octave dots
  below: number; // lower-octave dots
}

export function parseNote(token: string): NoteToken {
  const mods = token.slice(1);
  return {
    letter: token.slice(0, 1),
    flat: mods.includes("_"),
    sharp: mods.includes("^"),
    above: (mods.match(/'/g) ?? []).length,
    below: (mods.match(/,/g) ?? []).length,
  };
}

function Note({ token }: { token: string }) {
  const { letter, flat, sharp, above, below } = parseNote(token);
  const cls = ["stf-note", flat && "flat", sharp && "sharp"].filter(Boolean).join(" ");
  return (
    <span className={cls}>
      <span className="stf-dots above" aria-hidden="true">
        {above > 0 ? "•".repeat(above) : " "}
      </span>
      <span className="stf-letter">{letter}</span>
      <span className="stf-dots below" aria-hidden="true">
        {below > 0 ? "•".repeat(below) : " "}
      </span>
    </span>
  );
}

/** Render notes + literal passthrough (holds, rests, barlines, brackets). */
function renderInline(text: string, key: { n: number }): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  NOTE_RE.lastIndex = 0;
  while ((m = NOTE_RE.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(<Fragment key={key.n++}>{text.slice(last, m.index)}</Fragment>);
    }
    nodes.push(<Note key={key.n++} token={m[0]} />);
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    nodes.push(<Fragment key={key.n++}>{text.slice(last)}</Fragment>);
  }
  return nodes;
}

// A curve `( … )` is drawn on paper as an arc UNDER the group, not literal
// parens. Match balanced (non-nested) groups; a still-open `(` (mid-typing)
// falls through as literal text until the reviewer closes it.
const CURVE_RE = /\(([^)]*)\)/g;

export function StfLineText({ text }: { text: string }) {
  const nodes: ReactNode[] = [];
  const key = { n: 0 };
  let last = 0;
  let m: RegExpExecArray | null;
  CURVE_RE.lastIndex = 0;
  while ((m = CURVE_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(...renderInline(text.slice(last, m.index), key));
    nodes.push(
      <span key={key.n++} className="stf-curve">
        {renderInline(m[1] ?? "", key)}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(...renderInline(text.slice(last), key));
  return <span className="stf-line-render">{nodes}</span>;
}
