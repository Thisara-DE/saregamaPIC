"""Generate PWA icon PNGs into frontend/public/.

Design matches favicon.svg: dark rounded square, serif "S" with an
upper-octave dot above it (sargam S').

Run from repo root:  uv run --with pillow scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUBLIC = Path(__file__).resolve().parent.parent / "frontend" / "public"

BG = (26, 21, 51)  # #1a1533
FG = (234, 230, 255)  # #eae6ff
DOT = (143, 123, 240)  # #8f7bf0

FONT_CANDIDATES = [
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("No suitable font found; edit FONT_CANDIDATES")


def make_icon(size: int, maskable: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Maskable icons must fill the full square (the OS applies its own mask,
    # keeping only the central ~80% "safe zone" visible).
    radius = 0 if maskable else int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)

    scale = 0.72 if maskable else 1.0  # shrink art into the safe zone
    font = load_font(int(size * 0.56 * scale))
    cx = size / 2

    bbox = draw.textbbox((0, 0), "S", font=font)
    text_h = bbox[3] - bbox[1]
    dot_r = size * 0.055 * scale
    gap = size * 0.06 * scale
    total_h = dot_r * 2 + gap + text_h
    top = (size - total_h) / 2

    draw.ellipse(
        [cx - dot_r, top, cx + dot_r, top + dot_r * 2],
        fill=DOT,
    )
    text_top = top + dot_r * 2 + gap
    draw.text((cx - (bbox[2] - bbox[0]) / 2 - bbox[0], text_top - bbox[1]), "S", font=font, fill=FG)
    return img


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    make_icon(192, maskable=False).save(PUBLIC / "pwa-192.png")
    make_icon(512, maskable=False).save(PUBLIC / "pwa-512.png")
    make_icon(512, maskable=True).save(PUBLIC / "pwa-512-maskable.png")
    # iOS home-screen icon: opaque, no transparency, 180x180
    apple = make_icon(180, maskable=True).convert("RGB")
    apple.save(PUBLIC / "apple-touch-icon.png")
    print(f"Icons written to {PUBLIC}")


if __name__ == "__main__":
    main()
