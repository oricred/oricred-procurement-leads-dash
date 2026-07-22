from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.award import Award
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.schemas.stats import (
    BuyerCount,
    CategoryCount,
    ProvinceCount,
    SourceCount,
    StageCount,
    StatusCount,
    StatsResponse,
    YearlyCount,
    YearlyValue,
)
from app.workflow import WORKFLOW_STAGES, normalize_stage

router = APIRouter()


@router.get("", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):

    # --- Awards per year ---
    rows = await db.execute(
        select(func.extract("YEAR", Award.award_date).label("year"), func.count().label("count"))
        .where(Award.award_date.isnot(None))
        .group_by(func.extract("YEAR", Award.award_date))
        .order_by(func.extract("YEAR", Award.award_date).desc())
    )
    awards_per_year = [YearlyCount(year=int(r.year), count=int(r.count)) for r in rows.all()]

    # --- Tenders per year ---
    tender_year = func.coalesce(Tender.published_at, Tender.closing_date, Tender.discovered_at)
    rows = await db.execute(
        select(func.extract("YEAR", tender_year).label("year"), func.count().label("count"))
        .group_by(func.extract("YEAR", tender_year))
        .order_by(func.extract("YEAR", tender_year).desc())
    )
    tenders_per_year = [YearlyCount(year=int(r.year), count=int(r.count)) for r in rows.all()]

    # --- Award value per year ---
    rows = await db.execute(
        select(
            func.extract("YEAR", Award.award_date).label("year"),
            func.sum(Award.amount).label("value"),
        )
        .where(Award.award_date.isnot(None), Award.amount.isnot(None))
        .group_by(func.extract("YEAR", Award.award_date))
        .order_by(func.extract("YEAR", Award.award_date).desc())
    )
    award_value_per_year = [
        YearlyValue(year=int(r.year), value=float(r.value)) for r in rows.all() if r.value is not None
    ]

    # --- Summary counts ---
    total_awards = (await db.execute(select(func.count()).select_from(Award))).scalar() or 0
    total_tenders = (await db.execute(select(func.count()).select_from(Tender))).scalar() or 0
    total_leads = (await db.execute(select(func.count()).select_from(Opportunity))).scalar() or 0
    total_watching = (
        await db.execute(
            select(func.count()).select_from(WatchlistItem).where(WatchlistItem.status == "watching")
        )
    ).scalar() or 0
    past_due_count = (await db.execute(select(func.count()).select_from(PastDueQueue))).scalar() or 0

    # --- Value stats ---
    sum_val = (await db.execute(select(func.sum(Award.amount)))).scalar()
    total_award_value = float(sum_val) if sum_val is not None else None
    avg_val = (await db.execute(select(func.avg(Award.amount)))).scalar()
    avg_award_value = float(avg_val) if avg_val is not None else None

    # --- Leads from awards ---
    leads_from_awards = (
        await db.execute(
            select(func.count()).select_from(Opportunity).where(Opportunity.award_id.isnot(None))
        )
    ).scalar() or 0
    conversion_rate = (leads_from_awards / total_awards * 100) if total_awards > 0 else 0.0

    # --- Pipeline stage breakdown ---
    stage_rows = await db.execute(
        select(Opportunity.kanban_stage, func.count()).group_by(Opportunity.kanban_stage)
    )
    stage_counts: dict[str, int] = {}
    for stage, count in stage_rows.all():
        normalized = normalize_stage(stage) or stage
        stage_counts[normalized] = stage_counts.get(normalized, 0) + count

    leads_per_stage = [
        StageCount(stage=s, count=stage_counts.get(s, 0)) for s in WORKFLOW_STAGES
    ]

    # --- Awards by province ---
    rows = await db.execute(
        select(Tender.province, func.count().label("count"))
        .select_from(Award)
        .join(Tender, Award.tender_id == Tender.id)
        .where(Tender.province.isnot(None))
        .group_by(Tender.province)
        .order_by(func.count().desc())
    )
    awards_by_province = [ProvinceCount(province=str(r.province), count=int(r.count)) for r in rows.all()]

    # --- Awards by source ---
    rows = await db.execute(
        select(Award.source, func.count().label("count"))
        .group_by(Award.source)
        .order_by(func.count().desc())
    )
    awards_by_source = [SourceCount(source=str(r.source), count=int(r.count)) for r in rows.all()]

    # --- Tenders by derived status ---
    all_tenders_count = total_tenders
    awarded_count = (
        await db.execute(
            select(func.count(func.distinct(Award.tender_id)))
        )
    ).scalar() or 0
    watching_count = (
        await db.execute(
            select(func.count()).select_from(WatchlistItem).where(WatchlistItem.status == "watching")
        )
    ).scalar() or 0
    tenders_by_status = [
        StatusCount(status="total", count=all_tenders_count),
        StatusCount(status="awarded", count=min(awarded_count, all_tenders_count)),
        StatusCount(status="watching", count=min(watching_count, all_tenders_count)),
        StatusCount(status="no_award", count=max(0, all_tenders_count - awarded_count)),
    ]

    # --- Top 10 buyers ---
    rows = await db.execute(
        select(Tender.buyer_org_id, func.count().label("count"))
        .select_from(Award)
        .join(Tender, Award.tender_id == Tender.id)
        .where(Tender.buyer_org_id.isnot(None))
        .group_by(Tender.buyer_org_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_buyers = [BuyerCount(buyer_org_id=str(r.buyer_org_id), count=int(r.count)) for r in rows.all()]

    # --- Top 10 categories ---
    rows = await db.execute(
        select(Tender.category_id, func.count().label("count"))
        .where(Tender.category_id.isnot(None))
        .group_by(Tender.category_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_categories = [
        CategoryCount(category_id=str(r.category_id), count=int(r.count)) for r in rows.all()
    ]

    return StatsResponse(
        awards_per_year=awards_per_year,
        tenders_per_year=tenders_per_year,
        award_value_per_year=award_value_per_year,
        total_awards=total_awards,
        total_tenders=total_tenders,
        total_leads=total_leads,
        total_watching=total_watching,
        past_due_count=past_due_count,
        total_award_value=total_award_value,
        avg_award_value=avg_award_value,
        leads_from_awards=leads_from_awards,
        conversion_rate=conversion_rate,
        leads_per_stage=leads_per_stage,
        awards_by_province=awards_by_province,
        awards_by_source=awards_by_source,
        tenders_by_status=tenders_by_status,
        top_buyers=top_buyers,
        top_categories=top_categories,
    )
