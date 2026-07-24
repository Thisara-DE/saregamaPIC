"""End-to-end API tests against a temp data dir (real SQLite, real files)."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.storage import data_dir_is_ephemeral, preview_path, thumbnail_path


def _valid_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), "white").save(buffer, "PNG")
    return buffer.getvalue()


PNG_1PX = _valid_png()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def test_health(client):
    r = client.get("/api/health", headers={"X-Request-ID": "attacker-controlled"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers
    assert len(r.headers["x-request-id"]) == 32
    assert r.headers["x-request-id"] != "attacker-controlled"


def test_https_security_headers(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data", app_base_url="https://app.example.test"
    )
    with TestClient(create_app(settings), base_url="https://app.example.test") as c:
        r = c.get("/api/health")
    assert r.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert "upgrade-insecure-requests" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["permissions-policy"] == (
        "camera=(self), geolocation=(), microphone=()"
    )


def test_compiled_frontend_and_spa_fallback(tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<h1>SaReGaMaPic</h1>", encoding="utf-8")
    (web_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", web_dir=web_dir)

    with TestClient(create_app(settings)) as c:
        assert "SaReGaMaPic" in c.get("/").text
        assert "SaReGaMaPic" in c.get("/songs/abc/pages/1").text
        assert "javascript" in c.get("/app.js").headers["content-type"]
        assert c.get("/missing.js").status_code == 404
        assert c.get("/api/not-a-route").status_code == 404


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


def test_upload_first_import_creates_song_and_first_scan_atomically(client, settings):
    r = client.post(
        "/api/songs/import",
        data={"title": "  Optional title  "},
        files={"file": ("page1.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["song"]["title"] == "Optional title"
    assert body["song"]["scan_count"] == 1
    assert body["scan"]["song_id"] == body["song"]["id"]
    assert body["scan"]["page_no"] == 1
    stored = settings.images_dir / body["song"]["id"] / f"{body['scan']['id']}.png"
    assert stored.read_bytes() == PNG_1PX

    untitled = client.post(
        "/api/songs/import",
        files={"file": ("page2.png", io.BytesIO(PNG_1PX), "image/png")},
    )
    assert untitled.status_code == 201
    assert untitled.json()["song"]["title"] == ""


def test_upload_first_import_does_not_create_song_for_invalid_image(client):
    before = client.get("/api/songs").json()
    r = client.post(
        "/api/songs/import",
        files={"file": ("bad.jpg", io.BytesIO(b"not an image"), "image/jpeg")},
    )
    assert r.status_code == 415
    assert client.get("/api/songs").json() == before


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


def test_upload_rejects_spoofed_malformed_and_polyglot_images(client, settings):
    song_id = client.post("/api/songs", json={"title": "Hostile"}).json()["id"]
    hostile = [
        (b"not really a jpeg\xff\xd9", "image/jpeg"),
        (PNG_1PX, "image/jpeg"),
        (PNG_1PX + b"<script>alert(1)</script>", "image/png"),
    ]
    for data, content_type in hostile:
        r = client.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("hostile", io.BytesIO(data), content_type)},
        )
        assert r.status_code == 415

    assert client.get(f"/api/songs/{song_id}").json()["scans"] == []
    assert not (settings.images_dir / song_id).exists()


def test_upload_rejects_extreme_decoded_dimensions(client, settings):
    song_id = client.post("/api/songs", json={"title": "Too wide"}).json()["id"]
    image = Image.new("1", (16_001, 1))
    data = io.BytesIO()
    image.save(data, "PNG")
    r = client.post(
        f"/api/songs/{song_id}/scans",
        files={"file": ("wide.png", io.BytesIO(data.getvalue()), "image/png")},
    )
    assert r.status_code == 415
    assert "dimensions" in r.json()["detail"]
    assert not (settings.images_dir / song_id).exists()


def test_validation(client):
    assert client.post("/api/songs", json={"title": ""}).status_code == 422
    assert client.get("/api/songs/missing").status_code == 404


def test_hostile_text_is_stored_and_returned_as_inert_data(client):
    title = "\"><script>alert(document.cookie)</script>'; DROP TABLE songs;--"
    notes = "https://evil.example/\nQR: javascript:alert(1)\n{{system prompt}}"
    created = client.post(
        "/api/songs", json={"title": title, "notes": notes, "owner_id": "attacker"}
    )
    assert created.status_code == 201
    assert created.json()["title"] == title
    assert created.json()["notes"] == notes
    assert client.get("/api/songs").status_code == 200
    assert client.get(f"/api/songs/{created.json()['id']}").json()["title"] == title


def test_daily_upload_quota(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        upload_limit_per_minute=10,
        upload_quota_per_day=1,
    )
    with TestClient(create_app(settings)) as limited:
        song_id = limited.post("/api/songs", json={"title": "Quota"}).json()["id"]
        first = limited.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("one.png", io.BytesIO(PNG_1PX), "image/png")},
        )
        second = limited.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("two.png", io.BytesIO(PNG_1PX), "image/png")},
        )
    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["detail"] == "Daily upload quota reached"
    assert second.headers["retry-after"] == "86400"


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


def test_preview_downscales_and_leaves_original_untouched(client, settings):
    song_id = client.post("/api/songs", json={"title": "Preview"}).json()["id"]
    original = _jpeg_bytes(4000, 3000)  # full-res original: too heavy for the editor
    scan = _upload(client, song_id, original)

    r = client.get(f"/api/scans/{scan['id']}/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    preview = Image.open(io.BytesIO(r.content))
    assert preview.size == (1600, 1200)  # longest side capped at 1600, aspect kept

    assert preview_path(settings.data_dir, scan["id"]).is_file()
    stored = settings.images_dir / song_id / f"{scan['id']}.jpg"
    assert stored.read_bytes() == original  # original byte-identical

    assert client.get(f"/api/scans/{scan['id']}/preview").status_code == 200  # cached
    assert client.get("/api/scans/nope/preview").status_code == 404


def test_delete_scan_renumbers_and_removes_files(client, settings):
    song_id = client.post("/api/songs", json={"title": "Del scan"}).json()["id"]
    scans = [_upload(client, song_id, _jpeg_bytes(40, 40)) for _ in range(3)]
    client.get(f"/api/scans/{scans[1]['id']}/thumbnail")  # materialize derived files
    client.get(f"/api/scans/{scans[1]['id']}/preview")

    r = client.delete(f"/api/scans/{scans[1]['id']}")
    assert r.status_code == 204

    detail = client.get(f"/api/songs/{song_id}").json()
    assert [s["page_no"] for s in detail["scans"]] == [1, 2]
    assert [s["id"] for s in detail["scans"]] == [scans[0]["id"], scans[2]["id"]]

    assert not (settings.images_dir / song_id / f"{scans[1]['id']}.jpg").exists()
    assert not thumbnail_path(settings.data_dir, scans[1]["id"]).exists()
    assert not preview_path(settings.data_dir, scans[1]["id"]).exists()
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


def _page_file() -> dict:
    return {"file": ("page.png", io.BytesIO(PNG_1PX), "image/png")}


def test_rename_song_sets_a_title_recognition_left_blank(client):
    """A song recognition never named had no way back to a real name — that is
    the gap this closes, so start from a blank title."""
    song = client.post("/api/songs/import", data={"title": ""}, files=_page_file()).json()["song"]
    assert song["title"] == ""

    renamed = client.patch(f"/api/songs/{song['id']}", json={"title": "  Tharuda Nidana  "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Tharuda Nidana"  # surrounding space trimmed
    assert client.get(f"/api/songs/{song['id']}").json()["title"] == "Tharuda Nidana"

    # Blank or whitespace-only would strand the song again.
    assert client.patch(f"/api/songs/{song['id']}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/songs/{song['id']}", json={"title": ""}).status_code == 422
    assert client.get(f"/api/songs/{song['id']}").json()["title"] == "Tharuda Nidana"
    assert client.patch("/api/songs/missing", json={"title": "X"}).status_code == 404


def test_song_reports_the_first_page_holding_a_digital_version(client):
    """The gallery greys out 'digital version' from this field alone, so it must
    be absent until a transcription exists and then point at the right page."""
    created = client.post(
        "/api/songs/import", data={"title": "Two pages"}, files=_page_file()
    ).json()
    song_id = created["song"]["id"]
    client.post(f"/api/songs/{song_id}/scans", files=_page_file())

    assert client.get(f"/api/songs/{song_id}").json()["digital_page_no"] is None

    pages = client.get(f"/api/songs/{song_id}").json()["scans"]
    second = next(s for s in pages if s["page_no"] == 2)
    client.put(
        f"/api/scans/{second['id']}/transcription",
        json={"stf": {"header": {}, "lines": []}, "status": "draft"},
    )
    assert client.get(f"/api/songs/{song_id}").json()["digital_page_no"] == 2
    assert [s for s in client.get("/api/songs").json() if s["id"] == song_id][0][
        "digital_page_no"
    ] == 2


def test_ephemeral_data_dir_is_detected_only_for_the_container_path(tmp_path):
    """Deploys wipe an unmounted /data silently — the app boots fine and simply
    has no songs, scans, or sessions. This is the only signal there is."""
    # A local checkout keeps data/ inside the repo on the root device; that is
    # normal and must never warn.
    assert data_dir_is_ephemeral(tmp_path) is False

    # Standing in for the deployed path: same device as root = nothing mounted.
    unmounted = tmp_path / "data"
    unmounted.mkdir()
    assert (
        data_dir_is_ephemeral(unmounted, container_dir=unmounted, root=tmp_path) is True
    )

    # A missing container path must not raise on the way to a boolean.
    assert data_dir_is_ephemeral(
        Path("/definitely-not-here"), container_dir=Path("/definitely-not-here")
    ) is False
