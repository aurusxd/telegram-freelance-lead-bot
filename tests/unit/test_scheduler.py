import asyncio

from app.scheduler import (
    PORTFOLIO_SYNC_INTERVAL_HOURS,
    create_scheduler,
    register_discovery_job,
    register_portfolio_sync_job,
)


async def noop_job() -> None:
    await asyncio.sleep(0)


def test_discovery_job_registered_with_configured_interval() -> None:
    scheduler = create_scheduler()

    register_discovery_job(scheduler, noop_job, interval_minutes=10)

    job = scheduler.get_job("discovery_run")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 600
    assert job.max_instances == 1
    assert job.coalesce is True


async def test_repeated_registration_replaces_the_job() -> None:
    scheduler = create_scheduler()
    scheduler.start(paused=True)

    register_discovery_job(scheduler, noop_job, interval_minutes=10)
    register_discovery_job(scheduler, noop_job, interval_minutes=30)

    jobs = [job for job in scheduler.get_jobs() if job.id == "discovery_run"]
    scheduler.shutdown(wait=False)
    assert len(jobs) == 1
    assert jobs[0].trigger.interval.total_seconds() == 1800


def test_portfolio_sync_job_registered_daily() -> None:
    scheduler = create_scheduler()

    register_portfolio_sync_job(scheduler, noop_job)

    job = scheduler.get_job("portfolio_sync")
    assert job is not None
    assert job.trigger.interval.total_seconds() == PORTFOLIO_SYNC_INTERVAL_HOURS * 3600
