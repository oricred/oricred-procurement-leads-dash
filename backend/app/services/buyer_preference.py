from decimal import Decimal
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.models.organization import Organization
from app.models.opportunity import Opportunity


async def compute_buyer_preference(
    opportunity_id: str,
    db: AsyncSession,
    config: dict | None = None,
) -> float:
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        return 0.0

    from app.services.admin_config import get_config
    if config is None:
        scoring_config = await get_config("admin_scoring", db)
        config = scoring_config.get("buyer_preference", {})

    if not config.get("enabled", True):
        return 0.0

    province_weights = config.get("province_weights", {})
    default_weight = config.get("default_province_weight", 40)
    preferred_buyers = config.get("preferred_buyers", [])
    soe_bonus = config.get("soe_bonus", 20)

    province = None
    buyer_org_id = None

    if opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()
        if tender:
            province = tender.province
            buyer_org_id = tender.buyer_org_id

    score = 0.0

    province_score = province_weights.get(province.lower(), default_weight) if province else default_weight
    score += province_score

    is_preferred = False
    is_soe = False

    if buyer_org_id:
        org_result = await db.execute(
            select(Organization).where(Organization.id == buyer_org_id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            if org.organization_type == "soe":
                is_soe = True
            if org.name in preferred_buyers or org.id in preferred_buyers:
                is_preferred = True

    if is_preferred:
        score += soe_bonus * 1.5
    elif is_soe:
        score += soe_bonus

    return round(min(score, 100), 2)
