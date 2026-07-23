"""Google OIDC login backed by opaque, revocable server-side sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import Settings
from .security import client_ip, enforce_limit, security_event

INITIAL_OWNER_ID = "00000000000000000000000000000001"
SESSION_COOKIE = "srg_session"

router = APIRouter(prefix="/auth", tags=["authentication"])


class CurrentUser(BaseModel):
    id: str
    email: str
    display_name: str


def configure_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.auth_enabled:
        oauth.register(
            name="google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth


def prepare_initial_owner(conn: sqlite3.Connection, settings: Settings) -> None:
    if settings.initial_owner_email:
        conn.execute(
            "UPDATE users SET email = ? WHERE id = ?",
            (settings.initial_owner_email.strip().lower(), INITIAL_OWNER_ID),
        )
    if not settings.auth_enabled:
        conn.execute(
            "UPDATE users SET status = 'active' WHERE id = ?", (INITIAL_OWNER_ID,)
        )
    conn.commit()


def current_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )


def create_session(
    conn: sqlite3.Connection, user_id: str, settings: Settings
) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=settings.session_days)
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), user_id, expires_at.isoformat()),
    )
    conn.commit()
    return token


def authenticate_session(conn: sqlite3.Connection, token: str | None) -> str | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT user_id, expires_at, revoked_at FROM sessions WHERE id_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        return None
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return None
    if expires_at <= datetime.now(UTC):
        return None
    return str(row["user_id"])


def require_same_origin(request: Request, settings: Settings) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is None or not hmac.compare_digest(origin.rstrip("/"), settings.app_base_url):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


def _safe_return_to(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlparse(value)
    return value if not parsed.scheme and not parsed.netloc and value.startswith("/") else "/"


@router.get("/login")
async def login(request: Request, return_to: str = "/") -> Response:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return RedirectResponse(_safe_return_to(return_to), status_code=303)
    enforce_limit(
        request,
        action="login",
        subject=client_ip(request),
        limit=settings.login_limit_per_10_minutes,
        window_seconds=600,
    )
    request.session["return_to"] = _safe_return_to(return_to)
    redirect_uri = f"{settings.app_base_url}/api/auth/callback"
    return await request.app.state.oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(status_code=404)
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=401, detail="Google login failed") from exc
    claims = token.get("userinfo")
    if not claims or not claims.get("sub") or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google did not verify this identity")

    email = str(claims.get("email", "")).strip().lower()
    conn: sqlite3.Connection = request.state.db
    user = conn.execute(
        "SELECT id, status FROM users WHERE email = ? COLLATE NOCASE", (email,)
    ).fetchone()
    if user is None or user["status"] == "disabled":
        security_event(request, "login", "uninvited")
        raise HTTPException(status_code=403, detail="This account has not been invited")

    identity = conn.execute(
        "SELECT user_id FROM identities WHERE provider = 'google' AND subject = ?",
        (str(claims["sub"]),),
    ).fetchone()
    if identity is not None and identity["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Identity is linked to another account")

    conn.execute(
        "INSERT OR IGNORE INTO identities (provider, subject, user_id) VALUES ('google', ?, ?)",
        (str(claims["sub"]), user["id"]),
    )
    conn.execute(
        "UPDATE users SET display_name = ?, status = 'active' WHERE id = ?",
        (str(claims.get("name", ""))[:200], user["id"]),
    )
    conn.commit()
    session_token = create_session(conn, str(user["id"]), settings)
    destination = _safe_return_to(request.session.pop("return_to", "/"))
    response = RedirectResponse(destination, status_code=303)
    _set_session_cookie(response, session_token, settings)
    security_event(request, "login", "succeeded", user_id=str(user["id"]))
    return response


@router.get("/me", response_model=CurrentUser)
def me(request: Request) -> CurrentUser:
    row = request.state.db.execute(
        "SELECT id, email, display_name FROM users WHERE id = ? AND status = 'active'",
        (current_user_id(request),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return CurrentUser(**dict(row))


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        request.state.db.execute(
            "UPDATE sessions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            " WHERE id_hash = ?",
            (_token_hash(token),),
        )
        request.state.db.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    security_event(
        request,
        "logout",
        "succeeded",
        user_id=getattr(request.state, "user_id", None),
    )
    return response
