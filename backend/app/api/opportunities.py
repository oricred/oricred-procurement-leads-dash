from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models.opportunity import Opportunity, OpportunityAudit
from app.models.award import Award
from app.models.tender import Tender
from app.models.company import Company
from app.models.organization import Organization
from app.models.contact import Contact
from app.models.user import User
from app.schemas.opportunity import OpportunityRead, OpportunityStageUpdate, OpportunityUpdate, OpportunityList, AuditEntry, OpportunityContactedUpdate, OpportunityTransition
from app.schemas.contact import ContactRead
from app.schemas.buyer_relationship import BuyerRelationshipRead
from app.services.buyer_relationship import compute_relationship, get_relationship
from app.services.funding_suitability import compute_funding_suitability
from app.services.buyer_preference import compute_buyer_preference
from app.services.crm.sync import push_opportunity_to_crm
from app.services.lead_scoring import choose_primary_contact, refresh_lead_scoring
from app.services.lead_service import mark_opportunity_contacted, retry_contact_lookup_for_opportunity
from app.workflow import LEGACY_STAGE_MAP, WORKFLOW_NEXT, is_workflow_stage, normalize_stage

router = APIRouter()


async def _load_opportunity_contacts(opp: Opportunity, db: AsyncSession) -> list[ContactRead]:
    contacts: list[Contact] = []
    if opp.company_id:
        c_result = await db.execute(
            select(Contact).where(Contact.company_id == opp.company_id).order_by(Contact.is_primary.desc(), Contact.last_name)
        )
        contacts.extend(c_result.scalars().all())
    if opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()
        if tender and tender.buyer_org_id:
            o_result = await db.execute(
                select(Contact).where(Contact.organization_id == tender.buyer_org_id).order_by(Contact.is_primary.desc(), Contact.last_name)
            )
            seen = {c.id for c in contacts}
            for c in o_result.scalars().all():
                if c.id not in seen:
                    contacts.append(c)
    return [ContactRead.model_validate(c) for c in contacts]


def _opportunity_to_read(opp: Opportunity, tender: Tender | None = None, award: Award | None = None, company: Company | None = None, contacts: list[ContactRead] | None = None) -> OpportunityRead:
    days_since = None
    if award and award.award_date:
        days_since = (datetime.now(timezone.utc) - award.award_date).days

    return OpportunityRead(
        id=str(opp.id),
        tender_id=str(opp.tender_id) if opp.tender_id else None,
        award_id=str(opp.award_id) if opp.award_id else None,
        company_id=str(opp.company_id) if opp.company_id else None,
        company_name=company.name if company else award.supplier_name if award else None,
        award_value=award.amount if award else None,
        buyer_org=tender.buyer_org_id if tender else None,
        province=tender.province if tender else None,
        category=tender.category_id if tender else None,
        kanban_stage=normalize_stage(opp.kanban_stage) or opp.kanban_stage,
        assigned_to=opp.assigned_to,
        contact_sufficiency=opp.contact_sufficiency,
        risk_flag=opp.risk_flag,
        win_probability=opp.win_probability,
        funding_suitability=opp.funding_suitability,
        buyer_preference_score=opp.buyer_preference_score,
        lead_priority_score=opp.lead_priority_score,
        lead_priority_reasons=opp.lead_priority_reasons or [],
        next_action=opp.next_action,
        last_contact_lookup_at=opp.last_contact_lookup_at,
        contacted_at=opp.contacted_at,
        credit_decision=opp.credit_decision,
        lost_reason=opp.lost_reason,
        conditions_checklist=opp.conditions_checklist or [],
        needs_enrichment=opp.needs_enrichment,
        primary_contact=ContactRead.model_validate(choose_primary_contact([c for c in contacts or [] if c.company_id])) if choose_primary_contact([c for c in contacts or [] if c.company_id]) else None,
        source_tender_title=tender.title if tender else None,
        source_award_date=award.award_date if award else None,
        source_award_value=award.amount if award else None,
        related_bidders=opp.related_bidders,
        contacts=contacts or [],
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
        stage = normalize_stage(stage)
        if not is_workflow_stage(stage):
            raise HTTPException(status_code=400, detail="Invalid opportunity stage")
        stage_values = [stage] + [legacy for legacy, canonical in LEGACY_STAGE_MAP.items() if canonical == stage]
        q = q.where(Opportunity.kanban_stage.in_(stage_values))
    if assigned_to:
        q = q.where(Opportunity.assigned_to == assigned_to)
    q = q.order_by(Opportunity.lead_priority_score.desc().nulls_last(), Opportunity.buyer_preference_score.desc().nulls_last(), Opportunity.updated_at.desc())

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

        contacts = await _load_opportunity_contacts(opp, db)
        items.append(_opportunity_to_read(opp, tender, award, company, contacts))

    return OpportunityList(items=items, total=len(items))


@router.post("/{opportunity_id}/transition", response_model=OpportunityRead)
async def transition_opportunity(
    opportunity_id: str, body: OpportunityTransition, db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    opp = await db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if opp.version != body.version:
        raise HTTPException(status_code=409, detail="Version conflict: opportunity was modified")

    old_stage = normalize_stage(opp.kanban_stage) or opp.kanban_stage
    action = body.action
    if action in ("decline", "lose"):
        if not body.lost_reason or not body.lost_reason.strip():
            raise HTTPException(status_code=400, detail="A lost reason is required")
        new_stage = "lost_lead"
    elif action == "reopen":
        if old_stage not in ("funded", "lost_lead") or not body.confirm:
            raise HTTPException(status_code=400, detail="Terminal reopening requires confirmation")
        new_stage = "new_lead"
    elif action == "back":
        if not body.confirm:
            raise HTTPException(status_code=400, detail="Backward movement requires confirmation")
        previous = {next_stage: current for current, next_stage in WORKFLOW_NEXT.items()}
        if old_stage not in previous:
            raise HTTPException(status_code=400, detail="This stage cannot move backward")
        new_stage = previous[old_stage]
    elif action == "advance":
        if old_stage == "new_lead":
            raise HTTPException(status_code=400, detail="Use mark-contacted to advance a new lead")
        new_stage = WORKFLOW_NEXT.get(old_stage)
        if not new_stage:
            raise HTTPException(status_code=400, detail="This stage cannot advance")
        if old_stage == "credit_review":
            if body.credit_decision != "approved":
                raise HTTPException(status_code=400, detail="Credit approval is required before pre-approval")
            opp.credit_decision = body.credit_decision
        if old_stage == "conditions_precedent":
            checklist = body.conditions_checklist if body.conditions_checklist is not None else (opp.conditions_checklist or [])
            if not checklist or not all(bool(item.get("cleared")) for item in checklist):
                raise HTTPException(status_code=400, detail="All conditions must be cleared before advancing")
            opp.conditions_checklist = checklist
    else:
        raise HTTPException(status_code=400, detail="Use advance, back, reopen, decline, or lose")

    opp.kanban_stage = new_stage
    opp.version += 1
    opp.updated_at = datetime.now(timezone.utc)
    if new_stage == "lost_lead":
        opp.lost_reason = body.lost_reason.strip()
        opp.closed_at = datetime.now(timezone.utc)
    elif new_stage == "funded":
        opp.closed_at = datetime.now(timezone.utc)
    elif action == "reopen":
        opp.closed_at = None
    db.add(OpportunityAudit(opportunity_id=opp.id, from_stage=old_stage, to_stage=new_stage, changed_by=current_user["name"]))
    await db.commit()
    await db.refresh(opp)
    await push_opportunity_to_crm(opportunity_id)
    return await _read_opportunity_with_context(opp, db)

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

    contacts = await _load_opportunity_contacts(opp, db)
    return _opportunity_to_read(opp, tender, award, company, contacts)


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

    raise HTTPException(status_code=400, detail="Use the approved transition endpoint for workflow changes")

    new_stage = normalize_stage(body.stage)
    if not is_workflow_stage(new_stage):
        raise HTTPException(status_code=400, detail="Invalid opportunity stage")

    old_stage = normalize_stage(opp.kanban_stage)
    opp.kanban_stage = new_stage
    opp.version += 1
    opp.updated_at = datetime.now(timezone.utc)
    if body.assigned_to:
        opp.assigned_to = body.assigned_to
    if new_stage in ("funded", "lost_lead"):
        opp.closed_at = datetime.now(timezone.utc)

    audit = OpportunityAudit(
        opportunity_id=opp.id,
        from_stage=old_stage,
        to_stage=new_stage,
        changed_by=body.assigned_to or "system",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(opp)

    await push_opportunity_to_crm(opportunity_id)

    return await _read_opportunity_with_context(opp, db)


async def _read_opportunity_with_context(opp: Opportunity, db: AsyncSession) -> OpportunityRead:
    tender = await db.get(Tender, opp.tender_id) if opp.tender_id else None
    award = await db.get(Award, opp.award_id) if opp.award_id else None
    company = await db.get(Company, opp.company_id) if opp.company_id else None
    contacts = await _load_opportunity_contacts(opp, db)
    return _opportunity_to_read(opp, tender, award, company, contacts)


@router.post("/{opportunity_id}/find-contact", response_model=OpportunityRead)
async def find_opportunity_contact(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    try:
        opp, _added = await retry_contact_lookup_for_opportunity(opportunity_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return await _read_opportunity_with_context(opp, db)


@router.post("/{opportunity_id}/mark-contacted", response_model=OpportunityRead)
async def mark_contacted(
    opportunity_id: str,
    body: OpportunityContactedUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        opp = await mark_opportunity_contacted(
            opportunity_id=opportunity_id,
            version=body.version,
            db=db,
            contact_id=body.contact_id,
            note=body.note,
            changed_by=current_user["name"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await push_opportunity_to_crm(opportunity_id)
    return await _read_opportunity_with_context(opp, db)

@router.patch("/{opportunity_id}/assign")
async def assign_opportunity(opportunity_id: str, assignee: str, db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user)):
    result = await db.execute(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    target = await db.get(User, assignee) if assignee else None
    if assignee and (not target or not target.is_active):
        raise HTTPException(status_code=400, detail="Assignee must be an active user")
    opp.assigned_to = str(target.id) if target else None
    opp.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await push_opportunity_to_crm(opportunity_id)
    return {"status": "ok", "assigned_to": assignee}


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
async def update_opportunity(opportunity_id: str, body: OpportunityUpdate, db: AsyncSession = Depends(get_db), _: dict = Depends(get_current_user)):
    result = await db.execute(select(Opportunity).where(Opportunity.id == opportunity_id))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if body.notes is not None:
        opp.notes = body.notes
    if body.risk_flag is not None:
        if body.risk_flag not in ("red", "amber", "green"):
            raise HTTPException(status_code=400, detail="Invalid risk_flag")
        opp.risk_flag = body.risk_flag
    if body.assigned_to is not None:
        if not body.assigned_to:
            opp.assigned_to = None
        else:
            assignee = await db.get(User, body.assigned_to)
            if not assignee or not assignee.is_active:
                raise HTTPException(status_code=400, detail="Assignee must be an active user")
            opp.assigned_to = str(assignee.id)
    opp.updated_at = datetime.now(timezone.utc)
    opp.version += 1
    await db.commit()
    await db.refresh(opp)
    return await _read_opportunity_with_context(opp, db)


@router.get("/{opportunity_id}/audit", response_model=list[AuditEntry])
async def get_opportunity_audit(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OpportunityAudit)
        .where(OpportunityAudit.opportunity_id == opportunity_id)
        .order_by(OpportunityAudit.changed_at.desc())
    )
    return result.scalars().all()


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

    from app.services.admin_config import get_config
    from app.services.crm.monday import MondayDotComAdapter

    creds = await get_config("admin_credentials", db)
    api_key = creds.get("monday_api_key", "")
    board_id = creds.get("monday_board_id", "oricred_opportunities")
    if not api_key:
        return {"activities": []}

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    adapter = MondayDotComAdapter(api_key)

    try:
        activities = await adapter.get_recent_activity(board_id, today)
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
