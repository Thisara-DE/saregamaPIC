"""Proves security-event logging actually reaches a handler.

Before this fix, uvicorn's default logging config left the root logger with no
handlers and an effective level of WARNING, so every `security_event` INFO
record (login, uninvited-account attempt, rate-limit denial, deletion,
recognition) was silently discarded in the deployed container — verified with
`logging.getLogger("saregamapic.security")` resolving to `handlers: []` and
`effective level: 30`. A test that only checks a config dict exists would not
have caught that; these instead prove records are actually emitted.
"""

import json
import logging

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class _Capture(logging.Handler):
    """Collects records directly, sidestepping pytest's caplog/propagate
    interaction with our deliberately non-propagating logger (see
    `configure_logging`'s docstring) so this test doesn't depend on other
    tests having already run first in the session."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _owned_handlers() -> list[logging.Handler]:
    """Only the handler `configure_logging` installed, filtering out whatever
    pytest's own log-capture plugin attaches. Because our logger is
    deliberately non-propagating (see `configure_logging`), pytest's
    `catching_logs` treats it like a second root and attaches its own
    LogCaptureHandler/_FileHandler/etc. directly to it too — real handlers
    that must not be mistaken for accumulation bugs of ours."""
    return [
        h
        for h in logging.getLogger("saregamapic").handlers
        if getattr(h, "_saregamapic_owned", False)
    ]


def test_saregamapic_logger_resolves_to_a_configured_handler(tmp_path):
    create_app(Settings(data_dir=tmp_path / "data"))
    logger = logging.getLogger("saregamapic.security")
    assert logger.getEffectiveLevel() <= logging.INFO
    handlers = _owned_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)


def test_configure_logging_is_idempotent_across_repeated_create_app_calls(tmp_path):
    """create_app() runs once per test across dozens of tests in one pytest
    session on the same process; a naive `addHandler` would accumulate one
    handler per call and multiply every log line by the test count."""
    settings = Settings(data_dir=tmp_path / "data")
    create_app(settings)
    create_app(settings)
    create_app(settings)
    assert len(_owned_handlers()) == 1


def test_log_level_is_configurable_and_defaults_to_info(tmp_path):
    assert Settings(data_dir=tmp_path / "data").log_level == "INFO"
    create_app(Settings(data_dir=tmp_path / "data", log_level="WARNING"))
    assert logging.getLogger("saregamapic").getEffectiveLevel() == logging.WARNING
    # Restore INFO: this logger is process-global, and other tests in this
    # session assert on INFO-level security events being captured.
    create_app(Settings(data_dir=tmp_path / "data", log_level="INFO"))


def test_security_event_emits_a_record_during_a_real_request(tmp_path):
    """Drives an actual endpoint that calls `security_event` (song deletion) and
    proves a record reaches a handler on "saregamapic.security" — not just that
    the logger is configured, but that a real request produces output."""
    settings = Settings(data_dir=tmp_path / "data")
    capture = _Capture()
    logger = logging.getLogger("saregamapic.security")
    logger.addHandler(capture)
    try:
        with TestClient(create_app(settings)) as client:
            song_id = client.post("/api/songs", json={"title": "Log test"}).json()["id"]
            assert client.delete(f"/api/songs/{song_id}").status_code == 204
    finally:
        logger.removeHandler(capture)

    events = [json.loads(r.getMessage()) for r in capture.records]
    assert any(e["event"] == "song_delete" and e["outcome"] == "succeeded" for e in events)


def test_ephemeral_data_dir_warning_reaches_a_handler_not_only_last_resort(tmp_path):
    """The other half of the fix: main.py's plain `logger.error` on the parent
    "saregamapic" logger must also come through the same handler, formatted,
    instead of only reaching stderr via `logging.lastResort`."""
    create_app(Settings(data_dir=tmp_path / "data"))  # ensure configure_logging ran
    capture = _Capture()
    logger = logging.getLogger("saregamapic")
    logger.addHandler(capture)
    try:
        logger.error("test message: %s", "unmounted /data")
    finally:
        logger.removeHandler(capture)
    assert any("unmounted /data" in r.getMessage() for r in capture.records)
    # Confirm the record was also formatted by our handler — not pytest's own
    # capture handler, which `logger.handlers[0]` is not guaranteed to avoid
    # (see `_owned_handlers`'s docstring above).
    formatted = _owned_handlers()[0].format(capture.records[-1])
    assert "ERROR" in formatted and "saregamapic" in formatted
