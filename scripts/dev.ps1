# Start backend (FastAPI :8000) and frontend (Vite :5173) for development.
# Run from anywhere:  powershell -File scripts\dev.ps1
# Stop with Ctrl+C (stops Vite), then the backend window closes on its own exit.

$repo = Split-Path -Parent $PSScriptRoot

# Backend in its own window so logs stay separate.
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$repo\backend'; uv run uvicorn app.main:app --reload --port 8000"
)

# Frontend in this window. --host makes it reachable from phone/tablet on the LAN.
Set-Location "$repo\frontend"
npm run dev
