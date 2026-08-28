"""Tender status, computed in SQL, against a real database.

Regression guard for the M1 defect: _compute_status_for_tender issued three
sequential SELECTs per row inside the result loop, so a 50-row page cost up to
151 round trips. The logic moved into the main query, and the existing endpoint
tests use mocked rows, so nothing would have caught a wrong CASE expression.

Precedence under test: opportunity > awarded > watching > past_due >
not_watched. is_watching is deliberately False for the opportunity and past_due
states even when a watchlist row exists — the Tenders page watch toggle relies
on it.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api.tenders import _status_columns
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
async def status_db():
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


async def _status_of(session_factory, tender_id: str):
    async with session_factory() as db:
        row = (
            await db.execute(
                select(Tender.id, *_status_columns()).where(Tender.id == tender_id)
            )
        ).one()
    return row.status, bool(row.is_watching), row.opportunity_id


async def _tender(session_factory, tender_id: str) -> None:
    async with session_factory() as db:
        db.add(Tender(
            id=tender_id, api_id=f"api-{tender_id}", title="T",
            raw_payload={}, discovered_at=NOW,
        ))
        await db.commit()


class TestStatusStates:
    async def test_not_watched(self, status_db):
        await _tender(status_db, "t1")
        assert await _status_of(status_db, "t1") == ("not_watched", False, None)

    async def test_watching(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(WatchlistItem(tender_id="t1", status="watching", started_watching_at=NOW))
            await db.commit()
        assert await _status_of(status_db, "t1") == ("watching", True, None)

    async def test_awarded(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(WatchlistItem(tender_id="t1", status="awarded", started_watching_at=NOW))
            await db.commit()
        assert await _status_of(status_db, "t1") == ("awarded", True, None)

    async def test_past_due(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(PastDueQueue(tender_id="t1", entered_queue_at=NOW))
            await db.commit()
        status, is_watching, opp_id = await _status_of(status_db, "t1")
        assert (status, is_watching, opp_id) == ("past_due", False, None)

    async def test_opportunity(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(Opportunity(id="o1", tender_id="t1", company_id="c1"))
            await db.commit()
        assert await _status_of(status_db, "t1") == ("opportunity", False, "o1")


class TestStatusPrecedence:
    async def test_opportunity_outranks_a_watchlist_row(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(WatchlistItem(tender_id="t1", status="watching", started_watching_at=NOW))
            db.add(Opportunity(id="o1", tender_id="t1", company_id="c1"))
            await db.commit()
        status, is_watching, opp_id = await _status_of(status_db, "t1")
        assert status == "opportunity"
        assert is_watching is False, "the watch toggle depends on this staying False"
        assert opp_id == "o1"

    async def test_past_due_outranks_nothing_but_beats_not_watched(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(PastDueQueue(tender_id="t1", entered_queue_at=NOW))
            db.add(WatchlistItem(tender_id="t1", status="past_due", started_watching_at=NOW))
            await db.commit()
        status, is_watching, _ = await _status_of(status_db, "t1")
        assert status == "past_due"
        assert is_watching is False

    async def test_an_opportunity_without_a_company_does_not_count(self, status_db):
        """The original helper required company_id IS NOT NULL."""
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(Opportunity(id="o1", tender_id="t1", company_id=None))
            await db.commit()
        status, _, opp_id = await _status_of(status_db, "t1")
        assert status == "not_watched"
        assert opp_id is None

    async def test_the_newest_opportunity_wins(self, status_db):
        await _tender(status_db, "t1")
        async with status_db() as db:
            db.add(Opportunity(
                id="old", tender_id="t1", company_id="c1",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
            db.add(Opportunity(
                id="new", tender_id="t1", company_id="c1",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            ))
            await db.commit()
        _, _, opp_id = await _status_of(status_db, "t1")
        assert opp_id == "new"


class TestQueryCount:
    async def test_status_costs_no_extra_queries(self, status_db):
        """The M1 regression stated directly: one query for the whole page."""
        for i in range(10):
            await _tender(status_db, f"t{i}")

        async with status_db() as db:
            statements = []
            original = db.execute

            async def counting(statement, *args, **kwargs):
                statements.append(statement)
                return await original(statement, *args, **kwargs)

            db.execute = counting
            rows = (await db.execute(select(Tender.id, *_status_columns()))).all()

        assert len(rows) == 10
        assert len(statements) == 1, f"expected one query, issued {len(statements)}"
