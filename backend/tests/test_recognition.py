"""Recognition + transcription routes, with an injected fake recognizer
(never hits the network or needs an API key). Also covers image prep."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.recognition import RecognitionResult, RecognitionUnavailable, prepare_image

_DRAFT_STF = {
    "header": {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"},
    "lines": [{"n": 1, "kind": "sargam", "text": "S R - G | P D N S'"}],
}


def _jpeg(width: int, height: int, orientation: int | None = None) -> bytes:
    im = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    if orientation is None:
        im.save(buf, "JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _fake_recognizer(_data: bytes, _content_type: str) -> RecognitionResult:
    return RecognitionResult(
        stf=_DRAFT_STF, model="fake-model", input_tokens=123, output_tokens=45
    )


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=_fake_recognizer)) as c:
        yield c


def _scan(client) -> tuple[str, str]:
    song_id = client.post("/api/songs", json={"title": "Rec"}).json()["id"]
    r = client.post(
        f"/api/songs/{song_id}/scans",
        files={"file": ("p.jpg", io.BytesIO(_jpeg(80, 60)), "image/jpeg")},
    )
    return song_id, r.json()["id"]


def test_prepare_image_downscales_and_applies_exif():
    jpeg, media_type = prepare_image(_jpeg(4000, 2000, orientation=6))
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(jpeg)) as im:
        # orientation 6 rotates landscape → portrait; long edge capped at 2600
        assert im.size == (1300, 2600)


def test_recognize_creates_draft_with_metrics(client):
    _, scan_id = _scan(client)
    r = client.post(f"/api/scans/{scan_id}/recognize")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["stf"]["header"]["concert_scale"] == "G"
    assert body["model"] == "fake-model"
    assert body["input_tokens"] == 123 and body["output_tokens"] == 45
    assert body["warnings"] == []  # the fake STF is clean

    # GET returns the same draft
    got = client.get(f"/api/scans/{scan_id}/transcription")
    assert got.status_code == 200
    assert got.json()["stf"] == _DRAFT_STF


def test_recognize_reruns_overwrite_draft_but_not_reviewed(client):
    _, scan_id = _scan(client)
    client.post(f"/api/scans/{scan_id}/recognize")
    # re-running on a draft is fine
    assert client.post(f"/api/scans/{scan_id}/recognize").status_code == 201
    # mark reviewed, then re-recognize is refused
    client.put(
        f"/api/scans/{scan_id}/transcription",
        json={"stf": _DRAFT_STF, "status": "reviewed"},
    )
    assert client.post(f"/api/scans/{scan_id}/recognize").status_code == 409


def test_save_transcription_upserts_and_returns_warnings(client):
    _, scan_id = _scan(client)
    # Start from a recognized draft so the save exercises the UPDATE path and
    # must clear metrics that no longer describe the manually edited text.
    assert client.post(f"/api/scans/{scan_id}/recognize").status_code == 201
    illegal = {"header": {}, "lines": [{"n": 1, "kind": "sargam", "text": "S_ P"}]}
    r = client.put(
        f"/api/scans/{scan_id}/transcription", json={"stf": illegal, "status": "draft"}
    )
    assert r.status_code == 200
    assert any("S and P never" in w for w in r.json()["warnings"])
    # manual save clears recognition metrics (they no longer describe the text)
    assert r.json()["model"] is None
    assert r.json()["input_tokens"] is None
    assert r.json()["output_tokens"] is None


def test_transcription_404_before_recognition(client):
    _, scan_id = _scan(client)
    assert client.get(f"/api/scans/{scan_id}/transcription").status_code == 404
    assert client.post("/api/scans/nope/recognize").status_code == 404


def test_recognition_unavailable_returns_503(tmp_path):
    def unavailable(_data, _ct):
        raise RecognitionUnavailable("ANTHROPIC_API_KEY is not set")

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=unavailable)) as c:
        song_id = c.post("/api/songs", json={"title": "S"}).json()["id"]
        scan_id = c.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("p.jpg", io.BytesIO(_jpeg(40, 40)), "image/jpeg")},
        ).json()["id"]
        r = c.post(f"/api/scans/{scan_id}/recognize")
        assert r.status_code == 503
        assert "ANTHROPIC_API_KEY" in r.json()["detail"]
