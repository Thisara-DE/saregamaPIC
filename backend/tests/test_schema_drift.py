"""Guard against the hand-mirrored API types drifting (finding #7).

`frontend/src/api/types.ts` mirrors `backend/app/schemas.py` by hand — a
deliberate choice while the API is small (no codegen toolchain). This test makes
that choice safe for the status enums, which are the fields most likely to drift
silently: it fails CI if a backend `Literal` set is not present verbatim as a
string union in types.ts. It is one-directional (backend ⊆ frontend) — a backend
status value with no matching TS union is the dangerous case, since the frontend
would then receive a value its type says is impossible."""

import re
from typing import get_args

from app.config import REPO_ROOT
from app.schemas import PageStatus, TranscriptionStatus

TYPES_TS = REPO_ROOT / "frontend" / "src" / "api" / "types.ts"


def _ts_string_unions(text: str) -> list[frozenset[str]]:
    """Every `"a" | "b" | ...` string-literal union in the TypeScript source, as
    value sets (order- and whitespace-independent)."""
    unions: list[frozenset[str]] = []
    for match in re.finditer(r'"[^"]+"(?:\s*\|\s*"[^"]+")+', text):
        unions.append(frozenset(re.findall(r'"([^"]+)"', match.group())))
    return unions


def test_status_enums_are_mirrored_in_frontend_types():
    unions = _ts_string_unions(TYPES_TS.read_text(encoding="utf-8"))
    for literal in (PageStatus, TranscriptionStatus):
        want = frozenset(get_args(literal))
        assert want in unions, (
            f"backend status set {sorted(want)} has no matching string union in "
            f"{TYPES_TS.name} — the hand-mirrored types have drifted (finding #7)"
        )
