from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_relationship import BuyerRelationship
from app.models.award import Award
from app.models.opportunity import Opportunity, OpportunityAudit
from app.models.tender import Tender


async def compute_relationship(
    company_id: str,
    organization_id: str,
    db: AsyncSession,
) -> BuyerRelationship:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    award_counts = await db.execute(
        select(
            func.count(Award.id),
            func.coalesce(func.sum(Award.amount), 0),
        )
        .select_from(Award)
        .join(Tender, Tender.id == Award.tender_id)
        .where(Tender.buyer_org_id == organization_id)
        .where(Award.supplier_company_id.isnot(None))
        .where(Award.award_date >= cutoff)
    )
    award_count, total_value = award_counts.one()
    award_count = award_count or 0
    total_value = total_value or 0

    response_times = await db.execute(
        select(
            func.avg(
                func.extract("epoch", OpportunityAudit.changed_at - Award.award_date) / 86400
            )
        )
        .select_from(OpportunityAudit)
        .join(Opportunity, Opportunity.id == OpportunityAudit.opportunity_id)
        .join(Award, Award.id == Opportunity.award_id)
        .where(Opportunity.company_id == company_id)
        .where(Award.buyer_org_id == organization_id)
        .where(OpportunityAudit.from_stage == "new")
        .where(OpportunityAudit.to_stage == "contacted")
    )
    avg_response = response_times.scalar()

    win_data = await db.execute(
        select(
            func.count(Opportunity.id).filter(Opportunity.kanban_stage == "funded"),
            func.count(Opportunity.id),
        )
        .where(Opportunity.company_id == company_id)
        .where(Opportunity.tender_id.isnot(None))
    )
    funded_count, total_opps = win_data.one()
    win_rate = (funded_count / total_opps) if total_opps > 0 else None

    result = await db.execute(
        select(BuyerRelationship).where(
            BuyerRelationship.company_id == company_id,
            BuyerRelationship.organization_id == organization_id,
        )
    )
    rel = result.scalar_one_or_none()

    relevance = _compute_relevance(award_count, float(total_value), win_rate)

    if rel:
        rel.award_count_12m = award_count
        rel.total_award_value_12m = float(total_value) if total_value else None
        rel.avg_response_days = float(avg_response) if avg_response else None
        rel.win_rate = float(win_rate) if win_rate else None
        rel.relevance_score = relevance
        rel.updated_at = datetime.now(timezone.utc)
    else:
        rel = BuyerRelationship(
            company_id=company_id,
            organization_id=organization_id,
            award_count_12m=award_count,
            total_award_value_12m=float(total_value) if total_value else None,
            avg_response_days=float(avg_response) if avg_response else None,
            win_rate=float(win_rate) if win_rate else None,
            relevance_score=relevance,
        )
        db.add(rel)

    await db.flush()
    return rel


def _compute_relevance(award_count: int, total_value: float, win_rate: float | None) -> float:
    score = 0.0
    if award_count > 0:
        count_score = min(award_count / 10, 1.0) * 40
        value_score = min(total_value / 50_000_000, 1.0) * 30
        score += count_score + value_score
    if win_rate is not None:
        score += win_rate * 30
    return round(min(score, 100.0), 2)


async def get_relationship(
    company_id: str,
    organization_id: str,
    db: AsyncSession,
) -> BuyerRelationship | None:
    result = await db.execute(
        select(BuyerRelationship).where(
            BuyerRelationship.company_id == company_id,
            BuyerRelationship.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()
