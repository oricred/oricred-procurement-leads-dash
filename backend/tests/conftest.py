"""Shared test fixtures.

The ``tsa_stub`` fixture is the important one: it gives tests a ``TSADatabase``
that executes no SQL but records what would have been sent and returns queued
fixture rows. That makes the ingestion and enrichment paths testable without a
live Tenders-SA connection — see
``docs/specifications/remediation-07-engineering-hygiene.md`` section 6.
"""

from typing import Any

import pytest

from app.clients.tsa_db import TSADatabase


class _StubResult:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self) -> "_StubResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def scalar(self) -> Any:
        if not self._rows:
            return None
        return next(iter(self._rows[0].values()))


class _StubSession:
    def __init__(self, owner: "StubTSADatabase"):
        self._owner = owner

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _StubResult:
        sql = str(statement)
        self._owner.calls.append((sql, dict(params or {})))
        return _StubResult(self._owner.next_rows(sql))


class StubTSADatabase(TSADatabase):
    """A TSADatabase with no engine. Records SQL, returns queued rows.

    Queue rows per table name with ``queue()``; the table is matched against the
    ``FROM <table>`` in the generated SQL.
    """

    def __init__(self) -> None:  # deliberately does not call super().__init__
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[str, list[dict[str, Any]]] = {}
        self._session_factory = lambda: _StubSession(self)

    def queue(self, table: str, rows: list[dict[str, Any]]) -> "StubTSADatabase":
        self._responses[table] = rows
        return self

    def next_rows(self, sql: str) -> list[dict[str, Any]]:
        for table, rows in self._responses.items():
            if f"FROM {table}" in sql:
                return rows
        return []

    async def close(self) -> None:
        return None

    # ── assertions helpers ──

    @property
    def last_sql(self) -> str:
        return self.calls[-1][0]

    @property
    def last_params(self) -> dict[str, Any]:
        return self.calls[-1][1]


@pytest.fixture
def tsa_stub() -> StubTSADatabase:
    return StubTSADatabase()


@pytest.fixture
async def import_db(monkeypatch):
    """In-memory database for the lead contact import tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app.database as database

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
    yield session_factory
    await engine.dispose()
