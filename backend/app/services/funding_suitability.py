from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.award import Award


def compute_score(
    bee_level: int | None,
    cipc_forensic_risk_score: float | None,
    restricted_supplier: bool | None,
    award_value_12m: Decimal | None,
    company_age_days: int | None,
) -> float:
    if restricted_supplier:
        return 0.0

    score = 0.0

    if bee_level is not None:
        level_score = max(0, (4 - bee_level)) / 3 * 100
        score += 0.25 * level_score

    if award_value_12m is not None and award_value_12m > 0:
        normalized = min(float(award_value_12m) / 50_000_000, 1.0) * 100
        score += 0.20 * normalized

    if cipc_forensic_risk_score is not None:
        inverted = max(0, 100 - cipc_forensic_risk_score)
        score += 0.20 * inverted

    score += 0.15 * 50.0

    if company_age_days is not None:
        track_record = min(company_age_days / 3650, 1.0) * 100
        score += 0.10 * track_record
    else:
        score += 0.10 * 30.0

    return round(score, 2)


async def compute_funding_suitability(
    company_id: str,
    db: AsyncSession,
) -> float:
    result = await db.execute(
        select(Company).where(Company.id == company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        return 0.0

    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    agg_result = await db.execute(
        select(func.sum(Award.amount))
        .where(Award.supplier_company_id == company.api_id)
        .where(Award.award_date >= cutoff)
    )
    total_value = agg_result.scalar() or Decimal("0")

    age_days = None
    if company.created_at:
        age_days = (datetime.now(timezone.utc) - company.created_at).days

    return compute_score(
        bee_level=company.bee_level,
        cipc_forensic_risk_score=float(company.cipc_forensic_risk_score) if company.cipc_forensic_risk_score is not None else None,
        restricted_supplier=company.restricted_supplier,
        award_value_12m=total_value,
        company_age_days=age_days,
    )
