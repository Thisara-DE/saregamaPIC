"""Image store: originals on disk under DATA_DIR/images/<song_id>/.

The uploaded photo is the source of truth for a scan and is NEVER modified
(fidelity rule). Paths stored in the DB are relative to DATA_DIR so the
whole data folder can be moved or restored from Dropbox as one unit.
"""

from pathlib import Path

# HEIC is included because iPhones may upload it; browsers can't display it
# natively — if that bites in Phase 1, convert a *copy* for display, never
# the original.
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


def extension_for(content_type: str) -> str | None:
    return CONTENT_TYPE_EXT.get(content_type)


def save_scan_image(
    images_dir: Path, song_id: str, scan_id: str, content_type: str, data: bytes
) -> str:
    """Write the original image; returns the DB-relative path (POSIX style)."""
    ext = CONTENT_TYPE_EXT[content_type]
    song_dir = images_dir / song_id
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / f"{scan_id}{ext}").write_bytes(data)
    return f"images/{song_id}/{scan_id}{ext}"
