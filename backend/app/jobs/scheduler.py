from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import async_session
from app.jobs.award_check import check_awards_for_watching
from app.jobs.contact_enrichment import run_contact_enrichment
from app.jobs.crm_sync import sync_crm
from app.jobs.discovery import discover_new_tenders
from app.jobs.historical_contacts import sync_historical_contacts_job
from app.jobs.model_refresh import refresh_timing_model
from app.models.job_run import JobRun
from app.services.admin_config import DEFAULT_JOBS, get_config

logger = structlog.get_logger()
scheduler: AsyncIOScheduler | None = None

JobHandler = Callable[[], Awaitable[object | None]]
JOB_HANDLERS: dict[str, tuple[str, JobHandler]] = {
    "discover_tenders": ("Discover new tenders", discover_new_tenders),
    "check_awards": ("Ingest Tenders-SA awards", check_awards_for_watching),
    "refresh_timing_model": ("Refresh award timing model", refresh_timing_model),
    "sync_crm": ("Sync CRM activity", sync_crm),
    "contact_enrichment": ("Enrich contacts from TSA DB", run_contact_enrichment),
    "historical_contacts": ("Sync historical awarded companies", sync_historical_contacts_job),
}


async def run_job(job_name: str, handler: JobHandler):
    async with async_session() as db:
        run = JobRun(job_name=job_name, started_at=datetime.now(timezone.utc), status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)

    try:
        result = await handler()
        processed = result if isinstance(result, int) else None
        async with async_session() as db:
            record = await db.get(JobRun, run.id)
            if record:
                record.status = "success"
                record.items_processed = processed
                record.finished_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception as exc:
        logger.exception("job_failed", job=job_name, error=str(exc))
        async with async_session() as db:
            record = await db.get(JobRun, run.id)
            if record:
                record.status = "failed"
                record.error = str(exc)[:500]
                record.finished_at = datetime.now(timezone.utc)
                await db.commit()


def _job_config(config: dict, job_name: str) -> dict:
    fallback = DEFAULT_JOBS.get(job_name, {})
    configured = config.get(job_name, {}) if isinstance(config.get(job_name), dict) else {}
    return {**fallback, **configured}


async def configure_scheduler(active_scheduler: AsyncIOScheduler) -> None:
    async with async_session() as db:
        config = await get_config("admin_jobs", db)

    for job_name, (label, handler) in JOB_HANDLERS.items():
        active_scheduler.remove_job(job_name) if active_scheduler.get_job(job_name) else None
        job_config = _job_config(config, job_name)
        if not job_config.get("enabled", True):
            continue
        try:
            trigger = CronTrigger.from_crontab(str(job_config.get("cron", DEFAULT_JOBS[job_name]["cron"])))
        except (TypeError, ValueError):
            logger.warning("invalid_job_cron", job=job_name, cron=job_config.get("cron"))
            continue
        active_scheduler.add_job(
            run_job,
            trigger,
            args=[job_name, handler],
            id=job_name,
            name=label,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    logger.info("scheduler_configured", jobs=[job.id for job in active_scheduler.get_jobs()])


async def start_scheduler() -> AsyncIOScheduler:
    global scheduler
    scheduler = AsyncIOScheduler()
    await configure_scheduler(scheduler)
    scheduler.start()
    return scheduler


async def reload_scheduler() -> None:
    if scheduler:
        await configure_scheduler(scheduler)
