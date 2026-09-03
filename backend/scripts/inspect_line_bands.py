"""Visualise the line detector on real sheets, through the PRODUCTION preview path.

Run from backend/:
    uv run python -m scripts.inspect_line_bands                     # all of samples/
    uv run python -m scripts.inspect_line_bands ../samples/Scan_x.jpg ../samples/Scan_y.jpg
    uv run python -m scripts.inspect_line_bands --out ../line_bands_overlays

This is the "measure against a real desk photo" step findings F17/F19 need. The
corpus of hand-written sheets in samples/ is all clean flatbed-style scans; the
whole F5/F9/F13/F14 desk-photo family has been reasoned about and closed WITHOUT a
single phone photo of a sheet on a desk. Drop one into samples/ (surround visible,
a few degrees of tilt, ordinary room-light shadow along the paper's edge), run
this, and look at the overlay.

For each image it reproduces EXACTLY what the server hands ``detect_line_bands``:
the WebP quality-80 editor preview from ``storage._ensure_derived`` -- not the raw
JPEG, which findings F17 showed changes the band count on most sheets. It prints
the band count and normalized positions, compares to the committed golden file
(``tests/line_bands_baseline.json``) when the sheet is in it, and writes an OVERLAY
PNG with every band drawn on the preview so you can eyeball whether the bands land
on the written rows -- the check no synthetic fixture can stand in for.

Overlays contain the user's private sheets, so the default output dir is
gitignored. This script never mutates samples/ (the fidelity rule); the preview is
built in memory.
"""

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app.line_detection import detect_line_bands
from app.storage import PREVIEW_MAX_DIM

_REPO = Path(__file__).resolve().parents[2]
_SAMPLES_DIR = _REPO / "samples"
_BASELINE = _REPO / "backend" / "tests" / "line_bands_baseline.json"
_EXTS = ("*.jpg", "*.jpeg", "*.png", "*.webp")


def _preview(path: Path) -> Image.Image:
    """The exact pixels the server feeds the detector.

    Mirrors ``storage._ensure_derived`` (exif_transpose -> thumbnail(PREVIEW_MAX_DIM)
    -> convert RGB -> WEBP q80), in memory, so this tool and the running system see
    the same lossy artifact. Kept in sync with that function and with the test
    helper ``tests.test_line_detection._bands_through_preview`` by hand.
    """
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((PREVIEW_MAX_DIM, PREVIEW_MAX_DIM))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "WEBP", quality=80)
    buf.seek(0)
    with Image.open(buf) as preview:
        return preview.convert("RGB")


def _draw_overlay(preview: Image.Image, bands: list[tuple[float, float]], dest: Path) -> None:
    """Draw each band as a translucent red strip with solid edge lines, numbered."""
    img = preview.copy()
    width, height = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    for i, (y0, y1) in enumerate(bands):
        top, bottom = round(y0 * height), round(y1 * height)
        draw.rectangle([0, top, width - 1, bottom], fill=(255, 0, 0, 40))
        draw.line([(0, top), (width - 1, top)], fill=(255, 0, 0, 255), width=2)
        draw.line([(0, bottom), (width - 1, bottom)], fill=(255, 0, 0, 255), width=2)
        draw.text((4, top + 2), str(i), fill=(255, 0, 0, 255))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def _resolve_images(args_images: list[str]) -> list[Path]:
    if args_images:
        return [Path(p).resolve() for p in args_images]
    return sorted(p for ext in _EXTS for p in _SAMPLES_DIR.glob(ext))


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect line-band detection on real sheets.")
    parser.add_argument("images", nargs="*", help="image paths (default: all of samples/)")
    parser.add_argument(
        "--out",
        default=str(_REPO / "line_bands_overlays"),
        help="overlay output dir (default: ../line_bands_overlays, gitignored)",
    )
    parser.add_argument("--no-overlay", action="store_true", help="print counts only")
    args = parser.parse_args()

    images = _resolve_images(args.images)
    if not images:
        raise SystemExit(f"no images found (looked in {_SAMPLES_DIR} for {_EXTS})")
    baseline: dict[str, int] = (
        json.loads(_BASELINE.read_text(encoding="utf-8")) if _BASELINE.is_file() else {}
    )
    out_dir = Path(args.out).resolve()

    print(f"{'sheet':45s} {'bands':>5s} {'baseline':>8s}  positions (y0-y1)")
    for path in images:
        preview = _preview(path)
        bands = detect_line_bands(preview.copy())
        want = baseline.get(path.name)
        flag = "" if want is None else ("  OK" if want == len(bands) else f"  != baseline {want}")
        pos = " ".join(f"{y0:.2f}-{y1:.2f}" for y0, y1 in bands)
        print(f"{path.name:45s} {len(bands):5d} {('-' if want is None else want):>8}{flag}")
        print(f"{'':45s} {'':5s} {'':8s}  {pos}")
        if not args.no_overlay:
            dest = out_dir / f"{path.stem}.bands.png"
            _draw_overlay(preview, bands, dest)
    if not args.no_overlay:
        print(f"\noverlays written to {out_dir}")
        print("open them and check each red strip sits on a written row, with none on the desk.")


if __name__ == "__main__":
    main()
