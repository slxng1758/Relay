"""
Seed the database with sample dev data: two teams, their members, the services
and repo they own, a decision, in-flight tasks, and a runbook, connected by
edges. Run via `opsgraph seed` (see `app/cli.py`).

Embeddings are intentionally not generated here (would require downloading the
sentence-transformer model); `/api/graph/search` falls back to keyword search
over this data without them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base, db_session
from app.core.logging import configure_logging, get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import (
    Decision,
    Document,
    NodeType,
    Person,
    Repository,
    Service,
    SourceSystem,
    Task,
    Team,
)
from app.db.repositories.base import BaseRepository
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


async def _upsert(session: AsyncSession, model: type[Base], external_id: str, **fields: Any) -> Any:
    repo: BaseRepository[Any] = BaseRepository(session)
    repo.model = model
    instance, _ = await repo.upsert_by_external_id(external_id, SourceSystem.MANUAL, **fields)
    return instance


async def main() -> None:
    configure_logging()
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        edge_repo = EdgeRepository(session)

        platform_team = await _upsert(
            session,
            Team,
            "seed-team-platform",
            name="Platform",
            slack_channel_id="C0PLATFORM",
            description="Owns core infrastructure services.",
        )
        growth_team = await _upsert(
            session,
            Team,
            "seed-team-growth",
            name="Growth",
            slack_channel_id="C0GROWTH",
            description="Owns onboarding and activation.",
        )

        alice = await _upsert(
            session,
            Person,
            "seed-person-alice",
            display_name="Alice Chen",
            email="alice@example.com",
            slack_user_id="U0ALICE",
            github_login="alice-chen",
            team_id=platform_team.id,
        )
        bob = await _upsert(
            session,
            Person,
            "seed-person-bob",
            display_name="Bob Martinez",
            email="bob@example.com",
            slack_user_id="U0BOB",
            github_login="bobm",
            team_id=platform_team.id,
        )
        carla = await _upsert(
            session,
            Person,
            "seed-person-carla",
            display_name="Carla Singh",
            email="carla@example.com",
            slack_user_id="U0CARLA",
            github_login="carla-singh",
            team_id=growth_team.id,
        )

        auth_service = await _upsert(
            session,
            Service,
            "seed-service-auth",
            name="auth-service",
            description="Handles authentication and session management.",
            owner_team_id=platform_team.id,
            repo_url="https://github.com/example/auth-service",
            status="active",
        )
        onboarding_service = await _upsert(
            session,
            Service,
            "seed-service-onboarding",
            name="onboarding-service",
            description="Drives new-user onboarding flows.",
            owner_team_id=growth_team.id,
            repo_url="https://github.com/example/onboarding-service",
            status="active",
        )

        auth_repo = await _upsert(
            session,
            Repository,
            "seed-repo-auth-service",
            full_name="example/auth-service",
            description="Auth service source.",
            default_branch="main",
            language="Python",
            owner_team_id=platform_team.id,
        )

        migration_decision = await _upsert(
            session,
            Decision,
            "seed-decision-jwt-migration",
            title="Migrate session auth to JWT",
            summary=(
                "Move from server-side sessions to stateless JWTs to support "
                "horizontal scaling of auth-service."
            ),
            rationale="Server-side sessions don't scale across regions.",
            status="open",
            decided_at=now - timedelta(days=10),
            decided_by_id=alice.id,
            source_url="https://example.slack.com/archives/C0PLATFORM/p1700000000",
        )

        onboarding_task = await _upsert(
            session,
            Task,
            "seed-task-onboarding-redesign",
            title="Redesign onboarding checklist",
            description="Simplify the first-run checklist based on activation funnel data.",
            status="in_progress",
            priority="high",
            assignee_id=carla.id,
            team_id=growth_team.id,
            due_date=now + timedelta(days=7),
            jira_key="GROW-123",
        )
        jwt_task = await _upsert(
            session,
            Task,
            "seed-task-jwt-rollout",
            title="Roll out JWT auth to staging",
            description="Implementation follow-up for the JWT migration decision.",
            status="open",
            priority="high",
            assignee_id=bob.id,
            team_id=platform_team.id,
            due_date=now + timedelta(days=14),
            jira_key="PLAT-456",
        )

        runbook = await _upsert(
            session,
            Document,
            "seed-doc-auth-runbook",
            title="RUNBOOK: auth-service incident response",
            doc_type="runbook",
            doc_url="https://docs.example.com/auth-runbook",
            owner_id=alice.id,
        )

        edges: list[dict[str, Any]] = [
            dict(source_id=alice.id, source_type=NodeType.PERSON,
                 target_id=platform_team.id, target_type=NodeType.TEAM, edge_type=EdgeType.MEMBER_OF),
            dict(source_id=bob.id, source_type=NodeType.PERSON,
                 target_id=platform_team.id, target_type=NodeType.TEAM, edge_type=EdgeType.MEMBER_OF),
            dict(source_id=carla.id, source_type=NodeType.PERSON,
                 target_id=growth_team.id, target_type=NodeType.TEAM, edge_type=EdgeType.MEMBER_OF),
            dict(source_id=platform_team.id, source_type=NodeType.TEAM,
                 target_id=auth_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.OWNS),
            dict(source_id=growth_team.id, source_type=NodeType.TEAM,
                 target_id=onboarding_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.OWNS),
            dict(source_id=alice.id, source_type=NodeType.PERSON,
                 target_id=auth_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.MAINTAINS),
            dict(source_id=onboarding_service.id, source_type=NodeType.SERVICE,
                 target_id=auth_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.DEPENDS_ON),
            dict(source_id=auth_repo.id, source_type=NodeType.REPOSITORY,
                 target_id=auth_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.RELATED_TO),
            dict(source_id=alice.id, source_type=NodeType.PERSON,
                 target_id=migration_decision.id, target_type=NodeType.DECISION, edge_type=EdgeType.AUTHORED),
            dict(source_id=migration_decision.id, source_type=NodeType.DECISION,
                 target_id=jwt_task.id, target_type=NodeType.TASK, edge_type=EdgeType.INFORMED_BY),
            dict(source_id=runbook.id, source_type=NodeType.DOCUMENT,
                 target_id=auth_service.id, target_type=NodeType.SERVICE, edge_type=EdgeType.DOCUMENTS),
        ]
        for edge in edges:
            await edge_repo.get_or_create_edge(**edge)

    logger.info("seed.complete", onboarding_task_id=str(onboarding_task.id))


if __name__ == "__main__":
    asyncio.run(main())
