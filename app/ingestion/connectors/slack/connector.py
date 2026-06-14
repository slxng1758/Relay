"""
Slack connector.

Syncs workspace members into `Person` nodes (keyed by Slack user ID) and scans
the channels listed in `settings.slack_decision_channel_ids` for messages, which
become `Decision` nodes with an `AUTHORED` edge from their poster. Also handles
real-time `message` events delivered via the Slack Events API webhook.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import Decision, NodeType, Person, SourceSystem
from app.ingestion.base_connector import BaseConnector, IngestionStats
from app.ingestion.processors.embedding_processor import embed_node

logger = get_logger(__name__)


class SlackConnector(BaseConnector):
    source_system = SourceSystem.SLACK

    def __init__(self) -> None:
        self._client = AsyncWebClient(token=settings.slack_bot_token)

    async def sync(self, full_sync: bool = False) -> IngestionStats:
        stats = IngestionStats()
        await self._sync_users(stats)
        await self._sync_decision_channels(stats, full_sync=full_sync)
        logger.info("slack.sync.complete", **stats.__dict__)
        return stats

    # ── Users ────────────────────────────────────────────────────────────────

    async def _sync_users(self, stats: IngestionStats) -> None:
        cursor: str | None = None
        async with db_session() as session:
            while True:
                resp = await self._client.users_list(cursor=cursor, limit=200)
                for member in resp.get("members", []):
                    if member.get("is_bot") or member.get("deleted"):
                        continue

                    profile = member.get("profile", {})
                    _, created = await self.upsert_node(
                        session,
                        Person,
                        external_id=member["id"],
                        display_name=profile.get("real_name") or member.get("name", member["id"]),
                        email=profile.get("email"),
                        slack_user_id=member["id"],
                    )
                    stats.nodes_created += int(created)
                    stats.nodes_updated += int(not created)

                cursor = resp.get("response_metadata", {}).get("next_cursor") or None
                if not cursor:
                    break

    # ── Decision channels ────────────────────────────────────────────────────

    async def _sync_decision_channels(self, stats: IngestionStats, full_sync: bool) -> None:
        channel_ids = settings.slack_decision_channel_id_list
        if not channel_ids:
            return

        oldest = "0" if full_sync else str(datetime.now(timezone.utc).timestamp() - 86400)

        async with db_session() as session:
            for channel_id in channel_ids:
                cursor: str | None = None
                while True:
                    resp = await self._client.conversations_history(
                        channel=channel_id, cursor=cursor, oldest=oldest, limit=200
                    )
                    for message in resp.get("messages", []):
                        await self._ingest_message(session, channel_id, message, stats)

                    cursor = resp.get("response_metadata", {}).get("next_cursor") or None
                    if not cursor:
                        break

    async def _ingest_message(
        self,
        session: AsyncSession,
        channel_id: str,
        message: dict[str, Any],
        stats: IngestionStats,
    ) -> None:
        # Skip joins/leaves/edits and anything without text – not decision-worthy.
        if message.get("subtype") or not message.get("text"):
            return

        ts = message["ts"]
        text = message["text"]

        decision, created = await self.upsert_node(
            session,
            Decision,
            external_id=f"{channel_id}:{ts}",
            title=text.splitlines()[0][:512],
            summary=text,
            status="open",
            decided_at=datetime.fromtimestamp(float(ts), tz=timezone.utc),
            source_url=f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}",
        )
        stats.nodes_created += int(created)
        stats.nodes_updated += int(not created)

        author_id = message.get("user")
        if author_id:
            person = await self.get_node(session, Person, author_id)
            if person is None:
                person, person_created = await self.upsert_node(
                    session,
                    Person,
                    external_id=author_id,
                    display_name=author_id,
                    slack_user_id=author_id,
                )
                stats.nodes_created += int(person_created)

            _, edge_created = await self.upsert_edge(
                session,
                source_id=person.id,
                source_type=NodeType.PERSON,
                target_id=decision.id,
                target_type=NodeType.DECISION,
                edge_type=EdgeType.AUTHORED,
            )
            stats.edges_created += int(edge_created)

        await embed_node(session, decision.id, NodeType.DECISION, text)

    # ── Real-time events ─────────────────────────────────────────────────────

    async def handle_event(self, event: dict[str, Any]) -> IngestionStats:
        """Handle a Slack Events API callback (e.g. `message` in a decision channel)."""
        stats = IngestionStats()
        inner = event.get("event", event)

        if inner.get("type") != "message":
            return stats

        channel_id = inner.get("channel")
        if channel_id not in settings.slack_decision_channel_id_list:
            return stats

        async with db_session() as session:
            await self._ingest_message(session, channel_id, inner, stats)

        logger.info("slack.event.processed", channel=channel_id, **stats.__dict__)
        return stats
