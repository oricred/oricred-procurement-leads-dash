from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.watchlist import WatchlistItem
from app.models.tender import Tender
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.models.category import Category
from app.schemas.watchlist import WatchlistItemRead, WatchlistList, WatchToggleRequest, WatchToggleResponse
from app.services.award_timing import AwardTimingService
from app.api.auth import get_current_user

router = APIRouter()


@router.get("", response_model=WatchlistList)
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    opportunity_subq = (
        select(Opportunity.id)
        .where(
            Opportunity.tender_id == WatchlistItem.tender_id,
            Opportunity.company_id.isnot(None),
        )
        .order_by(Opportunity.created_at.desc())
        .limit(1)
        .correlate(WatchlistItem)
        .scalar_subquery()
    )

    opportunity_count_subq = (
        select(func.count())
        .select_from(Opportunity)
        .where(
            Opportunity.tender_id == WatchlistItem.tender_id,
            Opportunity.company_id.isnot(None),
        )
        .correlate(WatchlistItem)
        .scalar_subquery()
    )

    result = await db.execute(
        select(
            WatchlistItem,
            Tender,
            opportunity_subq.label("opportunity_id"),
            opportunity_count_subq.label("opportunity_count"),
        )
        .join(Tender, WatchlistItem.tender_id == Tender.id)
        .where(WatchlistItem.status.in_(["watching", "awarded"]))
        .order_by(WatchlistItem.created_at.desc())
    )
    rows = result.all()

    items = []
    for wl, tender, opp_id, opp_count in rows:
        days_until = None
        days_over = None
        progress = None
        label = "On Track"

        if wl.expected_window_end:
            delta = (wl.expected_window_end - now).days
            if delta > 0:
                days_until = delta
            else:
                days_over = abs(delta)
                label = "Past Due" if wl.status == "past_due" else "Approaching Window"

        if wl.expected_window_start and wl.expected_window_end:
            total = (wl.expected_window_end - wl.expected_window_start).days
            elapsed = (now - wl.expected_window_start).days
            if total > 0:
                progress = min(100, max(0, int(elapsed / total * 100)))

        cat_name = None
        if tender.category_id:
            cat = await db.get(Category, tender.category_id)
            if cat:
                cat_name = cat.name

        items.append(WatchlistItemRead(
            id=str(wl.id),
            tender_id=str(tender.id),
            title=tender.title,
            estimated_value=tender.estimated_value,
            category=tender.category_id,
            category_name=cat_name,
            province=tender.province,
            buyer_org=tender.buyer_org_id,
            status=wl.status,
            expected_window_start=wl.expected_window_start,
            expected_window_end=wl.expected_window_end,
            closing_date=tender.closing_date,
            days_until_window=days_until,
            days_overdue=days_over,
            progress_pct=progress,
            label=label,
            opportunity_id=str(opp_id) if opp_id else None,
            opportunity_count=opp_count or 0,
        ))

    return WatchlistList(items=items, total=len(items))


@router.post("/toggle", response_model=WatchToggleResponse)
async def toggle_watchlist(
    body: WatchToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    tender_result = await db.execute(select(Tender).where(Tender.id == body.tender_id))
    tender = tender_result.scalar_one_or_none()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    existing = await db.execute(
        select(WatchlistItem).where(WatchlistItem.tender_id == body.tender_id)
    )
    wl = existing.scalar_one_or_none()

    if wl:
        await db.delete(wl)
        pd = await db.execute(
            select(PastDueQueue).where(PastDueQueue.tender_id == body.tender_id)
        )
        pd_item = pd.scalar_one_or_none()
        if pd_item:
            await db.delete(pd_item)
        await db.commit()
        return WatchToggleResponse(is_watching=False)
    else:
        timing = AwardTimingService(db)
        start, end = await timing.get_expected_window(
            tender.buyer_org_id, tender.category_id, tender.closing_date
        )
        db.add(WatchlistItem(
            tender_id=body.tender_id,
            status="watching",
            expected_window_start=start,
            expected_window_end=end,
            started_watching_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        return WatchToggleResponse(is_watching=True)
