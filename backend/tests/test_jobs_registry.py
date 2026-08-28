"""Regression guard for the L8 defect.

The scheduler and the Admin Run Now endpoint kept separate hand-maintained
maps that had drifted: fix_corrupted_award_dates was schedulable but had no
trigger, so an operator noticing bad dates could not run the repair; and
backfill_tenders was triggerable through the API but appeared in no jobs list,
so no button rendered for it.

Both now derive from one registry.
"""

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.jobs.scheduler import DEFAULT_JOBS, JOBS


class TestRegistryIsConsistent:
    def test_every_job_is_listed_for_the_admin_page(self):
        assert set(DEFAULT_JOBS) == set(JOBS)

    def test_every_job_is_triggerable_or_says_why_not(self):
        for job in JOBS.values():
            assert job.triggerable, f"{job.name} cannot be run on demand"

    def test_every_schedulable_job_has_a_cron(self):
        for job in JOBS.values():
            if job.schedulable:
                assert job.default_cron, f"{job.name} is schedulable with no cron"

    def test_on_demand_jobs_have_no_cron(self):
        for job in JOBS.values():
            if not job.schedulable:
                assert not job.default_cron

    @pytest.mark.parametrize("name", sorted(JOBS))
    def test_the_default_cron_parses(self, name):
        """An invalid cron only produced a logger.warning at startup and the job
        was silently dropped."""
        job = JOBS[name]
        if job.schedulable:
            CronTrigger.from_crontab(job.default_cron)

    @pytest.mark.parametrize("name", sorted(JOBS))
    def test_every_handler_is_callable(self, name):
        job = JOBS[name]
        assert callable(job.handler)
        assert callable(job.on_demand)

    def test_run_now_may_differ_from_the_scheduled_pass(self):
        """Ingest Awards Now re-reads the full 30-day window, unlike the
        incremental scheduled run."""
        check_awards = JOBS["check_awards"]
        assert check_awards.on_demand is not check_awards.handler
        assert check_awards.on_demand.__name__ == "backfill_recent_awards"

    def test_jobs_that_do_nothing_useful_ship_disabled(self):
        """sync_crm fetches Monday activity and discards it; an enabled hourly
        job would make a real API call for a debug line."""
        assert JOBS["sync_crm"].enabled_by_default is False
        assert DEFAULT_JOBS["sync_crm"]["enabled"] is False


class TestTriggerEndpointCoversTheRegistry:
    @pytest.mark.parametrize("name", sorted(JOBS))
    def test_every_registered_job_can_be_triggered(self, name):
        job = JOBS.get(name)
        assert job is not None and job.triggerable

    def test_an_unknown_job_is_not_in_the_registry(self):
        assert JOBS.get("no_such_job") is None
