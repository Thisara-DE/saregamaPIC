"""Runtime configuration.

Settings are read from environment variables with sensible defaults so dev
needs zero setup. Tests build a Settings pointing at a temp dir and pass it
to create_app() — never mutate module globals.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/app/config.py -> repo root is two levels up
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

APP_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    # DATA_DIR holds the SQLite DB and the image store. Default <repo>/data:
    # gitignored, but inside Dropbox so it is backed up for free.
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("SAREGAMAPIC_DATA_DIR", str(REPO_ROOT / "data"))
    ))
    # Optional single-user bearer token. Empty (default) = no auth, fine for
    # LAN-only use. Set SAREGAMAPIC_API_TOKEN before exposing beyond the LAN.
    api_token: str = field(default_factory=lambda: os.environ.get("SAREGAMAPIC_API_TOKEN", ""))
    # Claude vision recognition (Phase 2). The key is read from the environment
    # and NEVER committed or written to the vault. Empty = recognition returns a
    # clean 503 until a key is exported.
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    recognition_model: str = field(
        default_factory=lambda: os.environ.get("SAREGAMAPIC_MODEL", "claude-opus-4-8")
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "saregamapic.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"
