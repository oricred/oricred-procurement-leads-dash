from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.award import Award
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.services.buyer_relationship import _compute_relevance, compute_relationship


class TestComputeRelevance:

    def test_no_awards_returns_low(self):
        score = _compute_relevance(0, 0, None)
        assert score == 0.0

    def test_awards_contribute(self):
        score = _compute_relevance(5, 10_000_000, None)
        assert 0 < score <= 100

    def test_value_contributes(self):
        low_val = _compute_relevance(2, 1_000_000, None)
        high_val = _compute_relevance(2, 40_000_000, None)
        assert high_val > low_val

    def test_win_rate_contributes(self):
        no_win = _compute_relevance(5, 10_000_000, 0.0)
        high_win = _compute_relevance(5, 10_000_000, 1.0)
        assert high_win > no_win

    def test_perfect_score(self):
        score = _compute_relevance(10, 50_000_000, 1.0)
        assert score == 100.0

    def test_score_capped_at_100(self):
        score = _compute_relevance(100, 500_000_000, 1.0)
        assert score <= 100.0


async def test_relationship_is_scoped_to_supplier_and_buyer():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    async with sessions() as db:
        company = Company(api_id="C-1", name="Target supplier")
        other_company = Company(api_id="C-2", name="Other supplier")
        buyer_tender = Tender(
            api_id="T-1", raw_payload={}, title="Buyer one", buyer_org_id="ORG-1",
            discovered_at=now,
        )
        other_buyer_tender = Tender(
            api_id="T-2", raw_payload={}, title="Buyer two", buyer_org_id="ORG-2",
            discovered_at=now,
        )
        db.add_all([company, other_company, buyer_tender, other_buyer_tender])
        await db.flush()

        db.add_all([
            Award(
                tender_id=buyer_tender.id, supplier_name=company.name,
                supplier_company_id=company.api_id, amount=10_000_000,
                award_date=now, discovered_at=now,
            ),
            Award(
                tender_id=buyer_tender.id, supplier_name=other_company.name,
                supplier_company_id=other_company.api_id, amount=40_000_000,
                award_date=now, discovered_at=now,
            ),
            Opportunity(
                tender_id=buyer_tender.id, company_id=company.id,
                kanban_stage="funded",
            ),
            Opportunity(
                tender_id=other_buyer_tender.id, company_id=company.id,
                kanban_stage="lost_lead",
            ),
        ])
        await db.flush()

        relationship = await compute_relationship(company.id, "ORG-1", db)
        assert relationship.award_count_12m == 1
        assert float(relationship.total_award_value_12m) == 10_000_000
        assert float(relationship.win_rate) == 1.0

    await engine.dispose()
