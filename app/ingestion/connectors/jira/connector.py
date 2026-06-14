"""
Jira connector.

JQL-searches issues (optionally scoped to `settings.jira_project_keys`) and
upserts them as `Task` nodes, including the assignee as a `Person` keyed by
their Jira account ID. The `jira` library is synchronous, so all SDK calls run
in a thread.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from jira import JIRA
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.db.models.nodes import NodeType, Person, SourceSystem, Task
from app.ingestion.base_connector import BaseConnector, IngestionStats
from app.ingestion.processors.embedding_processor import embed_node

logger = get_logger(__name__)

_PAGE_SIZE = 50

_STATUS_MAP = {
    "to do": "open",
    "open": "open",
    "in progress": "in_progress",
    "in review": "in_progress",
    "done": "done",
    "closed": "done",
}


class JiraConnector(BaseConnector):
    source_system = SourceSystem.JIRA

    def __init__(self) -> None:
        self._client = JIRA(
            server=settings.jira_server,
            basic_auth=(settings.jira_email, settings.jira_api_token),
        )

    async def sync(self, full_sync: bool = False) -> IngestionStats:
        stats = IngestionStats()
        jql = self._build_jql(full_sync)

        start_at = 0
        async with db_session() as session:
            while True:
                issues = await asyncio.to_thread(
                    self._client.search_issues, jql, startAt=start_at, maxResults=_PAGE_SIZE
                )
                if not issues:
                    break

                for issue in issues:
                    await self._ingest_issue(session, issue, stats)

                start_at += len(issues)
                if len(issues) < _PAGE_SIZE:
                    break

        logger.info("jira.sync.complete", **stats.__dict__)
        return stats

    def _build_jql(self, full_sync: bool) -> str:
        clauses = []

        project_keys = settings.jira_project_key_list
        if project_keys:
            clauses.append(f"project in ({', '.join(project_keys)})")

        if not full_sync:
            clauses.append("updated >= -1d")

        return " AND ".join(clauses) + " order by updated DESC" if clauses else "order by updated DESC"

    async def _ingest_issue(self, session: AsyncSession, issue: Any, stats: IngestionStats) -> None:
        fields = issue.fields

        assignee_id = None
        if fields.assignee:
            person, created = await self.upsert_node(
                session,
                Person,
                external_id=fields.assignee.accountId,
                display_name=fields.assignee.displayName,
                email=getattr(fields.assignee, "emailAddress", None),
                jira_account_id=fields.assignee.accountId,
            )
            stats.nodes_created += int(created)
            stats.nodes_updated += int(not created)
            assignee_id = person.id

        due_date = None
        if getattr(fields, "duedate", None):
            due_date = datetime.fromisoformat(fields.duedate).replace(tzinfo=timezone.utc)

        task, created = await self.upsert_node(
            session,
            Task,
            external_id=issue.key,
            title=fields.summary,
            description=getattr(fields, "description", None),
            status=_STATUS_MAP.get(fields.status.name.lower(), "open"),
            priority=getattr(fields.priority, "name", None) if fields.priority else None,
            assignee_id=assignee_id,
            due_date=due_date,
            source_url=f"{settings.jira_server}/browse/{issue.key}",
            jira_key=issue.key,
        )
        stats.nodes_created += int(created)
        stats.nodes_updated += int(not created)

        description = getattr(fields, "description", None) or ""
        await embed_node(session, task.id, NodeType.TASK, f"{fields.summary}\n{description}")
