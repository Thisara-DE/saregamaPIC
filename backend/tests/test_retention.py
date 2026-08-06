"""Startup retention prune (finding #5): stale sessions / idempotency / limit
events are removed, live ones survive.

Foreign keys are turned off on the test connection: this exercises the DELETE
predicates in isolation, so it need not build valid users/songs/scans rows for
every referenced id."""

import time

from app import db
from app.config import Settings
from app.retention import prune_expired


def _conn(tmp_path):
    settings = Settings(data_dir=tmp_path)
    db.migrate(settings.db_path)
    conn = db.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn, settings


def test_prunes_expired_and_revoked_sessions_but_keeps_a_live_one(tmp_path):
    conn, settings = _conn(tmp_path)
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, expires_at) VALUES ('live', 'u1', ?)",
        ("2999-01-01T00:00:00+00:00",),  # far future → kept
    )
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, expires_at) VALUES ('expired', 'u1', ?)",
        ("2000-01-01T00:00:00+00:00",),  # long past → pruned
    )
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, expires_at, revoked_at)"
        " VALUES ('revoked', 'u1', '2999-01-01T00:00:00+00:00', '2000-01-01T00:00:00.000Z')",
    )
    conn.commit()

    pruned = prune_expired(conn, settings)

    assert pruned["expired_sessions"] == 1
    assert pruned["revoked_sessions"] == 1
    survivors = {r["id_hash"] for r in conn.execute("SELECT id_hash FROM sessions")}
    assert survivors == {"live"}


def test_keeps_a_recently_revoked_session_within_the_grace_window(tmp_path):
    conn, settings = _conn(tmp_path)
    # Revoked "just now" — inside the 7-day retention, so kept for the audit trail.
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, expires_at, revoked_at)"
        " VALUES ('fresh', 'u1', '2999-01-01T00:00:00+00:00',"
        " strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
    )
    conn.commit()

    assert prune_expired(conn, settings)["revoked_sessions"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 1


def test_prunes_old_idempotency_rows_but_keeps_recent_ones(tmp_path):
    conn, settings = _conn(tmp_path)
    cols = "(user_id, idempotency_key, scan_id, status, created_at)"
    conn.execute(
        f"INSERT INTO recognition_idempotency {cols}"
        " VALUES ('u1', 'old', 's1', 'completed', '2000-01-01T00:00:00.000Z')",
    )
    conn.execute(
        f"INSERT INTO recognition_idempotency {cols}"
        " VALUES ('u1', 'new', 's1', 'started', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
    )
    conn.commit()

    assert prune_expired(conn, settings)["recognition_idempotency"] == 1
    keys = {
        r["idempotency_key"]
        for r in conn.execute("SELECT idempotency_key FROM recognition_idempotency")
    }
    assert keys == {"new"}


def test_prunes_stale_limit_events(tmp_path):
    conn, settings = _conn(tmp_path)
    now = int(time.time())
    insert = (
        "INSERT INTO security_limit_events (action, subject, occurred_at)"
        " VALUES ('login', 'ip', ?)"
    )
    conn.execute(insert, (now - 3 * 86400,))  # 3 days old → pruned (> 48h)
    conn.execute(insert, (now - 60,))  # a minute old → kept
    conn.commit()

    assert prune_expired(conn, settings)["security_limit_events"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM security_limit_events").fetchone()["n"] == 1
