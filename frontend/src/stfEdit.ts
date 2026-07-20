// Pure text transforms for the correction editor's tap-to-toggle mark bar.
// Marks are stored as ASCII suffixes on a note (R_ flat, M^ sharp, S' upper
// octave, S, lower octave) — the reviewer shouldn't have to touch-type them.
// These helpers edit the raw STF line text and report where the caret should
// land, so EditorPage can restore it after the controlled input re-renders.
//
// They are deliberately permissive: an illegal mark (S_, R^) is left for the
// advisory validator to flag, matching the app's "flag, don't silently fix"
// rule. Only M is ever sharp; only R G D N are ever flat.

export type Mark = "_" | "^" | "'" | ",";

const NOTE_TOKEN_RE = /[SRGMPDN][_^',]*/g;

/**
 * The note token the caret sits in (or on the edge of), else the nearest note
 * to its left — so "type G, tap ♭" flats the G just entered. Null if no note
 * precedes the caret. Returns the token's [start, end) offsets.
 */
export function noteTokenAt(text: string, caret: number): [number, number] | null {
  let best: [number, number] | null = null;
  let m: RegExpExecArray | null;
  NOTE_TOKEN_RE.lastIndex = 0;
  while ((m = NOTE_TOKEN_RE.exec(text)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    if (caret >= start && caret <= end) return [start, end]; // inside or on an edge
    if (end <= caret) best = [start, end]; // a candidate to the left
    else break; // token begins after the caret — nothing closer follows
  }
  return best;
}

/** Toggle one accidental/octave mark on the note at the caret. */
export function toggleMark(
  text: string,
  caret: number,
  mark: Mark,
): { text: string; caret: number } {
  const span = noteTokenAt(text, caret);
  if (!span) return { text, caret };
  const [start, end] = span;
  const letter = text.slice(start, start + 1);
  let mods = text.slice(start + 1, end);
  mods = mods.includes(mark) ? mods.replace(mark, "") : mods + mark;
  const token = letter + mods;
  return { text: text.slice(0, start) + token + text.slice(end), caret: start + token.length };
}

/**
 * Insert a structural token (barline, hold, rest) at the caret, normalising the
 * whitespace around it to single spaces so taps never pile up double spaces.
 */
export function insertToken(
  text: string,
  caret: number,
  token: string,
): { text: string; caret: number } {
  const before = text.slice(0, caret).replace(/\s+$/, "");
  const after = text.slice(caret).replace(/^\s+/, "");
  const head = (before ? before + " " : "") + token + " ";
  return { text: head + after, caret: head.length };
}
