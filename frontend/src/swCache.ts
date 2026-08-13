// Service-worker runtime cache names, single-sourced here so the build config
// (vite.config.ts, which bakes them into the generated SW's runtimeCaching) and
// the app runtime (offline.ts, which deletes them on sign-out) can never drift.
// This module MUST stay import-free: vite.config.ts imports it while loading, so
// pulling in React (or anything with side effects) here would run during config
// evaluation. Plain string constants only.

// NetworkFirst — the signed-in identity. Cached so RootGate can boot offline
// from the last-known user instead of the "couldn't reach the server" screen.
export const AUTH_CACHE = "sarega-auth";

// NetworkFirst — read data: the songs list, a song's detail, and per-page
// transcriptions (the STF). Fresh when online, served from cache offline.
export const API_CACHE = "sarega-api";

// CacheFirst — scan images (thumbnail, 1600px preview, full original). These
// are immutable artifacts keyed by scan id (originals never change per the
// fidelity rule; derived copies are pure cache), so once viewed online they are
// available offline without a revalidation round-trip.
export const IMAGE_CACHE = "sarega-images";

// Every runtime cache this app owns — clearOfflineCaches() deletes exactly these
// on sign-out, leaving Workbox's own precache (the app shell) untouched.
export const RUNTIME_CACHES = [AUTH_CACHE, API_CACHE, IMAGE_CACHE] as const;
