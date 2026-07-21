// Fixed-S transposition — the Phase 3 core. A song's canonical STF is stored
// verbatim in its ORIGINAL scale and NEVER rewritten (fidelity rule + notation
// standard v1.1); the Digital view (and, later, the Western view) are DERIVED by
// rotating a copy of the text through this pure module.
//
// Semantics (vault decision 2026-07-17-notation-standard-v1, "Notation standard
// v1.1"): each sargam letter is a fixed fingering name, i.e. a pitch class
// measured in semitones from S. Transposing to a new scale rotates every note by
// the interval between the source and target tonic and re-renders the letters —
// the fingering PATTERN relative to the (new) S is unchanged, so the same melody
// is playable in the new key.
//
// Octave-crossing rule: a note is modelled as a single ABSOLUTE semitone integer
//     absolute = 12 * octave + pitchClass          (octave = #upper − #lower dots)
// and transposition is just `absolute + k`. A rotation that carries a pitch class
// across the S boundary therefore lands in the adjacent octave automatically (an
// octave dot appears/disappears). Because it is one integer, the operation is
// exactly reversible: transpose(+k) then transpose(−k) restores every note — the
// round-trip guarantee the engine is verified against.
//
// Only genuine pitch tokens are rotated. Alien letters (a misread `B`) and
// illegal accidentals (`S_`, `M_`, `R^` …) are passed through VERBATIM — matching
// the app's "flag, don't silently fix" rule; the advisory validator surfaces them
// and the reviewer fixes them in the ORIGINAL scale, never here.

// Semitones from S for each natural letter — the fixed-S chromatic space
// (mirrors backend NATURAL_PC in stf.py).
const NATURAL_PC: Record<string, number> = {
  S: 0,
  R: 2,
  G: 4,
  M: 5,
  P: 7,
  D: 9,
  N: 11,
};

// Canonical token for each pitch class 0..11: S and P never take an accidental,
// flats live on R G D N, the lone sharp on M. This bijection is what makes a
// rotation lossless — every pitch class has exactly one spelling.
const PC_TOKEN: { letter: string; accidental: "" | "_" | "^" }[] = [
  { letter: "S", accidental: "" }, // 0
  { letter: "R", accidental: "_" }, // 1  R♭
  { letter: "R", accidental: "" }, // 2
  { letter: "G", accidental: "_" }, // 3  G♭
  { letter: "G", accidental: "" }, // 4
  { letter: "M", accidental: "" }, // 5
  { letter: "M", accidental: "^" }, // 6  M♯
  { letter: "P", accidental: "" }, // 7
  { letter: "D", accidental: "_" }, // 8  D♭
  { letter: "D", accidental: "" }, // 9
  { letter: "N", accidental: "_" }, // 10 N♭
  { letter: "N", accidental: "" }, // 11
];

// A sargam note token: a letter then any mix of octave dots and one accidental.
const NOTE_RE = /[SRGMPDN][_^',]*/g;

// Western note name -> pitch class (0..11), for scale selectors / header labels
// (mirrors backend _NOTE_BASE in stf.py).
const NOTE_BASE: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/**
 * Western scale name -> pitch class (0..11), ignoring any quality word
 * (maj/minor). Accepts `G`, `Eb`, `B♭`, `F#`, `D maj`, `C minor`. Null when the
 * leading token isn't a note letter. Mirrors backend parse_pitch_class.
 */
export function scalePitchClass(scale: string): number | null {
  const s = scale.trim();
  const base = s ? NOTE_BASE[s.charAt(0).toUpperCase()] : undefined;
  if (base === undefined) return null;
  let pc = base;
  for (const ch of s.slice(1)) {
    if (ch === "#" || ch === "♯") pc += 1;
    else if (ch === "b" || ch === "♭") pc -= 1;
    else break; // stop at the first non-accidental (space, quality word, …)
  }
  return ((pc % 12) + 12) % 12;
}

// Display names for the 12 chromatic scales, indexed by pitch class. Flats are
// used for the black keys (F♯ the lone exception — the standard "favorite"
// spelling), because real music — and this app's stored headers — key in flats
// (E♭, B♭, A♭…), never in D♯/A♯. A song's own header string is still shown
// verbatim where it exists; this table only names DERIVED (transposed) scales.
export const SCALE_NAMES: readonly string[] = [
  "C",
  "D♭",
  "D",
  "E♭",
  "E",
  "F",
  "F♯",
  "G",
  "A♭",
  "A",
  "B♭",
  "B",
];

/** Name for a pitch class 0..11 (wraps), for labelling a transposed scale. */
export function pitchClassName(pc: number): string {
  return SCALE_NAMES[(((pc % 12) + 12) % 12)]!;
}

/**
 * The transposition interval from one tonic to another as a SIGNED semitone
 * count in the range [-5, +6] — the octave-representative NEAREST zero. Using
 * the smallest shift (instead of always rotating 0..11 upward) keeps the
 * transposed melody in the register closest to the original: a down-a-4th key
 * change reads as -5, not +7 up a 5th, so notes don't jump into a super-high
 * octave (spurious double dots). A whole-octave manual nudge layers on top of
 * this in the viewer; both are uniform shifts, so intervals and the exact
 * round-trip guarantee are untouched.
 */
export function transposeSemitones(sourcePc: number, targetPc: number): number {
  const k = (((targetPc - sourcePc) % 12) + 12) % 12; // 0..11 (upward)
  return k > 6 ? k - 12 : k; // fold to [-5, +6]; tritone (6) stays +6
}

interface ParsedNote {
  letter: string;
  accidental: "" | "_" | "^";
  octave: number; // #upper dots − #lower dots
}

/**
 * Parse a note token into (letter, single accidental, octave). Returns null when
 * the token is not a well-formed, LEGAL pitch — i.e. the accidental breaks the
 * fixed-S rules (S/P accidental, M flat, R/G/D/N sharp, or both marks at once).
 * Such tokens are left verbatim by the caller.
 */
function parseLegalNote(token: string): ParsedNote | null {
  const letter = token.charAt(0);
  const mods = token.slice(1);
  const flat = mods.includes("_");
  const sharp = mods.includes("^");
  if (flat && sharp) return null;
  let accidental: "" | "_" | "^" = "";
  if (flat) {
    if (letter !== "R" && letter !== "G" && letter !== "D" && letter !== "N") return null;
    accidental = "_";
  } else if (sharp) {
    if (letter !== "M") return null;
    accidental = "^";
  }
  const octave = (mods.match(/'/g)?.length ?? 0) - (mods.match(/,/g)?.length ?? 0);
  return { letter, accidental, octave };
}

/** Render an absolute semitone offset (from middle S) as a canonical token. */
function renderAbsolute(absolute: number): string {
  const octave = Math.floor(absolute / 12);
  const pc = absolute - octave * 12; // 0..11 (floor keeps this non-negative)
  const { letter, accidental } = PC_TOKEN[pc]!;
  // Canonical mark order: letter, octave dots, accidental. Chosen to match the
  // recognizer's real output (e.g. `R'_`, `M'^`) so transpose(text, 0) reproduces
  // stored tokens byte-for-byte — the round-trip returns the exact original.
  // Display-invariant: StfLineText / parseNote accept marks in any order.
  const dots = octave > 0 ? "'".repeat(octave) : octave < 0 ? ",".repeat(-octave) : "";
  return letter + dots + accidental;
}

/**
 * Transpose one line of STF text by `semitones`, rotating every legal note token
 * and preserving everything else (holds `-`, rests `+`, barlines `|`, `//`,
 * curves `(…)`, brackets `[…]`, spacing, lyrics) verbatim. A `semitones` of 0
 * returns the text unchanged (the Original-scale view stays exactly verbatim).
 */
export function transposeLine(text: string, semitones: number): string {
  if (semitones === 0) return text; // identity: keep stored text byte-for-byte
  return text.replace(NOTE_RE, (token) => {
    const note = parseLegalNote(token);
    if (!note) return token; // alien letter / illegal accidental → verbatim
    const absolute =
      12 * note.octave + NATURAL_PC[note.letter]! + accidentalOffset(note.accidental);
    return renderAbsolute(absolute + semitones);
  });
}

function accidentalOffset(accidental: "" | "_" | "^"): number {
  return accidental === "_" ? -1 : accidental === "^" ? 1 : 0;
}

// Line kinds that carry note tokens (mirrors backend _NOTE_KINDS). Others
// (section, lyric, roadmap, annotation) are free text and pass through untouched.
const NOTE_KINDS = new Set(["sargam", "run"]);

/**
 * Transpose a note-bearing line, or return non-note lines unchanged. `kind` is
 * the StfLine kind; only `sargam`/`run` lines are rotated.
 */
export function transposeLineOfKind(kind: string, text: string, semitones: number): string {
  return NOTE_KINDS.has(kind) ? transposeLine(text, semitones) : text;
}
