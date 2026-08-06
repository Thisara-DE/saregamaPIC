// Single source for the STF token grammar shared across the frontend render,
// edit, and transpose modules (codebase-review finding #6). This note-token
// pattern and the note-bearing line kinds used to be copy-pasted in five places,
// so a notation-standard change was a five-file edit with no compiler help.
//
// The backend mirrors these in `backend/app/stf.py` (`NOTE_TOKEN_PATTERN` +
// `_NOTE_KINDS`). Cross-language duplication is unavoidable, so the two are kept
// as one definition per language, cross-referenced, rather than shared.

// A sargam note token: a letter, then any mix of octave dots and one accidental
// (order-tolerant on input; stfTranspose's canonical writer emits
// letter→dots→accidental). Mirrors backend `stf.NOTE_TOKEN_PATTERN`.
export const NOTE_TOKEN_SOURCE = "[SRGMPDN][_^',]*";

/**
 * A FRESH global note-token regex. Returned by a factory, never shared as a
 * const, because a `/g` regex carries mutable `lastIndex` — one shared instance
 * driving `exec` loops in different modules is a classic cross-call bug.
 */
export function noteTokenRegex(): RegExp {
  return new RegExp(NOTE_TOKEN_SOURCE, "g");
}

// Line kinds that carry sargam note tokens and so get the faithful arc/mark
// render + transposition; every other kind (section, lyric, roadmap, annotation)
// is free text, passed through verbatim. Mirrors backend `stf._NOTE_KINDS`.
export const NOTE_KINDS: ReadonlySet<string> = new Set(["sargam", "run"]);
