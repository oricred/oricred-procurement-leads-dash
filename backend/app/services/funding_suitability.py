from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.services.award_history import AwardHistory, load_one
from app.utils import as_utc


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
    company: Company | None = None,
    history: AwardHistory | None = None,
) -> float:
    """Score a supplier's suitability for funding.

    `company` and `history` may be supplied by a caller that already holds
    them. The award ingest loop does, and passing both removes two queries per
    new lead — see remediation-04 section 2.
    """
    if company is None:
        result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = result.scalar_one_or_none()
    if not company:
        return 0.0

    if history is None:
        history = await load_one(company.api_id, db)
    total_value = history.value_last_12m

    age_days = None
    created_at = as_utc(company.created_at)
    if created_at:
        age_days = (datetime.now(timezone.utc) - created_at).days

    return compute_score(
        bee_level=company.bee_level,
        cipc_forensic_risk_score=float(company.cipc_forensic_risk_score) if company.cipc_forensic_risk_score is not None else None,
        restricted_supplier=company.restricted_supplier,
        award_value_12m=total_value,
        company_age_days=age_days,
    )
