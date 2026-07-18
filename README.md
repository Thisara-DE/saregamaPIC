# SaReGaMaPic

*Point. Shoot. Sa Re Ga Ma.*

Photograph a hand-written sargam (S R G M) music sheet and get a faithful
digital copy — same notation, same lines, same punctuation. Browse your
sheets in a gallery and toggle between the original photo, the digital
sargam copy, and (eventually) Western staff notation.

Personal project for transcribing Sinhala songs played on Alto Saxophone
and bamboo flutes.

## Docs

Requirements, technical design, decisions, and the implementation plan live
in the Obsidian vault: `I:\Dropbox\Obsidian\saregamapic\`

## Status

Phase 0 (scaffold) built: installable PWA + FastAPI + SQLite, camera capture
→ image store round trip verified. Remaining Phase 0 exit step: install on
the actual phone and tablet (see "Testing on phone/tablet" below).

## Stack

| Part | Tech | Where |
| --- | --- | --- |
| Frontend | Vite 6 + React 19 + TypeScript (strict), vite-plugin-pwa | `frontend/` |
| Backend | FastAPI on Python 3.13 (managed by uv), plain sqlite3 + SQL migrations | `backend/` |
| Data | SQLite DB + original scan images | `data/` (gitignored, Dropbox-backed) |

Note: Vite is pinned to v6 because this machine runs Node 20.8 (Vite 7 needs
Node 20.19+). If you upgrade Node to 22 LTS, Vite 7 becomes an option.

## Run it (development)

```powershell
# one-time setup
cd backend;  uv sync          # creates .venv, installs deps (uv downloads Python if needed)
cd frontend; npm install

# start both (backend :8000 in its own window, Vite :5173 in this one)
powershell -File scripts\dev.ps1
```

Or individually:

```powershell
cd backend;  uv run uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev
```

Open http://localhost:5173 — the Vite dev server proxies `/api/*` to
FastAPI, so there is no CORS and no base-URL config anywhere.

Running a second dev instance side by side (ports already taken):
`SAREGAMAPIC_API_PORT` points the Vite proxy at a backend on another port,
and `SAREGAMAPIC_NO_HTTPS=1` forces plain HTTP even when `frontend/certs/`
exists (some tooling can only reach http://localhost).

### Checks

```powershell
cd backend;  uv run pytest;  uv run ruff check .
cd frontend; npm test;       npm run lint;      npm run build
```

## Testing on phone/tablet (LAN)

`npm run dev` already listens on the LAN (Vite prints the Network URL).
Plain HTTP is enough to *view* the app from a phone, but **installing the
PWA and using the camera require HTTPS**. One-time setup:

1. Install mkcert on this PC: `winget install FiloSottile.mkcert`
2. Trust its CA locally: `mkcert -install`
3. Generate a cert for this PC's LAN IP (and localhost):
   `mkcert -cert-file frontend\certs\cert.pem -key-file frontend\certs\key.pem localhost 192.168.50.76`
   (replace with the current LAN IP if it changed)
4. Restart `npm run dev` — the config auto-detects `frontend/certs/` and
   serves HTTPS.
5. On each device, install the mkcert root CA (`mkcert -CAROOT` shows the
   file; send it to the device):
   - **Android:** Settings → Security → Install a certificate → CA certificate.
   - **iOS:** AirDrop/email the file, install the profile, then enable it in
     Settings → General → About → Certificate Trust Settings.
6. Browse to `https://<pc-ip>:5173`, then "Add to Home Screen" / "Install app".

Steps 2 and 5 change device trust settings — do them yourself, deliberately.

## Dropbox coexistence

This repo lives inside Dropbox. Two folders are marked ignored for Dropbox
(NTFS stream `com.dropbox.ignored=1`) because sync locks break tooling:
`frontend/node_modules` and `backend/.venv`. The stream can silently
disappear (observed 2026-07-18 — Dropbox locks then corrupted Vite's dep
cache and the app served broken JS). Vite's cache therefore lives OUTSIDE
Dropbox now (`%TEMP%\saregamapic-vite-cache`, set in `vite.config.ts`), but
the streams are still needed so npm/uv installs don't fight sync locks. If
they're missing or you recreate those folders, re-apply:

```powershell
Set-Content -Path frontend\node_modules -Stream com.dropbox.ignored -Value 1
Set-Content -Path backend\.venv        -Stream com.dropbox.ignored -Value 1
```

`data/` intentionally stays synced — that's the backup story for your scans.
Avoid running the backend on two machines at once against the same synced
`data/` (SQLite + concurrent Dropbox sync don't mix).

## Layout

```
backend/   FastAPI app  (app/main.py factory, app/migrations/*.sql schema)
frontend/  React PWA    (src/pages/, src/api/client.ts typed API wrapper)
scripts/   dev.ps1 (run both), make_icons.py (regenerate PWA icons)
samples/   real scanned sheets (Phase 2 recognition eval set — read only)
data/      runtime: saregamapic.db + images/<song>/<scan>.<ext>
```
