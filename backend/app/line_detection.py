"""Deterministic per-line band detection for the correction editor's photo pane.

Finding #11's last piece — auto-scroll: when the reviewer focuses an STF line,
the photo pans to that line on the sheet. That needs a vertical position per
line, and this module produces it WITHOUT the two things the alternatives cost:

- It never touches the vision recognizer. Recognition accuracy on these sheets is
  fragile (the Phase 3.5 tiling experiment regressed it just by re-cropping the
  image), so asking the model to also emit coordinates was rejected as a risk to
  the one thing the project protects hardest.
- It stores nothing. Bands are a pure function of the scan image, recomputed on
  demand, so there is no schema change and every existing (and hand-typed)
  transcription gets auto-scroll for free — no re-recognition.

The method is a horizontal projection profile. A hand-written sheet is dark
strokes on light paper separated by whitespace gaps, so each written row — a row
of notes, a lyric line, a heading — is a run of ink-heavy image rows with blank
rows above and below. We binarize to ink/paper, measure the ink fraction of each
image row, keep the runs of ink-heavy rows, and return them as normalized
``[y0, y1]`` fractions of image height. Normalized coordinates map onto whatever
downscaled copy the client renders, so the caller runs this on the same preview
the editor shows and the bands line up exactly.

The thresholds below are principled but first-cut: they are validated here
against synthetic bars, not against the real hand-written corpus (the editor is
login-gated). Expect a tuning pass against real sheets, the same follow-up the
pinch/zoom work took.
"""

from PIL import Image, ImageOps

# A pixel counts as ink if it is darker than this fraction of the way from the
# image's darkest to its lightest pixel. Anchoring to the image's own dynamic
# range (rather than a fixed 0-255 level) adapts to a dim scan or a bright one.
_INK_LEVEL_FRACTION = 0.5
# Below this dynamic range the page is effectively uniform (blank, or a solid
# fill) — there are no ink rows to find, so return nothing rather than slicing
# noise. 40 of 255 is a faint-but-real pencil stroke on paper.
_MIN_CONTRAST = 40
# An image row is part of a written line when its ink fraction sits in this band.
# The LOWER bound: a row of notes or lyrics covers well above it; blank paper sits
# near zero. Low enough that a sparse line (a lone note, a short heading) still
# trips it — a few percent of a wide row.
_ROW_INK_FRACTION = 0.012
# The UPPER bound (finding #9): a written row is SPARSE ink on paper — measured
# across the real samples/ corpus, the densest row is ~0.11 of its width. A row
# that is mostly ink is not writing but a solid dark region — the desk around the
# paper in a phone capture, or a heavy full-width rule. Excluding those rows here,
# at the source, stops a desk visible along ONE edge from forming a spurious band
# that survives the height filters and skews every line's auto-scroll (the
# _MAX_HEIGHT_FRACTION guard only catches a full surround, where the paper's own
# rows are ink too). 0.5 sits far above real writing (~0.11) and far below a solid
# region (~1.0).
_ROW_INK_MAX_FRACTION = 0.5
# Ink runs closer than this (as a fraction of image height) are merged into one
# band: it stitches a note row back together with the octave dots and flat dashes
# that sit just above and below it, which would otherwise read as their own thin
# rows. Kept small so a genuinely separate lyric line stays its own band.
_MERGE_GAP_FRACTION = 0.015
# Runs shorter than this (fraction of image height) are dropped as specks —
# eraser crumbs, bleed-through, a stray dot — not lines.
_MIN_HEIGHT_FRACTION = 0.006
# Runs taller than this (fraction of image height) are dropped: no single written
# row on a sargam sheet is half the page. This is the guard against the phone-
# capture failure — a scan taken on a desk (`<input capture="environment">`, not a
# flatbed) puts a dark surround around the paper, which drives `ink_level` low
# enough that EVERY image row (blank gaps included) reads as ink. The whole sheet
# then collapses to one run spanning (0, height); without this cap that came back
# as a single full-page "band" that the editor re-centred on for every line focus,
# jerking the reader's own pan away on each tab — strictly worse than not
# auto-scrolling at all. Dropping the giant run puts that case back on the
# documented no-op path (no bands → the editor simply doesn't auto-scroll). The
# real samples/ scans top out at a 0.34-tall band, so 0.5 never touches a genuine
# row. Making desk photos produce USEFUL bands (paper-region detection) is the
# owed real-corpus tuning pass, not this guard.
_MAX_HEIGHT_FRACTION = 0.5

# Band = (y0, y1) normalized to [0, 1] of image height, top-to-bottom.
Band = tuple[float, float]


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Contiguous True runs of ``flags`` as (start, end-exclusive) index pairs."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _merge_gaps(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    """Merge consecutive runs whose gap is at most ``max_gap`` rows."""
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def detect_line_bands(im: Image.Image) -> list[Band]:
    """Normalized vertical bands of the written rows on a sheet, top to bottom.

    ``im`` is any decodable image of the sheet (the caller passes the editor
    preview). Returns ``[]`` for a blank or undecodable-looking page — the editor
    then simply doesn't auto-scroll, which is the correct graceful degradation.
    """
    im = ImageOps.exif_transpose(im).convert("L")
    width, height = im.size
    if width == 0 or height == 0:
        return []

    lo, hi = im.getextrema()
    if hi - lo < _MIN_CONTRAST:
        return []
    ink_level = lo + _INK_LEVEL_FRACTION * (hi - lo)
    mask = im.point(lambda p: 255 if p < ink_level else 0)

    # Collapse each row to a single averaged pixel: a width-1 BOX downscale is the
    # projection profile. The value is 255 x (ink fraction of that row).
    column = mask.resize((1, height), Image.Resampling.BOX)
    # One "L" byte per row (the column is 1px wide), so the raw bytes ARE the
    # per-row averages, no per-pixel Python iteration to pull them out. A row
    # counts as writing when its ink fraction is in [_ROW_INK_FRACTION,
    # _ROW_INK_MAX_FRACTION]: too little is blank paper, too much is a solid dark
    # region (a desk edge), not a written line.
    lo_ink = _ROW_INK_FRACTION * 255
    hi_ink = _ROW_INK_MAX_FRACTION * 255
    ink_per_row = [lo_ink <= value <= hi_ink for value in column.tobytes()]

    runs = _runs(ink_per_row)
    runs = _merge_gaps(runs, round(height * _MERGE_GAP_FRACTION))
    min_height = max(1, round(height * _MIN_HEIGHT_FRACTION))
    max_height = height * _MAX_HEIGHT_FRACTION
    runs = [(a, b) for a, b in runs if min_height <= b - a <= max_height]
    return [(a / height, b / height) for a, b in runs]
