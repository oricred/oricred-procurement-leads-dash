"""A job's outcome must reach job_runs even when the database is the problem.

run_job used to open its session and write the "running" row *above* the try
block. When the connection pool was exhausted — which is exactly what a long
ingest pass caused — that insert raised before the handler was reached: no row
was written, the exception went to APScheduler, and Admin -> Jobs showed
nothing. The jobs looked unscheduled rather than failing, which is the opposite
of what an operator needs to see.

Bookkeeping is now best-effort on both ends, and the closing write inserts a row
if the opening one never landed.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs import scheduler as scheduler_module
from app.models.job_run import JobRun


@pytest.fixture
async def sessions(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler_module, "async_session", factory)
    yield factory
    await engine.dispose()


async def _runs(sessions) -> list[JobRun]:
    async with sessions() as db:
        return list((await db.execute(select(JobRun))).scalars().all())


async def test_a_successful_job_records_its_count(sessions):
    async def handler():
        return 42

    await scheduler_module.run_job("demo", handler)

    run = (await _runs(sessions))[0]
    assert run.status == "success"
    assert run.items_processed == 42
    assert run.error is None
    assert run.finished_at is not None


async def test_a_failing_job_records_the_error(sessions):
    async def handler():
        raise RuntimeError("QueuePool limit of size 5 overflow 10 reached")

    await scheduler_module.run_job("demo", handler)

    run = (await _runs(sessions))[0]
    assert run.status == "failed"
    assert "QueuePool limit" in run.error
    assert run.finished_at is not None


async def test_the_error_is_truncated_to_the_column_width(sessions):
    async def handler():
        raise RuntimeError("x" * 5_000)

    await scheduler_module.run_job("demo", handler)

    assert len((await _runs(sessions))[0].error) == 500


async def test_a_failure_is_recorded_even_when_the_opening_write_could_not_be(
    sessions, monkeypatch
):
    """The regression: a pool timeout on the bookkeeping must not erase the outcome."""
    calls = {"n": 0}
    real = scheduler_module.async_session

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("QueuePool limit of size 5 overflow 10 reached")
        return real()

    monkeypatch.setattr(scheduler_module, "async_session", flaky)

    async def handler():
        raise ValueError("the real failure")

    await scheduler_module.run_job("demo", handler)

    runs = await _runs(sessions)
    assert len(runs) == 1, "the outcome must still be recorded, exactly once"
    assert runs[0].status == "failed"
    assert "the real failure" in runs[0].error


async def test_the_handler_still_runs_when_the_opening_write_fails(sessions, monkeypatch):
    """Bookkeeping must never decide whether the job runs."""
    calls = {"n": 0}
    real = scheduler_module.async_session
    ran = {"yes": False}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("pool exhausted")
        return real()

    monkeypatch.setattr(scheduler_module, "async_session", flaky)

    async def handler():
        ran["yes"] = True
        return 7

    await scheduler_module.run_job("demo", handler)

    assert ran["yes"]
    assert (await _runs(sessions))[0].items_processed == 7


async def test_a_successful_job_does_not_raise_when_the_result_cannot_be_written(
    sessions, monkeypatch
):
    """A job that worked must not be turned into a crash by the bookkeeping."""
    calls = {"n": 0}
    real = scheduler_module.async_session

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("pool exhausted on the way out")
        return real()

    monkeypatch.setattr(scheduler_module, "async_session", flaky)

    async def handler():
        return 1

    await scheduler_module.run_job("demo", handler)  # must not raise

    assert (await _runs(sessions))[0].status == "running"


async def test_a_skipped_execution_is_recorded(sessions):
    """max_instances=1 skips are not exceptions, so nothing used to record them."""
    await scheduler_module._record_finish(
        None,
        "discover_tenders",
        datetime.now(timezone.utc),
        "skipped",
        error="previous run still in progress",
    )

    run = (await _runs(sessions))[0]
    assert run.job_name == "discover_tenders"
    assert run.status == "skipped"
    assert run.error == "previous run still in progress"
