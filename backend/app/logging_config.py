"""Explicit logging configuration, applied once at application start.

Nothing in this application ever asked SQLAlchemy to echo statements —
`create_async_engine` is called with `echo=settings.sql_echo`, which defaults to
false, and SQLAlchemy itself pins its own `sqlalchemy` logger to WARNING at
import. Production still emitted an `INFO sqlalchemy.engine.Engine` record for
every statement, because *something outside this codebase* — a `--log-config`
passed to uvicorn, a `--log-level`, or a stray `logging.basicConfig()` — raised
those loggers to INFO after SQLAlchemy had set them.

The discovery job issues four to six statements per tender across up to 20,000
tenders every fifteen minutes. At roughly three journald lines per echoed
statement that is a six-figure line count per run, which is what filled the
disk and what the log pipeline was billed for.

So this module does not politely leave the loggers alone. It asserts the level
it wants, and clears any level set on a `sqlalchemy.*` child logger so an
inherited WARNING cannot be overridden by configuration this application does
not control. `configure_logging()` runs at import of `app.main`, which uvicorn
imports *after* it has configured logging, so this wins.

To turn statement logging back on for a short, deliberate investigation:

    ORICRED_SQL_ECHO=true

Leave it off otherwise. It is not a debugging convenience at this data volume;
it is an outage.
"""

import logging
import sys

import structlog

from app.config import settings

# Every logger tree SQLAlchemy emits under. `sqlalchemy.engine` carries the
# statement echo; `sqlalchemy.pool` carries per-connection checkout traffic,
# which is just as chatty under a job that opens a connection per loop.
SQLALCHEMY_LOGGERS = (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
    "sqlalchemy.orm",
)


def _resolve_level(name: str) -> int:
    """A bad ORICRED_LOG_LEVEL must not stop the service from starting."""
    level = logging.getLevelName(str(name).strip().upper())
    return level if isinstance(level, int) else logging.INFO


def _quiet_sqlalchemy(echo: bool) -> None:
    """Force the SQLAlchemy loggers to the level we intend.

    Clearing the level on every existing `sqlalchemy.*` child matters: an
    external dictConfig may have set `sqlalchemy.engine.Engine` directly, and a
    WARNING on the parent does not override a level set on the child.
    """
    target = logging.INFO if echo else logging.WARNING
    for name in SQLALCHEMY_LOGGERS:
        logging.getLogger(name).setLevel(target)
    if echo:
        return
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("sqlalchemy."):
            logging.getLogger(name).setLevel(logging.NOTSET)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def configure_logging() -> None:
    """Pin log levels and give structlog a real configuration.

    structlog was never configured, so it fell back to its defaults: no level
    filtering at all, and a console renderer that writes ANSI colour codes into
    journald where nothing interprets them.
    """
    level = _resolve_level(settings.log_level)

    _quiet_sqlalchemy(settings.sql_echo)

    renderer: structlog.types.Processor
    if settings.log_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        # Colour is for a terminal. Under systemd the escape sequences are
        # stored verbatim and every consumer has to strip them.
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )

    structlog.get_logger().info(
        "logging_configured",
        level=logging.getLevelName(level),
        sql_echo=settings.sql_echo,
        json=settings.log_json,
    )
