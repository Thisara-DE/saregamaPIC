"""Unit tests for the projection-profile line detector (finding #11 auto-scroll).

Synthetic rows, not real sheets: these pin the algorithm's behaviour (run finding,
gap merge, noise drop, blank page, and the two desk-capture failure modes F5/F9)
so a refactor can't silently break it. Rows are drawn SPARSE, like real writing,
because the detector now distinguishes a written row from a solid dark region by
ink density (finding #9). Threshold tuning against the real hand-written corpus is
a separate, login-gated follow-up noted in the module docstring."""

from PIL import Image, ImageDraw

from app.line_detection import _merge_gaps, _runs, detect_line_bands

WIDTH, HEIGHT = 200, 1000


def _sheet(bars: list[tuple[int, int]]) -> Image.Image:
    """A white page with a written row at each (top, bottom).

    Rows are drawn as SPARSE dashes (~30% of the width), not solid bars: a real
    hand-written row is a few percent to ~0.1 of its width in ink (measured across
    the samples/ corpus), and the detector now relies on that — a near-solid row
    is a desk edge or a heavy rule, not writing (finding #9). A solid bar would be
    (correctly) rejected as such, so the synthetic rows have to look like real ones."""
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    for top, bottom in bars:
        for x in range(0, WIDTH, 40):  # a 12px dash every 40px ≈ 30% ink coverage
            draw.rectangle([x, top, min(x + 12, WIDTH) - 1, bottom - 1], fill=0)
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


def test_side_desk_surround_collapses_and_the_guard_drops_it():
    # F5: a portrait phone capture with the desk showing down BOTH sides makes
    # every image row read as ink (the side strips), so the whole sheet is one
    # over-tall run. The _MAX_HEIGHT_FRACTION guard drops it, leaving the documented
    # no-op (no bands → the editor simply doesn't auto-scroll) rather than one
    # full-page band the editor would re-centre on every line focus.
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, 14, HEIGHT - 1], fill=70)  # left desk strip, full height
    draw.rectangle([WIDTH - 15, 0, WIDTH - 1, HEIGHT - 1], fill=70)  # right desk strip
    bands = detect_line_bands(im)
    assert all(y1 - y0 <= 0.5 for y0, y1 in bands), bands
    assert bands == []


def test_bottom_edge_desk_does_not_add_a_spurious_band():
    # F9: the realistic one-handed capture — paper across the top, the desk showing
    # along the bottom. The desk rows are near-solid ink (a written row is sparse),
    # so the _ROW_INK_MAX_FRACTION bound rejects them at the source: the detector
    # returns exactly the written rows, with NO extra band down at the desk that
    # would shift bandForLine for every line.
    im = _sheet([(100, 140), (300, 340), (500, 540)])  # three rows in the top 55%
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, int(HEIGHT * 0.75), WIDTH - 1, HEIGHT - 1], fill=90)  # desk
    bands = detect_line_bands(im)
    assert len(bands) == 3, bands
    assert max(y1 for _, y1 in bands) < 0.6  # every band is a written row, not the desk
    assert _centres(bands) == sorted(_centres(bands))


def test_over_tall_run_is_dropped():
    # The direct unit for the guard: a single ink region covering most of the page
    # (0.05..0.95 ≈ 0.9 of height > _MAX_HEIGHT_FRACTION) is not a line, so it is
    # dropped — the same shape as a collapsed capture, in isolation.
    assert detect_line_bands(_sheet([(50, 950)])) == []


def test_runs_and_merge_gaps_helpers():
    assert _runs([False, True, True, False, True]) == [(1, 3), (4, 5)]
    assert _runs([]) == []
    assert _merge_gaps([(0, 3), (5, 8)], max_gap=2) == [(0, 8)]
    assert _merge_gaps([(0, 3), (6, 8)], max_gap=2) == [(0, 3), (6, 8)]
