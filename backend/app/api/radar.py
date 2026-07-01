from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.award import Award
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.schemas.radar import RadarAward, RadarData

router = APIRouter()


@router.get("", response_model=RadarData)
async def get_radar(db: AsyncSession = Depends(get_db)):
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    result = await db.execute(
        select(Award, Tender)
        .join(Tender, Award.tender_id == Tender.id)
        .where(Award.discovered_at >= seven_days_ago)
        .order_by(Award.discovered_at.desc())
        .limit(50)
    )
    rows = result.all()

    awards = []
    for award, tender in rows:
        awards.append(RadarAward(
            id=str(award.id),
            tender_title=tender.title,
            supplier_name=award.supplier_name,
            amount=award.amount,
            award_date=award.award_date,
            buyer_org=tender.buyer_org_id,
            passed_filter=True,
        ))

    count_result = await db.execute(select(func.count()).select_from(PastDueQueue))
    past_due_count = count_result.scalar() or 0

    return RadarData(awards=awards, past_due_count=past_due_count)
