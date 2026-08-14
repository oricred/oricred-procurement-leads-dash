from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs.discovery import _process_tender
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.services.qualification import FilterResult, QualificationService
from app.services.award_timing import AwardTimingService


async def test_existing_tender_is_updated_and_watchlist_is_not_duplicated(monkeypatch):
    async def always_pass(self, tender):
        return FilterResult(True)

    async def fixed_window(self, buyer_org_id, category_id, closing_date):
        return closing_date, closing_date + timedelta(days=30)

    monkeypatch.setattr(QualificationService, "evaluate", always_pass)
    monkeypatch.setattr(AwardTimingService, "get_expected_window", fixed_window)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    first = {
        "tender_id": "T-1",
        "title": "Original title",
        "estimated_value": 1_000_000,
        "province": "gp",
        "category_id": "construction",
        "closing_date": "2026-09-01T00:00:00+00:00",
        "source_organization_id": "ORG-1",
        "source_organization": "Buyer",
        "organization_type": "national",
        "publication_date": "2026-08-01T00:00:00+00:00",
    }
    updated = {**first, "title": "Updated title", "closing_date": "2026-09-15T00:00:00+00:00"}

    async with sessions() as db:
        await _process_tender(first, db, now)
        await db.commit()
        await _process_tender(updated, db, now + timedelta(hours=1))
        await db.commit()

        tender = (await db.execute(select(Tender).where(Tender.api_id == "T-1"))).scalar_one()
        watch_count = await db.scalar(select(func.count()).select_from(WatchlistItem))
        assert tender.title == "Updated title"
        assert tender.closing_date.date().isoformat() == "2026-09-15"
        assert watch_count == 1

    await engine.dispose()
