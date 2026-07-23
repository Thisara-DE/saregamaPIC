"""Phase 3.4 authentication and cross-user isolation tests."""

import io
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.auth import INITIAL_OWNER_ID, SESSION_COOKIE, create_session
from app.config import Settings
from app.main import create_app


def _valid_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), "white").save(buffer, "PNG")
    return buffer.getvalue()


PNG_1PX = _valid_png()
ORIGIN = "https://app.example.test"


@pytest.fixture
def auth_settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        auth_enabled=True,
        app_base_url=ORIGIN,
        google_client_id="test-client",
        google_client_secret="test-secret",
        oauth_state_secret="x" * 64,
        initial_owner_email="owner@example.com",
    )


@pytest.fixture
def auth_client(auth_settings):
    with TestClient(create_app(auth_settings), base_url=ORIGIN) as client:
        yield client


def _activate_user(settings: Settings, email: str, user_id: str | None = None) -> str:
    user_id = user_id or uuid.uuid4().hex
    conn = db.connect(settings.db_path)
    try:
        if user_id == INITIAL_OWNER_ID:
            conn.execute(
                "UPDATE users SET email = ?, status = 'active' WHERE id = ?",
                (email, user_id),
            )
        else:
            conn.execute(
                "INSERT INTO users (id, email, status) VALUES (?, ?, 'active')",
                (user_id, email),
            )
        conn.commit()
    finally:
        conn.close()
    return user_id


def _session(settings: Settings, user_id: str) -> str:
    conn = db.connect(settings.db_path)
    try:
        return create_session(conn, user_id, settings)
    finally:
        conn.close()


def _as(client: TestClient, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token)


def _post(client: TestClient, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    headers["Origin"] = ORIGIN
    return client.post(path, headers=headers, **kwargs)


def test_auth_rejects_missing_session_and_cross_origin_mutation(
    auth_client, auth_settings
):
    assert auth_client.get("/api/health").status_code == 200
    assert auth_client.get("/api/songs").status_code == 401

    owner_id = _activate_user(
        auth_settings, "owner@example.com", INITIAL_OWNER_ID
    )
    _as(auth_client, _session(auth_settings, owner_id))
    assert auth_client.get("/api/songs").status_code == 200
    assert auth_client.post("/api/songs", json={"title": "No origin"}).status_code == 403
    assert _post(auth_client, "/api/songs", json={"title": "Allowed"}).status_code == 201


def test_logout_revokes_server_session(auth_client, auth_settings):
    owner_id = _activate_user(
        auth_settings, "owner@example.com", INITIAL_OWNER_ID
    )
    token = _session(auth_settings, owner_id)
    _as(auth_client, token)
    assert auth_client.get("/api/auth/me").status_code == 200
    assert _post(auth_client, "/api/auth/logout").status_code == 204
    _as(auth_client, token)
    assert auth_client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(auth_client, auth_settings):
    owner_id = _activate_user(auth_settings, "owner@example.com", INITIAL_OWNER_ID)
    token = _session(auth_settings, owner_id)
    conn = db.connect(auth_settings.db_path)
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    _as(auth_client, token)
    assert auth_client.get("/api/auth/me").status_code == 401


def test_active_session_renews_database_expiry_and_persistent_cookie(
    auth_client, auth_settings
):
    owner_id = _activate_user(auth_settings, "owner@example.com", INITIAL_OWNER_ID)
    token = _session(auth_settings, owner_id)
    near_expiry = datetime.now(UTC) + timedelta(days=1)
    conn = db.connect(auth_settings.db_path)
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = ?",
            (near_expiry.isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    _as(auth_client, token)
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 200
    assert f"Max-Age={auth_settings.session_days * 86400}" in response.headers["set-cookie"]

    conn = db.connect(auth_settings.db_path)
    try:
        renewed = datetime.fromisoformat(
            conn.execute("SELECT expires_at FROM sessions").fetchone()["expires_at"]
        )
    finally:
        conn.close()
    assert renewed > datetime.now(UTC) + timedelta(days=360)


def test_disabled_user_session_is_rejected(auth_client, auth_settings):
    owner_id = _activate_user(auth_settings, "owner@example.com", INITIAL_OWNER_ID)
    token = _session(auth_settings, owner_id)
    conn = db.connect(auth_settings.db_path)
    try:
        conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (owner_id,))
        conn.commit()
    finally:
        conn.close()
    _as(auth_client, token)
    assert auth_client.get("/api/songs").status_code == 401


def test_default_session_lifetime_is_one_year(monkeypatch):
    monkeypatch.delenv("SAREGAMAPIC_SESSION_DAYS", raising=False)
    assert Settings().session_days == 365


def test_login_is_rate_limited_per_ip(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        auth_enabled=True,
        app_base_url=ORIGIN,
        google_client_id="test-client",
        google_client_secret="test-secret",
        oauth_state_secret="x" * 64,
        initial_owner_email="owner@example.com",
        login_limit_per_10_minutes=1,
    )

    class FakeGoogle:
        async def authorize_redirect(self, request, redirect_uri):
            return RedirectResponse("https://accounts.google.test/login")

    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        client.app.state.oauth = SimpleNamespace(google=FakeGoogle())
        first = client.get("/api/auth/login", follow_redirects=False)
        second = client.get("/api/auth/login", follow_redirects=False)
    assert first.status_code == 307
    assert second.status_code == 429
    assert second.headers["retry-after"] == "600"


def test_google_callback_activates_invited_owner_and_preserves_return_path(
    auth_client,
):
    class FakeGoogle:
        async def authorize_redirect(self, request, redirect_uri):
            assert redirect_uri == f"{ORIGIN}/api/auth/callback"
            request.session["oauth_state_tested"] = True
            return RedirectResponse("https://accounts.google.test/login")

        async def authorize_access_token(self, request):
            assert request.session["oauth_state_tested"] is True
            return {
                "userinfo": {
                    "sub": "google-subject-1",
                    "email": "owner@example.com",
                    "email_verified": True,
                    "name": "Thisara",
                }
            }

    auth_client.app.state.oauth = SimpleNamespace(google=FakeGoogle())
    start = auth_client.get(
        "/api/auth/login?return_to=/songs/abc/pages/2", follow_redirects=False
    )
    assert start.status_code == 307
    assert start.headers["location"] == "https://accounts.google.test/login"

    callback = auth_client.get("/api/auth/callback", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/songs/abc/pages/2"
    me = auth_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "id": INITIAL_OWNER_ID,
        "email": "owner@example.com",
        "display_name": "Thisara",
    }


def test_two_users_cannot_discover_or_access_each_others_resources(
    auth_client, auth_settings
):
    owner_a = _activate_user(
        auth_settings, "owner@example.com", INITIAL_OWNER_ID
    )
    owner_b = _activate_user(auth_settings, "other@example.com")
    token_a = _session(auth_settings, owner_a)
    token_b = _session(auth_settings, owner_b)

    _as(auth_client, token_a)
    song = _post(auth_client, "/api/songs", json={"title": "A private song"}).json()
    scan = _post(
        auth_client,
        f"/api/songs/{song['id']}/scans",
        files={"file": ("page.png", io.BytesIO(PNG_1PX), "image/png")},
    ).json()
    stf = {
        "header": {"concert_scale": "G", "alto_scale": "E", "beat": ""},
        "lines": [{"n": 1, "kind": "sargam", "text": "S R G"}],
    }
    saved = auth_client.put(
        f"/api/scans/{scan['id']}/transcription",
        headers={"Origin": ORIGIN},
        json={"stf": stf, "status": "reviewed"},
    )
    assert saved.status_code == 200

    _as(auth_client, token_b)
    assert auth_client.get("/api/songs").json() == []
    assert auth_client.get(f"/api/songs/{song['id']}").status_code == 404
    assert auth_client.get(f"/api/scans/{scan['id']}/image").status_code == 404
    assert auth_client.get(f"/api/scans/{scan['id']}/thumbnail").status_code == 404
    assert auth_client.get(f"/api/scans/{scan['id']}/preview").status_code == 404
    assert auth_client.get(
        f"/api/scans/{scan['id']}/transcription"
    ).status_code == 404
    assert _post(
        auth_client, f"/api/scans/{scan['id']}/recognize"
    ).status_code == 404
    assert auth_client.put(
        f"/api/scans/{scan['id']}/transcription",
        headers={"Origin": ORIGIN},
        json={"stf": stf, "status": "draft"},
    ).status_code == 404
    assert _post(
        auth_client,
        f"/api/songs/{song['id']}/scans",
        files={"file": ("foreign.png", io.BytesIO(PNG_1PX), "image/png")},
    ).status_code == 404
    assert auth_client.delete(
        f"/api/scans/{scan['id']}", headers={"Origin": ORIGIN}
    ).status_code == 404
    assert auth_client.delete(
        f"/api/songs/{song['id']}", headers={"Origin": ORIGIN}
    ).status_code == 404

    _as(auth_client, token_a)
    assert auth_client.get(f"/api/songs/{song['id']}").status_code == 200
    assert auth_client.get(f"/api/scans/{scan['id']}/image").status_code == 200
