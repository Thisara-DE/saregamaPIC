"""Unit tests for the projection-profile line detector (finding #11 auto-scroll).

Synthetic images, not real sheets: these pin the algorithm's behaviour (stroke
mask, deskew, run finding, valley splitting, noise drop, blank page) so a refactor
can't silently break it. The real hand-written corpus is checked separately by the
golden-file test at the bottom, which needs ``samples/`` and so only runs on a dev
machine.

Every fixture writes SPARSE ink — short vertical dashes spread across the row,
roughly the ~0.11 row coverage measured across the real ``samples/`` scans —
rather than a solid bar. That is not cosmetic: the detector decides ink by the
horizontal top-hat (a stroke is dark against the paper a few pixels to either
side), so a solid full-width bar is not ink at all, and an ink fraction measured
over the paper span is only distinguishable from one measured over the whole
frame when the row is partly paper (F9). The desk-photo helpers cover the input
class every failure in the F5/F9/F13/F14 family came from — a phone capture with
the table visible — in the four shapes that behave differently (full surround,
one edge, both sides, tilted edge), and the F25 helpers add the two the real
capture path turned out to need: a hand shadow ON the paper, and a tilted sheet."""

import io
import json
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageOps

from app.line_detection import (
    _fill_enclosed_gaps,
    _guard_paper_edges,
    _horizontal_max,
    _horizontal_min,
    _merge_gaps,
    _otsu_threshold,
    _runs,
    _skew_angle,
    _smooth,
    _split_at_valleys,
    _stroke_mask,
    _trim_to_core,
    analyze_lines,
    detect_line_bands,
)
from app.storage import PREVIEW_MAX_DIM

WIDTH, HEIGHT = 200, 1000

# The user's real hand-written sheets. Gitignored (they are the Phase 2 eval set,
# not test data), so anything using them must skip when they are absent. Glob every
# extension the corpus might hold, not just *.jpg — a .jpeg/.png/.webp sample used to
# be silently excluded while the skip message still claimed the corpus was absent
# (F16).
_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_SAMPLES = sorted(
    p for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp") for p in _SAMPLES_DIR.glob(ext)
)
# Committed golden file: per-sheet band count through the production preview path.
_BASELINE_PATH = Path(__file__).resolve().parent / "line_bands_baseline.json"


def _bands_through_preview(path: Path) -> list[tuple[float, float]]:
    """Detect on the SAME artifact production feeds the detector: the WebP-q80 editor
    preview, not the source JPEG. Mirrors ``storage._ensure_derived`` exactly
    (exif_transpose -> thumbnail(PREVIEW_MAX_DIM) -> convert RGB -> WEBP q80), so the
    corpus check sees the lossy re-encode the running system does (F17). This is not
    a rounding-error difference: WebP q80 shifts the grey histogram every quantity
    the detector reads is taken from, and on this corpus it changes the band count on
    7 of 10 sheets versus the raw thumbnail the old test used.
    """
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((PREVIEW_MAX_DIM, PREVIEW_MAX_DIM))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "WEBP", quality=80)
    buf.seek(0)
    with Image.open(buf) as preview:
        return detect_line_bands(preview.copy())


def _centres(bands: list[tuple[float, float]]) -> list[float]:
    return [(y0 + y1) / 2 for y0, y1 in bands]


def _write_row(
    draw: ImageDraw.ImageDraw, top: int, bottom: int, x0: int, x1: int, *, dashes: int = 8
) -> None:
    """A sparsely written row: `dashes` short vertical strokes spread across `x0`..`x1`.

    Covers a fraction of the row's paper width, the way real notation does — not
    a solid bar, which would score as ink under any denominator (and, under the
    horizontal top-hat, not at all). Each dash is at most 6px wide: a pencil stroke
    on the 1600px preview is 3–6px, and the horizontal closing's window is sized
    for that, so a fixture must not draw fatter "strokes" than the sheets do.
    """
    step = (x1 - x0) / dashes
    for i in range(dashes):
        left = round(x0 + i * step)
        draw.rectangle([left, top, left + min(6, max(2, round(step / 4))), bottom - 1], fill=0)


def _page(rows: list[tuple[int, int]], *, paper: int = 255) -> Image.Image:
    """A flatbed-style page: paper fills the frame, written rows at (top, bottom)."""
    im = Image.new("L", (WIDTH, HEIGHT), paper)
    draw = ImageDraw.Draw(im)
    for top, bottom in rows:
        _write_row(draw, top, bottom, 10, WIDTH - 10)
    return im


def _desk_sheet(
    rows: list[tuple[int, int]],
    *,
    surround: int = 90,
    paper: int = 230,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> Image.Image:
    """A phone photo, not a flatbed scan: a dark desk `surround` framing a lighter
    `paper` rectangle on all four sides, with written rows on the paper.

    This is the input class the pure-white ``_page`` helper structurally cannot
    produce, and it is exactly the F5 failure: the dark surround pulled the ink
    level down until every image row — blank gaps included — read as ink."""
    im = Image.new("L", (width, height), surround)
    draw = ImageDraw.Draw(im)
    margin_x, margin_y = width // 6, height // 12
    draw.rectangle([margin_x, margin_y, width - margin_x, height - margin_y], fill=paper)
    dashes = 8 if width <= WIDTH else 14
    for top, bottom in rows:
        _write_row(draw, top, bottom, margin_x + 4, width - margin_x - 4, dashes=dashes)
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
    rows: list[tuple[int, int]],
    *,
    coverage: float = 0.45,
    surround: int = 90,
    paper: int = 230,
    penumbra: int = 0,
) -> Image.Image:
    """F13's framing: desk down BOTH sides covering `coverage` of every row, paper
    filling the middle. Every row has the same desk contribution, so a whole-frame
    ink fraction ranks blank rows and written rows within a hair of each other.

    `penumbra` softens the paper/desk edge: instead of a one-pixel step, a linear
    paper->surround ramp `penumbra` px wide sits just outside each inner paper edge,
    the way a real out-of-focus or shadowed capture blurs the boundary. A step edge
    is confined to the single bucket the detector's inset removes; a soft one spans
    more, which is the case F19 asked whether the one-bucket inset survives."""
    im = Image.new("L", (WIDTH, HEIGHT), surround)
    draw = ImageDraw.Draw(im)
    margin = round(WIDTH * coverage / 2)
    draw.rectangle([margin, 0, WIDTH - margin - 1, HEIGHT - 1], fill=paper)
    for k in range(penumbra):
        val = round(surround + (paper - surround) * (k + 1) / (penumbra + 1))
        draw.line([(margin - penumbra + k, 0), (margin - penumbra + k, HEIGHT - 1)], fill=val)
        right = WIDTH - margin - 1 + penumbra - k
        draw.line([(right, 0), (right, HEIGHT - 1)], fill=val)
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


def _shadowed_sheet(
    rows: list[tuple[int, int]],
    *,
    shadow: tuple[float, float] = (0.35, 0.62),
    shadow_level: float = 0.4,
    penumbra: int = 30,
) -> Image.Image:
    """F25's capture: a preview-sized (1200x1600) desk sheet with the
    photographer's hand/phone shadow cast ON the paper — a vertical band across
    ``shadow`` of the width with soft ``penumbra``-px edges, everything under it
    (paper and strokes alike) darkened to ``shadow_level``. The shadow lies between
    lit paper on both sides, so it is inside every row's paper span; under a
    page-wide ink level its paper IS ink on every row, and the whole page becomes
    one over-tall run — which is the real photographs' 0-band failure."""
    im = _desk_sheet(rows, width=1200, height=1600)
    width, height = im.size
    px = im.load()
    left, right = round(width * shadow[0]), round(width * shadow[1])
    for x in range(left - penumbra, right + penumbra):
        if x < left:
            factor = 1 - (1 - shadow_level) * (x - (left - penumbra)) / penumbra
        elif x < right:
            factor = shadow_level
        else:
            factor = shadow_level + (1 - shadow_level) * (x - right) / penumbra
        for y in range(height):
            px[x, y] = round(px[x, y] * factor)
    return im


def _tilted_sheet(rows: list[tuple[int, int]], *, degrees: float) -> Image.Image:
    """A preview-sized written desk sheet photographed ``degrees`` off square: the
    whole ``_desk_sheet`` (paper edges and rows together) rotated about the image
    centre. Bands come back in the deskewed frame, so their centres should land
    back on ``rows`` — that round trip is the deskew's contract."""
    surround = 90
    return _desk_sheet(rows, surround=surround, width=1200, height=1600).rotate(
        degrees, resample=Image.Resampling.BICUBIC, fillcolor=surround
    )


def test_finds_one_band_per_row_in_order():
    bands = detect_line_bands(_page([(100, 140), (400, 440), (800, 860)]))
    assert len(bands) == 3, bands
    # top-to-bottom, each roughly centred on its row
    assert _centres(bands) == sorted(_centres(bands))
    assert abs(_centres(bands)[0] - 0.12) < 0.02
    assert abs(_centres(bands)[1] - 0.42) < 0.02
    assert abs(_centres(bands)[2] - 0.83) < 0.02
    # bands stay within [0, 1] and don't overlap
    assert all(0.0 <= y0 < y1 <= 1.0 for y0, y1 in bands)


def test_blank_page_has_no_bands():
    assert detect_line_bands(Image.new("L", (WIDTH, HEIGHT), 255)) == []


def test_octave_dots_belong_to_their_row():
    # A note row with the octave dots just above it (3px dots, 3px clear of the
    # letters). The dots are ink — small enough for the horizontal closing — but
    # they must not become their own band: the smoothing and merge gap stitch them
    # to the row they annotate.
    im = _page([(100, 112)])
    draw = ImageDraw.Draw(im)
    for i in range(8):
        x = 12 + round(i * 22.5)
        draw.rectangle([x, 94, x + 2, 96], fill=0)
    bands = detect_line_bands(im)
    assert len(bands) == 1, bands
    y0, y1 = bands[0]
    assert y0 <= 0.106 <= y1


def test_well_separated_rows_stay_distinct():
    bands = detect_line_bands(_page([(100, 110), (150, 160)]))
    assert len(bands) == 2


def test_tiny_speck_is_dropped_as_noise():
    # a 3px mark holds fewer rows of ink than the min height (0.006 * 1000 = 6),
    # and the profile smoothing must not inflate it past that (it spreads a 3-row
    # speck over 7 rows) — hence the filter counts raw ink rows, not extent.
    assert detect_line_bands(_page([(500, 503)])) == []


def test_empty_image_is_safe():
    assert detect_line_bands(Image.new("L", (0, 0))) == []


def test_desk_surround_finds_the_real_rows():
    # F5 originally: a phone photo with the desk visible around the paper drove the
    # ink level low enough that every image row read as ink, so the detector
    # returned ONE band spanning the whole sheet and the editor re-centred the photo
    # on every line focus. With the ink fraction measured over each row's paper
    # span, the surround is outside the span at every row, so the two written rows
    # are found exactly where they are.
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


def test_side_desk_soft_edge_still_finds_the_rows():
    # F19 asked whether the one-bucket edge inset survives a SOFT paper/desk edge.
    # Every other desk fixture draws a hard step edge, which the single-bucket inset
    # removes exactly; a penumbra spans more. With a 30px ramp on this 200px fixture
    # the rows are found cleanly — and under the top-hat a smooth ramp is its own
    # local background, so it is not ink in the first place.
    rows = [(200, 240), (500, 540), (800, 840)]
    bands = detect_line_bands(_side_desk_sheet(rows, penumbra=30))
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
    # The direct unit for the max-height guard: strokes with no row structure at all
    # — vertical hatching from 0.05 to 0.95 of the page — is one flat run with no
    # valleys to split at, taller than _MAX_HEIGHT_FRACTION, so it is dropped.
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    _write_row(draw, 50, 950, 10, WIDTH - 10)
    assert detect_line_bands(im) == []


def test_shadow_on_the_paper_neither_hides_nor_merges_rows():
    # F25: the real capture path — sheet on a music stand, phone in hand, room light
    # — puts the photographer's shadow across part of the paper. Under the old
    # page-wide ink level the shadowed paper WAS ink: on the four real photographs
    # that gave 0 bands on two sheets and one section-sized band on the other two.
    # Ink is now decided against each pixel's own local paper, so a stroke in the
    # shadow is as much ink as one in the light and the shadow itself is nothing.
    # Verified to FAIL against the old detector first: it returned 0 bands here.
    rows = [(300, 360), (500, 560), (700, 760), (900, 960), (1100, 1160)]
    bands = detect_line_bands(_shadowed_sheet(rows))
    assert len(bands) == len(rows), bands
    for (top, bottom), (y0, y1) in zip(rows, bands, strict=True):
        assert y0 <= (top + bottom) / 2 / 1600 <= y1, (rows, bands)
    # ...and the shadow alone, on an unwritten sheet, is not a band either.
    assert detect_line_bands(_shadowed_sheet([])) == []


def test_rows_bridged_by_marks_are_still_split():
    # F25's second mechanism: on a dense sheet the gap between rows never falls to
    # zero — octave dots, the ends of arcs, a stray stroke — so a single threshold
    # merges a whole section. Here the gaps carry a sparse floor of small marks (≈2%
    # ink, above _ROW_INK_FRACTION), which under threshold-only runs makes the four
    # rows one run. The valley split cuts it back into four. Verified to FAIL
    # against the old detector first: it returned one 0.10–0.46 band.
    rows = [(100, 140), (200, 240), (300, 340), (400, 440)]
    im = _page(rows)
    draw = ImageDraw.Draw(im)
    for y in range(140, 400, 6):
        for x in (30, 90, 150):
            draw.rectangle([x, y, x + 2, y + 2], fill=0)
    bands = detect_line_bands(im)
    assert len(bands) == len(rows), bands
    for (top, bottom), (y0, y1) in zip(rows, bands, strict=True):
        assert y0 <= (top + bottom) / 2 / HEIGHT <= y1, (rows, bands)


def test_horizontal_marks_alone_are_not_ink():
    # The property the valleys depend on: arcs, hold dashes and flat marks are long
    # ALONG the row, so the horizontal closing treats them as background. A page
    # holding only such marks has no bands. (Its cost: a row of nothing but hold
    # dashes — no letters — is invisible too; the corpus has one such row.)
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(im)
    for y in (100, 300, 500):
        for x in range(10, WIDTH - 40, 50):
            draw.rectangle([x, y, x + 40, y + 1], fill=0)
    assert detect_line_bands(im) == []


def test_tilted_rows_are_deskewed_and_reported_in_the_row_frame():
    # F25's third mechanism: a hand-held capture tilts, and at 8–10° a row sweeps
    # more image height than the row pitch, so adjacent rows overlap in y and no
    # projection can separate them. The detector finds the skew and projects in
    # the deskewed frame; because the tilt here is a rotation about the image
    # centre, the bands must land back on the rows as they were drawn. Preview-
    # sized on purpose: at 8° over this sheet's 800px of paper a row sweeps ~112px,
    # more than the 100px pitch. Verified to FAIL against the old detector first:
    # it returned ONE band for the five rows.
    rows = [(400, 440), (500, 540), (600, 640), (700, 740), (800, 840)]
    result = analyze_lines(_tilted_sheet(rows, degrees=8.0))
    assert len(result.bands) == len(rows), result
    assert abs(result.skew_degrees + 8.0) <= 0.5, result.skew_degrees
    for (top, bottom), (y0, y1) in zip(rows, result.bands, strict=True):
        assert y0 <= (top + bottom) / 2 / 1600 <= y1, (rows, result.bands)


def test_square_sheet_is_not_rotated():
    result = analyze_lines(_page([(100, 140), (400, 440), (800, 860)]))
    assert result.skew_degrees == 0.0
    assert len(result.bands) == 3


@pytest.mark.skipif(not _SAMPLES, reason="samples/ is gitignored; present on dev machines only")
def test_real_sheets_match_the_committed_baseline():
    # The real corpus is the only evidence the thresholds are calibrated right, and
    # it is gitignored, so this cannot run in CI. What it CAN do on a dev machine is
    # fail loudly when a change merges or loses a band — which a shape-invariant
    # test could NOT (F16). It pins the per-sheet band COUNT to a committed golden
    # file, measured through the production WebP preview path rather than a raw
    # JPEG thumbnail the running system never sees (F17). Since F25 the golden file
    # covers the phone photographs as well as the flatbed scans.
    baseline: dict[str, int] = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    present = {p.name for p in _SAMPLES}
    # A partially-synced Dropbox folder must fail loudly, not silently check fewer
    # sheets and read as a pass.
    missing = sorted(set(baseline) - present)
    assert not missing, f"baseline sheets absent from samples/ (partial sync?): {missing}"
    for path in _SAMPLES:
        bands = _bands_through_preview(path)
        # A sheet the golden file knows is a written sheet, so it must yield bands. A
        # sheet dropped into samples/ but not yet baselined only gets the shape
        # invariants below — pin its count via --update-baseline when ready.
        if path.name in baseline:
            assert bands, f"{path.name}: a written sheet must yield at least one band"
        assert all(0.0 <= y0 < y1 <= 1.0 for y0, y1 in bands), (path.name, bands)
        assert bands == sorted(bands), (path.name, bands)
        assert all(a[1] <= b[0] for a, b in zip(bands, bands[1:], strict=False)), (
            path.name,
            bands,
        )
        if path.name in baseline:
            assert len(bands) == baseline[path.name], (
                f"{path.name}: {len(bands)} bands now, golden file has "
                f"{baseline[path.name]} — a change merged or lost a row. "
                "If intended, regenerate with `python -m tests.test_line_detection "
                "--update-baseline`, eyeball the inspect_line_bands overlays, and "
                "only then commit."
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


def test_horizontal_closing_fills_short_gaps_only():
    # A white row with a 3px dark gap and a 20px dark gap: the closing (max then
    # min along the row, window 8) fills the short one and leaves the long one, so
    # the top-hat sees the stroke and not the wide feature.
    im = Image.new("L", (64, 1), 255)
    px = im.load()
    for x in range(10, 13):
        px[x, 0] = 0
    for x in range(30, 50):
        px[x, 0] = 0
    closed = _horizontal_min(_horizontal_max(im, 8), 8)
    out = closed.load()
    assert all(out[x, 0] == 255 for x in range(10, 13))  # stroke filled
    assert all(out[x, 0] == 0 for x in range(34, 46))  # wide feature kept (core)
    # ...and centred: the wide feature's edges have not drifted by a window
    assert out[29, 0] == 255 and out[50, 0] == 255


def test_stroke_mask_ignores_a_uniform_shadow():
    # The mask is a half-scale image, 255 only at strokes: a page whose left half
    # is darkened uniformly has no ink anywhere, a stroke on either half does.
    im = Image.new("L", (200, 40), 230)
    px = im.load()
    for x in range(100):
        for y in range(40):
            px[x, y] = 90
    assert _stroke_mask(im).getbbox() is None
    draw = ImageDraw.Draw(im)
    draw.rectangle([40, 10, 43, 30], fill=30)  # a stroke in the shadow
    draw.rectangle([140, 10, 143, 30], fill=120)  # a stroke in the light
    bbox = _stroke_mask(im).getbbox()
    assert bbox is not None
    assert bbox[0] <= 40 // 2 and bbox[2] >= 143 // 2, bbox


def test_skew_angle_recovers_a_known_tilt():
    # a stroke mask by hand: white dashes on black, six rows
    mask = Image.new("L", (300, 400), 0)
    draw = ImageDraw.Draw(mask)
    for y in range(60, 360, 40):
        for i in range(12):
            x = 20 + i * 22
            draw.rectangle([x, y, x + 3, y + 8], fill=255)
    assert _skew_angle(mask) == 0.0
    for degrees in (-5.0, 3.5):
        tilted = mask.rotate(degrees, resample=Image.Resampling.NEAREST, fillcolor=0)
        assert abs(_skew_angle(tilted) + degrees) <= 0.5, degrees
    assert _skew_angle(Image.new("L", (300, 400), 0)) == 0.0


def test_smooth_is_a_centred_box_average():
    assert _smooth([0, 0, 1, 0, 0], 3) == [0, 1 / 3, 1 / 3, 1 / 3, 0]
    assert _smooth([1, 2, 3], 1) == [1, 2, 3]
    assert _smooth([], 5) == []


def test_split_at_valleys_cuts_deep_valleys_only():
    #            0   1   2   3   4   5   6   7   8
    profile = [0.1, 0.2, 0.1, 0.02, 0.1, 0.2, 0.1, 0.0, 0.0]
    # valley 0.02 < 0.5 * 0.2 → two pieces, cut at the minimum (index 3)
    assert _split_at_valleys((0, 7), profile, 0.5) == [(0, 3), (3, 7)]
    # raise the valley above half the smaller peak → one piece
    profile[3] = 0.15
    assert _split_at_valleys((0, 7), profile, 0.5) == [(0, 7)]
    # a bump on a flank is absorbed by the taller peak, not split off
    profile = [0.02, 0.2, 0.15, 0.16, 0.05, 0.0]
    assert _split_at_valleys((0, 5), profile, 0.5) == [(0, 5)]
    # too short to have two peaks
    assert _split_at_valleys((0, 2), [0.1, 0.2], 0.5) == [(0, 2)]


def test_trim_to_core_keeps_the_rows_around_the_peak():
    profile = [0.02, 0.05, 0.2, 0.3, 0.2, 0.05, 0.02]
    # 30% of 0.3 = 0.09 → rows 2..4
    assert _trim_to_core((0, 7), profile, 0.014, 0.3) == (2, 5)
    # the floor wins when it is higher than the ratio
    assert _trim_to_core((0, 7), profile, 0.25, 0.3) == (3, 4)


def test_guard_paper_edges_skips_frame_edges():
    profile = [1.0] * 10
    # paper from row 2 to row 8 exclusive: guard 2 rows inside each edge
    has_span = [False, False, True, True, True, True, True, True, False, False]
    _guard_paper_edges(profile, has_span, 2)
    assert profile == [1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    # paper filling the frame has no paper edges: nothing is zeroed
    profile = [1.0] * 10
    _guard_paper_edges(profile, [True] * 10, 2)
    assert profile == [1.0] * 10
    # paper reaching the top of the frame only: only the bottom edge is guarded
    profile = [1.0] * 10
    _guard_paper_edges(profile, [True] * 6 + [False] * 4, 2)
    assert profile == [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


def _update_baseline() -> None:
    """Regenerate the committed golden file from the local samples/ corpus, through
    the same production preview path the test asserts against. Deliberate manual
    step — run only after an INTENDED detector change, then eyeball the git diff
    AND the overlays from scripts/inspect_line_bands.py.

        cd backend && uv run python -m tests.test_line_detection --update-baseline
    """
    counts = {p.name: len(_bands_through_preview(p)) for p in _SAMPLES}
    _BASELINE_PATH.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_BASELINE_PATH} with {len(counts)} entries:")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    import sys

    if "--update-baseline" in sys.argv:
        if not _SAMPLES:
            raise SystemExit(f"no samples found in {_SAMPLES_DIR}")
        _update_baseline()
    else:
        raise SystemExit(__doc__ and "run with --update-baseline to regenerate the golden file")
