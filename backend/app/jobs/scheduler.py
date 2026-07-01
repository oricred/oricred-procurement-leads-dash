import asyncio
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import async_session
from app.jobs.discovery import discover_new_tenders
from app.jobs.award_check import check_awards_for_watching
from app.jobs.model_refresh import refresh_timing_model
from app.jobs.crm_sync import sync_crm
from app.models.job_run import JobRun

logger = structlog.get_logger()


async def run_job(job_name: str, handler):
    async with async_session() as db:
        run = JobRun(job_name=job_name, started_at=datetime.now(timezone.utc), status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)

    try:
        await handler()
        async with async_session() as db:
            result = await db.get(JobRun, run.id)
            if result:
                result.status = "success"
                result.finished_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception as e:
        logger.exception("job_failed", job=job_name, error=str(e))
        async with async_session() as db:
            result = await db.get(JobRun, run.id)
            if result:
                result.status = "failed"
                result.error = str(e)[:500]
                result.finished_at = datetime.now(timezone.utc)
                await db.commit()


def start_scheduler():
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        run_job, "cron", minute="*/15",
        args=["discover_tenders", discover_new_tenders],
        id="discover_tenders", name="Discover new tenders",
    )
    scheduler.add_job(
        run_job, "cron", minute="0",
        args=["check_awards", check_awards_for_watching],
        id="check_awards", name="Check awards for watching tenders",
    )
    scheduler.add_job(
        run_job, "cron", day_of_week="sun", hour="2", minute="0",
        args=["refresh_timing_model", refresh_timing_model],
        id="refresh_timing_model", name="Refresh award timing model",
    )

    scheduler.add_job(
        run_job, "cron", hour="*", minute="30",
        args=["sync_crm", sync_crm],
        id="sync_crm", name="Sync CRM activity",
    )

    scheduler.start()
    logger.info("scheduler_started", jobs=["discover_tenders", "check_awards", "refresh_timing_model", "sync_crm"])
    return scheduler
