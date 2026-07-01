from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.past_due import PastDueQueue
from app.models.tender import Tender

router = APIRouter()


@router.get("")
async def list_past_due(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PastDueQueue, Tender)
        .join(Tender, PastDueQueue.tender_id == Tender.id)
        .order_by(PastDueQueue.entered_queue_at.desc())
    )
    rows = result.all()
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
                "days_in_queue": (datetime.now(timezone.utc) - pdq.entered_queue_at).days,
            }
            for pdq, tender in rows
        ]
    }
