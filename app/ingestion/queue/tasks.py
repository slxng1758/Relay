"""
ARQ task functions for ingestion.

Enqueued by the ingestion API (`app/api/routes/ingestion.py`) for manual
triggers and webhook events, and run by the worker
(`app/ingestion/queue/worker.py`) for scheduled syncs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.core.redis import CHANNEL_INGESTION_STATUS, publish_event
from app.ingestion.base_connector import BaseConnector, IngestionStats

logger = get_logger(__name__)


async def _run_sync(source: str, connector: BaseConnector, full_sync: bool) -> dict[str, Any]:
    try:
        stats = await connector.sync(full_sync=full_sync)
        status = "completed" if not stats.errors else "completed_with_errors"
    except Exception as exc:
        logger.error("ingestion.sync.failed", source=source, error=str(exc))
        stats = IngestionStats(errors=[str(exc)])
        status = "failed"

    result = {
        "source": source,
        "status": status,
        "nodes_created": stats.nodes_created,
        "nodes_updated": stats.nodes_updated,
        "edges_created": stats.edges_created,
        "errors": stats.errors,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await publish_event(CHANNEL_INGESTION_STATUS, result)
    return result


async def ingest_slack(ctx: dict[str, Any], full_sync: bool = False) -> dict[str, Any]:
    from app.ingestion.connectors.slack.connector import SlackConnector

    return await _run_sync("slack", SlackConnector(), full_sync)


async def ingest_github(ctx: dict[str, Any], full_sync: bool = False) -> dict[str, Any]:
    from app.ingestion.connectors.github.connector import GitHubConnector

    return await _run_sync("github", GitHubConnector(), full_sync)


async def ingest_jira(ctx: dict[str, Any], full_sync: bool = False) -> dict[str, Any]:
    from app.ingestion.connectors.jira.connector import JiraConnector

    return await _run_sync("jira", JiraConnector(), full_sync)


async def ingest_gdocs(ctx: dict[str, Any], full_sync: bool = False) -> dict[str, Any]:
    from app.ingestion.connectors.gdocs.connector import GDocsConnector

    return await _run_sync("gdocs", GDocsConnector(), full_sync)


async def process_slack_event(ctx: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    from app.ingestion.connectors.slack.connector import SlackConnector

    stats = await SlackConnector().handle_event(event)
    return {"source": "slack", "status": "processed", **stats.__dict__}


async def process_github_event(
    ctx: dict[str, Any], event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from app.ingestion.connectors.github.connector import GitHubConnector

    stats = await GitHubConnector().handle_event(event_type, payload)
    return {"source": "github", "status": "processed", "event_type": event_type, **stats.__dict__}
