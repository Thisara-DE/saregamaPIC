"""Recognition + transcription review (STF).

One current transcription per scan (enforced by a unique index). ``recognize``
creates/replaces the draft from the Claude vision call; ``PUT`` saves the
reviewer's edits (draft or reviewed). Both return advisory validation warnings —
the reviewer is the authority, so warnings never block a save (fidelity +
human-in-the-loop rules).
"""

import json
import sqlite3
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from ..auth import current_user_id
from ..learning import correction_summary, encode_summary
from ..recognition import (
    PREPROCESSING_VERSION,
    PROMPT_VERSION,
    RecognitionUnavailable,
    read_scan_bytes,
)
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
    "SELECT id, scan_id, status, stf_json, model, input_tokens, output_tokens,"
    " recognition_run_id, current_revision_id, updated_at"
    " FROM transcriptions WHERE scan_id = ?"
)

_SELECT_RUN = (
    "SELECT t.id, t.scan_id, 'draft' AS status, rr.raw_stf_json AS stf_json,"
    " rr.model, rr.input_tokens, rr.output_tokens, rr.id AS recognition_run_id,"
    " NULL AS current_revision_id, rr.created_at AS updated_at"
    " FROM recognition_runs rr JOIN transcriptions t ON t.scan_id = rr.scan_id"
    " WHERE rr.id = ? AND rr.scan_id = ? AND rr.outcome = 'succeeded'"
)

_FAILURE_DETAILS = {
    "api_error": "Recognition service request failed; try again",
    "configuration": "Recognition is not configured",
    "dependency": "Recognition service is unavailable",
    "invalid_json": "Recognition returned an invalid draft; try again",
    "max_tokens": "Recognition output was truncated; try a clearer crop or split the page",
    "refusal": "The recognition model declined this image",
    "internal_error": "Recognition failed unexpectedly; try again",
    "recognition_unavailable": "Recognition is unavailable; try again",
}


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
            "SELECT scan_id, status, recognition_run_id FROM recognition_idempotency"
            " WHERE user_id = ? AND idempotency_key = ?",
            (owner_id, idempotency_key),
        ).fetchone()
        if prior is not None:
            if prior["scan_id"] != scan_id:
                reject_idempotency("Idempotency-Key was already used for another scan")
            if prior["status"] == "started":
                reject_idempotency("Recognition with this Idempotency-Key is in progress")
            run = conn.execute(
                "SELECT outcome, error_code FROM recognition_runs"
                " WHERE id = ? AND scan_id = ?",
                (prior["recognition_run_id"], scan_id),
            ).fetchone()
            if run is not None and run["outcome"] == "failed":
                detail = _FAILURE_DETAILS.get(
                    run["error_code"], _FAILURE_DETAILS["recognition_unavailable"]
                )
                raise HTTPException(status_code=503, detail=detail)
            completed = conn.execute(
                _SELECT_RUN, (prior["recognition_run_id"], scan_id)
            ).fetchone()
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
        try:
            conn.execute(
                "INSERT INTO recognition_idempotency"
                " (user_id, idempotency_key, scan_id, status)"
                " VALUES (?, ?, ?, 'started')",
                (owner_id, idempotency_key, scan_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            reject_idempotency("Recognition with this Idempotency-Key is in progress")

    recognizer = request.app.state.recognizer
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    try:
        result = recognizer(image, scan["content_type"])
    except RecognitionUnavailable as e:
        conn.execute(
            "INSERT INTO recognition_runs"
            " (id, scan_id, user_id, preprocessing_version, prompt_version,"
            " latency_ms, outcome, error_code)"
            " VALUES (?, ?, ?, ?, ?, ?, 'failed', ?)",
            (
                run_id,
                scan_id,
                owner_id,
                PREPROCESSING_VERSION,
                PROMPT_VERSION,
                round((time.monotonic() - started) * 1000),
                e.code,
            ),
        )
        if idempotency_key is not None:
            conn.execute(
                "UPDATE recognition_idempotency"
                " SET status = 'completed', recognition_run_id = ?"
                " WHERE user_id = ? AND idempotency_key = ?",
                (run_id, owner_id, idempotency_key),
            )
        conn.commit()
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception:
        conn.execute(
            "INSERT INTO recognition_runs"
            " (id, scan_id, user_id, preprocessing_version, prompt_version,"
            " latency_ms, outcome, error_code)"
            " VALUES (?, ?, ?, ?, ?, ?, 'failed', 'internal_error')",
            (
                run_id,
                scan_id,
                owner_id,
                PREPROCESSING_VERSION,
                PROMPT_VERSION,
                round((time.monotonic() - started) * 1000),
            ),
        )
        if idempotency_key is not None:
            conn.execute(
                "UPDATE recognition_idempotency"
                " SET status = 'completed', recognition_run_id = ?"
                " WHERE user_id = ? AND idempotency_key = ?",
                (run_id, owner_id, idempotency_key),
            )
        conn.commit()
        raise

    stf_json = json.dumps(result.stf, ensure_ascii=False)
    suggested_title = (result.suggested_title or "").strip()[:200]
    conn.execute(
        "INSERT INTO recognition_runs"
        " (id, scan_id, user_id, preprocessing_version, prompt_version, model,"
        " suggested_title, raw_stf_json, warnings_json, input_tokens, output_tokens,"
        " latency_ms, outcome)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'succeeded')",
        (
            run_id,
            scan_id,
            owner_id,
            PREPROCESSING_VERSION,
            PROMPT_VERSION,
            result.model,
            suggested_title or None,
            stf_json,
            json.dumps(validate_stf(result.stf), ensure_ascii=False),
            result.input_tokens,
            result.output_tokens,
            round((time.monotonic() - started) * 1000),
        ),
    )
    if suggested_title:
        conn.execute(
            "UPDATE songs SET title = ? WHERE id = ? AND title = ''",
            (suggested_title, scan["song_id"]),
        )
    if existing is None:
        transcription_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO transcriptions"
            " (id, scan_id, stf_json, status, model, input_tokens, output_tokens,"
            " recognition_run_id) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)",
            (
                transcription_id,
                scan_id,
                stf_json,
                result.model,
                result.input_tokens,
                result.output_tokens,
                run_id,
            ),
        )
    else:
        transcription_id = existing["id"]
        conn.execute(
            "UPDATE transcriptions SET stf_json = ?, status = 'draft', model = ?,"
            " input_tokens = ?, output_tokens = ?, recognition_run_id = ?,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE scan_id = ?",
            (
                stf_json,
                result.model,
                result.input_tokens,
                result.output_tokens,
                run_id,
                scan_id,
            ),
        )
    revision_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO transcription_revisions"
        " (id, transcription_id, recognition_run_id, stf_json, status, source)"
        " VALUES (?, ?, ?, ?, 'draft', 'recognition')",
        (revision_id, transcription_id, run_id, stf_json),
    )
    conn.execute(
        "UPDATE transcriptions SET current_revision_id = ? WHERE id = ?",
        (revision_id, transcription_id),
    )
    if idempotency_key is not None:
        conn.execute(
            "UPDATE recognition_idempotency"
            " SET status = 'completed', recognition_run_id = ?"
            " WHERE user_id = ? AND idempotency_key = ?",
            (run_id, owner_id, idempotency_key),
        )
    conn.commit()
    security_event(
        request, "recognition", "succeeded", user_id=owner_id, resource_id=scan_id
    )
    return _to_response(conn.execute(_SELECT, (scan_id,)).fetchone())


@router.put("/scans/{scan_id}/transcription", response_model=Transcription)
def save_transcription(scan_id: str, body: TranscriptionSave, request: Request) -> Transcription:
    """Save the current STF view and append an immutable manual revision."""
    _scan_row(request, scan_id)
    conn: sqlite3.Connection = request.state.db
    stf_json = json.dumps(body.stf.model_dump(), ensure_ascii=False)
    existing = conn.execute(
        "SELECT id, recognition_run_id FROM transcriptions WHERE scan_id = ?", (scan_id,)
    ).fetchone()
    if existing is None:
        transcription_id = uuid.uuid4().hex
        recognition_run_id = None
        conn.execute(
            "INSERT INTO transcriptions (id, scan_id, stf_json, status) VALUES (?, ?, ?, ?)",
            (transcription_id, scan_id, stf_json, body.status),
        )
    else:
        transcription_id = existing["id"]
        recognition_run_id = existing["recognition_run_id"]
        conn.execute(
            "UPDATE transcriptions SET stf_json = ?, status = ?,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE scan_id = ?",
            (stf_json, body.status, scan_id),
        )
    summary_json = None
    if recognition_run_id is not None:
        run = conn.execute(
            "SELECT raw_stf_json FROM recognition_runs WHERE id = ?",
            (recognition_run_id,),
        ).fetchone()
        if run is not None and run["raw_stf_json"] is not None:
            summary_json = encode_summary(
                correction_summary(json.loads(run["raw_stf_json"]), body.stf.model_dump())
            )
    revision_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO transcription_revisions"
        " (id, transcription_id, recognition_run_id, stf_json, status, source,"
        " correction_summary_json) VALUES (?, ?, ?, ?, ?, 'manual', ?)",
        (
            revision_id,
            transcription_id,
            recognition_run_id,
            stf_json,
            body.status,
            summary_json,
        ),
    )
    conn.execute(
        "UPDATE transcriptions SET current_revision_id = ? WHERE id = ?",
        (revision_id, transcription_id),
    )
    conn.commit()
    return _to_response(conn.execute(_SELECT, (scan_id,)).fetchone())
