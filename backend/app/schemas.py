"""API request/response models (pydantic). Keep in sync with frontend/src/api/types.ts."""

from pydantic import BaseModel, Field


class SongCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)


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


class SongDetail(Song):
    scans: list[Scan] = []


class Health(BaseModel):
    status: str
    version: str
