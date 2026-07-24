"""API request/response models (pydantic). Keep in sync with frontend/src/api/types.ts."""

from pydantic import BaseModel, Field, field_validator


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


class SongDetail(Song):
    scans: list[Scan] = []


class SongImport(BaseModel):
    song: Song
    scan: Scan


class Health(BaseModel):
    status: str
    version: str


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
    status: str  # draft | reviewed
    stf: Stf
    warnings: list[str] = []
    # Recognition cost metrics (None for a manually-typed transcription).
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    updated_at: str


class TranscriptionSave(BaseModel):
    stf: Stf
    status: str = Field(default="draft", pattern="^(draft|reviewed)$")


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
