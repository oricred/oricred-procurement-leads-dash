from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.utils import as_utc

router = APIRouter()


@router.get("")
async def list_past_due(db: AsyncSession = Depends(get_db)):
    opportunity_id = (
        select(Opportunity.id)
        .where(Opportunity.tender_id == Tender.id)
        .order_by(Opportunity.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(PastDueQueue, Tender, opportunity_id.label("opportunity_id"))
        .join(Tender, PastDueQueue.tender_id == Tender.id)
        .where(PastDueQueue.resolution == "pending")
        .order_by(PastDueQueue.entered_queue_at.desc())
    )
    return {"items": [
        {
            "id": str(pdq.id), "tender_id": str(pdq.tender_id), "tender_title": tender.title,
            "estimated_value": float(tender.estimated_value) if tender.estimated_value else None,
            "province": tender.province, "buyer_org": tender.buyer_org_id,
            "entered_queue_at": pdq.entered_queue_at.isoformat(),
            "poll_count_since_due": pdq.poll_count_since_due, "resolution": pdq.resolution or "pending",
            "days_in_queue": (datetime.now(timezone.utc) - as_utc(pdq.entered_queue_at)).days,
            "opportunity_id": str(opportunity_id) if opportunity_id else None,
        }
        for pdq, tender, opportunity_id in result.all()
    ]}
