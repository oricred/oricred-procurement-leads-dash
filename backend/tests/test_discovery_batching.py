"""The batched discovery pass must behave exactly like the per-tender one.

_process_tender used to issue four queries per tender — tender, organization,
watchlist, past-due — across up to 20,000 tenders every fifteen minutes, in one
session held open for the whole pass. It is now preloaded per chunk and
committed per chunk.

The danger in that change is the cache lying: a miss that means "not preloaded"
rather than "no such row" would insert a second watchlist item for a tender that
already has one, silently, on every pass. These tests exercise the cached path
directly and compare it against the uncached path that
test_discovery_sync.py covers.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs.discovery import _preload, _process_tender
from app.models.organization import Organization
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.services.award_timing import AwardTimingService
from app.services.qualification import FilterResult, QualificationService

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _raw(api_id: str, **overrides) -> dict:
    return {
        "tender_id": api_id,
        "title": f"Tender {api_id}",
        "estimated_value": 1_000_000,
        "province": "gp",
        "category_id": "construction",
        "closing_date": "2026-09-01T00:00:00+00:00",
        "source_organization_id": "ORG-1",
        "source_organization": "Buyer",
        "organization_type": "national",
        "publication_date": "2026-08-01T00:00:00+00:00",
        **overrides,
    }


@pytest.fixture
def qualify_everything(monkeypatch):
    async def always_pass(self, tender):
        return FilterResult(True)

    async def fixed_window(self, buyer_org_id, category_id, closing_date):
        return closing_date, closing_date + timedelta(days=30)

    monkeypatch.setattr(QualificationService, "evaluate", always_pass)
    monkeypatch.setattr(AwardTimingService, "get_expected_window", fixed_window)


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _run_chunk(sessions, chunk: list[dict], now: datetime) -> int:
    """One preload-process-commit chunk, as discover_new_tenders does it."""
    processed = 0
    async with sessions() as db:
        cache = await _preload(db, chunk)
        for raw in chunk:
            processed += await _process_tender(raw, db, now, None, cache)
        await db.commit()
    return processed


async def test_second_pass_does_not_duplicate_the_watchlist(sessions, qualify_everything):
    """The regression the cache could introduce: one watch per tender, not one per pass."""
    chunk = [_raw("T-1"), _raw("T-2")]

    await _run_chunk(sessions, chunk, NOW)
    await _run_chunk(sessions, chunk, NOW + timedelta(hours=1))
    await _run_chunk(sessions, chunk, NOW + timedelta(hours=2))

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tender)) == 2
        assert await db.scalar(select(func.count()).select_from(WatchlistItem)) == 2


async def test_a_repeated_api_id_within_one_chunk_reuses_the_row(sessions, qualify_everything):
    """Two rows for the same tender in one batch must not become two tenders."""
    await _run_chunk(sessions, [_raw("T-1"), _raw("T-1", title="Same tender again")], NOW)

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tender)) == 1
        assert await db.scalar(select(func.count()).select_from(WatchlistItem)) == 1
        tender = (await db.execute(select(Tender))).scalar_one()
        assert tender.title == "Same tender again"


async def test_tenders_sharing_a_buyer_create_one_organization(sessions, qualify_everything):
    await _run_chunk(sessions, [_raw("T-1"), _raw("T-2"), _raw("T-3")], NOW)

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Organization)) == 1


async def test_an_existing_tender_is_updated_not_reinserted(sessions, qualify_everything):
    await _run_chunk(sessions, [_raw("T-1")], NOW)
    await _run_chunk(
        sessions,
        [_raw("T-1", title="Updated title", closing_date="2026-09-15T00:00:00+00:00")],
        NOW + timedelta(hours=1),
    )

    async with sessions() as db:
        tender = (await db.execute(select(Tender))).scalar_one()
        assert tender.title == "Updated title"
        assert tender.closing_date.date().isoformat() == "2026-09-15"


async def test_a_tender_outside_the_preload_scope_still_finds_its_watch(
    sessions, qualify_everything
):
    """The `loaded_tender_ids` guard.

    A cache built for a different chunk must not let _qualify_and_watch conclude
    that this tender has no watchlist item. Without the guard this inserts a
    duplicate.
    """
    await _run_chunk(sessions, [_raw("T-1")], NOW)

    async with sessions() as db:
        # A cache that covers T-2 only, then process T-1 against it.
        cache = await _preload(db, [_raw("T-2")])
        assert not cache.loaded_tender_ids
        await _process_tender(_raw("T-1"), db, NOW + timedelta(hours=1), None, cache)
        await db.commit()

        assert await db.scalar(select(func.count()).select_from(WatchlistItem)) == 1


async def test_preload_returns_watches_of_every_status(sessions, qualify_everything):
    """Qualification reconciles awarded and unqualified watches, so it must see them."""
    await _run_chunk(sessions, [_raw("T-1")], NOW)

    async with sessions() as db:
        watch = (await db.execute(select(WatchlistItem))).scalar_one()
        watch.status = "awarded"
        await db.commit()

    async with sessions() as db:
        cache = await _preload(db, [_raw("T-1")])
        tender = (await db.execute(select(Tender))).scalar_one()
        assert cache.watches[tender.id].status == "awarded"


async def test_an_awarded_watch_is_left_alone_by_a_later_pass(sessions, qualify_everything):
    """Reconciliation must not walk an awarded tender back to watching."""
    await _run_chunk(sessions, [_raw("T-1")], NOW)

    async with sessions() as db:
        watch = (await db.execute(select(WatchlistItem))).scalar_one()
        watch.status = "awarded"
        await db.commit()

    await _run_chunk(sessions, [_raw("T-1")], NOW + timedelta(hours=1))

    async with sessions() as db:
        watch = (await db.execute(select(WatchlistItem))).scalar_one()
        assert watch.status == "awarded"


async def test_an_unchanged_payload_is_not_rewritten(sessions, qualify_everything):
    """The JSON column is the biggest on the row; an unchanged feed must not rewrite it."""
    await _run_chunk(sessions, [_raw("T-1")], NOW)

    async with sessions() as db:
        cache = await _preload(db, [_raw("T-1")])
        tender = cache.tenders["T-1"]
        await _process_tender(_raw("T-1"), db, NOW + timedelta(hours=1), None, cache)
        assert "raw_payload" not in db.dirty and tender not in db.dirty


async def test_past_due_row_is_created_once_across_passes(sessions, monkeypatch):
    """A window that closed in the past enqueues one past-due row, not one per pass."""

    async def always_pass(self, tender):
        return FilterResult(True)

    async def elapsed_window(self, buyer_org_id, category_id, closing_date):
        return NOW - timedelta(days=60), NOW - timedelta(days=30)

    monkeypatch.setattr(QualificationService, "evaluate", always_pass)
    monkeypatch.setattr(AwardTimingService, "get_expected_window", elapsed_window)

    await _run_chunk(sessions, [_raw("T-1")], NOW)
    await _run_chunk(sessions, [_raw("T-1")], NOW + timedelta(hours=1))

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PastDueQueue)) == 1
        watch = (await db.execute(select(WatchlistItem))).scalar_one()
        assert watch.status == "past_due"


async def test_chunk_boundaries_do_not_change_the_result(sessions, qualify_everything):
    """Processing in two chunks must equal processing in one."""
    await _run_chunk(sessions, [_raw("T-1"), _raw("T-2")], NOW)
    await _run_chunk(sessions, [_raw("T-3")], NOW)

    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tender)) == 3
        assert await db.scalar(select(func.count()).select_from(WatchlistItem)) == 3
        assert await db.scalar(select(func.count()).select_from(Organization)) == 1
