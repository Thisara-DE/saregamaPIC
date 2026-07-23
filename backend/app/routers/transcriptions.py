"""Recognition + transcription review (STF).

One current transcription per scan (enforced by a unique index). ``recognize``
creates/replaces the draft from the Claude vision call; ``PUT`` saves the
reviewer's edits (draft or reviewed). Both return advisory validation warnings —
the reviewer is the authority, so warnings never block a save (fidelity +
human-in-the-loop rules).
"""

import json
import sqlite3
import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from ..auth import current_user_id
from ..recognition import RecognitionUnavailable, read_scan_bytes
from ..schemas import Transcription, TranscriptionSave
from ..security import enforce_limit, reject_idempotency, security_event
from ..stf import validate_stf

router = APIRouter()


def _scan_row(request: Request, scan_id: str) -> sqlite3.Row:
    row = request.state.db.execute(
        "SELECT sc.id, sc.song_id, sc.image_path, sc.content_type"
        " FROM scans sc JOIN songs so ON so.id = sc.song_id"
        " WHERE sc.id = ? AND so.owner_id = ?",
        (scan_id, current_user_id(request)),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return row


def _to_response(row: sqlite3.Row) -> Transcription:
    stf = json.loads(row["stf_json"])
    return Transcription(
        id=row["id"],
        scan_id=row["scan_id"],
        status=row["status"],
        stf=stf,
        warnings=validate_stf(stf),
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        updated_at=row["updated_at"],
    )


_SELECT = (
    "SELECT id, scan_id, status, stf_json, model, input_tokens, output_tokens, updated_at"
    " FROM transcriptions WHERE scan_id = ?"
)


@router.get("/scans/{scan_id}/transcription", response_model=Transcription)
def get_transcription(scan_id: str, request: Request) -> Transcription:
    _scan_row(request, scan_id)  # 404 if the scan is unknown
    row = request.state.db.execute(_SELECT, (scan_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No transcription for this scan yet")
    return _to_response(row)


@router.post("/scans/{scan_id}/recognize", response_model=Transcription, status_code=201)
def recognize(
    scan_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Transcription:
    """Run Claude vision on the scan's original image → a draft transcription.

    Refuses to clobber a human-reviewed transcription (409). Overwrites an
    existing draft (re-running recognition is fine).
    """
    return _recognize(scan_id, request, idempotency_key)


def _recognize(
    scan_id: str,
    request: Request,
    idempotency_key: str | None,
) -> Transcription:
    scan = _scan_row(request, scan_id)
    conn: sqlite3.Connection = request.state.db
    owner_id = current_user_id(request)
    if idempotency_key is not None:
        if not 1 <= len(idempotency_key) <= 128 or not idempotency_key.isascii():
            raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")
        prior = conn.execute(
            "SELECT scan_id, status FROM recognition_idempotency"
            " WHERE user_id = ? AND idempotency_key = ?",
            (owner_id, idempotency_key),
        ).fetchone()
        if prior is not None:
            if prior["scan_id"] != scan_id:
                reject_idempotency("Idempotency-Key was already used for another scan")
            if prior["status"] == "started":
                reject_idempotency("Recognition with this Idempotency-Key is in progress")
            completed = conn.execute(_SELECT, (scan_id,)).fetchone()
            if completed is None:
                reject_idempotency("Completed idempotent result is unavailable")
            return _to_response(completed)
    existing = conn.execute(_SELECT, (scan_id,)).fetchone()
    if existing is not None and existing["status"] == "reviewed":
        raise HTTPException(
            status_code=409,
            detail="This scan has a reviewed transcription; edit it instead of re-recognizing",
        )

    data_dir = request.app.state.settings.data_dir
    try:
        image = read_scan_bytes(data_dir, scan["image_path"])
    except OSError as e:
        raise HTTPException(status_code=404, detail="Image file missing from data dir") from e

    settings = request.app.state.settings
    enforce_limit(
        request,
        action="recognition_rate",
        subject=owner_id,
        limit=settings.recognition_limit_per_hour,
        window_seconds=3600,
    )
    enforce_limit(
        request,
        action="recognition_quota",
        subject=owner_id,
        limit=settings.recognition_quota_per_day,
        window_seconds=86_400,
        detail="Daily recognition quota reached",
    )
    if idempotency_key is not None:
        conn.execute(
            "INSERT INTO recognition_idempotency"
            " (user_id, idempotency_key, scan_id, status) VALUES (?, ?, ?, 'started')",
            (owner_id, idempotency_key, scan_id),
        )
        conn.commit()

    recognizer = request.app.state.recognizer
    try:
        result = recognizer(image, scan["content_type"])
    except RecognitionUnavailable as e:
        if idempotency_key is not None:
            conn.execute(
                "DELETE FROM recognition_idempotency"
                " WHERE user_id = ? AND idempotency_key = ?",
                (owner_id, idempotency_key),
            )
            conn.commit()
        raise HTTPException(status_code=503, detail=str(e)) from e

    stf_json = json.dumps(result.stf, ensure_ascii=False)
    if existing is None:
        conn.execute(
            "INSERT INTO transcriptions"
            " (id, scan_id, stf_json, status, model, input_tokens, output_tokens)"
            " VALUES (?, ?, ?, 'draft', ?, ?, ?)",
            (uuid.uuid4().hex, scan_id, stf_json, result.model,
             result.input_tokens, result.output_tokens),
        )
    else:
        conn.execute(
            "UPDATE transcriptions SET stf_json = ?, status = 'draft', model = ?,"
            " input_tokens = ?, output_tokens = ?,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE scan_id = ?",
            (stf_json, result.model, result.input_tokens, result.output_tokens, scan_id),
        )
    conn.commit()
    if idempotency_key is not None:
        conn.execute(
            "UPDATE recognition_idempotency SET status = 'completed'"
            " WHERE user_id = ? AND idempotency_key = ?",
            (owner_id, idempotency_key),
        )
        conn.commit()
    security_event(
        request, "recognition", "succeeded", user_id=owner_id, resource_id=scan_id
    )
    return _to_response(conn.execute(_SELECT, (scan_id,)).fetchone())


@router.put("/scans/{scan_id}/transcription", response_model=Transcription)
def save_transcription(scan_id: str, body: TranscriptionSave, request: Request) -> Transcription:
    """Save the reviewer's edited STF (draft or reviewed). Manual edits clear the
    recognition cost metrics — they no longer describe the saved text."""
    _scan_row(request, scan_id)
    conn: sqlite3.Connection = request.state.db
    stf_json = json.dumps(body.stf.model_dump(), ensure_ascii=False)
    existing = conn.execute(
        "SELECT id FROM transcriptions WHERE scan_id = ?", (scan_id,)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO transcriptions (id, scan_id, stf_json, status) VALUES (?, ?, ?, ?)",
            (uuid.uuid4().hex, scan_id, stf_json, body.status),
        )
    else:
        conn.execute(
            "UPDATE transcriptions SET stf_json = ?, status = ?,"
            " model = NULL, input_tokens = NULL, output_tokens = NULL,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE scan_id = ?",
            (stf_json, body.status, scan_id),
        )
    conn.commit()
    return _to_response(conn.execute(_SELECT, (scan_id,)).fetchone())
