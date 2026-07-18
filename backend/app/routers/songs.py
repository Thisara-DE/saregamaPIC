"""Songs + scan upload endpoints."""

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile

from ..schemas import Scan, Song, SongCreate, SongDetail
from ..storage import extension_for, save_scan_image

router = APIRouter()

MAX_IMAGE_BYTES = 30 * 1024 * 1024  # generous for high-res phone photos


def _db(request: Request) -> sqlite3.Connection:
    return request.state.db


def _song_row(conn: sqlite3.Connection, song_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM scans WHERE song_id = s.id) AS scan_count"
        " FROM songs s WHERE s.id = ?",
        (song_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return row


@router.post("/songs", response_model=Song, status_code=201)
def create_song(body: SongCreate, request: Request) -> Song:
    conn = _db(request)
    song_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO songs (id, title, notes) VALUES (?, ?, ?)",
        (song_id, body.title, body.notes),
    )
    conn.commit()
    return Song(**dict(_song_row(conn, song_id)))


@router.get("/songs", response_model=list[Song])
def list_songs(request: Request) -> list[Song]:
    rows = _db(request).execute(
        "SELECT s.*, (SELECT COUNT(*) FROM scans WHERE song_id = s.id) AS scan_count"
        " FROM songs s ORDER BY s.created_at DESC"
    ).fetchall()
    return [Song(**dict(r)) for r in rows]


@router.get("/songs/{song_id}", response_model=SongDetail)
def get_song(song_id: str, request: Request) -> SongDetail:
    conn = _db(request)
    row = _song_row(conn, song_id)
    scans = conn.execute(
        "SELECT id, song_id, page_no, content_type, uploaded_at FROM scans"
        " WHERE song_id = ? ORDER BY page_no",
        (song_id,),
    ).fetchall()
    return SongDetail(**dict(row), scans=[Scan(**dict(s)) for s in scans])


@router.post("/songs/{song_id}/scans", response_model=Scan, status_code=201)
async def upload_scan(song_id: str, file: UploadFile, request: Request) -> Scan:
    conn = _db(request)
    _song_row(conn, song_id)  # 404 if unknown song

    content_type = file.content_type or ""
    if extension_for(content_type) is None:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type {content_type!r}; expected JPEG/PNG/WebP/HEIC",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image larger than 30 MB")

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
    return Scan(**dict(row))
