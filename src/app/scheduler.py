from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

PORTFOLIO_SYNC_INTERVAL_HOURS = 24


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone="UTC")


def register_discovery_job(
    scheduler: AsyncIOScheduler,
    job: Callable[[], Awaitable[None]],
    interval_minutes: int,
) -> None:
    scheduler.add_job(
        job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="discovery_run",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("discovery job scheduled every {} minutes", interval_minutes)


def register_portfolio_sync_job(
    scheduler: AsyncIOScheduler,
    job: Callable[[], Awaitable[None]],
) -> None:
    scheduler.add_job(
        job,
        trigger=IntervalTrigger(hours=PORTFOLIO_SYNC_INTERVAL_HOURS),
        id="portfolio_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("portfolio sync job scheduled every {} hours", PORTFOLIO_SYNC_INTERVAL_HOURS)
