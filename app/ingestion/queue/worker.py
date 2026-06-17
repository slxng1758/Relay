"""
ARQ worker entry point.

Runs the ingestion task functions (`app.ingestion.queue.tasks`) on demand and
on a periodic schedule derived from `settings.ingestion_poll_interval_seconds`.
Started via `python -m app.ingestion.queue.worker` (see
`infra/docker/Dockerfile.worker`).
"""
from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings
from arq.worker import run_worker

from app.core.config import settings
from app.core.database import close_db
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, parse_redis_settings
from app.ingestion.queue.tasks import (
    ingest_github,
    ingest_gdocs,
    ingest_jira,
    ingest_slack,
    process_github_event,
    process_slack_event,
)

logger = get_logger(__name__)


def _poll_minutes() -> set[int]:
    """Convert the poll interval into the set of minutes-past-the-hour to run on.

    arq cron schedules are calendar-based rather than interval-based, so a
    900s interval becomes {0, 15, 30, 45}. Intervals of an hour or more run
    once on the hour.
    """
    interval_minutes = max(1, settings.ingestion_poll_interval_seconds // 60)
    if interval_minutes >= 60:
        return {0}
    return set(range(0, 60, interval_minutes))


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_db()
    await close_redis()
    logger.info("worker.shutdown")


_POLL_MINUTES = _poll_minutes()


class WorkerSettings:
    functions = [
        ingest_slack,
        ingest_github,
        ingest_jira,
        ingest_gdocs,
        process_slack_event,
        process_github_event,
    ]
    cron_jobs = [
        cron(ingest_slack, minute=_POLL_MINUTES, second=0),
        cron(ingest_github, minute=_POLL_MINUTES, second=0),
        cron(ingest_jira, minute=_POLL_MINUTES, second=0),
        cron(ingest_gdocs, minute=_POLL_MINUTES, second=0),
    ]
    redis_settings: RedisSettings = parse_redis_settings(settings.redis_queue_url)
    on_startup = startup
    on_shutdown = shutdown


if __name__ == "__main__":
    run_worker(WorkerSettings)
