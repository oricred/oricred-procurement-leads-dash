from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.opportunity import Opportunity
from app.models.watchlist import WatchlistItem
from app.models.past_due import PastDueQueue
from app.schemas.dashboard import DashboardStats, StageCount
from app.workflow import WORKFLOW_STAGES, normalize_stage

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Opportunity.kanban_stage, func.count())
        .group_by(Opportunity.kanban_stage)
    )
    stage_counts: dict[str, int] = {}
    for stage, count in result.all():
        normalized = normalize_stage(stage) or stage
        stage_counts[normalized] = stage_counts.get(normalized, 0) + count

    stages = [
        StageCount(stage=s, count=stage_counts.get(s, 0))
        for s in WORKFLOW_STAGES
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

