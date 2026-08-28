from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.schemas.tender import TenderItem, TendersList

router = APIRouter()


def _status_columns() -> tuple:
    """Tender status, watch flag and linked opportunity, computed in SQL.

    These were three sequential SELECTs per row inside the result loop, so a
    50-row page cost up to 151 round trips. The correlated-EXISTS form already
    existed in _apply_status_filter below; this is the same logic projected
    rather than filtered.

    Precedence must match the original helper exactly: opportunity, then
    awarded, then watching, then past due, then not watched. Note that
    is_watching is False for the opportunity and past_due states even when a
    watchlist row exists — the Tenders page watch toggle depends on that.
    """
    opportunity_id = (
        select(Opportunity.id)
        .where(Opportunity.tender_id == Tender.id, Opportunity.company_id.isnot(None))
        .order_by(Opportunity.created_at.desc())
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    watch_status = (
        select(WatchlistItem.status)
        .where(WatchlistItem.tender_id == Tender.id)
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    past_due_id = (
        select(PastDueQueue.id)
        .where(
            PastDueQueue.tender_id == Tender.id,
            # A resolved entry is history; only a pending one is a live state.
            PastDueQueue.resolution == "pending",
        )
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    status = case(
        (opportunity_id.isnot(None), literal("opportunity")),
        (watch_status == "awarded", literal("awarded")),
        (watch_status == "watching", literal("watching")),
        (past_due_id.isnot(None), literal("past_due")),
        else_=literal("not_watched"),
    )
    is_watching = case(
        (opportunity_id.isnot(None), literal(False)),
        (watch_status.in_(("awarded", "watching")), literal(True)),
        else_=literal(False),
    )
    return (
        opportunity_id.label("opportunity_id"),
        status.label("status"),
        is_watching.label("is_watching"),
    )


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
                    PastDueQueue.tender_id == Tender.id,
                    PastDueQueue.resolution == "pending",
                )
            )
        )
    elif status == "not_watched":
        return query.where(
            ~exists(
                select(WatchlistItem.id).where(
                    WatchlistItem.tender_id == Tender.id,
                    WatchlistItem.status.in_(("watching", "awarded", "past_due")),
                )
            )
            & ~exists(
                select(PastDueQueue.id).where(
                    PastDueQueue.tender_id == Tender.id,
                    PastDueQueue.resolution == "pending",
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
            *_status_columns(),
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
            status=row.status,
            is_watching=bool(row.is_watching),
            opportunity_id=str(row.opportunity_id) if row.opportunity_id else None,
        ))

    return TendersList(items=items, total=total, page=page, page_size=page_size)


@router.get("/tenders/provinces")
async def list_tender_provinces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Tender.province).distinct().where(Tender.province.isnot(None)).order_by(Tender.province)
    )
    return [r[0] for r in result.all()]
