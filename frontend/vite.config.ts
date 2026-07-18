/// <reference types="vitest/config" />
import fs from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// LAN HTTPS (needed for PWA install + camera on real devices):
// generate certs with mkcert into frontend/certs/ (see README) and the dev
// server picks them up automatically. Without certs it serves plain HTTP,
// which is fine for desktop localhost work.
const certDir = path.resolve(__dirname, "certs");
const httpsConfig =
  fs.existsSync(path.join(certDir, "cert.pem")) && fs.existsSync(path.join(certDir, "key.pem"))
    ? {
        cert: fs.readFileSync(path.join(certDir, "cert.pem")),
        key: fs.readFileSync(path.join(certDir, "key.pem")),
      }
    : undefined;

export default defineConfig({
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
      },
    }),
  ],
  server: {
    host: true, // listen on LAN so phone/tablet can reach the dev server
    https: httpsConfig,
    proxy: {
      // One rule: everything under /api goes to FastAPI. No CORS needed.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
  },
});
