"""Image store: originals on disk under DATA_DIR/images/<song_id>/.

The uploaded photo is the source of truth for a scan and is NEVER modified
(fidelity rule). Paths stored in the DB are relative to DATA_DIR so the
whole data folder can be moved or restored as one unit.

Derived files (thumbnails, and later any display conversions) live under
DATA_DIR/derived/ keyed by scan id. They are pure caches: safe to delete
wholesale, regenerated on demand from the originals.
"""

import contextlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# HEIC is included because iPhones may upload it; browsers can't display it
# natively — if that bites in Phase 1, convert a *copy* for display, never
# the original.
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
CONTENT_TYPE_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

MAX_IMAGE_SIDE = 16_000
MAX_IMAGE_PIXELS = 60_000_000
_PNG_END = bytes.fromhex("0000000049454e44ae426082")


# The path the Docker image points SAREGAMAPIC_DATA_DIR at. A deployment is only
# durable if a volume is mounted here; without one this is ordinary container
# storage, and every deploy starts from an empty one.
CONTAINER_DATA_DIR = Path("/data")


def data_dir_is_ephemeral(
    data_dir: Path,
    *,
    container_dir: Path = CONTAINER_DATA_DIR,
    root: Path = Path("/"),
) -> bool:
    """True when the deployed data directory is NOT on a mounted volume.

    A mount has its own device id, so a `/data` sharing the root filesystem's
    device means nothing was attached — the database, the original scans, and
    every login session are discarded on the next deploy. Checked only for the
    container path: a local checkout keeps `data/` inside the repo, where
    sharing the root device is normal and says nothing.
    """
    if data_dir != container_dir:
        return False
    try:
        return data_dir.stat().st_dev == root.stat().st_dev
    except OSError:
        return False


class InvalidImage(ValueError):
    """The upload is not a safe, fully decodable image of its declared type."""


def extension_for(content_type: str) -> str | None:
    return CONTENT_TYPE_EXT.get(content_type)


def _container_is_exact(data: bytes, content_type: str) -> bool:
    """Reject obvious MIME spoofing and bytes appended after the image container."""
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(_PNG_END)
    if content_type == "image/webp":
        return (
            len(data) >= 12
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
            and int.from_bytes(data[4:8], "little") + 8 == len(data)
        )
    return False


def validate_scan_image(data: bytes, content_type: str) -> None:
    """Fully verify an upload without rewriting the immutable original."""
    expected_format = CONTENT_TYPE_FORMAT.get(content_type)
    if expected_format is None or not _container_is_exact(data, content_type):
        raise InvalidImage("Image bytes do not match the declared type")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != expected_format:
                    raise InvalidImage("Decoded image does not match the declared type")
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_IMAGE_SIDE
                    or height > MAX_IMAGE_SIDE
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise InvalidImage("Image dimensions exceed the safe limit")
                image.verify()
    except InvalidImage:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise InvalidImage("Image cannot be safely decoded") from exc


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
