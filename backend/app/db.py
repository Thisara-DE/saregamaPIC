"""SQLite access + tiny migration runner.

Design choice (see vault decision 2026-07-17-phase-0-stack): plain sqlite3
with versioned .sql files instead of an ORM. The whole schema is readable in
app/migrations/, and adding a migration = adding NNN_name.sql. Applied
versions are tracked in schema_migrations.

Connections are per-request (FastAPI dependency), WAL mode so the uvicorn
worker and any ad-hoc CLI reads don't block each other.
"""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")


def connect(db_path: Path) -> sqlite3.Connection:
    # check_same_thread=False: the connection is created in async middleware
    # but used from FastAPI's sync-endpoint threadpool. Each connection serves
    # exactly one request sequentially, so cross-thread use is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(db_path: Path) -> None:
    """Apply any migrations in app/migrations/ not yet recorded."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
        )
        applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            m = _MIGRATION_RE.match(path.name)
            if not m:
                raise ValueError(f"Migration file name must be NNN_name.sql: {path.name}")
            version = int(m.group(1))
            if version in applied:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, path.name),
            )
            conn.commit()
    finally:
        conn.close()
