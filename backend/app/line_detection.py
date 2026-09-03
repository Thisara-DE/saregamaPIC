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

**The ink fraction is measured inside the paper, not across the frame** (finding
F9). Captures here are phone photographs, not flatbed scans, so the frame
routinely contains the desk around the sheet. Counting that surround as ink is
what produced every failure in the F5/F9/F13/F14 family: measured over the whole
row, a dark desk contributes to the numerator exactly like writing does, so blank
paper rows score as written ones and the resulting spurious bands silently shift
every line's scroll position. The denominator is therefore each row's own paper
span — the horizontal extent between its first and last paper column — and
anything outside that span is not counted at all. A desk along one edge, down
both sides, or crossing at an angle falls outside the span at every row and so
cannot manufacture a band, which is what a whole-frame threshold could never
achieve by tuning alone.

Two consequences worth knowing before touching the thresholds:

- There are **two thresholds, answering two different questions.** Where is the
  paper? — Otsu's method over the histogram, which splits the well-balanced
  {paper} vs {desk, ink} modes of a phone capture. What is ink? — the original
  midpoint of the dynamic range. They are not interchangeable: Otsu assumes two
  comparable classes, and on a clean scan ink is ~2 % of the pixels, so it drifts
  up toward the paper mode and swallows the anti-aliased halo around every stroke.
  Measured on the real ``samples/`` corpus, using Otsu as the ink level put the
  threshold at 217 instead of 165 and merged adjacent written rows into bands up
  to half the page tall. Desk contamination of the ink level is not a problem the
  ink threshold has to solve, because the paper span already excludes the desk
  from the measurement.
- A row that is *entirely* dark has no paper span of its own, and is resolved by
  position, not by pixel value: an all-dark run bounded by paper on both sides is
  taken as writing and inherits its neighbours' span, while one that runs to the
  image edge is surround and is dropped. A written row flush against the top or
  bottom edge with no margin at all is therefore missed; real captures have a
  margin, and missing a band degrades to not scrolling rather than scrolling
  somewhere wrong. The enclosed case is treated as writing because that is the
  useful default, but it is not only writing — an on-sheet shadow, fold, or resting
  object is enclosed too and is mis-classified as a written row, bounded (not
  prevented) by the max-height filter. See ``_fill_enclosed_gaps``.

The thresholds below are principled but still validated against synthetic images
rather than the real hand-written corpus (the editor is login-gated). The
synthetics now include the desk-photo input class in four shapes — full surround,
one edge, both sides, and tilted — which is what the earlier white-page-only
tests structurally could not express. Expect a tuning pass against real sheets.
"""

from PIL import Image, ImageOps

# A pixel counts as ink if it is darker than this fraction of the way from the
# image's darkest to its lightest pixel. Anchoring to the image's own dynamic
# range (rather than a fixed 0-255 level) adapts to a dim scan or a bright one.
# A dark surround drags this level down, which only makes it STRICTER — the safe
# direction, costing a faint stroke rather than inventing one — and the desk is
# excluded from the measurement by the paper span regardless.
_INK_LEVEL_FRACTION = 0.5
# Below this dynamic range the page is effectively uniform (blank, or a solid
# fill) — there are no ink rows to find, so return nothing rather than slicing
# noise. 40 of 255 is a faint-but-real pencil stroke on paper.
_MIN_CONTRAST = 40
# An image row is part of a written line when at least this fraction of ITS PAPER
# SPAN is ink. A row of notes or lyrics covers well above this; blank paper sits
# near zero. Low enough that a sparse line (a lone note, a short heading) still
# trips it — a few percent of a wide row. Note the denominator: measured against
# the paper span, this number means the same thing on a flatbed scan and on a
# phone photo, which is exactly what F9/F13 showed a whole-width denominator
# could not do.
#
# 0.014, not the 0.012 this was before the paper span existed — the constant had
# to be re-calibrated because what it divides by changed. The old code averaged a
# whole row into ONE byte and tested `value >= 0.012 * 255` (= `value >= 3.06`);
# `value` is an integer, so that is `value >= 4`. But `value` is not `floor(255·f)`
# — it is Pillow's resampled average, whose 8-bit accumulator is seeded with half
# an LSB and so rounds half-up, making `value >= 4` mean `f >= 3.5/255 ≈ 0.0137`.
# So the threshold that ACTUALLY SHIPPED was ≈0.0137, and 0.014 is a ~2% tightening
# of it, holding shipped behaviour roughly constant while the denominator changed
# underneath it — NOT the correction of a 17%-loose 0.0157 an earlier version of
# this note claimed (see finding F18; that arithmetic was wrong). Pulling the other
# way by a similar amount: the span's one-bucket inset at each end (see below) drops
# ~2 of ~64 buckets, so the same ink is ~3% larger as a fraction; the two nearly
# cancel. A re-tune must reason from ≈0.0137 as the known-good floor, not 0.0157.
#
# Calibrated against all 10 `samples/` scans, the only real corpus there is. That
# comparison is now an EXECUTABLE golden file — tests/line_bands_baseline.json, the
# per-sheet band count through the production WebP-q80 preview path — asserted by
# test_real_sheets_match_the_committed_baseline, not the prose "0 merged, 0 lost"
# that used to live here (which was measured on a JPEG thumbnail the running system
# never sees; finding F17). Re-run `uv run python -m tests.test_line_detection
# --update-baseline` (from backend/) after a deliberate threshold change, eyeball
# the diff, and only then commit the new golden file.
_ROW_INK_FRACTION = 0.014
# Ink runs closer than this (as a fraction of image height) are merged into one
# band: it stitches a note row back together with the octave dots and flat dashes
# that sit just above and below it, which would otherwise read as their own thin
# rows. Kept small so a genuinely separate lyric line stays its own band.
_MERGE_GAP_FRACTION = 0.015
# Runs shorter than this (fraction of image height) are dropped as specks —
# eraser crumbs, bleed-through, a stray dot — not lines.
_MIN_HEIGHT_FRACTION = 0.006
# Runs taller than this (fraction of image height) are dropped: no single written
# row on a sargam sheet is half the page (the real samples/ scans top out at a
# 0.34-tall band, so 0.5 never touches a genuine row). Kept from the F5 fix as
# harm reduction — with the paper-span denominator the whole-sheet collapse it was
# written for should no longer occur, but a band that large is wrong however it
# arose, and returning nothing puts the case on the documented no-op path (no
# bands → the editor simply doesn't auto-scroll) instead of re-centring the photo
# on every line focus. It also bounds the all-dark-run inheritance below.
_MAX_HEIGHT_FRACTION = 0.5
# Horizontal resolution of the paper-span scan, in buckets across the image width.
# Finding each row's paper edges pixel-by-pixel is a per-pixel Python loop over a
# 1600px preview; averaging into buckets first keeps the whole pass at C speed and
# still locates each edge to ~1.5% of the width, far finer than the span needs to
# be for a ratio.
_PAPER_COLUMNS = 64
# A bucket counts as paper when at least this fraction of it is lighter than the
# ink/paper split. Paper carries sparse writing so its buckets sit near 1.0; desk
# buckets sit at 0. Only the boundary bucket is genuinely ambiguous, and putting
# the line at half fills it in whichever direction it mostly is.
_PAPER_BUCKET_LEVEL = 0.5
# A row whose paper span is narrower than this fraction of the width is not
# treated as paper at all. Guards the ratio's denominator: a couple of light
# specks in a dark surround would otherwise define a two-bucket "span" that a
# little noise fills, scoring as a written row.
_MIN_PAPER_SPAN_FRACTION = 0.25

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


def _otsu_threshold(histogram: list[int]) -> int:
    """The grey level that best splits ``histogram`` into dark and light classes.

    Standard Otsu: the threshold maximizing between-class variance. Returned as
    "dark means ``value < t``". Chosen over a fixed fraction of the dynamic range
    because that fraction is anchored to the image's extrema, so a single dark
    desk pixel moves the ink level for the whole page (F5's fix hint (2), the
    root cause behind F9/F13/F14).

    Levels with no pixels leave the variance unchanged, so the maximum is usually
    a plateau rather than a point — on a two-tone synthetic it spans everything
    between the two tones. Taking the plateau's midpoint puts the threshold in the
    middle of the empty gap instead of hard against one tone, where a little noise
    would cross it.
    """
    total = sum(histogram)
    if total == 0:
        return 128
    weighted_total = sum(level * count for level, count in enumerate(histogram))
    dark_count = 0
    dark_weighted = 0
    best_variance = -1.0
    plateau: list[int] = []
    for t in range(1, 256):
        dark_count += histogram[t - 1]
        dark_weighted += (t - 1) * histogram[t - 1]
        light_count = total - dark_count
        if dark_count == 0 or light_count == 0:
            continue
        dark_mean = dark_weighted / dark_count
        light_mean = (weighted_total - dark_weighted) / light_count
        variance = dark_count * light_count * (dark_mean - light_mean) ** 2
        if variance > best_variance:
            best_variance, plateau = variance, [t]
        elif variance == best_variance:
            plateau.append(t)
    if not plateau:
        return 128
    return round(sum(plateau) / len(plateau))


def _paper_spans(rows: list[bytes]) -> list[tuple[int, int] | None]:
    """Each row's ``(first, last)`` paper bucket, or ``None`` if it has none.

    ``rows`` holds one thresholded byte per bucket, ``0xff`` where the bucket is
    paper. ``find``/``rfind`` do the scan in C, so this stays one pass per row
    rather than one per pixel.
    """
    spans: list[tuple[int, int] | None] = []
    for row in rows:
        first = row.find(b"\xff")
        spans.append(None if first < 0 else (first, row.rfind(b"\xff")))
    return spans


def _fill_enclosed_gaps(
    spans: list[tuple[int, int] | None], max_run: int
) -> list[tuple[int, int] | None]:
    """Give all-dark rows the paper span of their neighbours, but only when enclosed.

    A row with no paper bucket has lost the measurement the whole module rests on,
    and it is resolved by position, not by pixel value — a desk and a pencil stroke
    are both just "not paper". A dark run reaching the top or bottom edge has
    surround on one side, so it is left ``None`` and dropped. A dark run with paper
    above AND below it is enclosed, so it inherits the wider of the two enclosing
    spans and stays a candidate.

    Enclosed is treated *as* writing because that is the useful default, but the
    class is not exhaustively "heavy writing". A third member is any dark band lying
    ON the sheet — a cast shadow from the phone or photographer, a fold or curl, an
    object resting on the paper — which is also enclosed by paper and so also
    inherits a span, and if it is darker than ``ink_level`` becomes a band. This is
    a known mis-classification, not a regression: the old whole-frame threshold
    banded such a shadow too. It is bounded, not prevented: ``max_run`` caps the
    inheritance, and the max-height filter drops what survives. Note those two
    limits are the SAME number (``max_run`` is ``round(height * _MAX_HEIGHT_FRACTION)``),
    so a run of exactly ``height/2`` passes both rather than being caught by the
    second — an on-sheet shadow spanning close to half the page is the residual
    case, and separating it would need a per-row ink *ceiling* over the paper span
    (the ``_ROW_INK_MAX_FRACTION`` shape F13/F14 defeated when it was measured over
    the frame), with the same fail-first fixture discipline the desk cases got.
    """
    filled = list(spans)
    start: int | None = None
    for i in range(len(filled) + 1):
        missing = i < len(filled) and filled[i] is None
        if missing and start is None:
            start = i
        elif not missing and start is not None:
            above = filled[start - 1] if start > 0 else None
            below = filled[i] if i < len(filled) else None
            if above is not None and below is not None and i - start <= max_run:
                span = above if (above[1] - above[0]) >= (below[1] - below[0]) else below
                for j in range(start, i):
                    filled[j] = span
            start = None
    return filled


def detect_line_bands(im: Image.Image) -> list[Band]:
    """Normalized vertical bands of the written rows on a sheet, top to bottom.

    ``im`` is any decodable image of the sheet (the caller passes the editor
    preview). Returns ``[]`` for a blank or undecodable-looking page — the editor
    then simply doesn't auto-scroll, which is the correct graceful degradation.

    Bands are fractions of the FULL image height even when the sheet occupies only
    part of the frame, so the caller can map them straight onto the rendered
    preview without knowing where the paper was found.
    """
    im = ImageOps.exif_transpose(im).convert("L")
    width, height = im.size
    if width == 0 or height == 0:
        return []

    lo, hi = im.getextrema()
    if hi - lo < _MIN_CONTRAST:
        return []

    # Where is the paper? Otsu over the histogram: on a phone capture it splits the
    # two large modes, paper against {desk, ink}. On a flatbed scan there is no
    # second mode, so everything but the writing is paper and the span is the full
    # width — measured on the real samples/ corpus, 1590 of 1600 rows span the whole
    # frame, so the paper step is a no-op there and behaviour is unchanged.
    # Computed once, outside the lambda: point() evaluates its callable per palette
    # entry, so an inline call would run Otsu 256 times per image.
    paper_level = _otsu_threshold(im.histogram())
    paper = im.point(lambda p: 255 if p >= paper_level else 0)
    # What is ink? A separate, tighter question — see the module docstring for why
    # Otsu is the wrong answer to it.
    ink_level = lo + _INK_LEVEL_FRACTION * (hi - lo)
    ink = im.point(lambda p: 255 if p < ink_level else 0)

    # Average into buckets: a BOX downscale to _PAPER_COLUMNS wide gives, per row,
    # 255 x (paper fraction) and 255 x (ink fraction) of each bucket.
    columns = min(_PAPER_COLUMNS, width)
    paper_grid = (
        paper.resize((columns, height), Image.Resampling.BOX)
        .point(lambda v: 255 if v >= _PAPER_BUCKET_LEVEL * 255 else 0)
        .tobytes()
    )
    ink_grid = ink.resize((columns, height), Image.Resampling.BOX).tobytes()
    paper_rows = [paper_grid[r * columns : (r + 1) * columns] for r in range(height)]

    spans = _paper_spans(paper_rows)
    spans = _fill_enclosed_gaps(spans, round(height * _MAX_HEIGHT_FRACTION))

    min_span = _MIN_PAPER_SPAN_FRACTION * columns
    ink_per_row: list[bool] = []
    for r, span in enumerate(spans):
        if span is None:
            ink_per_row.append(False)
            continue
        # Inset past the buckets at each end of the span. Those straddle the edge
        # of the paper, so they hold surround by construction, and that leaks into
        # the numerator: on a 45%-desk frame two half-desk edge buckets alone score
        # 0.022 of a 36-bucket span — nearly twice _ROW_INK_FRACTION, enough to
        # make every blank row read as written. The cost is that ink in the
        # outermost ~1.5% of the paper's width is not counted, which no written row
        # depends on; the benefit is a numerator containing only paper.
        first, last = span[0] + 1, span[1] - 1
        if last - first + 1 < min_span:
            ink_per_row.append(False)
            continue
        row = ink_grid[r * columns + first : r * columns + last + 1]
        # sum() over a bytes slice is the row's ink, measured over the paper span
        # alone — the desk outside it is not in the numerator or the denominator.
        ink_per_row.append(sum(row) >= _ROW_INK_FRACTION * 255 * len(row))

    runs = _runs(ink_per_row)
    runs = _merge_gaps(runs, round(height * _MERGE_GAP_FRACTION))
    min_height = max(1, round(height * _MIN_HEIGHT_FRACTION))
    max_height = height * _MAX_HEIGHT_FRACTION
    runs = [(a, b) for a, b in runs if min_height <= b - a <= max_height]
    return [(a / height, b / height) for a, b in runs]
