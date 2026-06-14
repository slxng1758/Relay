"""
GitHub connector.

Syncs an organization's repositories (`Repository`), members (`Person`, keyed by
GitHub login), and open issues/PRs (`Task`, linked to their repo via a
`RELATED_TO` edge). PyGithub is synchronous, so all SDK calls run in a thread.
Also handles `issues`, `pull_request`, and `push` webhook events.
"""
from __future__ import annotations

import asyncio
from typing import Any

from github import Github
from github.Repository import Repository as GhRepository
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import NodeType, Person, Repository, SourceSystem, Task
from app.ingestion.base_connector import BaseConnector, IngestionStats
from app.ingestion.processors.embedding_processor import embed_node

logger = get_logger(__name__)


class GitHubConnector(BaseConnector):
    source_system = SourceSystem.GITHUB

    def __init__(self) -> None:
        self._client = Github(settings.github_token)

    async def sync(self, full_sync: bool = False) -> IngestionStats:
        stats = IngestionStats()
        org = await asyncio.to_thread(self._client.get_organization, settings.github_org)

        await self._sync_members(org, stats)
        await self._sync_repos(org, stats, full_sync=full_sync)

        logger.info("github.sync.complete", **stats.__dict__)
        return stats

    # ── Members ──────────────────────────────────────────────────────────────

    async def _sync_members(self, org: Any, stats: IngestionStats) -> None:
        members = await asyncio.to_thread(lambda: list(org.get_members()))

        async with db_session() as session:
            for member in members:
                _, created = await self.upsert_node(
                    session,
                    Person,
                    external_id=str(member.id),
                    display_name=member.name or member.login,
                    github_login=member.login,
                )
                stats.nodes_created += int(created)
                stats.nodes_updated += int(not created)

    # ── Repositories & issues/PRs ───────────────────────────────────────────

    async def _sync_repos(self, org: Any, stats: IngestionStats, full_sync: bool) -> None:
        repos = await asyncio.to_thread(lambda: list(org.get_repos()))

        async with db_session() as session:
            for repo in repos:
                repository, created = await self.upsert_node(
                    session,
                    Repository,
                    external_id=str(repo.id),
                    full_name=repo.full_name,
                    description=repo.description,
                    default_branch=repo.default_branch,
                    language=repo.language,
                )
                stats.nodes_created += int(created)
                stats.nodes_updated += int(not created)

                await self._sync_issues(session, repo, repository, stats, full_sync)

    async def _sync_issues(
        self,
        session: AsyncSession,
        repo: GhRepository,
        repository: Any,
        stats: IngestionStats,
        full_sync: bool,
    ) -> None:
        state = "all" if full_sync else "open"
        issues = await asyncio.to_thread(lambda: list(repo.get_issues(state=state)))

        for issue in issues:
            # PyGithub returns PRs as issues too; both map to Task with a stable key.
            external_id = f"pr-{issue.id}" if issue.pull_request else str(issue.id)

            assignee_id = None
            if issue.assignee:
                assignee = await self.get_node(session, Person, str(issue.assignee.id))
                assignee_id = assignee.id if assignee else None

            task, created = await self.upsert_node(
                session,
                Task,
                external_id=external_id,
                title=issue.title,
                description=issue.body,
                status="open" if issue.state == "open" else "done",
                assignee_id=assignee_id,
                source_url=issue.html_url,
            )
            stats.nodes_created += int(created)
            stats.nodes_updated += int(not created)

            _, edge_created = await self.upsert_edge(
                session,
                source_id=task.id,
                source_type=NodeType.TASK,
                target_id=repository.id,
                target_type=NodeType.REPOSITORY,
                edge_type=EdgeType.RELATED_TO,
            )
            stats.edges_created += int(edge_created)

            await embed_node(session, task.id, NodeType.TASK, f"{issue.title}\n{issue.body or ''}")

    # ── Webhooks ─────────────────────────────────────────────────────────────

    async def handle_event(self, event_type: str, payload: dict[str, Any]) -> IngestionStats:
        stats = IngestionStats()

        if event_type == "issues":
            await self._handle_issue_event(payload, stats)
        elif event_type == "pull_request":
            await self._handle_pull_request_event(payload, stats)
        elif event_type == "push":
            await self._handle_push_event(payload, stats)

        logger.info("github.event.processed", event_type=event_type, **stats.__dict__)
        return stats

    async def _handle_issue_event(self, payload: dict[str, Any], stats: IngestionStats) -> None:
        issue = payload["issue"]
        repo_payload = payload["repository"]

        async with db_session() as session:
            repository = await self.get_node(session, Repository, str(repo_payload["id"]))

            assignee_id = None
            if issue.get("assignee"):
                assignee = await self.get_node(session, Person, str(issue["assignee"]["id"]))
                assignee_id = assignee.id if assignee else None

            task, created = await self.upsert_node(
                session,
                Task,
                external_id=str(issue["id"]),
                title=issue["title"],
                description=issue.get("body"),
                status="open" if issue["state"] == "open" else "done",
                assignee_id=assignee_id,
                source_url=issue["html_url"],
            )
            stats.nodes_created += int(created)
            stats.nodes_updated += int(not created)

            if repository:
                _, edge_created = await self.upsert_edge(
                    session,
                    source_id=task.id,
                    source_type=NodeType.TASK,
                    target_id=repository.id,
                    target_type=NodeType.REPOSITORY,
                    edge_type=EdgeType.RELATED_TO,
                )
                stats.edges_created += int(edge_created)

            await embed_node(
                session, task.id, NodeType.TASK, f"{issue['title']}\n{issue.get('body') or ''}"
            )

    async def _handle_pull_request_event(
        self, payload: dict[str, Any], stats: IngestionStats
    ) -> None:
        pr = payload["pull_request"]
        repo_payload = payload["repository"]

        async with db_session() as session:
            repository = await self.get_node(session, Repository, str(repo_payload["id"]))

            assignee_id = None
            if pr.get("assignee"):
                assignee = await self.get_node(session, Person, str(pr["assignee"]["id"]))
                assignee_id = assignee.id if assignee else None

            task, created = await self.upsert_node(
                session,
                Task,
                external_id=f"pr-{pr['id']}",
                title=pr["title"],
                description=pr.get("body"),
                status="open" if pr["state"] == "open" else "done",
                assignee_id=assignee_id,
                source_url=pr["html_url"],
            )
            stats.nodes_created += int(created)
            stats.nodes_updated += int(not created)

            if repository:
                _, edge_created = await self.upsert_edge(
                    session,
                    source_id=task.id,
                    source_type=NodeType.TASK,
                    target_id=repository.id,
                    target_type=NodeType.REPOSITORY,
                    edge_type=EdgeType.RELATED_TO,
                )
                stats.edges_created += int(edge_created)

            await embed_node(
                session, task.id, NodeType.TASK, f"{pr['title']}\n{pr.get('body') or ''}"
            )

    async def _handle_push_event(self, payload: dict[str, Any], stats: IngestionStats) -> None:
        """Refresh the repository's default branch on push (cheap activity signal)."""
        repo_payload = payload["repository"]

        async with db_session() as session:
            repository = await self.get_node(session, Repository, str(repo_payload["id"]))
            if repository:
                repository.default_branch = repo_payload.get(
                    "default_branch", repository.default_branch
                )
                await session.flush()
                stats.nodes_updated += 1
