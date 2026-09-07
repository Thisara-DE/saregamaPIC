"""Scan image retrieval + deletion."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from PIL import Image

from ..auth import current_user_id
from ..line_detection import detect_line_bands
from ..schemas import LineBand, LineBands
from ..security import enforce_limit, security_event
from ..storage import delete_scan_files, ensure_preview, ensure_thumbnail
from ._common import scan_row

router = APIRouter()


@router.get("/scans/{scan_id}/image")
def get_scan_image(scan_id: str, request: Request) -> FileResponse:
    row = scan_row(request, scan_id)
    path = request.app.state.settings.data_dir / row["image_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    return FileResponse(path, media_type=row["content_type"])


@router.get("/scans/{scan_id}/thumbnail")
def get_scan_thumbnail(scan_id: str, request: Request) -> FileResponse:
    row = scan_row(request, scan_id)
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
    """A downscaled copy of the scan (1600px). Two consumers: the correction
    editor's photo pane (legible marks without the 4000x3000 original's
    sluggishness) and, since #15, the viewer's first paint before the full-res
    original loads. `detect_line_bands` also runs on this exact image, so its
    dimensions are load-bearing for auto-scroll. Pure cache; the original is
    untouched."""
    row = scan_row(request, scan_id)
    data_dir = request.app.state.settings.data_dir
    if not (data_dir / row["image_path"]).is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    preview = ensure_preview(data_dir, row["image_path"], scan_id)
    if preview is None:
        raise HTTPException(
            status_code=415, detail="Cannot decode this image format for preview"
        )
    return FileResponse(preview, media_type="image/webp")


@router.get("/scans/{scan_id}/line-bands", response_model=LineBands)
def get_scan_line_bands(scan_id: str, request: Request) -> LineBands:
    """Normalized vertical bands of the written rows, for the editor's per-line
    photo auto-scroll (finding #11).

    Detection runs on the SAME cached preview the editor renders, so no scaling
    is needed to map a band onto the on-screen image. One conversion IS implied,
    though (F25/F33): the detector deskews the page before projecting, and the
    bands are reported in that deskewed frame — i.e. a band is the row's vertical
    extent at the image's centre column. The editor pans the un-rotated preview,
    so on a tilted capture the row's ends sit above/below the band by
    (width/2)·sin(skew): ~4 % of image height at the 9–10° of a hand-held phone
    photo, against a ~8 % row pitch. Acceptable for panning (the row is still in
    view); anyone drawing bands ON the photo must rotate it by the detector's
    skew first (``line_detection.analyze_lines`` exposes ``skew_degrees``; this
    route deliberately does not, yet). Bands are a pure function of the pixels —
    nothing is stored, and an undecodable image just yields no bands (the editor
    then doesn't auto-scroll, rather than erroring)."""
    row = scan_row(request, scan_id)
    data_dir = request.app.state.settings.data_dir
    if not (data_dir / row["image_path"]).is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    preview = ensure_preview(data_dir, row["image_path"], scan_id)
    if preview is None:
        return LineBands(bands=[])
    with Image.open(preview) as im:
        bands = detect_line_bands(im)
    return LineBands(bands=[LineBand(y0=y0, y1=y1) for y0, y1 in bands])


@router.delete("/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: str, request: Request) -> Response:
    """Remove one page (e.g. a blurry retake); remaining pages are renumbered 1..n."""
    row = scan_row(request, scan_id)
    owner_id = current_user_id(request)
    enforce_limit(
        request,
        action="destructive",
        subject=owner_id,
        limit=request.app.state.settings.destructive_limit_per_hour,
        window_seconds=3600,
    )
    conn: sqlite3.Connection = request.state.db
    conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    remaining = conn.execute(
        "SELECT id FROM scans WHERE song_id = ? ORDER BY page_no", (row["song_id"],)
    ).fetchall()
    for i, r in enumerate(remaining, start=1):
        conn.execute("UPDATE scans SET page_no = ? WHERE id = ?", (i, r["id"]))
    conn.commit()
    delete_scan_files(request.app.state.settings.data_dir, row["image_path"], scan_id)
    security_event(
        request, "scan_delete", "succeeded", user_id=owner_id, resource_id=scan_id
    )
    return Response(status_code=204)
