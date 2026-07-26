"""Recognition + transcription routes, with an injected fake recognizer
(never hits the network or needs an API key). Also covers image prep."""

import io
import json
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
    STF_BODY_SCHEMA,
    STF_OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_BODY,
    RecognitionResult,
    RecognitionUnavailable,
    make_recognizer,
    make_tiled_recognizer,
    prepare_image,
    prepare_tiles,
    stitch_tiles,
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
    walk(STF_BODY_SCHEMA)


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

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return response

    class FakeMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return FakeStream()

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


def test_save_transcription_rejects_an_oversized_line(client):
    """One PUT with a 20,000-line x 5,000-char body once grew the SQLite file to
    300+ MB in one request; the per-line text cap is the first guard against it."""
    _, scan_id = _scan(client)
    body = {
        "stf": {"header": {}, "lines": [{"n": 1, "kind": "sargam", "text": "S" * 2001}]},
        "status": "draft",
    }
    r = client.put(f"/api/scans/{scan_id}/transcription", json=body)
    assert r.status_code == 422


def test_save_transcription_rejects_too_many_lines(client):
    """Second guard against the same oversized-PUT abuse: bound line COUNT too,
    not just per-line length."""
    _, scan_id = _scan(client)
    body = {
        "stf": {
            "header": {},
            "lines": [{"n": i, "kind": "sargam", "text": "S"} for i in range(1001)],
        },
        "status": "draft",
    }
    r = client.put(f"/api/scans/{scan_id}/transcription", json=body)
    assert r.status_code == 422


def test_save_transcription_rejects_an_illegal_kind(client):
    """`text`'s max_length alone was not enough: a 100,000-char `kind` on 1000
    lines reproduces the same disk-fill through a different field, since `kind`
    previously had no constraint at all. It must be one of the legal values."""
    _, scan_id = _scan(client)
    body = {
        "stf": {"header": {}, "lines": [{"n": 1, "kind": "X" * 100_000, "text": "S"}]},
        "status": "draft",
    }
    r = client.put(f"/api/scans/{scan_id}/transcription", json=body)
    assert r.status_code == 422


def test_save_transcription_rate_limited(tmp_path):
    """Bounding one request's size isn't enough on its own — a script could still
    send many legal-sized saves back to back, so the endpoint also needs its own
    rate limit (every other write path already has one)."""
    settings = Settings(
        data_dir=tmp_path / "data", transcription_save_limit_per_minute=1
    )
    with TestClient(create_app(settings, recognizer=_fake_recognizer)) as limited:
        song_id = limited.post("/api/songs", json={"title": "Rate"}).json()["id"]
        scan_id = limited.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("p.jpg", io.BytesIO(_jpeg(80, 60)), "image/jpeg")},
        ).json()["id"]
        body = {"stf": {"header": {}, "lines": []}, "status": "draft"}
        first = limited.put(f"/api/scans/{scan_id}/transcription", json=body)
        second = limited.put(f"/api/scans/{scan_id}/transcription", json=body)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_save_transcription_daily_quota(tmp_path):
    """The per-minute limit only slows a disk fill — transcription_revisions is
    append-only, so even legal-sized saves add up fast at 60/minute. A daily
    quota closes that, matching the rate+quota pair every other bounded write
    path (upload, recognition) already has."""
    settings = Settings(
        data_dir=tmp_path / "data",
        transcription_save_limit_per_minute=10,
        transcription_save_quota_per_day=1,
    )
    with TestClient(create_app(settings, recognizer=_fake_recognizer)) as limited:
        song_id = limited.post("/api/songs", json={"title": "Quota"}).json()["id"]
        scan_id = limited.post(
            f"/api/songs/{song_id}/scans",
            files={"file": ("p.jpg", io.BytesIO(_jpeg(80, 60)), "image/jpeg")},
        ).json()["id"]
        body = {"stf": {"header": {}, "lines": []}, "status": "draft"}
        first = limited.put(f"/api/scans/{scan_id}/transcription", json=body)
        second = limited.put(f"/api/scans/{scan_id}/transcription", json=body)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Daily transcription save quota reached"
    assert second.headers["retry-after"] == "86400"


def test_get_returns_a_stored_transcription_with_an_illegal_kind(client):
    """Same inbound/outbound split regression as the oversized-text test below,
    for the `kind` constraint specifically: a row stored with a `kind` outside
    the legal set (older data, or data from before this fix) must still GET
    back as 200, not fail response validation."""
    _, scan_id = _scan(client)
    stored_stf = json.dumps(
        {"header": {}, "lines": [{"n": 1, "kind": "not-a-real-kind", "text": "S"}]}
    )
    with sqlite3.connect(client.app.state.settings.db_path) as conn:
        conn.execute(
            "INSERT INTO transcriptions (id, scan_id, stf_json, status)"
            " VALUES ('preexisting-kind', ?, ?, 'reviewed')",
            (scan_id, stored_stf),
        )
        conn.commit()
    r = client.get(f"/api/scans/{scan_id}/transcription")
    assert r.status_code == 200
    assert r.json()["stf"]["lines"][0]["kind"] == "not-a-real-kind"


def test_get_returns_a_stored_transcription_that_exceeds_the_new_save_limits(client):
    """Regression guard for the inbound/outbound split: `Transcription.stf` (the
    GET response model) must stay permissive. If the new save-time bounds were
    ever applied to the shared `Stf`/`StfLine` model instead of a write-only
    copy, a row already in the database above the limit — exactly what a
    deployed database could hold before this fix shipped — would fail response
    validation and turn a readable page into a 500."""
    _, scan_id = _scan(client)
    oversized_text = "S " * 2000  # far past the 2000-char save-time cap
    oversized_stf = json.dumps(
        {"header": {}, "lines": [{"n": 1, "kind": "sargam", "text": oversized_text}]}
    )
    with sqlite3.connect(client.app.state.settings.db_path) as conn:
        conn.execute(
            "INSERT INTO transcriptions (id, scan_id, stf_json, status)"
            " VALUES ('preexisting', ?, ?, 'reviewed')",
            (scan_id, oversized_stf),
        )
        conn.commit()
    r = client.get(f"/api/scans/{scan_id}/transcription")
    assert r.status_code == 200
    assert r.json()["stf"]["lines"][0]["text"] == oversized_text


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
    assert calls == 1
    assert action[0] == "completed"
    assert run == ("failed", "invalid_json")


# --- Phase 3.5 Rung 1 tiled recognizer (offline experiment variant) ----------

# Frozen hash of the whole-page prompt. PROMPT_VERSION is pinned and 4/5 baseline
# sheets used this exact text; the tiled-experiment refactor split it into shared
# fragments, so this guards the control against a byte-level drift the split could
# introduce. Recompute deliberately (and bump PROMPT_VERSION) if the prompt changes.
_SYSTEM_PROMPT_SHA256 = "8b2462f8d65bd62bcfc96bd48f83f2136b9bf371fa9c556f07da1c30e208dbae"


def test_whole_page_prompt_is_unchanged_by_the_tiling_split():
    import hashlib

    assert hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == _SYSTEM_PROMPT_SHA256


def test_body_prompt_shares_the_notation_contract_but_drops_header_and_title():
    from app.recognition import _LINE_KINDS_AND_RULES, _NOTATION_CONTRACT

    # The two prompts must not drift apart on the notation/line-kind/rules rules.
    assert _NOTATION_CONTRACT in SYSTEM_PROMPT and _NOTATION_CONTRACT in SYSTEM_PROMPT_BODY
    assert _LINE_KINDS_AND_RULES in SYSTEM_PROMPT and _LINE_KINDS_AND_RULES in SYSTEM_PROMPT_BODY
    # A band carries no header/title — only the top band does, via SYSTEM_PROMPT.
    # (The body prompt still tells the model NOT to emit song_title, so it names
    # the field; what must be gone are the capture-instruction sections.)
    assert "## The header" not in SYSTEM_PROMPT_BODY
    assert "## The song title" not in SYSTEM_PROMPT_BODY
    assert "song_title" not in STF_BODY_SCHEMA["properties"]
    assert STF_BODY_SCHEMA["required"] == ["lines"]


def test_prepare_tiles_splits_into_overlapping_capped_bands():
    from app.recognition import _TILE_MAX_EDGE, _TILE_MAX_PIXELS

    bands = prepare_tiles(_jpeg(2000, 4000), tiles=2)
    assert len(bands) == 2
    heights = []
    for jpeg, media_type in bands:
        assert media_type == "image/jpeg"
        with Image.open(io.BytesIO(jpeg)) as im:
            w, h = im.size
            heights.append(h)
            # Each band is kept under BOTH per-image caps so the API shows it at
            # native detail instead of downscaling it server-side.
            assert max(w, h) <= _TILE_MAX_EDGE
            assert w * h <= _TILE_MAX_PIXELS
    # Bands overlap: their heights sum to more than a clean half-and-half split.
    assert sum(heights) > max(heights) * 2 * 0.9


def test_stitch_tiles_concatenates_dedupes_overlap_and_renumbers():
    header = {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"}
    top = [
        {"n": 1, "kind": "section", "text": "Intro"},
        {"n": 2, "kind": "sargam", "text": "S R G M"},
        {"n": 3, "kind": "sargam", "text": "P D N S'"},
    ]
    # The lower band re-sees the last row of the top band (a near-identical read),
    # then adds new rows below it.
    bottom = [
        {"n": 1, "kind": "sargam", "text": "P D N S'"},
        {"n": 2, "kind": "sargam", "text": "S' N D P"},
        {"n": 3, "kind": "lyric", "text": "sinhala"},
    ]
    stitched = stitch_tiles(header, [top, bottom])
    assert stitched["header"] == header
    texts = [line["text"] for line in stitched["lines"]]
    assert texts == ["Intro", "S R G M", "P D N S'", "S' N D P", "sinhala"]
    assert [line["n"] for line in stitched["lines"]] == [1, 2, 3, 4, 5]


def test_stitch_tiles_keeps_distinct_lines_that_merely_look_alike():
    # No genuine overlap: a coincidental resemblance at the seam must NOT be
    # dropped. Different kinds never match; unlike text never matches.
    top = [{"n": 1, "kind": "sargam", "text": "S R G M"}]
    bottom = [{"n": 1, "kind": "sargam", "text": "P D N S"}]
    stitched = stitch_tiles({}, [top, bottom])
    assert [line["text"] for line in stitched["lines"]] == ["S R G M", "P D N S"]


def _tile_response(payload: dict):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        model="claude-opus-4-8",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def test_tiled_recognizer_takes_header_from_top_band_and_stitches_body(monkeypatch):
    captured = []
    responses = iter(
        [
            _tile_response(
                {
                    "song_title": "Sanda Eliya",
                    "header": {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"},
                    "lines": [
                        {"n": 1, "kind": "section", "text": "Intro"},
                        {"n": 2, "kind": "sargam", "text": "S R_ G M"},
                    ],
                }
            ),
            _tile_response(
                # Body band: lines only, no header/title. Its first row repeats the
                # top band's last row (overlap) and must be deduped away.
                {
                    "lines": [
                        {"n": 1, "kind": "sargam", "text": "S R_ G M"},
                        {"n": 2, "kind": "sargam", "text": "P D N S'"},
                    ]
                }
            ),
        ]
    )

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return next(responses)

    class FakeMessages:
        def stream(self, **kwargs):
            captured.append(kwargs)
            return FakeStream()

    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **_kwargs: SimpleNamespace(messages=FakeMessages()),
    )

    recognizer = make_tiled_recognizer("test-key", "claude-opus-4-8", tiles=2)
    result = recognizer(_jpeg(1200, 2400), "image/jpeg")

    # Two band calls: top uses the full schema, body uses the lines-only schema.
    assert len(captured) == 2
    assert captured[0]["output_config"]["format"]["schema"] is STF_OUTPUT_SCHEMA
    assert captured[1]["output_config"]["format"]["schema"] is STF_BODY_SCHEMA
    assert captured[1]["system"] == SYSTEM_PROMPT_BODY
    # Header + title come from the top band; body is stitched with overlap dropped.
    assert result.suggested_title == "Sanda Eliya"
    assert result.stf["header"] == {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"}
    assert [line["text"] for line in result.stf["lines"]] == ["Intro", "S R_ G M", "P D N S'"]
    assert [line["n"] for line in result.stf["lines"]] == [1, 2, 3]
    # Tokens are summed across bands.
    assert result.input_tokens == 200
    assert result.output_tokens == 100
