from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.opportunities import _load_opportunity_contacts, _opportunity_to_read
from app.database import get_db
from app.models.award import Award
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.schemas.opportunity import OpportunityList
from app.workflow import LEGACY_STAGE_MAP, normalize_stage

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=OpportunityList)
async def list_leads(
    stage: str | None = Query(None),
    assigned_to: str | None = Query(None),
    contactability: str | None = Query(None),
    priority_min: float | None = Query(None),
    province: str | None = Query(None),
    buyer_org_id: str | None = Query(None),
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Opportunity).where(Opportunity.award_id.isnot(None))
    if stage:
        canonical = normalize_stage(stage)
        stage_values = [canonical] + [legacy for legacy, mapped in LEGACY_STAGE_MAP.items() if mapped == canonical]
        q = q.where(Opportunity.kanban_stage.in_(stage_values))
    if assigned_to:
        q = q.where(Opportunity.assigned_to == assigned_to)
    if contactability:
        if contactability == "contactable":
            q = q.where(Opportunity.contact_sufficiency == "sufficient")
        elif contactability == "needs_contact":
            q = q.where(Opportunity.contact_sufficiency.in_(("none", "role_based")))
    if priority_min is not None:
        q = q.where(Opportunity.lead_priority_score >= priority_min)

    q = q.order_by(Opportunity.lead_priority_score.desc().nulls_last(), Opportunity.created_at.desc())
    result = await db.execute(q)

    items = []
    for opp in result.scalars().all():
        tender = await db.get(Tender, opp.tender_id) if opp.tender_id else None
        if province and (not tender or (tender.province or "").lower() != province.lower()):
            continue
        if buyer_org_id and (not tender or tender.buyer_org_id != buyer_org_id):
            continue
        if category and (not tender or tender.category_id != category):
            continue
        award = await db.get(Award, opp.award_id) if opp.award_id else None
        company = await db.get(Company, opp.company_id) if opp.company_id else None
        contacts = await _load_opportunity_contacts(opp, db)
        items.append(_opportunity_to_read(opp, tender, award, company, contacts))

    return OpportunityList(items=items, total=len(items))
