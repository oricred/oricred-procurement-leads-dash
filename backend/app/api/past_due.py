from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.models.tender import Tender

router = APIRouter()


def _as_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    PostgreSQL round-trips DateTime(timezone=True) as aware; SQLite discards the
    offset. Subtracting one from the other raises.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("")
async def list_past_due(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    # Correlated subquery rather than an outer join. past_due_queue.tender_id is
    # not unique against opportunities.tender_id, so a tender with two
    # opportunities produced two rows for one past-due entry.
    opportunity_id = (
        select(Opportunity.id)
        .where(Opportunity.tender_id == PastDueQueue.tender_id)
        .order_by(Opportunity.created_at.desc())
        .limit(1)
        .correlate(PastDueQueue)
        .scalar_subquery()
    )

    base = (
        select(PastDueQueue, Tender, opportunity_id.label("opportunity_id"))
        .join(Tender, PastDueQueue.tender_id == Tender.id)
    )
    total = await db.scalar(
        select(func.count()).select_from(select(PastDueQueue.id).join(
            Tender, PastDueQueue.tender_id == Tender.id
        ).subquery())
    ) or 0

    rows = (
        await db.execute(
            base.order_by(PastDueQueue.entered_queue_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    now = datetime.now(timezone.utc)
    return {
        "items": [
            {
                "id": str(pdq.id),
                "tender_id": str(pdq.tender_id),
                "tender_title": tender.title,
                "estimated_value": float(tender.estimated_value) if tender.estimated_value else None,
                "province": tender.province,
                "buyer_org": tender.buyer_org_id,
                "entered_queue_at": pdq.entered_queue_at.isoformat(),
                "poll_count_since_due": pdq.poll_count_since_due,
                "resolution": pdq.resolution or "pending",
                "days_in_queue": (now - _as_aware(pdq.entered_queue_at)).days,
                "opportunity_id": str(opp_id) if opp_id else None,
            }
            for pdq, tender, opp_id in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
