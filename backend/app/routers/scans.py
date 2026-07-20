"""Scan image retrieval + deletion."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..storage import delete_scan_files, ensure_preview, ensure_thumbnail

router = APIRouter()


def _scan_row(request: Request, scan_id: str) -> sqlite3.Row:
    row = request.state.db.execute(
        "SELECT id, song_id, image_path, content_type FROM scans WHERE id = ?", (scan_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return row


@router.get("/scans/{scan_id}/image")
def get_scan_image(scan_id: str, request: Request) -> FileResponse:
    row = _scan_row(request, scan_id)
    path = request.app.state.settings.data_dir / row["image_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    return FileResponse(path, media_type=row["content_type"])


@router.get("/scans/{scan_id}/thumbnail")
def get_scan_thumbnail(scan_id: str, request: Request) -> FileResponse:
    row = _scan_row(request, scan_id)
    data_dir = request.app.state.settings.data_dir
    if not (data_dir / row["image_path"]).is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    thumb = ensure_thumbnail(data_dir, row["image_path"], scan_id)
    if thumb is None:
        raise HTTPException(
            status_code=415, detail="Cannot decode this image format for thumbnailing"
        )
    return FileResponse(thumb, media_type="image/webp")


@router.get("/scans/{scan_id}/preview")
def get_scan_preview(scan_id: str, request: Request) -> FileResponse:
    """A downscaled copy for the correction editor — legible marks without the
    4000x3000 original's sluggishness. Pure cache; the original is untouched."""
    row = _scan_row(request, scan_id)
    data_dir = request.app.state.settings.data_dir
    if not (data_dir / row["image_path"]).is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    preview = ensure_preview(data_dir, row["image_path"], scan_id)
    if preview is None:
        raise HTTPException(
            status_code=415, detail="Cannot decode this image format for preview"
        )
    return FileResponse(preview, media_type="image/webp")


@router.delete("/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: str, request: Request) -> Response:
    """Remove one page (e.g. a blurry retake); remaining pages are renumbered 1..n."""
    row = _scan_row(request, scan_id)
    conn: sqlite3.Connection = request.state.db
    conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    remaining = conn.execute(
        "SELECT id FROM scans WHERE song_id = ? ORDER BY page_no", (row["song_id"],)
    ).fetchall()
    for i, r in enumerate(remaining, start=1):
        conn.execute("UPDATE scans SET page_no = ? WHERE id = ?", (i, r["id"]))
    conn.commit()
    delete_scan_files(request.app.state.settings.data_dir, row["image_path"], scan_id)
    return Response(status_code=204)
