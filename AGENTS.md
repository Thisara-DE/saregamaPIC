# Project memory — SaReGaMaPic (Music_App)

This folder holds the code. All project knowledge lives in the vault:
I:\Dropbox\Obsidian\saregamapic\

Follow the session start/end protocol in I:\Dropbox\Obsidian\AGENTS.md.
These memory standards apply to the main session AND every subagent.

## Session start (summary)

1. Read I:\Dropbox\Obsidian\saregamapic\saregamapic-moc.md
2. Read the 2 most recent logs in I:\Dropbox\Obsidian\saregamapic\logs\

## Session end (summary)

1. Write a session log to I:\Dropbox\Obsidian\saregamapic\logs\YYYY-MM-DD-short-description.md
2. Record durable decisions in I:\Dropbox\Obsidian\saregamapic\decisions\
   (MUST be linked from the MOC — unlinked decisions are invisible)
3. Update the MOC if project state materially changed (MOC is an INDEX,
   ~600-word budget)
4. Show the finished session log to the user for review before closing

## Project quick facts

- App: photograph hand-written sargam (S R G M) sheets → faithful digital
  copy → gallery → toggle Original / Digital / Western notation.
- Stack: React+TS PWA (web + installable phone/tablet), FastAPI, SQLite,
  Codex vision for recognition. Canonical data format: STF (Sargam Text
  Format) — see the technical design doc in the vault.
- Fidelity rule: the digital copy preserves the paper's notation,
  punctuation, and line layout verbatim. Never "improve" a transcription.
  Stored STF is always the ORIGINAL scale; transposed views are derived.
- Notation standard v1 (defined 2026-07-17, see the decision record in the
  vault): fixed-S sargam — letters are fingering names, dash below = flat,
  dash above = sharp (M only), octave dots, Concert/Alto header pair.
  Transposition = 12-token chromatic rotation that rewrites letters.
- The user plays Alto Sax (E♭) and bamboo flutes and transcribes Sinhala
  songs by ear. Remaining Western-rendering questions (render pitch, S
  anchor, rhythm→staff details) wait for a Phase 4 user conversation.

## Codebase conventions (Phase 0, 2026-07-17)

Stack details + rationale: vault decision `2026-07-17-phase-0-stack`.

- Layout: `backend/` (FastAPI, uv-managed Python 3.13), `frontend/`
  (Vite 6 + React 19 + strict TS PWA), `data/` (SQLite + scan images;
  gitignored, Dropbox-backed), `scripts/`, `samples/` (Phase 2 eval set —
  READ ONLY, originals of the user's sheets).
- Backend: **plain sqlite3, no ORM.** Schema changes = add
  `backend/app/migrations/NNN_name.sql` (never edit an applied file).
  App factory `create_app(Settings)` — tests inject a tmp `Settings`;
  don't touch module globals. All routes under `/api`.
- Uploaded scan images are immutable originals — never modify, resize, or
  re-encode them in place (fidelity rule). Derived versions get new files.
- Frontend: API types in `src/api/types.ts` mirror `backend/app/schemas.py`
  BY HAND — change both sides in the same commit. All requests go through
  `src/api/client.ts`; same-origin `/api` only (Vite proxies to :8000 —
  no CORS, no base URLs).
- Camera = `<input type="file" capture="environment">`, not getUserMedia.
  Navigation is a state variable in `App.tsx`; introduce react-router when
  Phase 1 needs a 3rd view, don't grow the hand-rolled version.
- Checks before calling work done: `uv run pytest` + `uv run ruff check .`
  (backend), `npm test` + `npm run lint` + `npm run build` (frontend).
- Environment gotchas: Node 20.8 → Vite stays on 6.x until Node ≥ 20.19.
  uv needs system TLS certs (configured in pyproject `[tool.uv]`).
  `frontend/node_modules` and `backend/.venv` carry the
  `com.dropbox.ignored` NTFS stream — re-apply after recreating them
  (commands in README), or Dropbox file locks break Vite/uv.

## Rules

- Never store secrets (Codex API key) in the vault or commit them to the repo.
- Durable technical choices → decision record in the vault, not just code
  comments or chat.
- Outline before executing; show diffs before applying changes.
