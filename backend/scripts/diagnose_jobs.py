"""Diagnose failing scheduled jobs against whatever database this environment points at.

    cd backend && .venv/bin/python scripts/diagnose_jobs.py
    cd backend && .venv/bin/python scripts/diagnose_jobs.py --limit 200
    cd backend && .venv/bin/python scripts/diagnose_jobs.py --job check_awards
    cd backend && .venv/bin/python scripts/diagnose_jobs.py --no-probe

STRICTLY READ-ONLY. It issues SELECTs against the Oricred database and a single
`SELECT 1` against the Tenders-SA database. It does not write, commit, or alter
anything on either. Run it on the host that serves the API, with the same
environment the API process has, so it reads the same databases and the same
configuration.

`job_runs.error` is truncated to 500 characters by run_job, so this shows the
exception type and message but not the traceback. The traceback is in the
service log:

    journalctl -u oricred-backend.service --since '24 hours ago' | grep -A 30 job_failed

It separates the failures that all surface in Admin -> Jobs as one red row:

  1. the job never ran at all — disabled in config, an unparseable cron, or the
     scheduler never started (no `scheduler_configured` line at boot),
  2. every job that touches the Tenders-SA database fails and the rest succeed —
     one broken connection, not eight broken jobs,
  3. every job fails including the ones that never leave the Oricred database
     (refresh_timing_model, fix_corrupted_award_dates) — the Oricred database,
     the schema, or the process itself,
  4. one job fails on its own — its own bug, and the error text says which.

No password or secret is ever printed.
"""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from app.config import REQUIRED_IN_PRODUCTION, assert_production_safe, settings
from app.database import async_session, engine
from app.jobs.scheduler import DEFAULT_JOBS, JOBS, _job_config
from app.models.job_run import JobRun
from app.services.admin_config import get_config

# Jobs that never open a Tenders-SA connection. If these fail too, the fault is
# not the remote database.
LOCAL_ONLY_JOBS = frozenset({"refresh_timing_model", "fix_corrupted_award_dates", "sync_crm"})


def _describe(url: str) -> str:
    """Host and database name only — never the password."""
    if not url:
        return "(unset)"
    parts = urlsplit(url)
    host = parts.hostname or "(local file)"
    port = f":{parts.port}" if parts.port else ""
    name = (parts.path or "").lstrip("/") or "(none)"
    return f"{parts.scheme} -> {host}{port}/{name}"


def _age(when: datetime | None, now: datetime) -> str:
    if not when:
        return "never"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = now - when
    if delta < timedelta(minutes=1):
        return f"{int(delta.total_seconds())}s ago"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)}h ago"
    return f"{delta.days}d ago"


def show_environment() -> None:
    print("-- Environment --")
    print(f"  Oricred DB     : {_describe(settings.database_url)}")
    print(f"  Tenders-SA DB  : {_describe(settings.tsa_database_url)}")
    print(f"  ORICRED_DEBUG  : {settings.debug}")
    if settings.debug:
        print("    debug is on, so assert_production_safe() is a no-op — this is not a")
        print("    production configuration.")
    try:
        assert_production_safe(settings)
        print("  Config guard   : passes")
    except RuntimeError as exc:
        print("  Config guard   : FAILS — the app would refuse to start:")
        for line in str(exc).splitlines():
            print(f"      {line}")
    missing = [n for n in REQUIRED_IN_PRODUCTION if not str(getattr(settings, n)).strip()]
    if missing:
        print(f"  Unset required : {', '.join(missing)}")
    print()


async def probe_databases(probe_tsa: bool) -> None:
    print("-- Connectivity --")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("  Oricred DB     : reachable")
    except Exception as exc:
        print(f"  Oricred DB     : UNREACHABLE — {type(exc).__name__}: {exc}")
        print("    Every job fails at its first query when this is down.")

    if not probe_tsa:
        print("  Tenders-SA DB  : skipped (--no-probe)")
        print()
        return
    if not settings.tsa_database_url:
        print("  Tenders-SA DB  : ORICRED_TSA_DATABASE_URL is unset — every ingestion job")
        print("                   fails when it constructs TSADatabase().")
        print()
        return

    from app.clients.tsa_db import TSADatabase

    tsa = TSADatabase()
    try:
        async with tsa._session_factory() as session:  # read-only SELECT 1
            await session.execute(text("SELECT 1"))
        print("  Tenders-SA DB  : reachable (read-only SELECT 1)")
    except Exception as exc:
        print(f"  Tenders-SA DB  : UNREACHABLE — {type(exc).__name__}: {exc}")
        print("    This alone fails discover_tenders, check_awards, contact_enrichment,")
        print("    historical_contacts and all three backfills.")
    finally:
        await tsa.close()
    print()


async def show_schedule() -> None:
    print("-- Effective schedule --")
    async with async_session() as db:
        config = await get_config("admin_jobs", db)

    if not config:
        print("  No admin_jobs config row — every job uses its built-in default.")

    for job in JOBS.values():
        if not job.schedulable:
            print(f"  {job.name:<28} on-demand only")
            continue
        merged = _job_config(config, job.name)
        enabled = merged.get("enabled", job.enabled_by_default)
        cron = str(merged.get("cron") or job.default_cron)
        overridden = isinstance(config.get(job.name), dict)
        note = " (overridden in admin config)" if overridden else ""
        if not enabled:
            print(f"  {job.name:<28} DISABLED — never scheduled{note}")
            continue
        try:
            CronTrigger.from_crontab(cron)
        except (TypeError, ValueError) as exc:
            print(f"  {job.name:<28} BAD CRON {cron!r} — skipped at configure time ({exc}){note}")
            print("      The scheduler logs invalid_job_cron and moves on, so this job")
            print("      silently never runs.")
            continue
        print(f"  {job.name:<28} enabled  cron={cron}{note}")
    print()
    print("  A job listed as enabled here is only actually registered if the boot log")
    print("  shows it: journalctl -u oricred-backend.service | grep scheduler_configured")
    print()


async def show_history(limit: int, only_job: str | None) -> None:
    now = datetime.now(timezone.utc)
    stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    if only_job:
        stmt = (
            select(JobRun)
            .where(JobRun.job_name == only_job)
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        )
    async with async_session() as db:
        runs = list((await db.execute(stmt)).scalars().all())

    print(f"-- Last {len(runs)} run(s) --")
    if not runs:
        print("  The job_runs table is empty for this filter.")
        print("  Nothing has been recorded, so the jobs are not failing — they are not")
        print("  starting. Check the schedule above and the boot log.")
        print()
        return

    by_job: dict[str, list[JobRun]] = {}
    for run in runs:
        by_job.setdefault(run.job_name, []).append(run)

    for name in sorted(by_job):
        history = by_job[name]
        latest = history[0]
        counts = Counter(r.status or "unknown" for r in history)
        tally = "  ".join(f"{status}={count}" for status, count in sorted(counts.items()))
        scope = "local-only" if name in LOCAL_ONLY_JOBS else "needs Tenders-SA"
        print(f"  {name}  [{scope}]")
        print(f"    last: {latest.status} {_age(latest.started_at, now)}   {tally}")
        if latest.status == "running" and latest.finished_at is None:
            print("    still marked running — the process died mid-job, or max_instances=1")
            print("    is now blocking every subsequent fire of this job.")
        errors = [r.error for r in history if r.error]
        for message in list(dict.fromkeys(errors))[:3]:
            print(f"    error: {message}")
        if errors:
            print("    (truncated to 500 chars by run_job — full traceback in journalctl)")
        print()

    never_ran = [job.name for job in JOBS.values() if job.schedulable and job.name not in by_job]
    if never_ran and not only_job:
        print(f"  No run recorded in this window: {', '.join(never_ran)}")
        print()


def show_next_step() -> None:
    print("-- Next step --")
    print("  Pair this with the traceback for the same job and timestamp:")
    print("    journalctl -u oricred-backend.service --since '24 hours ago' \\")
    print("      | grep -B 5 -A 40 job_failed | tail -200")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=100, help="job_runs rows to read (default 100)"
    )
    parser.add_argument("--job", help="restrict the history to one job name")
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="skip the read-only SELECT 1 against the Tenders-SA database",
    )
    args = parser.parse_args()

    if args.job and args.job not in DEFAULT_JOBS:
        print(f"Unknown job {args.job!r}. Known: {', '.join(sorted(DEFAULT_JOBS))}")
        return

    show_environment()
    await probe_databases(probe_tsa=not args.no_probe)
    await show_schedule()
    await show_history(args.limit, args.job)
    show_next_step()


if __name__ == "__main__":
    asyncio.run(main())
