from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.watchlist import WatchlistItem
from app.models.past_due import PastDueQueue
from app.schemas.dashboard import DashboardStats, StageCount

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity.kanban_stage, func.count())
        .group_by(Opportunity.kanban_stage)
    )
    stage_counts = {stage: count for stage, count in result.all()}

    stages = [
        StageCount(stage=s, count=stage_counts.get(s, 0))
        for s in ["new", "assigned", "contacted", "in_discussion", "application_received", "funded", "closed"]
    ]

    total_result = await db.execute(select(func.count()).select_from(Opportunity))
    total = total_result.scalar() or 0

    watch_result = await db.execute(
        select(func.count()).where(WatchlistItem.status == "watching")
    )
    watching = watch_result.scalar() or 0

    pd_result = await db.execute(select(func.count()).select_from(PastDueQueue))
    past_due = pd_result.scalar() or 0

    return DashboardStats(stages=stages, total_opportunities=total, total_watching=watching, past_due_count=past_due)
