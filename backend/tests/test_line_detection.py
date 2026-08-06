"""Unit tests for the projection-profile line detector (finding #11 auto-scroll).

Synthetic bars, not real sheets: these pin the algorithm's behaviour (run
finding, gap merge, noise drop, blank page) so a refactor can't silently break
it. Threshold tuning against the real hand-written corpus is a separate,
login-gated follow-up noted in the module docstring."""

from PIL import Image, ImageDraw

from app.line_detection import _merge_gaps, _runs, detect_line_bands

WIDTH, HEIGHT = 200, 1000


def _sheet(bars: list[tuple[int, int]]) -> Image.Image:
    """A white page with black full-width bars at the given (top, bottom) rows."""
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    for top, bottom in bars:
        draw.rectangle([0, top, WIDTH - 1, bottom - 1], fill=0)
    return im


def _centres(bands: list[tuple[float, float]]) -> list[float]:
    return [(y0 + y1) / 2 for y0, y1 in bands]


def test_finds_one_band_per_bar_in_order():
    bands = detect_line_bands(_sheet([(100, 140), (400, 440), (800, 860)]))
    assert len(bands) == 3
    # top-to-bottom, each roughly centred on its bar
    assert _centres(bands) == sorted(_centres(bands))
    assert abs(_centres(bands)[0] - 0.12) < 0.02
    assert abs(_centres(bands)[1] - 0.42) < 0.02
    assert abs(_centres(bands)[2] - 0.83) < 0.02
    # bands stay within [0, 1] and don't overlap
    assert all(0.0 <= y0 < y1 <= 1.0 for y0, y1 in bands)


def test_blank_page_has_no_bands():
    assert detect_line_bands(Image.new("L", (WIDTH, HEIGHT), 255)) == []


def test_close_rows_merge_into_one_band():
    # gap of 8px < merge gap (0.015 * 1000 = 15) → one band, e.g. a note row and
    # the flat dashes just beneath it.
    bands = detect_line_bands(_sheet([(100, 110), (118, 128)]))
    assert len(bands) == 1
    y0, y1 = bands[0]
    assert y0 < 0.11 and y1 > 0.12  # spans both bars


def test_well_separated_rows_stay_distinct():
    # gap of 40px > merge gap → two bands.
    bands = detect_line_bands(_sheet([(100, 110), (150, 160)]))
    assert len(bands) == 2


def test_tiny_speck_is_dropped_as_noise():
    # a 3px mark < min height (0.006 * 1000 = 6) → not a line.
    assert detect_line_bands(_sheet([(500, 503)])) == []


def test_empty_image_is_safe():
    assert detect_line_bands(Image.new("L", (0, 0))) == []


def test_runs_and_merge_gaps_helpers():
    assert _runs([False, True, True, False, True]) == [(1, 3), (4, 5)]
    assert _runs([]) == []
    assert _merge_gaps([(0, 3), (5, 8)], max_gap=2) == [(0, 8)]
    assert _merge_gaps([(0, 3), (6, 8)], max_gap=2) == [(0, 3), (6, 8)]
