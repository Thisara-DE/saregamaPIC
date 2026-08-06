"""API request/response models (pydantic). Keep in sync with frontend/src/api/types.ts."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .stf import STF_LINE_KINDS

# Status enums, typed as Literal rather than bare `str` (finding #7): a stray
# value from a query is then caught at serialization instead of silently reaching
# the client, and the allowed set becomes a real OpenAPI enum. These are
# hand-mirrored in frontend/src/api/types.ts; tests/test_schema_drift.py fails if
# the two ever disagree.
PageStatus = Literal["new", "draft", "reviewed"]  # gallery/song + per-page pill
TranscriptionStatus = Literal["draft", "reviewed"]  # a transcription is one or the other


class SongCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)


class SongUpdate(BaseModel):
    """Rename an existing song.

    A blank title is rejected: an untitled song that recognition never named has
    no other way back to a real name, and silently accepting "" would strand it
    again.
    """

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _strip(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be blank")
        return title


class Scan(BaseModel):
    id: str
    song_id: str
    page_no: int
    content_type: str
    uploaded_at: str
    # This page's transcription status: "new" (not recognized), "draft", or
    # "reviewed". A freshly uploaded scan has no transcription yet, so "new".
    status: PageStatus = "new"


class Song(BaseModel):
    id: str
    title: str
    notes: str
    created_at: str
    scan_count: int = 0
    # First page's scan id (None when the song has no pages yet) — the
    # gallery uses it to show a cover thumbnail without fetching details.
    cover_scan_id: str | None = None
    # First page that has a transcription (None when nothing is transcribed yet).
    # Lets the gallery link straight to the digital view, and disable that link,
    # without fetching every page's transcription.
    digital_page_no: int | None = None
    # Gallery progress pill: "new" (nothing transcribed), "draft" (at least one
    # page is a draft), or "reviewed" (every page reviewed — shown as no pill).
    status: PageStatus = "new"


class SongDetail(Song):
    scans: list[Scan] = []


class SongImport(BaseModel):
    song: Song
    scan: Scan


class Health(BaseModel):
    status: str
    version: str


# --- Per-line photo bands (editor auto-scroll, finding #11) ---
# Computed on demand from the scan image, never stored: a band is a pure function
# of the pixels, so there's no schema/STF change and no re-recognition. Both
# coordinates are normalized to [0, 1] of image height, so they map onto whatever
# downscaled copy the editor renders. Mirror in frontend/src/api/types.ts by hand.


class LineBand(BaseModel):
    y0: float  # normalized top of a written row
    y1: float  # normalized bottom


class LineBands(BaseModel):
    bands: list[LineBand] = []


# --- Transcriptions (STF) — mirror in frontend/src/api/types.ts by hand ---


class StfHeader(BaseModel):
    concert_scale: str = ""
    alto_scale: str = ""
    beat: str = ""


class StfLine(BaseModel):
    n: int
    kind: str  # section | sargam | run | lyric | roadmap | annotation
    text: str


class Stf(BaseModel):
    header: StfHeader = Field(default_factory=StfHeader)
    lines: list[StfLine] = Field(default_factory=list)


class Transcription(BaseModel):
    id: str
    scan_id: str
    status: TranscriptionStatus
    stf: Stf
    warnings: list[str] = []
    # Recognition cost metrics (None for a manually-typed transcription).
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    updated_at: str


# --- Inbound-only bounds for saving a transcription -------------------------
# `Stf`/`StfLine` above stay permissive because `Transcription.stf` also uses
# them for the GET response: bounding the shared model would mean a row saved
# before these limits existed (or, before they existed, in a deployed database)
# could exceed them and turn a page GET into a 500 instead of a readable page.
# So the limits below apply ONLY to writes, via this separate `...In` set of
# models used exclusively by `TranscriptionSave`.
#
# Real hand-written sheet lines run well under 500 chars and real sheets run
# well under a few hundred lines (see the vault technical design doc); these
# caps are generous multiples of that so no legitimate correction is ever
# rejected, while still keeping one PUT bounded to a sane size on disk.
_STF_LINE_TEXT_MAX = 2000
_STF_LINES_MAX = 1000
_STF_HEADER_FIELD_MAX = 200


class StfHeaderIn(BaseModel):
    concert_scale: str = Field(default="", max_length=_STF_HEADER_FIELD_MAX)
    alto_scale: str = Field(default="", max_length=_STF_HEADER_FIELD_MAX)
    beat: str = Field(default="", max_length=_STF_HEADER_FIELD_MAX)


class StfLineIn(BaseModel):
    # `kind` was the actual hole in the first pass at this fix: a max_length on
    # `text` alone left `kind` free to carry the same abuse (a 100k-char `kind`
    # on each of 1000 lines reproduced the original disk-fill report through a
    # different field). Constraining it to the legal set — built from
    # `stf.STF_LINE_KINDS`, not retyped here — closes that and also
    # turns it into a real OpenAPI enum, which matters because
    # frontend/src/api/types.ts mirrors this by hand.
    kind: Literal[STF_LINE_KINDS]
    # No natural sheet has anywhere near this many lines (STF_LINES_MAX below
    # caps the array at 1000); the bound mainly guards against a pathological
    # bignum literal rather than any real numbering scheme.
    n: int = Field(ge=0, le=10_000)
    text: str = Field(max_length=_STF_LINE_TEXT_MAX)


class StfIn(BaseModel):
    header: StfHeaderIn = Field(default_factory=StfHeaderIn)
    lines: list[StfLineIn] = Field(default_factory=list, max_length=_STF_LINES_MAX)


class TranscriptionSave(BaseModel):
    stf: StfIn
    status: TranscriptionStatus = "draft"


# --- Recognition baseline (Phase 3.5) ---
# Aggregate counts only: no STF, no token text, no image data ever appears here.


class SymbolCorrections(BaseModel):
    category: str  # letter | accidental | octave | curve | rhythm | barline | ...
    corrected_tokens: int
    share_of_all_corrections: float
    per_1000_tokens: float | None = None
    sheets_affected: int


class SheetMetrics(BaseModel):
    sheet: int
    token_accuracy: float
    line_accuracy: float
    changed_tokens: int
    categories: dict[str, int] = {}


class RecognitionBaseline(BaseModel):
    reviewed_sheet_count: int
    baseline_ready: bool
    sheets_needed: int
    exact_sheet_matches: int
    mean_token_accuracy: float | None = None
    mean_line_accuracy: float | None = None
    corrections_by_symbol: list[SymbolCorrections] = []
    per_sheet: list[SheetMetrics] = []
    total_input_tokens: int
    total_output_tokens: int
    mean_latency_ms: float | None = None
