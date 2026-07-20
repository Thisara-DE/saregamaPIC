"""App factory.

create_app() wires settings, DB (migrated on startup), per-request
connections, optional bearer-token auth, and routers. All API routes live
under /api so the Vite dev server can proxy them with one rule.
"""

import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import db
from .config import APP_VERSION, Settings
from .recognition import Recognizer, make_recognizer
from .routers import scans, songs, transcriptions
from .schemas import Health


def create_app(settings: Settings | None = None, recognizer: Recognizer | None = None) -> FastAPI:
    settings = settings or Settings()
    # Tests inject a fake recognizer; production builds the real Claude client
    # lazily (no SDK import / API key needed unless recognition is actually run).
    recognizer = recognizer or make_recognizer(
        settings.anthropic_api_key, settings.recognition_model
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db.migrate(settings.db_path)
        yield

    app = FastAPI(title="SaReGaMaPic API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.recognizer = recognizer

    @app.middleware("http")
    async def db_and_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if settings.api_token:
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {settings.api_token}":
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        conn: sqlite3.Connection = db.connect(settings.db_path)
        request.state.db = conn
        try:
            return await call_next(request)
        finally:
            conn.close()

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=APP_VERSION)

    app.include_router(songs.router, prefix="/api")
    app.include_router(scans.router, prefix="/api")
    app.include_router(transcriptions.router, prefix="/api")
    return app


# uvicorn entry point: `uvicorn app.main:app`
app = create_app()
