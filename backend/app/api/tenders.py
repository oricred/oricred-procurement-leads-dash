from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tender import Tender
from app.models.organization import Organization
from app.models.category import Category
from app.models.opportunity import Opportunity
from app.models.watchlist import WatchlistItem
from app.models.past_due import PastDueQueue
from app.schemas.tender import TenderItem, TendersList

router = APIRouter()


async def _compute_status_for_tender(tender_id: str, db: AsyncSession) -> tuple[str, bool, str | None]:
    opp = await db.execute(
        select(Opportunity.id).where(
            Opportunity.tender_id == tender_id,
            Opportunity.company_id.isnot(None),
        ).limit(1)
    )
    opp_id = opp.scalar_one_or_none()
    if opp_id:
        return ("opportunity", False, str(opp_id))

    wl = await db.execute(
        select(WatchlistItem.status).where(
            WatchlistItem.tender_id == tender_id
        ).limit(1)
    )
    wl_row = wl.scalar_one_or_none()
    if wl_row == "awarded":
        return ("awarded", True, None)
    elif wl_row == "watching":
        return ("watching", True, None)

    pd = await db.execute(
        select(PastDueQueue.id).where(
            PastDueQueue.tender_id == tender_id
        ).limit(1)
    )
    if pd.scalar_one_or_none():
        return ("past_due", False, None)

    return ("not_watched", False, None)


def _apply_status_filter(query, status: str):
    if status == "watching":
        return query.where(
            exists(
                select(WatchlistItem.id).where(
                    WatchlistItem.tender_id == Tender.id,
                    WatchlistItem.status == "watching",
                )
            )
        )
    elif status == "opportunity":
        return query.where(
            exists(
                select(Opportunity.id).where(
                    Opportunity.tender_id == Tender.id,
                    Opportunity.company_id.isnot(None),
                )
            )
        )
    elif status == "awarded":
        return query.where(
            exists(
                select(WatchlistItem.id).where(
                    WatchlistItem.tender_id == Tender.id,
                    WatchlistItem.status == "awarded",
                )
            )
        )
    elif status == "past_due":
        return query.where(
            exists(
                select(PastDueQueue.id).where(
                    PastDueQueue.tender_id == Tender.id
                )
            )
        )
    elif status == "not_watched":
        return query.where(
            ~exists(
                select(WatchlistItem.id).where(
                    WatchlistItem.tender_id == Tender.id
                )
            )
            & ~exists(
                select(PastDueQueue.id).where(
                    PastDueQueue.tender_id == Tender.id
                )
            )
            & ~exists(
                select(Opportunity.id).where(
                    Opportunity.tender_id == Tender.id,
                    Opportunity.company_id.isnot(None),
                )
            )
        )
    return query


@router.get("/tenders", response_model=TendersList)
async def list_tenders(
    search: str | None = None,
    buyer_org_id: str | None = None,
    province: str | None = None,
    category_id: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
    status: str | None = None,
    has_opportunity: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(
            Tender.id,
            Tender.title,
            Tender.estimated_value,
            Tender.province,
            Tender.category_id,
            Category.name.label("category_name"),
            Tender.buyer_org_id,
            Organization.name.label("buyer_org_name"),
            Tender.closing_date,
            Tender.published_at,
            Tender.tender_type,
            Tender.discovered_at,
        )
        .outerjoin(Organization, Tender.buyer_org_id == Organization.id)
        .outerjoin(Category, Tender.category_id == Category.id)
    )

    if search:
        query = query.where(
            Tender.title.ilike(f"%{search}%")
        )
    if buyer_org_id:
        query = query.where(Tender.buyer_org_id == buyer_org_id)
    if province:
        query = query.where(Tender.province == province)
    if category_id:
        query = query.where(Tender.category_id == category_id)
    if value_min is not None:
        query = query.where(Tender.estimated_value >= value_min)
    if value_max is not None:
        query = query.where(Tender.estimated_value <= value_max)
    if closing_from:
        query = query.where(Tender.closing_date >= datetime.combine(closing_from, datetime.min.time()).replace(tzinfo=timezone.utc))
    if closing_to:
        query = query.where(Tender.closing_date <= datetime.combine(closing_to, datetime.max.time()).replace(tzinfo=timezone.utc))
    if status:
        query = _apply_status_filter(query, status)
    if has_opportunity is True:
        query = query.where(
            exists(
                select(Opportunity.id).where(
                    Opportunity.tender_id == Tender.id,
                    Opportunity.company_id.isnot(None),
                )
            )
        )
    elif has_opportunity is False:
        query = query.where(
            ~exists(
                select(Opportunity.id).where(
                    Opportunity.tender_id == Tender.id,
                    Opportunity.company_id.isnot(None),
                )
            )
        )

    total_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(total_query) or 0

    query = query.order_by(Tender.discovered_at.desc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = await db.execute(query)

    items = []
    for row in rows:
        status_val, is_watching, opp_id = await _compute_status_for_tender(str(row.id), db)
        items.append(TenderItem(
            id=str(row.id),
            title=row.title,
            estimated_value=float(row.estimated_value) if row.estimated_value is not None else None,
            province=row.province,
            category_id=row.category_id,
            category_name=row.category_name,
            buyer_org_id=row.buyer_org_id,
            buyer_org_name=row.buyer_org_name,
            closing_date=row.closing_date,
            published_at=row.published_at,
            tender_type=row.tender_type,
            discovered_at=row.discovered_at,
            status=status_val,
            is_watching=is_watching,
            opportunity_id=opp_id,
        ))

    return TendersList(items=items, total=total, page=page, page_size=page_size)


@router.get("/tenders/provinces")
async def list_tender_provinces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Tender.province).distinct().where(Tender.province.isnot(None)).order_by(Tender.province)
    )
    return [r[0] for r in result.all()]
