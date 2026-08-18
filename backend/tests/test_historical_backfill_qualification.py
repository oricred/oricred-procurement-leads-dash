from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs.historical_backfill import (
    _process_award_chunk,
    requalify_existing_award_leads,
)
from app.models.company import Company
from app.models.opportunity import OpportunityAudit
from app.models.tender import Tender
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


async def test_existing_automatic_leads_are_requalified_but_manual_overrides_are_preserved(monkeypatch):
    async def reject(self, tender, award, company):
        return FilterResult(False, "value_range", "Below minimum")

    monkeypatch.setattr(QualificationService, "evaluate_award_lead", reject)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)

    async with sessions() as db:
        company = Company(api_id="C-1", name="Supplier")
        tender = Tender(
            api_id="T-1", raw_payload={}, title="Tender", discovered_at=now,
        )
        db.add_all([company, tender])
        await db.flush()
        automatic_award = Award(
            tender_id=tender.id, supplier_name=company.name,
            supplier_company_id=company.api_id, amount=100_000,
            award_date=now, discovered_at=now,
        )
        manual_award = Award(
            tender_id=tender.id, supplier_name=company.name,
            supplier_company_id=company.api_id, amount=100_000,
            award_date=now, discovered_at=now,
        )
        db.add_all([automatic_award, manual_award])
        await db.flush()
        automatic = Opportunity(
            tender_id=tender.id, award_id=automatic_award.id,
            company_id=company.id, lead_origin="automatic",
        )
        manual = Opportunity(
            tender_id=tender.id, award_id=manual_award.id,
            company_id=company.id, lead_origin="manual",
        )
        db.add_all([automatic, manual])
        await db.flush()

        result = await requalify_existing_award_leads(db)
        await db.commit()

        assert result == {"checked": 1, "passed": 0, "closed": 1, "flagged": 0, "skipped": 0}
        assert automatic.kanban_stage == "lost_lead"
        assert automatic.lost_reason.startswith("Automatic requalification:")
        assert manual.kanban_stage == "new_lead"
        assert await db.scalar(select(func.count()).select_from(OpportunityAudit)) == 1

    await engine.dispose()
