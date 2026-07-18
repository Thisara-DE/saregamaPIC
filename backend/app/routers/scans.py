"""Scan image retrieval."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/scans/{scan_id}/image")
def get_scan_image(scan_id: str, request: Request) -> FileResponse:
    row = request.state.db.execute(
        "SELECT image_path, content_type FROM scans WHERE id = ?", (scan_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    path = request.app.state.settings.data_dir / row["image_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file missing from data dir")
    return FileResponse(path, media_type=row["content_type"])
