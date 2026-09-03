"""Shared router helpers.

Small ownership-scoped queries used by more than one router live here so they
have a single definition (the #6 one-definition rule). Import-light: this module
pulls in only ``fastapi`` + ``..auth`` so any router can depend on it without a
circular import.
"""

import sqlite3

from fastapi import HTTPException, Request

from ..auth import current_user_id


def scan_row(request: Request, scan_id: str) -> sqlite3.Row:
    """The scan's id/song_id/image_path/content_type, 404 unless the caller owns it.

    The ``JOIN songs … owner_id = ?`` is the ownership gate: another user's scan
    id is indistinguishable from a nonexistent one (no existence oracle).
    """
    row = request.state.db.execute(
        "SELECT sc.id, sc.song_id, sc.image_path, sc.content_type"
        " FROM scans sc JOIN songs so ON so.id = sc.song_id"
        " WHERE sc.id = ? AND so.owner_id = ?",
        (scan_id, current_user_id(request)),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return row
