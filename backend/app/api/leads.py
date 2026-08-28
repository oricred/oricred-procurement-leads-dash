import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.opportunities import _batch_load_opportunity_context, _opportunity_to_read
from app.database import get_db
from app.models.award import Award
from app.models.category import Category
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.tender import Tender
from app.models.user import User
from app.schemas.opportunity import OpportunityList
from app.services.lead_contact_import import apply_import, parse_import_file, preview_import
from app.services.text_utils import write_csv_row
from app.workflow import LEGACY_STAGE_MAP, is_workflow_stage, normalize_stage

router = APIRouter(prefix="/leads", tags=["leads"])
MAX_IMPORT_BYTES = 10 * 1024 * 1024
# The export is a deliberate full extract rather than a page, but it is still
# built entirely in memory, so it needs a ceiling of its own.
EXPORT_ROW_LIMIT = 50_000
LEAD_SORTS = ("priority", "newest")
LEAD_SORT_DEFAULT = "priority"


def _validate_lead_filters(stage: str | None, sort: str) -> None:
    """Reject unknown values instead of silently returning an empty inbox."""
    if stage and not is_workflow_stage(stage):
        raise HTTPException(status_code=400, detail="Invalid lead stage")
    if sort not in LEAD_SORTS:
        raise HTTPException(status_code=400, detail=f"Sort must be one of {', '.join(LEAD_SORTS)}")


async def _build_leads_query(
    stage=None, assigned_to=None, contactability=None, priority_min=None,
    province=None, buyer_org_id=None, category=None, risk_flag=None,
    next_action=None, value_min=None, award_recency_days=None, search=None,
    sort=LEAD_SORT_DEFAULT,
):
    # Award and tender are joined for context and filtering only. None of the
    # link columns carry a foreign key, so an inner join would silently drop a
    # lead whose tender row is missing — award_id is what defines the inbox.
    q = (
        select(Opportunity)
        .outerjoin(Award, Opportunity.award_id == Award.id)
        .outerjoin(Tender, Opportunity.tender_id == Tender.id)
        .outerjoin(Company, Opportunity.company_id == Company.id)
        .outerjoin(Organization, Tender.buyer_org_id == Organization.id)
        .outerjoin(Category, Tender.category_id == Category.id)
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
        # Match every field the inbox displays. Opportunity.assigned_to holds a
        # user UUID, not a name, so the owner is matched through User instead.
        pattern = f"%{search}%"
        q = q.where(
            or_(
                Award.supplier_name.ilike(pattern),
                Company.name.ilike(pattern),
                Tender.title.ilike(pattern),
                Tender.province.ilike(pattern),
                Tender.category_id.ilike(pattern),
                Category.name.ilike(pattern),
                Organization.name.ilike(pattern),
                Opportunity.assigned_to.in_(
                    select(User.id).where(
                        or_(User.name.ilike(pattern), User.email.ilike(pattern))
                    )
                ),
            )
        )
    if province:
        q = q.where(Tender.province.ilike(province))
    if buyer_org_id:
        q = q.where(Tender.buyer_org_id == buyer_org_id)
    if category:
        q = q.where(Tender.category_id == category)
    if sort == "newest":
        # A freshly converted award has no score yet; priority order buries it.
        q = q.order_by(
            Opportunity.created_at.desc(),
            Opportunity.lead_priority_score.desc().nulls_last(),
        )
    else:
        q = q.order_by(
            Opportunity.lead_priority_score.desc().nulls_last(),
            Award.award_date.desc().nulls_last(),
            Opportunity.created_at.desc(),
        )
    return q


async def _fetch_leads(
    db: AsyncSession,
    stage=None, assigned_to=None, contactability=None, priority_min=None,
    province=None, buyer_org_id=None, category=None, risk_flag=None,
    next_action=None, value_min=None, award_recency_days=None, search=None,
    sort=LEAD_SORT_DEFAULT, limit: int | None = None, offset: int = 0,
):
    q = await _build_leads_query(
        stage, assigned_to, contactability, priority_min, province,
        buyer_org_id, category, risk_flag, next_action, value_min,
        award_recency_days, search, sort,
    )

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    if limit is not None:
        q = q.limit(limit).offset(offset)

    result = await db.execute(q)
    opportunities = result.scalars().all()
    context = await _batch_load_opportunity_context(opportunities, db)

    items = [_opportunity_to_read(opp, **context[opp.id]) for opp in opportunities]
    return OpportunityList(items=items, total=total)


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
    sort: str = Query(LEAD_SORT_DEFAULT),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    _validate_lead_filters(stage, sort)
    return await _fetch_leads(
        db, stage, assigned_to, contactability, priority_min, province,
        buyer_org_id, category, risk_flag, next_action, value_min,
        award_recency_days, search, sort, limit=limit, offset=offset,
    )


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
    sort: str = Query(LEAD_SORT_DEFAULT),
    db: AsyncSession = Depends(get_db),
):
    """Export every lead matching the supplied inbox filters as CSV."""
    _validate_lead_filters(stage, sort)
    leads = await _fetch_leads(
        db, stage, assigned_to, contactability, priority_min, province,
        buyer_org_id, category, risk_flag, next_action, value_min,
        award_recency_days, search, sort, limit=None,
    )
    if leads.total > EXPORT_ROW_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=(
                f"That filter matches {leads.total:,} leads. "
                f"Narrow it to {EXPORT_ROW_LIMIT:,} or fewer."
            ),
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
        write_csv_row(
            writer,
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
            ],
        )
    # BOM so Excel on Windows renders names with diacritics correctly.
    return StreamingResponse(
        iter(["﻿" + stream.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="oricred-leads.csv"'},
    )


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, refusing anything larger.

    Checks the declared size first, then enforces the ceiling while reading
    because the declared size is client-supplied and may lie. The previous code
    called file.read() and checked len() afterwards, so a multi-gigabyte upload
    was fully buffered into the worker before being rejected.
    """
    megabytes = limit // (1024 * 1024)
    detail = f"Import files must be {megabytes} MB or smaller"
    if file.size is not None and file.size > limit:
        raise HTTPException(status_code=413, detail=detail)

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)


async def _parse_contact_import(file: UploadFile) -> list:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Choose a CSV or XLSX file to import")
    content = await _read_bounded(file, MAX_IMPORT_BYTES)
    if not content:
        raise HTTPException(status_code=400, detail="The import file is empty")
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
