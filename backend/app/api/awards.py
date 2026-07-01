from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.award import Award
from app.models.tender import Tender
from app.models.organization import Organization
from app.models.opportunity import Opportunity
from app.schemas.award import AwardItem, AwardsList

router = APIRouter()


@router.get("/awards", response_model=AwardsList)
async def list_awards(
    supplier: str | None = None,
    buyer_org_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    source: str | None = None,
    has_opportunity: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(
            Award.id,
            Award.supplier_name,
            Award.buyer_org_id,
            Organization.name.label("buyer_org_name"),
            Tender.title.label("tender_title"),
            Award.amount,
            Award.award_date,
            Award.bee_level,
            Award.source,
            Opportunity.id.label("opportunity_id"),
        )
        .outerjoin(Tender, Award.tender_id == Tender.id)
        .outerjoin(Organization, Award.buyer_org_id == Organization.id)
        .outerjoin(
            Opportunity,
            and_(
                Opportunity.award_id == Award.id,
                Opportunity.company_id.isnot(None),
            ),
        )
    )

    if supplier:
        query = query.where(Award.supplier_name.ilike(f"%{supplier}%"))
    if buyer_org_id:
        query = query.where(Award.buyer_org_id == buyer_org_id)
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

    total_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(total_query) or 0

    query = query.order_by(Award.award_date.desc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = await db.execute(query)

    items = []
    for row in rows:
        items.append(AwardItem(
            id=str(row.id),
            supplier_name=row.supplier_name,
            buyer_org_id=row.buyer_org_id,
            buyer_org_name=row.buyer_org_name,
            tender_title=row.tender_title,
            amount=float(row.amount) if row.amount is not None else None,
            award_date=row.award_date,
            bee_level=row.bee_level,
            source=row.source,
            opportunity_id=str(row.opportunity_id) if row.opportunity_id else None,
        ))

    return AwardsList(items=items, total=total, page=page, page_size=page_size)
