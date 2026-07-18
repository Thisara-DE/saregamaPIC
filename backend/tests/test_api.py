"""End-to-end API tests against a temp data dir (real SQLite, real files)."""

import io

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# 1x1 PNG (smallest valid image payload)
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_song_crud_and_scan_roundtrip(client, settings):
    # create song
    r = client.post("/api/songs", json={"title": "Test Song", "notes": "from pytest"})
    assert r.status_code == 201
    song = r.json()
    assert song["title"] == "Test Song"
    assert song["scan_count"] == 0

    # listed
    r = client.get("/api/songs")
    assert [s["id"] for s in r.json()] == [song["id"]]

    # upload a scan
    r = client.post(
        f"/api/songs/{song['id']}/scans",
        files={"file": ("page1.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert r.status_code == 201
    scan = r.json()
    assert scan["page_no"] == 1

    # image landed in the store, under the song's folder
    stored = settings.images_dir / song["id"] / f"{scan['id']}.png"
    assert stored.read_bytes() == PNG_1PX

    # detail shows the scan; page numbering increments
    r = client.post(
        f"/api/songs/{song['id']}/scans",
        files={"file": ("page2.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert r.json()["page_no"] == 2
    detail = client.get(f"/api/songs/{song['id']}").json()
    assert detail["scan_count"] == 2
    assert [s["page_no"] for s in detail["scans"]] == [1, 2]

    # image served back byte-identical
    r = client.get(f"/api/scans/{scan['id']}/image")
    assert r.status_code == 200
    assert r.content == PNG_1PX
    assert r.headers["content-type"] == "image/png"


def test_upload_rejections(client):
    song_id = client.post("/api/songs", json={"title": "S"}).json()["id"]
    # wrong type
    r = client.post(
        f"/api/songs/{song_id}/scans",
        files={"file": ("notes.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert r.status_code == 415
    # empty file
    r = client.post(
        f"/api/songs/{song_id}/scans",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    assert r.status_code == 400
    # unknown song
    r = client.post(
        "/api/songs/nope/scans",
        files={"file": ("p.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert r.status_code == 404


def test_validation(client):
    assert client.post("/api/songs", json={"title": ""}).status_code == 422
    assert client.get("/api/songs/missing").status_code == 404


def test_token_auth(tmp_path):
    s = Settings(data_dir=tmp_path / "data", api_token="secret")
    with TestClient(create_app(s)) as c:
        assert c.get("/api/songs").status_code == 401
        r = c.get("/api/songs", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
