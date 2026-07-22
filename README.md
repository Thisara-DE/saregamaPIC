# SaReGaMaPic

*Point. Shoot. Sa Re Ga Ma.*

SaReGaMaPic turns photographs of handwritten sargam music sheets into faithful,
readable digital copies. It is a personal music library for Sinhala songs
transcribed by ear for Alto Saxophone and bamboo flutes.

The app keeps the handwritten page and its digital transcription together. A song
can contain several pages, and each page can be viewed as the original photograph or
as clean digital sargam notation. Western staff notation is the next major view
planned for the app.

## Why it exists

Handwritten transcriptions are valuable but fragile. They can be difficult to search,
awkward to read on a small screen, and easy to lose or damage. Retyping every page is
slow, especially when the notation contains octave dots, accidentals, curves, holds,
rests, repeats, lyrics, and handwritten performance notes.

SaReGaMaPic is designed to make those sheets easier to preserve and use without
changing what was written. The digital copy is a transcription of the page, not a
new arrangement or an attempt to “improve” the music.

## How it works

1. Create a song in the gallery.
2. Photograph a handwritten sheet with a phone or tablet, or upload an existing
   image. Multi-page songs stay grouped together.
3. Ask the app to recognize the handwriting and create a digital sargam draft.
4. Review the draft beside the photograph and correct anything the recognition
   missed.
5. Save the reviewed version and switch between the original photograph and the
   digital copy whenever you play.
6. Select another Concert/Alto key when a transposed view is needed. The original
   transcription remains untouched.

Recognition is intentionally followed by human review. Pencil marks can be faint,
and details such as a dot, short underline, or curved grouping can change the meaning
of a passage. The musician remains the final authority.

## Faithful digital notation

The app preserves the notation as it appears on paper, including:

- sargam notes: S R G M P D N;
- flats, the sharp form of M, and upper- or lower-octave dots;
- holds, rests, barlines, repeats, and curved note groups;
- section headings, free-rhythm runs, endings, directions, and annotations;
- Sinhala lyric fragments written with the music;
- the original line order, spacing, and punctuation as closely as possible.

The saved transcription always represents the sheet in its original scale.
Transposition is a temporary view, so experimenting with another key cannot damage or
replace the reviewed copy.

## What works today

- Installable web app for desktop, phone, and tablet.
- Camera capture and image upload.
- Song gallery with thumbnails and multi-page sheets.
- Full-resolution original-page viewer.
- Handwriting recognition for the project's sargam notation standard.
- Side-by-side correction editor with a live digital preview.
- Visual rendering of accidentals, octave marks, and curved groups.
- Advisory warnings for notation that may have been misread.
- Original and Digital viewer modes.
- Transposition across all 12 keys using Concert/Alto scale pairs.
- Automatic nearest-octave placement plus manual octave adjustment.
- Original photographs stored without resizing or rewriting.

## Project status

SaReGaMaPic has completed **Phase 3**: capture, gallery, recognition, correction,
digital viewing, and sargam transposition are built and working.

The next milestone is **Phase 4 — Western notation**. It will add a third viewer mode
that converts reviewed sargam into readable Western staff notation and follows the
same key selector. Before that view is finalized, the remaining musical choices—such
as Concert versus Alto written pitch and how special rhythm markings should appear on
a staff—will be agreed with the musician.

Two practical recognition checks are still in progress: confirming the latest
faint-pencil improvements on real sheets and verifying that correcting a typical page
on the tablet is faster than retyping it.

## Scope and privacy

This is currently a single-user personal app. It does not include accounts, public
sharing, social features, audio playback, or MIDI. Original sheets and reviewed
transcriptions stay in the owner's local app storage;
recognition sends the prepared page image to the configured vision service only when
the user chooses **Recognize**.

## Project documentation

Requirements, musical notation rules, technical design, decisions, and the detailed
implementation plan are maintained in the project's private documentation.

---

## For developers

### Technology

| Part | Technology | Location |
| --- | --- | --- |
| Frontend | Vite 6, React 19, strict TypeScript, installable PWA | `frontend/` |
| Backend | FastAPI on Python 3.13, managed by uv | `backend/` |
| Storage | SQLite plus immutable original scan images | `data/` |

Vite remains on 6.x while the development machine uses Node 20.8. Upgrade Node to a
current LTS release before moving to a newer Vite major version.

### Run locally

```powershell
# One-time setup
cd backend;  uv sync
cd frontend; npm install

# Start the backend and frontend
powershell -File scripts\dev.ps1
```

Or start each process separately:

```powershell
cd backend;  uv run uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev
```

Open `http://localhost:5173`. The development server sends same-origin `/api`
requests to the backend on port 8000.

For a second local instance, `SAREGAMAPIC_API_PORT` selects another backend port and
`SAREGAMAPIC_NO_HTTPS=1` forces plain HTTP when local certificates exist.

### Checks

```powershell
cd backend;  uv run pytest;  uv run ruff check .
cd frontend; npm test;       npm run lint;      npm run build
```

### Install and test on a phone or tablet

The development server listens on the local network. Plain HTTP can display the app,
but installation and camera features require HTTPS.

1. Install mkcert: `winget install FiloSottile.mkcert`
2. Trust its local certificate authority: `mkcert -install`
3. Generate a certificate for localhost and the computer's current LAN address:

   ```powershell
   mkcert -cert-file frontend\certs\cert.pem -key-file frontend\certs\key.pem localhost <pc-ip>
   ```

4. Restart the frontend. It automatically uses certificates found in
   `frontend/certs/`.
5. Install the mkcert root certificate on the test device:

   - Android: **Settings → Security → Install a certificate → CA certificate**
   - iOS: install the profile, then enable it under
     **Settings → General → About → Certificate Trust Settings**

6. Browse to `https://<pc-ip>:5173` and choose **Install app** or
   **Add to Home Screen**.

Changing certificate trust is a device-security action and should be performed
deliberately by the device owner.

### Repository layout

```text
backend/   FastAPI application, migrations, recognition, and STF validation
frontend/  React PWA, gallery, editor, viewer, and transposition
scripts/   Development launcher and icon-generation utility
samples/   Read-only real-sheet recognition evaluation set
data/      Runtime database, immutable originals, and derived image caches
```
