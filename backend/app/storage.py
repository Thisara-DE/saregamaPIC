"""Image store: originals on disk under DATA_DIR/images/<song_id>/.

The uploaded photo is the source of truth for a scan and is NEVER modified
(fidelity rule). Paths stored in the DB are relative to DATA_DIR so the
whole data folder can be moved or restored from Dropbox as one unit.

Derived files (thumbnails, and later any display conversions) live under
DATA_DIR/derived/ keyed by scan id. They are pure caches: safe to delete
wholesale, regenerated on demand from the originals.
"""

import contextlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

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


# Grid thumbnails only need to be legible at ~200 CSS px; 512 covers 2x
# displays with room to spare while keeping files a few tens of KB.
THUMB_MAX_DIM = 512

# The correction editor shows the page big enough to read the marks against
# (dot-vs-dash, sharp ticks), but the 4000x3000 original makes the editor
# sluggish. 1600px long edge keeps every mark legible at a few hundred KB.
PREVIEW_MAX_DIM = 1600


def thumbnail_path(data_dir: Path, scan_id: str) -> Path:
    return data_dir / "derived" / "thumbs" / f"{scan_id}.webp"


def preview_path(data_dir: Path, scan_id: str) -> Path:
    return data_dir / "derived" / "previews" / f"{scan_id}.webp"


def _ensure_derived(image_path: Path, dest: Path, max_dim: int) -> Path | None:
    """Generate a cached, EXIF-corrected WebP downscale on first use.

    Phone photos store rotation in EXIF with the pixels unrotated, so the
    orientation must be baked in here — <img> would show the raw WebP
    sideways otherwise. The original is opened read-only.

    Returns None if the original can't be decoded (e.g. HEIC without a
    codec) — callers should fail with an explicit error, not a broken image.
    """
    if dest.is_file():
        return dest
    try:
        with Image.open(image_path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_dim, max_dim))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(dest, "WEBP", quality=80)
    except (UnidentifiedImageError, OSError):
        return None
    return dest


def ensure_thumbnail(data_dir: Path, image_rel_path: str, scan_id: str) -> Path | None:
    """Return the cached grid thumbnail for a scan, generating it on first use."""
    return _ensure_derived(
        data_dir / image_rel_path, thumbnail_path(data_dir, scan_id), THUMB_MAX_DIM
    )


def ensure_preview(data_dir: Path, image_rel_path: str, scan_id: str) -> Path | None:
    """Return the cached editor preview for a scan, generating it on first use."""
    return _ensure_derived(
        data_dir / image_rel_path, preview_path(data_dir, scan_id), PREVIEW_MAX_DIM
    )


def delete_scan_files(data_dir: Path, image_rel_path: str, scan_id: str) -> None:
    """Remove a scan's original and any derived files; prune empty song dir."""
    original = data_dir / image_rel_path
    original.unlink(missing_ok=True)
    thumbnail_path(data_dir, scan_id).unlink(missing_ok=True)
    preview_path(data_dir, scan_id).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        original.parent.rmdir()  # only succeeds if the song dir is now empty
