"""Startup retention pruning of the security bookkeeping tables (finding #5).

Sessions and recognition-idempotency rows are written on every login and every
recognition and are never otherwise removed, so both grow without bound. This is
the opportunistic-on-boot prune: cheap, no infrastructure, right-sized for a
single-user Railway app that redeploys often. The retention windows are
env-configurable (see config) precisely so a busy multi-user deployment can move
the same call onto a scheduled/cron job without code changes — that is the
recorded scaling path, not something this boot-time sweep pretends to be.

Each column stores its timestamp in a different format — `sessions.expires_at`
is Python ``datetime.isoformat()`` (``+00:00``), while ``revoked_at`` /
``created_at`` come from SQLite ``strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`` (``Z``).
The predicates below never compare the two formats against each other: the
isoformat column is compared to a Python isoformat ``now``, and the ``Z`` columns
to a SQLite-computed ``strftime`` cutoff in their own format.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime

from .config import Settings

logger = logging.getLogger("saregamapic")

# security_limit_events already self-prunes to 48h inside _limited on each check;
# this mirrors that window for the boot sweep (a process that never denies a
# request never runs that DELETE, so old rows can still linger between deploys).
_LIMIT_EVENT_RETENTION_SECONDS = 172_800


def prune_expired(conn: sqlite3.Connection, settings: Settings) -> dict[str, int]:
    """Delete stale sessions, idempotency keys, and limit events. Returns counts.

    Never raises on data; callers treat a failure as non-fatal (a prune that
    can't run must not stop the app from starting)."""
    # Clamp to at least a day: a misconfigured 0 would make the cutoff "now" and
    # delete rows for an in-flight recognition (a call finishes in ~a minute, far
    # inside any sane window).
    revoked_days = max(1, settings.session_revoked_retention_days)
    idempotency_days = max(1, settings.recognition_idempotency_retention_days)

    now_iso = datetime.now(UTC).isoformat()
    expired_sessions = conn.execute(
        "DELETE FROM sessions WHERE expires_at <= ?", (now_iso,)
    ).rowcount
    revoked_sessions = conn.execute(
        "DELETE FROM sessions WHERE revoked_at IS NOT NULL"
        " AND revoked_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)",
        (f"-{revoked_days} days",),
    ).rowcount
    recognition_idempotency = conn.execute(
        "DELETE FROM recognition_idempotency"
        " WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)",
        (f"-{idempotency_days} days",),
    ).rowcount
    security_limit_events = conn.execute(
        "DELETE FROM security_limit_events WHERE occurred_at < ?",
        (int(time.time()) - _LIMIT_EVENT_RETENTION_SECONDS,),
    ).rowcount
    conn.commit()

    pruned = {
        "expired_sessions": expired_sessions,
        "revoked_sessions": revoked_sessions,
        "recognition_idempotency": recognition_idempotency,
        "security_limit_events": security_limit_events,
    }
    if any(pruned.values()):
        logger.info("retention prune removed %s", pruned)
    return pruned
