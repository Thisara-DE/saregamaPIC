"""Recognition + transcription routes, with an injected fake recognizer
(never hits the network or needs an API key). Also covers image prep."""

import io
import json
import logging
import sqlite3
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.recognition import (
    _SCHEMA_UNSUPPORTED_KEYWORDS,
    STF_OUTPUT_SCHEMA,
    RecognitionResult,
    RecognitionUnavailable,
    make_recognizer,
    prepare_image,
)

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


def test_output_schema_avoids_keywords_structured_outputs_rejects():
    """Structured outputs accept only a subset of JSON Schema. A `minimum` on the
    line number 400'd every recognition call before the image was read, and the
    fake client in the test below cannot catch it — only the real API rejects it."""

    def walk(node, path="schema"):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in _SCHEMA_UNSUPPORTED_KEYWORDS, (
                    f"{path}.{key} is rejected by structured outputs; "
                    "enforce this bound in Python instead"
                )
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(STF_OUTPUT_SCHEMA)


def test_production_recognizer_requests_structured_output_and_handles_truncation(
    monkeypatch,
):
    captured = {}
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps({"song_title": "Title", **_DRAFT_STF}),
            )
        ],
        model="claude-opus-4-8",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **_kwargs: SimpleNamespace(messages=FakeMessages()),
    )
    recognizer = make_recognizer("test-key", "claude-opus-4-8")
    result = recognizer(_jpeg(80, 60), "image/jpeg")
    assert result.stf == _DRAFT_STF
    assert result.suggested_title == "Title"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["output_config"]["format"]["schema"]["required"] == [
        "song_title",
        "header",
        "lines",
    ]

    response.stop_reason = "max_tokens"
    response.content = [SimpleNamespace(type="text", text='{"song_title":')]
    with pytest.raises(RecognitionUnavailable) as error:
        recognizer(_jpeg(80, 60), "image/jpeg")
    assert error.value.code == "max_tokens"
    assert "truncated" in str(error.value)


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


def test_recognition_names_only_an_untitled_song(tmp_path):
    def title_recognizer(_data, _content_type):
        result = _fake_recognizer(_data, _content_type)
        return RecognitionResult(
            stf=result.stf,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            suggested_title="  Tharuda Nidana Maha Re  ",
        )

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=title_recognizer)) as c:
        untitled = c.post(
            "/api/songs/import",
            files={"file": ("p.jpg", io.BytesIO(_jpeg(80, 60)), "image/jpeg")},
        ).json()
        c.post(f"/api/scans/{untitled['scan']['id']}/recognize")
        assert c.get(f"/api/songs/{untitled['song']['id']}").json()["title"] == (
            "Tharuda Nidana Maha Re"
        )

        named = c.post(
            "/api/songs/import",
            data={"title": "My chosen name"},
            files={"file": ("p.jpg", io.BytesIO(_jpeg(80, 60)), "image/jpeg")},
        ).json()
        c.post(f"/api/scans/{named['scan']['id']}/recognize")
        assert c.get(f"/api/songs/{named['song']['id']}").json()["title"] == (
            "My chosen name"
        )


def test_recognition_idempotency_replays_without_second_model_call(tmp_path):
    calls = 0

    def counting_recognizer(_data, _content_type):
        nonlocal calls
        calls += 1
        return _fake_recognizer(_data, _content_type)

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=counting_recognizer)) as c:
        _, scan_id = _scan(c)
        _, other_scan_id = _scan(c)
        headers = {"Idempotency-Key": "recognize-action-1"}
        first = c.post(f"/api/scans/{scan_id}/recognize", headers=headers)
        replay = c.post(f"/api/scans/{scan_id}/recognize", headers=headers)
        conflict = c.post(f"/api/scans/{other_scan_id}/recognize", headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert calls == 1
    assert conflict.status_code == 409


def test_baseline_endpoint_counts_reviewed_pairs_and_ranks_symbols(client):
    """The deployed image ships app/ but not scripts/, so the baseline has to be
    readable over the API to be usable on Railway at all."""
    empty = client.get("/api/recognition/baseline").json()
    assert empty["reviewed_sheet_count"] == 0
    assert empty["baseline_ready"] is False
    assert empty["sheets_needed"] == 5
    assert empty["mean_token_accuracy"] is None

    _, scan_id = _scan(client)
    client.post(f"/api/scans/{scan_id}/recognize")
    corrected = {
        **_DRAFT_STF,
        "lines": [{"n": 1, "kind": "sargam", "text": "S R_ - G | P D N S'"}],
    }
    saved = client.put(
        f"/api/scans/{scan_id}/transcription",
        json={"stf": corrected, "status": "reviewed"},
    )
    assert saved.status_code == 200

    report = client.get("/api/recognition/baseline").json()
    assert report["reviewed_sheet_count"] == 1
    assert report["sheets_needed"] == 4
    assert report["baseline_ready"] is False
    assert report["corrections_by_symbol"][0]["category"] == "accidental"
    assert report["per_sheet"][0]["categories"] == {"accidental": 1}
    # Aggregates only: no STF or token text may reach the response.
    assert "S R" not in json.dumps(report)


def test_recognition_stamps_run_and_transcription_with_one_timestamp(client, tmp_path):
    """The original response reads `transcriptions.updated_at`, a replay reads
    `recognition_runs.created_at`. Separate clock reads made the two bodies
    differ whenever the inserts straddled a millisecond."""
    _, scan_id = _scan(client)
    client.post(f"/api/scans/{scan_id}/recognize")

    conn = sqlite3.connect(tmp_path / "data" / "saregamapic.db")
    row = conn.execute(
        "SELECT t.updated_at, rr.created_at FROM transcriptions t"
        " JOIN recognition_runs rr ON rr.id = t.recognition_run_id"
        " WHERE t.scan_id = ?",
        (scan_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == row[1]


def test_old_idempotency_key_replays_its_original_run_after_rerun(tmp_path):
    calls = 0

    def changing_recognizer(_data, _content_type):
        nonlocal calls
        calls += 1
        result = _fake_recognizer(_data, _content_type)
        return RecognitionResult(
            stf={**result.stf, "lines": [{**result.stf["lines"][0], "text": f"S {calls}"}]},
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=changing_recognizer)) as c:
        _, scan_id = _scan(c)
        first = c.post(
            f"/api/scans/{scan_id}/recognize", headers={"Idempotency-Key": "first"}
        )
        second = c.post(
            f"/api/scans/{scan_id}/recognize", headers={"Idempotency-Key": "second"}
        )
        replay = c.post(
            f"/api/scans/{scan_id}/recognize", headers={"Idempotency-Key": "first"}
        )
    assert first.json()["stf"]["lines"][0]["text"] == "S 1"
    assert second.json()["stf"]["lines"][0]["text"] == "S 2"
    assert replay.json()["stf"]["lines"][0]["text"] == "S 1"
    assert calls == 2


def test_recognition_daily_quota(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        recognition_limit_per_hour=10,
        recognition_quota_per_day=1,
    )
    with TestClient(create_app(settings, recognizer=_fake_recognizer)) as c:
        _, first_scan = _scan(c)
        _, second_scan = _scan(c)
        first = c.post(f"/api/scans/{first_scan}/recognize")
        second = c.post(f"/api/scans/{second_scan}/recognize")
    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["detail"] == "Daily recognition quota reached"


def test_recognize_reruns_preserve_runs_but_not_reviewed(client):
    _, scan_id = _scan(client)
    client.post(f"/api/scans/{scan_id}/recognize")
    # re-running on a draft is fine
    assert client.post(f"/api/scans/{scan_id}/recognize").status_code == 201
    with sqlite3.connect(client.app.state.settings.db_path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM recognition_runs WHERE scan_id = ?", (scan_id,)
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT count(*) FROM transcription_revisions tr"
            " JOIN transcriptions t ON t.id = tr.transcription_id"
            " WHERE t.scan_id = ? AND tr.source = 'recognition'",
            (scan_id,),
        ).fetchone()[0] == 2
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
    # Recognition metrics continue to identify the raw run; the corrected text
    # lives in a separate immutable revision with a privacy-safe diff summary.
    assert r.json()["model"] == "fake-model"
    with sqlite3.connect(client.app.state.settings.db_path) as conn:
        summary = conn.execute(
            "SELECT correction_summary_json FROM transcription_revisions"
            " WHERE source = 'manual' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    assert json.loads(summary)["exact_token_match"] is False
    assert json.loads(summary)["categories"]["accidental"] >= 1


def test_transcription_404_before_recognition(client):
    _, scan_id = _scan(client)
    assert client.get(f"/api/scans/{scan_id}/transcription").status_code == 404
    assert client.post("/api/scans/nope/recognize").status_code == 404


def test_recognition_unavailable_returns_503(tmp_path, caplog):
    def unavailable(_data, _ct):
        raise RecognitionUnavailable("ANTHROPIC_API_KEY is not set")

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=unavailable)) as c:
        song_id = c.post("/api/songs", json={"title": "S"}).json()["id"]
        scan_id = c.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("p.jpg", io.BytesIO(_jpeg(40, 40)), "image/jpeg")},
        ).json()["id"]
        with caplog.at_level(logging.WARNING, logger="saregamapic.security"):
            r = c.post(f"/api/scans/{scan_id}/recognize")
        assert r.status_code == 503
        # The client gets the mapped message; the provider's own text is not
        # rendered into the browser...
        assert r.json()["detail"] == "Recognition is unavailable; try again"
        assert "ANTHROPIC_API_KEY" not in r.text
        # ...but it must still be recoverable from the deployment's logs, since
        # recognition_runs keeps only the error code.
        assert "ANTHROPIC_API_KEY is not set" in caplog.text
        with sqlite3.connect(settings.db_path) as conn:
            run = conn.execute(
                "SELECT outcome, error_code, raw_stf_json FROM recognition_runs"
            ).fetchone()
        assert run == ("failed", "recognition_unavailable", None)


def test_failed_idempotent_recognition_replays_error_without_second_model_call(tmp_path):
    calls = 0

    def unavailable(_data, _ct):
        nonlocal calls
        calls += 1
        raise RecognitionUnavailable("invalid response", code="invalid_json")

    settings = Settings(data_dir=tmp_path / "data")
    with TestClient(create_app(settings, recognizer=unavailable)) as c:
        _, scan_id = _scan(c)
        headers = {"Idempotency-Key": "failed-recognition"}
        first = c.post(f"/api/scans/{scan_id}/recognize", headers=headers)
        replay = c.post(f"/api/scans/{scan_id}/recognize", headers=headers)
        with sqlite3.connect(settings.db_path) as conn:
            action = conn.execute(
                "SELECT status, recognition_run_id FROM recognition_idempotency"
            ).fetchone()
            run = conn.execute(
                "SELECT outcome, error_code FROM recognition_runs WHERE id = ?",
                (action[1],),
            ).fetchone()

    assert first.status_code == 503
    assert replay.status_code == 503
    assert replay.json()["detail"] == "Recognition returned an invalid draft; try again"
    # The whole point: one failure, one answer. The first attempt used to return
    # raw upstream text here while the replay returned the mapped message.
    assert first.json()["detail"] == replay.json()["detail"]
    assert "invalid response" not in first.text
    assert calls == 1
    assert action[0] == "completed"
    assert run == ("failed", "invalid_json")
