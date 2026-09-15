// Phase 3.6 — instrument profiles and dynamic key mapping.
//
// THE ONE IDEA. A sargam letter is a fixed FINGERING name, not a scale degree
// (notation standard v1.1). A fingering only becomes a sounding pitch once you
// say which instrument is holding it, so every instrument is modelled by the one
// number that answers that: the concert pitch class the fingering named `S`
// sounds on it. Alto Sax plays S as written G, which on an E♭ horn is concert
// B♭; a bamboo flute tuned to D plays S as concert D.
//
// WHAT THAT BUYS. The stored STF is written in ONE frame — the notation
// standard's own anchor, S = concert B♭ (validated with the user 2026-07-21) —
// and is never rewritten (fidelity rule). Picking up a different instrument then
// costs exactly one extra rotation of the DERIVED view: the same concert music,
// re-fingered. That is the behaviour the user chose (2026-09-08): a Concert G
// sheet stays in concert G on a D flute, so the fingerings move instead of the
// key. Awkward fingerings are an accepted cost — the answer to them is to flip
// to a differently tuned flute, not to silently transpose the tune.
//
// CONSEQUENCE WORTH KNOWING. Under any profile whose S differs from concert B♭,
// the "original scale" view is no longer byte-identical to the stored text; it
// is a re-fingering of it. Only the Alto Sax profile is the identity. The photo
// ("Original" view) is of course untouched either way.

import { pitchClassName, pitchClassSargam, transposeSemitones } from "./stfTranspose";
import { readPref, readSessionPref, writePref, writeSessionPref } from "./prefs";

/**
 * The concert pitch class the STORED sargam letters are anchored to: S = written
 * G on alto sax = concert B♭ (pc 10). This is a property of the notation
 * standard — the frame every transcription is authored in — not of whichever
 * instrument happens to be selected now.
 */
export const CANONICAL_S_PC = 10;

export type InstrumentKind = "alto-sax" | "bamboo-flute";

export interface InstrumentProfile {
  kind: InstrumentKind;
  /**
   * Concert pitch class (0..11) that the fingering `S` sounds on this
   * instrument. This single number carries the whole of "which instrument": a
   * transposing horn and a differently tuned flute differ only in it.
   */
  sPc: number;
}

/** Alto Sax (E♭). S = written G = concert B♭, so this profile is the identity. */
export const ALTO_SAX: InstrumentProfile = { kind: "alto-sax", sPc: CANONICAL_S_PC };

/** A bamboo flute whose S sounds at concert pitch class `sPc`. */
export function bambooFlute(sPc: number): InstrumentProfile {
  return { kind: "bamboo-flute", sPc: mod12(sPc) };
}

export const DEFAULT_PROFILE = ALTO_SAX;

function mod12(n: number): number {
  return ((n % 12) + 12) % 12;
}

export function sameProfile(a: InstrumentProfile, b: InstrumentProfile): boolean {
  return a.kind === b.kind && a.sPc === b.sPc;
}

/** Full name for menus and headings, e.g. "Alto Sax", "Bamboo flute in D". */
export function profileName(p: InstrumentProfile): string {
  return p.kind === "alto-sax" ? "Alto Sax" : `Bamboo flute in ${pitchClassName(p.sPc)}`;
}

/**
 * How far the DERIVED view must rotate: the shift that puts the tune's tonic
 * under the right finger on this instrument, in the smallest register (folded to
 * [-5,+6], the same rule the key selector has always used).
 *
 * Two shifts compose into one integer:
 *   • key    — `targetPc - sourcePc`, zero while the sheet's own key is kept;
 *   • anchor — `CANONICAL_S_PC - profile.sPc`, zero on Alto Sax.
 * Folding them together (rather than applying two rotations) is what keeps the
 * result in the nearest octave and keeps the operation exactly reversible.
 *
 * `targetPc` null = keep the sheet's own concert key (the default).
 *
 * An unknown `sourcePc` (unparseable header) disables only the KEY half: with no
 * tonic there is no interval to transpose by. The anchor half never mentions the
 * key, so it still applies — the letters are alto-anchored fingerings and the
 * instrument in your hands is not an alto, whatever the header does or does not
 * say (finding F35). What is left is exactly `CANONICAL_S_PC - sPc`, which is
 * also what the general expression collapses to at `target == source`.
 */
export function viewSemitones(
  profile: InstrumentProfile,
  sourcePc: number | null,
  targetPc: number | null,
): number {
  if (sourcePc === null) return transposeSemitones(profile.sPc, CANONICAL_S_PC);
  // Where the stored letters would sit had they been authored on THIS
  // instrument; the ordinary key rotation then runs from there.
  const authoredFrom = mod12(sourcePc + profile.sPc - CANONICAL_S_PC);
  return transposeSemitones(authoredFrom, targetPc ?? sourcePc);
}

/**
 * The sargam fingering the tune's tonic falls on for this instrument — a
 * concert-G tune on a D flute is fingered from `M`. Display form (♭/♯), for
 * headers; not STF text.
 */
export function tonicFingering(profile: InstrumentProfile, concertPc: number): string {
  return pitchClassSargam(concertPc - profile.sPc);
}

/**
 * The right-hand half of the header pair, opposite "Concert <key>".
 *
 * Alto Sax keeps the standard's Concert/Alto pair — the written key, up a major
 * 6th. A flute has no written key worth printing (the sargam IS its notation),
 * so it names the tuning plus where the tonic lands under the fingers, which is
 * what actually tells a player how the tune will sit.
 *
 * With no known concert key each half drops what it cannot know and keeps what
 * it can. The sax says nothing — its label is only ever a key, and it re-fingers
 * nothing. A flute still names its tuning, because the letters on screen HAVE
 * been re-fingered for it (see `viewSemitones`); it just cannot say where the
 * tonic falls, having no tonic.
 */
export function instrumentHeader(profile: InstrumentProfile, concertPc: number | null): string {
  const tuning = `Flute ${pitchClassName(profile.sPc)}`;
  if (concertPc === null) return profile.kind === "alto-sax" ? "" : tuning;
  return profile.kind === "alto-sax"
    ? `Alto ${pitchClassName(concertPc + 9)}`
    : `${tuning} · tonic ${tonicFingering(profile, concertPc)}`;
}

/**
 * The right-hand column of one row in the Key selector: the same quantity as
 * `instrumentHeader`, minus the tuning (constant down the list, so it belongs in
 * the column heading rather than repeated on all twelve rows).
 */
export function keyColumnValue(profile: InstrumentProfile, concertPc: number): string {
  return profile.kind === "alto-sax"
    ? pitchClassName(concertPc + 9)
    : tonicFingering(profile, concertPc);
}

/** Heading for that column: "Alto" names a key, "Tonic" names a fingering. */
export function keyColumnHeading(profile: InstrumentProfile): string {
  return profile.kind === "alto-sax" ? "Alto" : "Tonic";
}

/** One line under the selector explaining what the letters on screen mean. */
export function profileHint(profile: InstrumentProfile): string {
  if (profile.kind === "alto-sax") {
    return "Concert → Alto = up a major 6th (down a minor 3rd)";
  }
  const tuning = pitchClassName(profile.sPc);
  return `Fingerings for a flute in ${tuning} — S sounds concert ${tuning}`;
}

// ---------------------------------------------------------------------------
// Persistence. Two different lifetimes, deliberately:
//
//   • WHICH instrument — localStorage. "Keep the most recent choice as the next
//     session's default": you usually pick the same horn up again.
//   • WHETHER we have already asked this playing session — sessionStorage. A
//     playing session is one run of the app: relaunching (or opening a new tab)
//     is when you might have swapped instruments, and that is exactly when
//     sessionStorage clears. A mid-session reload therefore does not re-nag.
//
// Neither is a property of the sheet, so neither goes anywhere near the STF.
// ---------------------------------------------------------------------------

const PROFILE_KEY = "saregamapic.instrument";
const ASKED_KEY = "saregamapic.instrumentAsked";

/** Serialize for storage: "alto-sax" or "bamboo-flute:2". */
export function serializeProfile(p: InstrumentProfile): string {
  return p.kind === "alto-sax" ? "alto-sax" : `bamboo-flute:${p.sPc}`;
}

/**
 * Parse a stored profile, falling back to the default on anything unexpected —
 * a value from an older build, a hand-edited localStorage, a half-written
 * string. A stored preference must never be able to break the viewer.
 */
export function parseProfile(raw: string | null): InstrumentProfile {
  if (raw === "alto-sax") return ALTO_SAX;
  const flute = /^bamboo-flute:(\d{1,2})$/.exec(raw ?? "");
  if (flute) {
    const pc = Number(flute[1]);
    if (pc >= 0 && pc <= 11) return bambooFlute(pc);
  }
  return DEFAULT_PROFILE;
}

export function loadProfile(): InstrumentProfile {
  return parseProfile(readPref(PROFILE_KEY));
}

export function saveProfile(p: InstrumentProfile): void {
  writePref(PROFILE_KEY, serializeProfile(p));
}

/** Has "What are you playing?" already been shown this playing session? */
export function askedThisSession(): boolean {
  return readSessionPref(ASKED_KEY) === "1";
}

export function markAskedThisSession(): void {
  writeSessionPref(ASKED_KEY, "1");
}

/**
 * Every profile the picker offers, in menu order: the sax, then all twelve
 * flute tunings. Designed to grow — Tenor/Soprano Sax (B♭) and a concert flute
 * are each one more entry with their own `sPc` and no other change.
 */
export function allProfiles(): InstrumentProfile[] {
  return [ALTO_SAX, ...Array.from({ length: 12 }, (_, pc) => bambooFlute(pc))];
}
