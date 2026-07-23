"""Abuse controls and privacy-safe security event logging."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import NoReturn

from fastapi import HTTPException, Request

logger = logging.getLogger("saregamapic.security")


def client_ip(request: Request) -> str:
    """Return the peer address as normalized by the ASGI server."""
    return request.client.host if request.client is not None else "unknown"


def security_event(
    request: Request,
    action: str,
    outcome: str,
    *,
    user_id: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Log identifiers and outcomes only—never tokens, images, STF, or emails."""
    event = {
        "event": action,
        "outcome": outcome,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "user_id": user_id,
        "resource_id": resource_id,
        "client_ip": client_ip(request),
    }
    logger.info("%s", json.dumps(event, separators=(",", ":"), sort_keys=True))


def upstream_failure(
    request: Request,
    action: str,
    code: str,
    detail: str,
    *,
    user_id: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Log an upstream provider failure verbatim, server-side only.

    Deliberately separate from `security_event`, which promises to carry
    identifiers only. `detail` is third-party error text, so this never goes to
    a client: the route returns a safe mapped message and the diagnosis lives
    here, in the deployment's logs. Never pass user content (STF, images,
    emails) — only the provider's own message.
    """
    event = {
        "event": action,
        "outcome": "failed",
        "error_code": code,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "user_id": user_id,
        "resource_id": resource_id,
    }
    logger.warning("%s", json.dumps(event, separators=(",", ":"), sort_keys=True))


def _limited(
    conn: sqlite3.Connection,
    *,
    action: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> bool:
    if limit < 1:
        return True
    now = int(time.time())
    cutoff = now - window_seconds
    conn.execute(
        "DELETE FROM security_limit_events WHERE occurred_at < ?",
        (now - 172_800,),
    )
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM security_limit_events"
        " WHERE action = ? AND subject = ? AND occurred_at > ?",
        (action, subject, cutoff),
    ).fetchone()["n"]
    if count >= limit:
        conn.commit()
        return True
    conn.execute(
        "INSERT INTO security_limit_events (action, subject, occurred_at)"
        " VALUES (?, ?, ?)",
        (action, subject, now),
    )
    conn.commit()
    return False


def enforce_limit(
    request: Request,
    *,
    action: str,
    subject: str,
    limit: int,
    window_seconds: int,
    detail: str = "Too many requests; try again later",
) -> None:
    if not _limited(
        request.state.db,
        action=action,
        subject=subject,
        limit=limit,
        window_seconds=window_seconds,
    ):
        return
    security_event(
        request,
        "rate_limit",
        "denied",
        user_id=getattr(request.state, "user_id", None),
    )
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(window_seconds)},
    )


def reject_idempotency(detail: str) -> NoReturn:
    raise HTTPException(status_code=409, detail=detail)
