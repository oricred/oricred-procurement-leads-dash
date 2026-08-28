from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import async_session
from app.jobs.award_check import (
    backfill_recent_awards,
    check_awards_for_watching,
    fix_corrupted_award_dates,
)
from app.jobs.contact_enrichment import run_contact_enrichment
from app.jobs.crm_sync import sync_crm
from app.jobs.discovery import discover_new_tenders
from app.jobs.historical_contacts import sync_historical_contacts_job
from app.jobs.model_refresh import refresh_timing_model
from app.jobs.tender_backfill import backfill_stub_tenders
from app.models.job_run import JobRun
from app.services.admin_config import get_config

logger = structlog.get_logger()
scheduler: AsyncIOScheduler | None = None

JobHandler = Callable[[], Awaitable[object | None]]


@dataclass(frozen=True)
class JobDefinition:
    """One scheduled or on-demand job.

    Single source of truth for the scheduler, the Admin -> Jobs list and the
    Run Now endpoint. These were three hand-maintained maps that had drifted:
    fix_corrupted_award_dates was schedulable but had no trigger, and
    backfill_tenders was triggerable but appeared in no jobs list.
    """

    name: str
    label: str
    description: str
    handler: JobHandler
    default_cron: str = ""
    # Run Now sometimes means something stronger than the scheduled pass —
    # "Ingest Awards Now" re-reads the full 30-day window.
    manual_handler: JobHandler | None = None
    schedulable: bool = True
    triggerable: bool = True
    # Jobs that run but do nothing useful yet ship disabled.
    enabled_by_default: bool = True

    @property
    def on_demand(self) -> JobHandler:
        return self.manual_handler or self.handler


JOBS: dict[str, JobDefinition] = {
    job.name: job
    for job in (
        JobDefinition(
            "discover_tenders", "Discover new tenders",
            "Poll Tenders-SA for new tenders",
            discover_new_tenders, "*/15 * * * *",
        ),
        JobDefinition(
            "check_awards", "Ingest Tenders-SA awards",
            "Ingest Tenders-SA awards incrementally",
            check_awards_for_watching, "*/30 * * * *",
            manual_handler=backfill_recent_awards,
        ),
        JobDefinition(
            "refresh_timing_model", "Refresh award timing model",
            "Recompute award-timing model",
            refresh_timing_model, "0 2 * * 0",
        ),
        JobDefinition(
            "sync_crm", "Sync CRM activity",
            "Pull Monday.com activity (inbound sync not implemented)",
            sync_crm, "30 * * * *",
            # pull_crm_activity fetches activity and discards it, so an enabled
            # hourly job would make a real API call for a debug line.
            enabled_by_default=False,
        ),
        JobDefinition(
            "contact_enrichment", "Enrich contacts from Tenders-SA",
            "Pull directors and key personnel for tracked companies",
            run_contact_enrichment, "0 3 * * 1,4",
        ),
        JobDefinition(
            "historical_contacts", "Sync historical awarded companies",
            "Import historical awarded companies and contacts",
            sync_historical_contacts_job, "30 2 * * *",
        ),
        JobDefinition(
            "fix_corrupted_award_dates", "Fix corrupted award dates",
            "Repair awards with a missing, future or synthesised date",
            fix_corrupted_award_dates, "0 4 * * *",
        ),
        JobDefinition(
            "backfill_tenders", "Backfill stub tenders",
            "Re-fetch metadata for tenders created from awards",
            backfill_stub_tenders,
            schedulable=False,
        ),
    )
}

# The Admin -> Jobs list, derived rather than duplicated. On-demand jobs appear
# too, with an empty cron, so they get a Run Now button — backfill_tenders was
# triggerable through the API but rendered nowhere.
DEFAULT_JOBS: dict[str, dict] = {
    job.name: {
        "enabled": job.enabled_by_default,
        "cron": job.default_cron,
        "description": job.description,
        "schedulable": job.schedulable,
    }
    for job in JOBS.values()
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

    for job in JOBS.values():
        if not job.schedulable:
            continue
        if active_scheduler.get_job(job.name):
            active_scheduler.remove_job(job.name)
        job_config = _job_config(config, job.name)
        if not job_config.get("enabled", job.enabled_by_default):
            continue
        try:
            trigger = CronTrigger.from_crontab(str(job_config.get("cron") or job.default_cron))
        except (TypeError, ValueError):
            logger.warning("invalid_job_cron", job=job.name, cron=job_config.get("cron"))
            continue
        active_scheduler.add_job(
            run_job,
            trigger,
            args=[job.name, job.handler],
            id=job.name,
            name=job.label,
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
