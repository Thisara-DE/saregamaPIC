"""Claude vision recognition: hand-written sargam photo -> STF draft.

The Anthropic client is built lazily and injected as a callable (``Recognizer``)
so the rest of the app — and every test — never imports the SDK or needs an API
key. ``make_recognizer(settings)`` returns the real one; tests pass a fake to
``create_app(recognizer=...)``.

Fidelity: the original scan is never modified. A downscaled, EXIF-corrected JPEG
*copy* is what we send to the model (below the fidelity boundary — the stored
original stays byte-identical).

``make_tiled_recognizer`` is the Phase 3.5 Rung 1 experiment variant: it splits
the page into overlapping half-page bands, recognizes each at native detail, and
stitches the results. It is an OFFLINE eval tool only (driven by
``scripts/evaluate_recognition.py --tiled half``); the production ``recognize``
route still uses the whole-page ``make_recognizer``. See the vault design note
``saregamapic/phase-3-5-tiling-experiment``.
"""

import base64
import io
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from .stf import STF_LINE_KINDS

# A recognizer maps (original image bytes, content-type) -> a draft result.
Recognizer = Callable[[bytes, str], "RecognitionResult"]


@dataclass(frozen=True)
class RecognitionResult:
    stf: dict  # {"header": {...}, "lines": [...]}
    model: str
    input_tokens: int
    output_tokens: int
    suggested_title: str | None = None


class RecognitionUnavailable(RuntimeError):
    """Raised when recognition can't run (no API key, SDK missing, or a bad
    model response). The route turns this into a clean 503 rather than a 500."""

    def __init__(self, message: str, *, code: str = "recognition_unavailable") -> None:
        super().__init__(message)
        self.code = code


# Long edge to downscale to before the vision call. Kept above the native long
# edge of a typical scan so full-page sheets pass through without losing the
# faint slur arcs; high enough that the dot-vs-dash (octave vs flat) distinction
# survives, low enough to bound cost.
_MAX_EDGE = 2600
# Adaptive thinking counts toward max_tokens, so a dense full-page sheet can spend
# most of a small budget on reasoning and then truncate the STF mid-output
# (stop_reason "max_tokens"). 8000 was too tight — a sheet with many lines + lyrics
# hit the cap. Opus supports up to 128K output and cost accrues only on tokens
# actually generated, so a generous ceiling is safe. We stream and assemble the
# final message (below) so the SDK doesn't refuse a high cap and the long call
# keeps the connection active — Railway drops idle long-running responses, which is
# exactly what the client-side recognition recovery exists to survive.
_MAX_OUTPUT_TOKENS = 32000
PREPROCESSING_VERSION = "grayscale-autocontrast-2600-v1"
PROMPT_VERSION = "stf-v1.1-2026-07-24-msharp"

# --- Tiled recognizer (Phase 3.5 Rung 1) -------------------------------------
# Each band is cropped from the full-resolution grayscale image and kept UNDER
# the model's per-image caps (2576 px long edge AND ~3.75 MP area — whichever
# binds first) so it is seen at native detail instead of being downscaled
# server-side. A whole portrait page at 2600 px is ≈4.8 MP, over the area cap, so
# the API shrinks it; a half-page band fits under the cap → ~2× pixels-per-mark.
# See the vault note ``saregamapic/claude-api-vision-limits``.
_TILE_MAX_EDGE = 2576
_TILE_MAX_PIXELS = 3_750_000
# Fraction of page height shared between adjacent bands, so a notation row sitting
# on the cut line is fully contained in at least one band (never halved). The
# duplicated rows are dropped at stitch time.
_TILE_OVERLAP_FRACTION = 0.12
# Two recognitions of the same physical row are near-identical but not byte-equal
# (the model is stochastic); the stitcher treats lines this similar as duplicates.
_OVERLAP_SIMILARITY = 0.7
TILED_PREPROCESSING_VERSION = "tiled-half-grayscale-2576-v1"


def _preprocess(data: bytes) -> Image.Image:
    """EXIF-correct + grayscale + contrast-boost a *copy* of the scan, full-res.

    Phone photos store rotation in EXIF with pixels unrotated; the vision model
    sees raw pixels, so orientation must be baked in here (same reason as the
    thumbnail path).

    Faint pencil slur-arcs (curves) are the lightest strokes on the page and the
    first thing lost to downscale + JPEG — a curve-dropping recognition run is the
    classic failure. Flatten to grayscale (color carries no notation) and stretch
    contrast at full resolution so those arcs and flat underlines darken *before*
    any downscale averages them away. Downscaling/tiling happens after this.
    """
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im = ImageOps.autocontrast(im, cutoff=1)
        im = ImageEnhance.Contrast(im).enhance(1.4)
    return im


def _fit_box(size: tuple[int, int], max_edge: int, max_pixels: int | None) -> tuple[int, int]:
    """The ``thumbnail`` box that fits ``size`` under both caps (long edge + area)."""
    if max_pixels is None:
        return (max_edge, max_edge)
    w, h = size
    scale = min(1.0, max_edge / max(w, h))
    area = w * h * scale * scale
    if area > max_pixels:
        scale *= (max_pixels / area) ** 0.5
    return (max(1, math.floor(w * scale)), max(1, math.floor(h * scale)))


def _encode(im: Image.Image, max_edge: int, max_pixels: int | None) -> tuple[bytes, str]:
    """Downscale ``im`` to fit the caps and JPEG-encode it. Returns (bytes, media_type)."""
    im.thumbnail(_fit_box(im.size, max_edge, max_pixels))
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=95)
    return out.getvalue(), "image/jpeg"


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """EXIF-correct + contrast-boost + downscale a *copy* of the scan for the model.

    The whole-page path used by the production recognizer: one image, long edge
    capped at ``_MAX_EDGE``. Returns (jpeg_bytes, media_type).
    """
    return _encode(_preprocess(data), _MAX_EDGE, None)


def _horizontal_bands(im: Image.Image, tiles: int, overlap_fraction: float) -> list[Image.Image]:
    """Split ``im`` into ``tiles`` full-width horizontal bands that overlap by
    ``overlap_fraction`` of page height, centered on each internal cut."""
    w, h = im.size
    overlap = int(h * overlap_fraction)
    step = h / tiles
    bands = []
    for i in range(tiles):
        upper = 0 if i == 0 else max(0, int(round(i * step)) - overlap // 2)
        lower = h if i == tiles - 1 else min(h, int(round((i + 1) * step)) + overlap // 2)
        bands.append(im.crop((0, upper, w, lower)))
    return bands


def prepare_tiles(
    data: bytes, *, tiles: int = 2, overlap_fraction: float = _TILE_OVERLAP_FRACTION
) -> list[tuple[bytes, str]]:
    """Crop a preprocessed scan into overlapping bands, each encoded under the
    per-image caps. Cropping happens on the full-resolution grayscale image so
    each band keeps native detail; the original scan is untouched (fidelity rule).
    """
    im = _preprocess(data)
    return [
        _encode(band, _TILE_MAX_EDGE, _TILE_MAX_PIXELS)
        for band in _horizontal_bands(im, tiles, overlap_fraction)
    ]


# The notation contract (v1.1) the model must transcribe TO. Kept verbatim-faithful:
# preserve layout, never "improve" the music, flag illegal marks rather than fix them.
# Split into fragments so the whole-page and band prompts share ONE copy of the
# notation + line-kind + rules text; only the intro, header/title, and output-format
# sections differ. A test asserts SYSTEM_PROMPT is byte-for-byte what it was before
# the split (PROMPT_VERSION is pinned), and that both prompts share the fragments.
_PROMPT_INTRO = (
    "You transcribe photographs of hand-written Sinhala sargam music sheets into "
    "Sargam Text Format (STF). You are precise and literal: you reproduce exactly what "
    "is on the paper, preserving its notation, punctuation, and line layout. You NEVER "
    '"improve", correct, or normalize the music.'
)

_NOTATION_CONTRACT = """\
## The notation (fixed-S sargam)

Notes are uppercase letters: S R G M P D N (never lowercase).
- Plain letter = natural.
- A dash UNDERNEATH a letter = flat. Only R, G, D, N are ever flat. Encode as a
  trailing underscore: R_ G_ D_ N_. This flat dash is SHORT and FAINT — often the
  lightest stroke on the note — and in these songs R and D are flatted VERY
  frequently, so inspect directly beneath every R and every D specifically. Do not
  read a note as natural just because its underline is light; only leave it natural
  when there is genuinely no dash. A curve arc under a GROUP and a flat dash under
  ONE letter live in the same space below the notes: after you identify a curve,
  still check each letter inside it for its own separate flat underline — the curve
  does not absorb them.
- A dash, tick, or "/" slash ON TOP of M = sharp. ONLY M is ever sharp, and in
  these songs M is sharpened VERY frequently, so inspect directly above every M.
  Encode as a trailing caret: M^. This sharp mark is a short LINEAR stroke — a
  dash, tick, or slanted slash — NOT a round dot. Do NOT read it as an
  upper-octave dot (M'): a mark above M that is a line, however short or slanted,
  is a sharp (M^); reserve M' for a mark above M that is a genuinely round,
  dot-like point. When a mark above an M could be either, prefer the sharp — M is
  sharpened far more often than it is octave-shifted, and a slash misread as a dot
  is the single most common error on these sheets.
- S and P NEVER take any accidental. M is never flat. If a mark looks like it
  violates these rules, prefer the legal reading; if you truly cannot, transcribe
  what you see and it will be flagged for review.

Octave dots (a dot is a ROUND point; an accidental — flat dash below, sharp tick
above M — is a LINE. This dot-vs-line call is the #1 confusion, look carefully):
- A DOT above a letter = upper octave: encode a trailing apostrophe, S'. But a
  LINEAR mark above M is a sharp (M^), not this octave dot — see the sharp rule.
- A DOT below a letter = lower octave: encode a trailing comma, S,
- No dot = middle octave.
- Marks combine in any order; a lower-octave flat Re is R_, (dash below + dot below).

Rhythm and structure, transcribed inline in the note text:
- A lone note = one beat (a quarter note in 4/4). A single un-held note is just the
  bare letter — do NOT append `-` to it and do NOT wrap it in a curve.
- `-`  after a note: hold the previous note ONE more beat. Only for a note genuinely
  sustained across beats (e.g. R - - - held four beats); never a trailing `-` on a
  single quarter note.
- `+`  a one-beat REST (silence). Distinct from `-`.
- `|`  a barline.
- `//` repeat the section.
- `( … )` a curve drawn under a group that shares one beat, e.g. (SRGM). These
  arcs are drawn in LIGHT pencil and are the faintest marks on the page — scan
  every note group for a curve under it and transcribe EVERY curve you see; never
  skip a group just because its arc is light. A whole sheet with no curves at all
  is almost always a miss. A curve holds two or more SLOTS — a slot is a note, a
  `-` (hold), or a `+` (rest). A slot BEFORE a note delays that note within the
  beat, so a curve may legitimately hold a single note: `(-G)` = the first half of
  the beat is silent/held and G lands on the half-beat. That is NOT the same as a
  plain `G` — KEEP `(-G)` verbatim, never collapse it. These leading-slot curves
  are the EASIEST to miss: the arc is short and sits low under a dash-then-note, so
  it reads like a plain hold. Whenever a hold `-` or rest `+` is joined to the
  following note by one arc (the arc's left end starts under the `-`/`+`), wrap them
  as a curve `(-G)` / `(+G)` — check every `-` or `+` that abuts a note for such an
  arc. (Only when the arc is genuinely there; a standalone hold before a note with
  no arc stays `- G`.) But `(G-)` (note on the
  beat, then held through it) equals a plain quarter note — write bare `G`. A curve
  over only holds/rests with NO note, e.g. `(--)`, is one sustained beat — collapse
  it to a single `-`. And a single note with NO slot — a bare `(S)`, or a
  flat-underline / octave-dot beneath ONE note — is an accidental/octave mark
  (encode R_ / S,) or a phantom curve, never a real curve: write the bare note.
- `[ … ]` a passage for another instrument / decoration. Keep it as-is."""

_HEADER_AND_TITLE = """\
## The header

Sheets carry the scale as a Concert/Alto pair (alto = concert + 9 semitones, e.g.
G concert = E alto) and often a beat like 4/4, 3/4, or 2/4. Capture concert_scale,
alto_scale, and beat. Order on paper varies (Alto-first or Concert-first) and a key
quality may be present ("C minor", "D maj"). If the beat/time signature is absent,
leave beat empty (do not guess). A private scale/mode reminder in the top-right
corner is NOT part of the copy — ignore it.

## The song title

If a song title is explicitly written as a heading at the top of the page, copy it
verbatim into the top-level `song_title` field. Do not infer a title from lyrics,
annotations, filenames, musical content, or outside knowledge. If no clear title is
written at the top, return an empty string."""

_LINE_KINDS_AND_RULES = """\
## Line kinds

Each line of the sheet becomes one STF line object with a `kind`:
- "section"    — an underlined heading (Intro, Chorus, Verse, Interlude), with any
                 repeat count like *4 kept in the text.
- "sargam"     — a barred line of notes (the normal case).
- "run"        — an UNBARRED line of notes (free-rhythm ad-lib); preserve the note
                 spacing verbatim.
- "lyric"      — Sinhala lyric fragments written under the notes. Capture them.
- "roadmap"    — a margin play-order list or jump arrows (→ Chorus).
- "annotation" — any other written note ("Intro only", bracketed remarks).

## Rules

- Transcribe TOP to BOTTOM, LEFT to RIGHT, one STF line per written line, in order.
- Preserve spacing and barlines faithfully — the digital copy must mirror the paper.
- Adjacent flats each have their own short dash even if they look merged: two flat
  letters, each with its own underscore, never one shared mark.
- Ignore non-notation content: pencil smudges, eraser marks, reverse-side
  bleed-through, and unrelated margin scribbles (even upside-down).
- If a token is genuinely unreadable, transcribe it as ⍰ so the reviewer can fix it.
- Output ONLY the JSON described below — no prose, no code fences."""

_OUTPUT_FORMAT_FULL = """\
## Output format (exact JSON)

{
  "song_title": "Written title, or empty",
  "header": {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"},
  "lines": [
    {"n": 1, "kind": "section", "text": "Intro"},
    {"n": 2, "kind": "sargam",  "text": "G - GG GG | -- RND | G - GG GGR - |"}
  ]
}

Use empty strings for header fields that are absent. Number lines from 1 in
top-to-bottom order."""

SYSTEM_PROMPT = (
    _PROMPT_INTRO
    + "\n\n"
    + _NOTATION_CONTRACT
    + "\n\n"
    + _HEADER_AND_TITLE
    + "\n\n"
    + _LINE_KINDS_AND_RULES
    + "\n\n"
    + _OUTPUT_FORMAT_FULL
    + "\n"
)

# Body-band prompt: same notation + line-kind + rules contract, but the band is
# only PART of a page — no header, no title, lines only. Header/title come solely
# from the top band in the tiled recognizer.
_BODY_INTRO = (
    "You transcribe ONE horizontal BAND cropped from a photograph of a hand-written "
    "Sinhala sargam music sheet into Sargam Text Format (STF) lines. You are precise and "
    "literal: you reproduce exactly what is on the paper, preserving its notation, "
    'punctuation, and line layout. You NEVER "improve", correct, or normalize the music. '
    "This band is only PART of a page: transcribe every note, lyric, and section line you "
    "can see, top to bottom. There is NO header (concert/alto/beat) and NO song title to "
    "capture in a band — output note lines only."
)

_OUTPUT_FORMAT_BODY = """\
## Output format (exact JSON)

{
  "lines": [
    {"n": 1, "kind": "section", "text": "Intro"},
    {"n": 2, "kind": "sargam",  "text": "G - GG GG | -- RND | G - GG GGR - |"}
  ]
}

Number lines from 1 in top-to-bottom order. Output ONLY this JSON object — no header,
no song_title, no prose, no code fences."""

SYSTEM_PROMPT_BODY = (
    _BODY_INTRO
    + "\n\n"
    + _NOTATION_CONTRACT
    + "\n\n"
    + _LINE_KINDS_AND_RULES
    + "\n\n"
    + _OUTPUT_FORMAT_BODY
    + "\n"
)

_USER_TEXT = (
    "Transcribe this hand-written sargam sheet to STF JSON, following the rules "
    "exactly. Output only the JSON object."
)
_BODY_USER_TEXT = (
    "Transcribe every note, lyric, and section line visible in this band to STF JSON "
    "lines, following the rules exactly. Output only the JSON object with a `lines` array."
)

# Structured outputs accept only a subset of JSON Schema: numeric constraints
# (minimum/maximum/multipleOf) and string constraints (minLength/maxLength) are
# rejected with a 400, which fails the whole recognition call before the image is
# ever read. Enforce those bounds in Python instead — the song title is clamped
# where it is stored. `_SCHEMA_UNSUPPORTED_KEYWORDS` guards this in tests.
_STF_LINE_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "kind": {
                "type": "string",
                "enum": list(STF_LINE_KINDS),
            },
            "text": {"type": "string"},
        },
        "required": ["n", "kind", "text"],
        "additionalProperties": False,
    },
}

STF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "song_title": {"type": "string"},
        "header": {
            "type": "object",
            "properties": {
                "concert_scale": {"type": "string"},
                "alto_scale": {"type": "string"},
                "beat": {"type": "string"},
            },
            "required": ["concert_scale", "alto_scale", "beat"],
            "additionalProperties": False,
        },
        "lines": _STF_LINE_ARRAY,
    },
    "required": ["song_title", "header", "lines"],
    "additionalProperties": False,
}

# Body bands return note lines only — no header, no song title.
STF_BODY_SCHEMA = {
    "type": "object",
    "properties": {"lines": _STF_LINE_ARRAY},
    "required": ["lines"],
    "additionalProperties": False,
}

# Keywords structured outputs reject. Adding one to STF_OUTPUT_SCHEMA breaks every
# recognition call with a 400 before the model sees the image, so a test asserts
# the schema stays clear of them.
_SCHEMA_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)


def _extract_json(text: str) -> dict:
    """Parse the model's reply into a dict, tolerating stray fences/prose."""
    text = text.strip()
    if text.startswith("```"):  # strip a ```json … ``` fence if present
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _build_client(api_key: str):
    """Construct the Anthropic client, deferring SDK import to first call so a
    missing key/SDK fails cleanly at use, not at import."""
    if not api_key:
        raise RecognitionUnavailable(
            "ANTHROPIC_API_KEY is not set — recognition is unavailable",
            code="configuration",
        )
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - depends on install
        raise RecognitionUnavailable(
            "the 'anthropic' package is not installed", code="dependency"
        ) from e

    # This machine's network intercepts TLS; Python's bundled CA can't verify
    # api.anthropic.com. Use the Windows trust store instead — the Python
    # counterpart of the `[tool.uv] system-certs = true` project setting.
    import truststore

    truststore.inject_into_ssl()
    return anthropic.Anthropic(api_key=api_key)


def _recognize_image(
    client,
    model: str,
    jpeg: bytes,
    media_type: str,
    *,
    system: str,
    schema: dict,
    user_text: str,
):
    """Send one image to the model and return (parsed_payload, response).

    Streams and assembles the final message: with a high max_tokens the SDK
    refuses a non-streaming call it estimates could outlive the HTTP timeout, and
    streaming keeps the connection active for the long run. Raises
    RecognitionUnavailable on a network error, truncation, refusal, or bad JSON.
    """
    import anthropic

    b64 = base64.standard_b64encode(jpeg).decode("ascii")
    try:
        with client.messages.stream(
            model=model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.AnthropicError as e:  # network/auth/rate-limit → clean 503
        raise RecognitionUnavailable(f"Claude API call failed: {e}", code="api_error") from e

    if resp.stop_reason == "max_tokens":
        raise RecognitionUnavailable(
            "recognition output was truncated; try a clearer crop or split the page",
            code="max_tokens",
        )
    if resp.stop_reason == "refusal":
        raise RecognitionUnavailable(
            "the recognition model declined this image",
            code="refusal",
        )

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        payload = _extract_json(text)
    except json.JSONDecodeError as e:
        raise RecognitionUnavailable(
            "model did not return valid STF JSON", code="invalid_json"
        ) from e
    return payload, resp


def make_recognizer(api_key: str, model: str) -> Recognizer:
    """Build the production whole-page recognizer."""

    def recognize(data: bytes, _content_type: str) -> RecognitionResult:
        client = _build_client(api_key)
        jpeg, media_type = prepare_image(data)
        payload, resp = _recognize_image(
            client,
            model,
            jpeg,
            media_type,
            system=SYSTEM_PROMPT,
            schema=STF_OUTPUT_SCHEMA,
            user_text=_USER_TEXT,
        )
        suggested_title = payload.pop("song_title", "")
        return RecognitionResult(
            stf=payload,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            suggested_title=suggested_title if isinstance(suggested_title, str) else None,
        )

    return recognize


def _normalize_line_text(text) -> str:
    """Whitespace-stripped text for comparing two recognitions of the same row."""
    return "".join(str(text).split())


def _lines_match(a: dict, b: dict) -> bool:
    """True if two STF lines are the same physical row seen in both bands."""
    if a.get("kind") != b.get("kind"):
        return False
    ta, tb = _normalize_line_text(a.get("text", "")), _normalize_line_text(b.get("text", ""))
    if not ta and not tb:
        return True
    return SequenceMatcher(a=ta, b=tb).ratio() >= _OVERLAP_SIMILARITY


def _overlap_length(top: list[dict], bottom: list[dict]) -> int:
    """Largest k where the last k lines of ``top`` match the first k of ``bottom``
    (the duplicated overlap region), or 0 if none."""
    for k in range(min(len(top), len(bottom)), 0, -1):
        if all(_lines_match(top[-k + i], bottom[i]) for i in range(k)):
            return k
    return 0


def stitch_tiles(header: dict, tile_lines: list[list[dict]]) -> dict:
    """Concatenate per-band line lists top→bottom, dropping the duplicated overlap
    between consecutive bands, and renumber `n` from 1. Header comes from the
    caller (the top band); this only assembles the body."""
    merged: list[dict] = []
    for lines in tile_lines:
        band = [dict(line) for line in lines]
        merged = merged + band[_overlap_length(merged, band) :]
    for i, line in enumerate(merged, start=1):
        line["n"] = i
    return {"header": dict(header), "lines": merged}


def make_tiled_recognizer(api_key: str, model: str, *, tiles: int = 2) -> Recognizer:
    """Phase 3.5 Rung 1 half-page recognizer — OFFLINE experiment variant.

    Splits the page into ``tiles`` overlapping bands, recognizes each at native
    detail (header/title from the top band only, body bands lines-only), and
    stitches the results with overlap dedup. Bands run sequentially (simplest;
    concurrency is deferred until a rung wins). NOT wired into the production
    ``recognize`` route — used by ``evaluate_recognition.py --tiled half``.

    A/B'd 2026-07-26 (n=6, fresh in-batch control + 2-run noise band) and
    **refuted**: no diacritic gain (accidental flat, octave worse), layout and
    curve regressed, total corrections and token accuracy both worse, at ~2× cost.
    The ladder was stopped (no Rung 2). Kept for reproducibility of that negative
    result, not as a path to adopt — see the vault decision
    ``saregamapic/decisions/2026-07-26-tiling-refuted``.
    """

    def recognize(data: bytes, _content_type: str) -> RecognitionResult:
        client = _build_client(api_key)
        bands = prepare_tiles(data, tiles=tiles)
        header = {"concert_scale": "", "alto_scale": "", "beat": ""}
        suggested_title: str | None = None
        tile_lines: list[list[dict]] = []
        input_tokens = output_tokens = 0
        used_model = model
        for index, (jpeg, media_type) in enumerate(bands):
            is_top = index == 0
            payload, resp = _recognize_image(
                client,
                model,
                jpeg,
                media_type,
                system=SYSTEM_PROMPT if is_top else SYSTEM_PROMPT_BODY,
                schema=STF_OUTPUT_SCHEMA if is_top else STF_BODY_SCHEMA,
                user_text=_USER_TEXT if is_top else _BODY_USER_TEXT,
            )
            if is_top:
                header = payload.get("header") or header
                title = payload.get("song_title", "")
                suggested_title = title if isinstance(title, str) else None
            tile_lines.append(payload.get("lines") or [])
            input_tokens += resp.usage.input_tokens
            output_tokens += resp.usage.output_tokens
            used_model = resp.model
        stitched = stitch_tiles(header, tile_lines)
        return RecognitionResult(
            stf=stitched,
            model=used_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            suggested_title=suggested_title or None,
        )

    return recognize


def read_scan_bytes(data_dir: Path, image_rel_path: str) -> bytes:
    """Read a stored original scan (read-only; never modified)."""
    return (data_dir / image_rel_path).read_bytes()
