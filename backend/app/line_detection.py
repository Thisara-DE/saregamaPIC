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
of notes, a lyric line, a heading — is a peak in the per-row ink fraction with a
valley above and below it. We find the strokes, measure the ink fraction of each
image row, split the profile into its peaks, and return them as normalized
``[y0, y1]`` fractions of image height. Normalized coordinates map onto whatever
downscaled copy the client renders, so the caller runs this on the same preview
the editor shows and the bands line up exactly.

Four things about how that is done are worth knowing before touching it, because
each one was a real failure on the user's own photographs (findings F5, F9,
F13, F14 and F25), not a hypothetical:

- **What counts as ink is decided locally, not by a page-wide grey level** (F25).
  The real capture path is a sheet on a music stand photographed by a hand-held
  phone under room light, and every such photo carries the photographer's
  shadow across part of the paper. Any global threshold puts shadowed paper on
  the ink side of the split, which turned whole sections into one band or into
  nothing. Ink is now the *horizontal black top-hat*: a pixel is ink when it is
  darker than the paper a few pixels to its left and right (a 1-D grey closing
  along the row, minus the image). A stroke is thin along the row, so it stands
  out against its own local paper whether that paper is lit or shadowed; a
  shadow, the desk, and a paper edge are wide, so they are their own local
  background and contribute nothing. The same property makes the arcs, hold
  dashes and flat marks that sit BETWEEN rows invisible to the profile — they
  are long along the row — so the profile's valleys are deeper and the rows
  separate more cleanly than under any pixel-value threshold.
- **The ink fraction is measured inside the paper, not across the frame** (F9).
  Captures routinely contain the desk around the sheet, and counting that
  surround as ink was every failure in the F5/F9/F13/F14 family: a dark desk
  contributes to the numerator like writing does, so blank rows score as written
  ones. The denominator is each row's own paper span — the extent between its
  first and last paper column — and nothing outside it is counted at all, so a
  desk along one edge, down both sides, or crossing at an angle cannot
  manufacture a band. Where is the paper? Otsu's method over the histogram, which
  splits the well-balanced {paper} vs {desk, ink} modes of a phone capture; on a
  flatbed scan there is no second mode, so the span is the full width and the
  step is a no-op.
- **The page is deskewed before projecting** (F25). Hand-held captures tilt, and
  the user's rows themselves slope a few degrees on the flatbed scans. Under a
  tilt of θ a row sweeps ``width·tan θ`` of image height, which at 8–10° exceeds
  the row pitch: adjacent rows overlap in y and no projection can separate them.
  The skew is found by rotating the stroke mask through candidate angles and
  keeping the one whose profile is sharpest, then both masks are rotated about
  the image centre before bucketing. Bands are reported in that deskewed frame,
  which for the caller means "the row's y at the centre of the image" — the
  right thing to scroll to, and within a few percent of the row's ends.
- **Runs of ink are split at profile valleys, not only by threshold** (F25). On
  a dense sheet the gap between rows never falls to zero (octave dots, the ends
  of arcs, a stray stroke), so a single threshold merges a whole section. Each
  run above the floor is cut at every valley that drops below half the smaller
  of its two neighbouring peaks, and each piece is then trimmed to the rows that
  hold at least 30 % of its own peak, so a band is the row's core rather than the
  row plus half of the blank space around it.

A row that is *entirely* dark has no paper span of its own, and is resolved by
position, not by pixel value: an all-dark run bounded by paper on both sides is
taken as writing and inherits its neighbours' span, while one that runs to the
image edge is surround and is dropped. See ``_fill_enclosed_gaps``.

The thresholds below are principled but were calibrated against, and are guarded
by, the real corpus: ``tests/line_bands_baseline.json`` pins the per-sheet band
count through the production WebP preview path for every sheet in ``samples/``,
flatbed scans and phone photographs alike. Regenerate it only after a deliberate
change, and eyeball the overlays ``scripts/inspect_line_bands.py`` writes before
committing — a count is not a position.
"""

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageOps

# Below this dynamic range the page is effectively uniform (blank, or a solid
# fill) — there are no ink rows to find, so return nothing rather than slicing
# noise. 40 of 255 is a faint-but-real pencil stroke on paper.
_MIN_CONTRAST = 40
# The stroke mask is computed at 1/_INK_SCALE of the preview's resolution. The
# preview is 1600 px on its long side and a pencil stroke there is 3–6 px wide;
# at half scale it is still 2–3 px, wide enough to survive the box downscale and
# narrow enough for the closing window below, and the four ImageChops passes run
# on a quarter of the pixels.
_INK_SCALE = 2
# Width, in half-scale pixels, of the horizontal closing window: a dark run
# shorter than this along the row is filled with the paper beside it and so shows
# up in the top-hat as ink; a longer one is background. 8 half-scale px = 16 px on
# the preview, which covers any stroke, the vertical bar lines, and a small
# octave dot, and excludes the arcs and hold dashes (tens of px long) and every
# shadow or edge (hundreds). The window is built by doubling, so it is 8 exactly.
_STROKE_WINDOW = 8
# How much darker than its local paper a pixel must be to count as ink, in grey
# levels. Pencil on paper drops 40–80 levels in the light and ~20–35 in a deep
# shadow, where the same contrast scales with the illumination; WebP q80 noise on
# flat paper is ±2–3. 16 sits clear of the noise and still catches the shadowed
# strokes on the F25 photographs.
_INK_DROP = 16
# Skew search: candidate rotations in degrees, coarse pass then a fine pass around
# the best coarse angle. ±12° covers a hand-held capture with margin (the F25
# photographs run to ~9°); the user's rows on flatbed scans slope 2–6°.
_SKEW_RANGE = 12.0
_SKEW_COARSE_STEP = 1.5
_SKEW_FINE_STEP = 0.25
_SKEW_FINE_STEPS = 5
# An image row is part of a written line when at least this fraction of ITS PAPER
# SPAN is ink. Measured against the paper span, this number means the same thing
# on a flatbed scan and on a phone photo. It was 0.014 under the old pixel-value
# ink test and stays 0.014 under the top-hat: the top-hat finds fewer pixels per
# row (strokes only, no arcs), but a short heading such as "Verse" still clears
# it, and the corpus overlays were re-checked row by row after the change.
_ROW_INK_FRACTION = 0.014
# Rows within this fraction of image height of the paper's top or bottom edge are
# not measured. A tilted sheet's edge is a thin dark line that, once deskewed,
# collapses into a single horizontal row of "ink" just inside the paper; no
# written row sits that close to the edge. Edges that run off the frame (a
# flatbed scan fills it) are not paper edges and are left alone.
_EDGE_GUARD_FRACTION = 0.015
# The profile is box-smoothed over this fraction of image height before the peak
# analysis so a one-row dip inside a stroke does not read as a valley. 0.005 of
# 1600 px is 8 rows, well under any written row's height.
_SMOOTH_FRACTION = 0.005
# Ink runs closer than this (as a fraction of image height) are merged into one
# run before the valley analysis: it stitches a note row back together with the
# octave dots that sit just above and below it, which would otherwise read as
# their own thin rows.
_MERGE_GAP_FRACTION = 0.015
# A valley splits a run when the profile there drops below this fraction of the
# smaller of the two peaks it separates. Half is deliberately lenient: on the
# dense F25 sheets the inter-row floor sits at 20–40 % of the row peaks, and a
# real row's own internal dip (between its letters and its octave dots) does not
# drop that far after smoothing.
_VALLEY_RATIO = 0.5
# After splitting, each piece is trimmed to the contiguous rows around its peak
# that hold at least this fraction of the peak, so the band is the written row
# rather than the row plus the blank space up to the cut.
_CORE_RATIO = 0.3
# Pieces with fewer rows of raw ink than this (fraction of image height) are
# dropped as specks — eraser crumbs, bleed-through, a stray dot — not lines.
_MIN_HEIGHT_FRACTION = 0.006
# Runs taller than this (fraction of image height) are dropped: no single written
# row on a sargam sheet is half the page. A run that tall is wrong however it
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


@dataclass(frozen=True)
class LineAnalysis:
    """Everything ``analyze_lines`` learned about a sheet.

    ``bands`` are in the deskewed frame (see the module docstring);
    ``skew_degrees`` is the rotation that was applied, counter-clockwise
    positive as ``Image.rotate`` counts it, so a caller can rotate the same
    image by it and draw the bands on the result.
    """

    bands: list[Band]
    skew_degrees: float


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
    "dark means ``value < t``". Used to locate the paper against the desk, where
    the two classes are comparable in size; it is NOT used for ink (see the
    module docstring — ink is decided locally).

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


def _horizontal_max(im: Image.Image, window: int) -> Image.Image:
    """Grey dilation along the row: each pixel becomes the max of the ``window``
    pixels ending at it. Built by doubling shifted copies, so it is log2(window)
    C-speed passes; ``window`` is rounded up to a power of two."""
    shift = 1
    while shift < window:
        im = ImageChops.lighter(im, ImageChops.offset(im, shift, 0))
        shift *= 2
    return im


def _horizontal_min(im: Image.Image, window: int) -> Image.Image:
    """Grey erosion along the row over the ``window`` pixels STARTING at each pixel
    — the mirror of ``_horizontal_max``, so that max-then-min is a closing centred
    on the pixel rather than one shifted by a window's width."""
    shift = 1
    while shift < window:
        im = ImageChops.darker(im, ImageChops.offset(im, -shift, 0))
        shift *= 2
    return im


def _stroke_mask(gray: Image.Image) -> Image.Image:
    """The ink mask at 1/_INK_SCALE resolution: 255 where a pixel is at least
    ``_INK_DROP`` darker than the horizontal closing of its neighbourhood.

    ``ImageChops.offset`` wraps around, so the outermost ``_STROKE_WINDOW``
    half-scale columns see the opposite edge of the frame; they lie outside the
    paper span (or inside its one-bucket inset) and are never counted.
    """
    width, height = gray.size
    small = gray.resize(
        (max(1, width // _INK_SCALE), max(1, height // _INK_SCALE)), Image.Resampling.BOX
    )
    closed = _horizontal_min(_horizontal_max(small, _STROKE_WINDOW), _STROKE_WINDOW)
    return ImageChops.subtract(closed, small).point(lambda v: 255 if v >= _INK_DROP else 0)


def _profile_sharpness(mask: Image.Image) -> int:
    """How row-aligned the ink in ``mask`` is: the sum of squared differences
    between adjacent rows of its whole-frame projection. Rows that line up with
    the image rows give a spiky profile (large); the same rows tilted smear into
    each other (small). Whole-frame is fine here — the desk is the same on every
    row and only adds a slow ramp."""
    profile = mask.resize((1, mask.height), Image.Resampling.BOX).tobytes()
    return sum((profile[i] - profile[i - 1]) ** 2 for i in range(1, len(profile)))


def _rotated(mask: Image.Image, degrees: float) -> Image.Image:
    """``mask`` rotated about its centre, same size, corners filled with 0 (not
    paper / not ink)."""
    return mask.rotate(degrees, resample=Image.Resampling.NEAREST, fillcolor=0)


def _skew_angle(mask: Image.Image) -> float:
    """The rotation (degrees, counter-clockwise positive) that makes the written
    rows in ``mask`` horizontal: coarse sweep over ±_SKEW_RANGE, then a fine sweep
    around the best coarse angle. Returns 0.0 for a blank mask."""
    if not mask.getbbox():
        return 0.0

    # Ties (a square page scores the same at ±0.25°) resolve toward the smaller
    # rotation, so a sheet that needs none gets none.
    def score(angle: float) -> tuple[int, float]:
        return _profile_sharpness(_rotated(mask, angle) if angle else mask), -abs(angle)

    steps = round(2 * _SKEW_RANGE / _SKEW_COARSE_STEP)
    coarse = [-_SKEW_RANGE + i * _SKEW_COARSE_STEP for i in range(steps + 1)]
    best = max(coarse, key=score)
    fine = [best + i * _SKEW_FINE_STEP for i in range(-_SKEW_FINE_STEPS, _SKEW_FINE_STEPS + 1)]
    return max(fine, key=score)


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
    class is not exhaustively "heavy writing": a cast shadow, a fold, or an object
    resting on the sheet is enclosed too. Since ink is decided locally (top-hat),
    such a region only becomes a band if it holds strokes — a uniform shadow
    scores zero — so the inheritance is now safe rather than merely bounded by
    ``max_run`` and the max-height filter.
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


def _guard_paper_edges(profile: list[float], has_span: list[bool], guard: int) -> None:
    """Zero the ``guard`` rows just inside every paper edge, in place.

    An edge is where the span appears or disappears; the frame's own top and
    bottom are not edges (a flatbed scan fills the frame — its first row is
    writing-eligible paper, not a paper edge)."""
    for start, end in _runs(has_span):
        if start > 0:
            for r in range(start, min(end, start + guard)):
                profile[r] = 0.0
        if end < len(has_span):
            for r in range(max(start, end - guard), end):
                profile[r] = 0.0


def _smooth(values: list[float], window: int) -> list[float]:
    """Box-smooth ``values`` over ``window`` samples (centred; shorter at the
    ends). ``window`` ≤ 1 returns a copy."""
    n = len(values)
    if window <= 1 or n == 0:
        return list(values)
    half = window // 2
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append((prefix[hi] - prefix[lo]) / (hi - lo))
    return out


def _split_at_valleys(
    run: tuple[int, int], profile: list[float], ratio: float
) -> list[tuple[int, int]]:
    """Cut ``run`` at every valley that separates two peaks of ``profile``.

    Peaks are taken from the highest down; a candidate peak survives only if, on
    each side, the lowest point between it and the nearest surviving peak is
    below ``ratio`` times the smaller of the two — otherwise it is a bump on that
    neighbour's flank and is absorbed. Cuts go at the minimum between each pair of
    surviving peaks. A run with fewer than two surviving peaks comes back whole.
    """
    start, end = run
    if end - start < 3:
        return [run]
    peaks = [
        i
        for i in range(start + 1, end - 1)
        if profile[i] > profile[i - 1] and profile[i] >= profile[i + 1]
    ]
    if profile[start] > profile[start + 1]:
        peaks.insert(0, start)
    if profile[end - 1] > profile[end - 2]:
        peaks.append(end - 1)
    kept: list[int] = []
    for candidate in sorted(peaks, key=lambda i: -profile[i]):
        separated = True
        for other in kept:
            lo, hi = (other, candidate) if other < candidate else (candidate, other)
            valley = min(profile[lo : hi + 1])
            if valley >= ratio * min(profile[candidate], profile[other]):
                separated = False
                break
        if separated:
            kept.append(candidate)
    if len(kept) < 2:
        return [run]
    kept.sort()
    edges = [start]
    for a, b in zip(kept, kept[1:], strict=False):
        segment = profile[a : b + 1]
        edges.append(a + segment.index(min(segment)))
    edges.append(end)
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def _trim_to_core(
    run: tuple[int, int], profile: list[float], floor: float, ratio: float
) -> tuple[int, int]:
    """Shrink ``run`` to the contiguous rows around its peak whose profile is at
    least ``max(floor, ratio * peak)``."""
    start, end = run
    segment = profile[start:end]
    peak = start + segment.index(max(segment))
    level = max(floor, ratio * profile[peak])
    lo = peak
    while lo - 1 >= start and profile[lo - 1] >= level:
        lo -= 1
    hi = peak + 1
    while hi < end and profile[hi] >= level:
        hi += 1
    return (lo, hi)


def analyze_lines(im: Image.Image) -> LineAnalysis:
    """Find the written rows of a sheet: their bands plus the skew that was removed.

    ``im`` is any decodable image of the sheet (the caller passes the editor
    preview). ``bands`` is ``[]`` for a blank or undecodable-looking page — the
    editor then simply doesn't auto-scroll, which is the correct graceful
    degradation.

    Bands are fractions of the FULL image height even when the sheet occupies only
    part of the frame, so the caller can map them straight onto the rendered
    preview without knowing where the paper was found.
    """
    im = ImageOps.exif_transpose(im).convert("L")
    width, height = im.size
    if width == 0 or height == 0:
        return LineAnalysis([], 0.0)

    lo, hi = im.getextrema()
    if hi - lo < _MIN_CONTRAST:
        return LineAnalysis([], 0.0)

    # Where is the paper? Otsu over the histogram: on a phone capture it splits the
    # two large modes, paper against {desk, ink}. On a flatbed scan there is no
    # second mode, so everything but the writing is paper and the span is the full
    # width. Computed once, outside the lambda: point() evaluates its callable per
    # palette entry, so an inline call would run Otsu 256 times per image.
    paper_level = _otsu_threshold(im.histogram())
    paper = im.point(lambda p: 255 if p >= paper_level else 0)
    # What is ink? Decided against its own local paper — see the module docstring.
    ink = _stroke_mask(im)

    skew = _skew_angle(ink)
    if skew:
        ink = _rotated(ink, skew)
        paper = _rotated(paper, skew)

    # Average into buckets: a BOX downscale to _PAPER_COLUMNS wide gives, per row,
    # 255 x (paper fraction) and 255 x (ink fraction) of each bucket. The ink mask
    # is half-scale, so the same resize also brings it back to ``height`` rows.
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
    profile: list[float] = []
    for r, span in enumerate(spans):
        if span is None:
            profile.append(0.0)
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
            profile.append(0.0)
            continue
        row = ink_grid[r * columns + first : r * columns + last + 1]
        # sum() over a bytes slice is the row's ink, measured over the paper span
        # alone — the desk outside it is not in the numerator or the denominator.
        profile.append(sum(row) / (255 * len(row)))

    _guard_paper_edges(
        profile, [s is not None for s in spans], round(height * _EDGE_GUARD_FRACTION)
    )
    raw = profile
    profile = _smooth(raw, max(1, round(height * _SMOOTH_FRACTION)))

    runs = _runs([v >= _ROW_INK_FRACTION for v in profile])
    runs = _merge_gaps(runs, round(height * _MERGE_GAP_FRACTION))
    pieces = [
        _trim_to_core(piece, profile, _ROW_INK_FRACTION, _CORE_RATIO)
        for run in runs
        for piece in _split_at_valleys(run, profile, _VALLEY_RATIO)
    ]
    # The min-height filter counts rows of RAW ink, not the piece's extent: the
    # smoothing spreads a 3-row speck over a window's worth of rows, which would
    # otherwise let it through as a band.
    min_height = max(1, round(height * _MIN_HEIGHT_FRACTION))
    max_height = height * _MAX_HEIGHT_FRACTION
    pieces = [
        (a, b)
        for a, b in pieces
        if b - a <= max_height
        and sum(1 for r in range(a, b) if raw[r] >= _ROW_INK_FRACTION) >= min_height
    ]
    return LineAnalysis([(a / height, b / height) for a, b in pieces], skew)


def detect_line_bands(im: Image.Image) -> list[Band]:
    """Normalized vertical bands of the written rows on a sheet, top to bottom.

    The route's entry point; see ``analyze_lines`` for the full result.
    """
    return analyze_lines(im).bands
