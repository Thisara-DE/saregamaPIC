"""Songs + scan upload endpoints."""

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile

from ..auth import current_user_id
from ..schemas import Scan, Song, SongCreate, SongDetail
from ..security import enforce_limit, security_event
from ..storage import (
    InvalidImage,
    delete_scan_files,
    extension_for,
    save_scan_image,
    validate_scan_image,
)

router = APIRouter()

MAX_IMAGE_BYTES = 30 * 1024 * 1024  # generous for high-res phone photos

# cover_scan_id = first page, so the gallery can show a thumbnail per song.
_SONG_SELECT = (
    "SELECT s.*,"
    " (SELECT COUNT(*) FROM scans WHERE song_id = s.id) AS scan_count,"
    " (SELECT id FROM scans WHERE song_id = s.id ORDER BY page_no LIMIT 1) AS cover_scan_id"
    " FROM songs s"
)


def _db(request: Request) -> sqlite3.Connection:
    return request.state.db


def _song_row(conn: sqlite3.Connection, song_id: str, owner_id: str) -> sqlite3.Row:
    row = conn.execute(
        f"{_SONG_SELECT} WHERE s.id = ? AND s.owner_id = ?", (song_id, owner_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return row


@router.post("/songs", response_model=Song, status_code=201)
def create_song(body: SongCreate, request: Request) -> Song:
    conn = _db(request)
    owner_id = current_user_id(request)
    song_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO songs (id, title, notes, owner_id) VALUES (?, ?, ?, ?)",
        (song_id, body.title, body.notes, owner_id),
    )
    conn.commit()
    return Song(**dict(_song_row(conn, song_id, owner_id)))


@router.get("/songs", response_model=list[Song])
def list_songs(request: Request) -> list[Song]:
    rows = _db(request).execute(
        f"{_SONG_SELECT} WHERE s.owner_id = ? ORDER BY s.created_at DESC",
        (current_user_id(request),),
    ).fetchall()
    return [Song(**dict(r)) for r in rows]


@router.delete("/songs/{song_id}", status_code=204)
def delete_song(song_id: str, request: Request) -> Response:
    conn = _db(request)
    owner_id = current_user_id(request)
    enforce_limit(
        request,
        action="destructive",
        subject=owner_id,
        limit=request.app.state.settings.destructive_limit_per_hour,
        window_seconds=3600,
    )
    _song_row(conn, song_id, owner_id)  # 404 for unknown or another user's song
    scans = conn.execute(
        "SELECT id, image_path FROM scans WHERE song_id = ?", (song_id,)
    ).fetchall()
    conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))  # scans cascade
    conn.commit()
    data_dir = request.app.state.settings.data_dir
    for scan in scans:
        delete_scan_files(data_dir, scan["image_path"], scan["id"])
    security_event(
        request, "song_delete", "succeeded", user_id=owner_id, resource_id=song_id
    )
    return Response(status_code=204)


@router.get("/songs/{song_id}", response_model=SongDetail)
def get_song(song_id: str, request: Request) -> SongDetail:
    conn = _db(request)
    row = _song_row(conn, song_id, current_user_id(request))
    scans = conn.execute(
        "SELECT id, song_id, page_no, content_type, uploaded_at FROM scans"
        " WHERE song_id = ? ORDER BY page_no",
        (song_id,),
    ).fetchall()
    return SongDetail(**dict(row), scans=[Scan(**dict(s)) for s in scans])


@router.post("/songs/{song_id}/scans", response_model=Scan, status_code=201)
async def upload_scan(song_id: str, file: UploadFile, request: Request) -> Scan:
    conn = _db(request)
    owner_id = current_user_id(request)
    _song_row(conn, song_id, owner_id)
    settings = request.app.state.settings
    enforce_limit(
        request,
        action="upload_rate",
        subject=owner_id,
        limit=settings.upload_limit_per_minute,
        window_seconds=60,
    )
    enforce_limit(
        request,
        action="upload_quota",
        subject=owner_id,
        limit=settings.upload_quota_per_day,
        window_seconds=86_400,
        detail="Daily upload quota reached",
    )

    content_type = file.content_type or ""
    if extension_for(content_type) is None:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type {content_type!r}; expected JPEG, PNG, or WebP",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image larger than 30 MB")
    try:
        validate_scan_image(data, content_type)
    except InvalidImage as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    scan_id = uuid.uuid4().hex
    next_page = conn.execute(
        "SELECT COALESCE(MAX(page_no), 0) + 1 AS n FROM scans WHERE song_id = ?",
        (song_id,),
    ).fetchone()["n"]
    image_path = save_scan_image(
        request.app.state.settings.images_dir, song_id, scan_id, content_type, data
    )
    conn.execute(
        "INSERT INTO scans (id, song_id, page_no, image_path, content_type)"
        " VALUES (?, ?, ?, ?, ?)",
        (scan_id, song_id, next_page, image_path, content_type),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, song_id, page_no, content_type, uploaded_at FROM scans WHERE id = ?",
        (scan_id,),
    ).fetchone()
    security_event(
        request, "scan_upload", "succeeded", user_id=owner_id, resource_id=scan_id
    )
    return Scan(**dict(row))
