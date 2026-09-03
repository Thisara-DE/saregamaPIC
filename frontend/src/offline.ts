import { useEffect, useState } from "react";
import { API_CACHE, RUNTIME_CACHES } from "./swCache";

/**
 * Live online/offline state, tracking `navigator.onLine` plus the window
 * `online`/`offline` events. Used to show the offline banner on the read
 * surfaces (offline read — finding #16), so cached data is legible as cached.
 *
 * `navigator.onLine` only guarantees the negative: `false` means definitely
 * offline; `true` means "has a network interface", not "the server is
 * reachable". That is the right bias for a banner — we warn only when we are
 * certain there is no connection, never a false alarm.
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    // Sync once on mount in case the state changed before listeners attached.
    setOnline(navigator.onLine);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}

/**
 * Delete this app's service-worker runtime caches (identity, read data, images).
 * Called on sign-out so a signed-out — or a subsequently different — user on the
 * same device cannot read the previous session's cached songs offline. Workbox's
 * own precache (the app shell) is deliberately left intact; it holds no
 * user data and is needed to load the login screen.
 *
 * A no-op where the Cache Storage API is absent (e.g. jsdom, or a browser with
 * no service worker), so callers can await it unconditionally.
 */
export async function clearOfflineCaches(): Promise<void> {
  if (typeof caches === "undefined") return;
  await Promise.all(RUNTIME_CACHES.map((name) => caches.delete(name)));
}

/**
 * Evict specific GET responses from the read-data cache after a write that
 * changes them. The read-data routes are NetworkFirst with no network timeout,
 * so a stale entry is only ever served when genuinely offline — but a save made
 * just before going offline would otherwise still read back the pre-save copy
 * from cache. Deleting the entry the write invalidated closes that window, so
 * the offline fallback can never resurrect a superseded document (finding F21).
 *
 * `paths` are same-origin `/api/...` request paths (the cache is keyed by the
 * full request URL, so we resolve each against the current origin). A no-op
 * where Cache Storage is absent (jsdom), so callers can await it unconditionally
 * and best-effort — a failed eviction must never fail the write it follows.
 */
export async function invalidateCached(paths: string[]): Promise<void> {
  if (typeof caches === "undefined") return;
  try {
    const cache = await caches.open(API_CACHE);
    await Promise.all(paths.map((p) => cache.delete(p)));
  } catch {
    // Best-effort: the entry expires on its own and NetworkFirst refreshes it
    // the next time we are online, so a failed eviction is not worth surfacing.
  }
}
