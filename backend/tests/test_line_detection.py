"""Unit tests for the projection-profile line detector (finding #11 auto-scroll).

Synthetic images, not real sheets: these pin the algorithm's behaviour (run
finding, gap merge, noise drop, blank page) so a refactor can't silently break
it. Threshold tuning against the real hand-written corpus is a separate,
login-gated follow-up noted in the module docstring.

The desk-photo helpers below exist because the earlier white-page-only fixtures
could not express the input class every failure in the F5/F9/F13/F14 family came
from — a phone capture with the table visible around the paper. They cover the
four shapes that behave differently: a full surround, one edge, both sides, and a
tilted edge. ``_write_row`` draws SPARSE ink (roughly the ~0.11 row coverage
measured across the real ``samples/`` scans) rather than a solid bar, because a
solid bar cannot distinguish an ink fraction measured over the paper span from
one measured over the whole frame — which is the entire point of F9."""

import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.line_detection import (
    _fill_enclosed_gaps,
    _merge_gaps,
    _otsu_threshold,
    _runs,
    detect_line_bands,
)

WIDTH, HEIGHT = 200, 1000

# The user's real hand-written sheets. Gitignored (they are the Phase 2 eval set,
# not test data), so anything using them must skip when they are absent.
_SAMPLES = sorted((Path(__file__).resolve().parents[2] / "samples").glob("*.jpg"))


def _sheet(bars: list[tuple[int, int]]) -> Image.Image:
    """A white page with black full-width bars at the given (top, bottom) rows."""
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    for top, bottom in bars:
        draw.rectangle([0, top, WIDTH - 1, bottom - 1], fill=0)
    return im


def _centres(bands: list[tuple[float, float]]) -> list[float]:
    return [(y0 + y1) / 2 for y0, y1 in bands]


def _write_row(
    draw: ImageDraw.ImageDraw, top: int, bottom: int, x0: int, x1: int, *, dashes: int = 8
) -> None:
    """A sparsely written row: `dashes` short strokes spread across `x0`..`x1`.

    Covers a fraction of the row's paper width, the way real notation does — not
    the solid bar `_sheet` draws, which would score as ink under any denominator.
    """
    step = (x1 - x0) / dashes
    for i in range(dashes):
        left = round(x0 + i * step)
        draw.rectangle([left, top, left + max(2, round(step / 4)), bottom - 1], fill=0)


def _desk_sheet(
    bars: list[tuple[int, int]], *, surround: int = 90, paper: int = 230
) -> Image.Image:
    """A phone photo, not a flatbed scan: a dark desk `surround` framing a lighter
    `paper` rectangle on all four sides, with black note bars on the paper.

    This is the input class the pure-white ``_sheet`` helper structurally cannot
    produce, and it is exactly the F5 failure: the dark surround pulled the ink
    level down until every image row — blank gaps included — read as ink."""
    im = Image.new("L", (WIDTH, HEIGHT), surround)
    draw = ImageDraw.Draw(im)
    margin_x, margin_y = WIDTH // 6, HEIGHT // 12
    draw.rectangle([margin_x, margin_y, WIDTH - margin_x, HEIGHT - margin_y], fill=paper)
    for top, bottom in bars:
        draw.rectangle([margin_x, top, WIDTH - margin_x, bottom - 1], fill=0)
    return im


def _bottom_desk_sheet(
    rows: list[tuple[int, int]],
    *,
    desk_top: int = 750,
    surround: int = 90,
    paper: int = 230,
) -> Image.Image:
    """F9's framing: paper fills the top of the frame, desk shows along the bottom
    only. The desk region is far too short to trip the max-height guard, so under a
    whole-frame ink threshold it survived as an ordinary-looking extra band."""
    im = Image.new("L", (WIDTH, HEIGHT), paper)
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, desk_top, WIDTH - 1, HEIGHT - 1], fill=surround)
    for top, bottom in rows:
        _write_row(draw, top, bottom, 10, WIDTH - 10)
    return im


def _side_desk_sheet(
    rows: list[tuple[int, int]], *, coverage: float = 0.45, surround: int = 90, paper: int = 230
) -> Image.Image:
    """F13's framing: desk down BOTH sides covering `coverage` of every row, paper
    filling the middle. Every row has the same desk contribution, so a whole-frame
    ink fraction ranks blank rows and written rows within a hair of each other."""
    im = Image.new("L", (WIDTH, HEIGHT), surround)
    draw = ImageDraw.Draw(im)
    margin = round(WIDTH * coverage / 2)
    draw.rectangle([margin, 0, WIDTH - margin - 1, HEIGHT - 1], fill=paper)
    for top, bottom in rows:
        _write_row(draw, top, bottom, margin + 4, WIDTH - margin - 5)
    return im


def _tilted_desk_sheet(
    rows: list[tuple[int, int]],
    *,
    degrees: float = 3.0,
    width: int = 1200,
    height: int = 1600,
    desk_top: int = 1200,
    surround: int = 90,
    paper: int = 230,
) -> Image.Image:
    """F14's framing: the same bottom desk, but the paper/desk boundary crosses the
    frame at an angle, as a handheld capture always does. The boundary sweeps a
    wedge of rows whose desk coverage runs continuously from 0 to 1, so no
    per-row ink threshold anchored to the full width can bracket it."""
    im = Image.new("L", (width, height), paper)
    draw = ImageDraw.Draw(im)
    drop = round(width * math.tan(math.radians(degrees)))
    draw.polygon(
        [(0, desk_top), (width - 1, desk_top + drop), (width - 1, height - 1), (0, height - 1)],
        fill=surround,
    )
    for top, bottom in rows:
        _write_row(draw, top, bottom, 40, width - 40, dashes=14)
    return im


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


def test_desk_surround_finds_the_real_rows():
    # F5 originally: a phone photo with the desk visible around the paper drove the
    # ink level low enough that every image row read as ink, so the detector
    # returned ONE band spanning the whole sheet and the editor re-centred the photo
    # on every line focus. The max-height guard reduced that to `[]` — safe, but the
    # feature was simply off for desk photos, which F5 recorded as its deferred half
    # ("making desk photos produce USEFUL bands needs paper-region detection").
    #
    # With the ink fraction measured over each row's paper span, that half is done:
    # the surround is outside the span at every row, so the two written rows are
    # found exactly where they are. THIS ASSERTION IS THE OPPOSITE OF THE ONE IT
    # REPLACES — the old `== []` encoded the degradation, not the wanted behaviour.
    bands = detect_line_bands(_desk_sheet([(300, 340), (600, 640)]))
    assert len(bands) == 2, bands
    assert abs(_centres(bands)[0] - 0.32) < 0.02
    assert abs(_centres(bands)[1] - 0.62) < 0.02


def test_bottom_edge_desk_adds_no_band():
    # F9 proper: paper across the top three-quarters, desk along the bottom quarter
    # only. That surround is shorter than half the page, so it slipped past the
    # max-height guard as an ordinary-looking extra band below the last written row
    # — and one surplus band shifts EVERY line's mapping in `bandForLine`.
    rows = [(100, 140), (300, 340), (500, 540)]
    bands = detect_line_bands(_bottom_desk_sheet(rows))
    assert len(bands) == len(rows), bands
    # nothing may land in the desk region (rows 750+ of 1000)
    assert all(y1 <= 0.75 for _, y1 in bands), bands
    assert _centres(bands) == sorted(_centres(bands))


def test_side_desk_does_not_invert_the_classifier():
    # F13: desk down both sides at ~45% of every row. Measured over the full width,
    # blank paper rows scored 0.45 (→ "ink") while written rows scored ~0.51 and
    # were REJECTED by the ceiling then in place, so the detector returned bands on
    # the whitespace BETWEEN the written rows — a confident wrong answer where the
    # previous revision had at least returned nothing. Measured over the paper span,
    # the desk contributes to neither the numerator nor the denominator, so the
    # ranking cannot invert.
    rows = [(200, 240), (500, 540), (800, 840)]
    bands = detect_line_bands(_side_desk_sheet(rows))
    assert len(bands) == len(rows), bands
    for (top, bottom), (y0, y1) in zip(rows, bands, strict=True):
        assert y0 <= (top + bottom) / 2 / HEIGHT <= y1, (rows, bands)


def test_tilted_desk_edge_adds_no_band():
    # F14: the same bottom desk, tilted 3° as a handheld capture always is. The
    # boundary sweeps ~63 rows whose desk coverage runs continuously from 0 to 1, so
    # a wedge of them lands inside any fixed full-width ink window and forms a run
    # tall enough to clear the min-height filter. Per-row paper spans make the angle
    # irrelevant: the desk is outside the span at every row of the wedge.
    rows = [(200, 260), (500, 560), (800, 860)]
    bands = detect_line_bands(_tilted_desk_sheet(rows))
    assert len(bands) == len(rows), bands
    assert all(y1 <= 1200 / 1600 for _, y1 in bands), bands


def test_blank_sheet_on_a_desk_has_no_bands():
    # The desk is high-contrast against the paper, so the whole-frame contrast
    # guard cannot short-circuit this one: an unwritten sheet must still come back
    # empty on the strength of the paper-span measurement alone.
    assert detect_line_bands(_bottom_desk_sheet([])) == []
    assert detect_line_bands(_side_desk_sheet([])) == []


def test_over_tall_run_is_dropped():
    # The direct unit for the guard: a single dark block covering most of the page
    # (0.05..0.95 ≈ 0.9 of height > _MAX_HEIGHT_FRACTION) is not a line, so it is
    # dropped — the same shape as the collapsed-desk run, minus the surround.
    assert detect_line_bands(_sheet([(50, 950)])) == []


@pytest.mark.skipif(not _SAMPLES, reason="samples/ is gitignored; present on dev machines only")
def test_real_sheets_hold_the_band_invariants():
    # The real corpus is the only evidence _ROW_INK_FRACTION is calibrated right —
    # and it is gitignored, so this cannot run in CI and cannot be the whole story.
    # It asserts the invariants that survive someone adding a sheet, rather than
    # per-file band counts, which would break on the first new scan. The count
    # comparison against the reviewed baseline (0 merged, 0 lost across all 10) is
    # recorded beside the constant in line_detection.py; re-run it by hand when
    # touching a threshold.
    for path in _SAMPLES:
        with Image.open(path) as im:
            im.thumbnail((1600, 1600))
            bands = detect_line_bands(im.copy())
        assert bands, f"{path.name}: a written sheet must yield at least one band"
        assert all(0.0 <= y0 < y1 <= 1.0 for y0, y1 in bands), (path.name, bands)
        assert all(y1 - y0 <= 0.5 for y0, y1 in bands), (path.name, bands)
        assert bands == sorted(bands), (path.name, bands)
        assert all(a[1] <= b[0] for a, b in zip(bands, bands[1:], strict=False)), (
            path.name,
            bands,
        )


def test_runs_and_merge_gaps_helpers():
    assert _runs([False, True, True, False, True]) == [(1, 3), (4, 5)]
    assert _runs([]) == []
    assert _merge_gaps([(0, 3), (5, 8)], max_gap=2) == [(0, 8)]
    assert _merge_gaps([(0, 3), (6, 8)], max_gap=2) == [(0, 3), (6, 8)]


def test_otsu_splits_between_the_two_tones():
    # Two-tone image: every threshold strictly between the tones scores identically,
    # so the maximum is a plateau. The midpoint keeps the split off both tones.
    hist = [0] * 256
    hist[0], hist[255] = 500, 500
    assert _otsu_threshold(hist) == 128
    # Three tones — ink, desk, paper — must split {ink, desk} from paper, which is
    # the property the paper span depends on, not ink from {desk, paper}.
    hist = [0] * 256
    hist[0], hist[90], hist[230] = 50, 440, 510
    assert 90 < _otsu_threshold(hist) <= 230
    assert _otsu_threshold([0] * 256) == 128  # empty is safe, never divides by zero


def test_fill_enclosed_gaps_separates_heavy_writing_from_surround():
    span = (2, 60)
    # enclosed by paper above and below → a written row too dark to leave paper
    # showing; it inherits the span and stays a candidate.
    assert _fill_enclosed_gaps([span, None, None, span], max_run=10) == [span] * 4
    # running to the bottom edge → surround, left as None so it is dropped
    assert _fill_enclosed_gaps([span, None, None], max_run=10) == [span, None, None]
    # running to the top edge → likewise
    assert _fill_enclosed_gaps([None, None, span], max_run=10) == [None, None, span]
    # enclosed but taller than a plausible written row → not inherited
    assert _fill_enclosed_gaps([span, None, None, None, span], max_run=2) == [
        span,
        None,
        None,
        None,
        span,
    ]
    # the wider of the two enclosing spans wins, so a partially-occluded neighbour
    # can't narrow the denominator
    narrow, wide = (10, 20), (2, 60)
    assert _fill_enclosed_gaps([narrow, None, wide], max_run=10) == [narrow, wide, wide]
