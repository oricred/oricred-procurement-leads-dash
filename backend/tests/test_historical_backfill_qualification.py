from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs.historical_backfill import _process_award_chunk
from app.models.award import Award
from app.models.opportunity import Opportunity
from app.services.qualification import FilterResult, QualificationService


async def test_historical_award_is_stored_but_rejected_lead_is_not_created(monkeypatch):
    async def reject(self, tender, award, company):
        return FilterResult(False, "value_range", "Below minimum")

    monkeypatch.setattr(QualificationService, "evaluate_award_lead", reject)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    raw = {
        "id": "A-1",
        "tender_id": "T-UUID-1",
        "supplier_name": "Supplier",
        "amount": 100_000,
        "award_date": "2026-06-15",
        "created_at": "2026-06-20T00:00:00+00:00",
    }
    tender_metadata = {
        "id": "T-UUID-1",
        "tender_id": "T-1",
        "title": "Qualified business test",
        "publication_date": "2026-01-01T00:00:00+00:00",
        "closing_date": "2026-05-01T00:00:00+00:00",
    }

    async with sessions() as db:
        await _process_award_chunk(
            db,
            object(),
            [raw],
            {"T-UUID-1": tender_metadata},
            {},
            {},
            set(),
            now,
        )
        await db.commit()

        assert await db.scalar(select(func.count()).select_from(Award)) == 1
        assert await db.scalar(select(func.count()).select_from(Opportunity)) == 0

    await engine.dispose()
