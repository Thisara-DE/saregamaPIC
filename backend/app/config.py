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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # DATA_DIR holds the SQLite DB and image store. The default <repo>/data is
    # gitignored; deployed environments mount persistent storage separately.
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("SAREGAMAPIC_DATA_DIR", str(REPO_ROOT / "data"))
    ))
    # Phase 3.4 authentication. Local development remains zero-setup with auth
    # disabled; every remotely exposed environment must explicitly enable it.
    auth_enabled: bool = field(
        default_factory=lambda: _env_bool("SAREGAMAPIC_AUTH_ENABLED")
    )
    app_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "SAREGAMAPIC_APP_BASE_URL", "http://localhost:5173"
        ).rstrip("/")
    )
    google_client_id: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    )
    google_client_secret: str = field(
        default_factory=lambda: os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    )
    oauth_state_secret: str = field(
        default_factory=lambda: os.environ.get("SAREGAMAPIC_OAUTH_STATE_SECRET", "")
    )
    initial_owner_email: str = field(
        default_factory=lambda: os.environ.get("SAREGAMAPIC_INITIAL_OWNER_EMAIL", "")
    )
    session_days: int = field(
        default_factory=lambda: int(os.environ.get("SAREGAMAPIC_SESSION_DAYS", "30"))
    )
    login_limit_per_10_minutes: int = field(
        default_factory=lambda: int(os.environ.get("SAREGAMAPIC_LOGIN_LIMIT_10M", "20"))
    )
    upload_limit_per_minute: int = field(
        default_factory=lambda: int(os.environ.get("SAREGAMAPIC_UPLOAD_LIMIT_1M", "5"))
    )
    upload_quota_per_day: int = field(
        default_factory=lambda: int(os.environ.get("SAREGAMAPIC_UPLOAD_QUOTA_DAY", "100"))
    )
    recognition_limit_per_hour: int = field(
        default_factory=lambda: int(os.environ.get("SAREGAMAPIC_RECOGNITION_LIMIT_1H", "10"))
    )
    recognition_quota_per_day: int = field(
        default_factory=lambda: int(
            os.environ.get("SAREGAMAPIC_RECOGNITION_QUOTA_DAY", "30")
        )
    )
    destructive_limit_per_hour: int = field(
        default_factory=lambda: int(
            os.environ.get("SAREGAMAPIC_DESTRUCTIVE_LIMIT_1H", "100")
        )
    )
    # Claude vision recognition (Phase 2). The key is read from the environment
    # and never committed. Empty = recognition returns a
    # clean 503 until a key is exported.
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    recognition_model: str = field(
        default_factory=lambda: os.environ.get("SAREGAMAPIC_MODEL", "claude-opus-4-8")
    )
    # Production containers set this to the compiled React directory. Empty in
    # local Vite development and tests, where the frontend runs separately.
    web_dir: Path | None = field(default_factory=lambda: (
        Path(value) if (value := os.environ.get("SAREGAMAPIC_WEB_DIR", "")) else None
    ))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "saregamapic.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def secure_cookies(self) -> bool:
        return self.app_base_url.startswith("https://")

    def validate_auth(self) -> None:
        if not self.auth_enabled:
            return
        required = {
            "SAREGAMAPIC_APP_BASE_URL": self.app_base_url,
            "GOOGLE_OAUTH_CLIENT_ID": self.google_client_id,
            "GOOGLE_OAUTH_CLIENT_SECRET": self.google_client_secret,
            "SAREGAMAPIC_OAUTH_STATE_SECRET": self.oauth_state_secret,
            "SAREGAMAPIC_INITIAL_OWNER_EMAIL": self.initial_owner_email,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Authentication enabled but settings are missing: {', '.join(missing)}"
            )
        if self.session_days < 1 or self.session_days > 90:
            raise RuntimeError("SAREGAMAPIC_SESSION_DAYS must be between 1 and 90")
        limits = {
            "SAREGAMAPIC_LOGIN_LIMIT_10M": self.login_limit_per_10_minutes,
            "SAREGAMAPIC_UPLOAD_LIMIT_1M": self.upload_limit_per_minute,
            "SAREGAMAPIC_UPLOAD_QUOTA_DAY": self.upload_quota_per_day,
            "SAREGAMAPIC_RECOGNITION_LIMIT_1H": self.recognition_limit_per_hour,
            "SAREGAMAPIC_RECOGNITION_QUOTA_DAY": self.recognition_quota_per_day,
            "SAREGAMAPIC_DESTRUCTIVE_LIMIT_1H": self.destructive_limit_per_hour,
        }
        invalid = [name for name, value in limits.items() if value < 1]
        if invalid:
            raise RuntimeError(f"Security limits must be positive: {', '.join(invalid)}")
