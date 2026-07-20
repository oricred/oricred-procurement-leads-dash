import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.opportunities import _load_opportunity_contacts, _opportunity_to_read
from app.database import get_db
from app.models.award import Award
from app.models.category import Category
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.schemas.opportunity import OpportunityList
from app.services.lead_contact_import import apply_import, parse_import_file, preview_import
from app.workflow import LEGACY_STAGE_MAP, normalize_stage

router = APIRouter(prefix="/leads", tags=["leads"])
MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("", response_model=OpportunityList)
async def list_leads(
    stage: str | None = Query(None),
    assigned_to: str | None = Query(None),
    contactability: str | None = Query(None),
    priority_min: float | None = Query(None),
    province: str | None = Query(None),
    buyer_org_id: str | None = Query(None),
    category: str | None = Query(None),
    risk_flag: str | None = Query(None),
    next_action: str | None = Query(None),
    value_min: float | None = Query(None),
    award_recency_days: int | None = Query(None, ge=1),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Opportunity)
        .join(Award, Opportunity.award_id == Award.id)
        .join(Tender, Opportunity.tender_id == Tender.id)
        .where(Opportunity.award_id.isnot(None))
    )
    if stage:
        canonical = normalize_stage(stage)
        stage_values = [canonical] + [
            legacy for legacy, mapped in LEGACY_STAGE_MAP.items() if mapped == canonical
        ]
        q = q.where(Opportunity.kanban_stage.in_(stage_values))
    if assigned_to:
        q = q.where(Opportunity.assigned_to == assigned_to)
    if contactability == "contactable":
        q = q.where(Opportunity.contact_sufficiency == "sufficient")
    elif contactability == "needs_contact":
        q = q.where(Opportunity.contact_sufficiency.in_(("none", "role_based")))
    if priority_min is not None:
        q = q.where(Opportunity.lead_priority_score >= priority_min)
    if risk_flag:
        q = q.where(Opportunity.risk_flag == risk_flag)
    if next_action:
        q = q.where(Opportunity.next_action == next_action)
    if value_min is not None:
        q = q.where(Award.amount >= value_min)
    if award_recency_days:
        q = q.where(
            Award.award_date >= datetime.now(timezone.utc) - timedelta(days=award_recency_days)
        )
    if search:
        q = q.where(
            or_(
                Award.supplier_name.ilike(f"%{search}%"),
                Opportunity.assigned_to.ilike(f"%{search}%"),
            )
        )
    if province:
        q = q.where(Tender.province.ilike(province))
    if buyer_org_id:
        q = q.where(Tender.buyer_org_id == buyer_org_id)
    if category:
        q = q.where(Tender.category_id == category)
    q = q.order_by(
        Opportunity.lead_priority_score.desc().nulls_last(),
        Award.award_date.desc().nulls_last(),
        Opportunity.created_at.desc(),
    )

    result = await db.execute(q)
    items = []
    for opp in result.scalars().all():
        tender = await db.get(Tender, opp.tender_id) if opp.tender_id else None
        award = await db.get(Award, opp.award_id) if opp.award_id else None
        company = await db.get(Company, opp.company_id) if opp.company_id else None

        category_name = None
        if tender and tender.category_id:
            cat = await db.get(Category, tender.category_id)
            if cat:
                category_name = cat.name

        contacts = await _load_opportunity_contacts(opp, db)
        items.append(
            _opportunity_to_read(opp, tender, award, company, contacts, None, category_name)
        )
    return OpportunityList(items=items, total=len(items))


@router.get("/export")
async def export_leads(
    stage: str | None = Query(None),
    assigned_to: str | None = Query(None),
    contactability: str | None = Query(None),
    priority_min: float | None = Query(None),
    province: str | None = Query(None),
    buyer_org_id: str | None = Query(None),
    category: str | None = Query(None),
    risk_flag: str | None = Query(None),
    next_action: str | None = Query(None),
    value_min: float | None = Query(None),
    award_recency_days: int | None = Query(None, ge=1),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Export every lead matching the supplied inbox filters as CSV."""
    leads = await list_leads(
        stage,
        assigned_to,
        contactability,
        priority_min,
        province,
        buyer_org_id,
        category,
        risk_flag,
        next_action,
        value_min,
        award_recency_days,
        search,
        db,
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "lead_id",
            "company",
            "contact_name",
            "contact_job_title",
            "contact_email",
            "contact_phone",
            "contact_status",
            "award_value",
            "award_date",
            "buyer",
            "tender",
            "province",
            "category",
            "priority_score",
            "next_action",
            "assigned_to",
        ]
    )
    for lead in leads.items:
        contact = lead.primary_contact
        writer.writerow(
            [
                lead.id,
                lead.company_name,
                f"{contact.first_name} {contact.last_name}" if contact else None,
                contact.job_title if contact else None,
                contact.email if contact else None,
                (contact.phone_direct or contact.phone_mobile) if contact else None,
                lead.contact_sufficiency,
                lead.source_award_value or lead.award_value,
                lead.source_award_date,
                lead.buyer_org,
                lead.source_tender_title,
                lead.province,
                lead.category_name or lead.category,
                lead.lead_priority_score,
                lead.next_action,
                lead.assigned_to,
            ]
        )
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=oricred-leads.csv"},
    )


async def _parse_contact_import(file: UploadFile) -> list:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Choose a CSV or XLSX file to import")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The import file is empty")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="Import files must be 10 MB or smaller")
    try:
        return parse_import_file(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/contact-import/preview")
async def preview_contact_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    rows = await _parse_contact_import(file)
    try:
        return await preview_import(rows, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/contact-import/apply")
async def apply_contact_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    rows = await _parse_contact_import(file)
    try:
        return await apply_import(rows, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
