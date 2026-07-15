import csv
import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.award import Award
from app.models.company import Company
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.watchlist import WatchlistItem
from app.models.organization import Organization
from app.models.tender import Tender
from app.schemas.award import AwardItem, AwardsList
from app.schemas.opportunity import OpportunityRead
from app.services.lead_scoring import refresh_lead_scoring

router = APIRouter()

SORT_FIELDS = {
    "supplier": Award.supplier_name, "buyer": Organization.name, "tender": Tender.title,
    "value": Award.amount, "award_date": Award.award_date, "bee_level": Award.bee_level,
    "source": Award.source, "lead_state": Opportunity.kanban_stage,
}


def _query_awards():
    return (
        select(
            Award, Organization.name.label("buyer_org_name"), Tender.title.label("tender_title"),
            Opportunity.id.label("opportunity_id"), Opportunity.kanban_stage.label("lead_stage"),
            Opportunity.contact_sufficiency.label("contact_readiness"), Company.id.label("company_id"),
            WatchlistItem.id.label("watchlist_id"),
        )
        .outerjoin(Tender, Award.tender_id == Tender.id)
        .outerjoin(Organization, Award.buyer_org_id == Organization.id)
        .outerjoin(Company, Award.supplier_company_id == Company.api_id)
        .outerjoin(Opportunity, Opportunity.award_id == Award.id)
        .outerjoin(WatchlistItem, WatchlistItem.tender_id == Award.tender_id)
    )


def _filter_awards(query, supplier=None, buyer_org_id=None, province=None, buyer_scope=None,
                   date_from=None, date_to=None, value_min=None, value_max=None,
                   source=None, has_opportunity=None, watch_context=None):
    if supplier:
        query = query.where(Award.supplier_name.ilike(f"%{supplier}%"))
    if buyer_org_id and buyer_org_id != "all":
        query = query.where(Award.buyer_org_id == buyer_org_id)
    if province and province != "all":
        query = query.where(Tender.province.ilike(province))
    if buyer_scope == "municipal":
        query = query.where(Organization.organization_type.ilike("%municipal%"))
    if date_from:
        query = query.where(Award.award_date >= datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc))
    if date_to:
        query = query.where(Award.award_date <= datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc))
    if value_min is not None:
        query = query.where(Award.amount >= value_min)
    if value_max is not None:
        query = query.where(Award.amount <= value_max)
    if source:
        query = query.where(Award.source == source)
    if has_opportunity is True:
        query = query.where(Opportunity.id.isnot(None))
    elif has_opportunity is False:
        query = query.where(Opportunity.id.is_(None))
    if watch_context == "watched":
        query = query.where(WatchlistItem.id.isnot(None))
    elif watch_context == "not_watched":
        query = query.where(WatchlistItem.id.is_(None))
    return query


def _item(row) -> AwardItem:
    # SQLAlchemy exposes the ORM entity as ``row.Award``; retain support for
    # lightweight row-shaped consumers used by integrations and tests.
    entity = getattr(row, "Award", None)
    award = entity if isinstance(entity, Award) else row

    def optional(value):
        return value if isinstance(value, (str, int, float, datetime)) else None

    opportunity_id = optional(getattr(row, "opportunity_id", None))
    stage = optional(getattr(row, "lead_stage", None))
    return AwardItem(
        id=str(award.id), supplier_name=award.supplier_name,
        buyer_org_id=optional(getattr(award, "buyer_org_id", None)),
        buyer_org_name=optional(getattr(row, "buyer_org_name", None)),
        tender_title=optional(getattr(row, "tender_title", None)),
        amount=float(award.amount) if getattr(award, "amount", None) is not None else None,
        award_date=optional(getattr(award, "award_date", None)),
        bee_level=optional(getattr(award, "bee_level", None)), source=award.source,
        opportunity_id=str(opportunity_id) if opportunity_id else None,
        supplier_company_id=optional(getattr(award, "supplier_company_id", None)),
        supplier_resolved=bool(optional(getattr(row, "company_id", None))),
        lead_state=stage if isinstance(stage, str) else "not_created",
        contact_readiness=optional(getattr(row, "contact_readiness", None)),
    )
@router.get("/awards", response_model=AwardsList)
async def list_awards(
    supplier: str | None = None, buyer_org_id: str | None = None,
    province: str | None = None, buyer_scope: str | None = Query(None, pattern="^(municipal|all)?$"),
    date_from: date | None = None, date_to: date | None = None,
    value_min: float | None = None, value_max: float | None = None, source: str | None = None,
    has_opportunity: bool | None = None, watch_context: str | None = Query(None, pattern="^(watched|not_watched|all)?$"), sort: str = "award_date", direction: str = "desc",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = _filter_awards(_query_awards(), supplier, buyer_org_id, province, buyer_scope, date_from, date_to, value_min, value_max, source, has_opportunity, watch_context)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = SORT_FIELDS.get(sort, Award.award_date)
    query = query.order_by(order.asc().nulls_last() if direction == "asc" else order.desc().nulls_last())
    rows = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    return AwardsList(items=[_item(row) for row in rows], total=total, page=page, page_size=page_size)


@router.get("/awards/export")
async def export_awards(
    supplier: str | None = None, buyer_org_id: str | None = None,
    province: str | None = None, buyer_scope: str | None = Query(None, pattern="^(municipal|all)?$"),
    date_from: date | None = None, date_to: date | None = None,
    value_min: float | None = None, value_max: float | None = None, source: str | None = None,
    has_opportunity: bool | None = None, watch_context: str | None = Query(None, pattern="^(watched|not_watched|all)?$"), sort: str = "award_date", direction: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    query = _filter_awards(_query_awards(), supplier, buyer_org_id, province, buyer_scope, date_from, date_to, value_min, value_max, source, has_opportunity, watch_context)
    order = SORT_FIELDS.get(sort, Award.award_date)
    rows = await db.execute(query.order_by(order.asc().nulls_last() if direction == "asc" else order.desc().nulls_last()))
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["supplier", "buyer", "tender", "value", "award_date", "bee_level", "source", "lead_state", "contact_readiness"])
    for row in rows:
        item = _item(row)
        writer.writerow([item.supplier_name, item.buyer_org_name, item.tender_title, item.amount, item.award_date, item.bee_level, item.source, item.lead_state, item.contact_readiness])
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=oricred-awards.csv"})


@router.post("/awards/{award_id}/lead", response_model=OpportunityRead)
async def create_lead_from_award(award_id: str, db: AsyncSession = Depends(get_db)):
    award = await db.get(Award, award_id)
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    existing = (await db.execute(select(Opportunity).where(Opportunity.award_id == award.id))).scalar_one_or_none()
    if existing:
        from app.api.opportunities import _read_opportunity_with_context
        return await _read_opportunity_with_context(existing, db)

    company = None
    if award.supplier_company_id:
        company = (await db.execute(select(Company).where(Company.api_id == award.supplier_company_id))).scalar_one_or_none()
    if not company:
        company = (await db.execute(select(Company).where(Company.name.ilike(award.supplier_name)).limit(1))).scalar_one_or_none()
    provisional = company is None
    if provisional:
        company = Company(api_id=f"provisional:{award.id}", name=award.supplier_name, bee_level=award.bee_level)
        db.add(company)
        await db.flush()

    opp = Opportunity(
        award_id=award.id, tender_id=award.tender_id, company_id=company.id,
        kanban_stage="new_lead", needs_enrichment=provisional,
        contact_sufficiency="none", next_action="Resolve supplier identity" if provisional else "Find contact",
    )
    db.add(opp)
    await db.flush()
    await refresh_lead_scoring(opp, db, award=award, company=company, contacts=[])
    await db.commit()
    await db.refresh(opp)
    from app.api.opportunities import _read_opportunity_with_context
    return await _read_opportunity_with_context(opp, db)
