/// <reference types="vitest/config" />
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";
import { API_CACHE, AUTH_CACHE, IMAGE_CACHE } from "./src/swCache";

const DAY = 24 * 60 * 60;

// LAN HTTPS (needed for PWA install + camera on real devices):
// generate certs with mkcert into frontend/certs/ (see README) and the dev
// server picks them up automatically. Without certs it serves plain HTTP,
// which is fine for desktop localhost work.
// SAREGAMAPIC_NO_HTTPS=1 forces plain HTTP even when certs exist (used by
// tooling that can only talk to http://localhost, e.g. browser previews).
const certDir = path.resolve(__dirname, "certs");
const httpsConfig =
  !process.env.SAREGAMAPIC_NO_HTTPS &&
  fs.existsSync(path.join(certDir, "cert.pem")) &&
  fs.existsSync(path.join(certDir, "key.pem"))
    ? {
        cert: fs.readFileSync(path.join(certDir, "cert.pem")),
        key: fs.readFileSync(path.join(certDir, "key.pem")),
      }
    : undefined;

export default defineConfig({
  // File-sync locks can corrupt Vite's dependency cache (EBUSY on the
  // deps_temp -> deps rename) and serve broken modules. Keep the cache in the
  // operating system's temporary directory.
  cacheDir: path.join(os.tmpdir(), "saregamapic-vite-cache"),
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      // Allow install testing straight from the dev server (Phase 0 runs on
      // `vite dev` over the LAN; there is no deployed build yet).
      devOptions: { enabled: true },
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "SaReGaMaPic",
        short_name: "SaReGaMaPic",
        description:
          "Point. Shoot. Sa Re Ga Ma. — digitize hand-written sargam sheets.",
        theme_color: "#1a1533",
        background_color: "#1a1533",
        display: "standalone",
        orientation: "portrait",
        icons: [
          { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "pwa-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // The SPA fallback must never swallow API calls.
        navigateFallbackDenylist: [/^\/api\//],
        // Offline read (codebase-review finding #16). Without these, Workbox
        // precaches the app shell only, so with no signal the gallery is empty
        // AND RootGate's /api/auth/me fetch throws — the app never even boots.
        // Each entry defaults to GET, so writes (POST/PUT/PATCH/DELETE:
        // import, recognize, save, delete, rename) always pass through to the
        // network and are never served stale. line-bands and health are left
        // uncached (network-only) — neither is needed to read a sheet.
        runtimeCaching: [
          {
            // The signed-in identity. NetworkFirst so an online load refreshes
            // it, but offline it falls back to the cached user, which is what
            // lets RootGate render the app instead of the error screen.
            urlPattern: /\/api\/auth\/me$/,
            handler: "NetworkFirst",
            options: {
              cacheName: AUTH_CACHE,
              expiration: { maxEntries: 1, maxAgeSeconds: 30 * DAY },
              // A flaky rehearsal-room connection should fall back to cache fast
              // rather than hang the whole app boot behind a slow /me.
              networkTimeoutSeconds: 3,
            },
          },
          {
            // Read data: the songs list (/api/songs), a song's detail
            // (/api/songs/{id}) and per-page transcriptions
            // (/api/scans/{id}/transcription). POST /api/songs/import matches
            // this pattern too but is a POST, so the GET handler ignores it.
            urlPattern: /\/api\/(songs(\/[^/]+)?|scans\/[^/]+\/transcription)$/,
            handler: "NetworkFirst",
            options: {
              cacheName: API_CACHE,
              expiration: { maxEntries: 128, maxAgeSeconds: 30 * DAY },
              networkTimeoutSeconds: 3,
            },
          },
          {
            // Scan images — thumbnail, 1600px preview, full original. Immutable
            // per scan id, so CacheFirst: whatever was viewed online is then
            // available offline with no revalidation. statuses [0,200] keeps it
            // robust to opaque responses; purgeOnQuotaError lets the browser
            // reclaim these (the largest, most disposable cache) under pressure.
            urlPattern: /\/api\/scans\/[^/]+\/(thumbnail|preview|image)$/,
            handler: "CacheFirst",
            options: {
              cacheName: IMAGE_CACHE,
              expiration: {
                maxEntries: 256,
                maxAgeSeconds: 60 * DAY,
                purgeOnQuotaError: true,
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    host: true, // listen on LAN so phone/tablet can reach the dev server
    https: httpsConfig,
    proxy: {
      // One rule: everything under /api goes to FastAPI. No CORS needed.
      // SAREGAMAPIC_API_PORT lets a second dev instance point at its own
      // backend when :8000 is already taken.
      "/api": {
        target: `http://127.0.0.1:${process.env.SAREGAMAPIC_API_PORT ?? "8000"}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
  },
});
