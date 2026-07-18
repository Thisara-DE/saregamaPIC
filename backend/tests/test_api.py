"""End-to-end API tests against a temp data dir (real SQLite, real files)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.storage import thumbnail_path

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


def _jpeg_bytes(width: int, height: int, orientation: int | None = None) -> bytes:
    """A real JPEG, optionally with an EXIF orientation tag (pixels unrotated)."""
    im = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    if orientation is None:
        im.save(buf, "JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _upload(client, song_id: str, data: bytes, content_type: str = "image/jpeg") -> dict:
    r = client.post(
        f"/api/songs/{song_id}/scans",
        files={"file": ("page.jpg", io.BytesIO(data), content_type)},
    )
    assert r.status_code == 201
    return r.json()


def test_thumbnail_generated_cached_and_original_untouched(client, settings):
    song_id = client.post("/api/songs", json={"title": "Thumbs"}).json()["id"]
    original = _jpeg_bytes(1600, 800)
    scan = _upload(client, song_id, original)

    r = client.get(f"/api/scans/{scan['id']}/thumbnail")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    thumb = Image.open(io.BytesIO(r.content))
    assert thumb.size == (512, 256)  # longest side capped, aspect kept

    # cached on disk as a derived file; the original is byte-identical
    assert thumbnail_path(settings.data_dir, scan["id"]).is_file()
    stored = settings.images_dir / song_id / f"{scan['id']}.jpg"
    assert stored.read_bytes() == original

    # second request serves the cache (still correct)
    assert client.get(f"/api/scans/{scan['id']}/thumbnail").status_code == 200
    assert client.get("/api/scans/nope/thumbnail").status_code == 404


def test_thumbnail_applies_exif_orientation(client):
    """Phone photos: EXIF says rotate 90° — the thumbnail must bake that in."""
    song_id = client.post("/api/songs", json={"title": "EXIF"}).json()["id"]
    scan = _upload(client, song_id, _jpeg_bytes(1600, 800, orientation=6))
    r = client.get(f"/api/scans/{scan['id']}/thumbnail")
    thumb = Image.open(io.BytesIO(r.content))
    assert thumb.size == (256, 512)  # landscape pixels + orientation 6 → portrait


def test_delete_scan_renumbers_and_removes_files(client, settings):
    song_id = client.post("/api/songs", json={"title": "Del scan"}).json()["id"]
    scans = [_upload(client, song_id, _jpeg_bytes(40, 40)) for _ in range(3)]
    client.get(f"/api/scans/{scans[1]['id']}/thumbnail")  # materialize a thumb

    r = client.delete(f"/api/scans/{scans[1]['id']}")
    assert r.status_code == 204

    detail = client.get(f"/api/songs/{song_id}").json()
    assert [s["page_no"] for s in detail["scans"]] == [1, 2]
    assert [s["id"] for s in detail["scans"]] == [scans[0]["id"], scans[2]["id"]]

    assert not (settings.images_dir / song_id / f"{scans[1]['id']}.jpg").exists()
    assert not thumbnail_path(settings.data_dir, scans[1]["id"]).exists()
    assert client.delete(f"/api/scans/{scans[1]['id']}").status_code == 404


def test_delete_song_removes_scans_and_images(client, settings):
    song_id = client.post("/api/songs", json={"title": "Del song"}).json()["id"]
    scan = _upload(client, song_id, _jpeg_bytes(40, 40))
    client.get(f"/api/scans/{scan['id']}/thumbnail")

    assert client.delete(f"/api/songs/{song_id}").status_code == 204
    assert client.get(f"/api/songs/{song_id}").status_code == 404
    assert client.get(f"/api/scans/{scan['id']}/image").status_code == 404
    assert not (settings.images_dir / song_id).exists()
    assert not thumbnail_path(settings.data_dir, scan["id"]).exists()
    assert client.delete("/api/songs/missing").status_code == 404


def test_cover_scan_id(client):
    song_id = client.post("/api/songs", json={"title": "Cover"}).json()["id"]
    assert client.get(f"/api/songs/{song_id}").json()["cover_scan_id"] is None
    first = _upload(client, song_id, _jpeg_bytes(40, 40))
    _upload(client, song_id, _jpeg_bytes(40, 40))
    listed = client.get("/api/songs").json()
    assert next(s for s in listed if s["id"] == song_id)["cover_scan_id"] == first["id"]


def test_token_auth(tmp_path):
    s = Settings(data_dir=tmp_path / "data", api_token="secret")
    with TestClient(create_app(s)) as c:
        assert c.get("/api/songs").status_code == 401
        r = c.get("/api/songs", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200
