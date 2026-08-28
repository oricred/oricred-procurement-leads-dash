
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.tender import Tender


async def compute_buyer_preference(
    opportunity_id: str,
    db: AsyncSession,
    config: dict | None = None,
    opp: Opportunity | None = None,
    tender: Tender | None = None,
) -> float:
    """Score a buyer by province, SOE status and the preferred-buyer list.

    `config`, `opp` and `tender` may be supplied by a caller that already holds
    them. The award ingest loop does, and passing them removes three queries per
    new lead — including a fresh load of the admin scoring config, which is the
    same for every opportunity in a run.
    """
    if opp is None:
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

    if tender is None and opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()
    if tender is not None:
        province = tender.province
        buyer_org_id = tender.buyer_org_id

    score = 0.0

    province_score = province_weights.get(province.lower(), default_weight) if province else default_weight
    score += province_score

    is_preferred = False
    is_soe = False

    if buyer_org_id:
        # db.get consults the session identity map first. The award ingest loop
        # merges every organisation for the batch up front, so this costs
        # nothing there while still working standalone.
        org = await db.get(Organization, buyer_org_id)
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


async def evaluate_tender_preference(
    province: str | None,
    buyer_org_id: str | None,
    db: AsyncSession,
    config: dict | None = None,
) -> float:
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

    score = 0.0

    province_score = province_weights.get(province.lower(), default_weight) if province else default_weight
    score += province_score

    is_preferred = False
    is_soe = False

    if buyer_org_id:
        # db.get consults the session identity map first. The award ingest loop
        # merges every organisation for the batch up front, so this costs
        # nothing there while still working standalone.
        org = await db.get(Organization, buyer_org_id)
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
