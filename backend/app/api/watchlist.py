from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.watchlist import WatchlistItem
from app.models.tender import Tender
from app.schemas.watchlist import WatchlistItemRead, WatchlistList

router = APIRouter()


@router.get("", response_model=WatchlistList)
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(WatchlistItem, Tender)
        .join(Tender, WatchlistItem.tender_id == Tender.id)
        .where(WatchlistItem.status.in_(["watching", "past_due"]))
        .order_by(WatchlistItem.created_at.desc())
    )
    rows = result.all()

    items = []
    for wl, tender in rows:
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

        items.append(WatchlistItemRead(
            id=str(wl.id),
            tender_id=str(tender.id),
            title=tender.title,
            estimated_value=tender.estimated_value,
            category=tender.category_id,
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
        ))

    return WatchlistList(items=items, total=len(items))
