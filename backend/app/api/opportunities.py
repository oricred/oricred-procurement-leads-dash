from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.opportunity import Opportunity, OpportunityAudit
from app.models.award import Award
from app.models.tender import Tender
from app.models.company import Company
from app.models.organization import Organization
from app.schemas.opportunity import OpportunityRead, OpportunityStageUpdate, OpportunityList
from app.schemas.buyer_relationship import BuyerRelationshipRead
from app.services.buyer_relationship import compute_relationship, get_relationship
from app.services.funding_suitability import compute_funding_suitability
from app.services.buyer_preference import compute_buyer_preference
from app.services.crm.sync import push_opportunity_to_crm

router = APIRouter()


def _opportunity_to_read(opp: Opportunity, tender: Tender | None = None, award: Award | None = None, company: Company | None = None) -> OpportunityRead:
    days_since = None
    if award and award.award_date:
        days_since = (datetime.now(timezone.utc) - award.award_date).days

    return OpportunityRead(
        id=str(opp.id),
        tender_id=str(opp.tender_id) if opp.tender_id else None,
        award_id=str(opp.award_id) if opp.award_id else None,
        company_id=str(opp.company_id) if opp.company_id else None,
        company_name=company.name if company else None,
        award_value=award.amount if award else None,
        buyer_org=tender.buyer_org_id if tender else None,
        province=tender.province if tender else None,
        category=tender.category_id if tender else None,
        kanban_stage=opp.kanban_stage,
        assigned_to=opp.assigned_to,
        contact_sufficiency=opp.contact_sufficiency,
        risk_flag=opp.risk_flag,
        win_probability=opp.win_probability,
        funding_suitability=opp.funding_suitability,
        buyer_preference_score=opp.buyer_preference_score,
        days_since_award=days_since,
        notes=opp.notes,
        created_at=opp.created_at,
        updated_at=opp.updated_at,
        version=opp.version,
    )


@router.get("", response_model=OpportunityList)
async def list_opportunities(
    stage: str | None = Query(None),
    assigned_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Opportunity)
    if stage:
        q = q.where(Opportunity.kanban_stage == stage)
    if assigned_to:
        q = q.where(Opportunity.assigned_to == assigned_to)
    q = q.order_by(Opportunity.buyer_preference_score.desc().nulls_last(), Opportunity.updated_at.desc())

    result = await db.execute(q)
    opportunities = result.scalars().all()

    items = []
    for opp in opportunities:
        tender = None
        award = None
        company = None

        if opp.tender_id:
            t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
            tender = t_result.scalar_one_or_none()
        if opp.award_id:
            a_result = await db.execute(select(Award).where(Award.id == opp.award_id))
            award = a_result.scalar_one_or_none()
        if opp.company_id:
            c_result = await db.execute(select(Company).where(Company.id == opp.company_id))
            company = c_result.scalar_one_or_none()

        items.append(_opportunity_to_read(opp, tender, award, company))

    return OpportunityList(items=items, total=len(items))


@router.get("/{opportunity_id}", response_model=OpportunityRead)
async def get_opportunity(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Opportunity).where(Opportunity.id == opportunity_id))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    tender = None
    award = None
    company = None
    if opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()
    if opp.award_id:
        a_result = await db.execute(select(Award).where(Award.id == opp.award_id))
        award = a_result.scalar_one_or_none()
    if opp.company_id:
        c_result = await db.execute(select(Company).where(Company.id == opp.company_id))
        company = c_result.scalar_one_or_none()

    return _opportunity_to_read(opp, tender, award, company)


@router.patch("/{opportunity_id}/stage", response_model=OpportunityRead)
async def update_stage(
    opportunity_id: str,
    body: OpportunityStageUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if opp.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict: opportunity was modified")

    old_stage = opp.kanban_stage
    opp.kanban_stage = body.stage
    opp.version += 1
    opp.updated_at = datetime.now(timezone.utc)
    if body.assigned_to:
        opp.assigned_to = body.assigned_to
    if body.stage in ("funded", "closed"):
        opp.closed_at = datetime.now(timezone.utc)

    audit = OpportunityAudit(
        opportunity_id=opp.id,
        from_stage=old_stage,
        to_stage=body.stage,
        changed_by=body.assigned_to or "system",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(opp)

    await push_opportunity_to_crm(opportunity_id)

    return _opportunity_to_read(opp)


@router.patch("/{opportunity_id}/assign")
async def assign_opportunity(opportunity_id: str, assignee: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    opp.assigned_to = assignee
    opp.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await push_opportunity_to_crm(opportunity_id)
    return {"status": "ok", "assigned_to": assignee}


@router.get("/{opportunity_id}/relationship", response_model=BuyerRelationshipRead | None)
async def get_opportunity_relationship(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if not opp.company_id:
        return None

    tender = None
    if opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()

    if not tender or not tender.buyer_org_id:
        return None

    org_result = await db.execute(
        select(Organization).where(Organization.id == tender.buyer_org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        return None

    rel = await get_relationship(opp.company_id, org.id, db)
    if not rel:
        rel = await compute_relationship(opp.company_id, org.id, db)
        await db.commit()

    if not rel:
        return None

    return BuyerRelationshipRead(
        id=str(rel.id),
        company_id=rel.company_id,
        organization_id=rel.organization_id,
        award_count_12m=rel.award_count_12m,
        total_award_value_12m=float(rel.total_award_value_12m) if rel.total_award_value_12m else None,
        avg_response_days=rel.avg_response_days,
        win_rate=rel.win_rate,
        last_interaction_at=rel.last_interaction_at,
        relevance_score=rel.relevance_score,
        updated_at=rel.updated_at,
    )


@router.post("/{opportunity_id}/compute-funding")
async def compute_opportunity_funding(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if not opp.company_id:
        raise HTTPException(status_code=400, detail="Opportunity has no company")

    score = await compute_funding_suitability(opp.company_id, db)
    opp.funding_suitability = score
    opp.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"funding_suitability": score}


@router.post("/{opportunity_id}/compute-preference")
async def compute_opportunity_preference(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    score = await compute_buyer_preference(opportunity_id, db)
    opp.buyer_preference_score = score
    opp.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"buyer_preference_score": score}


@router.get("/{opportunity_id}/crm-activity")
async def get_crm_activity(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    from app.config import settings
    from app.services.crm.monday import MondayDotComAdapter

    api_key = settings.monday_api_key
    if not api_key:
        return {"activities": []}

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    adapter = MondayDotComAdapter(api_key)

    try:
        activities = await adapter.get_recent_activity("oricred_opportunities", today)
    finally:
        await adapter.close()

    company_name = None
    if opp.company_id:
        c_result = await db.execute(select(Company).where(Company.id == opp.company_id))
        company = c_result.scalar_one_or_none()
        if company:
            company_name = company.name

    filtered = []
    for act in activities:
        item_name = (act.data or {}).get("item_name", "")
        if company_name and company_name.lower() in item_name.lower():
            filtered.append({
                "event": act.event,
                "data": act.data,
                "created_at": act.created_at.isoformat(),
            })
        elif not company_name:
            filtered.append({
                "event": act.event,
                "data": act.data,
                "created_at": act.created_at.isoformat(),
            })

    return {"activities": filtered[:20]}
