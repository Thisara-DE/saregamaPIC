/**
 * Persisted UI preferences.
 *
 * These are *working* preferences — the digital view's text size and theme, and
 * whether the correction editor's photo pane is open. None of them is a
 * property of the page being looked at, so they follow the reader across pages
 * and sessions rather than resetting per page (unlike key/octave, which are
 * per-sheet performance choices).
 *
 * `localStorage` can throw outright on ACCESS, not just on write (Safari private
 * mode, storage disabled by policy), so no preference is ever allowed to take a
 * view down with it: reads fall back to null and writes are best-effort.
 */

export function readPref(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* preference is best-effort */
  }
}

/**
 * The same pair scoped to ONE run of the app. `sessionStorage` clears when the
 * tab (or the installed PWA) closes, which is the natural boundary for state
 * that means "during this playing session" — e.g. whether we have already asked
 * which instrument is in the player's hands. A mid-session reload keeps it; a
 * relaunch, when you may well have picked up a different instrument, does not.
 *
 * Guarded exactly like the localStorage pair above, and for the same reason:
 * access itself can throw, and no preference may take a view down with it.
 */
export function readSessionPref(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeSessionPref(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* preference is best-effort */
  }
}
