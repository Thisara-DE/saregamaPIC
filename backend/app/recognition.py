"""Claude vision recognition: hand-written sargam photo -> STF draft.

The Anthropic client is built lazily and injected as a callable (``Recognizer``)
so the rest of the app — and every test — never imports the SDK or needs an API
key. ``make_recognizer(settings)`` returns the real one; tests pass a fake to
``create_app(recognizer=...)``.

Fidelity: the original scan is never modified. A downscaled, EXIF-corrected JPEG
*copy* is what we send to the model (below the fidelity boundary — the stored
original stays byte-identical).
"""

import base64
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

# A recognizer maps (original image bytes, content-type) -> a draft result.
Recognizer = Callable[[bytes, str], "RecognitionResult"]


@dataclass(frozen=True)
class RecognitionResult:
    stf: dict  # {"header": {...}, "lines": [...]}
    model: str
    input_tokens: int
    output_tokens: int


class RecognitionUnavailable(RuntimeError):
    """Raised when recognition can't run (no API key, SDK missing, or a bad
    model response). The route turns this into a clean 503 rather than a 500."""


# Long edge to downscale to before the vision call. Kept above the native long
# edge of a typical scan so full-page sheets pass through without losing the
# faint slur arcs; high enough that the dot-vs-dash (octave vs flat) distinction
# survives, low enough to bound cost.
_MAX_EDGE = 2600


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """EXIF-correct + contrast-boost + downscale a *copy* of the scan for the model.

    Phone photos store rotation in EXIF with pixels unrotated; the vision model
    sees raw pixels, so orientation must be baked in here (same reason as the
    thumbnail path).

    Faint pencil slur-arcs (curves) are the lightest strokes on the page and the
    first thing lost to downscale + JPEG — a curve-dropping recognition run is the
    classic failure. Flatten to grayscale (color carries no notation) and stretch
    contrast at full resolution so those arcs and flat underlines darken *before*
    the thumbnail averages them away. Returns (jpeg_bytes, media_type).
    """
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im = ImageOps.autocontrast(im, cutoff=1)
        im = ImageEnhance.Contrast(im).enhance(1.4)
        im.thumbnail((_MAX_EDGE, _MAX_EDGE))
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=95)
    return out.getvalue(), "image/jpeg"


# The notation contract (v1.1) the model must transcribe TO. Kept verbatim-faithful:
# preserve layout, never "improve" the music, flag illegal marks rather than fix them.
SYSTEM_PROMPT = """\
You transcribe photographs of hand-written Sinhala sargam music sheets into \
Sargam Text Format (STF). You are precise and literal: you reproduce exactly what \
is on the paper, preserving its notation, punctuation, and line layout. You NEVER \
"improve", correct, or normalize the music.

## The notation (fixed-S sargam)

Notes are uppercase letters: S R G M P D N (never lowercase).
- Plain letter = natural.
- A dash UNDERNEATH a letter = flat. Only R, G, D, N are ever flat. Encode as a
  trailing underscore: R_ G_ D_ N_.
- A dash/tick ON TOP of M = sharp. ONLY M is ever sharp. Encode as a trailing
  caret: M^.
- S and P NEVER take any accidental. M is never flat. If a mark looks like it
  violates these rules, prefer the legal reading; if you truly cannot, transcribe
  what you see and it will be flagged for review.

Octave dots (distinct from the flat DASH — this is the #1 confusion, look carefully):
- A DOT above a letter = upper octave: encode a trailing apostrophe, S'
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
  plain `G` — KEEP `(-G)` verbatim, never collapse it. But `(G-)` (note on the
  beat, then held through it) equals a plain quarter note — write bare `G`. A curve
  over only holds/rests with NO note, e.g. `(--)`, is one sustained beat — collapse
  it to a single `-`. And a single note with NO slot — a bare `(S)`, or a
  flat-underline / octave-dot beneath ONE note — is an accidental/octave mark
  (encode R_ / S,) or a phantom curve, never a real curve: write the bare note.
- `[ … ]` a passage for another instrument / decoration. Keep it as-is.

## The header

Sheets carry the scale as a Concert/Alto pair (alto = concert + 9 semitones, e.g.
G concert = E alto) and often a beat like 4/4, 3/4, or 2/4. Capture concert_scale,
alto_scale, and beat. Order on paper varies (Alto-first or Concert-first) and a key
quality may be present ("C minor", "D maj"). If the beat/time signature is absent,
leave beat empty (do not guess). A private scale/mode reminder in the top-right
corner is NOT part of the copy — ignore it.

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
- Output ONLY the JSON described below — no prose, no code fences.

## Output format (exact JSON)

{
  "header": {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"},
  "lines": [
    {"n": 1, "kind": "section", "text": "Intro"},
    {"n": 2, "kind": "sargam",  "text": "G - GG GG | -- RND | G - GG GGR - |"}
  ]
}

Use empty strings for header fields that are absent. Number lines from 1 in
top-to-bottom order.
"""

_USER_TEXT = (
    "Transcribe this hand-written sargam sheet to STF JSON, following the rules "
    "exactly. Output only the JSON object."
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


def make_recognizer(api_key: str, model: str) -> Recognizer:
    """Build the production recognizer. The SDK import and client construction
    are deferred to first call so a missing key/SDK fails cleanly at use, not
    at import."""

    def recognize(data: bytes, _content_type: str) -> RecognitionResult:
        if not api_key:
            raise RecognitionUnavailable(
                "ANTHROPIC_API_KEY is not set — recognition is unavailable"
            )
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - depends on install
            raise RecognitionUnavailable("the 'anthropic' package is not installed") from e

        # This machine's network intercepts TLS; Python's bundled CA can't verify
        # api.anthropic.com. Use the Windows trust store instead — the Python
        # counterpart of the `[tool.uv] system-certs = true` gotcha (see CLAUDE.md).
        import truststore

        truststore.inject_into_ssl()

        jpeg, media_type = prepare_image(data)
        b64 = base64.standard_b64encode(jpeg).decode("ascii")
        client = anthropic.Anthropic(api_key=api_key)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8000,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
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
                            {"type": "text", "text": _USER_TEXT},
                        ],
                    }
                ],
            )
        except anthropic.AnthropicError as e:  # network/auth/rate-limit → clean 503
            raise RecognitionUnavailable(f"Claude API call failed: {e}") from e

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            stf = _extract_json(text)
        except json.JSONDecodeError as e:
            raise RecognitionUnavailable("model did not return valid STF JSON") from e
        return RecognitionResult(
            stf=stf,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    return recognize


def read_scan_bytes(data_dir: Path, image_rel_path: str) -> bytes:
    """Read a stored original scan (read-only; never modified)."""
    return (data_dir / image_rel_path).read_bytes()
