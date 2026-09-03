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
