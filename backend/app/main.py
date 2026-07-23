"""App factory."""

import sqlite3
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from . import db
from .auth import (
    INITIAL_OWNER_ID,
    SESSION_COOKIE,
    authenticate_session,
    configure_oauth,
    prepare_initial_owner,
    renew_session,
    require_same_origin,
)
from .auth import (
    router as auth_router,
)
from .config import APP_VERSION, Settings
from .recognition import Recognizer, make_recognizer
from .routers import scans, songs, transcriptions
from .schemas import Health


class SpaStaticFiles(StaticFiles):
    """Serve built frontend assets with an index fallback for React routes."""

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            is_client_route = (
                exc.status_code == 404
                and not scope["path"].startswith("/api/")
                and PurePosixPath(path).suffix == ""
            )
            if not is_client_route:
                raise
            return await super().get_response("index.html", scope)


def create_app(settings: Settings | None = None, recognizer: Recognizer | None = None) -> FastAPI:
    settings = settings or Settings()
    # Tests inject a fake recognizer; production builds the real Claude client
    # lazily (no SDK import / API key needed unless recognition is actually run).
    recognizer = recognizer or make_recognizer(
        settings.anthropic_api_key, settings.recognition_model
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.validate_auth()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db.migrate(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            prepare_initial_owner(conn, settings)
        finally:
            conn.close()
        yield

    app = FastAPI(title="SaReGaMaPic API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.recognizer = recognizer
    app.state.oauth = configure_oauth(settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oauth_state_secret or "local-development-only",
        session_cookie="srg_oauth",
        max_age=600,
        same_site="lax",
        https_only=settings.secure_cookies,
    )

    @app.middleware("http")
    async def db_and_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        conn: sqlite3.Connection = db.connect(settings.db_path)
        request.state.db = conn
        request.state.request_id = uuid.uuid4().hex
        try:
            session_token = request.cookies.get(SESSION_COOKIE)
            authenticated_session = None
            if settings.auth_enabled:
                authenticated_session = authenticate_session(conn, session_token, settings)
                request.state.user_id = (
                    authenticated_session.user_id if authenticated_session is not None else None
                )
                public_path = request.url.path in {
                    "/api/health",
                    "/api/auth/login",
                    "/api/auth/callback",
                }
                if request.url.path.startswith("/api/") and not public_path:
                    if request.state.user_id is None:
                        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
                    try:
                        require_same_origin(request, settings)
                    except StarletteHTTPException as exc:
                        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            else:
                request.state.user_id = INITIAL_OWNER_ID
            response = await call_next(request)
            if (
                authenticated_session is not None
                and authenticated_session.should_renew
                and session_token is not None
            ):
                renew_session(conn, session_token, settings, response)
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            conn.close()

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        csp = (
            "default-src 'self'; "
            "base-uri 'none'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "img-src 'self' data: blob:; "
            "object-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'"
        )
        if settings.secure_cookies:
            csp += "; upgrade-insecure-requests"
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        response.headers["Content-Security-Policy"] = csp
        response.headers["Permissions-Policy"] = (
            "camera=(self), geolocation=(), microphone=()"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=APP_VERSION)

    app.include_router(auth_router, prefix="/api")
    app.include_router(songs.router, prefix="/api")
    app.include_router(scans.router, prefix="/api")
    app.include_router(transcriptions.router, prefix="/api")

    # The deployed Docker image is a single same-origin service. Local development
    # leaves web_dir unset and continues to use Vite's dev server and /api proxy.
    if settings.web_dir is not None and settings.web_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=settings.web_dir, html=True), name="frontend")
    return app


# uvicorn entry point: `uvicorn app.main:app`
app = create_app()
