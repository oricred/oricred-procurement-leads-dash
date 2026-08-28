"""The SQL echo must stay off even when something outside this codebase turns it on.

Production emitted an `INFO sqlalchemy.engine.Engine` record for every statement
although `create_async_engine` was called with echo disabled and SQLAlchemy pins
its own logger to WARNING at import. Some external configuration — a uvicorn
`--log-config`, a `--log-level`, a stray `basicConfig()` — raised those loggers
afterwards. Discovery issues four to six statements per tender across up to
20,000 tenders every fifteen minutes, so the echo filled the disk.

These tests reproduce that external override and assert configure_logging()
defeats it, including when the level was set on the child logger directly, where
a WARNING on the parent would not have helped.
"""

import logging

import pytest
import structlog

from app.config import settings
from app.logging_config import _resolve_level, configure_logging

SQLALCHEMY_LOGGER_NAMES = (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool",
)


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging() mutates global state; put it back for other tests."""
    saved = {name: logging.getLogger(name).level for name in SQLALCHEMY_LOGGER_NAMES}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
    structlog.reset_defaults()


def _echo_is_on() -> bool:
    """Exactly the check SQLAlchemy makes before it formats a statement."""
    return logging.getLogger("sqlalchemy.engine.Engine").isEnabledFor(logging.INFO)


def test_external_info_level_is_overridden(monkeypatch):
    monkeypatch.setattr(settings, "sql_echo", False)
    logging.getLogger("sqlalchemy").setLevel(logging.INFO)
    assert _echo_is_on(), "precondition: the external override is in effect"

    configure_logging()

    assert not _echo_is_on()


def test_level_set_on_the_child_logger_is_also_cleared(monkeypatch):
    """A WARNING on `sqlalchemy` does not override a level set on the child."""
    monkeypatch.setattr(settings, "sql_echo", False)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.INFO)
    assert _echo_is_on()

    configure_logging()

    assert not _echo_is_on()


def test_pool_logger_is_quiet_too(monkeypatch):
    monkeypatch.setattr(settings, "sql_echo", False)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)

    configure_logging()

    assert not logging.getLogger("sqlalchemy.pool").isEnabledFor(logging.INFO)


def test_echo_can_still_be_turned_on_deliberately(monkeypatch):
    monkeypatch.setattr(settings, "sql_echo", True)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    configure_logging()

    assert _echo_is_on()


def test_structlog_filters_below_the_configured_level(monkeypatch):
    """The per-tender rejection line is debug, so INFO must drop it."""
    monkeypatch.setattr(settings, "log_level", "INFO")
    monkeypatch.setattr(settings, "sql_echo", False)

    configure_logging()

    assert not structlog.get_logger().is_enabled_for(logging.DEBUG)
    assert structlog.get_logger().is_enabled_for(logging.INFO)


def test_a_bad_log_level_does_not_stop_startup():
    assert _resolve_level("not-a-level") == logging.INFO
    assert _resolve_level("warning") == logging.WARNING
    assert _resolve_level(" debug ") == logging.DEBUG
