"""Guard against the hand-mirrored API types drifting (finding #7).

`frontend/src/api/types.ts` mirrors `backend/app/schemas.py` by hand — a
deliberate choice while the API is small (no codegen toolchain). This test makes
that choice safe for the status enums, the fields most likely to drift silently.

It binds each backend `Literal` to the field(s) that must carry it, not just to
the file (finding #10): `PageStatus` must appear as a `status:` field union at
least twice (`Song.status` and `Scan.status`), and `TranscriptionStatus` must be
the declared union of the `TranscriptionStatus` type alias. Comments are stripped
first, so a union in prose can never satisfy the guard. Each union is anchored to
its `;` terminator (finding #15), so an ADDITIVE widening
(`"new" | "draft" | "reviewed" | string`, which TypeScript collapses to `string`)
fails too, not only a wholesale replacement."""

import re
from typing import get_args

from app.config import REPO_ROOT
from app.schemas import PageStatus, TranscriptionStatus

TYPES_TS = REPO_ROOT / "frontend" / "src" / "api" / "types.ts"


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # block comments
    text = re.sub(r"//[^\n]*", "", text)  # line comments
    return text


def _union_regex(literal: object) -> str:
    """A whitespace-tolerant regex for the TS string union of a backend Literal,
    values in declaration order (which the mirror keeps), anchored to its `;`
    terminator so an extra `| string` alternative after it does NOT match."""
    body = r"\s*\|\s*".join(re.escape(f'"{value}"') for value in get_args(literal))
    return body + r"\s*;"


def test_status_enums_are_field_bound_in_frontend_types():
    src = _strip_comments(TYPES_TS.read_text(encoding="utf-8"))

    # PageStatus is carried by BOTH Song.status and Scan.status, inline.
    page_sites = re.findall(r"status\s*:\s*" + _union_regex(PageStatus), src)
    assert len(page_sites) >= 2, (
        f"PageStatus {sorted(get_args(PageStatus))} must be a `status:` union at "
        f"Song.status AND Scan.status in {TYPES_TS.name}; found {len(page_sites)}. "
        "The hand-mirrored types have drifted (finding #7/#10/#15)."
    )

    # TranscriptionStatus is the declared union of its type alias.
    assert re.search(
        r"type\s+TranscriptionStatus\s*=\s*" + _union_regex(TranscriptionStatus),
        src,
    ), (
        f"`export type TranscriptionStatus` must be "
        f"{sorted(get_args(TranscriptionStatus))} in {TYPES_TS.name} — it has drifted."
    )
